"""The window's worker jobs for 3D files of other formats (run in :mod:`.modelpool`).

Each job runs in a :class:`solidseas.workers.WorkerPool` worker: a process of its
own, below normal priority, with a memory cap and a deadline, which answers in
JSON and at most one binary frame. The window's process never parses a model
file; it gets these answers.

* :func:`details` is what the details panel shows first: the ``model_summary``
  (properties, tree and references), the Components tab's rows for an assembly
  (:func:`.modelview.components_data`) and the References tab's files
  (:func:`.modelview.references_data`).
* :func:`view` reads the model's geometry once, as the 3D view would (its stored
  display mesh first), and answers the Overview's measures
  (:func:`.modelview.scene_geometry`) and the Preview tab's image: the one the file
  stores, as a PNG SolidSeas wrote, else one rendered from that geometry
  (:func:`solidseas.render.render_preview`), as the binary frame.

The file is opened read-only ``within`` the folder the window names, through the
same path checks and settings as the library's own jobs (:func:`solidseas.jobs._open_model`).
Nothing here imports Qt.
"""

from typing import Any

from solidseas import model
from solidseas.errors import InvalidArgumentError, NoPreviewError, SolidSeasError
from solidseas.jobs import _open_model, _param

from . import modelview

DETAILS_JOB = "viewer_model_details"
VIEW_JOB = "viewer_model_view"
JOBS = {DETAILS_JOB: f"{__name__}:details", VIEW_JOB: f"{__name__}:view"}
VIEW_SECONDS = 30.0  # the geometry read, as the 3D view's own (mesh3d.BREP_SECONDS)
PREVIEW_SIDE = (768, 576)  # a rendered preview for the Preview tab
MAX_CAP = 50_000_000


def details(params: dict[str, Any]) -> dict[str, Any]:
    """``summary`` (``model_summary`` with its properties, tree and references),
    ``components`` (an assembly's rows, else None) and ``references`` (the files it
    names, located against ``folder``, else None) of the model file at ``path``."""
    folder = _param(params, "folder", (str,), required=True)
    path = _param(params, "path", (str,), required=True)
    with _open_model(params) as doc:
        summary = model.build_model_summary(doc, include=model.MODEL_SUMMARY_PARTS)
    components = modelview.components_data(summary) if summary.get("doc_type") == "assembly" else None
    refs = summary.get("references") or []
    references = modelview.references_data(summary, path, folder) if refs else None
    return {"summary": summary, "components": components, "references": references}


def _size(params: dict[str, Any], key: str, default: int) -> int:
    value = _param(params, key, (int,), default)
    if not 16 <= value <= 4096:
        raise InvalidArgumentError(f"{key} is from 16 to 4096", detail={"parameter": key})
    return value


def view(params: dict[str, Any]) -> tuple[dict[str, Any], bytes | None]:
    """``geometry`` (the Overview's measures, or None with ``geometry_error`` when the
    geometry could not be read) and ``preview`` (``source`` ``stored`` or
    ``rendered``, its size and whether it is ``partial``; None with
    ``preview_reason`` when there is none) of the model file at ``path``, the image as
    the binary frame. ``cap`` bounds the triangles read, as the 3D view's limit does;
    ``width`` and ``height`` size a rendered preview."""
    from solidseas.formats._source import preview_png
    from solidseas.render import render_preview

    cap = _param(params, "cap", (int,), 1_000_000)
    if not 1 <= cap <= MAX_CAP:
        raise InvalidArgumentError("cap is from 1 to 50,000,000", detail={"parameter": "cap"})
    width = _size(params, "width", PREVIEW_SIDE[0])
    height = _size(params, "height", PREVIEW_SIDE[1])
    out: dict[str, Any] = {"geometry": None, "geometry_error": None, "preview": None, "preview_reason": None}
    png = None
    with _open_model(params) as doc:
        scene = None
        try:
            scene = doc.scene(prefer="display", max_triangles=cap + 1, max_seconds=VIEW_SECONDS)
            out["geometry"] = modelview.scene_geometry(scene)
        except SolidSeasError as exc:
            out["geometry_error"] = model.error_info(exc)
        try:
            got = preview_png(doc.preview(), doc.limits)
        except SolidSeasError as exc:  # a damaged stored image: rendered instead, and said
            got = None
            out["preview_reason"] = f"the stored image could not be read ({exc})"[:300]
        if got is not None:
            png, w, h, stream = got
            out["preview"] = {"source": "stored", "width": w, "height": h, "stream": stream, "partial": False}
        elif scene is not None:
            try:
                r = render_preview(
                    scene, width=width, height=height, up_axis=doc.spec.up_axis, limits=doc.limits
                )
            except NoPreviewError:
                out["preview_reason"] = out["preview_reason"] or "the model holds no triangle to draw"
            else:
                png = r.data
                out["preview"] = {
                    "source": "rendered",
                    "width": r.width,
                    "height": r.height,
                    "stream": None,
                    "partial": r.partial or bool(scene.truncated),
                }
        else:
            out["preview_reason"] = (
                out["preview_reason"] or "the file stores no image and its geometry could not be read"
            )
    return out, png


__all__ = ["DETAILS_JOB", "JOBS", "VIEW_JOB", "details", "view"]
