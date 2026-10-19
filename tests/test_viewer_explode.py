"""The exploded view of an assembly in the SolidSeas Viewer's 3D view.

SOLIDWORKS keeps an assembly's own exploded views in its binary configuration
data, which SolidSeas does not decode (``docs/FORMAT.md`` 12.6), so the viewer
explodes an assembly itself, for display only. These tests check the arithmetic
(each instance's box against the one SOLIDWORKS gave for it, each group moved
along the line from the assembly's centre, groups at the centre stacked along
the longest axis, a box that holds every instance at any amount, the easing),
the Explode bar on the Preview tab with a stand-in for the OpenGL view, the
real view on the display (stepped on a clock of the test's own), and the
self-test's ``--explode``.

Every test that reads files checks that none of them changed.
"""

import json
import math
import os
import random
import shutil
from array import array
from pathlib import Path

import pytest

from gl_support import run_gl, run_self_test
from solidseas import geometry as geo
from solidseas import open_document
from solidseas_app.viewer import explode, mesh3d
from support import FIXTURES, fixture_path
from test_viewer import Viewer, _state, _stub_view_factory, _wait, needs_qt

O08, O15, O16 = "o08_asm_2x_boxA.SLDASM", "o15_sub_asm.SLDASM", "o16_asm_features.SLDASM"
CASES = [(O08, "Default"), (O15, "Default"), (O16, "Default"), (O16, "Lite")]
GT = json.loads((FIXTURES / "ground_truth.json").read_text(encoding="utf-8"))
TOL = 1e-6  # metres: the meshes are float32, SOLIDWORKS' boxes float64


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


def _scene(name: str = O16, configuration: str | None = None) -> mesh3d.SceneBuffers:
    path = str(fixture_path(name))
    folder = str(FIXTURES)
    return mesh3d.read_assembly_scene(path, folder, folder, 1_000_000, configuration=configuration)["data"]


def _boxes(scene) -> dict[str, tuple]:
    out = {}
    for ids, raw in zip(scene.instance_ids, scene.bounds, strict=True):
        b = array("f")
        b.frombytes(raw)
        for k, iid in enumerate(ids):
            out[iid] = (tuple(b[6 * k : 6 * k + 3]), tuple(b[6 * k + 3 : 6 * k + 6]))
    return out


def _flat(box) -> list[float]:
    """A box, or a list of them, as one flat list, for ``pytest.approx``."""
    if isinstance(box[0], (int, float)):
        return list(box)
    return [v for part in box for v in _flat(part)]


def _centre(box):
    return tuple((box[0][i] + box[1][i]) / 2 for i in range(3))


def _union(boxes):
    boxes = list(boxes)
    return (
        tuple(min(b[0][i] for b in boxes) for i in range(3)),
        tuple(max(b[1][i] for b in boxes) for i in range(3)),
    )


def _moved(box, d):
    return (tuple(box[0][i] + d[i] for i in range(3)), tuple(box[1][i] + d[i] for i in range(3)))


def _offsets(e: explode.Explosion, scene) -> dict[str, tuple]:
    return {iid: e.offset(m, k) for m, ids in enumerate(scene.instance_ids) for k, iid in enumerate(ids)}


# --------------------------------------------------------------------------- the arithmetic, no Qt
@pytest.mark.parametrize(("name", "configuration"), CASES)
def test_each_instance_box_is_the_one_solidworks_gave_it(name, configuration):
    """The boxes the explode moves, from each mesh's box and the instance's placement: equal
    to ``Component2.GetBox`` for parts turned by right angles, and holding it for the parts
    of the sub-assembly turned 40 degrees about (1, 1, 1), whose corner box is looser."""
    before = _state(FIXTURES)
    scene = _scene(name, configuration)
    boxes = _boxes(scene)
    comps = {c["name"]: c for c in GT[name]["api"]["configurations"][configuration]["components"]}
    assert set(boxes) <= set(comps) and len(boxes) == scene.n_instances
    for iid, box in boxes.items():
        want = comps[iid]["box_m"]
        got = [*box[0], *box[1]]
        if iid.startswith("o15_sub_asm-1/"):
            assert all(got[i] <= want[i] + TOL for i in range(3)) and all(
                got[i] >= want[i] - TOL for i in range(3, 6)
            ), iid
        else:
            assert got == pytest.approx(want, abs=TOL), iid
    # The same boxes as the library's own, from the mesh box's corners.
    with open_document(fixture_path(name)) as doc:
        g = geo.display_geometry(doc, configuration)
    for inst in g.instances:
        lo, hi = g.bounds(inst)
        assert [*boxes[inst.id][0], *boxes[inst.id][1]] == pytest.approx([*lo, *hi], abs=TOL)
    assert _state(FIXTURES) == before


def test_each_top_level_component_moves_away_from_the_centre():
    scene = _scene()
    boxes = _boxes(scene)
    e = explode.explode(scene.instance_ids, scene.bounds, explode.TOP)
    tops = {iid.partition("/")[0] for iid in boxes}
    assert e.groups == len(tops) == 11 and e.moving == 11 and e.central == 0
    whole = _union(boxes.values())
    assert _flat(e.bbox0) == pytest.approx(_flat(whole))
    c = _centre(whole)
    off = _offsets(e, scene)
    for top in tops:
        members = [iid for iid in boxes if iid.partition("/")[0] == top]
        p = _centre(_union(boxes[i] for i in members))
        want = tuple(explode.SPREAD * (p[i] - c[i]) for i in range(3))
        for iid in members:  # a sub-assembly moves as one
            assert off[iid] == pytest.approx(want, abs=1e-6), iid
    inner = ["o15_sub_asm-1/o02_boxA-1", "o15_sub_asm-1/o07_boxB_h31-1"]
    assert off[inner[0]] == off[inner[1]]
    # Fully exploded, every group's centre is twice as far from the assembly's centre.
    p = _centre(boxes["o02_boxA-2"])
    q = _centre(_moved(boxes["o02_boxA-2"], off["o02_boxA-2"]))
    assert math.dist(q, c) == pytest.approx(2 * math.dist(p, c), rel=1e-5)
    assert _flat(e.bbox1) == pytest.approx(_flat(_union(_moved(b, off[i]) for i, b in boxes.items())))

    parts = explode.explode(scene.instance_ids, scene.bounds, explode.PARTS)
    assert parts.groups == parts.moving == 12
    poff = _offsets(parts, scene)
    assert poff[inner[0]] != poff[inner[1]]  # each part on its own
    assert poff["o02_boxA-2"] == pytest.approx(off["o02_boxA-2"], abs=1e-9)  # a part at the top: the same


def test_components_at_the_centre_are_stacked_along_the_longest_axis():
    """Three boxes sharing the assembly's centre: the largest stays, the others go to
    either side along the longest axis (here X), clear of it and of each other."""

    def box(c, h):
        return [c[0] - h[0], c[1] - h[1], c[2] - h[2], c[0] + h[0], c[1] + h[1], c[2] + h[2]]

    centre = (0.0, 0.0, 0.0)
    rows = [
        box(centre, (0.05, 0.01, 0.01)),  # the shaft: the largest
        box(centre, (0.01, 0.02, 0.02)),  # a wheel on it
        box(centre, (0.005, 0.015, 0.015)),  # a bearing
        box((0.2, 0.0, 0.0), (0.01, 0.01, 0.01)),
        box((-0.2, 0.0, 0.0), (0.01, 0.01, 0.01)),
    ]
    ids = [["shaft-1", "wheel-1", "bearing-1", "right-1", "left-1"]]
    bounds = [array("f", [v for r in rows for v in r]).tobytes()]
    e = explode.explode(ids, bounds, explode.TOP)
    assert (e.groups, e.central, e.moving, e.axis) == (5, 3, 4, 0)
    shaft, wheel, bearing = e.offset(0, 0), e.offset(0, 1), e.offset(0, 2)
    assert shaft == (0.0, 0.0, 0.0)
    assert wheel[0] > 0 and bearing[0] < 0 and wheel[1:] == bearing[1:] == (0.0, 0.0)
    gap = explode.GAP * math.dist(e.bbox0[0], e.bbox0[1])
    assert wheel[0] - 0.01 == pytest.approx(0.05 + gap, rel=1e-5)  # its near side just clear of the shaft
    assert -bearing[0] - 0.005 == pytest.approx(0.05 + gap, rel=1e-5)
    assert e.offset(0, 3) == pytest.approx((0.2 * explode.SPREAD, 0, 0)) and e.offset(0, 4)[0] < 0


def test_a_single_group_never_moves():
    one = [array("f", [0, 0, 0, 0.01, 0.01, 0.01, 0.02, 0, 0, 0.03, 0.01, 0.01]).tobytes()]
    ids = [["sub-1/a-1", "sub-1/b-1"]]
    top = explode.explode(ids, one, explode.TOP)
    assert (top.groups, top.moving) == (1, 0) and top.bbox1 == top.bbox0
    parts = explode.explode(ids, one, explode.PARTS)
    assert (parts.groups, parts.moving) == (2, 2) and parts.offset(0, 0)[0] < 0 < parts.offset(0, 1)[0]
    empty = explode.explode([], [], explode.TOP)
    assert empty.groups == 0 and empty.bbox_at(0.5) == ((0, 0, 0), (0, 0, 0))


def test_the_box_at_any_amount_holds_every_instance():
    """Each instance moves on a straight line, so the box of the blend of the collapsed and
    exploded boxes holds the assembly at every amount, and is exact at both ends."""
    rnd = random.Random(7)
    ids, bounds = [], []
    for m in range(4):
        rows = []
        for _k in range(30):
            c = [rnd.uniform(-1, 1) for _ in range(3)]
            h = [rnd.uniform(0.01, 0.3) for _ in range(3)]
            rows += [c[0] - h[0], c[1] - h[1], c[2] - h[2], c[0] + h[0], c[1] + h[1], c[2] + h[2]]
        ids.append([f"g{rnd.randrange(12)}/p{m}-{k}" for k in range(30)])
        bounds.append(array("f", rows).tobytes())
    scene = mesh3d.SceneBuffers([], [], [], ids, [], ((0, 0, 0), (0, 0, 0)), bounds=bounds)
    boxes = _boxes(scene)
    for level in explode.LEVELS:
        e = explode.explode(ids, bounds, level)
        off = _offsets(e, scene)
        for step in range(21):
            t = step / 20
            actual = _union(_moved(b, [t * v for v in off[i]]) for i, b in boxes.items())
            bound = e.bbox_at(t)
            assert all(bound[0][i] <= actual[0][i] + 1e-9 for i in range(3)), (level, t)
            assert all(bound[1][i] >= actual[1][i] - 1e-9 for i in range(3)), (level, t)
            if step in (0, 20):
                assert _flat(bound) == pytest.approx(_flat(actual), abs=1e-9)
    assert explode.explode(ids, bounds, explode.TOP).bbox_at(7.0) == explode.explode(
        ids, bounds, explode.TOP
    ).bbox_at(1.0)  # clamped


def test_the_explode_eases_from_one_amount_to_another():
    assert (explode.ease(0), explode.ease(0.5), explode.ease(1), explode.ease(2)) == (0, 0.5, 1, 1)
    a = explode.Animation(0.0, 1.0, now=0.0)
    assert a.duration == explode.FULL_SECONDS
    values = [a.value(a.duration * i / 10) for i in range(11)]
    assert values[0] == 0 and values[-1] == 1 and values == sorted(values)
    assert values[1] < 0.1 and values[9] > 0.9  # gentle at both ends
    assert not a.done(a.duration / 2) and a.done(a.duration)
    back = explode.Animation(1.0, 0.5, now=0.0)
    assert back.value(0.0) == 1.0 and back.value(back.duration) == 0.5
    assert explode.Animation(0.5, 0.52, now=0).duration == explode.MIN_SECONDS


def test_a_dragged_slider_is_followed_closely():
    """The view follows a slider dragged from 0 to 100 percent over one second, a value
    change every 16 ms: closing on each new value exponentially it keeps about 60 ms
    behind, and is there a fraction of a second after the release. Starting the half-
    second ease again at each change, as it did, left it at 15 percent when the handle
    reached 100."""

    def drag(follow: bool, seconds: float = 1.0, step: float = 0.016, tick: float = 0.015):
        """The slider changes every ``step``; the view draws the amount every ``tick``."""
        value, anim, next_tick, lags = 0.0, None, tick, []
        n = round(seconds / step)
        now = 0.0
        for k in range(1, n + 1):
            now, target = k * step, k / n
            while next_tick < now:
                value = anim.value(next_tick) if anim is not None else value
                next_tick += tick
            if not follow:
                anim = explode.Animation(value, target, now)
            elif anim is None:
                anim = explode.Follow(value, target, now)
            else:
                anim.retarget(target, now)
            lags.append(target - value)
        released = value
        settle = 0.0
        while not anim.done(now + settle) and settle < 10:
            settle += tick
        return max(lags), released, settle

    worst, at_release, settle = drag(True)
    assert worst < 0.1 and at_release > 0.9 and settle < 0.3
    old_worst, old_release, _ = drag(False)
    assert old_release == pytest.approx(0.145, abs=0.01) and old_worst > 0.8  # as the review measured
    f = explode.Follow(0.0, 1.0, now=0.0)
    assert f.value(0.0) == 0.0 and f.value(explode.FOLLOW_SECONDS) == pytest.approx(1 - math.exp(-1))
    f.retarget(0.5, explode.FOLLOW_SECONDS)  # from where it is, without starting from rest
    assert f.value(explode.FOLLOW_SECONDS) == pytest.approx(1 - math.exp(-1))
    assert not f.done(explode.FOLLOW_SECONDS) and f.done(10.0) and f.value(10.0) == pytest.approx(0.5)


def test_a_part_inside_another_is_moved_out_of_it():
    """Moving each group away from the centre parts two groups only by the distance between
    their centres, so a pin in a housing (here off the assembly's centre) stays inside it.
    The groups still overlapping when fully exploded are parted: the smaller one moves out
    along the axis that takes the least travel, a gap clear, and every group still moves on
    a straight line."""

    def box(c, h):
        return [c[0] - h[0], c[1] - h[1], c[2] - h[2], c[0] + h[0], c[1] + h[1], c[2] + h[2]]

    rows = [
        box((0.1, 0.0, 0.0), (0.08, 0.03, 0.03)),  # the housing, long in x
        box((0.11, 0.01, 0.0), (0.01, 0.01, 0.025)),  # a pin in it, near its centre
        box((-0.1, 0.0, 0.0), (0.02, 0.02, 0.02)),  # a part on its own
    ]
    ids = [["housing-1", "pin-1", "other-1"]]
    bounds = [array("f", [v for r in rows for v in r]).tobytes()]
    e = explode.explode(ids, bounds, explode.TOP)
    boxes = [((r[0], r[1], r[2]), (r[3], r[4], r[5])) for r in rows]
    moved = [_moved(b, e.offset(0, k)) for k, b in enumerate(boxes)]

    def overlap(a, b):
        return all(min(a[1][i], b[1][i]) - max(a[0][i], b[0][i]) > 1e-9 for i in range(3))

    assert overlap(boxes[0], boxes[1])  # collapsed, the pin is in the housing
    radial = [_moved(b, [c - m for c, m in zip(_centre(b), _centre(e.bbox0), strict=True)]) for b in boxes]
    assert overlap(radial[0], radial[1])  # moved away from the centre alone, it still is
    assert not any(overlap(moved[a], moved[b]) for a, b in ((0, 1), (0, 2), (1, 2)))
    gap = explode.GAP * math.dist(e.bbox0[0], e.bbox0[1])
    # The pin's shortest way out is along y, on its own side of the housing's middle (+y).
    housing, pin = moved[0], moved[1]
    assert pin[0][1] - housing[1][1] == pytest.approx(gap, rel=1e-4)
    assert e.offset(0, 1)[0] == pytest.approx(0.08) and e.offset(0, 1)[2] == 0  # only y changed
    assert e.offset(0, 0) == pytest.approx((0.07, 0, 0)) and e.offset(0, 2) == pytest.approx((-0.13, 0, 0))
    assert _flat(e.bbox1) == pytest.approx(_flat(_union(moved)), abs=1e-7)
    # Nothing to part: the radial offsets stand.
    pair = array("f", box((-1, 0, 0), (0.1,) * 3) + box((1, 0, 0), (0.1,) * 3)).tobytes()
    apart = explode.explode([["a-1", "b-1"]], [pair])
    assert apart.offset(0, 0) == pytest.approx((-1, 0, 0)) and apart.offset(0, 1) == pytest.approx((1, 0, 0))


def test_parting_overlaps_stops_at_its_budget():
    """Thousands of boxes all in one place, off the centre: every pair overlaps. Parting
    them runs on the UI thread, so it stops at its budget of comparisons instead of
    taking quadratic time, and past SEPARATE_UP_TO groups it is not tried."""
    import time

    for n, parted in ((3_000, True), (explode.SEPARATE_UP_TO + 1, False)):
        rows = [0.5, 0.5, 0.5, 0.6, 0.6, 0.6] * (n - 1) + [-1, -1, -1, -0.9, -0.9, -0.9]
        ids = [[f"p-{k}" for k in range(n)]]
        start = time.perf_counter()
        e = explode.explode(ids, [array("f", rows).tobytes()], explode.PARTS)
        assert time.perf_counter() - start < 10 and e.groups == n
        offsets = {e.offset(0, k) for k in range(n - 1)}
        assert (len(offsets) > 1) is parted  # all at one place, they moved apart or not at all


def test_exploding_changes_no_placement():
    before = _state(FIXTURES)
    scene = _scene()
    matrices = list(scene.matrices)
    for level in explode.LEVELS:
        explode.explode(scene.instance_ids, scene.bounds, level)
    assert scene.matrices == matrices
    assert _state(FIXTURES) == before


# --------------------------------------------------------------------------- the Explode bar
def _show(viewer, name: str) -> None:
    from solidseas_app.viewer.details import TABS

    w = viewer.window
    w.details.tabs.setCurrentIndex(TABS.index("Preview"))
    viewer.select(name)
    _wait(viewer.app, lambda: w.details.preview.mesh_state not in ("starting", "loading") and not w.busy)


@needs_qt
def test_the_explode_bar_moves_the_view_and_collapses_it(viewer):
    w = viewer.window
    pane = w.details.preview
    made: list = []
    pane.view_factory = _stub_view_factory(made)
    pane.gl_check = lambda: (True, "test")
    before = _state(FIXTURES)
    viewer.open(FIXTURES)
    w.change_settings(view_3d=True)
    _show(viewer, "o02_boxA.SLDPRT")
    assert pane.explode_row.isHidden()  # a part does not explode
    _show(viewer, O16)
    view = made[-1]
    assert not pane.explode_row.isHidden() and pane.explode_row.isEnabled()
    assert pane.explode_slider.value() == 0 and pane.explode_percent.text() == "0%"
    assert not pane.collapse_button.isEnabled() and view.explode_level == "top"
    assert pane.explode_groups == {"top": 11, "parts": 12}
    assert "11 top-level components move apart" in pane.explode_percent.toolTip()

    pane.explode_slider.setValue(50)
    assert view.explode_calls[-1] == (0.5, True) and pane.explode_percent.text() == "50%"
    assert pane.collapse_button.isEnabled()
    pane.explode_combo.setCurrentIndex(pane.explode_combo.findData("parts"))
    pane.explode_combo.activated.emit(pane.explode_combo.currentIndex())
    assert view.explode_level == "parts" and pane.explode_level == "parts"
    assert "12 parts move apart" in pane.explode_percent.toolTip()
    pane.collapse_button.click()
    assert view.explode_calls[-1] == (0.0, True) and pane.explode_slider.value() == 0
    assert not pane.collapse_button.isEnabled()

    # Another configuration keeps the amount and the level, applied at once to the new scene.
    pane.set_explode(100)
    pane.config_combo.setCurrentText("Lite")
    pane.choose_configuration("Lite")
    _wait(viewer.app, lambda: made[-1].assembly is not None and made[-1].assembly.n_instances == 10)
    _wait(viewer.app, lambda: pane.mesh_state == "ready" and not w.busy)
    assert view.explode_calls[-1] == (1.0, False) and view.explode_level == "parts"
    assert pane.explode_slider.value() == 100

    # The image shows no explode bar; a new document starts collapsed, at the level chosen.
    pane.set_mode("image")
    assert pane.explode_row.isHidden()
    pane.set_mode("3d")
    _show(viewer, O08)
    assert pane.explode_slider.value() == 0 and pane.explode_level == "parts"
    assert view.explode_level == "parts" and view.explode == 0
    assert pane.explode_groups == {"top": 2, "parts": 2}
    assert _state(FIXTURES) == before


@needs_qt
def test_the_explode_bar_waits_for_the_view(viewer):
    """While another configuration is read the bar is off, and an amount set meanwhile is
    applied, at once, to the scene that arrives."""
    w = viewer.window
    pane = w.details.preview
    made: list = []
    pane.view_factory = _stub_view_factory(made)
    pane.gl_check = lambda: (True, "test")
    viewer.open(FIXTURES)
    w.change_settings(view_3d=True)
    _show(viewer, O16)
    view = made[-1]
    assert pane.explode_row.isEnabled()
    pane.config_combo.setCurrentText("Lite")
    pane.choose_configuration("Lite")
    assert pane.mesh_state == "loading" and not pane.explode_row.isEnabled()
    calls = len(view.explode_calls)
    pane.set_explode(40)
    assert len(view.explode_calls) == calls  # nothing to move yet
    _wait(viewer.app, lambda: pane.mesh_state == "ready" and not w.busy)
    assert view.assembly.n_instances == 10 and pane.explode_row.isEnabled()
    assert view.explode_calls[-1] == (0.4, False)


@needs_qt
def test_a_drag_or_a_key_is_followed_and_a_page_step_eases(viewer):
    """Real mouse events drag the slider's handle: each change asks the view to follow;
    an arrow key's step follows too; Page Up, Collapse and an amount set from outside
    ease there."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionSlider

    w = viewer.window
    pane = w.details.preview
    made: list = []
    pane.view_factory = _stub_view_factory(made)
    pane.gl_check = lambda: (True, "test")
    viewer.open(FIXTURES)
    w.change_settings(view_3d=True)
    _show(viewer, O16)
    view, s = made[-1], pane.explode_slider
    opt = QStyleOptionSlider()
    s.initStyleOption(opt)
    slider = QStyle.ComplexControl.CC_Slider
    handle = s.style().subControlRect(slider, opt, QStyle.SubControl.SC_SliderHandle, s)
    groove = s.style().subControlRect(slider, opt, QStyle.SubControl.SC_SliderGroove, s)
    left, none = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier

    def mouse(kind, x):
        p = QPointF(x, handle.center().y())
        held = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else left
        QApplication.sendEvent(s, QMouseEvent(kind, p, s.mapToGlobal(p), left, held, none))

    mouse(QEvent.Type.MouseButtonPress, handle.center().x())
    assert s.isSliderDown()
    for k in range(1, 21):
        mouse(QEvent.Type.MouseMove, handle.center().x() + (groove.width() - handle.width()) * k / 20)
    mouse(QEvent.Type.MouseButtonRelease, groove.right())
    drag = [c for c in view.explode_calls if c[1] == "follow"]
    assert s.value() == 100 and len(drag) >= 10 and view.explode_calls[-1] == (1.0, "follow")
    assert all(c[1] == "follow" for c in view.explode_calls)  # every change of the drag followed

    QTest.keyClick(s, Qt.Key.Key_PageDown)  # a page step down (the slider counts it down)
    assert view.explode_calls[-1] == (0.75, True)
    QTest.keyClick(s, Qt.Key.Key_Left)
    assert view.explode_calls[-1] == (0.7, "follow")
    pane.collapse_button.click()
    assert view.explode_calls[-1] == (0.0, True)
    pane.set_explode(30)  # as Back and the self-test set it
    assert view.explode_calls[-1] == (0.3, True)


def _one_component(tmp_path, children: int):
    """A folder with an assembly whose one top-level component, a sub-assembly, holds
    ``children`` instances of a part (or, with 0, the assembly holds one part itself)."""
    from builders import TreeXml, resolving_assembly

    folder = tmp_path / "one"
    folder.mkdir(parents=True)
    shutil.copy2(fixture_path("o02_boxA.SLDPRT"), folder / "p.SLDPRT")
    t = TreeXml()
    t.top("m1")
    t.file("3", "p.SLDPRT")
    t.model("m3", "3")
    if children:
        t.file("2", "s.SLDASM", "ASSEMBLY")
        t.model("m2", "2")
        t.ref("m1", "s", 1, "m2")
        for n in range(1, children + 1):
            t.ref("m2", "p", n, "m3", transform=f"1 0 0 0 0 1 0 0 0 0 1 0 {0.05 * n} 0 0 1")
    else:
        t.ref("m1", "p", 1, "m3")
    (folder / "asm.SLDASM").write_bytes(resolving_assembly(t))
    return folder


@needs_qt
def test_one_top_level_component_explodes_every_part_and_says_so(viewer, tmp_path):
    """Grouped by top-level component, an assembly of one sub-assembly would not move at
    all: it starts at Every part, the bar says why in words next to the slider, and the
    next document is back at the level the user chose. With a single part the slider is
    off and the bar says nothing can move."""
    w = viewer.window
    pane = w.details.preview
    made: list = []
    pane.view_factory = _stub_view_factory(made)
    pane.gl_check = lambda: (True, "test")
    folder = _one_component(tmp_path, 3)
    shutil.copy2(fixture_path(O08), folder / O08)
    viewer.open(folder)
    w.change_settings(view_3d=True)
    _show(viewer, "asm.SLDASM")
    view = made[-1]
    assert pane.explode_groups == {"top": 1, "parts": 3}
    assert pane.explode_level == "parts" and view.explode_level == "parts" and pane.session_level == "top"
    assert pane.explode_combo.currentData() == "parts" and pane.explode_slider.isEnabled()
    assert not pane.explode_hint.isHidden()
    assert pane.explode_hint.text() == "One top-level component, so every part moves on its own."
    pane.set_explode(100)
    assert view.explode_calls[-1] == (1.0, True)
    _show(viewer, O08)  # two top-level components: the user's level again
    assert pane.explode_level == "top" and pane.explode_hint.isHidden() and pane.explode_slider.value() == 0
    # Chosen by the user for this document, Top-level stays and the bar says nothing moves.
    _show(viewer, "asm.SLDASM")
    pane.explode_combo.setCurrentIndex(pane.explode_combo.findData("top"))
    pane.explode_combo.activated.emit(pane.explode_combo.currentIndex())
    assert pane.explode_level == "top" and view.explode_level == "top"
    assert pane.explode_hint.text().startswith("There is only one top-level component, so nothing moves")

    single = _one_component(tmp_path / "single", 0)
    viewer.open(single)
    _show(viewer, "asm.SLDASM")
    assert pane.explode_groups == {"top": 1, "parts": 1}
    assert not pane.explode_slider.isEnabled() and not pane.explode_combo.isEnabled()
    assert not pane.collapse_button.isEnabled()
    assert pane.explode_hint.text() == "There is only one part, so nothing moves."


# --------------------------------------------------------------------------- OpenGL, on the real display
_GL_EXPLODE = """
from solidseas_app.viewer import mesh3d
scene = mesh3d.read_assembly_scene(sys.argv[1], sys.argv[2], sys.argv[2], 1_000_000)["data"]
out = {"gl": True}
now = [100.0]
for instanced in (True, False):
    view3d.Renderer.allow_instancing = instanced
    view = view3d.ModelView()
    view._clock = lambda: now[0]
    view.resize(400, 300)
    view.set_assembly(scene)
    collapsed = view.grabFramebuffer()
    view.explode_to(1.0)
    r = {"animating": view.animating, "error": view.error}
    now[0] += 0.1
    view._tick()
    r["partway"] = view.explode
    r["partway_box"] = [list(c) for c in view.camera.bbox]
    now[0] += 1.0
    view._tick()
    r["end"] = view.explode
    r["still"] = view.animating
    exploded = view.grabFramebuffer()
    r["offsets"] = [[v for k, v in enumerate(m.offsets) if k % 4 != 3] for m in view.renderer.meshes]
    r["numbers"] = [v for m in view.renderer.meshes for v in m.offsets[3::4]]
    r["box"] = [list(c) for c in view.camera.bbox]
    r["box1"] = [list(c) for c in view.explosion.bbox1]
    r["fitted"] = view.camera.fitted
    r["changed"] = exploded != collapsed
    view.set_explode_level("parts")
    r["parts_box"] = [list(c) for c in view.camera.bbox]
    view.explode_to(0.0, animate=False)
    r["collapsed_again"] = view.grabFramebuffer() == collapsed
    view.set_explode_level("top")
    view.explode_to(1.0, animate=False)
    r["explode_box"] = [list(c) for c in view.camera.bbox]
    out[str(instanced)] = r
    out["image_" + str(instanced)] = exploded
out["same"] = out.pop("image_True") == out.pop("image_False")
print(json.dumps(out))
"""


@needs_qt
def test_the_3d_view_explodes_on_the_display():
    """The view eases to the amount asked for on its own clock, the camera follows the box of
    the exploded assembly, the offsets reach the GPU, collapsing gives the first picture
    back, and instanced drawing and drawing one instance at a time agree."""
    out = run_gl(_GL_EXPLODE, str(fixture_path(O16)), str(FIXTURES))
    scene = _scene()
    e = explode.explode(scene.instance_ids, scene.bounds, explode.TOP)
    parts = explode.explode(scene.instance_ids, scene.bounds, explode.PARTS)
    for r in (out["True"], out["False"]):
        assert r["error"] is None and r["animating"] and not r["still"]
        assert 0 < r["partway"] < 1 and r["end"] == 1.0
        assert _flat(r["partway_box"]) == pytest.approx(_flat(e.bbox_at(r["partway"])), abs=1e-9)
        assert _flat(r["box"]) == pytest.approx(_flat(e.bbox1)) and r["box"] == r["box1"]
        assert r["fitted"] and r["changed"] and r["collapsed_again"]
        assert _flat(r["offsets"]) == pytest.approx(_flat([list(o) for o in e.offsets]), abs=1e-9)
        assert r["numbers"] == list(range(1, 13))  # each instance's number, for picking
        assert _flat(r["parts_box"]) == pytest.approx(_flat(parts.bbox1))
        assert _flat(r["explode_box"]) == pytest.approx(_flat(e.bbox1))
    assert out["same"]


_GL_DRAG = """
import time
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QStyle, QStyleOptionSlider
from solidseas_app.viewer import mesh3d
from solidseas_app.viewer.preview import PreviewPane

result = mesh3d.read_assembly_scene(sys.argv[1], sys.argv[2], sys.argv[2], 1_000_000)
pane = PreviewPane()
pane.resize(900, 700)
pane.set_3d_enabled(True)
pane.reset("assembly")
pane.meshRequested.connect(lambda: pane.set_mesh_result(result))
pane.show()


def pump(seconds):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.002)


deadline = time.perf_counter() + 60
while pane.mesh_state != "ready" and time.perf_counter() < deadline:
    pump(0.02)
view, s = pane.view, pane.explode_slider
pump(0.3)
opt = QStyleOptionSlider()
s.initStyleOption(opt)
slider = QStyle.ComplexControl.CC_Slider
handle = s.style().subControlRect(slider, opt, QStyle.SubControl.SC_SliderHandle, s)
groove = s.style().subControlRect(slider, opt, QStyle.SubControl.SC_SliderGroove, s)
left, none = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier


def mouse(kind, x):
    p = QPointF(x, handle.center().y())
    held = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else left
    QApplication.sendEvent(s, QMouseEvent(kind, p, s.mapToGlobal(p), left, held, none))


# A hand's drag: 50 moves 16 ms apart, from 0 to 100 percent, then let go.
trace = []
mouse(QEvent.Type.MouseButtonPress, handle.center().x())
for k in range(1, 51):
    mouse(QEvent.Type.MouseMove, handle.center().x() + (groove.width() - handle.width()) * k / 50)
    pump(0.016)
    trace.append((s.value(), view.explode * 100))
mouse(QEvent.Type.MouseButtonRelease, groove.right())
released = time.perf_counter()
at_release = view.explode * 100
while view.animating and time.perf_counter() - released < 5:
    pump(0.005)
settle = time.perf_counter() - released
end_value = view.explode
# The arrow key held down: ten steps at 30 a second, back down.
s.setFocus()
for _ in range(10):
    QApplication.sendEvent(s, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Left, none))
    pump(1 / 30)
key_lag = view.explode * 100 - s.value()
lags = [sv - ev for sv, ev in trace]
print(json.dumps({
    "slider": s.value(), "error": view.error, "max_lag": max(lags), "mean_lag": sum(lags) / len(lags),
    "at_release": at_release, "settle": settle, "end": end_value, "key_lag": key_lag,
    "drag_values": trace[-1][0],
}))
"""


@needs_qt
def test_the_view_keeps_up_with_a_dragged_slider_on_the_display():
    """The real Preview tab and 3D view on the display, o16 drawn: the slider's handle is
    dragged from 0 to 100 percent with 50 mouse moves over about a second, as a hand
    does. The view stays close behind it all the way (the review measured 80 points
    behind at worst and 40 on average, and 19.6 percent when the handle reached 100),
    and is there soon after the release; ten arrow-key steps at 30 a second are
    followed as closely."""
    out = run_gl(_GL_DRAG, str(fixture_path(O16)), str(FIXTURES))
    assert out["error"] is None and out["drag_values"] == 100
    assert out["max_lag"] <= 30 and out["mean_lag"] <= 15, out
    assert out["at_release"] >= 75 and out["settle"] < 0.6 and out["end"] == 1.0, out
    assert out["slider"] == 50 and out["key_lag"] <= 20, out


@needs_qt
def test_the_self_test_saves_an_exploded_assembly(tmp_path):
    shots = tmp_path / "shots"
    before = _state(FIXTURES)
    args = ["--self-test", str(FIXTURES), "--screenshot-dir", str(shots), "--select", O16, "--3d"]
    args += ["--explode", "0", "--explode", "50", "--explode", "100", "--explode", "100,parts"]
    report = run_self_test(args, shots, appdata=tmp_path / "Roaming")
    (doc,) = report["documents"]
    got = [(x["percent"], x["level"], x["groups"], x["drawn"], x.get("moving")) for x in doc["explode"]]
    assert got == [
        (0, "top", 11, 0.0, None),
        (50, "top", 11, 0.5, 11),
        (100, "top", 11, 1.0, 11),
        (100, "parts", 12, 1.0, 12),
    ]
    scene = _scene()
    full = explode.explode(scene.instance_ids, scene.bounds, explode.TOP)
    assert _flat(doc["explode"][2]["bbox"]) == pytest.approx(_flat(full.bbox1), abs=1e-6)
    names = [Path(p).name for p in report["screenshots"]]
    for stem in ("explode_0", "explode_50", "explode_100", "explode_100_parts"):
        assert any(n.endswith(f"o16_asm_features_{stem}.png") for n in names), stem
    assert not (tmp_path / "Roaming").exists()
    assert _state(FIXTURES) == before


@needs_qt
def test_the_self_test_explode_option_is_checked(app, tmp_path, monkeypatch):
    from solidseas_app.viewer import app as viewer_app

    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    base = ["--self-test", str(FIXTURES), "--screenshot-dir", str(tmp_path / "s"), "--select", O16]
    assert viewer_app.build_parser().parse_args([*base, "--3d", "--explode", "40,parts"]).explode == {
        O16: [(40, "parts")]
    }
    # Without a level: the one the Explode bar shows, as moving the slider alone does.
    plain = viewer_app.build_parser().parse_args([*base, "--3d", "--explode", "40"])
    assert plain.explode == {O16: [(40, None)]}
    for bad in ("101", "-1", "half", "50,sideways"):
        assert viewer_app.main([*base, "--3d", "--explode", bad]) == viewer_app.EXIT_USAGE, bad
    assert viewer_app.main([*base, "--explode", "50"]) == viewer_app.EXIT_USAGE  # needs --3d
    assert viewer_app.main(["--explode", "50"]) == viewer_app.EXIT_USAGE  # belongs to the self-test
    assert not (tmp_path / "s").exists()
