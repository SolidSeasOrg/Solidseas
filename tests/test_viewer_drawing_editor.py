"""The drawing editor (``solidseas_app.viewer.drawingeditor``; ``docs/DRAWINGS.md`` 15.4).

The editor runs for real, offscreen, on a real :class:`DrawingWorker`: drawings of
copies of o02 (as ``bracket.SLDPRT``) and o11 (as ``plate.SLDPRT``) under fictional
names in temporary folders, opened from their ``.ssdrw``, edited, saved, exported,
signed, released, revised and updated from a copy of o07. Add Dimension needs a part
with holes to measure between: the tests' worker starts its children with a stand-in
for the source and model stages that reads a part named ``FOUR-HOLES.SLDPRT`` as the
synthetic four-holes plate of ``tests/drawing_parts.py`` (every other stage is the
real one), so no fixture is needed for it.

Every question the editor asks goes to a stand-in the test sets (an unexpected one
fails the test), Email PDF's system calls are stand-ins that start nothing, and the
children run under an audit hook: the last test checks that the children wrote
nothing at all and the window's side nothing outside pytest's temporary folders.
Skipped without PySide6.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

try:
    import PySide6.QtWidgets  # noqa: F401
except ImportError:  # the window's tests need the [app] extra
    pytest.skip("PySide6 is not installed: the drawing editor is not tested", allow_module_level=True)

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtWidgets import QApplication, QGraphicsSceneMouseEvent

from pdf_reader import PdfDocument
from solidseas.drawing import DrawingOptions, document
from solidseas.drawing import display as D
from solidseas.drawing import settings as S
from solidseas.errors import ModelNotFoundError
from solidseas_app.viewer import drawingproc, mail
from solidseas_app.viewer.drawingproc import DrawingWorker
from support import fixture_path

TODAY = "2026-10-04"
FIELDS = {"number": "SS-1", "drawn_by": "Ann Bee", "material": "6061-T6", "finish": "None"}
PLATE = "FOUR-HOLES.SLDPRT"
AUDIT_ENV = "SOLIDSEAS_TEST_DRAWINGEDITOR_AUDIT"
LEFT, NONE = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


def people(**files):
    """Drawing Settings of the fictional Example Engineering Co., with two people."""
    s = S.with_value(S.DrawingSettings(), "company", "name", "Example Engineering Co.")
    s = S.with_value(
        s, "people", "people", [{"name": "Ann Bee", "initials": "AB"}, {"name": "Carl Dee", "initials": "CD"}]
    )
    for key, value in files.items():
        s = S.with_value(s, "files", key, value)
    return S.with_value(s, "email", "method", "webmail")


# --------------------------------------------------------------------------- the children
def _writes(event: str, args: tuple) -> list[str]:
    """The paths an audit event writes: a file opened for writing, a rename, a folder
    made, a file removed or truncated (Python's bytecode cache aside)."""
    paths = []
    if event == "open" and len(args) >= 3:
        path, mode, flags = args[0], args[1], args[2]
        writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & _WRITE_FLAGS
        )
        if writing and isinstance(path, (str, bytes, os.PathLike)):
            paths.append(os.path.abspath(os.fsdecode(path)))
    elif event in ("os.rename", "os.replace", "os.remove", "os.mkdir", "os.truncate", "os.rmdir") and args:
        for p in args[:2] if event in ("os.rename", "os.replace") else args[:1]:
            if isinstance(p, (str, bytes, os.PathLike)):
                paths.append(os.path.abspath(os.fsdecode(p)))
    return [p for p in paths if "__pycache__" not in Path(p).parts]


class PlateSource:
    """The source stage's answer for ``FOUR-HOLES.SLDPRT``: a part with no properties
    whose hashes are fixed, so the drawing's model is always this one."""

    name = PLATE
    configuration = None
    format = "sldprt"
    material = None
    sha256 = "ab" * 32
    geometry_digest = "cd" * 32
    properties_digest = None
    units = None
    warnings = ()
    hints = ()
    properties = ()

    def property(self, *names):
        return None

    def selected_bodies(self):
        return []


def serve(conn) -> None:
    """The child of the tests' worker: the real one, under an audit hook appending every
    write it sees to the file :data:`AUDIT_ENV` names, reading ``FOUR-HOLES.SLDPRT`` as
    the synthetic four-holes plate."""
    target = os.environ.get(AUDIT_ENV)
    if target:
        log = open(target, "a", encoding="utf-8")  # noqa: SIM115 - held for the child's life

        def hook(event: str, args: tuple) -> None:
            for p in _writes(event, args):
                log.write(f"{event} {p}\n")
                log.flush()

        sys.addaudithook(hook)
        log.write("audited\n")
        log.flush()
    import drawing_parts as P
    from solidseas.drawing import facegraph, source

    real_open, real_model = source.open_source, facegraph.from_bodies
    plate: list = []

    def open_source(part, **kw):
        if isinstance(part, (str, os.PathLike)) and os.path.basename(os.fspath(part)) == PLATE:
            return PlateSource()
        return real_open(part, **kw)

    def from_bodies(bodies, name=None, **kw):
        if name == PLATE:
            if not plate:
                plate.append(facegraph.from_transmit(P.four_holes_plate()[0]))
            return plate[0]
        return real_model(bodies, name=name, **kw)

    source.open_source, facegraph.from_bodies = open_source, from_bodies
    drawingproc._serve(conn)


@dataclass
class Place:
    root: Path
    parts: Path
    log: Path
    worker: DrawingWorker
    made: dict


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from solidseas_app.viewer.app import use_system_fonts

    use_system_fonts()
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def place(app, tmp_path_factory):
    """The parts (copies under fictional names), the worker the tests share, and the
    drawings it made of them, as ``.ssdrw`` bytes."""
    root = tmp_path_factory.mktemp("drawingeditor")
    parts = root / "parts"
    parts.mkdir()
    for fixture, name in (
        ("o02_boxA.SLDPRT", "bracket.SLDPRT"),
        ("o07_boxB_h31.SLDPRT", "bracket taller.SLDPRT"),
        ("o11_curved.SLDPRT", "plate.SLDPRT"),
    ):
        shutil.copyfile(fixture_path(fixture), parts / name)
    log = root / "writes.log"
    log.write_text("", encoding="utf-8")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv(AUDIT_ENV, str(log))  # every child the worker starts audits itself
        worker = DrawingWorker(serve=serve)
        try:
            made = {
                "bracket": worker.make(parts / "bracket.SLDPRT", fields=FIELDS, settings=people()).data,
                "plate": worker.make(
                    parts / "plate.SLDPRT", DrawingOptions(units="mm"), {**FIELDS, "number": "SS-2"}, people()
                ).data,
                "holes": worker.make(
                    parts / PLATE, DrawingOptions(units="mm"), {**FIELDS, "number": "SS-3"}, people()
                ).data,
            }
            yield Place(root, parts, log, worker, made)
        finally:
            worker.close()


PARTS = {"bracket": "bracket.SLDPRT", "plate": "plate.SLDPRT", "holes": None}
NUMBERS = {"bracket": "SS-1", "plate": "SS-2", "holes": "SS-3"}


def drawing_file(place: Place, folder: Path, which: str = "bracket") -> Path:
    """The drawing ``which`` saved in ``folder``, beside a copy of its part."""
    part = PARTS[which]
    if part is not None:
        shutil.copyfile(place.parts / part, folder / part)
    path = folder / f"{NUMBERS[which]}.ssdrw"
    path.write_bytes(place.made[which])
    return path


class Said:
    """The stand-ins for what the editor asks: each answers from a list the test gives,
    and anything asked without an answer fails the test."""

    def __init__(self, editor) -> None:
        self.told: list[tuple[str, str]] = []
        self.asked: list[str] = []
        self.answers: dict[str, list] = {}
        for name in ("ask_save_path", "ask_folder", "ask_model_path", "ask_question", "run_dialog"):
            setattr(editor, name, self._answer(name))
        editor.ask_close = lambda: "discard"
        editor.tell = lambda title, text: self.told.append((title, text))

    def _answer(self, name: str):
        def answer(*args):
            self.asked.append(name)
            queue = self.answers.get(name)
            if not queue:
                raise AssertionError(f"the editor asked {name}{args} with no answer given")
            got = queue.pop(0)
            return got(*args) if callable(got) else got

        return answer

    def give(self, name: str, *values) -> None:
        self.answers.setdefault(name, []).extend(values)


@pytest.fixture
def opened(place):
    """``opened(path, settings=...)``: an editor on ``path``, its first steps done, its
    questions answered by a :class:`Said`; every editor is closed after the test."""
    from solidseas_app.viewer.drawingeditor import DrawingEditor

    editors = []

    def make(path, settings=None, **kw):
        editor = DrawingEditor(
            place.worker,
            path,
            settings=settings or people(),
            settings_path=Path(path).parent / "Drawing.json",
        )
        said = Said(editor)
        editors.append(editor)
        assert editor.wait(), "the editor did not finish opening"
        return editor, said

    yield make
    for editor in editors:
        editor.close()
        editor.deleteLater()
    QApplication.processEvents()


def dim(editor, ident):
    return editor.dimension(ident)


def annotation(editor, ident):
    return next(a for a in editor.drawing.sheet.annotations if isinstance(a, D.Dimension) and a.id == ident)


def send(scene, kind, pos, buttons=NONE, button=NONE):
    ev = QGraphicsSceneMouseEvent(kind)
    ev.setScenePos(QPointF(pos))
    ev.setButtons(buttons)
    ev.setButton(button)
    QApplication.sendEvent(scene, ev)


def click(editor, ident):
    """A click on a dimension's text on the sheet."""
    at = editor.scene.to_scene(annotation(editor, ident).text_at)
    send(editor.scene, QEvent.Type.GraphicsSceneMouseMove, at)
    send(editor.scene, QEvent.Type.GraphicsSceneMousePress, at, LEFT, LEFT)
    send(editor.scene, QEvent.Type.GraphicsSceneMouseRelease, at, NONE, LEFT)


def tree_item(editor, ident):
    item = editor._dimension_item(ident)
    assert item is not None, ident
    return item


def done(editor):
    assert editor.wait(), "the editor did not finish"
    return editor.drawing


# --------------------------------------------------------------------------- words (no child)
def test_the_words_of_a_dimension_and_a_drop():
    from solidseas_app.viewer import drawingeditor as E

    horizontal = D.Dimension(
        "d-1", "linear", "v-1", ((0, 10), (20, 10), (0, 20)), (10, 20), 0.02, D.DimText("20")
    )
    assert E.placement_delta(horizontal, 5.0, 3.0) == (5.0, 3.0)  # above its view: up is away from it
    below = D.Dimension("d-1", "linear", "v-1", ((0, 10), (20, 10), (0, 2)), (10, 2), 0.02, D.DimText("20"))
    assert E.placement_delta(below, 5.0, 3.0) == (5.0, -3.0)
    left = D.Dimension(
        "d-1", "linear", "v-1", ((10, 0), (10, 20), (2, 0)), (2, 10), 0.02, D.DimText("20"), 90.0
    )
    assert E.placement_delta(left, 5.0, 3.0) == (3.0, -5.0)  # vertical: along is up, across is left
    leader = D.Dimension("d-1", "hole_callout", "v-1", ((0, 0), (5, 5)), (5, 5), 0.01, D.DimText("10"))
    assert E.placement_delta(leader, 5.0, 3.0) == (5.0, 3.0)

    class Check:
        def __init__(self, level, code):
            self.level, self.code = level, code

    assert E.blocks_release(Check("error", "R4.complete"))
    assert E.blocks_release(Check("warning", "COV.unclaimed"))
    assert E.blocks_release(Check("information", "R6.signatures"))
    assert not E.blocks_release(Check("warning", "R9.lines"))


# --------------------------------------------------------------------------- opening and the lists
def test_opening_shows_the_sheet_the_lists_and_the_model(place, opened, tmp_path):
    from solidseas_app.viewer import drawingeditor as E

    editor, said = opened(drawing_file(place, tmp_path))
    d = editor.drawing
    assert d.status == "PRELIMINARY" and editor.model_state == "unchanged" and editor.editable
    assert editor.model_button.text() == E.MODEL_UNCHANGED and not editor.model_button.isEnabled()
    assert editor.status_label.text() == "PRELIMINARY, revision A"
    assert editor.windowTitle().startswith("SS-1.ssdrw") and not editor.isWindowModified()
    menus = [a.text() for a in editor.menuBar().actions()]
    assert "&Drawing (Experimental)" in menus, menus
    assert set(editor.scene.owners()) >= {"d-1", "d-2", "d-3", "title", "stamp"}
    groups = [editor.dimensions.topLevelItem(i).text(0) for i in range(editor.dimensions.topLevelItemCount())]
    assert groups == ["Front view", "Top view"]
    item = tree_item(editor, "d-1")
    assert item.checkState(0) == Qt.CheckState.Checked and item.text(1) == "linear"
    assert item.text(0) == "d-1  10.0" and item.text(2).startswith("±")
    assert editor.checks.topLevelItemCount() == len(d.checks) > 0
    blocking = [editor.checks.topLevelItem(i).text(2) for i in range(editor.checks.topLevelItemCount())]
    assert "blocks release" in blocking  # the signatures Release needs
    # a check selects what it is about and offers its fixes
    row = next(
        i
        for i in range(editor.checks.topLevelItemCount())
        if editor.checks.topLevelItem(i).text(1) == "R6.signatures"
    )
    editor.checks.topLevelItem(row).setSelected(True)
    fixes = [editor.fixes_layout.itemAt(i).widget() for i in range(editor.fixes_layout.count())]
    assert [w.text() for w in fixes if w is not None] == ["Sign..."]
    # the title fields when nothing is selected, a dimension's properties when one is
    assert editor.properties.title_fields["number"].text() == "SS-1"
    click(editor, "d-3")
    assert editor.selected == "d-3" and editor.scene.selected() == ("d-3",)
    assert editor.properties.measured.text() == "30.0000 mm" and editor.properties.band.text().startswith("±")
    assert said.asked == []


# --------------------------------------------------------------------------- edits and undo
def test_remove_restore_undo_and_redo(place, opened, tmp_path):
    editor, _said = opened(drawing_file(place, tmp_path))
    tree_item(editor, "d-1").setCheckState(0, Qt.CheckState.Unchecked)  # the tick box removes
    d = done(editor)
    assert dim(editor, "d-1").state == "removed" and "d-1" not in editor.scene.owners()
    assert tree_item(editor, "d-1").checkState(0) == Qt.CheckState.Unchecked
    assert editor.undo_stack.count() == 1 and editor.isWindowModified()
    editor.undo()
    assert dim(editor, "d-1").state == "shown" and "d-1" in editor.scene.owners()
    assert not editor.isWindowModified()
    editor.redo()
    assert editor.drawing is d and dim(editor, "d-1").state == "removed"
    tree_item(editor, "d-1").setCheckState(0, Qt.CheckState.Checked)  # ticked again: restored
    done(editor)
    assert dim(editor, "d-1").state == "shown" and editor.undo_stack.count() == 2
    assert editor.last_message == "Restore d-1"


def test_a_dimension_dragged_on_the_sheet_is_moved(place, opened, tmp_path):
    editor, _said = opened(drawing_file(place, tmp_path))
    ann = annotation(editor, "d-2")
    assert ann.angle_deg == 90.0 and ann.points[2][0] > ann.points[0][0]  # vertical, right of its view
    at = editor.scene.to_scene(ann.text_at)
    scene = editor.scene
    send(scene, QEvent.Type.GraphicsSceneMouseMove, at)
    send(scene, QEvent.Type.GraphicsSceneMousePress, at, LEFT, LEFT)
    send(scene, QEvent.Type.GraphicsSceneMouseMove, at + QPointF(5.0, -3.0), LEFT, LEFT)
    send(scene, QEvent.Type.GraphicsSceneMouseRelease, at + QPointF(5.0, -3.0), NONE, LEFT)
    done(editor)
    p = dim(editor, "d-2").placement
    assert p.moved and (p.along_mm, p.across_mm) == (3.0, 5.0)  # up the sheet is along, right is away
    moved = annotation(editor, "d-2")
    assert moved.text_at[0] > ann.text_at[0] + 4.0 and moved.text_at[1] > ann.text_at[1] + 2.0
    # two more drags in quick succession: each adds to the one before
    editor.scene.moved.emit("d-2", 1.0, 0.0)
    editor.scene.moved.emit("d-2", 0.0, 2.0)
    done(editor)
    p = dim(editor, "d-2").placement
    assert (p.along_mm, p.across_mm) == (5.0, 6.0) and editor.undo_stack.count() == 3
    editor.reset_position("d-2")
    done(editor)
    assert dim(editor, "d-2").placement is None or not dim(editor, "d-2").placement.moved


def test_property_changes_go_through_the_panel(place, opened, tmp_path):
    editor, _said = opened(drawing_file(place, tmp_path))
    panel = editor.properties
    editor.select("d-1")
    band = panel.band.text()
    panel.precision.setCurrentIndex(panel.precision.findData(3))
    panel.precision.activated.emit(panel.precision.currentIndex())
    done(editor)
    d = dim(editor, "d-1")
    assert d.places == 3 and d.places_source == "user" and panel.band.text() != band
    panel.prefix.setText("2X")
    panel.suffix.setPlainText("TYP")
    panel._apply_text()
    done(editor)
    d = dim(editor, "d-1")
    assert d.prefix == "2X" and d.suffix == ("TYP",) and editor.undo_stack.count() == 2
    assert tree_item(editor, "d-1").text(0).startswith("d-1  2X")
    panel.override.setText("10.5")
    editor.override_value("d-1", panel.override.text())
    done(editor)
    assert dim(editor, "d-1").override == "10.5" and "overridden" in tree_item(editor, "d-1").text(3)
    assert any(c.code == "R2.override" for c in editor.drawing.checks)
    panel.tolerance.setCurrentIndex(panel.tolerance.findData("basic"))
    panel._apply_tolerance()
    done(editor)
    assert dim(editor, "d-1").tolerance == "basic" and "basic" in tree_item(editor, "d-1").text(3)
    panel.characteristic.setCurrentIndex(panel.characteristic.findData("position"))
    panel.zone.setValue(0.1)
    panel.diameter.setChecked(True)
    panel.datums[0].setCurrentIndex(panel.datums[0].findData("A"))
    panel._apply_frame()
    done(editor)
    frame = dim(editor, "d-1").frame
    assert frame.characteristic == "position" and frame.datums == ("A",) and abs(frame.value - 0.0001) < 1e-12
    # a note's text, and the title block
    editor.select("n-2")
    assert panel.pages.currentIndex() == 1
    panel.note.setPlainText("REMOVE ALL BURRS")
    editor.set_note("n-2", panel.note.toPlainText())
    done(editor)
    edited = [n for _nid, n in editor.drawing.notes if n.text == "REMOVE ALL BURRS"]
    assert len(edited) == 1 and edited[0].origin == "user"  # an edited note is the user's
    editor.select("")
    panel.title_fields["title"].setText("BRACKET, MOTOR MOUNT")
    panel._apply_title()
    done(editor)
    assert document.title_text(editor.drawing, "title") == "BRACKET, MOTOR MOUNT"
    count = editor.undo_stack.count()
    for _k in range(count):
        editor.undo()
    assert dim(editor, "d-1").places_source == "role" and dim(editor, "d-1").override is None


# --------------------------------------------------------------------------- an assembly
def test_an_assembly_drawing_has_its_parts_list_and_no_dimension_actions(place, opened, tmp_path):
    from solidseas_app.viewer import drawingeditor as E

    for name in ("o15_sub_asm.SLDASM", "o02_boxA.SLDPRT", "o07_boxB_h31.SLDPRT"):
        shutil.copyfile(fixture_path(name), tmp_path / name)  # the assembly beside its parts
    fields = {"number": "SS-7", "drawn_by": "Ann Bee"}
    path = tmp_path / "SS-7.ssdrw"
    path.write_bytes(
        place.worker.make(tmp_path / "o15_sub_asm.SLDASM", fields=fields, settings=people()).data
    )
    editor, said = opened(path)
    assert editor.model_state == "unchanged" and editor.editable
    assert {"parts", "balloon-1", "balloon-2", "title"} <= set(editor.scene.owners())
    listed = editor.dimensions
    shown = sum(listed.topLevelItem(i).childCount() for i in range(listed.topLevelItemCount()))
    assert shown == 3, "the overall size, for reference"
    a = editor.actions_by_name
    for key in ("add", "remove", "reset", "block"):
        assert not a[key].isEnabled() and a[key].toolTip() == E.NO_DIMENSIONS
    assert a["notes"].isEnabled() and a["sign"].isEnabled() and a["release"].isEnabled()
    # a balloon dragged: it moves there as one undoable step, its leader following
    balloon = next(x for x in editor.drawing.sheet.annotations if isinstance(x, D.Balloon))
    at = editor.scene.to_scene(balloon.centre)
    send(editor.scene, QEvent.Type.GraphicsSceneMousePress, at, LEFT, LEFT)
    send(editor.scene, QEvent.Type.GraphicsSceneMouseMove, at + QPointF(30, 30), LEFT)
    send(editor.scene, QEvent.Type.GraphicsSceneMouseRelease, at + QPointF(30, 30), NONE, LEFT)
    d = done(editor)
    assert editor.selected == "" and editor.undo_stack.count() == 1
    moved = next(x for x in d.sheet.annotations if isinstance(x, D.Balloon) and x.item == balloon.item)
    assert moved.centre != balloon.centre and moved.leader[0] == balloon.leader[0]
    assert [e[0] for e in d.options.balloons] == [balloon.item]
    editor.undo_stack.undo()
    d = done(editor)
    assert d.options.balloons == () and editor.undo_stack.count() == 1
    # the title, as for a part, keeps the parts list
    editor.properties.title_fields["title"].setText("FRAME, WELDED")
    editor.properties._apply_title()
    d = done(editor)
    assert document.title_text(d, "title") == "FRAME, WELDED"
    assert [len(x.rows) for x in d.sheet.annotations if isinstance(x, D.PartsList)] == [2]
    assert not [c for c in d.checks if c.level == "error" and c.code != "R6.signatures"]
    assert said.asked == []
    # Edit Parts List: the BOM editor on the model's BOMs; Apply is one undoable step
    assert a["parts"].isEnabled()
    editor.edit_parts_list()
    done(editor)
    bom = editor.parts_editor
    assert bom.apply_to_drawing and bom.table.rowCount() == 2
    assert [bom.table.horizontalHeaderItem(c).text() for c in range(bom.table.columnCount())][2] == "DWG NO."
    bom.table.selectRow(0)
    bom.hide_row()
    bom.table.item(0, 3).setText("Corner bracket")
    bom.apply()
    d = done(editor)
    (parts,) = [x for x in d.sheet.annotations if isinstance(x, D.PartsList)]
    assert len(parts.rows) == 1 and parts.rows[0][0] == "1" and parts.rows[0][3] == "CORNER BRACKET"
    assert d.options.parts_list is not None and editor.undo_stack.count() == 2
    editor.undo()
    d = done(editor)
    assert d.options.parts_list is None and [
        len(x.rows) for x in d.sheet.annotations if isinstance(x, D.PartsList)
    ] == [2]
    bom.undo_stack.setClean()
    bom.close()


# --------------------------------------------------------------------------- Add Dimension
def test_add_dimension_on_the_four_holes_plate(place, opened, tmp_path):
    from solidseas_app.viewer import drawingeditor as E

    path = drawing_file(place, tmp_path, "holes")
    editor, said = opened(path)
    # nothing in the drawing's folder is its model: view-only, and Find... chooses it
    assert editor.model_state == "missing" and editor.model_button.text() == E.MODEL_NOT_FOUND
    assert "(view-only)" in editor.windowTitle() and not editor.editable
    editor.remove("d-2")
    assert not editor.busy and editor.last_message == E.VIEW_ONLY
    (tmp_path / "model").mkdir()
    part = tmp_path / "model" / PLATE
    part.write_bytes(b"read by the child's stand-in for the source stage")
    said.give("ask_model_path", str(part))
    editor.model_button.click()
    done(editor)
    assert editor.model_state == "unchanged" and editor.editable and editor.model_path == str(part)
    editor.toggle_add_dimension(True)
    assert editor.adding and editor.actions_by_name["add"].isChecked()
    click(editor, "d-5")  # the X location of f-1, an ordinate from f-6
    click(editor, "d-6")  # of f-2
    done(editor)
    assert editor.picked == ["f-1", "f-2"]
    assert set(editor.scene.highlighted()) >= set(editor.scene.owners_of_feature("f-1"))
    assert [c.words for c in editor.candidates] == ["25.00 along X", "38.00 along Y"]
    assert editor.add_panel.offered.count() == 2
    editor.add_panel.offered.setCurrentRow(1)
    editor.add_panel._add()
    done(editor)
    added = next(d for d in editor.drawing.dimensions if d.origin == "user")
    assert (
        added.key == "user/distance/f-1/f-2/y" and added.state == "shown" and abs(added.value - 0.038) < 1e-9
    )
    assert editor.picked == [] and editor.candidates == ()
    assert tree_item(editor, added.id).checkState(0) == Qt.CheckState.Checked
    tree_item(editor, added.id).setCheckState(0, Qt.CheckState.Unchecked)  # a user dimension is deleted
    done(editor)
    assert editor.dimension(added.id) is None
    editor.undo()
    assert editor.dimension(added.id) is not None
    editor.toggle_add_dimension(False)
    assert not editor.adding and editor.scene.highlighted() == {}


# --------------------------------------------------------------------------- the model
def test_view_only_without_the_model_then_find(place, opened, tmp_path):
    from solidseas_app.viewer import drawingeditor as E

    path = drawing_file(place, tmp_path)
    (tmp_path / "models").mkdir()
    moved = tmp_path / "models" / "bracket copy.SLDPRT"
    os.replace(tmp_path / "bracket.SLDPRT", moved)
    editor, said = opened(path)
    assert editor.model_state == "missing" and editor.model_button.text() == E.MODEL_NOT_FOUND
    assert editor.drawing.sheet is not None and "d-1" in editor.scene.owners()  # shown from its sheet
    assert editor.drawing.checks  # those the file answers
    assert not editor.actions_by_name["sign"].isEnabled() and editor.actions_by_name["find"].isEnabled()
    editor.sign("CHECKED", "Carl Dee")
    assert editor.last_message == E.VIEW_ONLY and not editor.busy
    said.give("ask_model_path", str(moved))
    editor.find_model()
    done(editor)
    assert editor.model_state == "unchanged" and editor.model_button.text() == E.MODEL_UNCHANGED
    editor.remove("d-1")
    done(editor)
    editor.save()
    done(editor)
    saved = document.read(path).drawing
    assert saved.model["relative"] == "models/bracket copy.SLDPRT" and saved.model["stored"] is None


def test_update_from_model_o02_to_o07_with_the_report(place, opened, tmp_path):
    from solidseas_app.viewer import drawingeditor as E

    path = drawing_file(place, tmp_path)
    editor, said = opened(path)
    a, b = dim(editor, "d-1"), dim(editor, "d-2")
    editor.remove(a.id)
    editor.move(b.id, 3.0, 6.0)
    editor.save()
    done(editor)
    editor.close()
    # the model saved again, taller: the drawing opens view-only with Update Drawing
    shutil.copyfile(place.parts / "bracket taller.SLDPRT", tmp_path / "bracket.SLDPRT")
    editor, said = opened(path)
    assert editor.model_state == "changed" and editor.model_button.text() == E.MODEL_CHANGED
    assert editor.model_path == str(tmp_path / "bracket.SLDPRT") and not editor.editable
    editor.restore(a.id)
    assert editor.last_message == E.VIEW_ONLY_CHANGED and not editor.busy
    editor.model_button.click()  # Update Drawing
    done(editor)
    report = editor.last_report
    assert report.changed >= 1 and report.words().endswith("needs attention")
    assert said.told[-1][0] == "Update from Model" and said.told[-1][1].startswith(report.words())
    assert editor.model_state == "unchanged" and editor.editable
    assert dim(editor, a.id).state == "removed" and dim(editor, b.id).placement.moved
    assert (
        editor.drawing.model["sha256"]
        == hashlib.sha256((tmp_path / "bracket.SLDPRT").read_bytes()).hexdigest()
    )
    assert editor.revision_description().startswith("UPDATED FROM MODEL")
    editor.restore(a.id)  # editable at once
    done(editor)
    assert dim(editor, a.id).state == "shown"
    editor.undo()
    editor.undo()  # back before the update: the drawing records the old model again
    done(editor)
    assert editor.model_state == "changed" and not editor.editable
    editor.redo()
    done(editor)
    assert editor.model_state == "unchanged" and editor.editable


def test_an_idle_model_is_let_go_and_a_lost_one_attached_again(place, opened, tmp_path):
    editor, _said = opened(drawing_file(place, tmp_path))
    editor.idle_ms = 50
    editor.remove("d-1")
    done(editor)
    end = time.monotonic() + 20
    while editor._attached and time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)
    assert not editor._attached  # the child let go of it (8.12)
    with pytest.raises(ModelNotFoundError):
        place.worker.edit(editor.drawing, "restore", ["d-1"])
    editor.idle_ms = 3_600_000
    editor.restore("d-1")  # attached again first
    done(editor)
    assert dim(editor, "d-1").state == "shown" and editor._attached
    # a child started again has no model: the edit is answered model_not_found, attached and asked again
    started = place.worker.started
    place.worker._proc.kill()
    place.worker._proc.join(5)
    editor.remove("d-1")
    done(editor)
    assert dim(editor, "d-1").state == "removed" and place.worker.started == started + 1


# --------------------------------------------------------------------------- signing, release, revisions
def test_sign_release_refused_then_allowed_and_start_revision(place, opened, tmp_path):
    from solidseas_app.viewer import drawingeditor as E

    path = drawing_file(place, tmp_path)
    editor, said = opened(path)
    editor.release({}, today=TODAY)
    done(editor)
    assert "CHECKED is not signed" in editor.release_reasons and editor.drawing.status == "PRELIMINARY"
    assert said.told[-1][0] == "Release refused" and "APPROVED is not signed" in said.told[-1][1]
    editor.sign("CHECKED", "Carl Dee", today=TODAY)
    done(editor)
    assert editor.drawing.status == "CHECKED" and editor.status_label.text() == "CHECKED, revision A"

    def approve(dialog):  # Sign... through its dialog
        row, person = dialog.fields["row"], dialog.fields["person"]
        assert [row.itemData(i) for i in range(row.count())] == ["APPROVED"]  # the rows not yet signed
        person.setCurrentIndex(person.findData("Ann Bee"))
        return True

    said.give("run_dialog", approve, True)  # then Release...'s dialog: nothing to accept on this part
    editor.sign()
    done(editor)
    assert [s.row for s in editor.drawing.signatures] == ["DRAWN", "CHECKED", "APPROVED"]
    editor.release()
    done(editor)
    d = editor.drawing
    assert d.status == "RELEASED" and editor.release_reasons == ()
    assert d.revisions[-1].date is not None and d.revisions[-1].approved == "Ann Bee"
    pdf, dxf = tmp_path / "SS-1 A.pdf", tmp_path / "SS-1 A.dxf"
    assert (
        pdf.is_file()
        and dxf.is_file()
        and "PRELIMINARY" not in " ".join(r.text for r in PdfDocument(pdf.read_bytes()).text_runs())
    )
    assert {(o.name, o.released) for o in d.outputs} == {("SS-1 A.pdf", True), ("SS-1 A.dxf", True)}
    assert document.read(path).drawing.status == "RELEASED" and not editor.isWindowModified()
    assert (
        editor.undo_stack.count() == 0
        and not editor.editable
        and "(RELEASED, read-only)" in editor.windowTitle()
    )
    editor.remove("d-1")
    assert editor.last_message == E.READ_ONLY and not editor.busy
    assert editor.actions_by_name["revision"].isEnabled() and not editor.actions_by_name["update"].isEnabled()
    # a released export is never replaced: Export writes a new name
    released = pdf.read_bytes()
    editor.export_pdf(tmp_path)
    done(editor)
    assert pdf.read_bytes() == released and (tmp_path / "SS-1 A (2).pdf").is_file()
    editor.start_revision("HEIGHT CHANGED", today=TODAY)
    done(editor)
    d = editor.drawing
    assert d.status == "PRELIMINARY" and [r.rev for r in d.revisions] == ["A", "B"]
    assert [s.row for s in d.signatures] == ["DRAWN"] and editor.editable
    assert editor.status_label.text() == "PRELIMINARY, revision B"
    assert pdf.read_bytes() == released


def test_a_released_drawing_whose_model_changed_is_revised_with_it(place, opened, tmp_path):
    path = drawing_file(place, tmp_path)
    editor, said = opened(path)
    editor.sign("CHECKED", "Carl Dee", today=TODAY)
    done(editor)
    editor.sign("APPROVED", "Ann Bee", today=TODAY)
    done(editor)
    editor.release({}, today=TODAY)
    done(editor)
    assert editor.drawing.status == "RELEASED"
    editor.close()
    # the model saved again, taller: Update Drawing starts the next revision with it
    shutil.copyfile(place.parts / "bracket taller.SLDPRT", tmp_path / "bracket.SLDPRT")
    editor, said = opened(path)
    assert editor.drawing.status == "RELEASED" and editor.model_state == "changed" and not editor.editable
    assert editor.actions_by_name["update"].isEnabled() and editor.actions_by_name["revision"].isEnabled()

    def describe(dialog):  # Start Revision's row, asked first
        assert dialog.fields["description"].text() == "UPDATED FROM MODEL"
        dialog.fields["description"].setText("HEIGHT CHANGED")
        return True

    said.give("run_dialog", describe)
    editor.model_button.click()  # Update Drawing
    done(editor)
    d = editor.drawing
    assert d.status == "PRELIMINARY" and [r.rev for r in d.revisions] == ["A", "B"]
    assert d.revisions[-1].description == "HEIGHT CHANGED" and [s.row for s in d.signatures] == ["DRAWN"]
    assert editor.model_state == "unchanged" and editor.editable and editor.last_report.changed >= 1
    assert said.told[-1][0] == "Update from Model"
    assert d.model["sha256"] == hashlib.sha256((tmp_path / "bracket.SLDPRT").read_bytes()).hexdigest()
    assert editor.status_label.text() == "PRELIMINARY, revision B"
    editor.undo()  # one step: back to the released drawing of the old model
    done(editor)
    assert editor.drawing.status == "RELEASED" and editor.model_state == "changed" and not editor.editable
    editor.redo()
    done(editor)
    assert editor.drawing.status == "PRELIMINARY" and editor.editable


def test_release_with_typed_reasons_and_email_of_the_released_pdf(place, opened, tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(mail, "open_in_browser", lambda url: started.append(url))
    monkeypatch.setattr(mail, "open_folder", lambda folder: started.append(folder))
    monkeypatch.setattr(mail, "start_explorer", lambda p: started.append(p))
    path = drawing_file(place, tmp_path, "plate")
    editor, said = opened(path)
    editor.override_value("d-2", "40.5")  # R2.override: an error until accepted with a reason
    editor.set_title({"material": "UNOBTAINIUM 7"})  # not in the materials list
    done(editor)
    assert any(c.code == "R2.override" and c.level == "error" for c in editor.drawing.checks)
    # the signature checks offer Sign... as their fix; the button opens Sign...'s dialog
    row = next(
        i
        for i in range(editor.checks.topLevelItemCount())
        if editor.checks.topLevelItem(i).text(1) == "R6.signatures"
    )
    editor.checks.topLevelItem(row).setSelected(True)
    button = editor.fixes_layout.itemAt(0).widget()
    assert button.text() == "Sign..."

    def checked_by_carl(dialog):
        dialog.fields["row"].setCurrentIndex(dialog.fields["row"].findData("CHECKED"))
        dialog.fields["person"].setCurrentIndex(dialog.fields["person"].findData("Carl Dee"))
        return True

    said.give("run_dialog", checked_by_carl)
    button.click()
    editor.sign("APPROVED", "Ann Bee")
    done(editor)
    editor.release({})  # the override and the material are not accepted yet
    done(editor)
    reasons = " ".join(editor.release_reasons)
    assert "R2.override" in reasons and "map it or accept it as typed" in reasons
    fields = []

    def reasons_typed(dialog):
        fields.extend(dialog.fields)
        for name, box in dialog.fields.items():
            box.setText("CUSTOMER DRAWING 12 SAYS 40.5" if name != "material" else "CUSTOMER SUPPLIES IT")
        return True

    said.give("run_dialog", reasons_typed)
    editor.release()
    done(editor)
    assert "material" in fields and len(fields) == 2  # the override's item and the material
    d = editor.drawing
    assert d.status == "RELEASED" and dict(d.accepted)["material"] == "CUSTOMER SUPPLIES IT"
    # Email PDF of a released drawing: its released PDF, asked nothing
    editor.email_pdf()
    done(editor)
    assert started and started[-1].startswith("https://mail.google.com/") and "SS-2" in started[-1]
    assert editor.last_delivery.route == "webmail"
    if os.name == "nt":  # selected in File Explorer, which the message points to
        assert os.path.basename(started[-2]) == "SS-2 A.pdf" and "the selected PDF" in editor.last_message
    else:  # its folder opened: the message names it
        assert "SS-2 A.pdf" in editor.last_message
    # Start Revision through its dialog, pre-filled and editable
    descriptions = []

    def revised(dialog):
        descriptions.append(dialog.fields["description"].text())
        dialog.fields["description"].setText("MATERIAL CHANGED")
        return True

    said.give("run_dialog", revised)
    editor.start_revision()
    done(editor)
    assert editor.drawing.revisions[-1].description == "MATERIAL CHANGED" and descriptions == [""]


# --------------------------------------------------------------------------- saving (12.6)
def test_save_and_save_again_by_the_hash_rule(place, opened, tmp_path):
    path = drawing_file(place, tmp_path)
    editor, _said = opened(path)
    editor.remove("d-1")
    editor.save()
    done(editor)
    assert editor.path == str(path) and "is replaced by its newer version" in editor.last_message
    assert document.read(path).drawing.dimensions == editor.drawing.dimensions
    first = path.read_bytes()
    editor.remove("d-2")
    editor.save()  # replaces the file it saved: the hash it recorded is the file's
    done(editor)
    assert editor.path == str(path) and path.read_bytes() != first and not editor.isWindowModified()
    editor.undo()  # undo after a save keeps working
    assert dim(editor, "d-2").state == "shown" and editor.isWindowModified()
    editor.save()
    done(editor)
    assert document.read(path).drawing.dimensions == editor.drawing.dimensions
    # changed behind the editor's back: not this drawing's own unchanged file any more
    path.write_bytes(place.made["bracket"])
    editor.remove("d-3")
    editor.save()
    done(editor)
    assert editor.path == str(tmp_path / "SS-1 (2).ssdrw")
    assert "SS-1.ssdrw is taken" in editor.last_message and path.read_bytes() == place.made["bracket"]
    assert document.read(editor.path).drawing.dimensions == editor.drawing.dimensions
    # closing with unsaved changes: Save, then the window closes
    editor.restore("d-3")
    done(editor)
    editor.ask_close = lambda: "save"
    assert not editor.close()  # not yet: the save runs first
    done(editor)
    assert editor._closed and document.read(editor.path).drawing.dimensions == editor.drawing.dimensions


def test_save_with_replace_own_files_off_writes_new_names(place, opened, tmp_path):
    path = drawing_file(place, tmp_path)
    editor, said = opened(path, settings=people(replace_own_files=False))
    editor.remove("d-1")
    editor.save()
    done(editor)
    assert editor.path == str(tmp_path / "SS-1 (2).ssdrw") and path.read_bytes() == place.made["bracket"]
    assert "every save is a new file" in editor.last_message
    editor.save()
    done(editor)
    assert editor.path == str(tmp_path / "SS-1 (3).ssdrw")
    # Save As to a name of the user's, and Save a Copy to Send, which never names a folder
    editor.save_as(tmp_path / "mine")
    done(editor)
    assert editor.path == str(tmp_path / "mine.ssdrw")
    said.give("ask_question", True)
    said.give("ask_save_path", str(tmp_path / "out" / "for the shop.ssdrw"))
    (tmp_path / "out").mkdir()
    editor.save_copy_to_send()
    done(editor)
    sent = document.read(tmp_path / "out" / "for the shop.ssdrw").drawing
    assert sent.model["stored"] is None and sent.model["relative"] is None
    assert editor.path == str(tmp_path / "mine.ssdrw")
    assert said.asked == ["ask_question", "ask_save_path"]


def test_a_refused_folder_opens_save_as_with_the_reason(place, opened, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    path = drawing_file(place, real)
    editor, said = opened(path)
    linked = tmp_path / "linked"
    os.symlink(real, linked, target_is_directory=True)
    titles = []

    def where(title, start):
        titles.append(title)
        return str(real / "elsewhere.ssdrw")

    said.give("ask_save_path", where)
    editor.save_as(linked / "SS-1.ssdrw")  # a folder given that is refused: said, nothing written
    assert "is a link" in editor.last_message and not editor.busy
    editor.path = str(linked / "SS-1.ssdrw")  # as if it were opened through the link
    editor.save()
    done(editor)
    assert "is a link" in titles[0] and editor.path == str(real / "elsewhere.ssdrw")
    assert (real / "elsewhere.ssdrw").is_file()


# --------------------------------------------------------------------------- exports and Email PDF
def test_export_pdf_and_dxf_and_keep_them_current(place, opened, tmp_path):
    path = drawing_file(place, tmp_path)
    editor, said = opened(path)
    editor.export_pdf(tmp_path)
    done(editor)
    pdf = tmp_path / "SS-1 A PRELIMINARY.pdf"
    assert pdf.is_file() and str(PdfDocument(pdf.read_bytes()).info()["Producer"]).startswith("SolidSeas")
    assert editor.isWindowModified()  # the export is recorded in the drawing
    said.give("ask_folder", str(tmp_path))
    editor.export_dxf()
    done(editor)
    dxf = tmp_path / "SS-1 A PRELIMINARY.dxf"
    assert dxf.read_bytes().startswith(b"999")
    assert {o.name for o in editor.drawing.outputs} == {pdf.name, dxf.name}
    editor.save()
    done(editor)
    before = pdf.read_bytes(), dxf.read_bytes()
    editor.remove("d-1")
    editor.save()  # keeps the PRELIMINARY exports up to date
    done(editor)
    assert pdf.read_bytes() != before[0] and dxf.read_bytes() != before[1]
    recorded = {o.name: o.sha256 for o in editor.drawing.outputs}
    assert recorded[pdf.name] == hashlib.sha256(pdf.read_bytes()).hexdigest()
    assert "kept up to date" in editor.last_message
    # an export changed behind the editor's back is left alone by Save, and Export writes a new name
    pdf.write_bytes(pdf.read_bytes() + b"\n% changed")
    editor.remove("d-2")
    editor.save()
    done(editor)
    assert pdf.read_bytes().endswith(b"% changed")
    editor.export_pdf(tmp_path)
    done(editor)
    assert (tmp_path / "SS-1 A PRELIMINARY (2).pdf").is_file()


def test_email_pdf_with_stand_ins_that_start_nothing(place, opened, tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(mail, "open_in_browser", lambda url: started.append(("browser", url)))
    monkeypatch.setattr(mail, "open_folder", lambda folder: started.append(("folder", folder)))
    monkeypatch.setattr(mail, "start_explorer", lambda p: started.append(("explorer", p)))
    path = drawing_file(place, tmp_path)
    editor, said = opened(path)
    said.give("ask_question", False)
    editor.email_pdf()  # not sent: nothing exported, nothing started
    assert not editor.busy and started == [] and not list(tmp_path.glob("*.pdf"))
    said.give("ask_question", True)
    editor.email_pdf()
    done(editor)
    pdf = tmp_path / "SS-1 A PRELIMINARY.pdf"
    assert pdf.is_file()
    where = ("explorer", str(pdf)) if os.name == "nt" else ("folder", str(tmp_path))
    assert started[0] == where and started[1][0] == "browser"
    assert started[1][1].startswith("https://mail.google.com/mail/?view=cm&fs=1&su=SS-1%20")
    assert editor.last_delivery.route == "webmail" and editor.last_message.startswith(
        "Gmail opened a new message"
    )


# --------------------------------------------------------------------------- the other commands
def test_sheet_units_block_notes_and_settings(place, opened, tmp_path):
    from solidseas_app.viewer import drawingeditor as E

    editor, said = opened(drawing_file(place, tmp_path, "plate"))
    assert (
        not editor.actions_by_name["detail"].isEnabled()
        and E.LATER in editor.actions_by_name["detail"].text()
    )
    assert not editor.actions_by_name["section"].isEnabled()
    editor.sheet_and_scale("B", (1, 1))
    done(editor)
    assert editor.drawing.options.sheet == "B" and editor.drawing.options.scale == (1, 1)
    assert editor.drawing.sheet.name == "B" and editor.undo_stack.count() == 1  # one step for both

    def inches(dialog):
        dialog.fields["units"].setCurrentIndex(dialog.fields["units"].findData("in"))
        return True

    said.give("run_dialog", inches)
    editor.set_units()
    done(editor)
    assert editor.drawing.options.units == "in"
    editor.tolerance_block([(1, 0.02), (2, 0.01), (3, 0.004)])
    done(editor)
    assert float(editor.drawing.settings.block("in")[2].plus_minus) == 0.004
    notes = [n.text for _nid, n in editor.drawing.notes]
    editor.edit_notes([*notes, "MARK PART NUMBER"])
    done(editor)
    assert (
        editor.drawing.notes[-1][1].text == "MARK PART NUMBER"
        and editor.drawing.notes[-1][1].origin == "user"
    )
    newer = S.with_value(people(), "company", "name", "Example Engineering Co. West")
    editor.settings = newer
    editor.use_current_settings()
    done(editor)
    assert editor.drawing.settings.company.name == "Example Engineering Co. West"
    dialog = editor.open_drawing_settings()  # saves to the editor's settings file only
    assert dialog.path == str(tmp_path / "Drawing.json")
    dialog.close()
    editor.undo()
    assert editor.drawing.settings.company.name == "Example Engineering Co."


# --------------------------------------------------------------------------- nothing written outside
def test_nothing_is_written_outside_tmp_path(place, opened, tmp_path, monkeypatch):
    monkeypatch.setattr(mail, "open_in_browser", lambda url: None)
    monkeypatch.setattr(mail, "open_folder", lambda folder: None)
    monkeypatch.setattr(mail, "start_explorer", lambda p: None)
    seen: list[str] = []
    active = True

    def hook(event: str, args: tuple) -> None:
        if active:
            seen.extend(_writes(event, args))

    sys.addaudithook(hook)  # idle once this test ends
    try:
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in place.parts.glob("*.SLD*")}
        path = drawing_file(place, tmp_path)
        editor, said = opened(path)
        editor.remove("d-1")
        editor.sign("CHECKED", "Carl Dee")
        editor.save()
        editor.export_pdf(tmp_path)
        editor.export_dxf(tmp_path)
        said.give("ask_question", True)
        editor.email_pdf()
        done(editor)
        editor.undo()
        editor.close()
    finally:
        active = False
    roots = [os.path.realpath(place.root), os.path.realpath(tmp_path)]
    outside = [p for p in seen if not any(os.path.commonpath([os.path.realpath(p), r]) == r for r in roots)]
    assert outside == []  # the window's side wrote nothing outside the temporary folders
    child = place.log.read_text(encoding="utf-8").splitlines()
    assert child and set(child) == {"audited"}  # every child of the worker wrote nothing at all
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in place.parts.glob("*.SLD*")}
    assert after == before  # the parts were opened read-only
