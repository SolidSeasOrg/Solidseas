"""Whether a project holds every file its documents reference (``docs/PDM.md`` 5).

:func:`check_project` reads every SOLIDWORKS document in a project folder and
resolves each of its references with SolidSeas' resolver
(:func:`solidseas.resolve.resolve_references`), the way SOLIDWORKS searches: from
the document's folder up. The folder probe goes on past the project folder, to the
filesystem root (``search_above_roots``), because that is where a reference leaks
into a neighbouring project. The library folder, when one is given, is a second
root, so a file that SOLIDWORKS' search would not find but the library holds is
reported as found there.

Each reference gets one :class:`Finding`, with one of :data:`RESULTS`:

* ``ok``: found inside the project;
* ``outside``: found only outside it, in the library, another project (a folder
  beside the project) or elsewhere;
* ``toolbox``: Toolbox hardware not found inside the project;
* ``inside_parent``: a virtual component or an imported one, stored inside its
  assembly;
* ``missing``: not found anywhere;
* ``different_document``: the only file found by that name is another document
  (its stored creation time differs);
* ``ambiguous``: several files could be it, and none could be chosen.

:func:`plan_copies` lists the copies that would make the project self-contained.
It plans only: nothing here writes a file.

The order in which the folder probe tries the stored folder's tails is the
resolver's (:func:`solidseas.resolve.names.suffix_tails`), the bare name first.
Whether SOLIDWORKS tries the longest tail first is not settled yet.

A sub-assembly's own components are checked when that sub-assembly is: a
reference the top document stores only for a file inside a sub-assembly is left
out. A sub-assembly outside the project is not followed, so what it references
shows once it has been copied in.
"""

import filecmp
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import SolidSeasError
from ..formats.solidworks import open_document
from ..resolve import IndexCache, ResolutionInput, resolve_references
from ..resolve.core import POSITIONAL_RULES
from ..resolve.names import DOCUMENT_EXTENSIONS, fold, parse_stored
from ..roots import Root, Roots
from ..walk import Walk

RESULTS = ("ok", "outside", "toolbox", "inside_parent", "missing", "different_document", "ambiguous")
PLACES = ("project", "library", "other_project", "elsewhere")
# The rules that follow SOLIDWORKS' own search (the name index is SolidSeas' own).
SEARCH_RULES = frozenset(("embedded", *POSITIONAL_RULES))
_INSIDE = ("embedded", "embedded_in_subassembly", "inside_parent")
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
    SOLIDWORKS' own search rules found the file, False when only SolidSeas' name index
    did (SOLIDWORKS itself would not find it there)."""

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


@dataclass(frozen=True)
class CheckResult:
    """Every reference of every document in ``project``. ``unreadable`` lists the
    documents that could not be read, with the error's class name."""

    project: Path
    library: Path | None
    toolbox_mandatory: bool
    documents: int
    findings: tuple[Finding, ...]
    unreadable: tuple[tuple[Path, str], ...] = ()

    def counts(self) -> dict[str, int]:
        out = dict.fromkeys(RESULTS, 0)
        for f in self.findings:
            out[f.result] = out.get(f.result, 0) + 1
        return out

    def problems(self) -> list[Finding]:
        """The findings that keep the project from being self-contained: every one but
        ``ok`` and ``inside_parent``, and but ``toolbox`` when Toolbox parts need no copy."""
        fine = {"ok", "inside_parent"} | (set() if self.toolbox_mandatory else {"toolbox"})
        return [f for f in self.findings if f.result not in fine]

    @property
    def self_contained(self) -> bool:
        return not self.problems() and not self.unreadable


@dataclass(frozen=True)
class PlannedCopy:
    """A file to copy into the project: from ``source`` to ``destination``, for the
    documents in ``referenced_by``. ``place`` is where the source is (:data:`PLACES`)."""

    source: Path
    destination: Path
    referenced_by: tuple[Path, ...]
    place: str | None


@dataclass(frozen=True)
class CopyConflict:
    """A copy that cannot be made: ``destination`` already holds another file of that
    name, or another planned copy takes it."""

    source: Path
    destination: Path
    referenced_by: tuple[Path, ...]
    reason: str


@dataclass(frozen=True)
class CopyPlan:
    """The copies :func:`plan_copies` would make, the ones it cannot, and the files
    already in place (same content at the destination: no copy needed)."""

    copies: tuple[PlannedCopy, ...]
    conflicts: tuple[CopyConflict, ...] = ()
    present: tuple[PlannedCopy, ...] = field(default=())


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
    toolbox = is_toolbox_path(f.stored_path) or (found is not None and is_toolbox_path(str(found)))
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
    )


def check_project(
    project: Path, *, library: Path | None = None, toolbox_mandatory: bool = True
) -> CheckResult:
    """Check that every reference of every SOLIDWORKS document in ``project`` resolves
    inside it (see the module notes). ``library`` is the common-parts library folder:
    a file found there is reported as ``outside`` with place ``library``.
    ``toolbox_mandatory`` True means Toolbox parts must be copied into the project like
    any other file; False means SOLIDWORKS loads them from the installation's own
    Toolbox folder, so a ``toolbox`` finding is no problem and needs no copy.

    Opens every document read-only and writes nothing. Raises ``FileNotFoundError``
    or ``NotADirectoryError`` for the project folder itself only; a document that
    cannot be read is listed in ``unreadable``."""
    project = Path(os.path.abspath(project))
    lib = Path(os.path.abspath(library)) if library is not None else None
    roots = [Root("project", str(project))]
    if lib is not None and not _inside(lib, project):
        roots.append(Root("library", str(lib), role="library"))
    cache = IndexCache()
    findings: list[Finding] = []
    unreadable: list[tuple[Path, str]] = []
    count = 0
    for path in _documents(project):
        count += 1
        try:
            with open_document(path, hold_open=True, within=project) as doc:
                inp = ResolutionInput.from_document(doc)
                files = doc.reference_set().files
        except (OSError, SolidSeasError) as exc:
            unreadable.append((path, type(exc).__name__))
            continue
        if not inp.files:
            continue
        resolution = resolve_references(
            inp,
            Roots(roots),
            cache=cache,
            allow_outside_roots=True,
            search_above_roots=True,
            skip_unavailable_roots=True,
        )
        for f in inp.files:
            if f.direct is False:  # checked when its own sub-assembly is
                continue
            r = resolution.results.get(f.key)
            if r is None:
                continue
            findings.append(_finding(path, files.get(f.key, f), r, project, lib))
    return CheckResult(project, lib, toolbox_mandatory, count, tuple(findings), tuple(unreadable))


# --------------------------------------------------------------------------- the plan
def _needs_copy(f: Finding, toolbox_mandatory: bool) -> bool:
    if f.found is None:
        return False
    if f.result == "outside":
        return True
    return f.result == "toolbox" and toolbox_mandatory


def _same_content(a: Path, b: Path) -> bool:
    try:
        return filecmp.cmp(a, b, shallow=False)
    except OSError:
        return False


def plan_copies(result: CheckResult) -> CopyPlan:
    """The copies that would make ``result``'s project self-contained, without making
    them. Each file found outside the project (and each Toolbox part, when
    ``toolbox_mandatory``) is copied once, into the deepest folder that holds every
    document referring to it, so SOLIDWORKS' search finds it from each of them; that
    folder is the project's own when it would lie outside it. A destination that
    already holds a file of that name is never written over: with the same content
    the copy is listed in ``present``, otherwise in ``conflicts``."""
    project = result.project
    groups: dict[str, tuple[Path, list[Path], str | None]] = {}
    for f in result.findings:
        if not _needs_copy(f, result.toolbox_mandatory) or f.found is None:
            continue
        src, users, place = groups.setdefault(_key(f.found), (f.found, [], f.place))
        if f.document not in users:
            users.append(f.document)
    copies: list[PlannedCopy] = []
    conflicts: list[CopyConflict] = []
    present: list[PlannedCopy] = []
    taken: dict[str, Path] = {}
    for src, users, place in groups.values():
        try:
            folder = Path(os.path.commonpath([str(u.parent) for u in users]))
        except ValueError:  # different drives
            folder = project
        if not _inside(folder, project):
            folder = project
        dest = folder / src.name
        by = tuple(users)
        if _key(dest) in taken:
            conflicts.append(CopyConflict(src, dest, by, "another planned copy has this name here"))
            continue
        if os.path.lexists(dest):
            if os.path.isfile(dest) and not os.path.islink(dest) and _same_content(src, dest):
                present.append(PlannedCopy(src, dest, by, place))
            else:
                conflicts.append(CopyConflict(src, dest, by, "a different file of this name is already here"))
            continue
        taken[_key(dest)] = src
        copies.append(PlannedCopy(src, dest, by, place))
    return CopyPlan(tuple(copies), tuple(conflicts), tuple(present))


__all__ = [
    "PLACES",
    "RESULTS",
    "SEARCH_RULES",
    "CheckResult",
    "CopyConflict",
    "CopyPlan",
    "Finding",
    "PlannedCopy",
    "check_project",
    "is_toolbox_path",
    "plan_copies",
]
