"""The viewer's File > Convert (``solidseas_app.viewer.convertfile`` and ``.convertaction``),
the OCCT backend extension's front in the viewer.

The conversion runs in the export's own process, as Export STEP's does
(``printing.export_in_process`` with job ``convert``), and starts the OCCT helper from
there: here a stand-in for it, a program the backend takes for a checkout's interpreter
(``test_occt_backend.install_standin_program``), so no Open CASCADE is needed. The
window's dialogs are stood in for, so none is ever shown.
"""

import os
import time

import pytest

import test_occt_backend as B
from solidseas.convert import occt
from solidseas_app.viewer import convertfile, printing
from support import FIXTURES, fixture_path

try:
    import PySide6.QtWidgets  # noqa: F401
except ImportError:
    HAVE_QT = False
else:
    HAVE_QT = True

needs_qt = pytest.mark.skipif(not HAVE_QT, reason="PySide6 is not installed: the window is not tested")


@pytest.fixture
def standin(tmp_path, monkeypatch):
    """The stand-in helper, reached from this process and from the ones it starts."""
    occt.forget()
    log = B.install_standin_program(tmp_path, monkeypatch)
    yield log
    occt.forget()


@pytest.fixture
def out(tmp_path):
    folder = tmp_path / "out"
    folder.mkdir()
    return folder


def _request(target, name="o02_boxA.SLDPRT", fmt="iges", folder=FIXTURES, **extra) -> dict:
    path = name if os.path.isabs(str(name)) else fixture_path(name)
    return {
        "job": "convert",
        "format": fmt,
        "path": str(path),
        "folder": str(folder),
        "target": str(target),
        **extra,
    }


def test_what_converts_to_what_and_why_not():
    assert convertfile.targets(None) == convertfile.targets("solidworks") == ("iges", "brep")
    assert convertfile.targets("parasolid") == convertfile.targets("step") == ("iges", "brep")
    assert convertfile.targets("iges") == ("step", "brep")
    assert convertfile.targets("occt_brep") == ("step", "iges")
    assert convertfile.targets("stl") == ()
    for content in (None, "parasolid", "step", "iges", "occt_brep"):
        assert convertfile.unavailable(content, "part") is None
    assert convertfile.unavailable(None, "drawing") == convertfile.DRAWING
    assert convertfile.unavailable("stl", "part").startswith("STL files hold triangles")
    assert convertfile.unavailable("acis", "part").endswith("not ACIS files")
    offered = ("iges", "brep")
    assert convertfile.format_of_name("a/part.IGES", offered) == "iges"
    assert convertfile.format_of_name("part.brep", offered) == "brep"
    assert convertfile.format_of_name("part.step", offered) is None
    assert convertfile.format_of_name("part", offered) is None
    assert convertfile.extensions("brep") == (".brep",) and convertfile.extensions("iges")[0] == ".igs"


def test_convert_runs_in_the_export_process_and_writes_the_chosen_file(standin, out):
    target = out / "box.igs"
    result = printing.export_in_process(_request(target))
    assert result["ok"], result
    data = result["data"]
    assert data["file"] == str(target) and os.path.getsize(target) == data["bytes"]
    assert (data["format"], data["source_format"], data["backend"]) == ("iges", "solidworks", "occt")
    assert data["report"]["faces"] == 6 and data["left_out"] == []
    assert os.listdir(out) == ["box.igs"]  # no part file left beside it
    # the part went as the STEP Export STEP writes of it, named after the document
    (sent,) = B._requests(standin)
    assert (sent["args"]["from"], sent["args"]["to"], sent["args"]["name"]) == ("step", "iges", "o02_boxA")
    lines = convertfile.written_lines(data)
    assert lines[1] == "IGES through Open CASCADE: 1 solid(s), 6 face(s)" and len(lines) == 2
    # an existing file is replaced only when the save dialog asked to
    again = printing.export_in_process(_request(target))
    assert not again["ok"] and again["error"]["code"] == "output_refused"
    assert again["error"]["detail"]["rule"] == "exists"
    assert printing.export_in_process(_request(target, overwrite=True))["ok"]
    assert os.listdir(out) == ["box.igs"]


def test_an_iges_file_goes_to_the_backend_as_it_is(tmp_path, standin, out):
    models = tmp_path / "models"
    models.mkdir()
    part = models / "bracket.igs"
    part.write_bytes(B.iges("OPEN INVALID"))
    result = printing.export_in_process(_request(out / "bracket.step", part, "step", models))
    assert result["ok"], result
    data = result["data"]
    assert data["source_format"] == "iges" and (out / "bracket.step").is_file()
    (sent,) = B._requests(standin)
    assert (sent["args"]["from"], sent["args"]["to"]) == ("iges", "step")
    lines = convertfile.written_lines(data)
    assert lines[1] == "STEP through Open CASCADE: 1 solid(s), 6 face(s)"
    assert "2 group(s) of surfaces did not close" in lines[2] and "faults" in lines[3]


def test_convert_refusals_write_nothing(standin, out, monkeypatch):
    inside = printing.export_in_process(_request(FIXTURES / "x.igs"))
    assert not inside["ok"] and inside["error"]["code"] == "output_refused"
    assert inside["error"]["detail"]["rule"] == "source_folder"
    other = printing.export_in_process(_request(out / "x.step"))  # asked for IGES
    assert not other["ok"] and other["error"]["detail"]["rule"] == "output_extension"
    mesh = printing.export_in_process(_request(out / "x.igs", "o02_boxA.STL"))
    assert not mesh["ok"] and mesh["error"]["code"] == "not_implemented"
    assert mesh["error"]["detail"]["rule"] == "model_file"
    # without the backend the export's process says what to add, and writes nothing
    monkeypatch.delenv(occt.ENV_PYTHON)
    missing = printing.export_in_process(_request(out / "x.igs"))
    assert not missing["ok"] and missing["error"]["code"] == "format_not_supported"
    assert missing["error"]["detail"]["rule"] == "needs_extension"
    assert os.listdir(out) == [] and not (FIXTURES / "x.igs").exists()
    assert B._requests(standin) == []


def test_through_open_cascade_a_part_converts_and_reads_back_the_same(tmp_path, out, monkeypatch):
    python = B.ocp_python()
    if python is None:
        pytest.skip("no interpreter where OCP imports (SOLIDSEAS_OCCT_PYTHON, or this one)")
    from solidseas.formats import open_model

    occt.forget()
    monkeypatch.setenv(occt.ENV_PYTHON, python)
    try:
        result = printing.export_in_process(_request(out / "box.igs"))
        assert result["ok"], result
        assert result["data"]["report"]["solids"] == 1 and result["data"]["report"]["valid"] is True
        again = tmp_path / "again"
        again.mkdir()
        result = printing.export_in_process(_request(again / "box.brep", out / "box.igs", "brep", out))
        assert result["ok"], result
        for written in (out / "box.igs", again / "box.brep"):
            with open_model(written) as doc:
                volume = doc.scene().objects[0].measures()["volume_m3"]
            assert volume == pytest.approx(B._step_volume(), rel=1e-9), written
    finally:
        occt.forget()


# --------------------------------------------------------------------------- the window
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


class Converter:
    def __init__(self, app, out) -> None:
        from solidseas_app.viewer.window import MainWindow

        self.app = app
        self.window = MainWindow(None)
        self.window.show()
        c = self.window.convert
        self.messages: list[str] = []
        self.questions: list[str] = []
        self.answer = False
        self.asked: list[tuple] = []
        self.chosen = (str(out / "out.igs"), "iges")
        c.ask_path = lambda suggested, formats: self.asked.append((suggested, formats)) or self.chosen
        c.message = lambda icon, text: self.messages.append(text)
        c.confirm = lambda text: self.questions.append(text) or self.answer
        self.outcomes: list[dict] = []
        c.finished.connect(self.outcomes.append)
        self.finished: list[int] = []
        self.window.detailsFinished.connect(self.finished.append)

    def open(self, name: str, folder=FIXTURES) -> None:
        self.window.open_folder(str(folder))
        _wait(self.app, lambda: self.window.listing_info is not None)
        assert self.window.select_document(name), name
        generation = self.window.generation
        _wait(self.app, lambda: generation in self.finished)

    def press(self) -> dict:
        n = len(self.outcomes)
        self.window.act_convert.trigger()
        _wait(self.app, lambda: len(self.outcomes) > n)
        return self.outcomes[-1]

    def close(self) -> None:
        assert self.window.shutdown()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()


@pytest.fixture
def converter(app, out):
    made = []

    def make() -> Converter:
        c = Converter(app, out)
        made.append(c)
        return c

    yield make
    for c in made:
        c.close()


@needs_qt
def test_convert_is_in_the_file_menu_only_while_the_occt_backend_is_there(converter, tmp_path, monkeypatch):
    occt.forget()
    w = converter().window
    actions = w.menuBar().actions()[0].menu().actions()
    assert actions.index(w.act_convert) == actions.index(w.act_step) + 1
    assert not w.act_convert.isVisible() and not w.act_convert.isEnabled()
    # switched on: the Extensions page's change reaches the window, and the item is there
    B.install_standin_program(tmp_path, monkeypatch)
    w.extensions_changed()
    assert w.act_convert.isVisible() and not w.act_convert.isEnabled()  # nothing shown yet
    monkeypatch.delenv(occt.ENV_PYTHON)
    w.extensions_changed()
    assert not w.act_convert.isVisible()
    occt.forget()


@needs_qt
def test_convert_writes_the_part_shown(converter, standin, out):
    c = converter()
    c.open("o02_boxA.SLDPRT")
    assert c.window.act_convert.isVisible() and c.window.act_convert.isEnabled()
    outcome = c.press()
    assert outcome["ok"] and outcome["file"] == c.chosen[0] and os.path.isfile(c.chosen[0])
    ((suggested, formats),) = c.asked
    assert suggested.endswith("o02_boxA.igs") and formats == ("iges", "brep")
    assert c.messages and "IGES through Open CASCADE: 1 solid(s), 6 face(s)" in c.messages[-1]
    assert sorted(os.listdir(out)) == ["out.igs"]
    # a name without an extension gets the file type's, and the type chosen decides
    c.chosen = (str(out / "box"), "brep")
    outcome = c.press()
    assert outcome["ok"] and outcome["file"] == str(out / "box.brep") and outcome["format"] == "brep"
    # a name with one of the formats' extensions decides over the file type chosen
    c.chosen = (str(out / "named.igs"), "brep")
    assert c.press()["format"] == "iges"


@needs_qt
def test_convert_is_off_for_drawings_and_meshes_saying_why(converter, standin):
    c = converter()
    c.open("o18_drw_boxA.SLDDRW")
    assert c.window.act_convert.isVisible() and not c.window.act_convert.isEnabled()
    assert c.window.act_convert.toolTip() == convertfile.DRAWING + "."
    c.open("o02_boxA.STL")
    assert not c.window.act_convert.isEnabled()
    assert c.window.act_convert.toolTip().startswith("STL files hold triangles")
    c.open("o02_boxA.step")
    assert c.window.act_convert.isEnabled()
