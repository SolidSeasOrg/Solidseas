"""Finding the documents an Alibre Design assembly places (provisional,
``docs/formats/alibre.md``).

An assembly names each document by its GUID, its version and the repository
path it had where it was saved; the stored name is often not the file's name on
disk. Resolution therefore never opens a stored path. It walks the assembly's
own folder (then each further root the caller gives) with
:class:`solidseas.walk.Walk`, which follows no link, never opens a cloud
placeholder and skips lock files, collects the Alibre files there, and reads
only the ``VERSION`` stream of each, opened read-only within its folder:

1. a file whose document GUID is the one referenced is found (``found_by``
   ``document_guid``); among several, the one in the assembly's own folder, then
   the shortest relative path, then the version referenced, with the warning
   ``component_ambiguous``; a newer version than the one referenced is used and
   warned ``component_newer``, an older one ``component_older``;
2. failing that, a file in the assembly's folder named as the stored name with
   an Alibre extension is used only when its own GUID could not be read
   (``found_by`` ``name``, warning ``component_found_by_name``): one whose GUID
   differs is another document;
3. otherwise the document is ``not_found``.

A file with several names (a hard link) is no candidate when the assembly was
opened with ``refuse_hard_links``: another of its names may lie outside the
folder. The walk keeps ``resolve_depth``, ``resolve_examined`` and
``resolve_seconds``, and at most ``resolve_candidates`` files are read; a bound
reached is reported as ``truncated``. GUIDs read are cached by path, size and modification time for
the life of one :class:`Resolver`.
"""

import os
import time
from dataclasses import dataclass, field

from ...errors import ReaderWarning, SolidSeasError
from ..limits import Limits
from ..solidworks._io import open_readonly

EXTENSIONS = (".ad_prt", ".ad_asm", ".ad_smp")


@dataclass(frozen=True)
class Candidate:
    path: str
    root: str  # the folder it was found under
    rel: str  # relative to that folder, "/"-separated
    in_own_folder: bool
    size: int | None
    mtime_ns: int | None


@dataclass
class Resolution:
    """Where one referenced document was found: ``status`` ``found`` or ``not_found``,
    ``path`` (absolute) and ``within`` (the folder to open it within), ``found_by``,
    ``version`` the file's, and warnings."""

    status: str
    path: str | None = None
    within: str | None = None
    rel: str | None = None
    found_by: str | None = None
    version: int | None = None
    warnings: list[ReaderWarning] = field(default_factory=list)


def read_guid(
    path: str, within: str, limits: Limits, *, refuse_hard_links: bool = False
) -> tuple[str, int | None] | None:
    """The document GUID and version in the ``VERSION`` stream of the file at ``path``,
    opened read-only within ``within`` and read no further; None when it is not an
    Alibre file, cannot be read, or has several names and ``refuse_hard_links``."""
    from ..solidworks.ole import OleContainer
    from .identity import read_version

    try:
        fh = open_readonly(path, within=within)
    except (OSError, SolidSeasError):
        return None
    try:
        st = os.fstat(fh.fileno())
        if refuse_hard_links and st.st_nlink > 1:
            return None
        size = st.st_size
        head = fh.read(8)
        if head != bytes.fromhex("d0cf11e0a1b11ae1"):
            return None
        ole = OleContainer(fh, size, None, True, 0)
        try:
            names = {s.name: s.size for s in ole.streams()}
            if (
                len(names) > limits.ole_streams
                or names.get("VERSION", limits.alibre_small_stream_bytes + 1)
                > limits.alibre_small_stream_bytes
            ):
                return None
            ident = read_version(ole.read_raw("VERSION", max_bytes=limits.alibre_small_stream_bytes), limits)
            return ident.guid, ident.version
        finally:
            ole.close()
    except (OSError, SolidSeasError, ValueError, IndexError):
        return None
    finally:
        fh.close()


def _several_names(path: str) -> bool:
    try:
        return os.lstat(path).st_nlink > 1
    except OSError:
        return False


class Resolver:
    """Resolution for one assembly (and the sub-assemblies its scene opens): ``folder``
    the assembly's folder (None for one opened from bytes), ``roots`` further folders."""

    def __init__(
        self,
        folder: str | None,
        roots: tuple[str, ...],
        limits: Limits,
        *,
        exclude: str | None = None,
        refuse_hard_links: bool = False,
    ) -> None:
        self.folder = os.path.abspath(folder) if folder else None
        self.roots = tuple(os.path.abspath(r) for r in roots if r)
        self.limits = limits
        self.exclude = os.path.normcase(os.path.abspath(exclude)) if exclude else None
        self.refuse_hard_links = refuse_hard_links
        self._refused: set[str] = set()  # candidates with several names, when those are refused
        self.truncated = False
        self._candidates: list[Candidate] | None = None
        self._guids: dict[tuple[str, int | None, int | None], tuple[str, int | None] | None] = {}
        self._read = 0
        self._deadline: float | None = None

    def candidates(self) -> list[Candidate]:
        """Every Alibre file under the folder and the roots, found by the walk."""
        if self._candidates is not None:
            return self._candidates
        from ...walk import Walk

        lim = self.limits
        self._deadline = time.monotonic() + lim.resolve_seconds
        out: list[Candidate] = []
        seen: set[str] = set()
        folders = ([self.folder] if self.folder else []) + [r for r in self.roots if r != self.folder]
        for base in folders:
            try:
                walk = Walk(
                    base,
                    max_depth=lim.resolve_depth,
                    max_examined=lim.resolve_examined,
                    deadline=self._deadline,
                )
                for e in walk:
                    if e.kind != "file" or os.path.splitext(e.name)[1].lower() not in EXTENSIONS:
                        continue
                    key = os.path.normcase(os.path.abspath(e.path))
                    if key in seen or key == self.exclude:
                        continue
                    seen.add(key)
                    out.append(
                        Candidate(
                            e.path, base, e.rel, base == self.folder and e.depth == 1, e.size, e.mtime_ns
                        )
                    )
                if walk.stats.truncated:
                    self.truncated = True
            except OSError:
                continue
        self._candidates = out
        return out

    def guid_of(self, c: Candidate) -> tuple[str, int | None] | None:
        key = (os.path.normcase(c.path), c.size, c.mtime_ns)
        if key in self._guids:
            return self._guids[key]
        if self._read >= self.limits.resolve_candidates or (
            self._deadline is not None and time.monotonic() > self._deadline
        ):
            self.truncated = True
            return None
        self._read += 1
        got = read_guid(c.path, c.root, self.limits, refuse_hard_links=self.refuse_hard_links)
        if got is None and self.refuse_hard_links and _several_names(c.path):
            self._refused.add(key[0])
        self._guids[key] = got
        return got

    def resolve(self, guid: str, version: int | None, stored_name: str | None) -> Resolution:
        """Where the document ``guid`` is (see the module notes)."""
        matches: list[tuple[Candidate, int | None]] = []
        unreadable_named: list[Candidate] = []
        want = (stored_name or "").casefold()
        for c in self.candidates():
            got = self.guid_of(c)
            if got is None:
                stem = os.path.splitext(os.path.basename(c.path))[0].casefold()
                refused = os.path.normcase(c.path) in self._refused
                if want and stem == want and c.in_own_folder and not refused:
                    unreadable_named.append(c)
                continue
            if got[0] == guid:
                matches.append((c, got[1]))
        warnings: list[ReaderWarning] = []
        if matches:
            if len(matches) > 1:
                warnings.append(
                    ReaderWarning(
                        "component_ambiguous",
                        f"{len(matches)} files hold the same component document; the nearest was used",
                    )
                )
            matches.sort(
                key=lambda m: (
                    not m[0].in_own_folder,
                    m[0].rel.count("/"),
                    len(m[0].rel),
                    m[1] != version,
                    m[0].rel,
                )
            )
            c, ver = matches[0]
            if version is not None and ver is not None:
                if ver > version:
                    warnings.append(
                        ReaderWarning(
                            "component_newer",
                            "a component file is a newer version than the assembly references",
                        )
                    )
                elif ver < version:
                    warnings.append(
                        ReaderWarning(
                            "component_older",
                            "a component file is an older version than the assembly references",
                        )
                    )
            return Resolution("found", c.path, c.root, c.rel, "document_guid", ver, warnings)
        if unreadable_named:
            c = unreadable_named[0]
            warnings.append(
                ReaderWarning(
                    "component_found_by_name",
                    "a component was found by its stored name, as its own identity could not be read",
                )
            )
            return Resolution("found", c.path, c.root, c.rel, "name", None, warnings)
        return Resolution("not_found", warnings=warnings)


__all__ = ["EXTENSIONS", "Candidate", "Resolution", "Resolver", "read_guid"]
