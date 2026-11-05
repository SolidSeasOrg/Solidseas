"""File > Convert's workings, without Qt: the document shown, written as IGES, BREP or
STEP through :mod:`solidseas.convert` (the OCCT backend extension), run in the export's
own process (:func:`.printing.export_in_process`, job ``convert``).

The document is opened read-only as Export STEP opens it (:func:`.printing._opened`). An
IGES, BREP or STEP file goes to the backend as it is; a SOLIDWORKS part or assembly, or a
Parasolid file, goes as the STEP File > Export STEP writes of it
(:func:`.stepexport.step_of`): the configuration the details panel shows, an assembly's
components found in the opened folder, a part of surfaces only as its surfaces. The
backend's file is written to ``.<name>.<token>.part`` beside the file the user chose
(created new) and then given that file's name, as Export STEP's is
(:func:`.stepexport.part_path`), so a process stopped while writing leaves no file under
that name. The file must lie outside the opened folder and the document's own folder,
as every export of the viewer does.
"""

import os
from typing import Any

from solidseas import cli as _cli
from solidseas.errors import OutputRefusedError

from . import reading, stepexport

TITLE = "Convert"
# The formats Convert writes, by the names solidseas.convert takes, each with its save
# dialog's file type and the extension a name without one gets.
NAMES = {"iges": "IGES", "brep": "BREP", "step": "STEP"}
FILTERS = {
    "iges": "IGES files (*.igs *.iges)",
    "brep": "BREP files (*.brep)",
    "step": "STEP files (*.step *.stp)",
}
# What each kind of document converts to: never its own format, and a SOLIDWORKS document or
# a Parasolid file not to STEP, which File > Export STEP writes with its assembly structure.
TARGETS = {
    "solidworks": ("iges", "brep"),
    "parasolid": ("iges", "brep"),
    "step": ("iges", "brep"),
    "iges": ("step", "brep"),
    "occt_brep": ("step", "iges"),
}
DRAWING = "IGES, BREP and STEP hold 3D models, not drawings: convert the model the drawing shows instead"
MESH = "{name} files hold triangles, not the exact faces and edges IGES and BREP are made of"
OTHER = (
    "SolidSeas converts IGES, BREP and STEP files, SOLIDWORKS parts and assemblies and Parasolid "
    "files, not {name} files"
)


def extensions(name: str) -> tuple[str, ...]:
    """The file extensions of the format ``name`` (``iges``, ``brep`` or ``step``), the one
    a name without an extension gets first."""
    from solidseas import convert

    return convert.EXTENSIONS[convert.target_format(name)]


def targets(content: str | None) -> tuple[str, ...]:
    """The formats a document whose content is ``content`` (a registry id; None for a
    SOLIDWORKS document) converts to here, in the order the save dialog lists them."""
    return TARGETS.get(content or "solidworks", ())


def unavailable(content: str | None, doc_type: str | None) -> str | None:
    """Why File > Convert is off for a document, said for its tooltip, from what the
    listing says of it before anything is read: ``content`` is its registry id (None or
    ``solidworks`` for a SOLIDWORKS document). None when it converts."""
    from solidseas.formats import registry

    if doc_type == "drawing":
        return DRAWING
    if targets(content):
        return None
    spec = registry.FORMATS.get(content or "")
    name = spec.name if spec is not None else str(content)
    if spec is not None and spec.kind == "mesh":
        return MESH.format(name=name)
    return OTHER.format(name=name)


def format_of_name(path: str, offered: tuple[str, ...]) -> str | None:
    """The format among ``offered`` whose extension ``path`` ends in, if any."""
    ext = os.path.splitext(path)[1].lower()
    for name in offered:
        if ext and ext in extensions(name):
            return name
    return None


def convert_file(
    path: str,
    folder: str,
    target: str,
    *,
    format: str,
    within: str | None = None,
    nested: tuple[str, ...] = (),
    configuration: str | None = None,
    allow_partial: bool = False,
    overwrite: bool = False,
    token: str | None = None,
    outside: bool = True,
) -> dict[str, Any]:
    """Write the document at ``path`` (opened read-only ``within`` the opened ``folder``, or
    the nested document ``nested`` leads to) as ``format`` (``iges``, ``brep`` or ``step``)
    to ``target``, through the backend that writes it; an assembly's component files are
    found as Export STEP finds them, without ``outside`` in the opened folder alone
    (:func:`.stepexport.step_of`). Returns what was written, for the
    window; raises what :func:`solidseas.convert.convert_document` raises
    (``FormatNotSupportedError`` with rule ``needs_extension`` when the backend is not
    there, ``UnsupportedOperationError`` for a document no backend converts), what the
    STEP of a SOLIDWORKS document raises (``NotRepresentableError`` naming each body
    refused, unless ``allow_partial``), and ``OutputRefusedError``."""
    from solidseas import convert
    from solidseas.formats import open_model
    from solidseas.formats.base import ModelDocument
    from solidseas.step import step_bytes

    from .printing import _opened

    fmt = convert.target_format(format)
    target = _cli.check_output_file(
        target,
        [os.path.abspath(path)],
        allow_source_dir=False,
        force=overwrite,
        source_dirs=[os.path.abspath(folder), os.path.dirname(os.path.abspath(path))],
    )
    ext = os.path.splitext(target)[1].lower()
    accepted = convert.EXTENSIONS[fmt]
    if ext not in accepted:
        raise OutputRefusedError(
            f"{NAMES.get(format, format)} files end in {' or '.join(accepted)}, not {ext or 'nothing'}",
            detail={"rule": "output_extension"},
        )
    part = stepexport.part_path(target, token or os.urandom(8).hex())
    nested = tuple(nested)
    stem = reading.export_stem(path, nested)
    left_out: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    with _opened(path, within or folder, nested) as doc:
        source = doc.format if isinstance(doc, ModelDocument) else "solidworks"
        if source in ("solidworks", "parasolid"):
            model = stepexport.step_of(
                doc, path, folder, nested, configuration, allow_partial=allow_partial, outside=outside
            )
            left_out = [
                {"name": b.name, "reason": b.reason, "message": b.message}
                for b in model.bodies
                if not b.written
            ][: stepexport.MAX_LISTED]
            warnings = [{"code": w.code, "message": w.message} for w in model.warnings]
            with open_model(step_bytes(model), name=stem + ".step") as step_doc:
                result = convert.convert_document(step_doc, part, format)
        else:
            result = convert.convert_document(doc, part, format)
    try:
        stepexport._claim(part, target, overwrite)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    return {
        "file": target,
        "bytes": result.bytes,
        "format": format,
        "source_format": source,
        "backend": result.backend,
        "report": dict(result.report),
        "left_out": left_out,
        "warnings": warnings,
    }


def written_lines(data: dict[str, Any]) -> list[str]:
    """What the window says of a file Convert wrote, from :func:`convert_file`'s result."""
    r = data.get("report") or {}
    what = ", ".join(
        f"{r[k]} {label}"
        for k, label in (("solids", "solid(s)"), ("faces", "face(s)"))
        if isinstance(r.get(k), int)
    )
    name = NAMES.get(data.get("format"), str(data.get("format")))
    lines = [
        f"Wrote {data['file']}  ({reading.size_text(data['bytes'])})",
        f"{name} through Open CASCADE" + (f": {what}" if what else ""),
    ]
    left = int(r.get("open_shells") or 0) + int(r.get("free_faces") or 0)
    if left and data.get("source_format") == "iges":
        lines.append(
            f"Note: {left} group(s) of surfaces did not close into a solid when sewn at 0.01 mm; "
            "they are written as surfaces."
        )
    if r.get("valid") is False:
        lines.append("Note: Open CASCADE's check found faults in the shape, so parts of it may be wrong.")
    lines += stepexport.left_out_lines(data.get("left_out") or [])
    lines += [
        f"Note: {w['message']}"
        for w in data.get("warnings") or []
        if w["code"] not in ("step_approximated", "bodies_left_out", "step_bodies_left_out")
    ]
    return lines
