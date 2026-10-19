"""Turning the SolidSeas Viewer's 3D view freely or as a turntable, and panning it.

The 3D view turned only as a turntable: about the model's Y axis, tilting no
further than straight above or below, never rolling. A model whose natural up
is not Y turned about a line slanting across the screen, and views past
straight above or below, or rolled, could not be reached. Free rotation, as
SOLIDWORKS does it, is now the default: a drag turns the model about the
screen's own axes, without limit, kept as three orthonormal axes. The turntable
stays as a setting and turns by the same yaw and pitch as before. What is new in
both is the point the model turns about: a fit, pan or zoom puts it in the middle
of the view at the depth of the model's centre, and it stays put while the model
turns, so a drag turns the same however many mouse moves it arrives in and
turning back undoes a turn.

Panning was reported broken too ("seems to only work in one axis"), so it was
measured on the real display before anything changed: real mouse events and
keys on the real widget, the drawn pixels read back. The model followed every
diagonal drag exactly on both screen axes, in both mouse styles and with
Ctrl+arrows, so panning itself needed no fix; the test that measured it stays
here as the regression test, in both rotation modes.

These tests check the camera's arithmetic (no Qt), the mouse, wheel and keys on
the widget, the setting, the Preferences dialog, the Settings menu and the help
under the view, then on the real display a diagonal pan, a free turn past
straight above (still drawn, still picked where drawn), and the self-test's
turn over the top in each mode.
"""

import json
import math
import os
import random
import sys
from pathlib import Path

import pytest

from gl_support import run_gl, run_self_test
from solidseas_app.viewer import mesh3d, viewmath
from support import FIXTURES, fixture_path
from test_viewer import Viewer, _show_3d, _state, _stub_view_factory, needs_qt

FREE, TURNTABLE = viewmath.FREE, viewmath.TURNTABLE
O02, O16 = "o02_boxA.SLDPRT", "o16_asm_features.SLDASM"
BOX = ((0.0, 0.0, 0.0), (0.04, 0.03, 0.01))  # the size of fixture o11, in metres


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from solidseas_app.viewer.app import use_system_fonts

    use_system_fonts()
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def viewer(app):
    v = Viewer(app)
    yield v
    v.close()


def _camera(mode: str = FREE, aspect: float = 1.5) -> viewmath.OrbitCamera:
    cam = viewmath.OrbitCamera(BOX, mode=mode)
    cam.aspect = aspect
    cam.reset()
    return cam


def _close(a, b, tol: float = 1e-12) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b, strict=True))


def _orthonormal(cam: viewmath.OrbitCamera, tol: float = 1e-12) -> bool:
    r, u, b = cam.axes
    dot = viewmath._dot
    return (
        all(abs(dot(v, v) - 1) <= tol for v in (r, u, b))
        and all(abs(dot(p, q)) <= tol for p, q in ((r, u), (r, b), (u, b)))
        and _close(viewmath._cross(r, u), b, tol)  # right-handed: right x up is toward the eye
    )


def _pixel(cam: viewmath.OrbitCamera, point, width: float, height: float) -> tuple[float, float]:
    nx, ny, _ = cam.project(point)
    return ((nx + 1) * width / 2, (1 - ny) * height / 2)


def _orientation(cam: viewmath.OrbitCamera) -> tuple[int, ...]:
    """An orientation turned in right angles from an axis-aligned one, as whole numbers."""
    r, u, _b = cam.axes
    return tuple(round(v) for v in (*r, *u))


# --------------------------------------------------------------------------- the camera, no Qt
def test_free_rotation_is_the_default_and_turns_about_the_screens_axes():
    assert viewmath.OrbitCamera().mode == FREE
    cam = _camera()
    r0, u0, b0 = cam.axes
    cam.rotate(50, 0)  # a drag to the right: about the screen's vertical axis, the front turning right
    angle = math.radians(50 * viewmath.DEGREES_PER_PIXEL)
    assert _close(cam.up, u0) and viewmath._dot(cam.back, b0) == pytest.approx(math.cos(angle))
    assert viewmath._dot(cam.back, r0) == pytest.approx(-math.sin(angle))  # the eye went left
    assert not cam.fitted
    r0, u0, b0 = cam.axes
    cam.rotate(0, 50)  # a drag down: about the screen's horizontal axis, the top tilting toward you
    assert _close(cam.right, r0) and viewmath._dot(cam.back, u0) == pytest.approx(math.sin(angle))
    r0, u0, b0 = cam.axes
    cam.rotate(30, 40)  # a diagonal drag of 50 pixels turns 20 degrees about the screen axis square to it

    def square(axes):
        r, u, _b = axes
        return viewmath._unit(viewmath._add(viewmath._mul(r, 40), viewmath._mul(u, 30)))

    assert viewmath._dot(cam.back, b0) == pytest.approx(math.cos(angle))
    assert _close(square(cam.axes), square((r0, u0, b0)))  # that axis stayed where it was
    assert _orthonormal(cam)

    # From an upright view the first move is the turntable's, in either direction.
    for dx, dy in ((30, 0), (0, 30), (-45, 0), (0, -45)):
        free, table = _camera(FREE), _camera(TURNTABLE)
        for c in (free, table):
            c.set_view("front")
            c.rotate(dx, dy)
        assert _close(free.back, table.back) and _close(free.up, table.up) and _close(free.right, table.right)


def test_free_rotation_goes_past_straight_above_to_every_view():
    cam = _camera()
    cam.set_view("front")
    cam.rotate(0, 90 / viewmath.DEGREES_PER_PIXEL)  # a drag down by 90 degrees: straight above
    assert _close(cam.back, (0, 1, 0)) and _close(cam.up, (0, 0, -1))
    cam.rotate(0, 90 / viewmath.DEGREES_PER_PIXEL)  # and on, without a stop: from behind, upside down
    assert _close(cam.back, (0, 0, -1)) and _close(cam.up, (0, -1, 0)) and _close(cam.right, (1, 0, 0))
    assert cam.yaw == pytest.approx(180) and cam.pitch == pytest.approx(0)  # the upright view from there
    cam.rotate(0, 180 / viewmath.DEGREES_PER_PIXEL)
    assert _close(cam.back, (0, 0, 1)) and _close(cam.up, (0, 1, 0))  # once round: as it started

    # Turned in right angles about the screen's axes, as the keys do with Shift, free rotation
    # reaches all 24 axis-aligned orientations; the turntable reaches only 12 of them, none
    # rolled or upside down.
    steps = ((90, 0), (-90, 0), (0, 90), (0, -90))
    for mode, count in ((FREE, 24), (TURNTABLE, 12)):
        start = _camera(mode)
        start.set_view("front")
        seen = {_orientation(start): start.state()}
        todo = [start.state()]
        while todo:
            state = todo.pop()
            for across, down in steps:
                c = viewmath.OrbitCamera(BOX, mode=mode)
                c.set_state(state)
                c.turn_model(across, down)
                key = _orientation(c)
                if key not in seen:
                    seen[key] = c.state()
                    todo.append(c.state())
        assert len(seen) == count, mode
        if mode == TURNTABLE:
            assert all(state["axes"][1][1] >= 0 for state in seen.values())  # its up never points down


def test_free_rotation_stays_a_rotation_however_long_it_turns():
    """The axes are made orthonormal again after every turn, so rounding never bends or
    stretches them; a turn and its reverse come back to where they started."""
    cam = _camera()
    rng = random.Random(7)
    for _ in range(20_000):
        cam.rotate(rng.uniform(-6, 6), rng.uniform(-6, 6))
    assert _orthonormal(cam, 1e-14)
    before = cam.axes
    for dx, dy in ((17, -3), (-250, 400), (0.5, 0.25)):
        cam.rotate(dx, dy)
        cam.rotate(-dx, -dy)
    assert all(_close(a, b, 1e-12) for a, b in zip(cam.axes, before, strict=True))


@pytest.mark.parametrize("mode", [FREE, TURNTABLE])
def test_panning_follows_a_diagonal_drag_exactly_in_any_orientation(mode):
    """The regression test for panning, without Qt: every corner of the model moves on
    the screen exactly as far as the pointer, across and down at once, whichever way the
    view is turned (upside down included, when free) and after zooming toward the cursor."""
    width, height = 900, 600

    def follows(cam, dx, dy):
        before = [_pixel(cam, k, width, height) for k in viewmath.corners(cam.bbox)]
        cam.pan(dx, dy, height)
        after = [_pixel(cam, k, width, height) for k in viewmath.corners(cam.bbox)]
        return all(
            abs(b[0] - a[0] - dx) < 1e-6 and abs(b[1] - a[1] - dy) < 1e-6
            for a, b in zip(before, after, strict=True)
        )

    turns = [(0, 0), (123, 47), (-80, 310), (400, -170), (0, 300)]
    for name in viewmath.VIEWS:
        for dx, dy in turns:
            cam = _camera(mode, width / height)
            cam.set_view(name)
            cam.rotate(dx, dy)
            assert follows(cam, 37, -23) and follows(cam, -55, 41), (name, dx, dy)
            cam.zoom(1.7, viewmath.ndc(700, 100, width, height))
            assert follows(cam, 29, 31), (name, dx, dy)
    upside_down = _camera(mode)
    upside_down.rotate(0, 300)
    assert (upside_down.up[1] < 0) == (mode == FREE)


def _screen(cam: viewmath.OrbitCamera, width: float = 900, height: float = 600) -> list[float]:
    """Where the model's eight corners are on the screen, in pixels, flattened."""
    return [v for k in viewmath.corners(cam.bbox) for v in _pixel(cam, k, width, height)]


def _depth(cam: viewmath.OrbitCamera) -> float:
    """How far the point the view turns about is in front of the model's centre."""
    return viewmath._dot(viewmath._sub(cam.target, cam.center), cam.back)


@pytest.mark.parametrize("mode", [FREE, TURNTABLE])
def test_the_view_turns_about_a_fixed_point_in_its_middle_at_the_depth_of_the_model(mode):
    """The model turns about the point in the middle of the view that the last fit, pan or
    zoom put at the depth of the model's centre, and that point stays put while it turns.
    Panned off the middle and turned a quarter, the model's centre comes to the middle;
    another quarter carries it to the other side, exactly as a half turn at once does.
    Panned, turned a quarter and then zoomed in on, the model keeps turning in the middle
    of the view: the old camera kept the point in front of the model through the zoom,
    and a turn of 30 degrees then swung the model's centre out of the view."""
    width, height = 900, 600
    cam = _camera(mode)
    cam.set_view("front")
    cam.pan(100, 0, height)
    assert _pixel(cam, cam.center, width, height) == pytest.approx((550, 300))
    half = _camera(mode)
    half.set_state(cam.state())
    cam.turn_model(90, 0)
    assert _pixel(cam, cam.center, width, height) == pytest.approx((450, 300))
    cam.turn_model(90, 0)
    assert _pixel(cam, cam.center, width, height) == pytest.approx((350, 300))
    half.turn_model(180, 0)
    assert cam.view_matrix() == pytest.approx(half.view_matrix(), abs=1e-15)
    assert cam.project(cam.target)[:2] == pytest.approx((0, 0), abs=1e-12)  # always the view's middle

    # A pan or a zoom puts the point at the model's depth, which changes nothing on screen.
    for move in (lambda c: c.pan(-60, 45, height), lambda c: c.zoom(1.6, (0.4, -0.3))):
        cam = _camera(mode)
        cam.pan(100, 0, height)
        cam.turn_model(70, 20)
        assert abs(_depth(cam)) > 1e-3 * cam.radius  # turned: the point is off the model's depth
        before = _screen(cam)
        target = cam.target
        cam.target = viewmath._add(target, viewmath._mul(cam.back, -_depth(cam)))
        assert _screen(cam) == pytest.approx(before, abs=1e-9)
        cam.target = target
        move(cam)
        assert _depth(cam) == pytest.approx(0, abs=1e-15)

    cam = _camera(mode)
    cam.set_view("front")
    cam.pan(250, 0, height)
    cam.turn_model(90, 0)
    cam.zoom(4.0)
    assert _pixel(cam, cam.center, width, height) == pytest.approx((450, 300))
    cam.turn_model(30, 0)
    assert _pixel(cam, cam.center, width, height) == pytest.approx((450, 300))


@pytest.mark.parametrize("mode", [FREE, TURNTABLE])
def test_a_turn_is_the_same_however_the_drag_or_the_keys_split_it(mode):
    """A drag turns the model the same whether it arrives in one mouse move or hundreds,
    which in practice is how fast it was made: after a pan, and after zooming toward a
    cursor off the middle, straight across, down and diagonally (the turntable stopping at
    straight above either way). Twelve 15-degree arrow-key turns are one half turn, as two
    Shift+arrow turns are. Re-centring the point turned about on every move made the end
    of a drag depend on the number of moves."""
    width, height = 900, 600

    def panned(cam):
        cam.zoom(2.5)
        cam.pan(250, 120, height)

    def zoomed(cam):
        for _ in range(3):
            cam.zoom(viewmath.WHEEL_STEP, viewmath.ndc(0.8 * width, 0.25 * height, width, height))

    for setup in (panned, zoomed):
        for dx, dy in ((450, 0), (0, 225), (300, 200), (-130, 340)):
            ends = []
            for moves in (1, 10, 300):
                cam = _camera(mode)
                setup(cam)
                for _ in range(moves):
                    cam.rotate(dx / moves, dy / moves)
                ends.append(_screen(cam))
            assert ends[1] == pytest.approx(ends[0], abs=1e-6), (setup.__name__, dx, dy)
            assert ends[2] == pytest.approx(ends[0], abs=1e-6), (setup.__name__, dx, dy)

    for across, down in ((15, 0), (0, 15), (-15, 0), (0, -15)):
        keys, shift, once = (_camera(mode) for _ in range(3))
        for cam, step, count in ((keys, 1, 12), (shift, 6, 2), (once, 12, 1)):
            panned(cam)
            for _ in range(count):
                cam.turn_model(across * step, down * step)
        assert _screen(keys) == pytest.approx(_screen(once), abs=1e-6), (across, down)
        assert _screen(shift) == pytest.approx(_screen(once), abs=1e-6), (across, down)


@pytest.mark.parametrize("mode", [FREE, TURNTABLE])
def test_turning_back_undoes_a_turn_after_a_pan_and_a_zoom(mode):
    """Turned and turned back by the same amount, every corner of the model is back where it
    was on screen after a pan and a zoom toward the cursor, with the keys and with a drag
    there and back in small moves (the turntable short of its stop). Re-centring the point
    turned about before every turn left a panned model elsewhere."""
    width, height = 900, 600
    cam = _camera(mode)
    cam.pan(250, -80, height)
    cam.zoom(1.7, viewmath.ndc(700, 150, width, height))
    start = _screen(cam)
    for across, down in ((90, 0), (0, 30), (40, -25), (-15, 0)):
        cam.turn_model(across, down)
        assert _screen(cam) != pytest.approx(start, abs=1)
        cam.turn_model(-across, -down)
        assert _screen(cam) == pytest.approx(start, abs=1e-6), (across, down)
    for dx, dy in ((4, 0), (0, 1), (3, -1)):  # tilts of 30 degrees, short of the stop
        for _ in range(75):
            cam.rotate(dx, dy)
        for _ in range(75):
            cam.rotate(-dx, -dy)
        assert _screen(cam) == pytest.approx(start, abs=1e-6), (dx, dy)


def test_the_standard_views_are_the_same_exact_orientation_in_either_mode():
    for name in viewmath.VIEWS:
        free, table = _camera(FREE), _camera(TURNTABLE)
        for cam in (free, table):
            cam.rotate(-210, 380)  # upside down, when free
            cam.set_view(name)
            assert cam.fitted
        assert free.axes == table.axes == viewmath.turntable_axes(*viewmath.VIEWS[name]), name
        assert (free.yaw, free.pitch) == viewmath.VIEWS[name]
    cam = _camera(FREE)
    cam.rotate(77, 333)
    cam.reset()
    s = 1 / 3**0.5
    assert cam.fitted and cam.back == pytest.approx((s, s, s))


def test_switching_modes_keeps_the_view_or_sets_it_upright():
    # A turntable becomes a free camera with exactly the same view.
    table = _camera(TURNTABLE)
    table.rotate(123, 47)
    matrices = (table.view_matrix(), table.projection_matrix())
    table.set_mode(FREE)
    assert table.mode == FREE and (table.view_matrix(), table.projection_matrix()) == matrices

    # A free camera turned upside down becomes the upright turntable view from the same direction.
    free = _camera(FREE)
    free.rotate(40, 300)
    assert free.up[1] < 0
    direction = free.back
    free.set_mode(TURNTABLE)
    assert free.mode == TURNTABLE and _close(free.back, direction)
    assert free.up[1] > 0 and free.right[1] == 0 and -90 <= free.pitch <= 90
    free.rotate(0, 10_000)
    assert free.pitch == viewmath.PITCH_LIMIT  # and it is a turntable again

    # Looking straight down, rolled, the turntable keeps the screen's right axis.
    free = _camera(FREE)
    free.set_view("front")
    free.turn_model(90, 0)
    free.turn_model(0, 90)
    right = free.right
    assert _close(free.back, (0, 1, 0)) and not _close(right, (1, 0, 0))
    free.set_mode(TURNTABLE)
    assert free.pitch == pytest.approx(90) and _close(free.back, (0, 1, 0)) and _close(free.right, right)

    # A fitted camera fits again; one the user moved keeps its zoom and target.
    free = _camera(FREE)
    free.rotate(0, 300)
    free.fit()
    free.set_mode(TURNTABLE)
    assert free.fitted and max(max(abs(c) for c in free.project(k)[:2]) for k in viewmath.corners(BOX)) <= 1
    free = _camera(FREE)
    free.rotate(0, 300)
    free.zoom(2.0)
    kept = (free.target, free.half_height)
    free.set_mode(TURNTABLE)
    assert (free.target, free.half_height) == kept and not free.fitted


def test_the_camera_state_carries_the_orientation_and_reads_an_old_one():
    free = _camera(FREE)
    free.rotate(-40, 310)
    free.pan(12, -7, 600)
    state = free.state()
    assert set(state) == {"yaw", "pitch", "axes", "target", "half_height", "shift", "fitted"}
    back = _camera(FREE)
    back.set_state(state)
    assert all(_close(a, b) for a, b in zip(back.axes, free.axes, strict=True))
    assert back.target == free.target and back.half_height == free.half_height and not back.fitted
    assert back.view_matrix() == pytest.approx(free.view_matrix(), abs=1e-12)

    # A state from before the axes were kept, or a stand-in's, has only yaw and pitch.
    old = {"yaw": 75.0, "pitch": 20.0, "target": [0.01, 0.02, 0.0], "half_height": 0.05, "fitted": False}
    for mode in (FREE, TURNTABLE):
        cam = _camera(mode)
        cam.set_state(old)
        assert cam.axes == viewmath.turntable_axes(75.0, 20.0) and (cam.yaw, cam.pitch) == (75.0, 20.0)
        assert cam.target == (0.01, 0.02, 0.0) and cam.half_height == 0.05

    # A turntable takes a free state's upright yaw and pitch; axes that are not a rotation are
    # left for the yaw and pitch; a fitted state fits.
    table = _camera(TURNTABLE)
    table.set_state(state)
    assert table.up[1] > 0 and _close(table.back, free.back)
    for axes in ([[1, 0, 0], [1, 0, 0]], [[math.nan, 0, 0], [0, 1, 0]], [[1, 0], [0, 1]], "x", None):
        cam = _camera(FREE)
        cam.set_state({**state, "axes": axes})
        assert cam.axes == viewmath.turntable_axes(state["yaw"], state["pitch"]), axes
    cam = _camera(FREE)
    cam.set_state({**state, "fitted": True})
    assert cam.fitted and cam.target == cam.center and _close(cam.back, free.back)


# --------------------------------------------------------------------------- the widget, offscreen
@needs_qt
def test_the_3d_view_turns_freely_with_the_mouse_and_the_keys(app):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QKeyEvent, QMouseEvent
    from PySide6.QtWidgets import QApplication

    from solidseas_app.viewer import view3d

    data = mesh3d.read_part_mesh(str(fixture_path(O02)), str(FIXTURES), 1000)["data"]
    view = view3d.ModelView()  # never shown: the camera follows the mouse without OpenGL
    view.resize(400, 300)
    view.set_mesh(data)
    cam = view.camera
    assert view.rotation_mode == FREE and cam.mode == FREE
    no = Qt.KeyboardModifier.NoModifier

    def drag(button, dx, dy, mods=no):
        start = QPointF(200, 150)
        QApplication.sendEvent(
            view, QMouseEvent(QEvent.Type.MouseButtonPress, start, start, button, button, mods)
        )
        for k in range(1, 6):
            p = QPointF(200 + dx * k / 5, 150 + dy * k / 5)
            QApplication.sendEvent(
                view, QMouseEvent(QEvent.Type.MouseMove, p, p, Qt.MouseButton.NoButton, button, mods)
            )
        end = QPointF(200 + dx, 150 + dy)
        QApplication.sendEvent(
            view,
            QMouseEvent(QEvent.Type.MouseButtonRelease, end, end, button, Qt.MouseButton.NoButton, mods),
        )

    def key(k, mods=no):
        QApplication.sendEvent(view, QKeyEvent(QEvent.Type.KeyPress, k, mods))

    # Over the top with the rotate button of either mouse style.
    drag(Qt.MouseButton.LeftButton, 0, 250)
    assert cam.up[1] < 0 and not cam.fitted and _orthonormal(cam)
    key(Qt.Key.Key_R)
    view.mouse_style = viewmath.SOLIDWORKS
    drag(Qt.MouseButton.MiddleButton, 0, 250)
    assert cam.up[1] < 0
    view.mouse_style = viewmath.STANDARD

    # The arrow keys turn 15 degrees about the screen's axes, 90 with Shift.
    ctrl, shift = Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.ShiftModifier
    key(Qt.Key.Key_R)
    r0, u0, b0 = cam.axes
    key(Qt.Key.Key_Right)  # as a drag to the right
    assert _close(cam.up, u0) and viewmath._dot(cam.back, b0) == pytest.approx(math.cos(math.radians(15)))
    assert viewmath._dot(cam.back, r0) < 0
    r0, u0, b0 = cam.axes
    key(Qt.Key.Key_Up, shift)  # as a drag up, a quarter turn: the eye goes down
    assert _close(cam.right, r0) and _close(cam.back, viewmath._mul(u0, -1)) and _close(cam.up, b0)
    key(Qt.Key.Key_1, ctrl)
    key(Qt.Key.Key_Down, shift)
    key(Qt.Key.Key_Down, shift)  # over the top: the front view from behind, upside down
    assert _close(cam.back, (0, 0, -1)) and _close(cam.up, (0, -1, 0))
    key(Qt.Key.Key_5, ctrl)
    assert cam.axes == viewmath.turntable_axes(*viewmath.VIEWS["top"]) and cam.fitted
    target = cam.target
    key(Qt.Key.Key_Left, ctrl)  # Ctrl+arrow still pans
    assert cam.target != target and cam.axes == viewmath.turntable_axes(*viewmath.VIEWS["top"])

    # Back puts back a free view, upside down included; an old state still reads.
    drag(Qt.MouseButton.LeftButton, 70, 260)
    state = view.camera_state()
    assert "axes" in state and cam.up[1] < 0
    key(Qt.Key.Key_R)
    view.set_camera_state(state)
    assert _same(view.camera_state(), state)
    view.set_camera_state(
        {"yaw": 75.0, "pitch": 20.0, "target": [0, 0, 0], "half_height": 0.05, "fitted": True}
    )
    assert cam.axes == viewmath.turntable_axes(75.0, 20.0) and cam.fitted

    # Turned upside down, then switched to a turntable: upright, from the same direction.
    drag(Qt.MouseButton.LeftButton, 0, 250)
    direction = cam.back
    view.set_rotation_mode(TURNTABLE)
    assert view.rotation_mode == TURNTABLE and cam.mode == TURNTABLE
    assert cam.up[1] > 0 and _close(cam.back, direction)
    view.set_mesh(data)  # a new scene keeps the mode
    assert view.camera.mode == TURNTABLE
    view.deleteLater()


@needs_qt
@pytest.mark.parametrize("mode", [FREE, TURNTABLE])
def test_the_3d_view_turns_the_same_however_fast_the_drag_is(app, mode):
    """On the widget, with real mouse, wheel and key events: after a right-drag pan and a
    wheel zoom toward a cursor off the middle, a left-drag across turns the model to the
    same view whether it arrives in 2 mouse moves or 120 (a quick or a slow drag); twelve
    Left presses give the same view as two Shift+Left presses; and Shift+Right then
    Shift+Left puts the view back."""
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
    from PySide6.QtWidgets import QApplication

    from solidseas_app.viewer import view3d

    data = mesh3d.read_part_mesh(str(fixture_path(O02)), str(FIXTURES), 1000)["data"]
    no = Qt.KeyboardModifier.NoModifier
    shift = Qt.KeyboardModifier.ShiftModifier
    left, right = Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton

    def mouse(view, kind, x, y, button):
        p = QPointF(x, y)
        pressed = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else button
        held = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else button
        QApplication.sendEvent(view, QMouseEvent(kind, p, p, pressed, held, no))

    def drag(view, button, dx, dy, moves):
        x, y = 150.0, 150.0
        mouse(view, QEvent.Type.MouseButtonPress, x, y, button)
        for k in range(1, moves + 1):
            mouse(view, QEvent.Type.MouseMove, x + dx * k / moves, y + dy * k / moves, button)
        mouse(view, QEvent.Type.MouseButtonRelease, x + dx, y + dy, button)

    def view_after(moves=0, keys=()):
        view = view3d.ModelView(rotation_mode=mode)  # never shown: the camera follows without OpenGL
        view.resize(600, 400)
        view.set_mesh(data)
        drag(view, right, 140, 60, 4)
        p = QPointF(480, 90)
        wheel = QWheelEvent(
            p, p, QPoint(), QPoint(0, 360), Qt.MouseButton.NoButton, no, Qt.ScrollPhase.NoScrollPhase, False
        )
        QApplication.sendEvent(view, wheel)
        if moves:
            drag(view, left, 450, 0, moves)
        for k, mods in keys:
            QApplication.sendEvent(view, QKeyEvent(QEvent.Type.KeyPress, k, mods))
        assert view.camera.mode == mode
        matrix = view.camera.view_matrix()
        view.deleteLater()
        return matrix

    still = view_after()
    slow, quick = view_after(moves=120), view_after(moves=2)
    assert quick == pytest.approx(slow, abs=1e-12)
    assert slow != pytest.approx(still, abs=1e-3)  # it did turn
    twelve = view_after(keys=[(Qt.Key.Key_Left, no)] * 12)
    assert twelve == pytest.approx(view_after(keys=[(Qt.Key.Key_Left, shift)] * 2), abs=1e-12)
    assert twelve != pytest.approx(still, abs=1e-3)
    there_and_back = view_after(keys=[(Qt.Key.Key_Right, shift), (Qt.Key.Key_Left, shift)])
    assert there_and_back == pytest.approx(still, abs=1e-12)


def _same(a: dict, b: dict) -> bool:
    from solidseas_app.viewer.selftest import same_camera

    return same_camera(a, b)


@needs_qt
def test_the_rotation_mode_is_a_setting_kept_in_its_file(tmp_path):
    from solidseas_app.viewer.settings import Settings, SettingsStore

    assert Settings().rotation_mode == FREE  # free is the default
    path = tmp_path / "Viewer.ini"
    store = SettingsStore(str(path))
    assert store.save(Settings(rotation_mode=TURNTABLE, mouse_style="solidworks"))
    assert "rotation_mode=turntable" in path.read_text(encoding="utf-8")
    assert SettingsStore(str(path)).load() == Settings(rotation_mode=TURNTABLE, mouse_style="solidworks")
    for raw, expected, reset in (
        ("sideways", FREE, ["rotation_mode"]),
        (" Turntable ", TURNTABLE, []),
        ("", FREE, ["rotation_mode"]),
        ("@Variant(free)", FREE, ["rotation_mode"]),
    ):
        path.write_text(f"[Preferences]\nrotation_mode={raw}\nview_3d=true\n", encoding="utf-8")
        store = SettingsStore(str(path))
        assert store.load() == Settings(view_3d=True, rotation_mode=expected), raw
        assert store.reset_keys == reset, raw


@needs_qt
def test_the_rotation_mode_is_chosen_in_preferences_and_the_settings_menu(app, tmp_path):
    from PySide6.QtWidgets import QDialogButtonBox

    from solidseas_app.viewer.preferences import MOUSE_NOTE, ROTATION_TIPS, PreferencesDialog
    from solidseas_app.viewer.settings import Settings, SettingsStore
    from solidseas_app.viewer.window import MainWindow

    path = tmp_path / "Viewer.ini"
    w = MainWindow(SettingsStore(str(path)))
    dialog = PreferencesDialog(w, w.settings, w.store.path)
    try:
        pane = w.details.preview
        assert pane.rotation_mode == FREE and w.act_rotation[FREE].isChecked()
        assert dialog.free.isChecked() and not dialog.turntable.isChecked()
        assert "SOLIDWORKS" in dialog.free.text() and "upright" in dialog.turntable.text()
        assert dialog.free.toolTip() == ROTATION_TIPS[FREE] and "upside down" in ROTATION_TIPS[FREE]
        assert dialog.turntable.toolTip() == ROTATION_TIPS[TURNTABLE]
        assert "never rolls" in ROTATION_TIPS[TURNTABLE]
        assert "turntable" not in MOUSE_NOTE.lower()  # the mouse note no longer says it only turns so
        # A 1080p screen at 125 percent scaling leaves about 830 pixels for the dialog and its
        # title bar; a group of its own for the rotation had made the dialog 905 pixels tall.
        assert dialog.sizeHint().height() <= 800
        dialog.turntable.setChecked(True)
        assert w.settings == Settings()  # nothing happens before Apply or OK
        dialog.applied.connect(w.apply_settings)
        dialog.buttons.button(QDialogButtonBox.StandardButton.Apply).click()
        assert w.settings == Settings(rotation_mode=TURNTABLE)
        assert pane.rotation_mode == TURNTABLE and w.act_rotation[TURNTABLE].isChecked()
        assert SettingsStore(str(path)).load() == w.settings
        dialog.buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).click()
        assert dialog.free.isChecked() and dialog.values() == Settings()

        menus = {a.text(): a.menu() for a in w.settings_menu.actions() if a.menu() is not None}
        assert [a.text() for a in menus["Rotation in the 3D View"].actions()] == [
            "&Free: Any View, as in SOLIDWORKS",
            "&Turntable: Stays Upright",
            "",
            "Turn About the Point &Under the Pointer",
        ]
        w.act_rotation[FREE].trigger()
        assert w.settings.rotation_mode == FREE and pane.rotation_mode == FREE
        assert SettingsStore(str(path)).load().rotation_mode == FREE
    finally:
        dialog.deleteLater()
        w.shutdown()
        w.close()
    # A saved choice applies when the window opens.
    SettingsStore(str(path)).save(Settings(rotation_mode=TURNTABLE))
    w = MainWindow(SettingsStore(str(path)))
    try:
        assert w.details.preview.rotation_mode == TURNTABLE and w.act_rotation[TURNTABLE].isChecked()
    finally:
        w.shutdown()
        w.close()


@needs_qt
def test_the_help_under_the_3d_view_says_how_to_rotate_in_each_mode(viewer):
    w = viewer.window
    pane = w.details.preview
    made: list = []
    stub = _stub_view_factory(made)
    turned: list[str] = []

    def factory():
        view = stub()
        view.set_rotation_mode = turned.append  # the real view's method, recorded
        return view

    pane.view_factory = factory
    pane.gl_check = lambda: (True, "test")
    before = _state(FIXTURES)
    viewer.open(FIXTURES)
    w.change_settings(view_3d=True)
    _show_3d(viewer, O02)
    assert pane.mesh_state == "ready"
    free_text = "Rotation is free: a drag across turns the model about the screen's vertical axis"
    assert free_text in pane.caption.text()
    w.change_settings(rotation_mode=TURNTABLE)
    assert turned == [TURNTABLE]
    caption = pane.caption.text()
    assert "Rotation is a turntable: a drag across turns the model about its vertical axis" in caption
    assert "at most to straight above or below" in caption and free_text not in caption
    _show_3d(viewer, O16)  # an assembly's help says the same
    assert "Rotation is a turntable" in pane.caption.text() and "Click a component" in pane.caption.text()
    w.change_settings(rotation_mode=FREE)
    assert turned == [TURNTABLE, FREE] and free_text in pane.caption.text()
    assert _state(FIXTURES) == before


@needs_qt
def test_the_self_test_rotation_option_is_checked_and_kept_in_its_own_settings(app, tmp_path, monkeypatch):
    from solidseas_app.viewer import app as viewer_app
    from solidseas_app.viewer.settings import SettingsStore

    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)  # main() installs its own
    assert viewer_app.main(["--rotation", "turntable"]) == viewer_app.EXIT_USAGE  # it goes with --self-test
    report = tmp_path / "out" / "report.json"
    args = ["--self-test", str(FIXTURES), "--report", str(report), "--select", O02]
    assert viewer_app.main([*args, "--rotation", "sideways"]) == viewer_app.EXIT_USAGE
    assert viewer_app.main([*args, "--rotation", "turntable"]) == 0
    out = json.loads(report.read_text(encoding="utf-8"))
    assert out["ok"] and out["rotation"] == TURNTABLE
    assert SettingsStore(out["settings"]).load().rotation_mode == TURNTABLE
    assert viewer_app.main([*args, "--force"]) == 0  # free by default
    out = json.loads(report.read_text(encoding="utf-8"))
    assert out["rotation"] == FREE and SettingsStore(out["settings"]).load().rotation_mode == FREE
    assert not (tmp_path / "Roaming").exists()


# --------------------------------------------------------------------------- OpenGL, on the real display
_GL_PAN = """
from array import array
from itertools import compress
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QKeyEvent, QMouseEvent, QWheelEvent
from solidseas_app.viewer import mesh3d, viewmath
part_path, asm_path, folder = sys.argv[1:4]
part = mesh3d.read_part_mesh(part_path, folder, 1000)["data"]
asm = mesh3d.read_assembly_scene(asm_path, folder, folder, 1_000_000)["data"]
lite = mesh3d.read_assembly_scene(asm_path, folder, folder, 1_000_000, configuration="Lite")["data"]
NO, CTRL = Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ControlModifier
LEFT, RIGHT, MIDDLE = Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton


def mouse(view, kind, x, y, button, mods):
    p = QPointF(x, y)
    pressed = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else button
    held = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else button
    QApplication.sendEvent(view, QMouseEvent(kind, p, view.mapToGlobal(p), pressed, held, mods))


def drag(view, button, dx, dy, mods=NO):
    x, y = view.width() / 2, view.height() / 2
    mouse(view, QEvent.Type.MouseButtonPress, x, y, button, mods)
    for k in range(1, 5):
        mouse(view, QEvent.Type.MouseMove, x + dx * k / 4, y + dy * k / 4, button, mods)
    mouse(view, QEvent.Type.MouseButtonRelease, x + dx, y + dy, button, mods)


def key(view, k, mods=NO):
    QApplication.sendEvent(view, QKeyEvent(QEvent.Type.KeyPress, k, mods))


def wheel(view, x, y, notches):
    p = QPointF(x, y)
    QApplication.sendEvent(view, QWheelEvent(
        p, view.mapToGlobal(p), QPoint(), QPoint(0, 120 * notches), Qt.MouseButton.NoButton, NO,
        Qt.ScrollPhase.NoScrollPhase, False,
    ))


def centroid(view):
    # The middle of the drawn model's pixels in the view's own pixels, and how many touch the edge.
    img = view.grabFramebuffer().convertToFormat(QImage.Format.Format_RGB32)
    w, h = img.width(), img.height()
    px = array("I")
    px.frombytes(bytes(img.constBits())[: 4 * w * h])
    bg = px[0]
    sx = sy = n = edge = 0
    for y in range(h):
        mask = [v != bg for v in px[y * w : (y + 1) * w]]
        c = sum(mask)
        if c:
            n, sy, sx = n + c, sy + y * c, sx + sum(compress(range(w), mask))
            edge += (c if y in (0, h - 1) else 0) + mask[0] + mask[-1]
    scale = w / view.width()
    return [sx / n / scale, sy / n / scale, edge] if n else None


cases = []


def measure(view, label, act, want):
    app.processEvents()
    a = centroid(view)
    act()
    app.processEvents()
    b = centroid(view)
    got = None if a is None or b is None else [b[0] - a[0], b[1] - a[1]]
    cases.append({"case": label, "want": list(want), "got": got, "edge": None if b is None else b[2]})


def small(view):
    view.camera.fit()
    view.camera.zoom(0.4)
    view.update()


for instanced in (True, False):
    view3d.Renderer.allow_instancing = instanced
    for name, scene in (("o02", part), ("o16", asm)):
        for mode in (viewmath.FREE, viewmath.TURNTABLE):
            view = view3d.ModelView(rotation_mode=mode)
            view.resize(320, 240)
            view.show()
            (view.set_mesh if name == "o02" else view.set_assembly)(scene)
            app.processEvents()
            w, h = view.width(), view.height()
            tag = f"{name} {mode} {'instanced' if instanced else 'one by one'}"
            for orient in ("isometric", "top", "turned"):
                view.mouse_style = viewmath.STANDARD
                if orient == "turned":
                    view.reset_view()
                    drag(view, LEFT, 40, 250)  # free: over the top, upside down; a turntable stops above
                else:
                    view.set_view(orient)
                small(view)
                measure(view, f"{tag} {orient} right-drag", lambda: drag(view, RIGHT, 40, 30), (40, 30))
                measure(view, f"{tag} {orient} middle-drag", lambda: drag(view, MIDDLE, -40, 30), (-40, 30))
                view.mouse_style = viewmath.SOLIDWORKS
                ctrl_drag = lambda: drag(view, MIDDLE, 30, -40, CTRL)  # noqa: E731
                measure(view, f"{tag} {orient} Ctrl+middle-drag", ctrl_drag, (30, -40))
                measure(
                    view,
                    f"{tag} {orient} Ctrl+Left, Ctrl+Up",
                    lambda: (key(view, Qt.Key.Key_Left, CTRL), key(view, Qt.Key.Key_Up, CTRL)),
                    (-w / 10, -h / 10),
                )
            view.mouse_style = viewmath.STANDARD
            view.reset_view()
            wheel(view, w / 2, h / 2, -3)
            wheel(view, 0.7 * w, 0.3 * h, 1)
            measure(view, f"{tag} zoomed toward the cursor", lambda: drag(view, RIGHT, 30, -20), (30, -20))
            small(view)
            drag(view, LEFT, 60, 200)
            state = view.camera_state()
            view.reset_view()
            view.set_camera_state(state)
            measure(view, f"{tag} after Back", lambda: drag(view, RIGHT, -35, 25), (-35, 25))
            if name == "o16":
                view.reset_view()
                view.explode_to(1.0, animate=False)
                small(view)
                measure(view, f"{tag} exploded", lambda: drag(view, RIGHT, 40, 30), (40, 30))
                view.explode_to(0.0, animate=False)
                measure(view, f"{tag} collapsed", lambda: drag(view, RIGHT, -40, -30), (-40, -30))
                view.set_assembly(lite)
                app.processEvents()
                small(view)
                measure(view, f"{tag} another configuration", lambda: drag(view, RIGHT, 40, -30), (40, -30))
            cases.append({"case": f"{tag} error", "error": view.error})
            view.close()
print(json.dumps({"gl": True, "cases": cases}))
"""


@needs_qt
def test_panning_follows_the_pointer_on_both_axes_on_the_display():
    """The regression test for panning, on the real display: real mouse events and keys on
    the real view, the drawn pixels read back. The middle of the model's pixels moves with
    every diagonal drag, across and down at once, to within half a pixel: right-drag and
    middle-drag (Standard), Ctrl+middle-drag and Ctrl+arrows (SOLIDWORKS), seen from the
    isometric view, from above and turned (over the top when free), zoomed toward the
    cursor, after Back, exploded and collapsed, and in another configuration; a part and
    an assembly, instanced and one instance at a time, in both rotation modes."""
    before = _state(FIXTURES)
    out = run_gl(_GL_PAN, str(fixture_path(O02)), str(fixture_path(O16)), str(FIXTURES), timeout=300)
    cases = out["cases"]
    assert len(cases) == 2 * (2 * 15 + 2 * 18)
    for c in cases:
        if "want" not in c:
            assert c["error"] is None, c
            continue
        assert c["got"] is not None and c["edge"] == 0, c  # drawn, and wholly in view
        assert abs(c["got"][0] - c["want"][0]) < 0.5 and abs(c["got"][1] - c["want"][1]) < 0.5, c
    assert _state(FIXTURES) == before


_GL_TURN_OVER = """
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from solidseas_app.viewer import mesh3d, viewmath
from solidseas_app.viewer.selftest import covered, drag
scene = mesh3d.read_assembly_scene(sys.argv[1], sys.argv[2], sys.argv[2], 1_000_000)["data"]
n = sum(len(i) for i in scene.instance_ids)
out = {"gl": True, "instances": n}
for instanced in (True, False):
    view3d.Renderer.allow_instancing = instanced
    for mode in (viewmath.FREE, viewmath.TURNTABLE):
        view = view3d.ModelView(rotation_mode=mode)
        view.resize(480, 360)
        view.show()
        view.set_assembly(scene)
        app.processEvents()
        r = {"covered_before": covered(view)}
        drag(view, Qt.MouseButton.LeftButton, (240, 50), (240, 300))  # 100 degrees down from isometric
        app.processEvents()
        cam = view.camera
        r.update({"up_y": cam.up[1], "pitch": cam.pitch, "covered": covered(view)})
        # Every instance in front somewhere is picked where it is drawn: the id pass uses the
        # same matrices as the picture.
        r["picks"] = picks = {}
        for g in range(n):
            p = view.pixel_of(g)
            picks[g] = None if p is None else view.instance_at(*p)
        # What is drawn lies inside the model's box as the camera projects it.
        img = view.grabFramebuffer()
        bg = img.pixelColor(0, 0)
        drawn = [(x, y) for y in range(0, img.height(), 2) for x in range(0, img.width(), 2)
                 if img.pixelColor(x, y) != bg]
        scale = img.width() / view.width()
        corners = [cam.project(k) for k in viewmath.corners(cam.bbox)]
        box = [((x + 1) * view.width() / 2, (1 - y) * view.height() / 2) for x, y, _ in corners]
        def extent(points, scale=1.0):
            xs, ys = [x / scale for x, _ in points], [y / scale for _, y in points]
            return [min(xs), min(ys), max(xs), max(ys)] if points else None

        r["drawn"], r["box"] = extent(drawn, scale), extent(box)
        r["error"] = view.error
        out[f"{instanced} {mode}"] = r
        view.close()
print(json.dumps(out))
"""


@needs_qt
def test_a_free_turn_past_straight_above_still_draws_and_picks_on_the_display():
    """Dragged 100 degrees down from the isometric view, a free view goes 45 degrees past
    straight above and shows the assembly upside down, still drawn (as much of the view
    as before, near enough), inside the box the camera projects, and every instance in
    front is picked where it is drawn; a turntable stops at straight above."""
    before = _state(FIXTURES)
    out = run_gl(_GL_TURN_OVER, str(fixture_path(O16)), str(FIXTURES))
    n = out["instances"]
    for instanced in ("True", "False"):
        free, table = out[f"{instanced} free"], out[f"{instanced} turntable"]
        for r in (free, table):
            assert r["error"] is None
            assert r["covered"] > 0.25 * r["covered_before"] > 0, r
            x0, y0, x1, y1 = r["drawn"]
            a0, b0, a1, b1 = r["box"]
            assert a0 - 1 <= x0 and x1 <= a1 + 1 and b0 - 1 <= y0 and y1 <= b1 + 1, r
            found = {int(g): k for g, k in r["picks"].items() if k is not None}
            assert all(int(g) == k for g, k in found.items()) and len(found) >= n - 3, r["picks"]
        # 35.26 degrees up, turned 100 degrees: 44.74 degrees past straight above, upside down
        assert free["up_y"] < 0 and free["pitch"] == pytest.approx(180 - viewmath.ISO_PITCH - 100, abs=1e-6)
        assert table["pitch"] == viewmath.PITCH_LIMIT and table["up_y"] == pytest.approx(0, abs=1e-12)
    assert _state(FIXTURES) == before


@needs_qt
@pytest.mark.parametrize("mode", [FREE, TURNTABLE])
def test_the_self_test_turns_the_model_over_the_top(tmp_path, mode):
    """The self-test drags each 3D view 100 degrees over the top and saves it: free, past
    straight above and upside down; a turntable, stopped at straight above; the model
    drawn either way. The views it saves after that start from the isometric view again."""
    shots = tmp_path / "shots"
    before = _state(FIXTURES)
    args = ["--self-test", str(FIXTURES), "--screenshot-dir", str(shots), "--select", O02, "--select", O16]
    args += ["--3d", "--rotation", mode, "--explode", "100"]
    report = run_self_test(args, shots, appdata=tmp_path / "Roaming")
    assert report["rotation"] == mode
    for doc in report["documents"]:
        turned = doc["turned_over"]
        assert turned["rotation"] == mode and turned["covered"] > 0.01
        if mode == FREE:
            assert turned["past_top"] and turned["up_y"] < 0
        else:
            assert not turned["past_top"] and turned["pitch"] == viewmath.PITCH_LIMIT
    names = [Path(p).name for p in report["screenshots"]]
    for stem in ("o02_boxA", "o16_asm_features"):
        shot = next(n for n in names if n.endswith(f"{stem}_turned_over.png"))
        assert (
            names.index(shot)
            == names.index(next(n for n in names if n.endswith(f"{stem}_preview_3d.png"))) + 1
        )
    assert any(
        n.endswith("o16_asm_features_explode_100_parts.png") or n.endswith("explode_100.png") for n in names
    )
    assert not (tmp_path / "Roaming").exists()
    assert _state(FIXTURES) == before
