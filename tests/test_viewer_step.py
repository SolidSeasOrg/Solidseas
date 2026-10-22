"""The viewer's File > Export STEP (``solidseas_app.viewer.stepexport`` and ``.stepaction``).

The export runs in the export's own process, as 3D Print's does
(``printing.export_in_process`` with job ``step``), and writes the file the user
chose, through a part file beside it that a stopped process never leaves behind.
The window's save dialog, question and message boxes are stood in for, so no
dialog is ever shown.
"""

import errno
import os
import time

import pytest

import step_support as T
from solidseas_app.viewer import printing, stepexport
from support import FIXTURES, fixture_path, within

try:
    import PySide6.QtWidgets  # noqa: F401
except ImportError:
    HAVE_QT = False
else:
    HAVE_QT = True

needs_qt = pytest.mark.skipif(not HAVE_QT, reason="PySide6 is not installed: the window is not tested")


def _request(target, name="o02_boxA.SLDPRT", **extra) -> dict:
    return {
        "job": "step",
        "path": str(fixture_path(name)),
        "folder": str(FIXTURES),
        "target": str(target),
        **extra,
    }


def test_export_step_runs_in_the_export_process_and_writes_the_chosen_file(tmp_path):
    target = tmp_path / "box.stp"
    result = printing.export_in_process(_request(target))
    assert result["ok"], result
    data = result["data"]
    assert data["file"] == str(target) and os.path.getsize(target) == data["bytes"]
    assert data["solids"] == 1 and data["faces"] == 6 and data["exact"] and not data["partial"]
    assert data["uncertainty_mm"] == pytest.approx(1e-5)
    assert os.listdir(tmp_path) == ["box.stp"]  # no part file left beside it
    f = T.read(target.read_bytes())
    assert T.syntax_problems(f) == [] and f.header_record("FILE_NAME")[0] == "box.stp"
    # an existing file is replaced only when the save dialog asked to
    again = printing.export_in_process(_request(target))
    assert not again["ok"] and again["error"]["code"] == "output_refused"
    assert again["error"]["detail"]["rule"] == "exists"
    assert printing.export_in_process(_request(target, overwrite=True))["ok"]
    assert os.listdir(tmp_path) == ["box.stp"]


def test_export_step_refusals_write_nothing(tmp_path):
    inside = printing.export_in_process(_request(FIXTURES / "x.step"))
    assert not inside["ok"] and inside["error"]["code"] == "output_refused"
    assert inside["error"]["detail"]["rule"] == "source_folder"
    other = printing.export_in_process(_request(tmp_path / "x.stl"))
    assert not other["ok"] and other["error"]["detail"]["rule"] == "output_extension"
    unstored = printing.export_in_process(
        _request(tmp_path / "x.step", "o06_boxA_props_mat_cfg.SLDPRT", configuration="OracleAlt")
    )
    assert not unstored["ok"] and unstored["error"]["code"] == "nothing_to_export"
    assert os.listdir(tmp_path) == []
    assert not (FIXTURES / "x.step").exists()


def test_a_cancelled_step_export_ends_its_process_and_leaves_nothing(tmp_path):
    t0 = time.monotonic()
    answers = iter([False])
    result = printing.export_in_process(
        _request(tmp_path / "c.step", "o11_curved.SLDPRT"), lambda: next(answers, True)
    )
    assert result == printing.CANCELLED
    assert time.monotonic() - t0 < within(5)
    assert os.listdir(tmp_path) == []


def test_a_part_of_surfaces_only_is_written_as_its_surfaces(tmp_path, monkeypatch):
    """The viewer has no choice of body types: a part with no solid gets its sheets
    written, where the library (solids by default) would say there is nothing to export;
    a part with solids keeps to them."""
    import solidseas.step as S
    from solidseas.errors import NothingToExportError

    real = S.step_model
    asked = []

    def surfaces_only(doc, configuration=None, **options):
        asked.append(options.get("body_types", ("solid",)))
        if "sheet" not in asked[-1]:
            raise NothingToExportError("only sheets", detail={"rule": "sheets_not_asked"})
        return real(doc, configuration, **{**options, "body_types": ("solid",)})

    monkeypatch.setattr(S, "step_model", surfaces_only)
    data = stepexport.export_step_file(
        str(fixture_path("o02_boxA.SLDPRT")), str(FIXTURES), str(tmp_path / "s.step")
    )
    assert asked == [("solid",), ("solid", "sheet")] and os.path.isfile(data["file"])
    asked.clear()
    monkeypatch.setattr(
        S, "step_model", lambda doc, configuration=None, **o: asked.append(o) or real(doc, configuration, **o)
    )
    stepexport.export_step_file(str(fixture_path("o02_boxA.SLDPRT")), str(FIXTURES), str(tmp_path / "t.step"))
    assert [o.get("body_types") for o in asked] == [None]


def test_a_hidden_solid_beside_shown_surfaces_exports_and_prints_as_surfaces(tmp_path, monkeypatch):
    """A part whose solid is hidden and whose one shown body is a surface: File > Export
    STEP writes the surface and lists the hidden solid it left out, and 3D Print says the
    part is surfaces, which a slicer cannot print from a STEP, rather than that every
    body is hidden. Neither names an option of the library the viewer cannot set."""
    from solidseas import open_document
    from test_step import _with_flags

    _with_flags(monkeypatch, [1, 0], sheets=(0,))
    part = str(fixture_path("o12_multibody.SLDPRT"))
    data = stepexport.export_step_file(part, str(FIXTURES), str(tmp_path / "s.step"))
    assert (data["solids"], data["sheets"]) == (0, 1)
    assert [(b["name"], b["reason"]) for b in data["left_out"]] == [("Boss-Extrude1", "hidden")]
    assert stepexport.left_out_lines(data["left_out"]) == [
        "Hidden bodies not written (SOLIDWORKS leaves them out of its STEP too): Boss-Extrude1"
    ]
    f = T.read((tmp_path / "s.step").read_bytes())
    assert len(f.of("SHELL_BASED_SURFACE_MODEL")) == 1 and f.of("MANIFOLD_SOLID_BREP") == []
    with open_document(part) as doc:
        model, why = printing.step_for_print(doc, None, "x")
    assert model is None and why == "the part's bodies are surfaces, which a slicer cannot print from a STEP"
    _with_flags(monkeypatch, [0, 0])  # every body hidden: said so, in the viewer's words
    with open_document(part) as doc:
        model, why = printing.step_for_print(doc, None, "x")
    assert model is None and "hidden in SOLIDWORKS" in why and "include_hidden" not in why


def test_bodies_not_written_are_worded_by_why():
    left = [
        {"name": "Surface-Trim1", "reason": "not_asked"},
        {"name": "Surface-Knit2", "reason": "not_asked"},
        {"name": "3DSketch1", "reason": "unsupported_body"},
        {"name": "Body2", "reason": "fit_failed"},
        {"name": "Boss-Extrude3", "reason": "hidden"},
    ]
    assert stepexport.left_out_lines(left) == [
        "Hidden bodies not written (SOLIDWORKS leaves them out of its STEP too): Boss-Extrude3",
        "Surface bodies not written (the part's solids are): Surface-Trim1, Surface-Knit2",
        "Wire bodies not written (STEP holds no wire body): 3DSketch1",
        "Left out, as you asked: Body2 (fit_failed)",
    ]
    assert stepexport.left_out_lines([]) == []


def test_the_part_file_sits_beside_the_target(tmp_path):
    part = stepexport.part_path(str(tmp_path / "a.step"), "abc")
    assert os.path.dirname(part) == str(tmp_path) and os.path.basename(part) == ".a.step.abc.part"


@pytest.mark.skipif(os.name == "nt", reason="Windows names a new file by a rename, not a link")
def test_a_folder_without_hard_links_is_said_to_be_one(tmp_path, monkeypatch):
    """Outside Windows the file is named by a second link to its part, which a FAT or exFAT
    drive refuses with EPERM, a PermissionError: the refusal says what the folder is, not
    that permission was denied, and nothing is left there. A file the save dialog asked
    to replace is replaced without a link."""
    from solidseas.errors import OutputRefusedError
    from solidseas_app.viewer.wording import refusal_text

    def refused(src, dst, *args, **kwargs):
        raise OSError(errno.EPERM, os.strerror(errno.EPERM))

    monkeypatch.setattr(os, "link", refused)
    source, folder = str(fixture_path("o02_boxA.SLDPRT")), str(FIXTURES)
    with pytest.raises(OutputRefusedError) as err:
        stepexport.export_step_file(source, folder, str(tmp_path / "box.step"))
    assert err.value.detail == {"rule": printing.NO_HARD_LINKS, "errno": "EPERM"}
    assert os.listdir(tmp_path) == []
    assert refusal_text({"detail": err.value.detail}).startswith("That folder is on a file system without")
    (tmp_path / "old.step").write_bytes(b"old")
    data = stepexport.export_step_file(source, folder, str(tmp_path / "old.step"), overwrite=True)
    assert data["file"] == str(tmp_path / "old.step") and os.listdir(tmp_path) == ["old.step"]


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


class Exporter:
    def __init__(self, app, tmp) -> None:
        from solidseas_app.viewer.window import MainWindow

        self.app = app
        self.window = MainWindow(None)
        self.window.show()
        s = self.window.step
        self.messages: list[str] = []
        self.questions: list[str] = []
        self.answer = False
        self.paths: list[str] = []
        self.chosen = str(tmp / "out.step")
        s.ask_path = lambda suggested: self.paths.append(suggested) or self.chosen
        s.message = lambda icon, text: self.messages.append(text)
        s.confirm = lambda text: self.questions.append(text) or self.answer
        self.outcomes: list[dict] = []
        s.finished.connect(self.outcomes.append)
        self.finished: list[int] = []
        self.window.detailsFinished.connect(self.finished.append)

    def open(self, name: str) -> None:
        self.window.open_folder(str(FIXTURES))
        _wait(self.app, lambda: self.window.listing_info is not None)
        assert self.window.select_document(name), name
        generation = self.window.generation
        _wait(self.app, lambda: generation in self.finished)

    def press(self) -> dict:
        n = len(self.outcomes)
        self.window.act_step.trigger()
        _wait(self.app, lambda: len(self.outcomes) > n)
        return self.outcomes[-1]

    def close(self) -> None:
        assert self.window.shutdown()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()


@pytest.fixture
def exporter(app, tmp_path):
    made = []

    def make() -> Exporter:
        e = Exporter(app, tmp_path)
        made.append(e)
        return e

    yield make
    for e in made:
        e.close()


@needs_qt
def test_export_step_is_in_the_file_menu_beside_export_parasolid(exporter):
    w = exporter().window
    actions = w.menuBar().actions()[0].menu().actions()
    assert actions.index(w.act_step) == actions.index(w.act_parasolid) + 1
    assert not w.act_step.isEnabled()  # nothing shown yet


@needs_qt
def test_export_step_writes_the_part_shown(exporter, tmp_path):
    e = exporter()
    e.open("o11_curved.SLDPRT")
    assert e.window.act_step.isEnabled()
    outcome = e.press()
    assert outcome["ok"] and outcome["file"] == e.chosen and os.path.isfile(e.chosen)
    assert e.paths and e.paths[0].endswith("o11_curved.step")
    # 14 faces: o11's hole and rim each written as two, cut at their seams as SOLIDWORKS does
    assert e.messages and "Exact" in e.messages[-1] and "14 faces" in e.messages[-1]
    assert sorted(os.listdir(tmp_path)) == ["out.step"]


@needs_qt
def test_a_refusal_asks_whether_to_write_without_the_bodies(exporter, tmp_path):
    e = exporter()
    e.open("o02_boxA.SLDPRT")
    calls = []

    def fake(request, cancelled):
        calls.append(dict(request))
        if not request["allow_partial"]:
            return {
                "ok": False,
                "error": {"code": "not_representable", "reader_message": "1 of 2 bodies: Body2 (fit_failed)"},
            }
        return printing.export_in_process({**request, "allow_partial": False}, cancelled)

    e.window.step.export = fake
    e.answer = False
    outcome = e.press()
    assert outcome == {"ok": False, "error": outcome["error"], "declined": True}
    assert (
        "Body2 (fit_failed)" in e.questions[-1] and "Write the file without these bodies?" in e.questions[-1]
    )
    assert not os.path.exists(e.chosen)
    e.answer = True
    outcome = e.press()
    assert outcome["ok"] and [c["allow_partial"] for c in calls[-2:]] == [False, True]
    assert os.path.isfile(e.chosen)


@needs_qt
def test_a_name_without_an_extension_does_not_replace_a_step_file_unasked(exporter, tmp_path):
    """A save dialog that returns "foo" asked about "foo", not about the "foo.step" the
    export adds: replacing that one is asked about first."""
    e = exporter()
    e.open("o11_curved.SLDPRT")
    existing = tmp_path / "foo.step"
    existing.write_text("an earlier STEP file")
    e.chosen = str(tmp_path / "foo")
    e.answer = False
    e.window.act_step.trigger()
    e.app.processEvents()
    assert len(e.questions) == 1 and "foo.step already exists" in e.questions[0]
    assert not e.outcomes and existing.read_text() == "an earlier STEP file"
    e.answer = True
    outcome = e.press()
    assert outcome["ok"] and outcome["file"] == str(existing)
    assert existing.read_bytes().startswith(b"ISO-10303-21;")
    assert sorted(os.listdir(tmp_path)) == ["foo.step"]
    e.chosen = str(tmp_path / "new")  # no file of that name: nothing to ask
    outcome = e.press()
    assert outcome["ok"] and len(e.questions) == 2 and (tmp_path / "new.step").is_file()


@needs_qt
def test_export_step_does_not_run_twice_while_its_dialog_is_open(exporter, tmp_path):
    """A second trigger while the save dialog is open (a key the menu passed on twice)
    opens no second dialog."""
    e = exporter()
    e.open("o02_boxA.SLDPRT")
    asked = []

    def ask(suggested):
        asked.append(suggested)
        e.window.act_step.trigger()  # again, from inside the dialog
        return e.chosen

    e.window.step.ask_path = ask
    outcome = e.press()
    assert outcome["ok"] and len(asked) == 1 and os.path.isfile(e.chosen)
