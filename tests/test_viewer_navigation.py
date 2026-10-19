"""Finding your way round the 3D view as in Fusion 360 and SOLIDWORKS: the view cube,
Home, and the camera moves they make.

The view cube sits over the view's top-right corner and turns with the model. Its
26 regions (6 faces, 12 edges, 8 corners) each look from their own direction,
upright and fitted, with SOLIDWORKS's axes: Front on +Z, Top on +Y, Right on +X, so
its faces and its front-top-right corner are exactly Ctrl+1 to Ctrl+7. Looking
straight at a face it offers step arrows to the next face and roll arrows; Home goes
to the view the document opened with, or one the user set from the cube's menu.
The cube's clicks, Home, R, the Isometric button and Ctrl+1 to Ctrl+7 ease the
camera there; anything else the user does takes the camera from wherever the move
got to.

These tests check the arithmetic without Qt (the regions, the hit test, the camera's
moves, its lens shift, a turn about a point and a roll), the cube widget offscreen
(its place, its clicks and menus kept from the model's, its tooltips and fade), the
moves on the view, Home per document through the Preview pane, the setting, and on
the real display that a click on each region lands on exactly the frame the view
draws when set there at once, at 100, 125 and 150 percent scaling.
"""

import math
import os
import random

import pytest

from gl_support import run_gl
from solidseas_app.viewer import mesh3d, viewcube, viewmath
from support import FIXTURES, fixture_path
from test_viewer import Viewer, _stub_view_factory, needs_qt

FREE, TURNTABLE = viewmath.FREE, viewmath.TURNTABLE
O02, O16 = "o02_boxA.SLDPRT", "o16_asm_features.SLDASM"
BOX = ((0.0, 0.0, 0.0), (0.04, 0.03, 0.01))


def _camera(mode: str = FREE, aspect: float = 1.5) -> viewmath.OrbitCamera:
    cam = viewmath.OrbitCamera(BOX, mode=mode)
    cam.aspect = aspect
    cam.reset()
    return cam


def _close(a, b, tol: float = 1e-12) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b, strict=True))


def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def _random_cameras(n: int, seed: int = 11):
    rng = random.Random(seed)
    for _ in range(n):
        cam = _camera()
        cam.rotate(rng.uniform(-900, 900), rng.uniform(-900, 900))
        yield cam


# --------------------------------------------------------------------------- the regions, no Qt
def test_the_26_regions_and_their_names():
    regions = viewmath.REGIONS
    assert len(regions) == len(set(regions)) == 26
    counts = [sum(1 for v in r if v) for r in regions]
    assert (counts.count(1), counts.count(2), counts.count(3)) == (6, 12, 8)
    assert viewmath.region_name((0, 1, 1)) == "front-top"
    assert viewmath.region_name((-1, 1, -1)) == "back-top-left"
    for r in regions:
        assert viewmath.parse_region(viewmath.region_name(r)) == r
        words = viewmath.region_name(r).split("-")
        assert viewmath.parse_region("-".join(reversed(words))) == r  # any order
    for bad in ("front-back", "top-top", "up", "", "front-top-right-left", "left-right-top"):
        assert viewmath.parse_region(bad) is None, bad
    assert viewmath.region_text((0, 0, 1)) == "Front"
    assert viewmath.region_text((0, 1, 1)) == "Front and top edge"
    assert viewmath.region_text((-1, 1, -1)) == "Back, top and left corner"
    assert viewcube.tooltip((1, 1, 1)) == "Isometric: front, top and right (R)"
    assert viewcube.tooltip((0, 1, 0)) == "Top (Ctrl+5)"


def test_the_faces_and_the_front_top_right_corner_are_solidworks_standard_views():
    """Front looks along -Z, Top along -Y with -Z up the screen, and the (1, 1, 1) corner is
    SOLIDWORKS's isometric: the same axes, exactly, as Ctrl+1 to Ctrl+7."""
    for region, name in viewmath.FACES.items():
        assert viewmath.region_angles(region) == viewmath.VIEWS[name]
        a, b = _camera(), _camera()
        a.look_from(region)
        b.set_view(name)
        assert a.axes == b.axes and a.fitted, name
        assert _close(a.back, region)
    iso = _camera()
    iso.look_from(viewmath.ISOMETRIC)
    assert iso.axes == viewmath.turntable_axes(*viewmath.VIEWS["isometric"])
    top = _camera()
    top.look_from((0, 1, 0))
    assert _close(top.right, (1, 0, 0)) and _close(top.up, (0, 0, -1))  # the front at the bottom
    bottom = _camera()
    bottom.look_from((0, -1, 0))
    assert _close(bottom.up, (0, 0, 1))
    # Every region looks from its own direction, upright (Y up, or straight above or below).
    for region in viewmath.REGIONS:
        cam = _camera()
        cam.look_from(region)
        assert _close(cam.back, _unit(region)), region
        assert cam.right[1] == pytest.approx(0, abs=1e-15) and cam.up[1] >= -1e-15, region


def test_a_click_finds_the_region_it_was_on_from_any_view():
    """The middle of a region's largest cell drawn from here is that region, from 500
    random orientations and from every region's own view, at each size the cube can
    have; looking from a region, the cube's middle is that region; looking straight at a
    face, its four edges and four corners are still there to click, as its border."""
    for size in (96, 123, 128):
        checked = 0
        for cam in _random_cameras(500):
            for r in viewmath.REGIONS:
                p = viewcube.point_of(cam.axes, r, size)
                if p is not None:
                    checked += 1
                    assert viewcube.region_at(cam.axes, *p, size) == r
        assert checked > 500 * 7
        for r in viewmath.REGIONS:
            cam = _camera()
            cam.look_from(r)
            assert viewcube.region_at(cam.axes, size / 2, size / 2, size) == r
            for q in viewmath.REGIONS:
                p = viewcube.point_of(cam.axes, q, size)
                if p is not None:
                    assert viewcube.region_at(cam.axes, *p, size) == q
    front = _camera()
    front.set_view("front")
    reachable = {r for r in viewmath.REGIONS if viewcube.point_of(front.axes, r, 123) is not None}
    assert reachable == {r for r in viewmath.REGIONS if r[2] == 1}
    # The border cells are 0.22 of the face's edge: a corner cell 9 to 12 pixels square.
    size = 123
    edge = 2 * viewcube.HALF * size
    lo = size / 2 - edge / 2
    assert viewcube.region_at(front.axes, lo + 0.21 * edge, lo + 0.21 * edge, size) == (-1, 1, 1)
    assert viewcube.region_at(front.axes, lo + 0.23 * edge, lo + 0.21 * edge, size) == (0, 1, 1)
    assert viewcube.region_at(front.axes, lo - 1, size / 2, size) is None  # off the cube


def _quarter_orientations():
    """The 24 orientations a cube's faces can face the eye in, rolled by right angles."""
    seen, todo = {}, [_camera()]
    todo[0].set_view("front")
    while todo:
        cam = todo.pop()
        key = tuple(round(v) for v in (*cam.right, *cam.up))
        if key in seen:
            continue
        seen[key] = cam
        for across, down in ((90, 0), (0, 90)):
            c = cam.copy()
            c.turn_model(across, down)
            c._axes = viewmath.snapped(c.axes)
            todo.append(c)
    return list(seen.values())


def _overlap(rect, polygon) -> bool:
    x0, y0, w, h = rect
    xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
    return min(xs) < x0 + w and max(xs) > x0 and min(ys) < y0 + h and max(ys) > y0


def test_the_cubes_buttons_never_cover_it():
    """Home, always shown, lies outside the circle round the cube in any orientation; the
    step and roll arrows, shown only looking straight at a face, lie off the cube then and
    off each other."""
    faced = _quarter_orientations()
    assert len(faced) == 24
    for size in (96, 128):
        rects = viewcube.control_rects(size)
        names = list(rects)
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                (ax, ay, aw, ah), (bx, by, bw, bh) = rects[a], rects[b]
                e = 1e-9  # side by side, touching, is not overlapping
                assert not (
                    ax < bx + bw - e and bx < ax + aw - e and ay < by + bh - e and by < ay + ah - e
                ), (a, b)
        x, y, w, h = rects[viewcube.HOME]
        corner = max(abs(x + w - size / 2), abs(y + h - size / 2))
        assert math.hypot(corner, corner) > math.sqrt(3) * viewcube.HALF * size
        for cam in faced:
            shown = viewcube.shown_controls(cam.axes, FREE)
            assert shown == {viewcube.HOME, *viewcube.STEPS, *viewcube.ROLLS}
            for cell in viewcube.cells(cam.axes, size):
                assert not any(_overlap(rects[n], cell.polygon) for n in shown), cell
        for cam in _random_cameras(50):
            assert viewcube.shown_controls(cam.axes, FREE) == {viewcube.HOME}
    side = _camera(TURNTABLE)
    side.set_view("front")
    assert viewcube.shown_controls(side.axes, TURNTABLE) == {viewcube.HOME, *viewcube.STEPS}
    side.set_view("top")
    assert viewcube.ROLLS[0] in viewcube.shown_controls(side.axes, TURNTABLE)


def test_the_cube_is_sized_and_placed_for_the_view():
    assert viewcube.cube_side(760, 560) == 123
    assert viewcube.cube_side(600, 440) == 97
    assert viewcube.cube_side(1000, 700) == 128 and viewcube.cube_side(3000, 2000) == 128
    assert viewcube.cube_side(500, 300) == 96
    assert viewcube.cube_side(299, 800) == 0 and viewcube.placement(800, 299) is None
    assert viewcube.placement(760, 560) == (760 - 123 - 8, 8, 123, 123)


# --------------------------------------------------------------------------- the camera, no Qt
def test_slerp_ends_where_it_should_at_a_steady_speed():
    a = viewmath.quat_of_axes(_camera().axes)
    end = _camera()
    end.look_from((-1, -1, -1))
    b = viewmath.quat_of_axes(end.axes)
    assert viewmath.slerp(a, b, 0.0) == pytest.approx(a, abs=1e-12)
    assert viewmath.slerp(a, b, 1.0) == pytest.approx(b, abs=1e-12) or viewmath.slerp(
        a, b, 1.0
    ) == pytest.approx(tuple(-v for v in b), abs=1e-12)
    total = viewmath.quat_angle(a, b)
    for t in (0.1, 0.25, 0.5, 0.9):
        assert viewmath.quat_angle(a, viewmath.slerp(a, b, t)) == pytest.approx(t * total, abs=1e-6)
    assert _close(viewmath.axes_of_quat(b)[2], end.back, 1e-12)
    # A half turn goes one way round, not through nothing.
    front, back = _camera(), _camera()
    front.set_view("front")
    back.set_view("back")
    q0, q1 = viewmath.quat_of_axes(front.axes), viewmath.quat_of_axes(back.axes)
    mid = viewmath.axes_of_quat(viewmath.slerp(q0, q1, 0.5))
    assert viewmath.orthonormal(mid[0], mid[2]) is not None and abs(mid[2][2]) < 1e-9


@pytest.mark.parametrize("mode", [FREE, TURNTABLE])
def test_a_camera_move_eases_to_exactly_its_end(mode):
    cam = _camera(mode)
    cam.rotate(130, 40)
    cam.zoom(2.0)
    yaw, pitch = viewmath.region_angles((-1, 1, -1))
    move = viewmath.CameraMove(cam, {"yaw": yaw, "pitch": pitch, "fitted": True}, 10.0)
    assert viewmath.MOVE_MIN_S <= move.duration <= viewmath.MOVE_MAX_S
    assert move.state(cam)["fitted"] and move.state(cam)["yaw"] == yaw
    t, rights = 10.0, []
    while not move.apply(cam, t):
        assert not cam.fitted
        rights.append(cam.right)
        t += 0.016
    assert len(rights) >= 10
    goal = _camera(mode)
    goal.look_from((-1, 1, -1))
    assert cam.view_matrix() == goal.view_matrix() and cam.projection_matrix() == goal.projection_matrix()
    assert cam.fitted
    if mode == TURNTABLE:  # it never rolls on the way
        assert all(abs(r[1]) < 1e-12 for r in rights)
    # A short move takes the least time, a half turn the most.
    still = _camera(mode)
    assert viewmath.CameraMove(still, still.state(), 0.0).duration == viewmath.MOVE_MIN_S
    half = _camera(mode)
    half.set_view("front")
    assert viewmath.CameraMove(half, {"yaw": 180.0, "pitch": 0.0, "fitted": True}, 0.0).duration == 0.5


def test_a_fitted_move_lands_fitted_on_a_box_that_changed_on_the_way():
    cam = _camera()
    move = viewmath.CameraMove(cam, {"yaw": 0.0, "pitch": 0.0, "fitted": True}, 0.0)
    move.apply(cam, move.duration / 2)
    cam.bbox = ((0.0, 0.0, 0.0), (0.4, 0.03, 0.01))  # exploded meanwhile
    cam.aspect = 0.8
    move.apply(cam, move.duration)
    goal = viewmath.OrbitCamera(cam.bbox)
    goal.aspect = 0.8
    goal.set_view("front")
    assert cam.fitted and cam.view_matrix() == goal.view_matrix()
    assert cam.projection_matrix() == goal.projection_matrix()


def test_unproject_undoes_project_with_and_without_a_shift():
    for shift in ((0.0, 0.0), (0.3, -0.2)):
        for cam in _random_cameras(20, seed=5):
            cam.shift = shift
            cam.pan(17, -9, 600)
            for p in viewmath.corners(BOX):
                nx, ny, nz = cam.project(p)
                q = viewmath.unproject(cam, nx, ny, (nz + 1) / 2)
                assert _close(p, q, 1e-12)


def _precision(fmt: str):
    """A float rounded to IEEE single (``f``) or half (``e``) precision, as a GPU works."""
    import struct

    def rounded(v: float) -> float:
        return struct.unpack(fmt, struct.pack(fmt, v))[0]

    return rounded


def test_the_depth_pass_packs_24_bits_without_overflowing_half_precision():
    """The depth pass writes a depth as three bytes, worked out a byte at a time so that no
    value on the way exceeds 256. In single precision (desktop OpenGL) it reads back within
    one of its 255 x 65536 steps. In half precision, which OpenGL ES's mediump may be (its
    largest number is 65504, and 2^24 times a depth, as the depth used to be packed, is
    infinite there, a NaN once taken a byte at a time), every byte is still a byte and the
    depth holds about 11 bits."""
    single, half = _precision("f"), _precision("e")
    rng = random.Random(7)
    depths = [0.0, 1.0, 0.5, 1 / 255, 254.5 / 255, 1 - 1e-7] + [rng.random() for _ in range(5000)]
    for z in depths:
        got = viewmath.depth_bytes(single(z), single)
        assert all(0 <= b <= 255 for b in got)
        assert abs(viewmath.depth_of(*got) - single(z)) <= 1.0 / viewmath.DEPTH_STEPS
        low = viewmath.depth_bytes(half(z), half)
        assert all(0 <= b <= 255 for b in low)
        assert abs(viewmath.depth_of(*low) - z) < 1e-3
    assert viewmath.depth_bytes(1.0) == (0, 0, 255) and viewmath.depth_of(0, 0, 255) == 1.0
    assert viewmath.depth_bytes(0.5) == (0, 128, 127) and viewmath.depth_of(0, 128, 127) == 0.5
    assert viewmath.depth_of(0, 0, 0) == 0.0 and viewmath.depth_of(255, 255, 255) == 1.0
    with pytest.raises(OverflowError):
        half(0.73 * 16777215.0)


@pytest.mark.parametrize("mode", [FREE, TURNTABLE])
def test_a_turn_about_a_point_keeps_it_under_the_pointer(mode):
    """Turned about a model point, that point keeps its place on the screen and its depth,
    however the drag is split, and turning back undoes the turn; the turntable still
    stops at straight above."""
    width, height = 900, 600
    for about in ((0.04, 0.0, 0.01), (0.01, 0.025, 0.0), (0.0, 0.0, 0.0)):
        ends = []
        for moves in (1, 7, 60):
            cam = _camera(mode)
            cam.zoom(1.8, viewmath.ndc(600, 200, width, height))
            before = cam.project(about)[:2]
            start = cam.view_matrix()
            for _ in range(moves):
                cam.rotate(140 / moves, 90 / moves, about)
            assert cam.project(about)[:2] == pytest.approx(before, abs=1e-12)
            ends.append(cam.view_matrix())
            for _ in range(moves):
                cam.rotate(-140 / moves, -90 / moves, about)
            assert cam.view_matrix() == pytest.approx(start, abs=1e-12)
        assert ends[1] == pytest.approx(ends[0], abs=1e-12) and ends[2] == pytest.approx(ends[0], abs=1e-12)
    table = _camera(TURNTABLE)
    table.rotate(0, 10_000, (0.04, 0.0, 0.01))
    assert table.pitch == viewmath.PITCH_LIMIT


def test_roll_turns_about_the_line_of_sight_and_a_turntable_only_from_above():
    cam = _camera()
    cam.set_view("front")
    assert cam.roll(90)  # counter-clockwise on the screen: the model's top goes left
    assert _close(cam.up, (1, 0, 0)) and _close(cam.right, (0, -1, 0)) and _close(cam.back, (0, 0, 1))
    assert not cam.fitted
    cam.roll(-90)
    assert _close(cam.up, (0, 1, 0))
    for _ in range(24):
        cam.roll(15)
    assert _close(cam.up, (0, 1, 0), 1e-12)
    table = _camera(TURNTABLE)
    table.set_view("front")
    assert not table.roll(90) and table.yaw == 0  # a turntable never rolls a side view
    table.set_view("top")
    free = _camera()
    free.set_view("top")
    for sign in (1, -1):
        t, f = table.copy(), free.copy()
        assert t.roll(90 * sign) and f.roll(90 * sign)
        assert _close(t.axes[0], f.axes[0]) and _close(t.axes[1], f.axes[1])  # the same turn on the screen
    table.set_view("bottom")
    free.set_view("bottom")
    assert table.roll(30) and free.roll(30) and _close(table.right, free.right)


def _right_handed(axes) -> bool:
    right, up, back = axes
    return all(abs(c) in (0, 1) for v in axes for c in v) and tuple(
        right[(k + 1) % 3] * up[(k + 2) % 3] - right[(k + 2) % 3] * up[(k + 1) % 3] for k in range(3)
    ) == tuple(back)


def test_the_step_arrows_need_a_face_square_on_and_the_roll_arrows_square_it_up():
    """Looking straight at a face but rolled part of the way (a roll key, or a turntable
    dragged up to straight above, which keeps the isometric's yaw of 45 degrees), the face
    on a side of the screen is no one face: the step arrows hide, where they used to land
    15 or 45 degrees off every face. The roll arrows stay and roll to the next quarter turn,
    so they square the view up, and then the steps come back. Every step and roll lands on
    whole axes."""
    cam = _camera()
    cam.set_view("front")
    cam.roll(-15)
    shown = viewcube.shown_controls(cam.axes, FREE)
    assert set(viewcube.ROLLS) <= shown and not set(viewcube.STEPS) & shown
    assert viewcube.face_on(cam.axes) == (0, 0, 1) and viewcube.square_on(cam.axes) is None
    assert viewcube.stepped(cam.axes, "step-up") is None
    assert viewcube.rolled(cam.axes, 1) == ((1, 0, 0), (0, 1, 0), (0, 0, 1))  # 15 back: square
    assert viewcube.rolled(cam.axes, -1) == ((0, 1, 0), (-1, 0, 0), (0, 0, 1))  # 75 on: the top to the right
    table = _camera(TURNTABLE)
    table.turn(0, 90)  # dragged up from the isometric
    assert table.yaw == 45 and viewcube.face_on(table.axes) == (0, 1, 0)
    shown = viewcube.shown_controls(table.axes, TURNTABLE)
    assert set(viewcube.ROLLS) <= shown and not set(viewcube.STEPS) & shown
    assert viewcube.rolled(table.axes, 1)[1] in ((-1, 0, 0), (0, 0, -1))  # a quarter's edge: square
    # Square on, a roll is a quarter turn and a step brings the face on that side to the front.
    for cam in _quarter_orientations():
        right, up, back = (tuple(round(c) for c in v) for v in cam.axes)
        assert viewcube.square_on(cam.axes) == (right, up, back)
        assert viewcube.shown_controls(cam.axes, FREE) >= set(viewcube.STEPS)
        sides = {
            "step-up": up,
            "step-down": tuple(-c for c in up),
            "step-left": tuple(-c for c in right),
            "step-right": right,
        }
        for side, faced in sides.items():
            got = viewcube.stepped(cam.axes, side)
            assert _right_handed(got) and got[2] == faced, (side, got)
        for sign in (1, -1):
            turned = viewcube.rolled(cam.axes, sign)
            assert _right_handed(turned) and turned[2] == back
            assert turned[0] == (tuple(-c for c in up) if sign > 0 else up)  # 90 degrees that way
            again = cam.axes
            for _ in range(4):
                again = viewcube.rolled(again, sign)
            assert again == (right, up, back)  # four quarters round


def test_a_move_on_a_model_under_a_micrometre_zooms_one_way():
    """A fit draws a point-like model under :data:`.viewmath.OrbitCamera.MIN_HALF`; a move
    between two such fits zoomed in up to 87 times on the way and snapped back at the end,
    and took the longest a move takes. Now it zooms steadily from the one to the other, and
    a move that hardly zooms takes the time its turn takes."""
    for size in (1e-9, 5e-8, 1e-3):
        cam = viewmath.OrbitCamera(((0.0, 0.0, 0.0), (size, size, size)))
        cam.aspect = 1.4
        cam.reset()
        start = cam.half_height
        yaw, pitch = viewmath.region_angles((1, 0, 0))
        move = viewmath.CameraMove(cam, {"yaw": yaw, "pitch": pitch, "fitted": True}, 0.0)
        goal = move.goal(cam).half_height
        lo, hi = min(start, goal), max(start, goal)
        t, seen = 0.0, []
        while not move.apply(cam, t):
            seen.append(cam.half_height)
            t += 0.016
        assert seen and all(lo * (1 - 1e-9) <= h <= hi * (1 + 1e-9) for h in seen), size
        assert cam.half_height == pytest.approx(goal, rel=1e-12) and cam.fitted
        assert move.duration < viewmath.MOVE_MAX_S


def test_a_fit_centres_the_model_in_the_free_area():
    """With the legend over the right of the view, a fit puts the model in the area left of
    it or the one below, whichever shows it larger, centred there by a lens shift; the
    model still turns about its own centre, which stays in that area's middle."""
    width, height = 900, 600
    cam = _camera(aspect=width / height)
    whole = cam.half_height
    left = (-1.0, -1.0, 0.2, 1.0)  # left of a column over the right 40 percent
    below = (-1.0, -1.0, 1.0, 0.0)  # below a column over the top half
    cam.set_free([left, below])
    # Seen from the isometric view, the box is as large left of the column as in the whole
    # view (its height holds it there); below the column it would be half as large.
    assert cam.fitted and cam.shift == (-0.4, 0.0) and cam.half_height == pytest.approx(whole)
    for k in viewmath.corners(BOX):
        x, y, _z = cam.project(k)
        assert -1 <= x <= 0.2 and -1 <= y <= 1
    ref = _camera(aspect=width / height)
    ref.free = (left,)
    ref.fit()
    ref2 = _camera(aspect=width / height)
    ref2.free = (below,)
    ref2.fit()
    assert cam.half_height == min(ref.half_height, ref2.half_height)
    centre = cam.project(cam.center)[:2]
    assert centre == pytest.approx(cam.shift, abs=1e-12)
    cam.turn_model(70, 20)
    assert cam.project(cam.center)[:2] == pytest.approx(cam.shift, abs=1e-12)
    # Panning and zooming toward the cursor stay exact with a shift.
    cam.zoom(1.7, (0.6, -0.4))
    p = cam.point_at(0.6, -0.4)
    assert cam.project(p)[:2] == pytest.approx((0.6, -0.4), abs=1e-12)
    # A moved camera keeps its shift until the next fit; of equals, the first area wins.
    cam.set_free(None)
    assert cam.shift != (0.0, 0.0) and not cam.fitted
    cam.fit()
    assert cam.shift == (0.0, 0.0)
    cam.set_free([(-1.0, -1.0, 0.0, 1.0), (0.0, -1.0, 1.0, 1.0)])  # two halves, side by side
    assert cam.shift == (-0.5, 0.0)


def test_a_fit_keeps_the_model_off_the_view_cube_where_that_costs_little():
    """Without the legend, a fit whose box would reach under the view cube's corner puts the
    model left of the cube or below it instead, whichever shows it larger, unless that draws
    it under AVOID_SHARE as large; one whose outline clears the corner stays in the middle,
    as an isometric box does though the rectangle round it would not."""
    width, height = 900, 600
    x, y, side, _h = viewcube.placement(width, height)
    avoid = viewmath.avoid_area(width, height, (x, y, side, side))
    assert avoid == pytest.approx((2 * (x - 8) / width - 1, 1 - 2 * (y + side + 8) / height, 1.0, 1.0))

    def fitted(box, view, area=avoid, aspect=width / height):
        cam = viewmath.OrbitCamera(box)
        cam.aspect = aspect
        cam.set_free(None, area)
        cam.set_view(view)
        return cam

    def reaches(cam, area=avoid):
        outline = viewmath._hull([cam.project(k)[:2] for k in viewmath.corners(cam.bbox)])
        return viewmath._meets(outline, area)

    # A long model from the front: below the cube it is as large as in the whole view.
    long_box = ((0.0, 0.0, 0.0), (0.3, 0.15, 0.02))
    whole, cam = fitted(long_box, "front", None), fitted(long_box, "front")
    assert reaches(whole) and not reaches(cam)
    assert cam.half_height == pytest.approx(whole.half_height) and cam.shift[0] == 0 and cam.shift[1] < 0
    assert cam.copy().avoid == avoid  # a move's end works out the same
    # Shaped like the view: left of the cube it is 16 percent smaller, which a fit gives up.
    shaped = ((0.0, 0.0, 0.0), (0.3, 0.2, 0.02))
    whole, cam = fitted(shaped, "front", None), fitted(shaped, "front")
    assert not reaches(cam) and cam.shift[0] < 0 and cam.shift[1] == 0
    assert whole.half_height / cam.half_height == pytest.approx(0.84, abs=0.005)
    # In a 500 x 400 view it would be 22 percent smaller: too much, so it stays.
    small = viewmath.avoid_area(500, 400, viewcube.placement(500, 400))
    cam = fitted(((0.0, 0.0, 0.0), (0.25, 0.2, 0.02)), "front", small, 500 / 400)
    assert reaches(cam, small) and cam.shift == (0.0, 0.0)
    # A cube from the isometric view in a square view: its hexagon clears the corner that the
    # rectangle round it reaches into.
    square = viewmath.avoid_area(700, 700, viewcube.placement(700, 700))
    cube_box = ((0.0, 0.0, 0.0), (0.1, 0.1, 0.1))
    cam = fitted(cube_box, "isometric", square, 1.0)
    xs, ys = zip(*[cam.project(k)[:2] for k in viewmath.corners(cube_box)], strict=True)
    assert max(xs) > square[0] and max(ys) > square[1]
    assert not reaches(cam, square) and cam.shift == (0.0, 0.0)
    # The legend's column already keeps clear of the cube: nothing more moves.
    left = (-1.0, -1.0, 0.2, 1.0)
    cam = viewmath.OrbitCamera(long_box)
    cam.aspect = width / height
    cam.set_free([left], avoid)
    cam.set_view("front")
    assert cam.shift == (-0.4, 0.0)


def test_keep_in_view_refits_only_a_model_that_left_the_free_area():
    cam = _camera()
    cam.pan(50, 0, 600)
    kept = cam.state()
    cam.bbox = ((0.0, 0.0, 0.0), (0.05, 0.03, 0.01))  # another configuration, overlapping
    assert not cam.keep_in_view() and cam.state() == {**kept}
    cam.bbox = ((5.0, -5.0, 0.0), (5.04, -4.97, 0.01))  # far off the view
    back = cam.back
    assert cam.keep_in_view() and cam.fitted and _close(cam.back, back)
    cam.zoom(0.02)  # zoomed out as far as it goes
    cam.bbox = ((5.0, -5.0, 0.0), (5.001, -4.999, 0.001))  # a far smaller model: too far out for it
    assert cam.keep_in_view() and cam.fitted


def test_old_camera_states_without_a_shift_still_read():
    cam = _camera()
    cam.shift = (0.3, 0.1)
    old = {"yaw": 75.0, "pitch": 20.0, "target": [0.01, 0.02, 0.0], "half_height": 0.05, "fitted": False}
    cam.set_state(old)
    assert cam.shift == (0.0, 0.0)
    for bad in (None, "x", [1], [math.nan, 0], [1, 2, 3]):
        cam.set_state({**old, "shift": bad})
        assert cam.shift == (0.0, 0.0), bad
    cam.set_state({**old, "shift": [0.25, -0.5]})
    assert cam.shift == (0.25, -0.5) and cam.state()["shift"] == [0.25, -0.5]


# --------------------------------------------------------------------------- the widget, offscreen
@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from solidseas_app.viewer.app import use_system_fonts

    use_system_fonts()
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _part():
    return mesh3d.read_part_mesh(str(fixture_path(O02)), str(FIXTURES), 1000)["data"]


class _Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def _shown_view(app, mode: str = FREE, size=(760, 560)):
    """A 3D view on screen (offscreen: no OpenGL, but laid out and visible), showing o02,
    on a clock of the test's own."""
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from solidseas_app.viewer import view3d

    host = QWidget()
    view = view3d.ModelView(rotation_mode=mode)
    QVBoxLayout(host).addWidget(view)
    host.layout().setContentsMargins(0, 0, 0, 0)
    host.resize(*size)
    host.show()
    app.processEvents()
    view.set_mesh(_part())
    view._clock = clock = _Clock()
    view._ticker.stop()  # the test steps the move itself
    return host, view, clock


def _mouse(widget, kind, x, y, button=None, mods=None):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    button = button or Qt.MouseButton.LeftButton
    mods = mods or Qt.KeyboardModifier.NoModifier
    p = QPointF(x, y)
    pressed = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else button
    held = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else button
    event = QMouseEvent(kind, p, widget.mapToGlobal(p), pressed, held, mods)
    QApplication.sendEvent(widget, event)
    return event


def _click(widget, x, y, button=None):
    from PySide6.QtCore import QEvent

    _mouse(widget, QEvent.Type.MouseButtonPress, x, y, button)
    _mouse(widget, QEvent.Type.MouseButtonRelease, x, y, button)


def _key(widget, key, mods=None):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication

    QApplication.sendEvent(
        widget, QKeyEvent(QEvent.Type.KeyPress, key, mods or Qt.KeyboardModifier.NoModifier)
    )


def _run_move(view, clock, step: float = 0.016) -> int:
    frames = 0
    while view.moving:
        clock.t += step
        view._tick()
        frames += 1
        assert frames < 100
    return frames


@needs_qt
def test_the_cube_sits_top_right_and_the_legend_under_it(app):
    from solidseas_app.viewer import preview

    host, shown, _clock = _shown_view(app)
    try:
        cube = shown.cube
        assert cube.isVisible() and cube.geometry().getRect() == (760 - 123 - 8, 8, 123, 123)
        assert shown.legend_top() == 8 + 123 + 6
        legend = preview.Legend(shown)
        legend.set_files(
            [{"name": f"part{k}", "color": "#336699", "instances": 1, "key": f"k{k}"} for k in range(4)]
        )
        legend.show()
        assert legend.y() == shown.legend_top() and legend.geometry().right() == 760 - 8 - 1
        host.resize(1000, 700)
        app.processEvents()
        assert cube.geometry().getRect() == (1000 - 128 - 8, 8, 128, 128) and legend.y() == 8 + 128 + 6
        shown.set_cube_shown(False)
        assert not cube.isVisible() and legend.y() == 8 and shown.legend_top() == 8
        shown.set_cube_shown(True)
        assert cube.isVisible() and legend.y() == 8 + 128 + 6
        host.resize(500, 280)  # too small for a cube: it would take a third of the short side
        app.processEvents()
        assert not cube.isVisible() and legend.y() == 8
        # Its picture: drawn at its own size, transparent beside the cube.
        host.resize(760, 560)
        app.processEvents()
        img = cube.picture()
        assert (img.width(), img.height()) == (round(123 * cube.devicePixelRatioF()),) * 2
        assert img.pixelColor(img.width() - 2, img.height() - 2).alpha() == 0
        centre = img.pixelColor(img.width() // 2, img.height() // 2 + 15)
        assert centre.alpha() == 255
    finally:
        host.deleteLater()


@needs_qt
def test_cube_clicks_turn_the_view_and_never_reach_the_model(app):
    """A click on a face, an edge or a corner eases the camera to its view; on Home, a step
    arrow or a roll arrow, to theirs. The view never sees those presses: nothing is picked,
    no drag starts, no menu is asked for. A press on the cube's square beside the cube
    reaches the view, mapped to its own coordinates, and starts its drag there."""
    from PySide6.QtCore import QEvent, Qt

    host, view, clock = _shown_view(app)
    try:
        cube = view.cube
        events = []
        view.picked.connect(lambda i: events.append(("picked", i)))
        view.menuRequested.connect(lambda i, _p: events.append(("menu", i)))
        size = cube.width()
        for region in ((0, 0, 1), (0, 1, 1), (-1, 1, -1), (0, -1, 0)):
            path = viewcube.path_to(view.camera.axes, region, size)
            assert path[-1] == region and len(path) <= 3
            for step in path[:-1]:  # the hidden half, through what is drawn, as the self-test goes
                _click(cube, *viewcube.point_of(view.camera.axes, step, size))
                _run_move(view, clock)
            p = viewcube.point_of(view.camera.axes, region, size)
            _click(cube, *p)
            assert view.moving and view._press_button is None and view._drag is None
            assert view.camera_state()["fitted"]  # Back taken now returns where the move goes
            frames = _run_move(view, clock)
            assert frames >= 9  # 0.15 s at least, a frame every 16 ms
            goal = viewmath.OrbitCamera(view.camera.bbox)
            goal.aspect = view.camera.aspect
            goal.look_from(region)
            assert view.camera.view_matrix() == goal.view_matrix() and view.camera.fitted, region
            assert cube.axes == view.camera.axes  # the cube turned with it
        assert events == []

        # Looking straight at the bottom: the arrows step to the next face and roll.
        assert viewcube.face_on(view.camera.axes) == (0, -1, 0)
        rects = viewcube.control_rects(size)
        x, y, w, h = rects["step-right"]
        _click(cube, x + w / 2, y + h / 2)
        _run_move(view, clock)
        assert _close(view.camera.back, (1, 0, 0), 1e-12)
        x, y, w, h = rects["roll-cw"]
        up = view.camera.up
        _click(cube, x + w / 2, y + h / 2)
        _run_move(view, clock)
        assert _close(view.camera.back, (1, 0, 0), 1e-12) and _close(view.camera.right, up, 1e-12)
        x, y, w, h = rects[viewcube.HOME]
        _click(cube, x + w / 2, y + h / 2)
        _run_move(view, clock)
        assert (
            view.camera.axes == viewmath.turntable_axes(*viewmath.VIEWS["isometric"]) and view.camera.fitted
        )
        assert events == []

        # Beside the cube's regions, the press is the view's: a left-drag there turns the model.
        corner = (size - 3.0, size - 3.0)
        assert cube.at(*corner) is None
        before = view.camera.axes
        _mouse(cube, QEvent.Type.MouseButtonPress, *corner)
        assert view._drag == viewmath.ROTATE
        assert (view._press.x(), view._press.y()) == (cube.x() + corner[0], cube.y() + corner[1])
        _mouse(cube, QEvent.Type.MouseMove, corner[0] - 30, corner[1] + 20)
        _mouse(cube, QEvent.Type.MouseButtonRelease, corner[0] - 30, corner[1] + 20)
        assert view.camera.axes != before and view._drag is None
        # A drag on the cube turns the model as a drag on the view does, without easing.
        start = view.camera.copy()
        p = viewcube.point_of(view.camera.axes, (0, 0, 1), size)
        _mouse(cube, QEvent.Type.MouseButtonPress, *p)
        for k in range(1, 11):
            _mouse(cube, QEvent.Type.MouseMove, p[0] + 6 * k, p[1] + 3 * k)
        _mouse(cube, QEvent.Type.MouseButtonRelease, p[0] + 60, p[1] + 30)
        start.turn_model(24, 12)
        assert _close(view.camera.back, start.back) and _close(view.camera.up, start.up)
        assert not view.moving and events == []
        # A middle-drag over the cube is the view's too.
        _mouse(cube, QEvent.Type.MouseButtonPress, *p, Qt.MouseButton.MiddleButton)
        assert view._press_button == "middle"
        _mouse(cube, QEvent.Type.MouseButtonRelease, *p, Qt.MouseButton.MiddleButton)
    finally:
        host.deleteLater()


@needs_qt
def test_the_cube_has_its_own_menu_tooltips_and_fade(app, monkeypatch):
    from PySide6.QtCore import QEvent, QPoint, QPointF
    from PySide6.QtGui import QContextMenuEvent, QEnterEvent, QHelpEvent
    from PySide6.QtWidgets import QApplication, QToolTip

    from solidseas_app.viewer import cubewidget

    host, view, clock = _shown_view(app)
    try:
        cube = view.cube
        opened, menus, tips = [], [], []
        cube.run_menu = lambda menu, _where: opened.append([x.text() for x in menu.actions()])
        view.menuRequested.connect(lambda i, _p: menus.append(i))
        monkeypatch.setattr(QToolTip, "showText", lambda *a: tips.append(a[1]))

        def right_click(x, y):
            right = cubewidget.Qt.MouseButton.RightButton
            _mouse(cube, QEvent.Type.MouseButtonPress, x, y, right)
            _mouse(cube, QEvent.Type.MouseButtonRelease, x, y, right)
            q = QPoint(int(x), int(y))
            QApplication.sendEvent(
                cube, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, q, cube.mapToGlobal(q))
            )

        p = viewcube.point_of(view.camera.axes, (0, 0, 1), cube.width())
        right_click(*p)
        assert (
            opened == [["Home", "Set Current View as Home", "Reset Home to Isometric", "", "Fit"]]
            and not menus
        )
        right_click(cube.width() - 2, cube.width() - 2)  # beside the cube: the model's menu
        assert menus == [-1] and len(opened) == 1

        # Set Current View as Home, then Home goes there; Reset Home: the isometric.
        changed = []
        view.homeChanged.connect(changed.append)
        view.set_view("front")
        view.camera.zoom(1.5)
        state = view.camera_state()
        menu = cube.make_menu()
        assert not menu.actions()[2].isEnabled()
        menu.actions()[1].trigger()
        assert changed == [state] and view.home == state and cube.has_home
        view.reset_view()
        _key(view, cubewidget.Qt.Key.Key_Home)
        _run_move(view, clock)
        from solidseas_app.viewer.selftest import same_camera

        assert same_camera(view.camera_state(), state)
        menu = cube.make_menu()
        assert menu.actions()[2].isEnabled()
        menu.actions()[2].trigger()
        assert changed[-1] is None and view.home is None and not cube.has_home
        view.go_home(animate=False)
        assert (
            view.camera.axes == viewmath.turntable_axes(*viewmath.VIEWS["isometric"]) and view.camera.fitted
        )

        def hover(x, y):
            q = QPoint(int(x), int(y))
            event = QHelpEvent(QEvent.Type.ToolTip, q, cube.mapToGlobal(q))
            QApplication.sendEvent(cube, event)

        hover(*viewcube.point_of(view.camera.axes, (1, 1, 1), cube.width()))
        hover(*viewcube.point_of(view.camera.axes, (0, 1, 1), cube.width()))
        x, y, w, h = viewcube.control_rects(cube.width())[viewcube.HOME]
        hover(x + w / 2, y + h / 2)
        assert tips == [
            "<qt>Isometric: front, top and right (R)</qt>",
            "<qt>Front and top edge</qt>",
            "<qt>" + cubewidget.CONTROL_TIPS[viewcube.HOME] + "</qt>",
        ]

        # Translucent while the pointer is away, opaque over it.
        assert cube.target_opacity == cubewidget.AWAY
        QApplication.sendEvent(cube, QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
        assert cube.target_opacity == cubewidget.OVER
        QApplication.sendEvent(cube, QEvent(QEvent.Type.Leave))
        assert cube.target_opacity == cubewidget.AWAY and cube.hover is None
    finally:
        host.deleteLater()


@needs_qt
def test_other_navigation_takes_the_camera_from_a_move(app):
    """A press, the wheel, an arrow key or F stop a move where it is; another cube click,
    Home, R or Ctrl+n start a new one from there; Back and a new scene cancel it; switching
    the rotation mode ends it first. A view not on screen moves at once."""
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    from solidseas_app.viewer import view3d

    host, view, clock = _shown_view(app)
    try:

        def half_way():
            view.set_view("front")
            view.look_at_region((-1, 1, -1))
            clock.t += 0.08
            view._tick()
            assert view.moving
            return view.camera.view_matrix()

        wheel = QWheelEvent(
            QPointF(300, 300),
            QPointF(300, 300),
            QPoint(),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        there = half_way()
        _mouse(view, QEvent.Type.MouseButtonPress, 300, 300)  # stopped where the move got to
        assert not view.moving and view.camera.view_matrix() == there and not view.camera.fitted
        _mouse(view, QEvent.Type.MouseButtonRelease, 300, 300)
        half_way()
        half = view.camera.half_height
        QApplication.sendEvent(view, wheel)
        assert not view.moving and view.camera.half_height < half
        half_way()
        axes = view.camera.axes
        _key(view, Qt.Key.Key_Left)
        assert not view.moving and view.camera.axes != axes
        half_way()
        _key(view, Qt.Key.Key_F)
        assert not view.moving and view.camera.fitted
        for start, goal in (
            (lambda: _key(view, Qt.Key.Key_R), "isometric"),
            (lambda: _key(view, Qt.Key.Key_3, Qt.KeyboardModifier.ControlModifier), "left"),
            (lambda: _key(view, Qt.Key.Key_Home), "isometric"),
        ):
            half_way()
            start()
            assert view.moving
            assert view.camera_state()["yaw"] == viewmath.VIEWS[goal][0]
            _run_move(view, clock)
            assert view.camera.axes == viewmath.turntable_axes(*viewmath.VIEWS[goal])
        half_way()
        back = {"yaw": 10.0, "pitch": 5.0, "target": [0, 0, 0], "half_height": 0.05, "fitted": False}
        view.set_camera_state(back)
        assert not view.moving and view.camera.half_height == 0.05
        half_way()
        view.set_mesh(_part())
        assert not view.moving and view.camera.axes == viewmath.turntable_axes(*viewmath.VIEWS["isometric"])
        half_way()
        view.set_rotation_mode(TURNTABLE)
        assert not view.moving and view.camera.yaw == pytest.approx(viewmath.region_angles((-1, 1, -1))[0])
        hidden = view3d.ModelView()
        hidden.set_mesh(_part())
        _key(hidden, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
        assert not hidden.moving and hidden.camera.axes == viewmath.turntable_axes(*viewmath.VIEWS["front"])
        hidden.deleteLater()
    finally:
        host.deleteLater()


@needs_qt
def test_turntable_steps_are_upright_and_its_roll_arrows_show_only_above_or_below(app):
    host, view, clock = _shown_view(app, TURNTABLE)
    try:
        view.set_view("top")
        view.step("step-right")
        _run_move(view, clock)
        assert _close(view.camera.back, (1, 0, 0), 1e-12) and _close(view.camera.up, (0, 1, 0), 1e-12)
        assert viewcube.ROLLS[0] not in view.cube.shown
        before = view.camera.state()
        view.cube_roll(1)
        assert not view.moving and view.camera.state() == before
        view.set_view("top")
        assert set(viewcube.ROLLS) <= view.cube.shown
        view.cube_roll(-1)
        _run_move(view, clock)
        assert view.camera.pitch == 90 and view.camera.yaw == pytest.approx(90)
        # Free: from Top, the right arrow shows Right with -Z up, as the step turned it.
        view.set_rotation_mode(FREE)
        view.set_view("top")
        view.step("step-right")
        _run_move(view, clock)
        assert _close(view.camera.back, (1, 0, 0), 1e-12) and _close(view.camera.up, (0, 0, -1), 1e-12)
        view.step("step-up")
        _run_move(view, clock)
        assert _close(view.camera.back, (0, 0, -1), 1e-12)  # the face above came to the front
    finally:
        host.deleteLater()


@needs_qt
@pytest.mark.parametrize("mode", [FREE, TURNTABLE])
def test_a_rolled_face_view_shows_no_step_arrows_and_a_roll_arrow_squares_it(app, mode):
    from PySide6.QtCore import Qt

    host, view, clock = _shown_view(app, mode)
    try:
        cube, cam = view.cube, view.camera
        if mode == FREE:
            view.set_view("front")
            _key(view, Qt.Key.Key_PageDown)  # 15 degrees clockwise
        else:
            cam.turn(0, 90)  # a drag up from the isometric: straight down, the yaw still 45
            view.update()
        assert not set(viewcube.STEPS) & cube.shown and set(viewcube.ROLLS) <= cube.shown
        before = cam.state()
        view.step("step-up")
        assert not view.moving and cam.state() == before  # nothing: no one face lies above
        rects = viewcube.control_rects(cube.width())
        x, y, w, h = rects["roll-ccw"]
        _click(cube, x + w / 2, y + h / 2)
        _run_move(view, clock)
        assert viewcube.square_on(cam.axes) is not None and cam.fitted
        assert set(viewcube.STEPS) <= cube.shown
        face, up = viewcube.face_on(cam.axes), tuple(round(c) for c in cam.up)
        x, y, w, h = rects["step-up"]
        _click(cube, x + w / 2, y + h / 2)
        _run_move(view, clock)
        assert _close(cam.back, up, 1e-12) and face != viewcube.face_on(cam.axes)
    finally:
        host.deleteLater()


@needs_qt
@pytest.mark.parametrize("mode", [FREE, TURNTABLE])
def test_a_double_click_on_the_cube_is_its_click_however_the_cube_turns_between_the_two(app, mode):
    """A person's double-click on a step arrow or a corner: by the second click the move has
    gone most of the way, the arrow has hidden and the corner has moved from under the
    pointer. That second click used to reach the view, which fitted the camera where the
    move had got to (or would open the component there). It is the cube's: the move goes
    on to its end. Driven through the window, as Qt delivers a real double-click."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    host, view, clock = _shown_view(app, mode)
    try:
        win, cube = host.windowHandle(), view.cube
        left, none = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
        opened, fits = [], []
        view.activated.connect(opened.append)
        fit = view.fit
        view.fit = lambda: (fits.append(1), fit())
        under = []

        def between(*_):  # the time between a person's two clicks
            clock.t += 0.12
            view._tick()
            under.append((cube.shown, cube.at(*spot)))

        cube.stepClicked.connect(between)
        cube.regionClicked.connect(between)
        view.set_view("front")
        x, y, w, h = viewcube.control_rects(cube.width())["step-up"]
        spot = (x + w / 2, y + h / 2)
        QTest.mouseDClick(win, left, none, QPoint(int(cube.x() + spot[0]), int(cube.y() + spot[1])))
        assert "step-up" not in under[-1][0]  # the arrow had hidden by the second click
        assert view.moving and not fits
        _run_move(view, clock)
        assert _close(view.camera.back, (0, 1, 0), 1e-12) and view.camera.fitted
        view.go_home(animate=False)
        spot = viewcube.point_of(cube.axes, (-1, 1, 1), cube.width())
        QTest.mouseDClick(win, left, none, QPoint(int(cube.x() + spot[0]), int(cube.y() + spot[1])))
        assert under[-1][1] != (-1, 1, 1)  # the corner had moved from under the pointer
        assert view.moving and not fits
        _run_move(view, clock)
        assert _close(view.camera.back, _unit((-1, 1, 1)), 1e-12) and view.camera.fitted
        assert not opened
        # Beside the cube's regions a double-click is still the view's: it fits.
        corner = QPoint(int(cube.x() + cube.width() - 3), int(cube.y() + cube.width() - 3))
        view.camera.zoom(1.5)
        QTest.mouseDClick(win, left, none, corner)
        assert fits and view.camera.fitted
    finally:
        host.deleteLater()


@needs_qt
def test_a_right_drag_off_the_cube_or_onto_it_opens_no_menu(app):
    """As on Windows, where the menu is asked for when the right button is let go, under the
    pointer: a right press on the cube dragged onto the model used to open the model's menu
    (the view read the drag of its own last right-click), and one dragged from the model
    onto the cube the cube's. Neither opens a menu now; right-clicks on each still open
    theirs, and beside the cube's regions the model's."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    hints = app.styleHints()
    trigger = hints.contextMenuTrigger()
    hints.setContextMenuTrigger(Qt.ContextMenuTrigger.Release)
    host, view, _clock = _shown_view(app)
    try:
        win, cube = host.windowHandle(), view.cube
        right, none = Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier
        menus = []
        view.menuRequested.connect(lambda i, _p: menus.append(("model", i)))
        cube.run_menu = lambda _menu, _where: menus.append(("cube",))

        def gesture(start, end):
            QTest.mousePress(win, right, none, start)
            dx, dy = end.x() - start.x(), end.y() - start.y()
            for k in range(1, 8):
                QTest.mouseMove(win, QPoint(start.x() + dx * k // 7, start.y() + dy * k // 7))
            QTest.mouseRelease(win, right, none, end)
            app.processEvents()
            got = list(menus)
            menus.clear()
            return got

        px, py = viewcube.point_of(view.camera.axes, (0, 0, 1), cube.width())
        on_cube = QPoint(int(cube.x() + px), int(cube.y() + py))
        on_view = QPoint(on_cube.x() - 210, on_cube.y() + 210)
        beside = QPoint(int(cube.x() + cube.width() - 3), int(cube.y() + cube.width() - 3))
        assert gesture(on_view, on_view) == [("model", -1)]
        assert gesture(on_cube, on_view) == []
        assert gesture(on_view, on_cube) == []
        assert gesture(on_cube, on_cube) == [("cube",)]
        assert gesture(beside, beside) == [("model", -1)]
        hints.setContextMenuTrigger(Qt.ContextMenuTrigger.Press)  # as on Linux: asked on the press
        assert gesture(on_cube, on_cube) == [("cube",)]
        assert gesture(on_view, on_view) == [("model", -1)]
    finally:
        hints.setContextMenuTrigger(trigger)
        host.deleteLater()


@needs_qt
def test_a_key_that_eases_acts_at_once_during_a_drag(app):
    """R, Home and Ctrl+1 to Ctrl+7 ease the camera; pressed during a drag, the move fought
    the drag, whose moves it overwrote until it ended. During a drag they act at once and
    the drag goes on from there; a drag's move stops a move under way, as its press does."""
    from PySide6.QtCore import QEvent, Qt

    host, view, clock = _shown_view(app)
    try:
        cam = view.camera
        iso = cam.copy()
        iso.reset()
        view.set_view("front")
        _mouse(view, QEvent.Type.MouseButtonPress, 200, 300)
        for k in range(1, 4):
            _mouse(view, QEvent.Type.MouseMove, 200 + 10 * k, 300)
        _key(view, Qt.Key.Key_R)
        assert not view.moving and cam.view_matrix() == iso.view_matrix()
        for k in range(4, 14):
            _mouse(view, QEvent.Type.MouseMove, 200 + 10 * k, 300)
        _mouse(view, QEvent.Type.MouseButtonRelease, 330, 300)
        iso.rotate(100, 0)
        assert _close(cam.back, iso.back) and _close(cam.up, iso.up)
        # A drag of the cube holds the camera too.
        p = viewcube.point_of(cam.axes, (0, 0, 1), view.cube.width())
        _mouse(view.cube, QEvent.Type.MouseButtonPress, *p)
        _mouse(view.cube, QEvent.Type.MouseMove, p[0] + 20, p[1])
        _key(view, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
        assert not view.moving and view.camera.axes == viewmath.turntable_axes(*viewmath.VIEWS["front"])
        _mouse(view.cube, QEvent.Type.MouseButtonRelease, p[0] + 20, p[1])
        # Should a move be under way at a drag's move, it stops there, as at the drag's press.
        _mouse(view, QEvent.Type.MouseButtonPress, 200, 300)
        view._drag, pressed = None, view._drag  # a move set going under the drag
        view.look_at_region((-1, 1, -1))
        view._drag = pressed
        assert view.moving
        _mouse(view, QEvent.Type.MouseMove, 210, 300)
        assert not view.moving
        _mouse(view, QEvent.Type.MouseButtonRelease, 210, 300)
    finally:
        host.deleteLater()


@needs_qt
def test_without_the_legend_a_fit_keeps_the_model_off_the_cube(app):
    """o02 seen from the left reaches under the cube in a 760 x 560 view: a fit puts it below
    the cube instead, at least AVOID_SHARE as large; from the isometric view it clears the
    corner and stays in the middle; with the cube hidden the whole view is the model's."""
    host, view, _clock = _shown_view(app)
    try:
        cam = view.camera
        assert cam.avoid == pytest.approx(viewmath.avoid_area(760, 560, view.cube.geometry().getRect()))
        view.set_view("left")
        whole = cam.copy()
        whole.avoid = None
        whole.fit()
        outline = viewmath._hull([cam.project(k)[:2] for k in viewmath.corners(cam.bbox)])
        assert not viewmath._meets(outline, cam.avoid) and cam.shift != (0.0, 0.0)
        assert whole.half_height / cam.half_height >= viewmath.OrbitCamera.AVOID_SHARE
        view.set_view("isometric")
        assert cam.shift == (0.0, 0.0)
        view.set_view("left")
        view.set_cube_shown(False)
        assert cam.avoid is None and cam.shift == (0.0, 0.0) and cam.fitted
        view.set_cube_shown(True)
        assert cam.shift != (0.0, 0.0)
    finally:
        host.deleteLater()


@needs_qt
def test_home_is_kept_for_each_document_through_the_preview_pane(app):
    from PySide6.QtCore import Signal

    viewer = Viewer(app)
    try:
        w = viewer.window
        pane = w.details.preview
        made: list = []
        stub = _stub_view_factory(made)
        homes: list = []

        def factory():
            base = type(stub())
            made.pop()

            class HomeView(base):
                homeChanged = Signal(object)

                def use_home(self, state):
                    homes.append(state)

            view = HomeView()
            made.append(view)
            return view

        pane.view_factory = factory
        pane.gl_check = lambda: (True, "test")
        viewer.open(FIXTURES)
        w.change_settings(view_3d=True)
        from test_viewer import _show_3d

        _show_3d(viewer, O02)
        assert homes == [None]
        state = {"yaw": 10.0, "pitch": 5.0, "target": [0, 0, 0], "half_height": 0.05, "fitted": False}
        made[-1].homeChanged.emit(state)
        _show_3d(viewer, O16)
        assert homes[-1] is None  # another document: its own Home
        _show_3d(viewer, O02)
        assert homes[-1] == state  # o02 opens at the Home set for it
        made[-1].homeChanged.emit(None)
        _show_3d(viewer, O16)
        _show_3d(viewer, O02)
        assert homes[-1] is None
    finally:
        viewer.close()


@needs_qt
def test_the_view_cube_is_a_setting_in_preferences_and_the_settings_menu(app, tmp_path):
    from solidseas_app.viewer.preferences import VIEW_CUBE_TEXT, PreferencesDialog
    from solidseas_app.viewer.preview import CUBE_TEXT, controls_text
    from solidseas_app.viewer.settings import Settings, SettingsStore
    from solidseas_app.viewer.window import MainWindow

    assert Settings().view_cube
    path = tmp_path / "Viewer.ini"
    store = SettingsStore(str(path))
    assert store.save(Settings(view_cube=False))
    assert "view_cube=false" in path.read_text(encoding="utf-8")
    assert SettingsStore(str(path)).load() == Settings(view_cube=False)
    path.write_text("[Preferences]\nview_cube=sometimes\n", encoding="utf-8")
    reread = SettingsStore(str(path))
    assert reread.load().view_cube and reread.reset_keys == ["view_cube"]

    w = MainWindow(SettingsStore(str(path)))
    dialog = PreferencesDialog(w, w.settings, w.store.path)
    try:
        assert dialog.view_cube.text() == VIEW_CUBE_TEXT and dialog.view_cube.isChecked()
        assert dialog.sizeHint().height() <= 800
        dialog.view_cube.setChecked(False)
        assert dialog.values() == Settings(view_cube=False)
        texts = [a.text() for a in w.settings_menu.actions()]
        assert texts.index("&View Cube in the 3D View") == texts.index("&Boxes for Missing Meshes") + 1
        # Its letter is its own: View &Cube took C from Clear Index, so Alt+S, C did nothing.
        letters = [t[t.index("&") + 1].lower() for t in texts if "&" in t]
        assert letters.count("v") == 1 and "&Clear Index..." in texts
        pane = w.details.preview
        w.act_view_cube.trigger()
        assert not w.settings.view_cube and not pane.show_cube
        assert SettingsStore(str(path)).load().view_cube is False
        w.act_view_cube.trigger()
        assert w.settings.view_cube and pane.show_cube
    finally:
        dialog.deleteLater()
        w.shutdown()
        w.close()
    assert CUBE_TEXT in controls_text("standard") and "Home key" in controls_text("standard", cube=False)
    # A turntable rolls only looking straight down or up, and its caption says so.
    assert "Page Up and Page Down roll it," in controls_text("standard", rotation=FREE)
    assert "roll it looking straight down or up" in controls_text("standard", rotation=TURNTABLE)


# --------------------------------------------------------------------------- OpenGL, on the real display
_GL_CUBE = """
import time
from array import array
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QImage, QMouseEvent
from solidseas_app.viewer import mesh3d, viewcube, viewmath
part = mesh3d.read_part_mesh(sys.argv[1], sys.argv[2], 1000)["data"]
(x0, y0, z0), (x1, y1, z1) = part.bbox
dims = (x1 - x0, y1 - y0, z1 - z0)


LEFT, NONE, NO = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier


def click(widget, x, y):
    for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
        p = QPointF(x, y)
        held = NONE if kind == QEvent.Type.MouseButtonRelease else LEFT
        QApplication.sendEvent(widget, QMouseEvent(kind, p, widget.mapToGlobal(p), LEFT, held, NO))


def extent(img):
    # The drawn model's width and height in device pixels: what differs from the corner's colour.
    img = img.convertToFormat(QImage.Format.Format_RGB32)
    w, h = img.width(), img.height()
    px = array("I")
    px.frombytes(bytes(img.constBits())[: 4 * w * h])
    bg = px[0]
    x0, x1, rows = w, -1, []
    for y in range(h):
        row = px[y * w : (y + 1) * w]
        if row.count(bg) == w:
            continue
        rows.append(y)
        x0 = min(x0, next(x for x in range(w) if row[x] != bg))
        x1 = max(x1, next(x for x in range(w - 1, -1, -1) if row[x] != bg))
    return (x1 - x0 + 1, rows[-1] - rows[0] + 1) if rows else (0, 0)


out = {"gl": True, "regions": [], "scale": None}
for mode in (viewmath.FREE, viewmath.TURNTABLE):
    view = view3d.ModelView(rotation_mode=mode)
    view.resize(560, 420)
    view.show()
    view.set_mesh(part)
    app.processEvents()
    out["scale"] = view.devicePixelRatioF()
    cube = view.cube
    out["side"] = cube.width()
    out["picture"] = [cube.picture().width(), cube.picture().height()]
    out["placed"] = list(cube.geometry().getRect())
    clicked = []
    cube.regionClicked.connect(clicked.append)
    for region in viewmath.REGIONS:
        view.reset_view()
        app.processEvents()
        path = viewcube.path_to(view.camera.axes, region, cube.width())[:-1]
        for step in path:  # the hidden half, through what is drawn
            click(cube, *viewcube.point_of(view.camera.axes, step, cube.width()))
            t = time.perf_counter()
            while view.moving and time.perf_counter() - t < 5:
                app.processEvents()
        p = viewcube.point_of(view.camera.axes, region, cube.width())
        t = time.perf_counter()
        click(cube, *p)
        frames = 0
        while view.moving and time.perf_counter() - t < 5:
            app.processEvents()
            frames += 1
        seconds = time.perf_counter() - t
        app.processEvents()
        eased = view.grabFramebuffer()
        cam = view.camera
        rec = {"mode": mode, "region": list(region), "path": [list(r) for r in path], "fitted": cam.fitted,
               "seconds": seconds, "clicked": list(clicked[-1]) if clicked else None}
        rec["back"] = list(cam.back)
        upp = 2 * cam.half_height / (view.height() * view.devicePixelRatioF())
        rec["want"] = [sum(abs(cam.right[i]) * dims[i] for i in range(3)) / upp,
                       sum(abs(cam.up[i]) * dims[i] for i in range(3)) / upp]
        rec["got"] = list(extent(eased))
        cam.look_from(region)
        view.update()
        app.processEvents()
        rec["same_frame"] = eased == view.grabFramebuffer()
        rec["error"] = view.error
        out["regions"].append(rec)
    view.close()
print(json.dumps(out))
"""


def _check_cube_run(out, scale):
    regions = out["regions"]
    assert len(regions) == 2 * 26
    assert out["side"] == viewcube.cube_side(560, 420)
    assert out["placed"] == list(viewcube.placement(560, 420))
    assert out["picture"] == [round(out["side"] * scale)] * 2
    for r in regions:
        assert r["error"] is None and r["fitted"] and r["same_frame"], r
        assert r["clicked"] == r["region"], r
        assert _close(r["back"], _unit(r["region"]), 1e-9), r
        assert abs(r["got"][0] - r["want"][0]) <= 2 and abs(r["got"][1] - r["want"][1]) <= 2, r
        assert r["seconds"] < 1.5, r


@needs_qt
def test_a_click_on_each_region_lands_on_the_frame_of_that_view_on_the_display():
    """On the real display, for each of the 26 regions in both rotation modes: clicked on
    the cube where it is drawn (the hidden half by way of the top), the view eases there and
    ends on exactly the frame it draws when set there at once, fitted, and o02 (10 x 20 x
    30 mm, every side different) is drawn as large as its box seen from there."""
    out = run_gl(_GL_CUBE, str(fixture_path(O02)), str(FIXTURES), timeout=300)
    _check_cube_run(out, out["scale"])


@needs_qt
@pytest.mark.parametrize("factor", ["1.25", "1.5"])
def test_the_cube_keeps_its_layout_and_clicks_at_other_display_scales(factor):
    """Qt's own scaling, in a child process: the same logical layout, a picture of the side
    times the scale in device pixels, and clicks landing on the same regions."""
    out = run_gl(
        _GL_CUBE, str(fixture_path(O02)), str(FIXTURES), timeout=300, env={"QT_SCALE_FACTOR": factor}
    )
    assert out["scale"] >= float(factor) - 1e-9
    _check_cube_run(out, out["scale"])


# --------------------------------------------------------------------------- the pointer, the wheel, the keys
def test_the_nearest_drawn_pixel_of_a_small_square():
    assert viewmath.nearest_index([None] * 9, 3) is None
    assert viewmath.nearest_index([1, None, None, None, None, None, None, None, 2], 3) == 0
    assert viewmath.nearest_index([None, None, None, None, 0.5, None, None, None, None], 3) == 4
    assert viewmath.nearest_hit([None, 7, None, 3, None, None, None, None, None], 3) == 7


@needs_qt
def test_a_turn_drag_turns_about_the_point_under_the_pointer(app):
    """The point read under the pointer at a turn's first move stays at that pixel while
    the model turns about it, a mark shows it while the drag lasts, and afterwards the
    point the view turns about is back at the depth of the model's centre. A click reads
    nothing; with the setting off, or nothing under the pointer, the model turns about the
    middle of the view as before."""
    from PySide6.QtCore import QEvent

    host, view, _clock = _shown_view(app)
    try:
        cam = view.camera
        point = (0.01, 0.02, 0.03)  # o02's corner nearest the isometric eye
        x, y = ((v + 1) / 2 for v in cam.project(point)[:2])
        px, py = x * view.width(), (1 - y) * view.height()
        reads: list = []

        def surface(sx, sy, radius=None):
            reads.append((sx, sy))
            return point

        view.surface_at = surface
        _click(view, px, py)  # a click is a pick: nothing read
        assert reads == []
        _mouse(view, QEvent.Type.MouseButtonPress, px, py)
        for k in range(1, 6):
            _mouse(view, QEvent.Type.MouseMove, px + 10 * k, py + 5 * k)
            assert view.pivot_mark.isVisible()
            nx, ny, _ = cam.project(point)
            assert ((nx + 1) / 2 * view.width(), (1 - ny) / 2 * view.height()) == pytest.approx(
                (px, py), abs=1e-9
            )
        _mouse(view, QEvent.Type.MouseButtonRelease, px + 50, py + 25)
        assert reads == [(px, py)] and not view.pivot_mark.isVisible()
        assert viewmath._dot(viewmath._sub(cam.target, cam.center), cam.back) == pytest.approx(0, abs=1e-15)
        nx, ny, _ = cam.project(point)
        assert ((nx + 1) / 2 * view.width(), (1 - ny) / 2 * view.height()) == pytest.approx(
            (px, py), abs=1e-9
        )

        for setting, found in ((False, point), (True, None)):
            view.set_about_pointer(setting)
            view.surface_at = lambda sx, sy, radius=None, f=found: reads.append((sx, sy)) or f
            reads.clear()
            target = cam.target
            _mouse(view, QEvent.Type.MouseButtonPress, px, py)
            _mouse(view, QEvent.Type.MouseMove, px + 40, py)
            assert not view.pivot_mark.isVisible()
            _mouse(view, QEvent.Type.MouseButtonRelease, px + 40, py)
            assert cam.target == target  # about the middle of the view
            assert reads == ([] if not setting else [(px, py)])
    finally:
        host.deleteLater()


def _wheel(widget, x, y, across, down, mods=None):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    p = QPointF(x, y)
    event = QWheelEvent(
        p,
        widget.mapToGlobal(p),
        QPoint(),
        QPoint(across, down),
        Qt.MouseButton.NoButton,
        mods or Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(widget, event)
    return event


@needs_qt
def test_a_sideways_scroll_turns_the_model_as_a_scroll_area_moves_its_content(app):
    """A two-finger touchpad swipe across (or a tilted wheel) sends a horizontal scroll, which
    zoomed nothing. It now turns the model about the screen's vertical axis, 15 degrees a
    notch as the Left and Right keys do, its front moving the way a scroll area moves its
    content for the same event; a mostly vertical scroll still zooms."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel, QScrollArea

    area = QScrollArea()
    area.resize(200, 200)
    wide = QLabel("x")
    wide.setFixedSize(2000, 150)
    area.setWidget(wide)
    area.show()
    area.horizontalScrollBar().setValue(900)
    app.processEvents()
    before = wide.x()
    _wheel(area.viewport(), 100, 100, 120, 0)
    app.processEvents()
    content = wide.x() - before  # positive: the content moved right
    area.deleteLater()
    assert content != 0

    host, view, _clock = _shown_view(app)
    try:
        view.set_view("front")
        cam = view.camera
        front = (0.005, 0.01, 0.03)  # the middle of o02's front face
        x0 = cam.project(front)[0]
        _wheel(view, 300, 300, 120, 0)
        moved = cam.project(front)[0] - x0
        assert moved * content > 0  # the model's front went the content's way
        swiped = cam.view_matrix()
        view.set_view("front")
        _key(view, Qt.Key.Key_Right if content > 0 else Qt.Key.Key_Left)
        assert cam.view_matrix() == swiped  # one notch is one arrow key
        view.set_view("front")
        for _ in range(4):
            _wheel(view, 300, 300, 30, 0)  # a touchpad's small steps: a quarter notch each
        assert cam.view_matrix() == pytest.approx(swiped, abs=1e-12)
        view.set_view("front")
        half = cam.half_height
        _wheel(view, 300, 300, 120, 20)  # mostly across: it only turns
        assert cam.half_height == half and cam.yaw != 0
        _wheel(view, 300, 300, 20, 120)  # mostly down: it only zooms
        assert cam.half_height != half
    finally:
        host.deleteLater()


@needs_qt
def test_ctrl_or_shift_pressed_during_a_middle_drag_switches_it(app):
    """SOLIDWORKS style: a middle-drag rotates, and pressing Ctrl once it has started makes it
    pan from there, the model following the pointer exactly; letting go turns it again, and
    Shift zooms. The same holds when the modifiers come with the moves alone."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication

    host, view, _clock = _shown_view(app)
    try:
        view.mouse_style = viewmath.SOLIDWORKS
        cam = view.camera
        middle = Qt.MouseButton.MiddleButton
        ctrl, shift = Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.ShiftModifier

        def key(kind, k, mods):
            QApplication.sendEvent(view, QKeyEvent(kind, k, mods))

        def pixel(p):
            nx, ny, _ = cam.project(p)
            return ((nx + 1) / 2 * view.width(), (1 - ny) / 2 * view.height())

        x, y = 300.0, 250.0
        _mouse(view, QEvent.Type.MouseButtonPress, x, y, middle)
        axes = cam.axes
        _mouse(view, QEvent.Type.MouseMove, x + 20, y, middle)
        assert cam.axes != axes and view._drag == viewmath.ROTATE
        key(QEvent.Type.KeyPress, Qt.Key.Key_Control, ctrl)
        assert view._drag == viewmath.PAN
        axes, before = cam.axes, pixel(cam.center)
        _mouse(view, QEvent.Type.MouseMove, x + 60, y + 30, middle, ctrl)
        after = pixel(cam.center)
        assert cam.axes == axes and (after[0] - before[0], after[1] - before[1]) == pytest.approx(
            (40, 30), abs=1e-9
        )
        key(QEvent.Type.KeyRelease, Qt.Key.Key_Control, ctrl)
        assert view._drag == viewmath.ROTATE
        _mouse(view, QEvent.Type.MouseMove, x + 80, y + 30, middle)
        assert cam.axes != axes
        key(QEvent.Type.KeyPress, Qt.Key.Key_Shift, shift)
        assert view._drag == viewmath.ZOOM
        half = cam.half_height
        _mouse(view, QEvent.Type.MouseMove, x + 80, y, middle, shift)  # up: in
        assert cam.half_height < half
        _mouse(view, QEvent.Type.MouseMove, x + 80, y + 10, middle)  # Shift let go, seen on a move
        assert view._drag == viewmath.ROTATE
        _mouse(view, QEvent.Type.MouseMove, x + 80, y + 20, middle, ctrl)  # Ctrl seen on a move
        assert view._drag == viewmath.PAN
        _mouse(view, QEvent.Type.MouseButtonRelease, x + 80, y + 20, middle)
        assert view._drag is None
        # The Standard style goes by the buttons alone.
        view.mouse_style = viewmath.STANDARD
        _mouse(view, QEvent.Type.MouseButtonPress, x, y)
        key(QEvent.Type.KeyPress, Qt.Key.Key_Control, ctrl)
        assert view._drag == viewmath.ROTATE
        _mouse(view, QEvent.Type.MouseButtonRelease, x, y)
    finally:
        host.deleteLater()


@needs_qt
def test_page_up_and_page_down_roll_the_model(app):
    from PySide6.QtCore import Qt

    host, view, _clock = _shown_view(app)
    try:
        cam = view.camera
        view.set_view("front")
        _key(view, Qt.Key.Key_PageDown)  # clockwise on the screen: the model's top tilts right
        a = math.radians(15)
        assert _close(cam.up, (-math.sin(a), math.cos(a), 0)) and _close(cam.back, (0, 0, 1))
        assert viewmath._dot((0, 1, 0), cam.right) > 0  # the model's +Y points up and to the right
        _key(view, Qt.Key.Key_PageUp)
        assert _close(cam.up, (0, 1, 0))
        _key(view, Qt.Key.Key_PageDown, Qt.KeyboardModifier.ShiftModifier)
        assert _close(cam.up, (-1, 0, 0)) and _close(cam.right, (0, 1, 0))
        view.set_rotation_mode(TURNTABLE)
        view.set_view("front")
        before = cam.state()
        _key(view, Qt.Key.Key_PageUp)
        assert cam.state() == before  # a turntable cannot roll a side view
        view.set_view("top")
        _key(view, Qt.Key.Key_PageUp, Qt.KeyboardModifier.ShiftModifier)
        assert cam.pitch == 90 and cam.yaw == pytest.approx(270)
    finally:
        host.deleteLater()


@needs_qt
def test_turning_about_the_pointer_is_a_setting(app, tmp_path):
    from solidseas_app.viewer.preferences import POINTER_TEXT, PreferencesDialog
    from solidseas_app.viewer.settings import Settings, SettingsStore
    from solidseas_app.viewer.window import MainWindow

    assert Settings().turn_about_pointer
    path = tmp_path / "Viewer.ini"
    assert SettingsStore(str(path)).save(Settings(turn_about_pointer=False))
    assert "turn_about_pointer=false" in path.read_text(encoding="utf-8")
    assert SettingsStore(str(path)).load() == Settings(turn_about_pointer=False)
    w = MainWindow(SettingsStore(str(path)))
    dialog = PreferencesDialog(w, w.settings, w.store.path)
    try:
        assert dialog.turn_about_pointer.text() == POINTER_TEXT and not dialog.turn_about_pointer.isChecked()
        assert dialog.sizeHint().height() <= 800
        menus = {a.text(): a.menu() for a in w.settings_menu.actions() if a.menu() is not None}
        rotation = [a.text() for a in menus["Rotation in the 3D View"].actions()]
        assert rotation[2:] == ["", "Turn About the Point &Under the Pointer"]
        pane = w.details.preview
        assert not pane.about_pointer
        w.act_pointer.trigger()
        assert w.settings.turn_about_pointer and pane.about_pointer
        assert SettingsStore(str(path)).load().turn_about_pointer
    finally:
        dialog.deleteLater()
        w.shutdown()
        w.close()


_GL_DEPTH = """
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from solidseas_app.viewer import mesh3d, viewmath
part_path, asm_path, boxed_path, folder, boxed_folder = sys.argv[1:6]
part = mesh3d.read_part_mesh(part_path, folder, 1000)["data"]
asm = mesh3d.read_assembly_scene(asm_path, folder, folder, 1_000_000)["data"]
boxed = mesh3d.read_assembly_scene(boxed_path, boxed_folder, boxed_folder, 1_000_000)["data"]
LEFT, NONE, NO = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier


def mouse(view, kind, x, y):
    p = QPointF(x, y)
    pressed = NONE if kind == QEvent.Type.MouseMove else LEFT
    held = NONE if kind == QEvent.Type.MouseButtonRelease else LEFT
    QApplication.sendEvent(view, QMouseEvent(kind, p, view.mapToGlobal(p), pressed, held, NO))


def boxes_of(view):
    # Each instance's box as exploded now, numbered over the scene.
    from array import array
    out = []
    scene = view.scene
    for m, raw in enumerate(scene.bounds or []):
        b = array("f")
        b.frombytes(raw)
        for k in range(len(b) // 6):
            d = view.explosion.offset(m, k) if view.explosion is not None and view.explode else (0, 0, 0)
            out.append(([b[6 * k + i] + view.explode * d[i] for i in range(3)],
                        [b[6 * k + 3 + i] + view.explode * d[i] for i in range(3)]))
    return out


cases = []
for instanced in (True, False):
    view3d.Renderer.allow_instancing = instanced
    for name in ("part", "assembly", "exploded", "transparent", "boxes"):
        view = view3d.ModelView()
        view.resize(480, 360)
        view.show()
        if name == "part":
            view.set_mesh(part)
        else:
            view.set_assembly(boxed if name == "boxes" else asm)
        app.processEvents()
        if name == "exploded":
            view.explode_to(1.0, animate=False)
        n = view.scene.n_instances
        if name == "transparent":
            view.set_looks([0.25 if g % 2 else 1.0 for g in range(n)], None)
        app.processEvents()
        boxes = boxes_of(view) if name != "part" else [view.scene.bbox]
        for g in range(n):
            p = view.pixel_of(g) if name != "part" else (view.width() / 2 + 0.5, view.height() / 2 + 0.5)
            if p is None:
                continue
            point = view.surface_at(*p)
            # The instance the same small pass finds there: at an edge of g's pixels the small
            # square may rasterise a neighbour where the whole view drew g.
            at = view.instance_at(*p) if name != "part" else 0
            rec = {"case": f"{name} {instanced}", "instance": g, "at": at, "pixel": list(p), "point": point}
            if point is not None and at is not None:
                lo, hi = boxes[at]
                # Within a pixel of it: a box's edge is a line, whose depth is the line's where
                # the pixel's middle falls beside it.
                pad = view.camera.units_per_pixel(view.height())
                rec["inside"] = all(lo[i] - pad <= point[i] <= hi[i] + pad for i in range(3))
                gap = min(min(abs(point[i] - lo[i]), abs(point[i] - hi[i])) for i in range(3))
                rec["face"] = gap / view.camera.radius
                # Turned about it with a drag from there: it keeps its pixel.
                x, y = p
                mouse(view, QEvent.Type.MouseButtonPress, x, y)
                for k in range(1, 6):
                    mouse(view, QEvent.Type.MouseMove, x + 10 * k, y + 5 * k)
                mark = view.pivot_mark.isVisible()
                mouse(view, QEvent.Type.MouseButtonRelease, x + 50, y + 25)
                nx, ny, _ = view.camera.project(point)
                rec["kept"] = [(nx + 1) / 2 * view.width() - x, (1 - ny) / 2 * view.height() - y]
                rec["mark"] = mark
                view.reset_view()
                app.processEvents()
            cases.append(rec)
        nothing = view.surface_at(2, 2)
        cases.append({"case": f"{name} {instanced} error", "error": view.error, "nothing": nothing})
        view.close()
print(json.dumps({"gl": True, "cases": cases}))
"""


@needs_qt
def test_the_depth_pass_finds_the_surface_under_the_pointer_on_the_display(tmp_path):
    """On the real display, instanced and one instance at a time: at a pixel of each
    instance, of a part, an assembly, an exploded one, one with every other instance
    transparent and one drawn partly as boxes, the depth variant of the id pass gives a
    point within a pixel of that instance's box (on its surface, for the part, a box), with
    nothing found on empty space; a turn dragged from there keeps that point at its pixel,
    marked while it turns."""
    from test_viewer_boxes import crafted

    boxed = crafted(tmp_path)
    out = run_gl(
        _GL_DEPTH,
        str(fixture_path(O02)),
        str(fixture_path(O16)),
        str(boxed / O16),
        str(FIXTURES),
        str(boxed),
        timeout=300,
    )
    found = [c for c in out["cases"] if "instance" in c]
    assert len({c["case"] for c in found}) == 10
    for c in out["cases"]:
        if "error" in c:
            assert c["error"] is None and c["nothing"] is None, c
            continue
        assert c["point"] is not None and c["inside"], c
        assert abs(c["kept"][0]) < 1e-6 and abs(c["kept"][1]) < 1e-6 and c["mark"], c
        if c["case"].startswith("part"):
            assert c["face"] < 1e-5, c  # on the box's surface: 24 bits of depth


# --------------------------------------------------------------------------- configurations and the legend
def test_the_free_areas_are_left_of_and_below_the_legends_column():
    """The legend over the right of a 900 x 600 view, under the cube: the model may go left
    of their column, full height, or below it, full width, 8 pixels clear of it; an area
    under 35 percent of the view is dropped, and with nothing reserved the whole view is
    the model's."""
    legend = (900 - 8 - 300, 8 + 128 + 6, 300, 150)  # x, y, width, height
    cube = (900 - 8 - 128, 8, 128, 128)
    areas = viewmath.free_areas(900, 600, [legend], [cube])
    left = 900 - 8 - 300 - 8
    top = 8 + 128 + 6 + 150 + 8
    assert areas == [
        pytest.approx((-1.0, -1.0, 2 * left / 900 - 1, 1.0)),
        pytest.approx((-1.0, -1.0, 1.0, 1 - 2 * top / 600)),
    ]
    wide = (900 - 8 - 120, 8, 120, 500)  # a tall legend: nothing below it
    assert viewmath.free_areas(900, 600, [wide]) == [
        pytest.approx((-1.0, -1.0, 2 * (900 - 136) / 900 - 1, 1.0))
    ]
    huge = (100, 8, 792, 500)  # wider than 65 percent of the view: no room left of it either
    assert viewmath.free_areas(900, 600, [huge]) == []
    assert viewmath.free_areas(900, 600, []) == []
    # The cube further left than the legend moves the column's edge.
    narrow = (900 - 8 - 90, 142, 90, 100)
    assert viewmath.free_areas(900, 600, [narrow], [cube])[0][2] == pytest.approx(
        2 * (900 - 8 - 128 - 8) / 900 - 1
    )


def _o16(configuration=None):
    kw = {"configuration": configuration} if configuration else {}
    return mesh3d.read_assembly_scene(str(fixture_path(O16)), str(FIXTURES), str(FIXTURES), 1_000_000, **kw)[
        "data"
    ]


@needs_qt
def test_another_configuration_keeps_the_camera(app):
    """A configuration change used to reset the view to the isometric fit. Now a camera the
    user moved keeps its direction, target, zoom and shift; a fitted one fits the new
    configuration from the same direction; and one whose new model would lie wholly out
    of view fits it from the same direction. A new document still opens at Home."""
    from solidseas_app.viewer.selftest import same_camera

    host, view, clock = _shown_view(app)
    try:
        default, lite = _o16(), _o16("Lite")
        view.set_assembly(default)
        view.camera.rotate(30, 20)
        view.camera.zoom(1.5, (0.3, 0.1))
        moved = view.camera_state()
        view.set_assembly(lite, keep_camera=True)
        assert same_camera(view.camera_state(), moved)
        view.set_view("back")
        view.set_assembly(default, keep_camera=True)
        assert view.camera.fitted and view.camera.axes == viewmath.turntable_axes(*viewmath.VIEWS["back"])
        assert view.camera.bbox == viewmath.OrbitCamera(default.bbox).bbox
        # Panned far off: the new model would be out of view, so it is fitted from there.
        view.camera.pan(5000, 0, view.height())
        back = view.camera.back
        view.set_assembly(lite, keep_camera=True)
        assert view.camera.fitted and _close(view.camera.back, back)
        # Mid-move, the move's end is what stays.
        view.look_at_region((0, 1, 1))
        clock.t += 0.05
        view._tick()
        view.set_assembly(default, keep_camera=True)
        assert not view.moving and view.camera.fitted and _close(view.camera.back, _unit((0, 1, 1)))
        view.set_assembly(lite)  # another document: Home
        assert view.camera.axes == viewmath.turntable_axes(*viewmath.VIEWS["isometric"])
    finally:
        host.deleteLater()


@needs_qt
def test_the_self_test_fails_a_refit_that_kept_the_model_in_view(app, monkeypatch):
    """The --configuration check passed any fitted camera looking the same way as a refit. A
    refit counts only where the camera as it was had lost the new model; one that still
    showed it fails the run."""
    from solidseas_app.viewer import selftest

    class Run:
        def _settle(self):
            pass

    monkeypatch.setattr(selftest, "covered", lambda _view: 0.5)
    host, view, _clock = _shown_view(app)
    try:
        default, lite = _o16(), _o16("Lite")

        def check(before, change):
            view.set_assembly(default)
            view.camera.rotate(30, 20)
            before()
            doc = {"_camera_before": (False, view.camera_state(), view.camera.free), "errors": []}
            change()
            info: dict = {}
            selftest.SelfTest._camera_after(Run(), doc, view, info)
            return info["camera"], [e["message"] for e in doc["errors"]]

        def lite_kept():
            view.set_assembly(lite, keep_camera=True)

        def lite_refit_anyway():
            view.set_assembly(lite, keep_camera=True)
            view.fit()  # as a keep_in_view that refit too eagerly would

        assert check(lambda: view.camera.zoom(1.5), lite_kept) == ("kept", [])
        assert check(lambda: view.camera.pan(5000, 0, view.height()), lite_kept) == ("refit", [])
        camera, errors = check(lambda: view.camera.zoom(1.5), lite_refit_anyway)
        assert camera == "refit with the model in view" and errors == [
            "the camera was fitted again though it still showed the model"
        ]
    finally:
        host.deleteLater()


@needs_qt
def test_the_pane_keeps_the_camera_for_the_same_document_only(app):
    viewer = Viewer(app)
    try:
        w = viewer.window
        pane = w.details.preview
        made: list = []
        pane.view_factory = _stub_view_factory(made)
        pane.gl_check = lambda: (True, "test")
        viewer.open(FIXTURES)
        w.change_settings(view_3d=True)
        from test_viewer import _show_3d, _wait

        _show_3d(viewer, O16)
        view = made[-1]
        assert view.keep_calls == [False]
        looked = {
            "yaw": 70.0,
            "pitch": 15.0,
            "target": [0.01, 0.0, 0.0],
            "half_height": 0.04,
            "fitted": False,
        }
        view.cam = dict(looked)
        pane.choose_configuration("Lite")
        _wait(viewer.app, lambda: pane.mesh_state not in ("starting", "loading") and not w.busy)
        assert view.keep_calls[-1] is True and view.cam == looked and not view.camera_calls
        _show_3d(viewer, O02)
        assert view.keep_calls[-1] is False  # a part of its own
        _show_3d(viewer, O16)
        assert view.keep_calls[-1] is False  # the assembly again: a new document, at Home
    finally:
        viewer.close()


@needs_qt
def test_the_fit_leaves_the_legends_column_free(app):
    """With the legend shown, a fitted model lies left of the column the legend and the
    cube take (or below it); hidden, the whole view is the model's again; a camera the
    user moved does not move."""
    from solidseas_app.viewer import preview

    host, view, _clock = _shown_view(app, size=(900, 600))
    try:
        view.set_assembly(_o16())
        files = [{"name": f"part{k}", "color": "#336699", "instances": 1, "key": f"k{k}"} for k in range(6)]
        legend = preview.Legend(view)
        legend.set_files(files)
        legend.show()
        app.processEvents()
        cam = view.camera
        assert cam.fitted and cam.free != (viewmath.WHOLE_VIEW,)
        column = min(legend.x(), view.cube.x())
        xs = []
        for k in viewmath.corners(cam.bbox):
            nx, ny, _ = cam.project(k)
            xs.append((nx + 1) / 2 * view.width())
            assert -1 <= ny <= 1
        assert max(xs) <= column - 8 + 1e-6 and cam.shift[0] < 0
        # The overlays take clicks where they are; the model's pixels there are not clickable.
        assert view.overlay_at(legend.x() + 5, legend.y() + 5) is legend
        p = viewcube.point_of(cam.axes, (0, 0, 1), view.cube.width())
        assert view.overlay_at(view.cube.x() + p[0], view.cube.y() + p[1]) is view.cube
        assert (
            view.overlay_at(view.cube.x() + view.cube.width() - 2, view.cube.y() + view.cube.width() - 2)
            is None
        )
        assert view.overlay_at(20, 300) is None
        legend.hide()
        app.processEvents()
        assert cam.free == (viewmath.WHOLE_VIEW,) and cam.shift == (0.0, 0.0) and cam.fitted
        cam.zoom(1.3)
        state = cam.state()
        legend.show()
        app.processEvents()
        assert cam.state() == state  # moved: it stays until the next fit
        view.fit()
        assert cam.shift[0] < 0
    finally:
        host.deleteLater()


_GL_LEGEND = """
from PySide6.QtGui import QImage
from solidseas_app.viewer import mesh3d, preview
asm = mesh3d.read_assembly_scene(sys.argv[1], sys.argv[2], sys.argv[2], 1_000_000)["data"]
out = {"gl": True, "views": []}
for w, h in ((900, 600), (600, 700), (1200, 500)):
    view = view3d.ModelView()
    view.resize(w, h)
    view.show()
    view.set_assembly(asm)
    legend = preview.Legend(view)
    legend.set_files(asm.files)
    legend.show()
    for name in ("isometric", "front", "top", "right"):
        view.set_view(name)
        app.processEvents()
        img = view.grabFramebuffer().convertToFormat(QImage.Format.Format_RGB32)
        scale = img.width() / view.width()
        bg = img.pixel(0, 0)
        x0 = int(min(legend.x(), view.cube.x()) * scale)
        y1 = int(legend.geometry().bottom() * scale)
        W, H = img.width(), img.height()
        inside = sum(img.pixel(x, y) != bg for y in range(0, y1, 2) for x in range(x0, W, 2))
        drawn = sum(img.pixel(x, y) != bg for y in range(0, H, 4) for x in range(0, W, 4))
        out["views"].append({"size": [w, h], "view": name, "in_column": inside, "drawn": drawn,
                             "shift": list(view.camera.shift), "error": view.error})
    view.close()
print(json.dumps(out))
"""


@needs_qt
def test_the_fit_leaves_the_legend_column_empty_on_the_display():
    out = run_gl(_GL_LEGEND, str(fixture_path(O16)), str(FIXTURES))
    assert len(out["views"]) == 12
    for v in out["views"]:
        assert v["error"] is None and v["drawn"] > 0 and v["in_column"] == 0, v
        assert v["shift"] != [0.0, 0.0], v


# --------------------------------------------------------------------------- the self-test's options
@needs_qt
def test_the_self_test_navigation_options_are_checked_and_kept_in_its_own_settings(
    app, tmp_path, monkeypatch
):
    import json
    import sys

    from solidseas_app.viewer import app as viewer_app
    from solidseas_app.viewer.settings import SettingsStore

    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)  # main() installs its own
    report = tmp_path / "out" / "report.json"
    args = ["--self-test", str(FIXTURES), "--report", str(report), "--select", O02]
    for bad in (
        ["--viewcube", "front"],  # without --self-test
        [*args, "--viewcube", "front"],  # without --3d
        [*args, "--3d", "--viewcube", "front-back"],
        [*args, "--3d", "--viewcube", "sideways"],
        [*args, "--pivot", "."],
        [*args, "--input-checks"],
        [*args, "--view-cube", "maybe"],
        [*args, "--pivot-at", "edge"],
        ["--self-test", str(FIXTURES), "--report", str(report), "--select-all", "--3d", "--pivot", "."],
    ):
        assert viewer_app.main(bad) == viewer_app.EXIT_USAGE, bad
    assert viewer_app._viewcube_spec("Top-Front") == "top-front"
    assert viewer_app._configuration_spec("Lite,fitted") == ("Lite", True)
    assert viewer_app._configuration_spec("Lite") == ("Lite", False)
    assert viewer_app.main([*args, "--view-cube", "off", "--pivot-at", "centre"]) == 0
    out = json.loads(report.read_text(encoding="utf-8"))
    assert out["ok"] and out["view_cube"] is False and out["pivot_at"] == "centre"
    stored = SettingsStore(out["settings"]).load()
    assert stored.view_cube is False and stored.turn_about_pointer is False
    assert viewer_app.main([*args, "--force"]) == 0
    out = json.loads(report.read_text(encoding="utf-8"))
    assert out["view_cube"] is True and out["pivot_at"] == "pointer"
    assert not (tmp_path / "Roaming").exists()


def _fixture_copy(tmp_path):
    import shutil

    folder = tmp_path / "fx"
    shutil.copytree(FIXTURES, folder)
    return folder


O16_PART = "o09_import_step-1"


@needs_qt
@pytest.mark.parametrize("mode", [FREE, TURNTABLE])
def test_the_self_test_clicks_the_cube_turns_about_the_pointer_and_checks_the_input(tmp_path, mode):
    """On the real display, on a copy of the fixtures: the self-test clicks each of the 26
    regions of o02's cube (the hidden half through what is drawn), Home, Set Current View as
    Home and Reset Home, the arrows and a drag, turns o02 about the point under the pointer
    and about the middle over empty space, checks the sideways scroll, the middle-drag's
    modifiers and the roll keys; then on o16 a corner, a turn about one of its parts and two
    configurations, after a turned view and after a fitted one. Every check passes, in both
    rotation modes, and the legend's column stays clear of the model."""
    from gl_support import run_self_test
    from test_viewer import _state

    folder = _fixture_copy(tmp_path)
    before = _state(folder)
    shots = tmp_path / "shots"
    args = ["--self-test", str(folder), "--screenshot-dir", str(shots), "--3d", "--rotation", mode]
    args += ["--select", O02, "--viewcube", "all"]
    for what in ("home", "set-home", "home", "reset-home", "home", "roll-cw", "roll-ccw"):
        args += ["--viewcube", what]
    for what in ("step-up", "step-down", "step-left", "step-right", "drag"):
        args += ["--viewcube", what]
    args += ["--pivot", "part", "--pivot", ".", "--input-checks"]
    args += ["--select", O16, "--viewcube", "back-top-left", "--pivot", O16_PART]
    args += ["--configuration", "Lite", "--configuration", "Default,fitted"]
    report = run_self_test(args, shots, appdata=tmp_path / "Roaming", timeout=600)
    o02, o16 = report["documents"]
    cubes = o02["viewcube"]
    assert len(cubes) == 26 + 12
    regions = cubes[:26]
    assert {r["viewcube"] for r in regions} == {viewmath.region_name(r) for r in viewmath.REGIONS}
    for r in cubes:
        assert "failed" not in r, r
    assert all("silhouette" in r for r in regions)
    assert any(len(r["path"]) > 1 for r in regions)  # the hidden half, reached through what is drawn
    assert [r["home"] for r in cubes if r["viewcube"] == "home"] == ["isometric", "set", "isometric"]
    part, empty = o02["pivot"]
    assert "failed" not in part and "failed" not in empty, (part, empty)
    assert max(abs(v) for v in part["kept"]) <= 0.5 and part["mark"]
    assert o02["input_checks"].get("failed") is None, o02["input_checks"]
    assert o02["input_checks"]["ctrl_pans"] == pytest.approx([40, 30], abs=0.5)
    (corner,) = o16["viewcube"]
    assert "failed" not in corner and corner["path"][-1] == "back-top-left"
    (pivot,) = o16["pivot"]
    assert "failed" not in pivot and max(abs(v) for v in pivot["kept"]) <= 0.5, pivot
    assert o16["mesh"]["legend_clear"] is True and o16["mesh"]["cube"]["shown"]
    lite, fitted = o16["mesh_configurations"]
    assert lite["camera"] in ("kept", "refit") and fitted["camera"] == "kept, fitted"
    assert lite["covered"] > 0 and fitted["covered"] > 0
    for doc in (o02, o16):
        assert doc["errors"] == [], doc["errors"]
    assert _state(folder) == before
    assert not (tmp_path / "Roaming").exists()


@needs_qt
def test_the_self_test_turns_about_the_middle_with_the_setting_off(tmp_path):
    """With --pivot-at centre the model turns about the middle of the view: the part's pixel
    moves, which the report records without failing; with --view-cube off no cube is shown.
    --input-checks runs on every selected document: on o12, two bodies fitted across the
    view, the pan it measures by the drawn pixels used to push the model past the frame's
    edge and come out short (38.7 pixels for 40); zoomed out a step first, it keeps it all
    in the frame."""
    from gl_support import run_self_test

    folder = _fixture_copy(tmp_path)
    shots = tmp_path / "shots"
    args = ["--self-test", str(folder), "--screenshot-dir", str(shots), "--3d", "--select", O02]
    args += ["--pivot", "part", "--view-cube", "off", "--pivot-at", "centre"]
    args += ["--select", "o12_multibody.SLDPRT", "--input-checks"]
    report = run_self_test(args, shots, appdata=tmp_path / "Roaming")
    doc, wide = report["documents"]
    (rec,) = doc["pivot"]
    assert rec["setting"] == "centre" and rec["about"] is None and "failed" not in rec and rec["moved"]
    assert doc["mesh"]["cube"]["shown"] is False and report["view_cube"] is False
    for checked in (doc, wide):
        assert checked["input_checks"]["pan_within_frame"], checked["input_checks"]
        assert checked["input_checks"]["ctrl_pans"] == pytest.approx([40, 30], abs=0.5)
        assert checked["errors"] == [], checked["errors"]
