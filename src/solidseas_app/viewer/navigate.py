"""Where a component's file is: what Go to file and Show in folder list do, and
where Open and Show in File Explorer (:mod:`.opening`) find the file.

The details panel already holds the document's ``references`` section, whose
files carry their resolution against the opened folder (``solidseas.resolve``
with that folder as the one root, :data:`.reading.ROOT_ID`, and point lookups
of a stored path on a local drive allowed unless Look for Referenced Files Only in
the Opened Folder is on). :func:`target` turns one file of
it into a :class:`Target`, the place the window goes to:

* ``listed``: found in or below the opened folder, at ``rel``; the window
  selects it in the document list.
* ``outside``: found outside the opened folder, at ``path``; the window opens
  it on its own in the details panel, read-only like everything else.
* ``nested``: a virtual (or embedded imported) component, stored inside the
  document as the nested document ``nested``.
* ``choose``: several files fit equally well (``ambiguous``); the user picks
  one of ``candidates``.
* ``missing``: nothing was found, or the file is stored somewhere the window
  cannot open it from here; ``why`` says which, in words.
* ``pending``: the references are still being resolved.
* ``unknown``: the references could not be read, or the file has no entry.

Nothing here imports Qt, so it is tested everywhere.
"""

import os
from dataclasses import dataclass, field, replace
from typing import Any

from .reading import ROOT_ID
from .wording import reference_status, rule_text

GO_TEXT = "Go to file"  # the menus' name for showing a file here, in the viewer

LISTED, OUTSIDE, NESTED, CHOOSE, MISSING, PENDING, UNKNOWN = (
    "listed",
    "outside",
    "nested",
    "choose",
    "missing",
    "pending",
    "unknown",
)
OPENABLE = (LISTED, OUTSIDE, NESTED)

# What a resolution warning means to the person asking for the file. An open set:
# a code not here is left out of the explanation, never shown as a code alone.
_WARNINGS = {
    "stored_unc_not_checked": (
        "The stored path is on a network share. SolidSeas never connects to a server a file names, "
        "so that path was not looked at."
    ),
    "stored_network_drive_not_checked": (
        "The stored path is on a mapped network drive, which SolidSeas never touches, so it was not "
        "looked at."
    ),
    "stored_path_refused": (
        "The stored path breaks a safety rule, so it was not used as a location; only its file name was "
        "searched for."
    ),
    "index_partial": "A limit stopped the search of the opened folder early, so the file may still be there.",
    "search_incomplete": "A limit stopped the search before it was complete, so the file may still be there.",
    "root_unavailable": "The opened folder could not be searched.",
    "placeholder_not_read": (
        "A cloud placeholder was found and not opened: its data is not on this computer, and SolidSeas "
        "never starts a download."
    ),
    "identity_read_failed": "A file that was found could not be read to check that it is the same document.",
    "from_parent_tree": (
        "It is used inside a sub-assembly and was looked for from the path this document stored for it."
    ),
}
_IDENTITY_DIFFERS = (
    "its creation time is not the one stored for it, so it may be another document with the same name"
)
OUTSIDE_NOT_SEARCHED = (
    "A stored path outside the opened folder is not looked at: Look for referenced files only in the "
    "opened folder is on (Settings > General)."
)


@dataclass(frozen=True)
class Candidate:
    """One file an ambiguous reference could be: ``rel`` below the opened folder, or
    ``path`` outside it."""

    location: str  # as the References tab shows it
    rel: str | None
    path: str | None
    found_by: str | None
    identity: str | None
    placeholder: bool


@dataclass(frozen=True)
class Target:
    """Where the window goes for one referenced file (see the module docstring)."""

    kind: str
    key: str
    name: str  # the file name as stored, or the key when none is stored
    doc_type: str | None = None
    stored_path: str | None = None
    status: str | None = None  # the resolution's status
    rel: str | None = None
    path: str | None = None
    nested: str | None = None
    candidates: tuple[Candidate, ...] = field(default=())
    how: str = ""  # how it was found, for the status bar
    caution: str = ""  # something to know about the file found (an identity that differs)
    why: str = ""  # why it cannot be opened, for missing and unknown

    @property
    def openable(self) -> bool:
        return self.kind in OPENABLE

    @property
    def in_folder_list(self) -> bool | None:
        """Whether Show in folder list can find it: True, False, or None until the
        references say."""
        if self.kind in (LISTED, CHOOSE):
            return True
        if self.kind == PENDING:
            return None
        return False

    @property
    def not_listed_reason(self) -> str:
        """Why Show in folder list cannot show it, in a few words."""
        if self.status == "inside_parent":
            return "stored inside the assembly"
        return {
            OUTSIDE: "outside the opened folder",
            NESTED: "stored inside the document",
            MISSING: "not found",
            UNKNOWN: "not resolved",
        }.get(self.kind, "")


def _type_of(name: str) -> str | None:
    return {".sldprt": "part", ".sldasm": "assembly", ".slddrw": "drawing"}.get(
        os.path.splitext(name)[1].lower()
    )


def candidate(cand: dict[str, Any]) -> Candidate:
    root, path = cand.get("root"), cand.get("path") or ""
    if root == ROOT_ID:
        rel, host, location = path, None, path
    elif root is None:
        rel, host, location = None, path, path
    else:  # another root: the viewer searches only the opened folder
        rel, host, location = None, None, f"{root}: {path}"
    return Candidate(
        location=location,
        rel=rel,
        path=host,
        found_by=cand.get("found_by"),
        identity=cand.get("identity"),
        placeholder=bool(cand.get("placeholder")),
    )


def explain(warnings: list[dict[str, Any]] | None) -> list[str]:
    """The sentences for the resolution warnings that say something to the user."""
    return [_WARNINGS[w["code"]] for w in warnings or [] if w.get("code") in _WARNINGS]


def target(
    file: dict[str, Any] | None,
    *,
    key: str,
    pending: bool = False,
    outside_roots: bool = True,
    model: bool = False,
) -> Target:
    """The :class:`Target` for the referenced file ``file`` (a file of the
    ``references`` kind, with its ``resolution``). ``pending`` says the references
    are still being read; ``outside_roots`` whether the search also looked at stored
    paths outside the opened folder (the viewer does unless its setting Look for
    Referenced Files Only in the Opened Folder is on); ``model`` that
    the file is named by a model file (an Alibre component), which is searched for
    as :func:`missing_text` says."""
    if file is None:
        if pending:
            return Target(PENDING, key, key)
        return Target(UNKNOWN, key, key, why="This document lists no file for it.")
    name = file.get("file_name") or file.get("stored_path") or key
    base = Target(
        UNKNOWN,
        key,
        name,
        doc_type=file.get("doc_type") or _type_of(name),
        stored_path=file.get("stored_path"),
    )
    rr = file.get("resolution")
    if not rr:
        if pending:
            return replace(base, kind=PENDING)
        return replace(base, why="Its location could not be worked out: the references were not resolved.")
    status = rr.get("status")
    base = replace(base, status=status)
    if status == "embedded" and (rr.get("nested") or file.get("nested")):
        stream = rr.get("nested") or file["nested"]
        return replace(base, kind=NESTED, nested=stream, how=f"stored inside the assembly ({stream})")
    if status in ("resolved", "moved") and rr.get("match"):
        match = rr["match"]
        how = f"{reference_status(status)}, {rule_text(rr.get('rule'))}"
        if rr.get("confidence"):
            how += f" ({rr['confidence']} confidence)"
        caution = _IDENTITY_DIFFERS if rr.get("identity") == "differ" else ""
        if match.get("root") == ROOT_ID:
            return replace(base, kind=LISTED, rel=match["path"], how=how, caution=caution)
        if match.get("root") is None:
            return replace(base, kind=OUTSIDE, path=match["path"], how=how, caution=caution)
    if status == "ambiguous":
        cands = tuple(candidate(c) for c in rr.get("candidates") or [])
        usable = [c for c in cands if c.rel is not None or c.path is not None]
        if usable:
            return replace(base, kind=CHOOSE, candidates=cands)
    why = missing_text(file, rr, outside_roots=outside_roots, model=model)
    return replace(base, kind=MISSING, why=why)


def missing_text(
    file: dict[str, Any], rr: dict[str, Any], *, outside_roots: bool = True, model: bool = False
) -> str:
    """Why a file cannot be opened: what was searched and what got in the way. A file a
    model file names (``model``) was looked for only beside that file: an Alibre
    component by its document GUID in the assembly's folder and its subfolders, a
    glTF buffer or an OBJ material library at the path it names in the file's folder."""
    status = rr.get("status")
    if model and file.get("kind") == "component":
        lines = [
            "No file with its document GUID was found. Searched the assembly's own folder and its "
            "subfolders; the rest of the opened folder was not searched."
        ]
    elif model and status == "refused":
        lines = [
            "The path the document names leads out of its folder, or through a link, junction or cloud "
            "placeholder, and SolidSeas never reads a file there for it."
        ]
    elif model:
        lines = [
            "No file was found at the path the document names, in the document's own folder. Files "
            "elsewhere are never read for it."
        ]
    elif status == "embedded_not_found":
        lines = [
            "It is a virtual component, stored inside this document rather than as a file of its own, "
            "but the document holds no copy of it."
        ]
    elif status == "inside_parent":
        lines = [
            "It is a component SOLIDWORKS made when it opened a STEP or similar assembly. It is kept "
            "inside this assembly rather than as a file of its own, so there is no file to open."
        ]
    elif status == "embedded_in_subassembly":
        lines = [
            "It is a virtual component of a sub-assembly: SOLIDWORKS stores it inside that "
            "sub-assembly's own file, not in this one. Open the sub-assembly, then this component "
            "from its Components tab."
        ]
    elif status == "ambiguous":
        lines = ["Several files could be this one, and none of them can be opened from here."]
    else:
        searched = "the opened folder and its subfolders"
        if outside_roots:
            searched += ", and the stored path when it is on a drive of this computer"
        lines = [f"No file of that name was found. Searched {searched}."]
        if not outside_roots:
            lines.append(OUTSIDE_NOT_SEARCHED)
    if not (status or "").startswith("embedded"):  # nothing was looked for on disk
        lines += explain(rr.get("warnings"))
    return "\n\n".join(lines)


def choose(t: Target, index: int) -> Target:
    """The target an ambiguous one becomes once candidate ``index`` is chosen; a
    candidate that cannot be opened (a cloud placeholder, another root) is missing."""
    c = t.candidates[index]
    how = f"chosen from {len(t.candidates)} files that fit equally well"
    caution = _IDENTITY_DIFFERS if c.identity == "differ" else ""
    if c.placeholder or (c.rel is None and c.path is None):
        why = "That file cannot be opened from here."
        if c.placeholder:
            why = "That file is a cloud placeholder, and SolidSeas never starts a download."
        return replace(t, kind=MISSING, why=why, candidates=())
    if c.rel is not None:
        return replace(t, kind=LISTED, rel=c.rel, how=how, caution=caution, candidates=())
    return replace(t, kind=OUTSIDE, path=c.path, how=how, caution=caution, candidates=())


def found_text(t: Target) -> str:
    """The status bar's line after going to a file."""
    text = f"{t.name}: {t.how}" if t.how else t.name
    if t.caution:
        text += f"; {t.caution}"
    return text
