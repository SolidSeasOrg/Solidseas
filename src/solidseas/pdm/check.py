"""Whether a project holds every file its documents reference (``docs/PDM.md`` 5).

:func:`check_project` reads every SOLIDWORKS document in a project folder and
resolves each of its references with SolidSeas' resolver
(:func:`solidseas.resolve.resolve_references`) in the order the SOLIDWORKS help
topic "Search Routine for Referenced Documents" gives (``search="documented"``):
the document's own folder (the bare name, then the stored folder's tails, shortest
first), then each folder above it under tails of one or more components, then the
stored path. There is no step for the file's old position relative to the document.
The climb goes on past the project folder, to the filesystem root
(``search_above_roots``), because that is where a reference leaks into a
neighbouring project. The first file the search reaches decides: when it was made
as another document, the reference is ``different_document`` and the search does
not go on past it. A file of that name that the search does not reach is never
taken as found: the reference is ``missing`` (or ``toolbox``), and the file is
listed in the finding's ``candidates``. The library folder, when one is given, is a
second root, so a copy there is listed too.

Each reference gets one :class:`Finding`, with one of :data:`RESULTS`:

* ``ok``: found inside the project;
* ``outside``: found only outside it, in the library, another project (a folder
  beside the project) or elsewhere;
* ``needs_confirmation``: found only as the bare name in a folder above the
  document, a place the help topic does not say SOLIDWORKS searches; confirm by
  opening the assembly in SOLIDWORKS;
* ``toolbox``: Toolbox hardware not found inside the project;
* ``inside_parent``: a virtual component, or an imported one stored inside its
  assembly (an imported one whose stored name has no folder is looked for on disk
  first, and is ``inside_parent`` only when no file of that name that could be it
  is found);
* ``missing``: not found where SOLIDWORKS looks (a file of that name elsewhere in
  the project or the library is in ``candidates``);
* ``different_document``: the first file the search reaches by that name is
  another document (its stored creation time differs);
* ``ambiguous``: several files could be it, and none could be chosen.

:func:`plan_copies` lists the copies that would make the project self-contained.
It plans to closure: a planned copy that is a document has its own references
searched for from its destination, over the real files and the copies planned so
far, and what it needs is planned beside it, round after round. It plans only:
nothing here writes a file.

Nothing here has been tried in SOLIDWORKS itself: the order is the help topic's.

A sub-assembly's own components are checked when that sub-assembly is: a
reference the top document stores only for a file inside a sub-assembly is left
out. The check does not follow a sub-assembly outside the project; the copy plan
does, from where its copy will be.
"""

import filecmp
import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from ..errors import SolidSeasError
from ..formats.solidworks import open_document
from ..resolve import IndexCache, ResolutionInput, resolve_references
from ..resolve.core import DEFAULT_MAX_EXAMINED, POSITIONAL_RULES
from ..resolve.gateway import Gateway
from ..resolve.identity import Identity, own_identity
from ..resolve.index import FolderIndex
from ..resolve.names import DOCUMENT_EXTENSIONS, fold, parse_stored
from ..roots import Root, Roots
from ..walk import Walk

RESULTS = (
    "ok",
    "outside",
    "needs_confirmation",
    "toolbox",
    "inside_parent",
    "missing",
    "different_document",
    "ambiguous",
)
PLACES = ("project", "library", "other_project", "elsewhere")
UNPLACED = ("missing", "different_document", "ambiguous", "unreadable", "round_limit")
# How many rounds a copy plan follows copies' own references before it stops.
MAX_ROUNDS = 10
# The rules that follow SOLIDWORKS' own search (the name index is SolidSeas' own).
SEARCH_RULES = frozenset(("embedded", *POSITIONAL_RULES))
_INSIDE = ("embedded", "embedded_in_subassembly", "inside_parent")
_NAME_RULES = ("name_index", "name_index_suffix")
_TOOLBOX_FOLDERS = ("SOLIDWORKS DATA", "TOOLBOX")
_PROJECT_FOLDER = ".solidseas"


@dataclass(frozen=True)
class Finding:
    """One reference of one document in the project.

    ``document`` is the referring document and ``key`` the reference's file key in it.
    ``relation`` is a part's relation to the file (``base_part``, ``mirrored_part``,
    ``in_context``, ``import_source`` or ``external``), None for an assembly's or a
    drawing's. ``found`` is the file the search found, or None. ``place`` says where it
    is (:data:`PLACES`), and ``found_in`` the library folder, the other project's
    folder, or for ``elsewhere`` the file's own folder. ``status``, ``rule``,
    ``identity`` and ``warnings`` are the resolver's. ``searched`` is True when one of
    SOLIDWORKS' own search rules found the file, False when only the bare name in a
    folder above the document did (rule ``bare_name_above``). ``candidates`` are, for
    a reference not found, the files of that name elsewhere in the project or the
    library, which SOLIDWORKS' search does not reach (none made as another
    document)."""

    document: Path
    key: str
    stored_path: str | None
    file_name: str | None
    relation: str | None
    result: str
    found: Path | None
    place: str | None
    found_in: Path | None
    status: str
    rule: str | None
    identity: str
    searched: bool
    toolbox: bool
    warnings: tuple[str, ...] = ()
    candidates: tuple[Path, ...] = ()


@dataclass(frozen=True)
class CheckResult:
    """Every reference of every document in ``project``. ``unreadable`` lists the
    documents that could not be read, with the error's class name."""

    project: Path
    library: Path | None
    copy_toolbox: bool
    documents: int
    findings: tuple[Finding, ...]
    unreadable: tuple[tuple[Path, str], ...] = ()

    def counts(self) -> dict[str, int]:
        """How many findings have each of :data:`RESULTS`, and ``toolbox_not_found``: how
        many of the ``toolbox`` ones were found nowhere (counted in ``toolbox`` too)."""
        out = dict.fromkeys(RESULTS, 0)
        for f in self.findings:
            out[f.result] = out.get(f.result, 0) + 1
        out["toolbox_not_found"] = sum(1 for f in self.findings if f.result == "toolbox" and f.found is None)
        return out

    def problems(self) -> list[Finding]:
        """The findings that keep the project from being self-contained: every one but
        ``ok`` and ``inside_parent``, and but ``toolbox`` when Toolbox parts need no copy."""
        fine = {"ok", "inside_parent"} | (set() if self.copy_toolbox else {"toolbox"})
        return [f for f in self.findings if f.result not in fine]

    @property
    def self_contained(self) -> bool:
        return not self.problems() and not self.unreadable


@dataclass(frozen=True)
class PlannedCopy:
    """A file to copy into the project: from ``source`` to ``destination``, for the
    documents in ``referenced_by``. ``place`` is where the source is (:data:`PLACES`).
    ``round`` is the round of the plan that needed it: 1 for the project's own
    documents, 2 and on for the references of copies planned in the round before, which
    are then the ``referenced_by``, at their destinations."""

    source: Path
    destination: Path
    referenced_by: tuple[Path, ...]
    place: str | None
    round: int = 1


@dataclass(frozen=True)
class CopyConflict:
    """A copy that cannot be made: ``destination`` already holds another file of that
    name, or another planned copy takes it. ``round`` as for :class:`PlannedCopy`."""

    source: Path
    destination: Path
    referenced_by: tuple[Path, ...]
    reason: str
    round: int = 1


@dataclass(frozen=True)
class Unplaced:
    """A reference of a planned copy that no copy places. ``document`` is the planned
    copy, at its destination, and ``source`` the file it is copied from. ``name`` is the
    referenced file's name. ``reason`` is one of :data:`UNPLACED`: ``missing``,
    ``different_document`` and ``ambiguous`` are the check's results for that reference
    from the copy's destination, ``unreadable`` means the source could not be read
    (``error`` names the exception, and ``name`` is None), and ``round_limit`` means
    the copy ``found`` would be needed in a round past the limit. ``round`` is the
    round in which a copy would have placed it."""

    document: Path
    source: Path
    name: str | None
    reason: str
    round: int
    found: Path | None = None
    error: str | None = None


@dataclass(frozen=True)
class CopyPlan:
    """The copies :func:`plan_copies` would make, the ones it cannot, the files already
    in place (same content at the destination: no copy needed), the references of
    planned copies that no copy places, and how many rounds the plan took."""

    copies: tuple[PlannedCopy, ...]
    conflicts: tuple[CopyConflict, ...] = ()
    present: tuple[PlannedCopy, ...] = field(default=())
    unplaced: tuple[Unplaced, ...] = ()
    rounds: int = 1


# --------------------------------------------------------------------------- paths
def _key(path: Path | str) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _inside(path: Path | str, folder: Path | str) -> bool:
    p, f = _key(path), _key(folder)
    return p == f or p.startswith(f.rstrip(os.sep) + os.sep)


def is_toolbox_path(path: str | None) -> bool:
    """Whether a stored or found path lies in a Toolbox folder: a folder named
    ``SOLIDWORKS Data`` (also ``SOLIDWORKS Data (2)`` and the like, as the installer
    names a second one) or ``Toolbox``, compared case-insensitively."""
    if not path:
        return False
    parts = path.replace("/", "\\").split("\\")[:-1]
    for part in parts:
        name = fold(part.strip())
        if name in _TOOLBOX_FOLDERS:
            return True
        if name.startswith("SOLIDWORKS DATA (") and name.endswith(")"):
            return True
    return False


def _documents(project: Path) -> Iterator[Path]:
    """The SOLIDWORKS documents below ``project``, as the shared walker finds them: no
    link is followed, no cloud placeholder or lock file is listed, and the project's
    own ``.solidseas`` folder is left out."""
    for e in Walk(project, exclude=[project / _PROJECT_FOLDER]):
        if e.kind == "file" and not e.is_dir and e.name.lower().endswith(DOCUMENT_EXTENSIONS):
            yield Path(e.path)


def _place(found: Path, project: Path, library: Path | None) -> tuple[str, Path]:
    if _inside(found, project):
        return "project", project
    if library is not None and _inside(found, library):
        return "library", library
    parent = project.parent
    if parent != project and _inside(found, parent):
        rel = Path(os.path.relpath(found, parent))
        if len(rel.parts) > 1:  # in a folder beside the project, not beside it itself
            return "other_project", parent / rel.parts[0]
    return "elsewhere", found.parent


# --------------------------------------------------------------------------- the check
def _finding(document: Path, f, r, project: Path, library: Path | None) -> Finding:
    found = Path(r.match.host_path) if r.match is not None else None
    candidates: tuple[Path, ...] = ()
    if found is None and r.status not in _INSIDE:
        candidates = tuple(
            Path(c.location.host_path)
            for c in r.candidates
            if c.found_by in _NAME_RULES and c.identity != "differ"
        )
    seen = (found, *candidates) if found is not None else candidates
    toolbox = is_toolbox_path(f.stored_path) or any(is_toolbox_path(str(p)) for p in seen)
    place = found_in = None
    if found is not None:
        place, found_in = _place(found, project, library)
    if r.status in _INSIDE:
        result = "inside_parent"
    elif r.status == "ambiguous":
        result = "ambiguous"
    elif found is None:
        result = "toolbox" if toolbox else "missing"
    elif r.identity == "differ":
        result = "different_document"
    elif r.rule == "bare_name_above" and (place == "project" or not toolbox):
        result = "needs_confirmation"
    elif place == "project":
        result = "ok"
    else:
        result = "toolbox" if toolbox else "outside"
    return Finding(
        document=document,
        key=f.key,
        stored_path=f.stored_path,
        file_name=parse_stored(f.stored_path).name if f.stored_path else None,
        relation=getattr(f, "relation", None),
        result=result,
        found=found,
        place=place,
        found_in=found_in,
        status=r.status,
        rule=r.rule,
        identity=r.identity,
        searched=r.rule in SEARCH_RULES,
        toolbox=toolbox,
        warnings=tuple(w.code for w in r.warnings),
        candidates=candidates,
    )


def _roots(project: Path, lib: Path | None) -> list[Root]:
    roots = [Root("project", str(project))]
    if lib is not None and not _inside(lib, project):
        roots.append(Root("library", str(lib), role="library"))
    return roots


def _check_document(
    read: Path,
    at: Path,
    project: Path,
    lib: Path | None,
    roots: list[Root],
    cache: IndexCache,
    gateway: Gateway | None = None,
) -> list[Finding]:
    """The findings of the document read from ``read``, its references searched for as
    if it were at ``at`` (the same path, except for a planned copy). Raises
    ``OSError`` or a :class:`SolidSeasError` when it cannot be read."""
    within = project if _inside(read, project) else read.parent
    with open_document(read, hold_open=True, within=within) as doc:
        inp = ResolutionInput.from_document(doc)
        files = doc.reference_set().files
    if not inp.files:
        return []
    if at != read:
        inp = replace(inp, path=str(at))
    resolution = resolve_references(
        inp,
        Roots(roots),
        cache=cache,
        gateway=gateway,
        allow_outside_roots=True,
        search_above_roots=True,
        skip_unavailable_roots=True,
        search="documented",
    )
    out = []
    for f in inp.files:
        if f.direct is False:  # checked when its own sub-assembly is
            continue
        r = resolution.results.get(f.key)
        if r is None:
            continue
        out.append(_finding(at, files.get(f.key, f), r, project, lib))
    return out


def check_project(project: Path, *, library: Path | None = None, copy_toolbox: bool = False) -> CheckResult:
    """Check that every reference of every SOLIDWORKS document in ``project`` resolves
    inside it (see the module notes). ``library`` is the common-parts library folder:
    a file found there is reported as ``outside`` with place ``library``.
    ``copy_toolbox`` True means Toolbox parts must be copied into the project like
    any other file; False means SOLIDWORKS loads them from the installation's own
    Toolbox folder, so a ``toolbox`` finding is no problem and needs no copy.

    Opens every document read-only and writes nothing. Raises ``FileNotFoundError``
    or ``NotADirectoryError`` for the project folder itself only; a document that
    cannot be read is listed in ``unreadable``."""
    project = Path(os.path.abspath(project))
    lib = Path(os.path.abspath(library)) if library is not None else None
    cache = IndexCache()
    findings: list[Finding] = []
    unreadable: list[tuple[Path, str]] = []
    count = 0
    for path in _documents(project):
        count += 1
        try:
            findings += _check_document(path, path, project, lib, _roots(project, lib), cache)
        except (OSError, SolidSeasError) as exc:
            unreadable.append((path, type(exc).__name__))
    return CheckResult(project, lib, copy_toolbox, count, tuple(findings), tuple(unreadable))


# --------------------------------------------------------------------------- the plan
def _needs_copy(f: Finding, copy_toolbox: bool) -> bool:
    if f.found is None:
        return False
    if f.result in ("outside", "needs_confirmation"):
        return True
    return f.result == "toolbox" and copy_toolbox


def _same_content(a: Path, b: Path) -> bool:
    try:
        return filecmp.cmp(a, b, shallow=False)
    except OSError:
        return False


class _CopyGateway(Gateway):
    """The resolver's gateway, with planned copies that do not exist yet: the identity of
    one is its source's, read from the source."""

    def __init__(self, planned: dict[str, Path]) -> None:
        super().__init__()
        self.planned = planned  # _key(destination) -> source
        self._sources: dict[str, Identity] = {}

    def _source_identity(self, source: Path) -> Identity:
        k = _key(source)
        ident = self._sources.get(k)
        if ident is None:
            try:
                with open_document(source, hold_open=True, within=source.parent) as doc:
                    ident = own_identity(doc)
            except Exception as exc:  # one unreadable source never stops the plan
                ident = Identity(None, error=type(exc).__name__)
            self._sources[k] = ident
        return ident

    def read_identities(self, requests: Sequence[tuple[str, str, bool]]) -> list[Identity]:
        out: list[Identity] = [Identity(None)] * len(requests)
        real: list[int] = []
        for i, (path, _within, _placeholder) in enumerate(requests):
            source = self.planned.get(_key(path))
            if source is not None:
                out[i] = self._source_identity(source)
            else:
                real.append(i)
        if real:
            got = super().read_identities([requests[i] for i in real])
            for i, ident in zip(real, got, strict=True):
                out[i] = ident
        return out


@dataclass
class _Copy:
    source: Path
    destination: Path
    users: list[Path]
    place: str | None
    round: int


@dataclass(frozen=True)
class _Need:
    source: Path
    destination: Path
    user: Path
    place: str | None


class _Planner:
    """The copies planned so far, and the search from where they will be."""

    def __init__(self, result: CheckResult) -> None:
        self.result = result
        self.copies: dict[str, _Copy] = {}  # _key(destination) -> the copy planned there
        self.conflicts: list[CopyConflict] = []
        self.present: list[PlannedCopy] = []
        self.unplaced: list[Unplaced] = []
        self.roots = _roots(result.project, result.library)
        self._cache = IndexCache()
        self._index: FolderIndex | None = None

    def add(self, needs: list[_Need], round_: int) -> list[_Copy]:
        """Plan ``needs``, once per source and destination; returns the copies new in this
        round. A destination never takes two sources, and an existing file is never
        written over."""
        groups: dict[tuple[str, str], tuple[_Need, list[Path]]] = {}
        for n in needs:
            _first, users = groups.setdefault((_key(n.source), _key(n.destination)), (n, []))
            if n.user not in users:
                users.append(n.user)
        new: list[_Copy] = []
        for (src_key, dest_key), (n, users) in groups.items():
            src, dest, by = n.source, n.destination, tuple(users)
            planned = self.copies.get(dest_key)
            if planned is not None:
                if _key(planned.source) == src_key:
                    planned.users += [u for u in users if u not in planned.users]
                else:
                    reason = "another planned copy has this name here"
                    self.conflicts.append(CopyConflict(src, dest, by, reason, round_))
                continue
            if os.path.lexists(dest):
                if os.path.isfile(dest) and not os.path.islink(dest) and _same_content(src, dest):
                    self.present.append(PlannedCopy(src, dest, by, n.place, round_))
                else:
                    reason = "a different file of this name is already here"
                    self.conflicts.append(CopyConflict(src, dest, by, reason, round_))
                continue
            copy = _Copy(src, dest, list(users), n.place, round_)
            self.copies[dest_key] = copy
            new.append(copy)
        return new

    def _overlay(self) -> tuple[IndexCache, tuple[str, bool]]:
        """A cache whose project index holds the planned copies as if they were made."""
        root = self.roots[0]
        if self._index is None:
            self._index = Gateway().build_index(root, max_examined=DEFAULT_MAX_EXAMINED, deadline=None)
        files = []
        for c in self.copies.values():
            try:
                st = os.stat(c.source)
                size, mtime = st.st_size, st.st_mtime_ns
            except OSError:
                size = mtime = None
            files.append(("/".join(Path(os.path.relpath(c.destination, root.path)).parts), size, mtime))
        key = (fold(root.path), root.recursive)
        cache = IndexCache()
        cache.indexes = dict(self._cache.indexes)
        cache.indexes[key] = self._index.with_files(files)
        cache.identities = self._cache.identities
        return cache, key

    def needs_of(self, copies: list[_Copy], round_: int) -> list[_Need]:
        """What ``copies`` need beside them, each read from its source and searched for
        from its destination, over the files there are and every copy planned so far.
        A reference that no copy can place is listed in ``unplaced``, with ``round_``."""
        res = self.result
        cache, key = self._overlay()
        gateway = _CopyGateway({k: c.source for k, c in self.copies.items()})
        out: list[_Need] = []
        for c in copies:
            if not c.destination.name.lower().endswith(DOCUMENT_EXTENSIONS):
                continue
            try:
                found = _check_document(
                    c.source, c.destination, res.project, res.library, self.roots, cache, gateway
                )
            except (OSError, SolidSeasError) as exc:
                self.unplaced.append(
                    Unplaced(c.destination, c.source, None, "unreadable", round_, error=type(exc).__name__)
                )
                continue
            for f in found:
                if _needs_copy(f, res.copy_toolbox) and f.found is not None:
                    other = self.copies.get(_key(f.found))  # found as a planned copy: copy its source
                    source = f.found if other is None else other.source
                    place = f.place if other is None else other.place
                    out.append(_Need(source, c.destination.parent / f.found.name, c.destination, place))
                elif f.result in ("missing", "different_document", "ambiguous") or (
                    f.result == "toolbox" and f.found is None and res.copy_toolbox
                ):
                    reason = "missing" if f.result == "toolbox" else f.result
                    self.unplaced.append(
                        Unplaced(c.destination, c.source, f.file_name or f.key, reason, round_, f.found)
                    )
        for k, index in cache.indexes.items():
            if k != key:
                self._cache.indexes.setdefault(k, index)
        return out


def plan_copies(result: CheckResult, *, max_rounds: int = MAX_ROUNDS) -> CopyPlan:
    """The copies that would make ``result``'s project self-contained, without making
    them. Each file found outside the project, each one found only by a search
    SOLIDWORKS may not make (``needs_confirmation``), and each Toolbox part when
    ``copy_toolbox``, is copied into the folder of each document referring to it,
    once per folder: the bare name in the document's own folder is the first place
    SOLIDWORKS looks, and the only folder where it tries the bare name. A destination
    that already holds a file of that name is never written over: with the same
    content the copy is listed in ``present``, otherwise in ``conflicts``.

    A copy that is a document itself (a sub-assembly, or a part with external files)
    has references of its own, which it may not find from its new folder. Each one is
    read from its source and its references searched for as if it already sat at its
    destination, over the files there are and every copy planned so far; what it needs
    is planned beside it in the next round. That repeats until a round adds nothing,
    for at most ``max_rounds`` rounds. Each copy records the round that planned it,
    and a later round's ``referenced_by`` are the planned copies that need it. What
    no copy can place is listed in ``unplaced``. Reads documents, writes nothing."""
    if max_rounds < 1:
        raise ValueError("max_rounds is at least 1")
    planner = _Planner(result)
    needs = [
        _Need(f.found, f.document.parent / f.found.name, f.document, f.place)
        for f in result.findings
        if _needs_copy(f, result.copy_toolbox) and f.found is not None
    ]
    new = planner.add(needs, 1)
    rounds = 1
    while new:
        needs = planner.needs_of(new, rounds + 1)
        if not needs:
            break
        if rounds == max_rounds:
            seen: set[tuple[str, str]] = set()
            for n in needs:
                k = (_key(n.user), _key(n.destination))
                if k not in seen:
                    seen.add(k)
                    planner.unplaced.append(
                        Unplaced(n.user, n.source, n.destination.name, "round_limit", rounds + 1, n.source)
                    )
            break
        rounds += 1
        new = planner.add(needs, rounds)
    copies = tuple(
        PlannedCopy(c.source, c.destination, tuple(c.users), c.place, c.round)
        for c in planner.copies.values()
    )
    return CopyPlan(copies, tuple(planner.conflicts), tuple(planner.present), tuple(planner.unplaced), rounds)


__all__ = [
    "MAX_ROUNDS",
    "PLACES",
    "RESULTS",
    "SEARCH_RULES",
    "UNPLACED",
    "CheckResult",
    "CopyConflict",
    "CopyPlan",
    "Finding",
    "PlannedCopy",
    "Unplaced",
    "check_project",
    "is_toolbox_path",
    "plan_copies",
]
