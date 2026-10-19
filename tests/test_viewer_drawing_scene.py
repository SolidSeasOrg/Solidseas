"""The laid-out sheet on screen (``solidseas_app.viewer.drawingscene``;
``docs/DRAWINGS.md`` 6.7, 15.3, 15.4).

The painter is checked against ``painter.RecordingPainter`` on the same sheets
(the same calls in the same order) and by where it puts ink on a hand-made sheet;
the scene by its groups (one per owner), the hover, pick and drag signals from
synthetic mouse events, ``set_sheet`` rebuilding only what changed, selection,
highlights, the owners of a feature, picking, the thumbnail and its red stamp, and
its speed on the 100-hole plate of ``tests/test_drawing_layout.py``; the view by
fitting a drawing of o11 whole, wheel zoom about the pointer and the middle button
pan. Everything runs offscreen (``QT_QPA_PLATFORM=offscreen``) and is skipped
without PySide6. Nothing is written to disk: the thumbnail is bytes, decoded here.
"""

import dataclasses
import math
import os
import time

import pytest

try:
    import PySide6.QtWidgets  # noqa: F401
except ImportError:  # the window's tests need the [app] extra
    pytest.skip("PySide6 is not installed: the sheet's scene is not tested", allow_module_level=True)

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPainter, QPalette, QWheelEvent
from PySide6.QtWidgets import QApplication, QGraphicsSceneMouseEvent

import drawing_parts as P
from drawing_plan_fixtures import plate
from drawing_support import COMPANY, fixture, sample_sheet, tiny_png
from solidseas import drawing
from solidseas.drawing import display as D
from solidseas.drawing import edit, facegraph, fonts, pdf
from solidseas.drawing import settings as S
from solidseas.drawing.layout import layout
from solidseas.drawing.painter import Painter, RecordingPainter, paint
from solidseas.drawing.plan import make_plan
from solidseas.errors import InvalidArgumentError

LEFT, MIDDLE, NONE = Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton, Qt.MouseButton.NoButton
NO_KEYS, CTRL = Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ControlModifier
DRAWING_CALLS = ("stroke", "fill", "text", "image")
METHODS = (
    "begin_page",
    "set_stroke",
    "path",
    "stroke",
    "fill",
    "text",
    "image",
    "group",
    "end_group",
    "end_page",
)


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from solidseas_app.viewer.app import use_system_fonts

    use_system_fonts()
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def ds(app):
    from solidseas_app.viewer import drawingscene

    return drawingscene


@pytest.fixture(scope="module")
def o11():
    """A drawing of o11 made by the library, as the drawing child process makes one."""
    s = S.with_value(S.DrawingSettings(), "company", "name", COMPANY)
    s = S.with_value(s, "people", "people", [{"name": "Ann Bee", "initials": "AB"}])
    fields = {"number": "SS-11", "drawn_by": "Ann Bee", "material": "6061-T6", "finish": "None"}
    return drawing.make_drawing(fixture("o11_curved.SLDPRT"), settings=s, fields=fields)


@pytest.fixture(scope="module")
def plate_sheet():
    """The 100-hole plate of ``test_two_hundred_locations_lay_out_quickly``, laid out."""
    xt, truth = P.random_plate(3, n=100)
    m = facegraph.from_transmit(xt)
    by_size: dict[float, list[int]] = {}
    for k, h in enumerate(truth["holes"]):
        by_size.setdefault(round(h["diameter"], 6), []).append(k)
    groups = [("scattered", ks) for ks in by_size.values() if len(ks) > 1]
    ctx = plate((m, truth), patterns=groups)
    return layout(make_plan(ctx), options=ctx.options, settings=ctx.settings).sheet


def owners_of(sheet):
    return list(dict.fromkeys(i.owner for i in sheet.painted))


def items_of(sheet, owner):
    return tuple(i for i in sheet.painted if i.owner == owner)


def text_centre(sheet, owner):
    """The sheet point in the middle of an owner's first text run."""
    t = next(i for i in sheet.painted if isinstance(i, D.TextRun) and i.owner == owner)
    shift = {"left": 0.0, "centre": -t.width / 2, "right": -t.width}[t.anchor] + t.width / 2
    a = math.radians(t.angle_deg)
    up = t.size * fonts.CAP_HEIGHT / 2
    return (t.x + shift * math.cos(a) - up * math.sin(a), t.y + shift * math.sin(a) + up * math.cos(a))


def rendered(scene, width_px=1200):
    """The scene as it is on screen now (hover, selection and highlights included)."""
    paper = scene.sceneRect()
    img = QImage(width_px, round(width_px * paper.height() / paper.width()), QImage.Format.Format_RGB32)
    img.fill(QColor(255, 255, 255))
    qp = QPainter(img)
    qp.setRenderHint(QPainter.RenderHint.Antialiasing)
    scene.render(qp, QRectF(img.rect()), paper)
    qp.end()
    return img


def count(img, near, tol=40, step=1):
    n = 0
    for y in range(0, img.height(), step):
        for x in range(0, img.width(), step):
            c = QColor(img.pixel(x, y))
            if abs(c.red() - near[0]) + abs(c.green() - near[1]) + abs(c.blue() - near[2]) <= tol:
                n += 1
    return n


def dark(img, step=1):
    n = 0
    for y in range(0, img.height(), step):
        for x in range(0, img.width(), step):
            if QColor(img.pixel(x, y)).lightness() < 100:
                n += 1
    return n


def send(scene, kind, pos, buttons=NONE, button=NONE, modifiers=NO_KEYS):
    ev = QGraphicsSceneMouseEvent(kind)
    ev.setScenePos(QPointF(pos))
    ev.setButtons(buttons)
    ev.setButton(button)
    ev.setModifiers(modifiers)
    QApplication.sendEvent(scene, ev)


def mouse(view, kind, pos, button=NONE, buttons=NONE):
    p = QPointF(pos)
    ev = QMouseEvent(kind, p, QPointF(view.viewport().mapToGlobal(p)), button, buttons, NO_KEYS)
    QApplication.sendEvent(view.viewport(), ev)


def listen(scene):
    got = []
    scene.hovered.connect(lambda owner: got.append(("hovered", owner)))
    scene.picked.connect(lambda owner, keys: got.append(("picked", owner, keys)))
    scene.moved.connect(lambda owner, dx, dy: got.append(("moved", owner, dx, dy)))
    return got


def shifted(sheet, owner, dx, dy):
    """The sheet with one owner's painted items moved, as a dragged dimension laid out
    again would be."""

    def move(item):
        if isinstance(item, (D.Stroke, D.Fill)):
            path = tuple(
                (op[0], *(v + (dx if k % 2 == 0 else dy) for k, v in enumerate(op[1:]))) for op in item.path
            )
            return dataclasses.replace(item, path=path)
        return dataclasses.replace(item, x=item.x + dx, y=item.y + dy)

    painted = tuple(move(i) if i.owner == owner else i for i in sheet.painted)
    return dataclasses.replace(sheet, painted=painted)


# --------------------------------------------------------------------------- the painter


def test_the_painter_gets_the_calls_the_recording_painter_gets(ds, o11):
    class Logged(ds.QtPainter):
        def __init__(self, *args, **kw):
            super().__init__(*args, **kw)
            self.calls = []

    def logged(name):
        def method(self, *args):
            self.calls.append((name, *args))
            return getattr(ds.QtPainter, name)(self, *args)

        return method

    for name in METHODS:
        setattr(Logged, name, logged(name))

    assert isinstance(ds.QtPainter(), Painter)
    for sheet in (sample_sheet(), o11.sheet):
        expected = RecordingPainter()
        paint(sheet, expected)
        img = QImage(800, 600, QImage.Format.Format_RGB32)
        img.fill(QColor(255, 255, 255))
        qp = QPainter(img)
        qp.scale(800 / sheet.width, 800 / sheet.width)
        drawn = Logged(qp)
        paint(sheet, drawn)
        qp.end()
        assert drawn.calls == expected.calls
        assert drawn.problems == []
        assert dark(img, step=2) > 200
        # recorded rather than drawn: one item for each drawing call, none dropped
        kept = ds.QtPainter()
        paint(sheet, kept)
        assert len(kept.prims) == sum(1 for c in expected.calls if c[0] in DRAWING_CALLS)


def test_the_painter_puts_ink_where_the_pdf_does(ds):
    """A 100 by 50 mm sheet at 10 pixels a millimetre: y is up, dashes start with a
    dash, a fill is filled, text is placed by its anchor with Helvetica's widths, and
    the logo lands in its box."""
    size = fonts.font_size(5.0)
    painted = (
        D.Stroke((("M", 10.0, 40.0), ("L", 90.0, 40.0)), 1.0),
        D.Stroke((("M", 10.0, 30.0), ("L", 90.0, 30.0)), 0.5, (5.0, 5.0)),
        D.Fill((("M", 2.0, 2.0), ("L", 8.0, 2.0), ("L", 8.0, 8.0), ("L", 2.0, 8.0), ("Z",)), grey=0.5),
        D.TextRun(90.0, 5.0, size, "HHHH", anchor="right", width=fonts.measure("HHHH", size)),
        D.TextRun(30.0, 10.0, size, "HH", angle_deg=90.0, width=fonts.measure("HH", size)),
        D.ImageRun(40.0, 20.0, 8.0, 4.0, tiny_png()),
    )
    sheet = D.Sheet("test", 100.0, 50.0, painted=painted)
    img = QImage(1000, 500, QImage.Format.Format_RGB32)
    img.fill(QColor(255, 255, 255))
    qp = QPainter(img)
    qp.scale(10.0, 10.0)
    painter = ds.QtPainter(qp)
    paint(sheet, painter)
    qp.end()

    def at(x_mm, y_mm):  # a sheet point (y up) as the pixel's colour
        c = QColor(img.pixel(int(x_mm * 10), int((50.0 - y_mm) * 10)))
        return (c.red(), c.green(), c.blue())

    assert at(50.0, 40.0) == (0, 0, 0) and at(50.0, 10.0) == (255, 255, 255)  # y up
    assert at(12.5, 30.0) == (0, 0, 0) and at(17.5, 30.0) == (255, 255, 255)  # dash, gap
    assert at(22.5, 30.0) == (0, 0, 0)
    assert all(abs(v - 128) <= 1 for v in at(5.0, 5.0))  # the grey fill
    assert at(44.0, 22.0) == (0x10, 0x20, 0x30)  # the logo's colour inside its box
    assert at(44.0, 25.0) == (255, 255, 255)

    # text: the run spans exactly Helvetica's width, ending at its right anchor
    kept = ds.QtPainter()
    paint(sheet, kept)
    right, upright = (p for p in kept.prims if p.text)
    box = right.outline.boundingRect()
    assert box.right() == pytest.approx(90.0, abs=1e-6)
    assert box.width() == pytest.approx(fonts.measure("HHHH", size), abs=1e-6)
    ink = [
        x
        for x in range(500, 1000)  # right of the grey fill
        for y in range(int((50 - 5 - 3.5) * 10), int((50 - 5) * 10))
        if QColor(img.pixel(x, y)).lightness() < 128
    ]
    assert 900 - fonts.measure("HHHH", size) * 10 - 2 <= min(ink) and max(ink) <= 901
    # turned 90 degrees: it runs up the sheet from its anchor, tops to the left
    turned = upright.outline.boundingRect()
    assert turned.bottom() == pytest.approx(50.0 - 10.0, abs=1e-6)
    assert turned.height() == pytest.approx(fonts.measure("HH", size), abs=1e-6)
    assert turned.right() < 30.0 + size * 0.3 and turned.left() < 30.0 - size * 0.7


def test_what_a_sheet_cannot_hold_is_left_out_and_said(ds):
    bad_logo = b"\x89PNG\r\n\x1a\nnot really"
    painted = (
        D.Stroke((("M", 0.0, 0.0), ("L", float("nan"), 5.0)), 0.3, owner="v-1"),
        D.Stroke((("L", 1.0, 1.0),), 0.3, owner="v-1"),
        D.Stroke((("M", 1.0, 1.0), ("L", 9.0, 1.0)), -1.0, owner="v-1"),
        D.TextRun(10.0, 10.0, 0.0, "ZERO", owner="n-1"),
        D.ImageRun(5.0, 5.0, 10.0, 10.0, bad_logo, owner="logo"),
        D.Stroke((("M", 1.0, 2.0), ("L", 9.0, 2.0)), 0.3, owner="v-1"),
    )
    sheet = D.Sheet("test", 100.0, 50.0, painted=painted)
    scene = ds.SheetScene(sheet)
    problems = scene.problems
    assert any("path" in p for p in problems)
    assert any("stroke" in p for p in problems)
    assert any("text" in p for p in problems)
    # the logo is refused for the reason the PDF writer gives
    (logo_problem,) = [p for p in problems if p.startswith("the logo was left out")]
    assert logo_problem in pdf.to_pdf(D.Sheet("test", 100.0, 50.0, painted=painted[4:5])).problems
    assert len(scene.item("v-1").prims) == 1  # only the good stroke
    assert scene.item("logo").prims == ()
    with pytest.raises(InvalidArgumentError):
        scene.set_sheet("not a sheet")
    with pytest.raises(InvalidArgumentError):
        scene.set_sheet(D.Sheet("test", 0.0, 50.0))


# --------------------------------------------------------------------------- the scene


def test_every_owner_becomes_one_group(ds, o11, plate_sheet):
    for sheet in (o11.sheet, plate_sheet):
        scene = ds.SheetScene(sheet)
        owners = owners_of(sheet)
        assert scene.owners() == tuple(owners)
        assert len(scene.items()) == len(owners)
        assert all(isinstance(i, ds.OwnerItem) and i.parentItem() is None for i in scene.items())
        for owner in owners:
            item = scene.item(owner)
            assert item.owner == owner and item.items == items_of(sheet, owner)
            # drawn by painter.paint on just its items: one recorded item a drawing call
            calls = RecordingPainter()
            paint(D.Sheet("", sheet.width, sheet.height, painted=item.items), calls)
            assert len(item.prims) == sum(1 for c in calls.calls if c[0] in DRAWING_CALLS)
        assert scene.sceneRect() == QRectF(0.0, 0.0, sheet.width, sheet.height)
        assert scene.problems == ()
        # stacked as the PDF draws: dimensions over views, the views in sheet order
        dims = [o for o in owners if o.startswith("d-")]
        views = [o for o in owners if o.startswith("v-")]
        assert min(scene.item(d).zValue() for d in dims) > max(scene.item(v).zValue() for v in views)
        zs = [scene.item(v).zValue() for v in views]
        assert zs == sorted(zs)
    sample = ds.SheetScene(sample_sheet())
    assert set(sample.owners()) == {"v-1", "d-1", "title", "", "logo"}  # the stamp has no owner there


def test_hover_pick_and_drag_from_mouse_events(ds, o11):
    sheet = o11.sheet
    scene = ds.SheetScene(sheet)
    got = listen(scene)
    on = scene.to_scene(text_centre(sheet, "d-2"))
    empty = scene.to_scene((240.0, 120.0))
    assert scene.owner_at(on) == "d-2" and scene.owner_at(empty) == ""

    send(scene, QEvent.Type.GraphicsSceneMouseMove, on)
    assert got == [("hovered", "d-2")] and scene.hover == "d-2"
    assert scene.item("d-2").colour == ds.HOVER_COLOUR
    send(scene, QEvent.Type.GraphicsSceneMouseMove, on + QPointF(0.1, 0.0))
    assert got == [("hovered", "d-2")]  # the same owner: said once
    send(scene, QEvent.Type.GraphicsSceneMouseMove, empty)
    assert got[-1] == ("hovered", "") and scene.item("d-2").colour is None
    got.clear()

    # press, drag 5 mm right and 3 mm down the screen, release: moved by (5, -3) on the sheet
    send(scene, QEvent.Type.GraphicsSceneMouseMove, on)
    send(scene, QEvent.Type.GraphicsSceneMousePress, on, LEFT, LEFT, CTRL)
    send(scene, QEvent.Type.GraphicsSceneMouseMove, on + QPointF(5.0, 3.0), LEFT)
    assert scene.item("d-2").pos() == QPointF(5.0, 3.0)
    send(scene, QEvent.Type.GraphicsSceneMouseRelease, on + QPointF(5.0, 3.0), NONE, LEFT)
    assert got == [("hovered", "d-2"), ("picked", "d-2", CTRL), ("moved", "d-2", 5.0, -3.0)]
    # it stays where it was dropped until the next sheet comes
    assert scene.item("d-2").pos() == QPointF(5.0, 3.0)
    assert scene.set_sheet(sheet) == ()
    assert scene.item("d-2").pos() == QPointF(0.0, 0.0)
    got.clear()

    # empty paper picks nothing; a click without a drag moves nothing
    send(scene, QEvent.Type.GraphicsSceneMousePress, empty, LEFT, LEFT)
    send(scene, QEvent.Type.GraphicsSceneMouseRelease, empty, NONE, LEFT)
    send(scene, QEvent.Type.GraphicsSceneMousePress, on, LEFT, LEFT)
    send(scene, QEvent.Type.GraphicsSceneMouseMove, on + QPointF(0.2, 0.0), LEFT)
    send(scene, QEvent.Type.GraphicsSceneMouseRelease, on + QPointF(0.2, 0.0), NONE, LEFT)
    assert got == [("picked", "", NO_KEYS), ("picked", "d-2", NO_KEYS)]
    got.clear()

    # only a dimension drags: the title block stays put
    title = scene.to_scene(text_centre(sheet, "title"))
    assert scene.owner_at(title) == "title" and not scene.can_move("title")
    send(scene, QEvent.Type.GraphicsSceneMousePress, title, LEFT, LEFT)
    send(scene, QEvent.Type.GraphicsSceneMouseMove, title + QPointF(10.0, 10.0), LEFT)
    send(scene, QEvent.Type.GraphicsSceneMouseRelease, title + QPointF(10.0, 10.0), NONE, LEFT)
    assert [g for g in got if g[0] == "moved"] == [] and scene.item("title").pos() == QPointF(0.0, 0.0)

    # Escape puts a dragged dimension back and says nothing
    send(scene, QEvent.Type.GraphicsSceneMousePress, on, LEFT, LEFT)
    send(scene, QEvent.Type.GraphicsSceneMouseMove, on + QPointF(4.0, 0.0), LEFT)
    assert scene.item("d-2").pos() == QPointF(4.0, 0.0)
    QApplication.sendEvent(scene, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, NO_KEYS))
    send(scene, QEvent.Type.GraphicsSceneMouseRelease, on + QPointF(4.0, 0.0), NONE, LEFT)
    assert scene.item("d-2").pos() == QPointF(0.0, 0.0)
    assert [g for g in got if g[0] == "moved"] == []

    # the wizard's preview is not editable: nothing drags there
    preview = ds.SheetScene(sheet, editable=False)
    seen = listen(preview)
    send(preview, QEvent.Type.GraphicsSceneMousePress, on, LEFT, LEFT)
    send(preview, QEvent.Type.GraphicsSceneMouseMove, on + QPointF(5.0, 0.0), LEFT)
    send(preview, QEvent.Type.GraphicsSceneMouseRelease, on + QPointF(5.0, 0.0), NONE, LEFT)
    assert seen == [("picked", "d-2", NO_KEYS)] and not preview.can_move("d-2")


def test_the_view_hovers_picks_and_drags_by_its_pixels(ds, o11):
    sheet = o11.sheet
    scene = ds.SheetScene(sheet)
    view = ds.SheetView(scene)
    view.resize(1000, 750)
    view.show()
    QApplication.processEvents()
    got = listen(scene)
    on = view.mapFromScene(scene.to_scene(text_centre(sheet, "d-2")))
    mouse(view, QEvent.Type.MouseMove, on + QPoint(0, 60))
    mouse(view, QEvent.Type.MouseMove, on)
    assert got[-1] == ("hovered", "d-2")
    mouse(view, QEvent.Type.MouseButtonPress, on, LEFT, LEFT)
    mouse(view, QEvent.Type.MouseMove, on + QPoint(30, 0), NONE, LEFT)
    mouse(view, QEvent.Type.MouseButtonRelease, on + QPoint(30, 0), LEFT, NONE)
    _hovered, picked, moved = got[-3:]
    assert picked == ("picked", "d-2", NO_KEYS)
    assert moved[:2] == ("moved", "d-2")
    assert moved[2] == pytest.approx(30.0 / view.scale_px_per_mm(), rel=1e-6) and moved[3] == 0.0
    # leaving the view ends the hover
    QApplication.sendEvent(view.viewport(), QEvent(QEvent.Type.Leave))
    assert got[-1] == ("hovered", "") and scene.hover == ""
    view.close()


def test_set_sheet_rebuilds_only_the_owners_that_changed(ds, o11):
    scene = ds.SheetScene(o11.sheet)
    before = {o: scene.item(o) for o in scene.owners()}
    scene.select(["d-2", "d-3"])
    scene.highlight(["d-4", "d-3"])
    moved, _checks = edit.move(o11, "d-2", 3.0, 4.0)
    assert scene.set_sheet(moved.sheet) == ("d-2",)
    for owner, item in before.items():
        assert (scene.item(owner) is item) == (owner != "d-2")
    assert scene.item("d-2").items == items_of(moved.sheet, "d-2")
    assert scene.selected() == ("d-2", "d-3")
    assert scene.item("d-2").colour == ds.SELECTED_COLOUR  # a rebuilt owner keeps its colour
    removed, _checks = edit.remove(moved, "d-3")
    assert set(scene.set_sheet(removed.sheet)) == {"d-1", "d-1-frame", "d-3"}
    assert scene.item("d-3") is None and "d-3" not in scene.owners()
    assert scene.selected() == ("d-2",) and set(scene.highlighted()) == {"d-4"}
    assert len(scene.items()) == len(owners_of(removed.sheet))
    assert scene.set_sheet(removed.sheet) == ()
    # an owner that comes back is added again
    assert set(scene.set_sheet(moved.sheet)) == {"d-1", "d-1-frame", "d-3"}
    assert scene.item("d-3") is not None and scene.owners() == tuple(owners_of(moved.sheet))


def test_selection_and_highlight_colour_their_owners(ds, o11):
    sheet = o11.sheet
    flagged = tuple(
        dataclasses.replace(a, flags=(*a.flags, "needs_attention"))
        if isinstance(a, D.Dimension) and a.id == "d-4"
        else a
        for a in sheet.annotations
    )
    scene = ds.SheetScene(dataclasses.replace(sheet, annotations=flagged))
    assert scene.item("d-4").colour == ds.WARNING_COLOUR  # needs attention
    assert scene.item("stamp").colour == ds.STAMP_COLOUR
    assert scene.item("plot").colour is None and scene.item("d-2").colour is None
    blue = (ds.SELECTED_COLOUR.red(), ds.SELECTED_COLOUR.green(), ds.SELECTED_COLOUR.blue())
    assert count(rendered(scene), blue, step=2) == 0

    scene.select(["title", "d-2", "nothing-of-the-sheet"])
    assert scene.selected() == ("d-2", "title")  # in sheet order, unknown owners ignored
    assert scene.item("d-2").colour == ds.SELECTED_COLOUR
    assert count(rendered(scene), blue, step=2) > 100
    scene.select([])
    assert scene.selected() == () and scene.item("d-2").colour is None

    scene.highlight(["d-3", "datum-A"], "#00a000")
    assert scene.item("d-3").colour == QColor("#00a000")
    assert count(rendered(scene), (0, 160, 0), step=2) > 20
    scene.highlight(["d-5"])
    assert scene.item("d-3").colour is None and scene.item("d-5").colour == ds.WARNING_COLOUR
    with pytest.raises(InvalidArgumentError):
        scene.highlight(["d-5"], "not a colour")
    scene.highlight([])
    assert scene.highlighted() == {} and scene.item("d-5").colour is None

    # the hover colour wins over the selection, the selection over a highlight
    scene.select(["d-2"])
    scene.highlight(["d-2"], "#00a000")
    assert scene.item("d-2").colour == ds.SELECTED_COLOUR
    scene.set_hover("d-2")
    assert scene.item("d-2").colour == ds.HOVER_COLOUR
    scene.set_hover("")
    assert scene.item("d-2").colour == ds.SELECTED_COLOUR


def picking_sheet():
    """A view's line with a dimension's line along part of it (listed first, drawn on
    top by its layer), an arrowhead, a note and a logo."""
    return D.Sheet(
        "test",
        100.0,
        50.0,
        painted=(
            D.Stroke((("M", 40.0, 25.0), ("L", 60.0, 25.0)), 0.3, layer="dimensions", owner="d-1"),
            D.Stroke((("M", 10.0, 25.0), ("L", 90.0, 25.0)), 0.5, layer="visible", owner="v-1"),
            D.Fill((("M", 70.0, 30.0), ("L", 74.0, 30.0), ("L", 72.0, 34.0), ("Z",)), "dimensions", "d-2"),
            D.TextRun(20.0, 35.0, 5.0, "TEXT", width=fonts.measure("TEXT", 5.0), layer="notes", owner="n-1"),
            D.ImageRun(80.0, 5.0, 10.0, 5.0, tiny_png(), owner="logo"),
        ),
    )


def test_picking_takes_the_nearest_owner_and_the_one_on_top(ds, o11):
    scene = ds.SheetScene(picking_sheet())

    def at(x, y, **kw):
        return scene.owner_at(scene.to_scene((x, y)), **kw)

    assert at(50.0, 25.0) == "d-1"  # on both lines: the dimension is on top
    assert at(20.0, 25.0) == "v-1"
    assert at(20.0, 25.8) == "v-1"  # within a millimetre of the line's edge
    assert at(20.0, 25.8, tolerance=0.2) == ""
    assert at(72.0, 31.0) == "d-2" and at(22.0, 36.0) == "n-1" and at(85.0, 7.0) == "logo"
    assert at(50.0, 45.0) == ""
    # a dragged item is picked where it is drawn now
    scene.item("d-1").setPos(QPointF(0.0, -10.0))
    assert at(50.0, 35.0) == "d-1" and at(50.0, 25.0) == "v-1"
    assert scene.to_scene((10.0, 20.0)) == QPointF(10.0, 30.0)
    assert scene.to_sheet(QPointF(10.0, 30.0)) == (10.0, 20.0)
    # on a drawing: a dimension's text, a frame's cell, the title block, empty paper
    sheet = o11.sheet
    drawn = ds.SheetScene(sheet)
    for owner in ("d-2", "d-1-frame", "title", "n-2"):
        assert drawn.owner_at(drawn.to_scene(text_centre(sheet, owner))) == owner
    assert drawn.owner_at(drawn.to_scene((240.0, 120.0))) == ""


def test_the_view_picks_within_a_few_of_its_pixels_at_any_zoom(ds):
    scene = ds.SheetScene(picking_sheet())
    view = ds.SheetView(scene)
    view.resize(1000, 750)
    view.show()
    QApplication.processEvents()
    for _zoom in range(2):
        line = view.mapFromScene(scene.to_scene((20.0, 25.0)))
        edge = 0.25 * view.scale_px_per_mm()  # the line is 0.5 mm wide
        for pixels, owner in ((4, "v-1"), (9, ""), (-4, "v-1"), (-9, "")):
            off = round(edge + abs(pixels)) * (1 if pixels > 0 else -1)
            mouse(view, QEvent.Type.MouseMove, line + QPoint(0, off))
            assert scene.hover == owner, (pixels, view.scale_px_per_mm())
        view.zoom(4.0, QPointF(line))
    assert view.scale_px_per_mm() > 30.0  # 9 pixels are a quarter of a millimetre here
    view.close()


def test_the_owners_of_a_feature_are_its_dimensions_and_their_frames(ds, o11):
    scene = ds.SheetScene(o11.sheet)
    by_feature: dict[str, list[str]] = {}
    for a in o11.sheet.annotations:
        if isinstance(a, D.Dimension):
            for ref in a.refs:
                by_feature.setdefault(ref, []).append(a.id)
    assert by_feature["f-1"]  # the hole: its size, its locations
    for feature, dims in by_feature.items():
        want = [o for o in scene.owners() if o in dims or (o.endswith("-frame") and o[:-6] in dims)]
        assert scene.owners_of_feature(feature) == tuple(want)
    assert "d-1-frame" in scene.owners_of_feature("f-1")
    assert scene.owners_of_feature("f-999") == ()


def test_the_thumbnail_shows_the_sheet_with_the_stamp_in_red(ds, o11):
    sheet = o11.sheet
    scene = ds.SheetScene(sheet)
    png = scene.render_png(800)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    img = QImage.fromData(png)
    assert (img.width(), img.height()) == (800, round(800 * sheet.height / sheet.width))
    assert dark(img, step=2) > 1000
    red = [
        (x, y)
        for y in range(img.height())
        for x in range(img.width())
        if (c := QColor(img.pixel(x, y))).red() > 150 and c.green() < 90 and c.blue() < 90
    ]
    assert len(red) > 50
    stamp = next(a for a in sheet.annotations if isinstance(a, D.Stamp))
    top = (sheet.height - stamp.at[1]) * 800 / sheet.width  # the stamp's baseline, in pixels
    assert all(y <= top + 2 for _x, y in red)
    # a thumbnail is the sheet's own colours: no hover, selection or highlight
    scene.select(scene.owners())
    scene.highlight(["d-2"], "#00a000")
    scene.set_hover("d-3")
    assert scene.render_png(800) == png
    for bad in (0, -5, ds.MAX_RENDER_PX + 1, 1.5, True, "800"):
        with pytest.raises(InvalidArgumentError):
            scene.render_png(bad)
    with pytest.raises(InvalidArgumentError):
        ds.SheetScene().render_png(100)


# --------------------------------------------------------------------------- speed


def test_the_hundred_hole_plate_paints_and_updates_quickly(ds, plate_sheet):
    sheet = plate_sheet
    dims = [a for a in sheet.annotations if isinstance(a, D.Dimension)]
    assert len(dims) >= 190 and len(sheet.painted) > 1000
    t0 = time.perf_counter()
    scene = ds.SheetScene(sheet)
    built = time.perf_counter() - t0
    view = ds.SheetView(scene)
    view.resize(1600, 1000)
    t1 = time.perf_counter()
    view.show()
    shown = view.viewport().grab()
    painted = time.perf_counter() - t1
    assert not shown.isNull() and view.mapToScene(view.viewport().rect()).boundingRect().contains(
        scene.sceneRect()
    )
    assert built + painted < 0.5, f"built in {built:.3f} s, painted in {painted:.3f} s"

    # as the editor gets sheets: read from the drawing's compact form, every item a new object
    owner = dims[len(dims) // 2].id
    first = D.from_compact(D.to_compact(sheet))
    again = D.from_compact(D.to_compact(shifted(sheet, owner, 2.0, 1.0)))
    best = math.inf
    for _ in range(3):  # back and forth, the best of three
        scene.set_sheet(first)
        t2 = time.perf_counter()
        rebuilt = scene.set_sheet(again)
        best = min(best, time.perf_counter() - t2)
        assert rebuilt == (owner,)
    assert best < 0.1, f"set_sheet took {best:.3f} s"
    print(
        f"\n100-hole plate: {len(dims)} dimensions, {len(sheet.painted)} painted items, "
        f"{len(scene.owners())} owners; built in {built * 1000:.0f} ms, painted at 1600 x 1000 "
        f"in {painted * 1000:.0f} ms; set_sheet after one dimension moved {best * 1000:.1f} ms"
    )
    view.close()


# --------------------------------------------------------------------------- the view


def test_a_drawing_of_o11_is_shown_whole(ds, o11):
    sheet = o11.sheet
    scene = ds.SheetScene(sheet)
    view = ds.SheetView(scene)
    view.resize(900, 700)
    view.show()
    QApplication.processEvents()
    paper = QRectF(0.0, 0.0, sheet.width, sheet.height)
    vp = view.viewport().rect()

    def whole():
        seen = view.mapToScene(vp).boundingRect()
        s = view.scale_px_per_mm()
        fills = paper.width() * s >= 0.9 * vp.width() or paper.height() * s >= 0.9 * vp.height()
        return seen.contains(paper) and fills

    assert view.fitted and whole()
    assert view.renderHints() & QPainter.RenderHint.Antialiasing
    img = view.viewport().grab().toImage()
    page = view.palette().color(QPalette.ColorRole.Window)
    corner = QColor(img.pixel(1, 1))
    assert (corner.red(), corner.green(), corner.blue()) == (page.red(), page.green(), page.blue())
    middle = view.mapFromScene(scene.to_scene((240.0, 120.0)))  # empty paper
    assert QColor(img.pixel(middle)).lightness() == 255
    shadow = view.mapFromScene(QPointF(sheet.width * 0.5, sheet.height)) + QPoint(0, 2)
    assert QColor(img.pixel(shadow)).lightness() < page.lightness()
    assert dark(img, step=2) > 500

    # resized while fitted: fitted again
    view.resize(600, 900)
    QApplication.processEvents()
    vp = view.viewport().rect()
    assert whole()

    # the wheel zooms about the pointer
    at = QPoint(200, 300)
    under = view.mapToScene(at)
    s0 = view.scale_px_per_mm()
    wheel = QWheelEvent(
        QPointF(at),
        QPointF(view.viewport().mapToGlobal(at)),
        QPoint(),
        QPoint(0, 120),
        NONE,
        NO_KEYS,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(view.viewport(), wheel)
    assert view.scale_px_per_mm() == pytest.approx(s0 * 1.25)
    moved = view.mapFromScene(under) - at
    assert abs(moved.x()) <= 1 and abs(moved.y()) <= 1
    assert not view.fitted
    view.resize(700, 900)  # no longer fitted: a resize keeps the zoom
    QApplication.processEvents()
    assert view.scale_px_per_mm() == pytest.approx(s0 * 1.25)

    # the middle button pans: the sheet point under the pointer follows it
    start = QPoint(300, 400)
    held = view.mapToScene(start)
    mouse(view, QEvent.Type.MouseButtonPress, start, MIDDLE, MIDDLE)
    mouse(view, QEvent.Type.MouseMove, start + QPoint(40, 25), NONE, MIDDLE)
    mouse(view, QEvent.Type.MouseButtonRelease, start + QPoint(40, 25), MIDDLE, NONE)
    after = view.mapFromScene(held)
    assert abs(after.x() - 340) <= 1 and abs(after.y() - 425) <= 1

    # zooming stops short of losing the sheet, and fit brings it all back
    for _ in range(40):
        view.zoom(0.5)
    vp = view.viewport().rect()
    assert view.scale_px_per_mm() == pytest.approx(
        ds.ZOOM_OUT * min(vp.width() / view._fit_rect().width(), vp.height() / view._fit_rect().height())
    )
    view.fit()
    assert view.fitted and whole()
    # a new sheet of another size is fitted too
    scene.set_sheet(dataclasses.replace(sheet, width=431.8, height=279.4))
    paper = QRectF(0.0, 0.0, 431.8, 279.4)
    assert whole()
    view.close()
