"""File > Export STEP's workings, without Qt: the export of a part, run in the export's
own process (:func:`.printing.export_in_process`, job ``step``).

The document is opened read-only as the details panel opens it (a Parasolid file
as a model file, :func:`.printing._opened`), mapped to STEP by
:func:`solidseas.step.step_model` in the configuration the details panel shows,
written to ``.<name>.<token>.part`` beside the file the user chose (created new),
and then given that file's name: by a rename that refuses a file that is there, or,
when the user's own save dialog asked to replace it, over it. A process stopped
while writing leaves only the part file, which :func:`.printing.export_in_process`
removes. The file must lie outside the opened folder and the document's own
folder, as every export of the viewer does.
"""

import os
from typing import Any

from solidseas import cli as _cli
from solidseas.errors import OutputRefusedError

from . import reading

TITLE = "Export STEP"
FILTER = "STEP files (*.step *.stp)"
MAX_LISTED = 20  # bodies named in a result or a refusal


def part_path(target: str, token: str) -> str:
    """Where the export is written before it gets ``target``'s name: a hidden part file
    beside it, so a process ended while writing leaves no file under that name."""
    folder, name = os.path.split(os.path.abspath(target))
    return os.path.join(folder, f".{name}.{token}.part")


def _claim(part: str, target: str, overwrite: bool) -> None:
    """Give the finished part file ``target``'s name: over a file there only with
    ``overwrite``; otherwise by :func:`.printing.rename_new`, which never replaces a file
    and says so plainly where the file system has no hard links to name it by."""
    from .printing import rename_new

    if overwrite:
        os.replace(part, target)
        return
    try:
        rename_new(part, target)
    except FileExistsError:
        raise OutputRefusedError(
            f"{target} already exists; it is not replaced unless asked", detail={"rule": "exists"}
        ) from None


def step_of(
    doc,
    path: str,
    folder: str,
    nested: tuple[str, ...] = (),
    configuration: str | None = None,
    *,
    allow_partial: bool = False,
    outside: bool = True,
):
    """The STEP model Export STEP writes of the open document ``doc`` (opened from
    ``path``, ``nested`` inside it, in the opened ``folder``): its solid bodies in
    ``configuration``, or its surface (sheet) bodies when it has no solid, an assembly's
    component files found in the opened folder (and, with ``outside``, at a stored path
    outside it on a drive of this computer). File > Convert sends the same model."""
    from solidseas.errors import NothingToExportError
    from solidseas.step import step_model

    stem = reading.export_stem(path, nested)
    roots = reading.roots_for(folder) if doc.doc_type == "assembly" else None  # finds its parts
    try:
        return step_model(
            doc, configuration, name=stem, allow_partial=allow_partial, roots=roots,
            allow_outside_roots=outside,
        )
    except NothingToExportError as exc:
        if (exc.detail or {}).get("rule") != "sheets_not_asked":
            raise
        # a part of surfaces only: its surfaces are what there is to send
        return step_model(
            doc,
            configuration,
            name=stem,
            allow_partial=allow_partial,
            body_types=("solid", "sheet"),
            roots=roots,
            allow_outside_roots=outside,
        )


def export_step_file(
    path: str,
    folder: str,
    target: str,
    *,
    within: str | None = None,
    nested: tuple[str, ...] = (),
    configuration: str | None = None,
    allow_partial: bool = False,
    overwrite: bool = False,
    token: str | None = None,
    outside: bool = True,
) -> dict[str, Any]:
    """Export the document at ``path`` (opened read-only ``within`` the opened ``folder``,
    or the nested document ``nested`` leads to; a SOLIDWORKS part or assembly, or a
    Parasolid file's part or assembly, whose files are found in ``folder``, and with
    ``outside`` at a stored path outside it on a drive of this computer) as STEP to
    ``target``: its solid bodies, or its
    surface (sheet) bodies when it has no solid. Returns what was written, for the window; raises what
    :func:`step_model` raises (``NotRepresentableError`` naming each body refused,
    ``UnsupportedOperationError`` for a file of another format) and
    ``OutputRefusedError``."""
    from solidseas.step import write_step

    from .printing import _opened

    sources = [os.path.abspath(path)]
    target = _cli.check_output_file(
        target,
        sources,
        allow_source_dir=False,
        force=overwrite,
        source_dirs=[os.path.abspath(folder), os.path.dirname(os.path.abspath(path))],
    )
    ext = os.path.splitext(target)[1].lower()
    if ext not in (".step", ".stp"):
        raise OutputRefusedError(
            f"a STEP export must end in .step or .stp, not {ext or 'nothing'}",
            detail={"rule": "output_extension"},
        )
    with _opened(path, within or folder, tuple(nested)) as doc:
        model = step_of(
            doc, path, folder, tuple(nested), configuration, allow_partial=allow_partial, outside=outside
        )
    part = part_path(target, token or os.urandom(8).hex())
    result = write_step(model, part, file_name=os.path.basename(target))  # created new; removed on failure
    try:
        _claim(part, target, overwrite)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    c = model.counts
    return {
        "file": target,
        "bytes": result.bytes,
        "name": model.name,
        "doc_type": model.doc_type,
        "configuration": model.configuration,
        "products": c.get("products", 1),
        "solids": c.get("solids", 0),
        "sheets": c.get("sheets", 0),
        "faces": c.get("faces", 0),
        "exact": model.exact,
        "partial": model.partial,
        "max_deviation_mm": None if model.max_deviation_m is None else model.max_deviation_m * 1000.0,
        "max_tolerance_mm": None if model.max_tolerance_m is None else model.max_tolerance_m * 1000.0,
        "uncertainty_mm": model.uncertainty_m * 1000.0,
        "source_format": model.source_format,
        "left_out": [
            {"name": b.name, "reason": b.reason, "message": b.message} for b in model.bodies if not b.written
        ][:MAX_LISTED],
        "warnings": [{"code": w.code, "message": w.message} for w in model.warnings],
        "seconds": round(model.seconds, 3),
    }


def refused_bodies(error: dict[str, Any]) -> str:
    """The refusal's own text, which names each body and its reason (the window shows
    it as plain text)."""
    text = error.get("reader_message") or error.get("message") or ""
    return text[:4000]


def left_out_lines(left: list[dict[str, Any]]) -> list[str]:
    """The bodies not written, worded by why: bodies hidden in SOLIDWORKS (which leaves
    them out of its own STEP too), surface bodies of a part that has solids (the export
    writes a part's solids; its surfaces only when it has no solid), wire bodies, which
    STEP holds no shape of here, and bodies left out after the user agreed to write the
    file without them."""

    hidden = [b["name"] for b in left if b["reason"] == "hidden"]
    sheets = [b["name"] for b in left if b["reason"] == "not_asked"]
    wires = [b["name"] for b in left if b["reason"] == "unsupported_body"]
    refused = [b for b in left if b["reason"] not in ("hidden", "not_asked", "unsupported_body")]
    lines = []
    if hidden:
        lines.append(
            "Hidden bodies not written (SOLIDWORKS leaves them out of its STEP too): " + ", ".join(hidden)
        )
    if sheets:
        lines.append("Surface bodies not written (the part's solids are): " + ", ".join(sheets))
    if wires:
        lines.append("Wire bodies not written (STEP holds no wire body): " + ", ".join(wires))
    if refused:
        lines.append("Left out, as you asked: " + "; ".join(f"{b['name']} ({b['reason']})" for b in refused))
    return lines
