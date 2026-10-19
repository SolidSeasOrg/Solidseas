"""3D files of other formats in the viewer, without Qt: names, rows and measures.

A model file (any format :mod:`solidseas.formats` reads other than SOLIDWORKS,
``docs/API.md`` 3.20) is read in the window's worker pool (:mod:`.modeljobs`) and,
for the 3D view, in the mesh process (:func:`.mesh3d.read_model_scene`); the window
only receives JSON, PNG images SolidSeas wrote and vertex buffers. What both sides
must agree on lives here:

* :func:`path_ids` names each node of a model's tree as the details panel and the
  3D view name an assembly's instances: the names of its ancestors and its own,
  joined by ``/`` (a name's own ``/`` encoded), so a pick in the view finds its row
  on the Components tab and the exploded view groups by the top-level component
  (:mod:`.explode`). Siblings of one name are told apart as ``box (2)``.
* :func:`components_data` turns the tree of a ``model_summary`` into the shape of
  the ``components`` data of a SOLIDWORKS assembly, which the Components tab
  already shows: one instance row per node, with its position in the model's frame,
  and the Files table. An Alibre component's file is its document GUID, the key of
  its reference; any other row stands for an object or a grouping inside the file
  itself, keyed :data:`OBJECT` or :data:`NODE` (:func:`is_internal`), which no
  Go to file or 3D Print entry is offered for.
* :func:`references_data` gives an Alibre assembly's references (and an OBJ's
  material libraries, a glTF's buffers) in the shape of the ``references`` data,
  each found file located against the opened folder as the References tab and Open
  file expect.
* :func:`scene_geometry` measures a :class:`solidseas.formats.Scene` for the
  Overview: objects, placed items and triangles, bodies and faces, and the box of
  the whole model in its own frame.

Nothing here imports Qt, so the worker pool and the mesh process use it as it is.
"""

import math
import os
from collections.abc import Iterable
from typing import Any

# The root id the opened folder has in a ``references`` match (.reading.ROOT_ID; not imported
# from there, so a worker importing this module does not load the command line with it).
ROOT_ID = "folder"

OBJECT = "object:"  # a file key for a mesh object inside the file: object:<index>
NODE = "node:"  # a file key for a grouping row inside the file (a STEP product, a 3MF component)
MAX_PATH_CHARS = 4000  # an instance id; a deeper one is cut and numbered
_RESOLVED = {"found": "resolved", "not_found": "missing"}
_RULES = {"document_guid": "document_guid", "name": "name_index"}
Mat = tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]
IDENTITY: Mat = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
# Formats whose reader keeps each object in a frame of its own and turns it Z up in the
# placements of the tree's top nodes (glTF: Y up, +90 degrees about X; solidseas.formats.gltf.Z_UP).
# The Components tab shows rotations with that turn taken out, as a 3MF of the same scene reads.
FRAME_TURNED = frozenset({"gltf"})
_Z_UP: Mat = ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0))
_Z_DOWN: Mat = ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0))


def _times(a: Mat, b: Mat) -> Mat:
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))  # type: ignore[return-value]


def _apply(a: Mat, v: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        a[0][0] * v[0] + a[0][1] * v[1] + a[0][2] * v[2],
        a[1][0] * v[0] + a[1][1] * v[1] + a[1][2] * v[2],
        a[2][0] * v[0] + a[2][1] * v[1] + a[2][2] * v[2],
    )


def is_internal(key: str | None) -> bool:
    """Whether a file key stands for something inside the file shown (an object or a
    grouping of a model file) rather than for a file of its own."""
    return bool(key) and (key.startswith(OBJECT) or key.startswith(NODE))  # type: ignore[union-attr]


def _label(name: str | None, node: dict[str, Any]) -> str:
    text = (name or "").strip() or f"{node.get('kind') or 'node'} {node.get('id')}"
    return text.replace("%", "%25").replace("/", "%2F")


def unlabel(label: str) -> str:
    """One name of an instance id as it reads: its ``/`` and ``%`` decoded."""
    return label.replace("%2F", "/").replace("%25", "%")


def _roots(nodes: list[dict[str, Any]]) -> tuple[list[str], dict[str | None, list[dict[str, Any]]]]:
    """The ids of the nodes that stand at the top of the rows, and every node's children.
    A tree with one root shows that root's children (the file itself is the root);
    a tree with several shows them all."""
    by_parent: dict[str | None, list[dict[str, Any]]] = {}
    ids = {n["id"] for n in nodes}
    for n in nodes:
        parent = n.get("parent") if n.get("parent") in ids else None
        by_parent.setdefault(parent, []).append(n)
    tops = by_parent.get(None, [])
    if len(tops) == 1:
        return [tops[0]["id"]], by_parent
    return [], by_parent


def _as_dict(p: tuple[Mat, tuple[float, float, float]]) -> dict[str, Any]:
    return {"rotation": [list(r) for r in p[0]], "translation_m": list(p[1])}


def fold(nodes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """The tree with each grouping that holds one object and nothing else (a STEP part
    occurrence over its one body, a 3MF component object over its mesh) folded into
    one node: the grouping's id, name and place, the object's ``object`` and colour, and
    ``object_name`` the object's own name. A part placed twice is then two instances
    of one part, not two sub-assemblies of a body each. A grouping that holds several
    bodies and nothing else (a multi-body part in a STEP assembly) is folded too, into
    one part: its first object's ``object``, every one in ``objects``, and no
    ``object_name``, so the row reads as the grouping. Also the folded objects' ids,
    each mapped to the id of the node it was folded into. The root of a one-root tree
    (the file itself) is never folded."""
    skip, by_parent = _roots(nodes)
    folded: dict[str, dict[str, Any]] = {}  # grouping id: its one object
    several: dict[str, list[dict[str, Any]]] = {}  # grouping id: its objects, two or more
    alias: dict[str, str] = {}

    def leaf(c: dict[str, Any]) -> bool:
        return (
            c.get("object") is not None
            and not c.get("file")
            and not by_parent.get(c["id"])
            and c.get("kind") in ("body", "object")
        )

    for n in nodes:
        kids = by_parent.get(n["id"], [])
        if n["id"] in skip or n.get("object") is not None or n.get("file") or not kids:
            continue
        if not all(leaf(c) for c in kids):
            continue
        if len(kids) == 1:
            folded[n["id"]] = kids[0]
        elif all(c.get("kind") == "body" for c in kids):  # a part's bodies, not objects placed apart
            several[n["id"]] = kids
        else:
            continue
        for c in kids:
            alias[c["id"]] = n["id"]
    if not alias:
        return nodes, {}
    out = []
    for n in nodes:
        if n["id"] in alias:
            continue
        kids = several.get(n["id"])
        if kids is not None:
            n = {
                **n,
                "object": kids[0]["object"],
                "objects": [c["object"] for c in kids],
                "color": n.get("color") or kids[0].get("color"),
                "object_name": None,
            }
        c = folded.get(n["id"])
        if c is not None:
            placement = n.get("placement")
            if c.get("placement") is not None:
                inner = _placement(c["placement"])
                placement = _as_dict(compose(_placement(placement), inner) if placement else inner)
            n = {
                **n,
                "object": c["object"],
                "color": n.get("color") or c.get("color"),
                "placement": placement,
                "object_name": c.get("name"),
            }
        out.append(n)
    return out, alias


def path_ids(nodes: list[dict[str, Any]]) -> dict[str, str]:
    """Each node's instance id (see the module notes): its ancestors' labels and its own,
    joined by ``/``, the root left out when there is one. A node at the top has no
    ancestor; the root of a one-root tree maps to "". An object folded into its grouping
    (:func:`fold`) has the grouping's id: one row and one instance stand for both."""
    nodes, alias = fold(nodes)
    skip, by_parent = _roots(nodes)
    out: dict[str, str] = {}
    stack: list[tuple[str | None, str]] = [(None, "")]
    while stack:
        parent, prefix = stack.pop()
        children = by_parent.get(parent, [])
        counts: dict[str, int] = {}
        for n in children:
            base = _label(n.get("name"), n)
            counts[base] = counts.get(base, 0) + 1
        seen: dict[str, int] = {}
        used: set[str] = set()
        for n in children:
            base = _label(n.get("name"), n)
            if n["id"] in skip:
                label = ""
            elif counts[base] > 1:
                seen[base] = seen.get(base, 0) + 1
                label = f"{base} ({seen[base]})"
            else:
                label = base
            while label and label in used:  # a name that reads like another's number
                label += f" #{n['id']}"
            used.add(label)
            path = label if not prefix else (f"{prefix}/{label}" if label else prefix)
            if len(path) > MAX_PATH_CHARS:
                path = f"{path[: MAX_PATH_CHARS // 2]}... #{n['id']}"
            out[n["id"]] = path
            stack.append((n["id"], path))
    for child, parent in alias.items():
        if parent in out:
            out[child] = out[parent]
    return out


def _placement(p: dict[str, Any] | None) -> tuple[Mat, tuple[float, float, float]]:
    if not p:
        return IDENTITY, (0.0, 0.0, 0.0)
    r = p.get("rotation") or IDENTITY
    t = p.get("translation_m") or (0.0, 0.0, 0.0)
    return (
        tuple(tuple(float(v) for v in row) for row in r),  # type: ignore[return-value]
        (float(t[0]), float(t[1]), float(t[2])),
    )


def compose(
    outer: tuple[Mat, tuple[float, float, float]], inner: tuple[Mat, tuple[float, float, float]]
) -> tuple[Mat, tuple[float, float, float]]:
    """``inner`` (a placement in ``outer``'s component frame) seen from ``outer``'s frame."""
    a, t = outer
    b, u = inner
    rot = tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))
    moved = tuple(a[i][0] * u[0] + a[i][1] * u[1] + a[i][2] * u[2] + t[i] for i in range(3))
    return rot, moved  # type: ignore[return-value]


def file_key(n: dict[str, Any]) -> str:
    if n.get("file"):
        return str(n["file"])
    if n.get("object") is not None:
        return f"{OBJECT}{n['object']}"
    return f"{NODE}{n['id']}"


def _ref_file_name(ref: dict[str, Any] | None) -> str | None:
    res = (ref or {}).get("resolution") or {}
    if res.get("path"):
        return os.path.basename(str(res["path"]).replace("\\", "/"))
    return (ref or {}).get("name")


def _doc_type_of(name: str | None) -> str:
    ext = os.path.splitext(name or "")[1].lower()
    return "assembly" if ext == ".ad_asm" else "part"


def components_data(summary: dict[str, Any]) -> dict[str, Any] | None:
    """The ``components`` data of a SOLIDWORKS assembly (``docs/API.md`` 5.5) made from a
    model file's ``model_summary`` (with its tree and references): instance rows with
    their positions in the model's frame, and the Files table. None when the summary
    has no tree."""
    tree = summary.get("tree")
    if not tree:
        return None
    raw = list(tree.get("nodes") or [])
    ids = path_ids(raw)
    nodes, _alias = fold(raw)
    refs = {r["key"]: r for r in summary.get("references") or []}
    skip, by_parent = _roots(nodes)
    files: dict[str, dict[str, Any]] = {}
    depth = 0
    turn = summary.get("format") in FRAME_TURNED

    def shown(p: tuple[Mat, tuple[float, float, float]], level: int, *, placed: bool):
        """A placement as the Rotation column reads it: for a format whose objects stay in a
        frame of their own (glTF, Y up), the node's rotation expressed in the model's Z-up
        frame, the reader's turn taken out (see :data:`FRAME_TURNED`)."""
        if not turn:
            return p
        rot, t = p
        if placed or level == 1:  # the turn is the first factor: Z R, so Z R Z^-1 = (Z R) Z^-1
            return _times(rot, _Z_DOWN), t
        return _times(_times(_Z_UP, rot), _Z_DOWN), _apply(_Z_UP, t)

    def node_data(n: dict[str, Any], placed: tuple[Mat, tuple[float, float, float]], level: int):
        nonlocal depth
        depth = max(depth, level)
        if turn and level == 1 and n.get("placement") is None:
            local = (_Z_UP, (0.0, 0.0, 0.0))  # placed with the reader's turn alone
        else:
            local = _placement(n.get("placement"))
        here = compose(placed, local)
        key = file_key(n)
        ref = refs.get(n.get("file") or "")
        f = files.get(key)
        if f is None:
            if ref is not None:
                name = _ref_file_name(ref)
                stored = ref.get("stored")
                doc_type = _doc_type_of(name)
            else:
                name, stored = n.get("object_name") or n.get("name") or key, None
                doc_type = "part" if key.startswith(OBJECT) else "assembly"
            f = files[key] = {
                "key": key,
                "stored_path": stored,
                "file_name": name,
                "doc_type": doc_type,
                "direct": level == 1,
                "virtual": False,
                "imported": False,
                "nested": None,
                "embedded": None,
                "embedded_in_subassembly": False,
                "configurations_used": [],
                "instances": 0,
                "instances_unsuppressed": 0,
                "instances_in_bom": 0,
                "per_configuration": None,
                "sources": [],
                "resolution": None,
            }
        f["instances"] += 1
        f["instances_unsuppressed"] += 1
        f["instances_in_bom"] += 1
        f["direct"] = f["direct"] or level == 1
        children = [node_data(c, here, level + 1) for c in by_parent.get(n["id"], [])]
        ident = ids.get(n["id"]) or n["id"]
        return {
            "id": ident,
            "parent": None,
            "name": unlabel(ident.rpartition("/")[2]),  # "box (2)" where siblings share a name
            "component": n.get("name"),
            "number": None,
            "depth": level,
            "file": key,
            "doc_type": f["doc_type"],
            "configuration": None,
            "suppressed": False,
            "hidden": False,
            "excluded_from_bom": False,
            "virtual": False,
            "transform": None
            if n.get("placement") is None
            else {"stored": None, **_as_dict(shown(local, level, placed=False)), "scale": 1.0},
            "placement": _as_dict(shown(here, level, placed=True)),
            "children_state": "described" if children else "none",
            "children": children,
            "kind": n.get("kind"),
            "color": n.get("color"),
        }

    top_nodes: list[dict[str, Any]] = []
    for root in skip:
        top_nodes.extend(by_parent.get(root, []))
    if not skip:
        top_nodes = by_parent.get(None, [])
    origin = (IDENTITY, (0.0, 0.0, 0.0))
    children = [node_data(n, origin, 1) for n in top_nodes]
    count = sum(1 for n in nodes if n["id"] not in skip)  # a folded grouping and object count once
    # The Files table lists what instances are of: the objects and the files the model names. A
    # grouping (a STEP product holding bodies, a 3MF component) is a row of the instances only.
    listed = [f for k, f in files.items() if not k.startswith(NODE)]
    return {
        "configuration": None,
        "configuration_source": "none",
        "configurations_described": [],
        "children_state": "described" if children else "none",
        "truncated": bool(tree.get("truncated")),
        "limits": None,
        "counts": {"nodes": count, "depth": depth, "files": len(listed)},
        "files": listed,
        "children": children,
        "warnings": [],
        "model": True,
    }


def _inside(path: str, folder: str) -> bool:
    try:
        return os.path.commonpath([os.path.normcase(path), os.path.normcase(folder)]) == os.path.normcase(
            folder
        )
    except ValueError:  # another drive
        return False


def located(path: str | None, document: str, folder: str) -> dict[str, Any] | None:
    """Where a file a model file names was found, as the References tab and Go to file
    expect: ``{"root": ROOT_ID, "path": rel}`` in the opened ``folder``, else ``{"root":
    None, "path": absolute}``. ``path`` is relative to the ``document``'s folder or
    absolute."""
    if not path:
        return None
    full = path if os.path.isabs(path) else os.path.join(os.path.dirname(document), *path.split("/"))
    full = os.path.normpath(full)
    base = os.path.normpath(os.path.abspath(folder))
    if _inside(full, base):
        return {"root": ROOT_ID, "path": os.path.relpath(full, base).replace(os.sep, "/")}
    return {"root": None, "path": full}


def references_data(summary: dict[str, Any], document: str, folder: str) -> dict[str, Any]:
    """The ``references`` data (``docs/API.md`` 5.6) of a model file's references, each
    found file located against the opened ``folder`` (:func:`located`). Version notes
    of an Alibre component are the resolution's warnings."""
    refs = summary.get("references") or []
    warn_by_code = {w.get("code"): w for w in summary.get("warnings") or []}
    files = []
    counts: dict[str, int] = {}
    for r in refs:
        res = r.get("resolution") or {}
        status = _RESOLVED.get(res.get("status") or "", res.get("status") or "missing")
        counts[status] = counts.get(status, 0) + 1
        warnings = []
        for code in ("component_newer", "component_older", "component_ambiguous", "component_found_by_name"):
            if code in warn_by_code and status == "resolved":
                warnings.append({"code": code, "message": warn_by_code[code].get("message") or ""})
        name = _ref_file_name(r)
        files.append(
            {
                "key": r["key"],
                "stored_path": r.get("stored"),
                "file_name": name,
                "doc_type": _doc_type_of(name) if r.get("kind") == "component" else None,
                "direct": True,
                "kind": r.get("kind"),
                "resolution": {
                    "status": status,
                    "match": located(res.get("path"), document, folder) if status == "resolved" else None,
                    "rule": _RULES.get(res.get("found_by") or "", res.get("found_by")),
                    "confidence": None,
                    "identity": f"version {res['version']}" if res.get("version") else None,
                    "warnings": warnings,
                    "candidates": [],
                },
            }
        )
    return {
        "files": files,
        "resolution": {"counts": counts, "outside_roots": False, "index_partial": False},
    }


# --------------------------------------------------------------------------- measures
def _box_of(positions) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    if len(positions) < 3:
        return None
    xs, ys, zs = positions[0::3], positions[1::3], positions[2::3]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def placed_box(placement, box) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """``box`` (an object's own coordinates) with its eight corners placed."""
    lo, hi = box
    pts = [placement.apply((x, y, z)) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    return (
        (min(q[0] for q in pts), min(q[1] for q in pts), min(q[2] for q in pts)),
        (max(q[0] for q in pts), max(q[1] for q in pts), max(q[2] for q in pts)),
    )


def union(boxes: Iterable[tuple[tuple[float, ...], tuple[float, ...]]]):
    lo, hi = [math.inf] * 3, [-math.inf] * 3
    for b in boxes:
        for i in range(3):
            lo[i] = min(lo[i], b[0][i])
            hi[i] = max(hi[i], b[1][i])
    if lo[0] == math.inf:
        return None
    return (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])


def scene_geometry(scene) -> dict[str, Any]:
    """What the Overview says of a model's geometry, from its scene: objects, placed
    items, triangles (placed, every item's), vertices (of the objects), bodies, faces
    and faces done, what the meshes came from, the box of the whole model in metres
    and its size in millimetres, what was cut short and what was left out."""
    boxes = [_box_of(o.positions) for o in scene.objects]
    placed: list[Any] = []
    triangles = 0
    for it in scene.items:
        if not 0 <= it.object < len(scene.objects):
            continue
        triangles += scene.objects[it.object].n_triangles
        b = boxes[it.object]
        if b is not None:
            placed.append(placed_box(it.placement, b))
    box = union(placed)
    counts = scene.counts or {}
    skipped = []
    for s in scene.skipped[:200]:
        if hasattr(s, "reason") and hasattr(s, "instance"):
            skipped.append({"instance": s.instance, "reason": s.reason, "message": getattr(s, "message", "")})
        else:  # a face the tessellation left out
            skipped.append({"instance": None, "reason": "face", "message": str(getattr(s, "reason", ""))})
    return {
        "objects": len(scene.objects),
        "items": len(scene.items),
        "triangles": triangles,
        "vertices": sum(o.n_vertices for o in scene.objects),
        "bodies": counts.get("bodies"),
        "faces": counts.get("faces"),
        "faces_done": counts.get("faces_done"),
        "components": counts.get("components"),
        "sources": sorted({o.source for o in scene.objects}),
        "box_m": None if box is None else [list(box[0]), list(box[1])],
        "size_mm": None if box is None else [(box[1][i] - box[0][i]) * 1000.0 for i in range(3)],
        "truncated": list(scene.truncated),
        "skipped": skipped,
        "skipped_count": len(scene.skipped),
        "warnings": [{"code": w.code, "message": w.message} for w in scene.warnings],
    }


__all__ = [
    "NODE",
    "OBJECT",
    "components_data",
    "compose",
    "file_key",
    "is_internal",
    "located",
    "path_ids",
    "placed_box",
    "references_data",
    "scene_geometry",
    "union",
    "unlabel",
]
