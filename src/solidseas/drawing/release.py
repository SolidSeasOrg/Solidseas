"""Status, signatures, release and revisions (``docs/DRAWINGS.md`` 13.2, 13.3, 17.2).

A drawing is **PRELIMINARY** when it is made, **CHECKED** once someone signs the
CHECKED row, and **RELEASED** by :func:`release`. A signature is a record of who
approved what and when (the row, the person's name, the date and the digest of the
drawing's content at that moment), not a cryptographic signature: anyone who can
edit the file can edit it, and :func:`check_release_record` and the digests only
show that a record no longer matches.

- :func:`content_digest` is the SHA-256 of what a signature covers: the drawing's
  id, the model's identity (not where it was found), the frozen options, the
  settings snapshot, the title fields, the features and their decisions, the
  datums, the dimensions, the notes and the revision rows' marks, zones and
  descriptions. Status, signatures, the accepted items, the outputs, the ids still
  free, the laid-out sheet and the file's times are not covered: release fills the
  revision row's date and approver and lays the sheet out again without changing
  what was signed.
- :func:`sign` records a signature on a row the settings name; signing CHECKED
  moves the status to CHECKED. The same person on a second row is a warning when the
  settings allow it and an error otherwise.
- :func:`invalidate`, after an edit, clears the signatures whose digest no longer
  matches (every row but DRAWN) and says so.
- :func:`release` needs every row the settings require signed and current, no
  error-level check except the accepted ones, the material mapped or accepted, and
  no dimension needing attention; it sets RELEASED and fills the revision row.
- :func:`start_revision` adds the next revision row (A, B, ... skipping I, O, Q, S,
  X and Z), clears the signatures and goes back to PRELIMINARY.

A RELEASED drawing refuses edits: :func:`require_editable` raises
``DrawingReleasedError`` (an ``InvalidArgumentError``, error code
``drawing_released``) with ``detail["rule"] == "drawing_released"``.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from typing import Any

from ..errors import DrawingReleasedError, InvalidArgumentError
from . import settings as settings_mod
from . import standards, types
from .limits import DEFAULT_LIMITS

PRELIMINARY, CHECKED, RELEASED = types.STATUSES
DRAWN = "DRAWN"
# Error-level checks Release lets through when the user accepted them with a typed reason (13.2).
ACCEPTABLE = ("COV.unclaimed", "R2.override")
MATERIAL_ITEM = "material"
RECORD_MISMATCH = "release record does not match the files"
SIGNATURES_MISMATCH = "the signatures do not match the drawing's content"
MAX_ZONES = 200
_ZONE = re.compile(r"[A-Z]{1,2}[0-9]{1,3}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_COVERED = ("id", "model", "options", "settings", "title", "features", "datums", "dimensions", "notes")
_MODEL_COVERED = (
    "name",
    "format",
    "configuration",
    "sha256",
    "geometry",
    "properties",
    "part_number",
    "model_revision",
    "units",
)


class ReleaseRefusedError(InvalidArgumentError):
    """Release was refused; ``reasons`` lists every reason, in words for the user, and
    ``detail["rule"]`` is ``release_refused``."""

    def __init__(self, reasons: Iterable[str]) -> None:
        self.reasons = tuple(reasons)
        super().__init__(
            "the drawing cannot be released: " + "; ".join(self.reasons),
            detail={"parameter": "drawing", "rule": "release_refused", "value": len(self.reasons)},
        )


def released_error(what: str = "it cannot be changed") -> DrawingReleasedError:
    """The error an edit of a RELEASED drawing raises (13.3): code ``drawing_released``."""
    return DrawingReleasedError(
        f"the drawing is RELEASED and {what}; start a revision first",
        detail={"parameter": "drawing", "rule": "drawing_released"},
    )


def require_editable(drawing: types.Drawing, what: str = "it cannot be changed") -> None:
    """Raise :func:`released_error` when ``drawing`` is RELEASED."""
    _check(drawing)
    if drawing.status == RELEASED:
        raise released_error(what)


def _check(drawing: Any) -> None:
    if not isinstance(drawing, types.Drawing):
        raise InvalidArgumentError("drawing must be a Drawing", detail={"parameter": "drawing"})


def status(drawing: types.Drawing) -> str:
    """PRELIMINARY, CHECKED or RELEASED."""
    _check(drawing)
    return drawing.status


def current_revision(drawing: types.Drawing) -> str | None:
    """The mark of the drawing's last revision row."""
    return drawing.revisions[-1].rev if drawing.revisions else None


def iso_day(today: str | datetime.date | None) -> str:
    """``today`` as ``YYYY-MM-DD`` (the local date when None); the file always stores the
    ISO form, whatever the settings' display format."""
    if today is None:
        return datetime.date.today().isoformat()
    if isinstance(today, datetime.datetime):
        return today.date().isoformat()
    if isinstance(today, datetime.date):
        return today.isoformat()
    if isinstance(today, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", today):
        try:
            return datetime.date.fromisoformat(today).isoformat()
        except ValueError:
            pass
    raise InvalidArgumentError("today must be a date (YYYY-MM-DD)", detail={"parameter": "today"})


def content_digest(drawing: types.Drawing) -> str:
    """The SHA-256 of what a signature covers (see the module notes), over the members as
    the file writes them, so the same content gives the same digest anywhere."""
    from .document import member_values

    _check(drawing)
    values = member_values(drawing)
    covered: dict[str, Any] = {k: values[k] for k in _COVERED}
    covered["model"] = {k: values["model"].get(k) for k in _MODEL_COVERED}
    covered["revisions"] = [
        {"rev": r["rev"], "zones": r["zones"], "description": r["description"]} for r in values["revisions"]
    ]
    text = json.dumps(covered, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _settings(drawing: types.Drawing) -> settings_mod.DrawingSettings:
    s = drawing.settings
    return s if isinstance(s, settings_mod.DrawingSettings) else settings_mod.DrawingSettings()


def _person(settings: settings_mod.DrawingSettings, person: Any) -> str:
    """The People entry's name for ``person`` (a name, initials or a People record)."""
    if isinstance(person, Mapping):
        person = person.get("name")
    if not isinstance(person, str) or not person.strip() or _CONTROL.search(person):
        raise InvalidArgumentError(
            "person must be a name from the People list", detail={"parameter": "person"}
        )
    people = settings.people.people
    if not people:
        raise InvalidArgumentError(
            "Drawing Settings name nobody who signs drawings; add the people first",
            detail={"parameter": "person", "rule": "no_people"},
        )
    want = " ".join(person.split()).casefold()
    for p in people:
        if want in (" ".join(p["name"].split()).casefold(), p.get("initials", "").strip().casefold()):
            return p["name"]
    raise InvalidArgumentError(
        f"{person[:60]!r} is not in the People list of Drawing Settings",
        detail={"parameter": "person", "rule": "not_in_people"},
    )


def sign(
    drawing: types.Drawing,
    row: str,
    person: Any,
    today: str | datetime.date | None = None,
) -> tuple[types.Drawing, tuple[str, ...]]:
    """``drawing`` signed on ``row`` by ``person`` (a name or initials from the People
    list of the drawing's settings) on ``today``, with the content digest of this
    moment, and the warnings. Only a row the settings use may be signed, once; the
    same person on a second row is a warning when the settings allow it and an error
    (rule ``same_person``) otherwise. Signing CHECKED moves the status to CHECKED.
    The editor's Sign... calls this; the command line never does."""
    require_editable(drawing, "it cannot be signed")
    settings = _settings(drawing)
    if row not in settings.people.rows:
        raise InvalidArgumentError(
            f"{str(row)[:20]!r} is not a row Drawing Settings use ({', '.join(settings.people.rows)})",
            detail={"parameter": "row", "rule": "row"},
        )
    name = _person(settings, person)
    day = iso_day(today)
    digest = content_digest(drawing)
    warnings: list[str] = []
    for s in drawing.signatures:
        if s.row == row:
            if s.digest == digest:
                raise InvalidArgumentError(
                    f"{row} is already signed by {s.name}", detail={"parameter": "row", "rule": "signed"}
                )
    others = [s for s in drawing.signatures if s.row != row and s.name.casefold() == name.casefold()]
    if others:
        if not settings.people.same_person_twice:
            raise InvalidArgumentError(
                f"{name} already signed {others[0].row}, and Drawing Settings let nobody sign two rows",
                detail={"parameter": "person", "rule": "same_person"},
            )
        warnings.append(f"{name} also signed {others[0].row}")
    kept = [s for s in drawing.signatures if s.row != row]
    kept.append(types.Signature(row, name, day, digest))
    order = {r: k for k, r in enumerate(settings_mod.APPROVAL_ROWS)}
    kept.sort(key=lambda s: order.get(s.row, len(order)))
    new_status = CHECKED if row == "CHECKED" and drawing.status == PRELIMINARY else drawing.status
    return replace(drawing, signatures=tuple(kept), status=new_status), tuple(warnings)


def invalidate(drawing: types.Drawing) -> tuple[types.Drawing, tuple[str, ...]]:
    """After an edit: ``drawing`` without the signatures the edit invalidated (those whose
    digest no longer matches the content; DRAWN is always kept), back to PRELIMINARY
    when CHECKED was cleared, and what was cleared, in words (13.2)."""
    require_editable(drawing)
    digest = content_digest(drawing)
    kept, said = [], []
    for s in drawing.signatures:
        if s.row == DRAWN or s.digest == digest:
            kept.append(s)
        else:
            said.append(f"the edit cleared the {s.row} signature of {s.name}")
    if not said:
        return drawing, ()
    rows = {s.row for s in kept}
    new_status = PRELIMINARY if drawing.status == CHECKED and "CHECKED" not in rows else drawing.status
    return replace(drawing, signatures=tuple(kept), status=new_status), tuple(said)


def _check_fields(c: Any) -> tuple[str, str, str, str]:
    """(level, code, item, message) of a check, from a mapping or an object."""

    def get(*names: str) -> str:
        for n in names:
            v = c.get(n) if isinstance(c, Mapping) else getattr(c, n, None)
            if isinstance(v, str) and v:
                return v
        return ""

    level = get("level", "severity").lower()
    code = get("code", "rule")
    item = get("item", "id", "key") or code
    message = get("message", "words", "text") or code
    return level, code, item, message


def _material_mapped(drawing: types.Drawing, settings: settings_mod.DrawingSettings) -> bool:
    for k, f in drawing.title:
        if k == "material":
            if f.source == "list" or settings.material(f.text) is not None:
                return True
            return any(e["callout"] == f.text for e in settings.materials.entries)
    return True  # no material field: nothing to map


def release_problems(
    drawing: types.Drawing,
    accepted: Mapping[str, str] | None = None,
    *,
    checks: Iterable[Any] | None = None,
) -> tuple[str, ...]:
    """Why ``drawing`` cannot be released, in words; empty when it can (13.2). ``accepted``
    maps an item (a check's item or code, or ``material``) to the user's typed reason;
    ``checks`` (the drawing's own by default) are mappings or objects with ``level``,
    ``code``, ``item`` and ``message``."""
    _check(drawing)
    accepted = dict(accepted or {})
    for item, reason in accepted.items():
        if not isinstance(item, str) or not isinstance(reason, str):
            raise InvalidArgumentError(
                "accepted maps items to typed reasons", detail={"parameter": "accepted"}
            )
    out: list[str] = []
    if drawing.status == RELEASED:
        return ("the drawing is already released",)
    settings = _settings(drawing)
    digest = content_digest(drawing)
    by_row = {s.row: s for s in drawing.signatures}
    for row in settings.people.required:
        s = by_row.get(row)
        if s is None:
            out.append(f"{row} is not signed")
        elif s.digest != digest:
            out.append(f"the {row} signature is older than the drawing's last change; sign it again")
    for c in drawing.checks if checks is None else checks:
        level, code, item, message = _check_fields(c)
        if level != "error":
            continue
        reason = accepted.get(item) or accepted.get(code)
        if code in ACCEPTABLE and isinstance(reason, str) and reason.strip():
            continue
        if code in ACCEPTABLE:
            out.append(f"{code} ({message}) needs a typed reason to be accepted")
        else:
            out.append(f"check {code}: {message}")
    if not _material_mapped(drawing, settings):
        reason = accepted.get(MATERIAL_ITEM)
        if not (isinstance(reason, str) and reason.strip()):
            out.append("the material is not in the materials list; map it or accept it as typed")
    for d in drawing.dimensions:
        if "needs_attention" in getattr(d, "flags", ()):
            out.append(f"dimension {d.id} needs attention")
    if not drawing.revisions:
        out.append("the drawing has no revision row")
    return tuple(out)


def release(
    drawing: types.Drawing,
    today: str | datetime.date | None = None,
    accepted: Mapping[str, str] | None = None,
    *,
    checks: Iterable[Any] | None = None,
) -> types.Drawing:
    """``drawing`` RELEASED on ``today`` (13.2): the revision row's date and approver (the
    APPROVED signer, else the last required row's) filled, the accepted items and
    their reasons recorded. Refused with :class:`ReleaseRefusedError` listing every
    reason (see :func:`release_problems`). The released PDF and DXF are then written
    without the stamp, as new files (``document.export_target``), and recorded
    (``document.record_output``)."""
    from .document import as_document

    problems = release_problems(drawing, accepted, checks=checks)
    if problems:
        raise ReleaseRefusedError(problems)
    settings = _settings(drawing)
    day = iso_day(today)
    by_row = {s.row: s for s in drawing.signatures}
    approver = by_row.get("APPROVED")
    if approver is None:
        signed = [by_row[r] for r in settings.people.required if r in by_row]
        approver = signed[-1] if signed else None
    rows = list(drawing.revisions)
    rows[-1] = replace(rows[-1], date=day, approved=approver.name if approver is not None else None)
    used = []
    keys_used = set()
    for c in drawing.checks if checks is None else checks:
        level, code, item, _m = _check_fields(c)
        if level == "error" and code in ACCEPTABLE:
            for key in (item, code):
                reason = (accepted or {}).get(key)
                if isinstance(reason, str) and reason.strip() and key not in keys_used:
                    used.append((key, reason.strip()[: DEFAULT_LIMITS.title_chars]))
                    keys_used.add(key)
                    break
    if not _material_mapped(drawing, settings):
        used.append((MATERIAL_ITEM, (accepted or {})[MATERIAL_ITEM].strip()[: DEFAULT_LIMITS.title_chars]))
    doc = as_document(drawing)
    return replace(doc, status=RELEASED, revisions=tuple(rows), accepted=tuple(used))


def start_revision(
    drawing: types.Drawing,
    description: str,
    zones: Iterable[str] = (),
    *,
    drawn_by: str | None = None,
    today: str | datetime.date | None = None,
) -> types.Drawing:
    """A RELEASED ``drawing`` opened for its next revision (13.3): a row with the next mark
    (``standards.next_revision``), ``description`` (pre-filled by the caller from the
    edit log and the merge report) and the ``zones`` of the changed items; every
    signature cleared, DRAWN signed again when ``drawn_by`` is given; PRELIMINARY.
    Released files keep their names: the new revision's files have their own."""
    _check(drawing)
    if drawing.status != RELEASED:
        raise InvalidArgumentError(
            "only a released drawing starts a revision; before the first release it is edited freely",
            detail={"parameter": "drawing", "rule": "not_released"},
        )
    if not isinstance(description, str) or not description.strip() or _CONTROL.search(description):
        raise InvalidArgumentError("a revision needs a description", detail={"parameter": "description"})
    if len(description) > DEFAULT_LIMITS.note_chars:
        raise InvalidArgumentError("the description is too long", detail={"parameter": "description"})
    zones = tuple(zones)
    if len(zones) > MAX_ZONES or not all(isinstance(z, str) and _ZONE.fullmatch(z) for z in zones):
        raise InvalidArgumentError(
            "zones are letters and a number, such as B3", detail={"parameter": "zones"}
        )
    rev = current_revision(drawing)
    first = _settings(drawing).people.first_revision
    mark = standards.next_revision(rev) if rev is not None else first
    rows = (*drawing.revisions, types.Revision(mark, description.strip(), tuple(dict.fromkeys(zones))))
    out = replace(drawing, revisions=rows, signatures=(), status=PRELIMINARY)
    if hasattr(out, "accepted"):
        out = replace(out, accepted=())
    if drawn_by is not None:
        if not isinstance(drawn_by, str) or not drawn_by.strip() or _CONTROL.search(drawn_by):
            raise InvalidArgumentError("drawn_by must be a name", detail={"parameter": "drawn_by"})
        out = replace(
            out, signatures=(types.Signature(DRAWN, drawn_by.strip(), iso_day(today), content_digest(out)),)
        )
    return out


def check_release_record(
    drawing: types.Drawing, files: Mapping[str, str | None] | Callable[[str], str | None]
) -> tuple[str, ...]:
    """For a drawing claiming RELEASED: whether its record still matches (17.2). ``files``
    gives the SHA-256 of each recorded export by name (None when it is not there). Any
    released export of the current revision whose file is missing or has another hash
    makes the first problem :data:`RECORD_MISMATCH`, and those files are never
    exported over; a required signature whose digest no longer matches the content
    adds :data:`SIGNATURES_MISMATCH`. Empty when the record holds (or the drawing is
    not released)."""
    _check(drawing)
    if drawing.status != RELEASED:
        return ()
    look = files if callable(files) else (lambda name: files.get(name))
    rev = current_revision(drawing)
    details = []
    for o in drawing.outputs:
        if not o.released or o.revision != rev:
            continue
        found = look(o.name)
        if found is None:
            details.append(f"{o.name} is not there")
        elif found != o.sha256:
            details.append(f"{o.name} is not the file that was released")
    out = [RECORD_MISMATCH, *details] if details else []
    digest = content_digest(drawing)
    required = _settings(drawing).people.required
    if any(s.row in required and s.digest != digest for s in drawing.signatures):
        out.append(SIGNATURES_MISMATCH)
    return tuple(out)


__all__ = [
    "ACCEPTABLE",
    "CHECKED",
    "DRAWN",
    "PRELIMINARY",
    "RECORD_MISMATCH",
    "RELEASED",
    "SIGNATURES_MISMATCH",
    "ReleaseRefusedError",
    "check_release_record",
    "content_digest",
    "current_revision",
    "invalidate",
    "iso_day",
    "release",
    "release_problems",
    "released_error",
    "require_editable",
    "sign",
    "start_revision",
    "status",
]
