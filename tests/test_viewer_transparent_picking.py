"""Picking through transparent parts, wherever the 3D view runs.

A transparent part ranks in the id pass at the far side of its own box, so a click
picks a part inside it or in front, and the part itself over what lies behind the box.
Its fragment shader moves the depth there (``FAR_DEPTH``), which OpenGL ES can do only
with ``GL_EXT_frag_depth``: without it the view now ranks the part the same way through
the stencil, its box's far side drawn where its mesh is. And on OpenGL ES that shader
may run in medium precision, perhaps half floats, so it holds no constant such floats
cannot (it held 1e30 and 1e-20). These tests pick one scene on desktop OpenGL and on
OpenGL ES, each way, and check every way picks alike; and they check the shader's
medium-precision constants.
"""

import re

import pytest

from gl_support import run_gl
from test_viewer import _wait, app, needs_qt  # noqa: F401  (the Qt application, as a fixture)

_GL_RANKS = """
import os
from array import array
from PySide6.QtGui import QSurfaceFormat
if os.environ.get("SOLIDSEAS_TEST_GLES"):
    fmt = QSurfaceFormat.defaultFormat()
    fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGLES)
    fmt.setVersion(3, 0)
    QSurfaceFormat.setDefaultFormat(fmt)
from solidseas_app.viewer import mesh3d
from solidseas_app.viewer.view3d import Renderer, ModelView, Scene, _box_mesh
from solidseas_app.viewer.explode import instance_bounds


def cube(lo, hi):
    sx, sy, sz = (hi[i] - lo[i] for i in range(3))
    return array("f", [sx, 0, 0, 0, 0, sy, 0, 0, 0, 0, sz, 0, lo[0], lo[1], lo[2], 1]).tobytes()


m = _box_mesh()
mesh = mesh3d.MeshBuffers(m.positions, m.normals, m.indices[: 4 * 36], m.n_vertices, 12, m.bbox)
# The housing, a part inside it, and a part behind its box, seen from the front.
placed = cube((-1, -1, -1), (1, 1, 1)) + cube((-0.3, -0.3, -0.3), (0.3, 0.3, 0.3))
placed += cube((0.4, -0.2, -3), (0.9, 0.3, -2.5))
colours = array("f", [0.8, 0.3, 0.2, 0.2, 0.6, 0.9, 0.3, 0.8, 0.3]).tobytes()
scene = Scene([mesh], [placed], [colours], ((-1, -1, -3), (1, 1, 1)),
              ids=[["housing-1", "inner-1", "behind-1"]], bounds=[instance_bounds(mesh.bbox, placed)])
out = {"gl": True}
for name, frag_depth, highp in (("far", True, True), ("medium", True, False), ("stencil", False, True)):
    Renderer.allow_frag_depth, Renderer.allow_highp = frag_depth, highp
    for instanced in (True, False):
        Renderer.allow_instancing = instanced
        v = ModelView()
        v.resize(240, 240)
        v.show()
        v.set_scene(scene)
        v.set_view("front")
        app.processEvents()
        v.grabFramebuffer()
        if v.renderer is None:  # no context of the kind asked for, or no renderer on it: stop here
            ctx = v.context()
            es = bool(ctx and ctx.isOpenGLES())
            said = None
            if ctx is not None:  # the context's format only: a GL call on it can crash the driver
                fmt = ctx.format()
                said = (
                    f"{fmt.renderableType().name} {fmt.majorVersion()}.{fmt.minorVersion()}"
                    f" {fmt.profile().name}, valid {ctx.isValid()}"
                )
            out[f"{name} {instanced}"] = {"es": es, "made": False, "error": v.error, "gl": said}
            print(json.dumps(out))
            raise SystemExit(0)
        r = {"es": v.context().isOpenGLES(), "rank_far": v.renderer.rank_far}

        def at(p):
            nx, ny, _ = v.camera.project(p)
            return (nx + 1) * 120, (1 - ny) * 120

        spots = {"inner": (0.0, 0.0, 0.3), "over_behind": (0.65, 0.05, 1.0), "housing": (-0.65, 0.6, 1.0)}
        for transparent in (False, True):
            v.set_looks([0.5 if transparent else 1.0, 1.0, 1.0], None)
            got = {k: v.instance_at(*at(p), radius=0) for k, p in spots.items()}
            surface = v.surface_at(*at(spots["housing"]), radius=0)
            got["housing_depth"] = None if surface is None else round(surface[2], 2)
            r["transparent" if transparent else "opaque"] = got
        r["error"] = v.error
        out[f"{name} {instanced}"] = r
        v.close()
Renderer.allow_frag_depth = Renderer.allow_highp = Renderer.allow_instancing = True
print(json.dumps(out))
"""


@needs_qt
@pytest.mark.parametrize("es", [False, True], ids=["desktop OpenGL", "OpenGL ES"])
def test_a_transparent_part_ranks_at_the_far_side_of_its_box_every_way(es):
    out = run_gl(_GL_RANKS, env={"SOLIDSEAS_TEST_GLES": "1"} if es else {})
    first = out["far True"]
    if es and not first["es"]:
        why = first.get("error") or "the context made is desktop OpenGL"
        pytest.skip(f"no OpenGL ES context can be made here ({why})")
    if es and not first.get("made", True):
        # Seen on a desktop NVIDIA driver: the OpenGL ES context it gives is not valid (and a
        # GL call on it crashes), so no renderer starts. Here every context is asked for as
        # OpenGL ES, so gl_status finds none either and the view leaves it to the preview,
        # which makes no view then; the viewer never asks for OpenGL ES there.
        why = first.get("error") or "no OpenGL ES context can be made"
        pytest.skip(f"no working OpenGL ES context here: {why} ({first.get('gl')})")
    for name in ("far", "medium", "stencil"):
        for instanced in ("True", "False"):
            r = out[f"{name} {instanced}"]
            assert r.get("made", True) and r["error"] is None and r["es"] == es, r
            assert r["rank_far"] == (name != "stencil"), r
            # Opaque, the housing is picked everywhere it is drawn, at its near side.
            assert r["opaque"] == {
                "inner": 0,
                "over_behind": 0,
                "housing": 0,
                "housing_depth": 1.0,
            }, (name, instanced, r)
            # Transparent: the part inside it is picked through it, the housing over the part
            # behind its box, and a turn about the housing still turns about its own surface.
            assert r["transparent"] == {
                "inner": 1,
                "over_behind": 0,
                "housing": 0,
                "housing_depth": 1.0,
            }, (name, instanced, r)


def test_the_id_pass_holds_no_constant_half_floats_cannot():
    """What the fragment shader of the id pass computes in medium precision on OpenGL ES
    (perhaps half floats: at most 65504, and nothing below about 6e-5 held exactly but 0)
    holds no constant beyond that; the slope below which the line of sight runs along a
    side of the box is 1e-3 there and stays 1e-20 at high precision."""
    pytest.importorskip("PySide6")
    from solidseas_app.viewer import view3d

    text = re.sub(r"/\*.*?\*/", "", view3d._FRAGMENT, flags=re.S)
    numbers = [float(v) for v in re.findall(r"(?<![\w.])(\d+\.\d*(?:e[-+]?\d+)?|\d+e[-+]?\d+)", text)]
    assert numbers and all(v == 0 or 6.1e-5 <= abs(v) <= 65504 for v in numbers), sorted(set(numbers))
    assert "1e30" not in view3d._FRAGMENT and "1e29" not in view3d._FRAGMENT

    class FakeES:
        def __init__(self, extensions):
            self.extensions = extensions

        def format(self):
            from PySide6.QtGui import QSurfaceFormat

            return QSurfaceFormat()

        def isOpenGLES(self):
            return True

        def hasExtension(self, name):
            return name in self.extensions

    es = FakeES({b"GL_EXT_frag_depth", b"GL_OES_standard_derivatives"})
    _vert, frag = view3d._headers(es, far_depth=True)
    assert "#define PARALLEL 1e-20" in frag and "#define PARALLEL 1e-3" in frag  # high, else medium
    _vert, frag = view3d._headers(es, far_depth=True, highp=False)
    assert "highp" not in frag and "#define PARALLEL 1e-3" in frag
    assert view3d._headers(FakeES(set()), far_depth=True) is None  # no GL_EXT_frag_depth: the stencil
    assert view3d._headers(es, far_depth=True, frag_depth=False) is None


@needs_qt
@pytest.mark.usefixtures("app")
def test_a_context_the_driver_could_not_make_is_reported_without_a_gl_call(monkeypatch, caplog):
    """On a desktop NVIDIA driver an OpenGL ES 3.0 request gave the view a context that is
    not valid: Qt calls no initializeGL, so the view drew nothing and said nothing, and a GL
    call on that context ended the program (SolidSeas-m4uz). The view now says so, as it
    reports every other OpenGL failure, and logs it, reading only the context's own state."""
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QResizeEvent, QSurfaceFormat
    from PySide6.QtWidgets import QApplication

    from solidseas_app.viewer import view3d

    class Broken:  # a context whose every GL call fails the test
        def isValid(self):
            return False

        def format(self):
            fmt = QSurfaceFormat()
            fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGLES)
            fmt.setVersion(3, 0)
            return fmt

        def __getattr__(self, name):
            raise AssertionError(f"the view called {name} on a context that does not work")

    view = view3d.ModelView()  # never shown: the context is the stand-in's
    failed: list[str] = []
    view.failed.connect(failed.append)
    monkeypatch.setattr(view, "context", lambda: None)
    view.resizeEvent(QResizeEvent(QSize(240, 240), QSize(0, 0)))
    assert view.error is None  # no context yet: not made, nothing to say
    monkeypatch.setattr(view, "context", Broken)
    monkeypatch.setattr(view3d, "gl_status", lambda: (False, "no OpenGL context can be made"))
    view.resizeEvent(QResizeEvent(QSize(240, 240), QSize(240, 240)))
    assert view.error is None  # none can be made here at all: the preview says so, and makes no view
    monkeypatch.setattr(view3d, "gl_status", lambda: (True, "a renderer, OpenGL 4.6"))
    with caplog.at_level("WARNING", logger="solidseas_app.viewer.view3d"):
        view.resizeEvent(QResizeEvent(QSize(240, 240), QSize(240, 240)))
        view.resizeEvent(QResizeEvent(QSize(300, 240), QSize(240, 240)))  # said once
    why = "the graphics driver could not make the OpenGL ES 3.0 context it asked for"
    assert view.renderer is None and view.error == why
    assert [r.getMessage() for r in caplog.records] == [f"3D view: {why}"]
    _wait(QApplication.instance(), lambda: failed)
    assert failed == [why]  # the preview shows it as it shows the other failures
    view.deleteLater()
