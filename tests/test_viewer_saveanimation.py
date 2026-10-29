"""Save Animation (``solidseas_app.viewer.animationaction``): the frames drawn offscreen on
the real display, and a run from options to the saved clip with a stand-in helper."""

import json
import os

import pytest

from gl_support import run_gl
from solidseas_app.viewer.animation import AnimationOptions, frames
from support import FIXTURES, fixture_path
from test_viewer import app, needs_qt  # noqa: F401  (the Qt application, as a fixture)

uses_qt = pytest.mark.usefixtures("app")  # the Qt application, for the tests that need it

O16 = "o16_asm_features.SLDASM"

_GL_FRAMES = """
import os
from solidseas_app.viewer import mesh3d
from solidseas_app.viewer.animation import AnimationOptions, frames
from PySide6.QtGui import QImage
scene = mesh3d.read_assembly_scene(sys.argv[1], sys.argv[2], sys.argv[2], 1_000_000)["data"]
view = view3d.ModelView()
view.resize(400, 300)
view.set_assembly(scene)
view.grabFramebuffer()
before = (view.camera_state(), view.explode)
plan = frames(AnimationOptions(seconds=1, fps=6, size="640x360"), view.camera_state())
n = view.render_frames(plan, (640, 360), "#204060", sys.argv[3])
names = sorted(os.listdir(sys.argv[3]))
images = [QImage(os.path.join(sys.argv[3], k)) for k in names]
corner = images[0].pixelColor(0, 0).name()
def edge_clear(i):
    w, h = i.width(), i.height()
    edge = [(x, 0) for x in range(w)] + [(x, h - 1) for x in range(w)]
    edge += [(0, y) for y in range(h)] + [(w - 1, y) for y in range(h)]
    return all(i.pixelColor(x, y).name() == "#204060" for x, y in edge)
clear = [edge_clear(i) for i in images]
print(json.dumps({"n": n, "names": names, "size": [images[0].width(), images[0].height()],
    "corner": corner, "distinct": len({bytes(i.constBits()) for i in images}),
    "kept": (view.camera_state(), view.explode) == before, "error": view.error, "clear": clear}))
"""


@needs_qt
def test_the_frames_are_drawn_offscreen_at_the_size_chosen(tmp_path):
    out = run_gl(_GL_FRAMES, str(fixture_path(O16)), str(FIXTURES), str(tmp_path))
    assert out["error"] is None and out["n"] == 6
    assert out["names"] == [f"frame{i:05d}.png" for i in range(6)]
    assert out["size"] == [640, 360] and out["corner"] == "#204060"
    assert out["distinct"] >= 5, "the camera turns between frames"
    assert out["kept"], "the view's own camera and explode are left as they were"
    assert all(out["clear"]), "the assembly stays inside every frame, exploded too"


_GL_FRAMES_REPAINTED = """
from PySide6.QtWidgets import QMainWindow
from solidseas_app.viewer import mesh3d
from solidseas_app.viewer.animation import AnimationOptions, frames
scene = mesh3d.read_assembly_scene(sys.argv[1], sys.argv[2], sys.argv[2], 1_000_000)["data"]
window = QMainWindow()
view = view3d.ModelView()
window.setCentralWidget(view)
window.resize(400, 300)
window.show()
view.set_assembly(scene)
view.grabFramebuffer()
plan = frames(AnimationOptions(seconds=1, fps=6, size="640x360"), view.camera_state())
def progress(index):
    view.update()
    app.processEvents()
    return True
n = view.render_frames(plan, (640, 360), "#204060", sys.argv[3], progress)
print(json.dumps({"n": n, "error": view.error}))
"""


@needs_qt
def test_each_frame_is_drawn_in_the_views_context_after_the_window_repaints(tmp_path):
    """Save Animation's progress dialog runs the event loop after each frame, and a repaint
    there leaves the window's own context current, which has none of the view's vertex
    arrays: drawn in it, the next frame crashed NVIDIA's driver. Each frame makes the view's
    context current again."""
    out = run_gl(_GL_FRAMES_REPAINTED, str(fixture_path(O16)), str(FIXTURES), str(tmp_path))
    assert out["error"] is None and out["n"] == 6


class _View:
    can_explode = True

    def __init__(self):
        self.drawn = []

    def camera_state(self):
        return {"yaw": 45.0, "pitch": 35.26, "half_height": 0.1, "target": [0, 0, 0]}

    def render_frames(self, planned, size, background, folder, progress=None):
        for f in planned:
            open(os.path.join(folder, f"frame{f.index:05d}.png"), "wb").close()
            self.drawn.append((f.index, size, background))
            if progress is not None and progress(f.index) is False:
                break
        return len(self.drawn)


class _Helper:
    def __init__(self):
        self.asked = []
        self.closed = False

    def request(self, op, args):
        self.asked.append((op, args))
        target = os.path.join(args["out_dir"], args["name"])
        with open(target, "w") as fh:
            json.dump(args, fh)
        return {"path": target, "bytes": os.path.getsize(target), "encoder": "h264_mf"}

    def close(self, timeout=None):
        self.closed = True


@needs_qt
@uses_qt
def test_a_run_draws_encodes_and_saves_the_clip_then_cleans_up(tmp_path, monkeypatch):
    from solidseas_app import extensions as X
    from solidseas_app.viewer.animationaction import SaveAnimation

    monkeypatch.setattr(X, "data_dir", lambda: str(tmp_path / "data"))
    view, helper, said = _View(), _Helper(), []
    target = tmp_path / "saved" / "spin"
    target.parent.mkdir()
    run = SaveAnimation(
        None,
        view,
        "o16",
        start_helper=lambda: helper,
        ask_path=lambda start, filters: str(target),
        say=lambda title, text: said.append(text),
        run_in_background=lambda work, done: done(work()),
    )
    assert run.run(AnimationOptions(seconds=1, fps=10, size="640x360"))
    assert len(view.drawn) == 10 and view.drawn[0][1:] == ((640, 360), "#ffffff")
    ((op, args),) = helper.asked
    assert op == "encode" and args["fps"] == 10 and args["format"] == "mp4" and helper.closed
    assert run.result["path"] == str(target) + ".mp4" and run.result["frames"] == 10
    assert json.loads((tmp_path / "saved" / "spin.mp4").read_text())["name"] == "clip.mp4"
    assert said == ["Saved spin.mp4: 10 frames."]
    assert os.listdir(tmp_path / "data" / "temp") == [], "the frames and the helper's copy are removed"


@needs_qt
@uses_qt
def test_a_helper_that_fails_or_writes_elsewhere_saves_nothing(tmp_path, monkeypatch):
    from solidseas_app import extensions as X
    from solidseas_app.viewer.animationaction import SaveAnimation

    monkeypatch.setattr(X, "data_dir", lambda: str(tmp_path / "data"))
    said = []

    class Elsewhere(_Helper):
        def request(self, op, args):
            stray = tmp_path / "stray.mp4"
            stray.write_text("x")
            return {"path": str(stray), "bytes": 1}

    class Fails(_Helper):
        def request(self, op, args):
            raise RuntimeError("ffmpeg could not write the clip")

    for helper in (Elsewhere(), Fails()):
        run = SaveAnimation(
            None,
            _View(),
            "o16",
            start_helper=lambda helper=helper: helper,
            ask_path=lambda start, filters: str(tmp_path / "out.gif"),
            say=lambda title, text: said.append(text),
            run_in_background=lambda work, done: done(_call(work)),
        )
        assert run.run(AnimationOptions(seconds=1, fps=5, format="gif"))
        assert run.result is None and helper.closed
    assert not (tmp_path / "out.gif").exists()
    assert "wrote somewhere it was not given" in said[0] and "could not write the clip" in said[1]
    assert os.listdir(tmp_path / "data" / "temp") == []


def _call(work):
    try:
        return work()
    except Exception as exc:
        return exc


@needs_qt
@uses_qt
def test_cancelling_the_save_dialog_starts_nothing():
    from solidseas_app.viewer.animationaction import SaveAnimation

    view = _View()
    run = SaveAnimation(None, view, "o16", start_helper=pytest.fail, ask_path=lambda s, f: "")
    assert not run.run(AnimationOptions()) and view.drawn == []


def test_the_plan_matches_what_the_dialog_defaults_to():
    assert (
        len(frames(AnimationOptions(), {"yaw": 0, "pitch": 30, "half_height": 1, "target": [0, 0, 0]})) == 180
    )


@needs_qt
def test_save_animation_is_offered_only_while_the_video_extension_is_on(monkeypatch):
    from solidseas_app import extensions as X
    from solidseas_app.viewer import animationaction as A

    monkeypatch.setattr(X, "is_on", lambda ext, state, **k: ext == "video" and "video" in state.on)
    monkeypatch.setattr(X, "read_state", lambda: X.ExtensionState(frozenset({"video"})))
    assert A.available(_View()) and not A.available(None) and not A.available(object())
    monkeypatch.setattr(X, "read_state", lambda: X.ExtensionState())
    assert not A.available(_View())
