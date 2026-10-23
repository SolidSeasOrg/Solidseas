"""Boxes for missing meshes kept out of the sort while something is transparent.

With a component made transparent, every box used to be sorted among the transparent
instances and drawn one at a time, three draws a box. Now a box wholly behind every
transparent instance along the line of sight, or wholly in front of them all, is drawn
in a batch, before or after the sorted pass, as the boxes are drawn when nothing is
transparent; only boxes that reach into the transparent instances' span are sorted. On
the real display, on both drawing paths, the picture is the one sorting every box gives.
"""

import pytest

from gl_support import run_gl
from test_viewer import needs_qt

_GL_BATCHES = """
from array import array
from solidseas_app.viewer import mesh3d
from solidseas_app.viewer.view3d import BOX_MESH, Renderer, ModelView, Scene, _box_mesh
from solidseas_app.viewer.explode import instance_bounds


def cube(lo, hi):
    sx, sy, sz = (hi[i] - lo[i] for i in range(3))
    return array("f", [sx, 0, 0, 0, 0, sy, 0, 0, 0, 0, sz, 0, lo[0], lo[1], lo[2], 1]).tobytes()


m = _box_mesh()
mesh = mesh3d.MeshBuffers(m.positions, m.normals, m.indices[: 4 * 36], m.n_vertices, 12, m.bbox)
unit = ((0, 0, 0), (1, 1, 1))
plate = cube((-0.3, -0.3, -0.1), (0.3, 0.3, 0.1))
# Behind the plate and in front of it, under it on the screen but never over one another;
# beside it, reaching into its span along the line of sight.
behind = [cube((x, -0.25, -1.1), (x + 0.08, -0.05, -0.9)) for x in (-0.25, -0.1, 0.05, 0.2)]
front = [cube((x, 0.05, 0.9), (x + 0.08, 0.25, 1.1)) for x in (-0.25, -0.1, 0.05, 0.2)]
beside = [cube((x, -0.1, -0.2), (x + 0.1, 0.1, 0.2)) for x in (-0.6, 0.5)]
boxes = b"".join(behind + front + beside)
n = len(behind) + len(front) + len(beside)
scene = Scene([mesh, BOX_MESH], [plate, boxes],
              [array("f", [0.8, 0.3, 0.2]).tobytes(), array("f", [0.72, 0.75, 0.78] * n).tobytes()],
              ((-0.7, -0.4, -1.1), (0.7, 0.4, 1.1)), ids=[["plate-1"], [f"box-{k}" for k in range(n)]],
              bounds=[instance_bounds(mesh.bbox, plate), instance_bounds(unit, boxes)], box_mesh=1)
out = {"gl": True}
for instanced in (True, False):
    Renderer.allow_instancing = instanced
    r = {}
    pictures = {}
    for batch in (True, False):
        Renderer.batch_boxes = batch
        v = ModelView()
        v.resize(320, 240)
        v.show()
        v.set_scene(scene)
        v.set_view("front")
        app.processEvents()
        opaque = v.grabFramebuffer()
        v.set_looks([0.5] + [1.0] * n, None)
        pictures[batch] = v.grabFramebuffer()
        r[f"changed_{batch}"] = pictures[batch] != opaque
        r[f"sorted_{batch}"] = v.renderer.sorted_items
        r[f"batched_{batch}"] = list(v.renderer.batched_boxes)
        r[f"error_{batch}"] = v.error
        if batch:  # everything transparent and hidden but one box behind: still drawn, alone in its batch
            v.set_looks([0.5] + [1.0] * n, [False, False] + [True] * (n - 1))
            v.grabFramebuffer()
            r["one_batched"] = list(v.renderer.batched_boxes)
            v.set_looks(None, None)
            r["back_to_opaque"] = v.grabFramebuffer() == opaque and v.renderer.batched_boxes == (0, 0)
        v.close()
    r["same_picture"] = pictures[True] == pictures[False]
    out[str(instanced)] = r
Renderer.batch_boxes = True
print(json.dumps(out))
"""


@needs_qt
def test_boxes_behind_or_in_front_of_what_is_transparent_are_drawn_in_batches():
    out = run_gl(_GL_BATCHES)
    for instanced in ("True", "False"):
        r = out[instanced]
        assert r["error_True"] is None and r["error_False"] is None, r
        assert r["changed_True"] and r["changed_False"], r  # the plate is drawn transparent
        assert (r["sorted_True"], r["batched_True"]) == (3, [4, 4]), r  # the plate and the two beside it
        assert (r["sorted_False"], r["batched_False"]) == (11, [0, 0]), r
        assert r["same_picture"], r
        assert r["one_batched"] == [1, 0] and r["back_to_opaque"], r


@pytest.mark.parametrize("name", ["BEHIND", "IN_FRONT", "SORTED"])
def test_the_batches_are_named(name):
    pytest.importorskip("PySide6")
    from solidseas_app.viewer import view3d

    assert {view3d.SORTED, view3d.BEHIND, view3d.IN_FRONT} == {0.0, 1.0, 2.0} and hasattr(view3d, name)
