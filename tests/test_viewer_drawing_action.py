"""File > New Drawing, Make Drawing, Open Drawing and Drawing Settings in the viewer
(``solidseas_app.viewer.drawingaction``; ``docs/DRAWINGS.md`` 15.1, 15.2 and 15.6).

The window's entries, their reasons when off, the wizard-to-editor hand-off and the
window's close are tested with stand-ins for the New Drawing wizard, the drawing editor,
the Drawing Settings dialog, the file dialog and the drawing process, made with the
real ones' arguments: no dialog is ever shown and no child process is started there.
The self-test's ``--drawing-dry-run`` runs for real on o02 at the end, through the
window's drawing process, its files in this test's own temporary folder.

Every test works on a copy of the fixtures in its own temporary folder. The people and
the company are the fictional "Example Engineering Co." and its staff. Everything here
needs PySide6 and is skipped without it, running offscreen.
"""

import json
import os
import shutil
import time
from pathlib import Path

import pytest

from support import FIXTURES

try:
    import PySide6.QtWidgets  # noqa: F401
except ImportError:  # the window's tests need the [app] extra
    HAVE_QT = False
else:
    HAVE_QT = True

pytestmark = pytest.mark.skipif(not HAVE_QT, reason="PySide6 is not installed: the window is not tested")

PART = "o02_boxA.SLDPRT"
ASSEMBLY = "o08_asm_2x_boxA.SLDASM"
DRAWING = "o18_drw_boxA.SLDDRW"
MESH = "o02_boxA.STL"
O16 = "o16_asm_features.SLDASM"
INNER = "o15_sub_asm-1/o07_boxB_h31-1"  # a part of o16's sub-assembly
VIRTUAL_INSTANCE = "Part12^o16_asm_features-1"  # a virtual part, stored inside o16
PARTS_ONLY = (
    "Drawings are made of SOLIDWORKS parts and assemblies, and of STEP, Parasolid and Alibre Design parts, "
    "in this release."
)


@pytest.fixture
def models(tmp_path) -> Path:
    folder = tmp_path / "models"
    shutil.copytree(FIXTURES, folder)
    return folder


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from solidseas_app.viewer.app import use_system_fonts

    use_system_fonts()
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _wait(app, condition, timeout: float = 60.0) -> None:
    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            raise AssertionError("timed out waiting for the viewer")
        app.processEvents()
        time.sleep(0.005)


def _texts(menu) -> list[str]:
    return [a.text() for a in menu.actions()]


def _entry(menu, start: str):
    found = [a for a in menu.actions() if a.text().startswith(start)]
    assert len(found) == 1, (start, _texts(menu))
    return found[0]


class Worker:
    """The drawing process, stood in for: made with its limits, closed with the window."""

    def __init__(self, limits) -> None:
        self.limits = limits
        self.closed = False

    def close(self) -> None:
        self.closed = True


class Editor:
    """The drawing editor, stood in for, made with the real one's arguments."""

    def __init__(self, worker, path, *, settings=None, settings_path=None, parent=None) -> None:
        self.worker, self.path, self.settings = worker, path, settings
        self.settings_path, self.parent = settings_path, parent
        self.visible = False
        self.keep_open = False  # True: closing it is refused, as for unsaved changes kept
        self.raised = 0
        self.closed = 0

    def show(self) -> None:
        self.visible = True

    def isVisible(self) -> bool:
        return self.visible

    def raise_(self) -> None:
        self.raised += 1

    def activateWindow(self) -> None:
        pass

    def close(self) -> bool:
        self.closed += 1
        if self.keep_open:
            return False
        self.visible = False
        return True


class Dialog:
    """The Drawing Settings dialog, stood in for: OK saves nothing here."""

    def __init__(self, parent, *, path=None, page=None, on_saved=None) -> None:
        self.parent, self.path, self.page, self.on_saved = parent, path, page, on_saved

    def exec(self) -> int:
        return 0


class Viewer:
    """A window whose drawing controller makes stand-ins and records them."""

    def __init__(self, app, tmp: Path) -> None:
        from PySide6.QtCore import QObject, Signal

        from solidseas.drawing import settings as drawing_settings
        from solidseas_app.viewer.window import MainWindow

        class Wizard(QObject):
            """The New Drawing wizard, stood in for, made with the real one's arguments."""

            drawing_written = Signal(str, bool)

            def __init__(
                self,
                parent,
                worker,
                part,
                *,
                configuration=None,
                settings=None,
                settings_path=None,
                folder=None,
            ) -> None:
                super().__init__(parent)
                self.parent_window, self.worker, self.part = parent, worker, part
                self.configuration, self.settings = configuration, settings
                self.settings_path, self.folder = settings_path, folder
                self.visible = False

            def show(self) -> None:
                self.visible = True

            def isVisible(self) -> bool:
                return self.visible

            def close(self) -> bool:
                self.visible = False
                return True

        self.app = app
        self.window = MainWindow()
        self.window.show()
        self.wizards: list = []
        self.wizard_class = Wizard  # the stand-in, for the Guided wizard too
        self.editors: list[Editor] = []
        self.dialogs: list[Dialog] = []
        self.workers: list[Worker] = []
        self.messages: list[str] = []
        self.finished: list[int] = []
        c = self.controller
        c.make_wizard = lambda *a, **k: self.wizards.append(Wizard(*a, **k)) or self.wizards[-1]
        c.make_editor = lambda *a, **k: self.editors.append(Editor(*a, **k)) or self.editors[-1]
        c.make_settings_dialog = lambda *a, **k: self.dialogs.append(Dialog(*a, **k)) or self.dialogs[-1]
        c.make_worker = lambda limits: self.workers.append(Worker(limits)) or self.workers[-1]
        c.message = lambda icon, text: self.messages.append(text)
        c.pick_drawing = lambda start: ""
        # The chooser of Express, Guided and Expert, stood in for: each answer is taken in
        # turn, Expert (the wizard) once none is left; the names it was asked about are kept.
        self.mode_answers: list[tuple[str | None, bool]] = []
        self.mode_asked: list[str] = []
        c.choose_mode = lambda name: (
            self.mode_asked.append(name)
            or (self.mode_answers.pop(0) if self.mode_answers else ("expert", False))
        )
        # Drawing Settings of the test's own, with nothing waiting for a first answer.
        settings = drawing_settings.DrawingSettings()
        for group, key, value in (
            ("company", "name", "Example Engineering Co."),
            ("people", "people", [{"name": "Alex Drafter", "initials": "AD"}]),
            ("standard", "unit_for_unstated", "mm"),
        ):
            settings = drawing_settings.with_value(settings, group, key, value)
        self.settings_path = str(tmp / "Drawing.json")
        drawing_settings.save_settings(settings, self.settings_path)
        c.settings_path = self.settings_path
        self.window.detailsFinished.connect(self.finished.append)

    @property
    def controller(self):
        return self.window.drawings

    def open(self, folder: Path, name: str) -> None:
        w = self.window
        if w.folder != str(folder):
            w.open_folder(str(folder))
            _wait(self.app, lambda: w.listing_info is not None)
        assert w.select_document(name), name
        generation = w.generation
        _wait(self.app, lambda: generation in self.finished)

    def list_menu(self, name: str):
        from solidseas_app.viewer.documents import NAME

        w = self.window
        row = w.model.find(name)
        return w.list_menu(w.proxy.mapFromSource(w.model.index(row, NAME)))

    def close(self) -> None:
        w = self.window
        w.shutdown()
        w.close()
        w.deleteLater()
        self.app.processEvents()


@pytest.fixture
def viewer(app, tmp_path):
    made: list[Viewer] = []

    def make() -> Viewer:
        v = Viewer(app, tmp_path)
        made.append(v)
        return v

    yield make
    for v in made:
        v.close()


def _target(source_path: str, name: str, **kw):
    from solidseas_app.viewer import reading
    from solidseas_app.viewer.printaction import PrintTarget

    nested = kw.pop("nested", ())
    return PrintTarget(
        reading.Source(source_path, os.path.dirname(source_path), nested), "/f", None, name, **kw
    )


# --------------------------------------------------------------------------- what can be drawn
def test_a_solidworks_part_or_assembly_of_its_own_file_can_be_drawn():
    from solidseas_app.viewer.drawingaction import refusal

    assert refusal(_target("/f/bracket.SLDPRT", "bracket.SLDPRT", doc_type="part")) is None
    assert refusal(_target("/f/bracket.SLDPRT", "bracket.SLDPRT")) is None  # the type not known yet
    assert refusal(_target("/f/top.SLDASM", "top.SLDASM", doc_type="assembly")) is None
    words, why = refusal(
        _target("/f/top.SLDASM", "Sub^top", doc_type="assembly", nested=("VirtualComp/Sub-sldasm",))
    )
    assert words == "stored inside its assembly" and "Save it as an assembly of its own" in why
    words, why = refusal(_target("/f/box.stl", "box.stl", doc_type="part", content_format="stl"))
    assert words == "not a format drawings are made from" and "(STL)" in why and why.endswith(PARTS_ONLY)
    # What the file holds decides, whatever its name says: a STEP saved as .SLDPRT.
    words, why = refusal(_target("/f/odd.SLDPRT", "odd.SLDPRT", doc_type="part", content_format="step"))
    assert words == "named as another format" and "extension of a STEP file" in why
    words, why = refusal(
        _target("/f/top.SLDASM", "Part12^top", doc_type="part", nested=("VirtualComp/Part12-sldprt",))
    )
    assert words == "stored inside its assembly" and "no file of its own" in why
    words, _why = refusal(_target("/f/sub.SLDASM", "Part3^sub", doc_type="part", virtual=("Part3^sub",)))
    assert words == "stored inside its assembly"
    assert refusal(_target("/f/x.SLDDRW", "x.SLDDRW", doc_type="drawing"))[0] == "a SOLIDWORKS drawing"


def test_a_step_parasolid_or_alibre_part_can_be_drawn_and_their_assemblies_not():
    from solidseas_app.viewer.drawingaction import ASSEMBLIES_ONLY, refusal

    for path, fmt in (("/f/shaft.step", "step"), ("/f/shaft.x_t", "parasolid"), ("/f/pin.AD_PRT", "alibre")):
        assert refusal(_target(path, os.path.basename(path), doc_type="part", content_format=fmt)) is None
    # among them the name decides nothing: a STEP file named .x_t is read as STEP
    assert refusal(_target("/f/odd.x_t", "odd.x_t", doc_type="part", content_format="step")) is None
    words, why = refusal(_target("/f/top.step", "top.step", doc_type="assembly", content_format="step"))
    assert (
        words == "an assembly of another format" and why == f"top.step is a STEP assembly. {ASSEMBLIES_ONLY}"
    )
    # a Parasolid file's head says assembly for a multi-body part too: the drawing process decides
    assert refusal(_target("/f/two.x_b", "two.x_b", doc_type="assembly", content_format="parasolid")) is None


def test_make_drawing_reads_as_its_3d_print_entry():
    from solidseas_app.viewer.drawingaction import make_text, said_of_drawing

    assert make_text("3D Print bracket.SLDPRT") == "Make Drawing of bracket.SLDPRT..."
    assert make_text("3D Print Part o07_boxB_h31.SLDPRT") == "Make Drawing of Part o07_boxB_h31.SLDPRT..."
    assert make_text("3D Print This Part") == "Make Drawing of This Part..."
    assert make_text("Something else") == "Make Drawing..."
    assert (
        said_of_drawing("gone.SLDPRT cannot be 3D printed from here.")
        == "gone.SLDPRT cannot be drawn from here."
    )


def test_open_drawing_takes_only_a_plain_ssdrw_file(tmp_path):
    from solidseas_app.viewer.drawingaction import drawing_file_problem

    good = tmp_path / "1234-001.ssdrw"
    good.write_bytes(b"{}")
    assert drawing_file_problem(str(good)) is None
    assert "not a SolidSeas drawing" in drawing_file_problem(str(tmp_path / "x.pdf"))
    assert "could not be found" in drawing_file_problem(str(tmp_path / "gone.ssdrw"))
    (tmp_path / "folder.ssdrw").mkdir()
    assert drawing_file_problem(str(tmp_path / "folder.ssdrw")) == "it is not a plain file"
    link = tmp_path / "link.ssdrw"
    try:
        link.symlink_to(good)
    except OSError:  # no symbolic links for this account (Windows without the privilege)
        return
    assert "link" in drawing_file_problem(str(link))


# --------------------------------------------------------------------------- the window's entries
def test_the_entries_are_in_the_file_and_settings_menus_and_beside_3d_print(viewer):
    from solidseas_app.viewer import drawingaction as da

    w = viewer().window
    c = w.drawings
    file_menu = w.menuBar().actions()[0].menu().actions()
    at = file_menu.index(w.act_print)
    assert file_menu[at + 1].isSeparator()
    assert file_menu[at + 2 : at + 4] == [c.new_action, c.open_action]
    assert c.new_action.text() == da.NEW_TEXT and c.new_action.shortcut().toString() == "Ctrl+D"
    settings = w.settings_menu.actions()
    assert settings[settings.index(w.act_ai_settings) + 1] is c.settings_action
    tools = w.toolbar.actions()
    assert tools[tools.index(w.act_print) + 1] is c.new_action and c.new_action.iconText() == "Drawing"
    assert not c.new_action.isEnabled()  # nothing shown


def test_the_drawing_entries_are_tagged_experimental():
    from solidseas_app.viewer import drawingaction as da

    assert da.NEW_TEXT == "New &Drawing... (Experimental)"
    assert da.OPEN_TEXT == "Open Dra&wing... (Experimental)"
    assert da.SETTINGS_TEXT == "&Drawing Settings... (Experimental)"


def test_switched_off_drawings_hide_their_entries_and_switched_on_bring_them_back(viewer, models):
    v = viewer()
    w, c = v.window, v.controller
    assert w.settings.drawings and c.enabled, "on by default"
    v.open(models, ASSEMBLY)
    w.apply_settings(w.settings.but(drawings=False), save=False)
    assert not c.enabled
    assert not c.new_action.isVisible() and not c.open_action.isVisible() and not c.new_action.isEnabled()
    menu = v.list_menu(PART)
    assert c.fill(menu) == [] and not any(t.startswith("Make Drawing") for t in _texts(menu))
    assert c.new_drawing() is None and c.open_drawing() is None and v.wizards == []
    assert c.settings_action.isVisible(), "Drawing Settings stays, where drawings are switched on again"
    w.apply_settings(w.settings.but(drawings=True), save=False)
    assert c.new_action.isVisible() and c.open_action.isVisible()
    menu = v.list_menu(PART)
    assert [a.text() for a in c.fill(menu)] == [f"Make Drawing of {PART}..."]


def test_new_drawing_is_on_for_a_part_and_off_with_the_reason_for_the_rest(viewer, models):
    v = viewer()
    c = v.controller
    action = c.new_action
    v.open(models, PART)
    assert action.isEnabled() and "Make a drawing of the part or assembly shown" in action.statusTip()
    v.open(models, ASSEMBLY)
    assert action.isEnabled() and "an assembly's parts list and balloons" in action.statusTip()
    v.open(models, DRAWING)
    assert not action.isEnabled() and action.statusTip().endswith(f"SOLIDWORKS drawing. {PARTS_ONLY}")
    v.open(models, MESH)
    assert not action.isEnabled() and f"(STL). {PARTS_ONLY}" in action.statusTip()
    # Ctrl+D (the action) does nothing while it is off, and says why when called anyway.
    action.trigger()
    assert v.wizards == []
    assert (
        c.new_drawing() == {"ok": False, "cannot": action.statusTip()}
        and v.messages[-1] == action.statusTip()
    )


def test_new_drawing_opens_the_wizard_on_the_part_shown(viewer, models):
    v = viewer()
    c = v.controller
    v.open(models, PART)
    c.new_action.trigger()
    (wizard,) = v.wizards
    assert wizard.part == str(models / PART) and wizard.parent_window is v.window
    assert wizard.configuration == v.window.print_target().configuration
    assert wizard.folder == str(models)  # the opened folder, for the folder rules of 12.6
    assert (
        wizard.settings_path == v.settings_path and wizard.settings.company.name == "Example Engineering Co."
    )
    assert wizard.visible and wizard.worker is c.worker and len(v.workers) == 1
    assert c.last["ok"] and c.last["part"] == str(models / PART)
    # One wizard at a time: pressed again, the open one is brought forward.
    c.new_action.trigger()
    assert len(v.wizards) == 1 and c.last["busy"]
    assert v.window.statusBar().currentMessage() == (
        "A New Drawing wizard is already open: finish it or close it first."
    )


def test_the_list_offers_make_drawing_beside_3d_print_once_the_menu_opens(viewer, models):
    from solidseas_app.viewer import opening

    v = viewer()
    v.open(models, ASSEMBLY)
    c = v.controller
    opens = [opening.OPEN_TEXT, opening.show_text()]
    # As the print controller made it, until it opens.
    menu = v.list_menu(PART)
    assert _texts(menu) == [*opens, "", f"3D Print {PART}"]
    added = c.fill(menu)
    assert _texts(menu) == [*opens, "", f"3D Print {PART}", f"Make Drawing of {PART}..."]
    assert added == [menu.actions()[-1]] and added[0].isEnabled()
    assert "New Drawing wizard" in added[0].toolTip()
    assert c.fill(menu) == []  # once
    added[0].trigger()
    assert v.wizards[-1].part == str(models / PART) and v.wizards[-1].configuration is None
    # An assembly's row: on, drawing the assembly.
    v.wizards[-1].visible = False
    menu = v.list_menu(ASSEMBLY)
    menu.aboutToShow.emit()  # what opening it does
    entry = _entry(menu, "Make Drawing of")
    assert entry.text() == f"Make Drawing of {ASSEMBLY}..." and entry.isEnabled()
    entry.trigger()
    assert v.wizards[-1].part == str(models / ASSEMBLY)
    v.wizards[-1].visible = False
    # A 3D file of another format, and a SOLIDWORKS drawing, which offers no 3D Print.
    menu = v.list_menu(MESH)
    c.fill(menu)
    entry = _entry(menu, "Make Drawing of")
    assert entry.text().endswith("(not a format drawings are made from)") and not entry.isEnabled()
    menu = v.list_menu(DRAWING)
    assert c.fill(menu) == [] and not any(t.startswith("Make Drawing") for t in _texts(menu))


def test_make_drawing_from_a_component_row_draws_that_part_from_its_assembly(viewer, models):
    from solidseas_app.viewer.details import CONFIG_ROLE

    v = viewer()
    c = v.controller
    d = v.window.details
    v.open(models, O16)
    item = d.instance_item(INNER)
    menu = d.component_menu(item)
    c.fill(menu)
    texts = _texts(menu)
    at = texts.index("3D Print o07_boxB_h31.SLDPRT")
    assert texts[at + 1] == "Make Drawing of o07_boxB_h31.SLDPRT..."
    _entry(menu, "Make Drawing of").trigger()
    wizard = v.wizards[-1]
    assert wizard.part == str(models / "o07_boxB_h31.SLDPRT") and wizard.folder == str(models)
    assert wizard.configuration == (item.data(0, CONFIG_ROLE) or None)  # the row's configuration
    wizard.visible = False
    # A sub-assembly's row is on, drawing the sub-assembly; a virtual part stored inside the
    # assembly is off.
    sub = d.component_menu(d.instance_item("o15_sub_asm-1"))
    c.fill(sub)
    assert _entry(sub, "Make Drawing of").isEnabled()
    assert _entry(sub, "Make Drawing of").text() == "Make Drawing of o15_sub_asm.SLDASM..."
    virtual = d.instance_menu(VIRTUAL_INSTANCE)
    c.fill(virtual)
    entry = _entry(virtual, "Make Drawing of Part")
    assert entry.text().endswith("(stored inside its assembly)") and not entry.isEnabled()
    # The 3D view's menu of an instance: its part, then each sub-assembly, each after its print.
    view = d.instance_menu(INNER)
    c.fill(view)
    texts = _texts(view)
    assert texts[texts.index("3D Print Part o07_boxB_h31.SLDPRT") + 1] == (
        "Make Drawing of Part o07_boxB_h31.SLDPRT..."
    )
    assert texts[texts.index("3D Print Sub-assembly o15_sub_asm.SLDASM") + 1] == (
        "Make Drawing of Sub-assembly o15_sub_asm.SLDASM..."
    )
    # Empty space: this assembly; for a part shown, This Part.
    space = d.preview.space_menu()
    c.fill(space)
    assert _texts(space) == ["3D Print This Assembly", "Make Drawing of This Assembly..."]
    v.open(models, PART)
    space = d.preview.space_menu()
    c.fill(space)
    assert _texts(space)[:2] == ["3D Print This Part", "Make Drawing of This Part..."]
    space.actions()[1].trigger()
    assert v.wizards[-1].part == str(models / PART)
    for m in (menu, sub, virtual, view, space):
        m.deleteLater()


def test_a_component_whose_file_is_missing_cannot_be_drawn_and_says_why(viewer, tmp_path, monkeypatch):
    from builders import TreeXml, resolving_assembly
    from solidseas.resolve import gateway as gateway_mod

    real = gateway_mod._drive_type
    monkeypatch.setattr(  # drive Q: does not exist, whatever this machine has
        gateway_mod,
        "_drive_type",
        lambda root: gateway_mod.DRIVE_NO_ROOT_DIR if root.upper().startswith("Q:") else real(root),
    )
    folder = tmp_path / "Job"
    folder.mkdir()
    t = TreeXml()
    t.top("m1")
    t.file("2", "Q:\\Gone\\gone.SLDPRT", swCreationTime="1700000000")
    t.model("m2", "2")
    t.ref("m1", "c2", 1, "m2")
    (folder / "top.SLDASM").write_bytes(resolving_assembly(t))
    v = viewer()
    v.open(folder, "top.SLDASM")
    menu = v.window.details.component_menu(v.window.details.instance_item("c2-1"))
    v.controller.fill(menu)
    assert _texts(menu)[-2:] == [
        "3D Print gone.SLDPRT (not found)",
        "Make Drawing of gone.SLDPRT... (not found)",
    ]
    entry = menu.actions()[-1]
    assert not entry.isEnabled() and entry.toolTip().count("cannot be drawn from here")
    assert "No file of that name was found." in entry.toolTip() and "3D printed" not in entry.toolTip()
    menu.deleteLater()


def test_choosing_an_entry_that_cannot_be_drawn_says_why(viewer, models):
    v = viewer()
    c = v.controller
    v.open(models, PART)
    assert c.draw_resolved(lambda: "x.SLDPRT cannot be 3D printed.\n\nIt is gone.")["ok"] is False
    assert v.messages[-1] == "x.SLDPRT cannot be drawn.\n\nIt is gone."
    assert c.draw_resolved(lambda: None) is None  # a question cancelled: nothing
    assert c.start(v.window.print_target())["ok"] and len(v.wizards) == 1


# --------------------------------------------------------------------------- the wizard and the editor
def test_the_wizard_hands_the_drawing_it_wrote_to_the_editor(viewer, models, tmp_path):
    v = viewer()
    c = v.controller
    v.open(models, PART)
    c.new_action.trigger()
    (wizard,) = v.wizards
    written: list[str] = []
    opened: list = []
    c.written.connect(written.append)
    c.opened.connect(opened.append)
    path = str(tmp_path / "out" / "1234-001.ssdrw")
    wizard.visible = False  # Finish closes it
    wizard.drawing_written.emit(path, True)
    (editor,) = v.editors
    assert editor.path == path and editor.worker is c.worker and editor.parent is None
    assert (
        editor.settings_path == v.settings_path and editor.settings.company.name == "Example Engineering Co."
    )
    assert editor.visible and opened == [editor] and written == [path]
    assert path in v.window.statusBar().currentMessage()
    # Open in the Editor unticked: written, no editor.
    other = str(tmp_path / "out" / "1234-002.ssdrw")
    wizard.drawing_written.emit(other, False)
    assert written == [path, other] and len(v.editors) == 1
    # The same drawing again: its editor is brought forward, not a second one.
    wizard.drawing_written.emit(path, True)
    assert len(v.editors) == 1 and editor.raised == 1
    assert len(v.workers) == 1  # one drawing process for the window


def test_open_drawing_opens_a_drawing_in_the_editor_once(viewer, tmp_path):
    v = viewer()
    c = v.controller
    drawing = tmp_path / "1234-001.ssdrw"
    drawing.write_bytes(b"{}")  # the editor reads it; the stand-in does not
    asked: list[str] = []
    c.pick_drawing = lambda start: asked.append(start) or str(drawing)
    c.open_action.trigger()
    (editor,) = v.editors
    assert editor.path == str(drawing) and editor.worker is c.worker and editor.parent is None
    assert asked and asked[0]  # Documents, with no folder open
    c.open_action.trigger()
    assert len(v.editors) == 1 and editor.raised == 1
    c.pick_drawing = lambda start: str(tmp_path / "notes.pdf")
    c.open_action.trigger()
    assert len(v.editors) == 1 and "not a SolidSeas drawing" in v.messages[-1]
    c.pick_drawing = lambda start: ""  # cancelled
    assert c.open_drawing() is None and len(v.editors) == 1

    # An editor that refuses the file says why, and none is kept.
    def refusing(*a, **k):
        raise ValueError("the drawing was written by a newer SolidSeas")

    other = tmp_path / "other.ssdrw"
    other.write_bytes(b"{}")
    c.make_editor = refusing
    c.pick_drawing = lambda start: str(other)
    assert c.open_drawing() is None and "newer SolidSeas" in v.messages[-1]


def test_closing_the_window_closes_the_editors_and_the_drawing_process(viewer, models, tmp_path):
    v = viewer()
    c = v.controller
    v.open(models, PART)
    c.new_action.trigger()
    (wizard,) = v.wizards
    for name in ("a.ssdrw", "b.ssdrw"):
        c.open_editor(str(tmp_path / name))
    first, second = v.editors
    # An editor that stays open (its user keeps unsaved changes) keeps the window open.
    second.keep_open = True
    assert not v.window.close()
    assert v.window.isVisible() and not v.workers[0].closed and second.raised == 1
    second.keep_open = False
    assert v.window.close()
    assert not first.visible and not second.visible and not wizard.visible
    assert v.workers[0].closed and c.editors == [] and c.wizard is None
    assert not c.new_action.isEnabled() and c.start(v.window.print_target())["closed"]


# --------------------------------------------------------------------------- Drawing Settings
def test_drawing_settings_opens_the_dialog_on_the_settings_file(viewer):
    v = viewer()
    c = v.controller
    c.settings_action.trigger()
    (dialog,) = v.dialogs
    assert dialog.parent is v.window and dialog.path == v.settings_path and dialog.page is None
    dialog.on_saved(None)
    assert "Drawing Settings saved" in v.window.statusBar().currentMessage()


def test_on_first_use_new_drawing_asks_for_drawing_settings_first(viewer, models, tmp_path):
    v = viewer()
    c = v.controller
    c.settings_path = str(tmp_path / "none" / "Drawing.json")  # not there: every first-use prompt
    v.open(models, PART)
    c.new_action.trigger()
    (dialog,) = v.dialogs
    assert dialog.page == "Standard and Units" and dialog.path == c.settings_path  # the unit comes first
    assert len(v.wizards) == 1 and c.last["first_use"] == "Standard and Units"
    v.wizards[0].visible = False
    c.new_action.trigger()  # once a session
    assert len(v.dialogs) == 1 and len(v.wizards) == 2


def test_without_the_wizard_or_the_editor_the_entries_say_so(viewer, models, monkeypatch, tmp_path):
    from solidseas_app.viewer import drawingaction as da

    def missing():
        raise ImportError("not built yet")

    monkeypatch.setattr(da, "_wizard_class", missing)
    monkeypatch.setattr(da, "_editor_class", missing)
    v = viewer()
    c = v.controller
    c.make_wizard = c.make_editor = None
    v.open(models, PART)
    assert c.new_drawing()["ok"] is False and "wizard is not in this viewer" in v.messages[-1]
    assert (
        c.open_editor(str(tmp_path / "x.ssdrw")) is None and "editor is not in this viewer" in v.messages[-1]
    )


# --------------------------------------------------------------------------- the self-test's dry run
def test_the_self_tests_drawing_dry_run_draws_o02_and_o08_and_reports_each_step(app, models, tmp_path):
    from PySide6.QtCore import QTimer

    from solidseas_app.viewer.selftest import SelfTest
    from solidseas_app.viewer.window import MainWindow

    window = MainWindow()
    window.resize(1200, 800)
    window.show()
    shots = tmp_path / "shots"
    base = tmp_path / "temp"
    base.mkdir()
    before = {p.name: p.read_bytes() for p in models.iterdir() if p.is_file()}
    st = SelfTest(
        window, str(models), screenshot_dir=str(shots), select=[PART, ASSEMBLY], drawing_dry_run=True
    )
    st.drawing_base = str(base)
    QTimer.singleShot(0, st.start)
    assert app.exec() == 0
    worker = window.drawings.worker
    window.shutdown()
    window.close()
    report = json.loads((shots / "selftest.json").read_text(encoding="utf-8"))
    assert report["ok"], (report["errors"], [d["errors"] for d in report["documents"]])
    part, assembly = (d["drawing"] for d in report["documents"])
    assert part["ok"] and part["drawable"] and part["entry"]["enabled"]
    wizard, editor = part["wizard"], part["editor"]
    assert wizard["probe"]["unit"] == "mm" and wizard["probe"]["size_mm"] == [10.0, 20.0, 30.0]
    assert [f["name"] for f in wizard["files"]] == [
        "ST-001 A PRELIMINARY.pdf",
        "ST-001 A PRELIMINARY.dxf",
        "ST-001.ssdrw",
    ]
    steps = [s["step"] for s in editor["steps"]]
    assert steps == [
        "remove",
        "restore",
        "undo",
        "undo",
        "sign CHECKED",
        "sign APPROVED",
        "save",
        "release",
        "save",
        "start revision",
        "save",
        "save",
    ]
    status = {s["step"]: (s["status"], s["revision"]) for s in editor["steps"]}
    assert status["sign CHECKED"] == ("CHECKED", "A") and status["release"] == ("RELEASED", "A")
    assert status["start revision"] == ("PRELIMINARY", "B")
    assert editor["released"] == ["ST-001 A.dxf", "ST-001 A.pdf"]
    email = editor["email"]
    assert email["pdf"] == "ST-001 B PRELIMINARY.pdf" and email["delivered"] in ("webmail", "attach", "show")
    if email["delivered"] == "webmail":
        assert email["opened"] == [email["url"]] and email["url"].startswith("https://")
        assert email["url"].endswith("su=ST-001%20SELF-TEST%20DRAWING")
    checks = part["checks"]
    assert sorted(checks) == [
        "ST-001 A PRELIMINARY.dxf",
        "ST-001 A PRELIMINARY.pdf",
        "ST-001 A.dxf",
        "ST-001 A.pdf",
        "ST-001 B PRELIMINARY.pdf",
    ]
    assert all(c["problems"] == [] and c["checker"] for c in checks.values())
    assert checks["ST-001 A.pdf"]["text_runs"] > 0 and checks["ST-001 A.dxf"]["dimensions"] > 0
    assert part["said"] == [] and "kept_in" not in part
    assert os.listdir(base) == []  # the run's folder, removed once every check passed
    assert any(p.endswith("_drawing_sheet.png") for p in report["screenshots"])
    # The assembly is drawn too: no dimension to remove, its parts list and balloon on the sheet.
    assert assembly["ok"] and assembly["drawable"] and assembly["entry"]["enabled"], assembly
    assert assembly["wizard"]["probe"]["assembly"] == {"items": 1, "instances": 2, "left_out": []}
    assert "material" not in assembly["wizard"]["make"] and assembly["wizard"]["make"]["dimensions"] == 3
    assert [s["step"] for s in assembly["editor"]["steps"]] == steps[4:]
    assert assembly["editor"]["parts"] == {"items": 1, "balloons": 1}
    assert assembly["editor"]["released"] == ["ST-002 A.dxf", "ST-002 A.pdf"]
    assert assembly["said"] == [] and "kept_in" not in assembly
    # Nothing was written beside the parts, and the drawing process ended with the window.
    assert {p.name: p.read_bytes() for p in models.iterdir() if p.is_file()} == before
    assert worker is not None and not worker.running


def test_the_dry_run_fails_on_a_pdf_or_dxf_its_checkers_refuse(tmp_path):
    from solidseas_app.viewer.selftest import check_dxf_file, check_pdf_file

    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.7\nnot really\n")
    got = check_pdf_file(str(bad), stamped=True)
    assert got["checker"] == "tests/pdf_reader.py" and got["problems"][0].startswith("the reader refused it")
    bad = tmp_path / "bad.dxf"
    bad.write_bytes(b"999\nSolidSeas\n0\nSECTION\n")
    assert check_dxf_file(str(bad), stamped=False)["problems"][0].startswith("the reader refused it")


# --------------------------------------------------------------------------- the drawing modes
class ExpressStandIn:
    """An Express drawing in progress, stood in for: made with the real one's arguments,
    started, and finished by the test."""

    made: list = []

    def __init__(self, parent, worker, part, *, configuration=None, settings=None, folder=None) -> None:
        from PySide6.QtCore import QObject, Signal

        class Signals(QObject):
            done = Signal(str)
            failed = Signal(str)

        self.signals = Signals()
        self.done, self.failed = self.signals.done, self.signals.failed
        self.parent, self.worker, self.part = parent, worker, part
        self.configuration, self.settings, self.folder = configuration, settings, folder
        self.started = False
        self.finished = False
        ExpressStandIn.made.append(self)

    def start(self) -> None:
        self.started = True


def test_the_chooser_offers_express_guided_and_expert(app):
    from PySide6.QtWidgets import QLabel

    from solidseas_app.viewer import drawingmode as M
    from solidseas_app.viewer import experimental

    dialog = M.ModeDialog(None, "plate.SLDPRT")
    try:
        assert list(dialog.buttons) == ["express", "guided", "expert"]
        assert [b.text() for b in dialog.buttons.values()] == ["Express", "Guided", "Expert"]
        assert all(b.isEnabled() for b in dialog.buttons.values())
        assert dialog.buttons["express"].description() == (
            "A simple drawing with the key sizes, straight to the editor"
        )
        assert dialog.buttons["guided"].description() == (
            "A few plain questions, one at a time, then the editor"
        )
        assert dialog.buttons["expert"].description().startswith("Every option")
        assert dialog.remember_box.text() == "Remember my choice" and not dialog.remember
        assert experimental.drawings_note() in [label.text() for label in dialog.findChildren(QLabel)]
        dialog.choose("nothing")  # not a mode: nothing happens
        assert dialog.chosen is None
        dialog.remember_box.setChecked(True)
        dialog.buttons["express"].click()
        assert dialog.chosen == "express" and dialog.remember and dialog.result() == 1
    finally:
        dialog.deleteLater()


def test_expert_opens_the_wizard_and_cancelling_the_chooser_starts_nothing(viewer, models):
    v = viewer()
    c = v.controller
    v.open(models, PART)
    v.mode_answers = [(None, False), ("expert", False)]
    c.new_action.trigger()
    assert v.mode_asked == [PART] and not v.wizards and c.last["cancelled"]
    c.new_action.trigger()
    assert len(v.wizards) == 1 and c.last["mode"] == "expert" and v.wizards[0].visible
    assert v.window.settings.drawing_mode == "ask", "nothing remembered"


def test_express_makes_the_drawing_and_opens_it_in_the_editor(viewer, models, tmp_path):
    v = viewer()
    c = v.controller
    c.make_express = ExpressStandIn
    ExpressStandIn.made = []
    v.open(models, PART)
    v.mode_answers = [("express", False)] * 2
    c.new_action.trigger()
    (run,) = ExpressStandIn.made
    assert run.started and run.part == str(models / PART) and run.folder == str(models)
    assert run.worker is c.worker and run.settings.company.name == "Example Engineering Co."
    assert not v.wizards and c.last["ok"] and c.last["mode"] == "express"
    assert "Express drawing" in v.window.statusBar().currentMessage()
    # Pressed again while it is being made: one at a time, and nothing asked.
    c.new_action.trigger()
    assert len(ExpressStandIn.made) == 1 and c.last["busy"] and len(v.mode_asked) == 1
    path = str(tmp_path / "out" / "O02.ssdrw")
    run.finished = True
    run.done.emit(path)
    (editor,) = v.editors
    assert editor.path == path and editor.visible
    # A failure is said, and the next press starts again.
    c.new_action.trigger()
    second = ExpressStandIn.made[-1]
    assert second is not run
    second.finished = True
    second.failed.emit("the part could not be read")
    assert "Express drawing was not made: the part could not be read" in v.messages[-1]


def test_remember_my_choice_skips_the_chooser_and_the_setting_is_on_the_drawings_page(viewer, models):
    from solidseas_app.viewer import settingswindow as SW

    v = viewer()
    c = v.controller
    v.open(models, PART)
    v.mode_answers = [("expert", True)]
    c.new_action.trigger()
    assert v.window.settings.drawing_mode == "expert" and len(v.mode_asked) == 1
    v.wizards[0].visible = False
    c.new_action.trigger()
    assert len(v.mode_asked) == 1 and len(v.wizards) == 2, "no chooser: the wizard straight away"
    d = SW.SettingsWindow(v.window, page=SW.DRAWINGS)
    try:
        combo = d.preferences.drawing_mode
        assert combo.isVisibleTo(d) and combo.currentData() == "expert"
        assert [combo.itemData(i) for i in range(combo.count())] == ["ask", "express", "guided", "expert"]
        combo.setCurrentIndex(combo.findData("ask"))
        assert d.apply()
        assert v.window.settings.drawing_mode == "ask"
    finally:
        d.deleteLater()
    v.wizards[1].visible = False
    c.new_action.trigger()
    assert len(v.mode_asked) == 2, "asked again"


def test_guided_opens_the_guided_wizard_and_can_be_remembered(viewer, models, tmp_path):
    v = viewer()
    c = v.controller
    guided: list = []
    c.make_guided = lambda *a, **k: guided.append(v.wizard_class(*a, **k)) or guided[-1]
    v.open(models, PART)
    v.mode_answers = [("guided", True)]
    c.new_action.trigger()
    (wizard,) = guided
    assert not v.wizards and wizard.visible and c.last["ok"] and c.last["mode"] == "guided"
    assert wizard.part == str(models / PART) and wizard.folder == str(models)
    assert wizard.settings.company.name == "Example Engineering Co."
    assert v.window.settings.drawing_mode == "guided"
    # Pressed again while it is open: it is brought forward, and nothing is asked.
    c.new_action.trigger()
    assert len(guided) == 1 and c.last["busy"] and len(v.mode_asked) == 1
    assert c.last["note"] == "A Guided drawing is already open: finish it or close it first."
    assert v.window.statusBar().currentMessage() == c.last["note"]
    # What it writes opens in the editor, as the wizard's does.
    path = str(tmp_path / "out" / "O02.ssdrw")
    wizard.drawing_written.emit(path, True)
    (editor,) = v.editors
    assert editor.path == path
    wizard.visible = False
    c.new_action.trigger()
    assert len(guided) == 2 and len(v.mode_asked) == 1, "remembered: no chooser"


def test_switched_off_drawings_start_no_mode(viewer, models):
    v = viewer()
    c = v.controller
    v.open(models, PART)
    v.window.apply_settings(v.window.settings.but(drawings=False, drawing_mode="express"))
    assert c.new_drawing() is None and not v.mode_asked and not v.wizards


def test_express_draws_a_part_with_a_hole_through_the_drawing_process(app, models):
    from solidseas.drawing import document
    from solidseas.drawing import settings as drawing_settings
    from solidseas_app.viewer.drawingmode import make_express
    from solidseas_app.viewer.drawingproc import DrawingWorker

    settings = drawing_settings.DrawingSettings()
    for group, key, value in (
        ("company", "name", "Example Engineering Co."),
        ("people", "people", [{"name": "Alex Drafter", "initials": "AD"}]),
    ):
        settings = drawing_settings.with_value(settings, group, key, value)
    source = models / "o10_import_step_cut.SLDPRT"
    before = source.read_bytes()
    worker = DrawingWorker()
    try:
        written = make_express(worker, str(source), None, settings, str(models))
    finally:
        worker.close()
    assert os.path.dirname(written.path) == str(models) and written.path.endswith(".ssdrw")
    assert written.files == (written.path,), "no PDF or DXF: the editor exports them"
    with open(written.path, "rb") as fh:
        d, problems = document.loads(fh.read())
    assert problems == [] and d.options.mode == "express" and d.options.detail == "simplified"
    kinds = sorted(dim.key.split("/")[0] for dim in d.dimensions)
    assert kinds == ["callout", "loc", "loc", "size", "size", "size"]
    assert [g.name for g in d.signatures if g.row == "DRAWN"] == ["Alex Drafter"]
    assert source.read_bytes() == before
