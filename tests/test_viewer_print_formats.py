"""3D Print's formats: 3MF, STL and STEP (``solidseas_app.viewer.printing`` and
``.printaction``), the formats each program takes, the STEP a print sends and the
3MF it falls back to, and the self-test's checks of both.

As in ``test_viewer_print.py``: no program is ever started (the session-wide guard of
``conftest.py`` replaces the launcher, and each window records what it would start),
programs are found in made-up install folders, and every print is made on a copy of
the fixtures, never in ``tests/fixtures``. Each STEP written is read back with the
tests' own checker (``step_support``), which shares no code with the writer.
"""

import json
import os
import shutil
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

import step_support as T
from solidseas.errors import NothingToExportError, NotRepresentableError, SldLimitError
from solidseas_app.viewer import printing
from support import FIXTURES

try:
    import PySide6.QtWidgets  # noqa: F401
except ImportError:
    HAVE_QT = False
else:
    HAVE_QT = True

needs_qt = pytest.mark.skipif(not HAVE_QT, reason="PySide6 is not installed: the window is not tested")
TODAY = "2026-10-03"
O16 = "o16_asm_features.SLDASM"
PART = "o02_boxA.SLDPRT"


@pytest.fixture
def models(tmp_path) -> Path:
    """A copy of the fixtures folder, for prints to go next to their models."""
    folder = tmp_path / "models"
    shutil.copytree(FIXTURES, folder)
    return folder


def _export(models: Path, name: str, fmt: str, **kw) -> dict:
    kw.setdefault("date", TODAY)
    base = models.parent / "temp"
    base.mkdir(exist_ok=True)  # the system's temporary folder, always there
    return printing.export_for_print(str(models / name), str(models), fmt, out_base=str(base), **kw)


def _checked(path: str, data: dict | None = None) -> dict:
    """The tests' own checker on the STEP at ``path``: it must pass."""
    data = data or {}
    with open(path, "rb") as fh:
        got = T.file_check(
            fh.read(), deviation_mm=data.get("max_deviation_mm"), tolerance_mm=data.get("max_tolerance_mm")
        )
    assert got["problems"] == [], got["problems"]
    return got


# --------------------------------------------------------------------------- formats by program
def test_each_program_takes_its_formats_3mf_first():
    assert printing.FORMATS == ("3mf", "stl", "step")
    assert printing.FORMAT_LABELS == {"3mf": "3MF", "stl": "STL", "step": "STEP"}
    assert printing.EXTENSIONS == {"3mf": ".3mf", "stl": ".stl", "step": ".step"}
    takes = {s.key: s.formats for s in printing.SLICERS}
    assert takes == {
        "bambu": ("3mf", "stl", "step"),
        "orca": ("3mf", "stl", "step"),
        "prusa": ("3mf", "stl", "step"),
        "cura": ("3mf", "stl"),  # STEP only through a plug-in
    }
    other = printing.other_program("C:\\Tools\\slicer.exe")
    assert other.formats == ("3mf", "stl", "step")
    bambu = printing.Program("bambu", "Bambu Studio", "C:\\b.exe", takes["bambu"])
    cura = printing.Program("cura", "UltiMaker Cura", "C:\\c.exe", takes["cura"])
    assert printing.format_for(bambu, printing.PrintChoice("bambu")) == "3mf"  # until one is chosen
    assert printing.format_for(bambu, printing.PrintChoice("bambu", None, "step")) == "step"
    assert printing.format_for(cura, printing.PrintChoice("cura", None, "step")) == "3mf"


def test_a_format_the_next_program_does_not_take_falls_back_to_its_first():
    cura = printing.Program("cura", "UltiMaker Cura", "C:\\c.exe", ("3mf", "stl"))
    orca = printing.Program("orca", "OrcaSlicer", "C:\\o.exe", printing.FORMATS)
    step = printing.PrintChoice("bambu", None, "step")
    assert printing.format_dropped(step, cura) == "step"
    assert printing.with_program(step, cura) == printing.PrintChoice("cura", None, None)
    assert printing.format_dropped(step, orca) is None
    assert printing.with_program(step, orca) == printing.PrintChoice("orca", None, "step")
    assert printing.format_dropped(printing.PrintChoice("bambu"), cura) is None
    assert printing.dropped_text(step, cura) == ", sent as 3MF: it does not take STEP"
    assert printing.dropped_text(step, orca) == ""


def test_step_is_remembered_in_the_print_section():
    assert printing.parse_choice({"program": "bambu", "format": "STEP"}) == printing.PrintChoice(
        "bambu", None, "step"
    )
    assert printing.parse_choice({"program": "bambu", "format": "stp"}).format is None
    found = [printing.Program("bambu", "Bambu Studio", "C:\\b.exe", printing.FORMATS)]
    choice = printing.PrintChoice("bambu", None, "step")
    assert printing.describe(choice, found) == "Bambu Studio, sent as STEP"
    assert printing.describe(choice, found, with_format=False) == "Bambu Studio"


# --------------------------------------------------------------------------- the STEP a print sends
def test_a_part_prints_as_step_next_to_the_model_named_with_the_date(models):
    out = _export(models, PART, "step")
    assert out["file"] == str(models / f"o02_boxA {TODAY}.step") and out["place"] == printing.MODEL
    assert out["format"] == out["requested_format"] == "step" and out["format_fallback"] is None
    assert out["doc_type"] == "part" and out["closed"] and out["objects"] == 1 and out["triangles"] == 0
    assert out["step"]["exact"] and out["step"]["solids"] == 1 and out["step"]["faces"] == 6
    assert os.path.getsize(out["file"]) == out["bytes"]
    got = _checked(out["file"], out["step"])
    assert got["solids"] == 1 and got["file_name"] == f"o02_boxA {TODAY}.step"
    again = _export(models, PART, "step")
    assert again["file"] == str(models / f"o02_boxA {TODAY} (2).step")
    assert _checked(again["file"])["file_name"] == f"o02_boxA {TODAY} (2).step"  # its own name
    other = _export(models, PART, "3mf")  # each format counts its own
    assert other["file"] == str(models / f"o02_boxA {TODAY}.3mf") and other["step"] is None
    assert not [n for n in os.listdir(models) if n.endswith(".part")]


def test_a_curved_part_prints_as_its_exact_step(models):
    out = _export(models, "o11_curved.SLDPRT", "step")
    # 14 faces: o11's hole and the fillet round it each cut in two at their seams
    assert out["format"] == "step" and out["step"]["exact"] and out["step"]["faces"] == 14
    _checked(out["file"], out["step"])


def test_a_step_of_a_configuration_the_part_stores_no_bodies_of_is_its_active_ones(models):
    """As its 3MF does: the active configuration's bodies, named and said as such."""
    out = _export(models, "o06_boxA_props_mat_cfg.SLDPRT", "step", configuration="OracleAlt")
    assert out["format"] == "step" and out["format_fallback"] is None
    assert out["configuration"] == "Default" and out["requested_configuration"] == "OracleAlt"
    assert out["file"] == str(models / f"o06_boxA_props_mat_cfg {TODAY}.step")
    assert "mesh_configuration_differs" in [w["code"] for w in out["warnings"]]
    _checked(out["file"], out["step"])
    three = _export(models, "o06_boxA_props_mat_cfg.SLDPRT", "3mf", configuration="OracleAlt")
    assert three["configuration"] == out["configuration"]


def test_a_step_print_follows_the_same_fallback_to_the_temporary_folder(models):
    off = _export(models, PART, "step", next_to_model=False)
    temp = printing.export_folder_path(str(models.parent / "temp"))
    assert off["place"] == printing.TEMP and off["file"] == os.path.join(temp, f"o02_boxA {TODAY}.step")
    confined = _export(models, PART, "step", confine=str(models.parent / "elsewhere"))
    assert confined["fallback"] == printing.CONFINED
    assert confined["file"] == os.path.join(temp, f"o02_boxA {TODAY} (2).step")
    _checked(confined["file"])
    old = os.path.join(temp, "old 2026-01-01.step")
    Path(old).write_bytes(b"ISO-10303-21;")
    os.utime(old, (1, 1))
    assert printing.clean_old(temp) == 1 and not os.path.exists(old)  # a week old: removed from there only


# o16 places o06 in a configuration whose bodies o06 does not store: its STEP is refused.
O16_REFUSED = (
    "one of its instances cannot be written as STEP (o06_boxA_props_mat_cfg-1: the part does not store "
    "the bodies of configuration 'OracleAlt')"
)


def test_an_assembly_goes_as_step_and_one_it_cannot_write_as_3mf_saying_why(models):
    asm = _export(models, "o08_asm_2x_boxA.SLDASM", "step")
    assert asm["format"] == "step" and asm["format_fallback"] is None
    assert asm["file"] == str(models / f"o08_asm_2x_boxA {TODAY}.step")
    _checked(asm["file"], asm["step"])
    out = _export(models, O16, "step")
    assert out["file"] == str(models / f"o16_asm_features {TODAY}.3mf") and zipfile.is_zipfile(out["file"])
    assert out["format"] == "3mf" and out["requested_format"] == "step"
    assert out["format_fallback"] == O16_REFUSED and out["step"] is None
    assert out["items"] == 12 and out["triangles"] > 0
    assert not [n for n in os.listdir(models) if n.startswith("o16") and TODAY in n and n.endswith(".step")]


def _refusing(exc):
    def step_model(doc, configuration=None, **options):
        raise exc

    return step_model


def _body(name, reason, message):
    from solidseas.step import StepBody

    return StepBody(0, name, None, "solid", "partition", reason=reason, message=message)


@pytest.mark.parametrize(
    ("exc", "said"),
    [
        (
            NotRepresentableError(
                "1 of 1 bodies",
                detail={"rule": "fit_failed"},
                bodies=[_body("Boss", "fit_failed", "too far")],
            ),
            "STEP cannot hold a body of it without loss (Boss: too far)",
        ),
        (
            NotRepresentableError(
                "3 of 3 bodies",
                bodies=[_body(f"B{i}", "foreign_geometry", "foreign") for i in range(3)],
            ),
            "STEP cannot hold 3 bodies of it without loss (B0: foreign; B1: foreign; 1 more)",
        ),
        (
            SldLimitError("stopped", detail={"limit": "max_seconds"}),
            "the STEP export stopped at its limit of 300 seconds",
        ),
        (
            SldLimitError("faces", detail={"limit": "max_faces"}),
            "the part has more than the 200,000 faces the STEP export takes",
        ),
        (
            NothingToExportError("nothing to export: only sheets", detail={"rule": "sheets_not_asked"}),
            "the part's bodies are surfaces, which a slicer cannot print from a STEP",
        ),
        (
            NothingToExportError("nothing to export: the document stores no solid body"),
            "the STEP export found nothing to write: the document stores no solid body",
        ),
    ],
)
def test_a_part_the_step_export_refuses_goes_as_3mf_and_says_why(models, monkeypatch, exc, said):
    import solidseas.step as S

    monkeypatch.setattr(S, "step_model", _refusing(exc))
    assert printing.step_refusal(exc) == said
    out = _export(models, PART, "step")
    assert out["format"] == "3mf" and out["requested_format"] == "step" and out["format_fallback"] == said
    assert out["file"] == str(models / f"o02_boxA {TODAY}.3mf") and zipfile.is_zipfile(out["file"])
    assert not [n for n in os.listdir(models) if n.endswith(".part") or (TODAY in n and n.endswith(".step"))]


def test_a_partial_step_is_never_sent(models, monkeypatch):
    """Bodies are never left out on request; should a STEP come back partial all the
    same, it goes as 3MF."""
    import solidseas.step as S

    real = S.step_model
    asked = []

    def partial(doc, configuration=None, **options):
        asked.append(options)
        return replace(real(doc, configuration, **options), partial=True)

    monkeypatch.setattr(S, "step_model", partial)
    out = _export(models, PART, "step")
    assert out["format"] == "3mf" and out["format_fallback"] == printing.STEP_PARTIAL
    assert asked and not any(o.get("allow_partial") for o in asked)


@pytest.mark.parametrize("next_to_model", [True, False])
def test_a_step_past_its_file_size_limit_goes_as_3mf_and_says_why(models, monkeypatch, next_to_model):
    """The size limit is found only as the STEP is written, after the model is made: the
    part is removed and the document is exported again as 3MF, next to the model or in
    the temporary folder as the STEP would have been."""
    import functools

    import solidseas.step as S

    monkeypatch.setattr(S, "write_step", functools.partial(S.write_step, max_bytes=100))
    said = "its STEP file would be larger than the 2 GiB the STEP export writes"
    assert printing.step_refusal(SldLimitError("big", detail={"limit": "max_bytes"})) == said
    out = _export(models, PART, "step", next_to_model=next_to_model)
    assert out["format"] == "3mf" and out["requested_format"] == "step" and out["format_fallback"] == said
    folder = str(models) if next_to_model else printing.export_folder_path(str(models.parent / "temp"))
    assert out["file"] == os.path.join(folder, f"o02_boxA {TODAY}.3mf") and zipfile.is_zipfile(out["file"])
    assert out["step"] is None and out["triangles"] > 0 and out["seconds"] >= 0
    for where in (models, Path(printing.export_folder_path(str(models.parent / "temp")))):
        left = os.listdir(where) if where.is_dir() else []
        assert not [n for n in left if n.endswith(".part") or (TODAY in n and n.endswith(".step"))]
    monkeypatch.undo()
    again = _export(models, PART, "step", next_to_model=next_to_model)  # its own numbering
    assert again["format"] == "step" and again["file"] == os.path.join(folder, f"o02_boxA {TODAY}.step")


def test_an_unknown_print_format_is_refused(models):
    from solidseas.errors import InvalidArgumentError

    with pytest.raises(InvalidArgumentError):
        _export(models, PART, "obj")
    assert not [n for n in os.listdir(models) if TODAY in n]


def test_a_step_print_runs_in_the_export_process(models):
    request = {
        "path": str(models / PART),
        "folder": str(models),
        "fmt": "step",
        "out_base": str(models.parent / "temp"),
        "date": TODAY,
    }
    (models.parent / "temp").mkdir(exist_ok=True)
    result = printing.export_in_process(request)
    assert result["ok"], result
    assert result["data"]["file"] == str(models / f"o02_boxA {TODAY}.step")
    _checked(result["data"]["file"])
    answers = iter([False])  # cancelled once the process is started
    cancelled = printing.export_in_process(
        {**request, "path": str(models / "o11_curved.SLDPRT")}, lambda: next(answers, True)
    )
    assert cancelled == printing.CANCELLED
    assert not [n for n in os.listdir(models) if n.endswith(".part") or n.startswith("o11_curved 20")]


def test_a_step_print_out_of_memory_says_to_send_another_format(monkeypatch):
    sent = []

    class Conn:  # the export's pipe carries JSON both ways
        def recv_bytes(self, maxlength=None):
            return json.dumps({"path": "x", "folder": "y", "fmt": "step"}).encode()

        def send_bytes(self, result):
            sent.append(json.loads(result))

    def boom(**request):
        raise MemoryError

    monkeypatch.setattr(printing, "export_for_print", boom)
    printing._export_serve(Conn())
    assert sent[0]["error"]["code"] == "print_export_too_large"
    assert "Send it as 3MF or STL instead" in sent[0]["error"]["message"]


# --------------------------------------------------------------------------- the window
@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from solidseas_app.viewer.app import use_system_fonts

    use_system_fonts()
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _wait(app, condition, timeout: float = 60.0) -> None:
    import time

    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            raise AssertionError("timed out waiting for the viewer")
        app.processEvents()
        time.sleep(0.005)


def _install(root: Path, rel: str) -> Path:
    exe = root / rel
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"MZ")
    exe.chmod(0o755)
    return exe


@pytest.fixture
def programs(tmp_path) -> dict:
    """Bambu Studio and Cura in a made-up Program Files."""
    pf = tmp_path / "Program Files"
    pf.mkdir()
    env = {"ProgramW6432": str(pf), "ProgramFiles": str(pf)}
    bambu = _install(pf, "Bambu Studio/bambu-studio.exe")
    cura = _install(pf, "UltiMaker Cura 5.7.1/UltiMaker-Cura.exe")
    found = printing.detect(env, app_path=lambda exe: None, windows=True)
    return {"env": env, "bambu": bambu, "cura": cura, "found": found}


class Printer:
    def __init__(self, app, tmp: Path, detected, store=None) -> None:
        from solidseas_app.viewer.window import MainWindow

        self.app = app
        self.window = MainWindow(store)
        self.window.show()
        self.started: list[tuple[str, str]] = []
        self.outcomes: list[dict] = []
        p = self.window.printer
        p.detect = lambda: list(detected)
        p.launch = lambda program, path: self.started.append((program, path))
        p.today = lambda: TODAY
        self.messages: list[str] = []
        p._message = lambda icon, text: self.messages.append(text)
        tmp.mkdir(exist_ok=True)
        p.out_base = str(tmp)
        p.finished.connect(self.outcomes.append)
        self.finished: list[int] = []
        self.window.detailsFinished.connect(self.finished.append)

    def open(self, folder: Path, name: str) -> None:
        self.window.open_folder(str(folder))
        _wait(self.app, lambda: self.window.listing_info is not None)
        assert self.window.select_document(name), name
        generation = self.window.generation
        _wait(self.app, lambda: generation in self.finished)

    def choose(self, action) -> dict:
        n = len(self.outcomes)
        action.trigger()
        _wait(self.app, lambda: len(self.outcomes) > n)
        return self.outcomes[-1]

    def close(self) -> None:
        assert self.window.shutdown()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()


@pytest.fixture
def printer(app, tmp_path, programs):
    made = []

    def make(store=None) -> Printer:
        p = Printer(app, tmp_path / "temp", programs["found"], store)
        made.append(p)
        return p

    yield make
    for p in made:
        p.close()


def _menu_texts(menu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def _action(menu, text: str):
    return next(a for a in menu.actions() if a.text() == text)


@needs_qt
def test_the_program_menu_offers_the_formats_the_program_takes(printer, programs, tmp_path):
    from solidseas_app.viewer.settings import SettingsStore

    store = SettingsStore(str(tmp_path / "Viewer.ini"))
    p = printer(store)
    c = p.window.printer
    c.fill_menu()
    texts = _menu_texts(c.menu)
    assert texts[-3:] == ["Send as 3MF", "Send as STL", "Send as STEP"]  # Bambu Studio's, until chosen
    assert [a.text() for a in c.menu.actions() if a.isChecked()] == ["Bambu Studio", "Send as 3MF"]
    assert "exact faces and edges" in _action(c.menu, "Send as STEP").toolTip()
    _action(c.menu, "Send as STEP").trigger()
    assert printing.load_choice(SettingsStore(str(tmp_path / "Viewer.ini"))) == printing.PrintChoice(
        "bambu", None, "step"
    )
    assert p.window.statusBar().currentMessage() == "3D Print now sends STEP to Bambu Studio."
    _action(c.menu, "UltiMaker Cura").trigger()
    assert c.choice == printing.PrintChoice("cura", None, None)  # its first: 3MF
    assert p.window.statusBar().currentMessage() == (
        "3D Print now opens UltiMaker Cura, sent as 3MF: it does not take STEP."
    )
    assert _menu_texts(c.menu)[-2:] == ["Send as 3MF", "Send as STL"]  # no STEP for Cura
    assert "Send as STEP" not in _menu_texts(c.menu)
    assert [a.text() for a in c.menu.actions() if a.isChecked()] == ["UltiMaker Cura", "Send as 3MF"]
    _action(c.menu, "Bambu Studio").trigger()  # nothing to drop: no message about the format
    assert p.window.statusBar().currentMessage() == "3D Print now opens Bambu Studio."
    q = printer()
    q.window.printer.detect = lambda: []
    q.window.printer.fill_menu()
    assert not [t for t in _menu_texts(q.window.printer.menu) if t.startswith("Send as")]


@needs_qt
def test_preferences_offer_the_formats_of_the_program_and_remember_one(printer, programs, tmp_path):
    from solidseas_app.viewer.preferences import PreferencesDialog
    from solidseas_app.viewer.settings import SettingsStore

    store = SettingsStore(str(tmp_path / "Viewer.ini"))
    p = printer(store)
    w = p.window
    options = w.printer.preferences_options()
    assert options == {
        "print_text": "Bambu Studio, found here and used until you choose another",
        "print_formats": ("3mf", "stl", "step"),
        "print_format": "3mf",
    }
    dialog = PreferencesDialog(w, w.settings, store.path, **options)
    dialog.print_format_chosen.connect(w.printer.set_format)
    combo = dialog.print_format
    assert [combo.itemText(i) for i in range(combo.count())] == ["3MF", "STL", "STEP"]
    assert combo.currentText() == "3MF" and dialog.chosen_format() == "3mf"
    assert (
        dialog.print_program.text()
        == "3D Print program: Bambu Studio, found here and used until you choose another"
    )
    chosen = []
    dialog.print_format_chosen.connect(chosen.append)
    dialog._apply()  # unchanged: nothing remembered
    assert chosen == [] and printing.load_choice(store) == printing.PrintChoice()
    combo.setCurrentIndex(combo.findData("step"))
    dialog._apply()
    assert chosen == ["step"]
    assert printing.load_choice(SettingsStore(str(tmp_path / "Viewer.ini"))) == printing.PrintChoice(
        "bambu", None, "step"
    )
    dialog.restore_defaults()
    assert dialog.chosen_format() == "3mf"
    dialog.deleteLater()
    w.printer.set_program(next(x for x in programs["found"] if x.key == "cura"))
    options = w.printer.preferences_options()
    assert options["print_formats"] == ("3mf", "stl") and options["print_format"] == "3mf"
    dialog = PreferencesDialog(w, w.settings, store.path, **options)
    assert dialog.print_program.text() == "3D Print program: UltiMaker Cura"
    assert [dialog.print_format.itemData(i) for i in range(dialog.print_format.count())] == ["3mf", "stl"]
    dialog.deleteLater()
    none = printer()
    none.window.printer.detect = lambda: []
    options = none.window.printer.preferences_options()
    assert options["print_formats"] == () and "no known program found" in options["print_text"]
    bare = PreferencesDialog(none.window, none.window.settings, None, **options)
    assert bare.print_format is None and bare.chosen_format() is None
    bare.deleteLater()


@needs_qt
def test_the_button_and_every_right_click_entry_send_the_chosen_format(printer, programs, models):
    p = printer()
    c = p.window.printer
    c.set_format("step")
    p.open(models, PART)
    outcome = p.choose(c.action)
    assert outcome["ok"] and outcome["format"] == "step", (outcome, p.messages)
    assert outcome["file"] == str(models / f"o02_boxA {TODAY}.step")
    assert p.started == [(os.path.normpath(programs["bambu"]), outcome["file"])]
    assert p.window.statusBar().currentMessage().startswith(f"Saved {outcome['file']} and opened it in Bambu")
    _checked(outcome["file"], outcome["step"])
    # The document list's right-click entry for the assembly: STEP asked, 3MF sent, and why.
    from PySide6.QtWidgets import QMenu

    menu = QMenu()
    c.add_action(menu, "3D Print o16", lambda: p.window.entry_print_target(_row(p, O16)))
    sent = p.choose(menu.actions()[0])
    assert sent["ok"] and sent["format"] == "3mf" and sent["requested_format"] == "step"
    assert sent["file"] == str(models / f"o16_asm_features {TODAY}.3mf")
    note = p.window.statusBar().currentMessage()
    assert f"(sent as 3MF, not STEP, as {O16_REFUSED})" in note and sent["note"] == note
    # The part's own entry: STEP, numbered after the button's.
    menu.clear()
    c.add_action(menu, "3D Print o02_boxA", lambda: p.window.entry_print_target(_row(p, PART)))
    again = p.choose(menu.actions()[0])
    assert again["format"] == "step" and again["file"] == str(models / f"o02_boxA {TODAY} (2).step")
    menu.deleteLater()


@needs_qt
def test_a_program_chosen_when_asked_that_does_not_take_the_format_says_so(app, tmp_path, programs, models):
    from solidseas_app.viewer.settings import SettingsStore

    store = SettingsStore(str(tmp_path / "Viewer.ini"))
    store.save_section(printing.SECTION, {"format": "step"})  # a format, and no program yet
    cura = next(x for x in programs["found"] if x.key == "cura")
    p = Printer(app, tmp_path / "temp", [cura], store)
    try:
        p.window.printer.ask = lambda detected: cura
        p.open(models, PART)
        outcome = p.choose(p.window.printer.action)
        assert outcome["ok"] and outcome["format"] == "3mf" and outcome["file"].endswith(".3mf")
        assert outcome["note"].endswith(
            "UltiMaker Cura is now the 3D Print program, sent as 3MF: it does not take STEP."
        )
        assert p.window.printer.choice == printing.PrintChoice("cura", None, None)
    finally:
        p.close()


@needs_qt
def test_the_progress_message_names_the_format_the_document_is_made_in(printer, programs, models):
    """Asked for as STEP, an assembly is made as 3MF, and the status line says so while
    it is exported; a part is made as STEP."""
    from PySide6.QtWidgets import QMenu

    p = printer()
    c = p.window.printer
    c.set_format("step")

    def started(trigger) -> tuple[str, dict]:
        n = len(p.outcomes)
        trigger()
        said = p.window.statusBar().currentMessage()
        _wait(p.app, lambda: len(p.outcomes) > n)
        return said, p.outcomes[-1]

    p.open(models, O16)
    said, sent = started(c.action.trigger)
    # an assembly is made as STEP, as far as the listing can tell; o16's turns out to need 3MF
    assert said.startswith(f"Preparing the STEP of {O16} for Bambu Studio..."), said
    assert sent["format"] == "3mf" and sent["format_fallback"] == O16_REFUSED
    menu = QMenu()
    c.add_action(menu, "3D Print o16", lambda: p.window.entry_print_target(_row(p, O16)))
    c.add_action(menu, "3D Print o02_boxA", lambda: p.window.entry_print_target(_row(p, PART)))
    said, _ = started(menu.actions()[0].trigger)
    assert said.startswith(f"Preparing the STEP of {O16} "), said
    said, sent = started(menu.actions()[1].trigger)
    assert said.startswith(f"Preparing the STEP of {PART} "), said
    assert sent["format"] == "step"
    menu.deleteLater()
    assert p.window.entry_print_target(_row(p, PART)).doc_type == "part"
    assert p.window.print_target().doc_type == "assembly"


def _row(p, name):
    return next(r for r in p.window.model.rows if r.entry["path"].endswith(name)).entry


# --------------------------------------------------------------------------- the self-test
@needs_qt
def test_the_self_test_prints_each_format_and_checks_it(app, tmp_path, programs, models):
    from PySide6.QtCore import QTimer

    from solidseas_app.viewer.selftest import SelfTest
    from solidseas_app.viewer.window import MainWindow

    reports = {}
    for fmt in ("step", "stl"):
        window = MainWindow()
        window.resize(1200, 800)
        window.show()
        window.printer.detect = lambda: list(programs["found"])
        window.printer.today = lambda: TODAY
        (tmp_path / "temp").mkdir(exist_ok=True)
        window.printer.out_base = str(tmp_path / "temp")
        shots = tmp_path / f"shots-{fmt}"
        st = SelfTest(
            window,
            str(models),
            screenshot_dir=None,
            report=str(shots / "selftest.json"),
            select=[PART, O16],
            print_dry_run=True,
            print_format=fmt,
        )
        shots.mkdir()
        QTimer.singleShot(0, st.start)
        assert app.exec() == 0
        window.shutdown()
        window.close()
        reports[fmt] = json.loads((shots / "selftest.json").read_text(encoding="utf-8"))
    step = reports["step"]
    assert step["ok"], (step["errors"], [d["errors"] for d in step["documents"]])
    assert step["print_format"] == "step"
    part, asm = step["documents"]
    assert [c["file"] for c in part["print_checks"]] == [
        str(models / f"o02_boxA {TODAY}.step"),
        str(models / f"o02_boxA {TODAY} (2).step"),
    ]
    for check in part["print_checks"]:
        assert check["format"] == "step" and check["step_check"]["problems"] == []
        assert (
            check["step_check"]["solids"] == 1 and check["step_check"]["checker"] == "tests/step_support.py"
        )
    assert [c["file"] for c in asm["print_checks"]] == [
        str(models / f"o16_asm_features {TODAY}.3mf"),
        str(models / f"o16_asm_features {TODAY} (2).3mf"),
    ]
    assert all(c["format_fallback"] == O16_REFUSED for c in asm["print_checks"])
    stl = reports["stl"]
    assert stl["ok"], (stl["errors"], [d["errors"] for d in stl["documents"]])
    assert [os.path.basename(c["file"]) for d in stl["documents"] for c in d["print_checks"]] == [
        f"o02_boxA {TODAY}.stl",
        f"o02_boxA {TODAY} (2).stl",
        f"o16_asm_features {TODAY}.stl",
        f"o16_asm_features {TODAY} (2).stl",
    ]


@needs_qt
def test_the_self_test_fails_a_step_the_checker_refuses_or_a_fallback_without_reason(
    app, tmp_path, programs, monkeypatch
):
    """The checks themselves: a STEP that is not one fails the run's check, and so does a
    3MF sent in place of a STEP without its reason said. A 3D file is judged by what it
    holds (the print's source_format), not by its name: a STEP saved as .SLDPRT must go
    as 3MF for being a STEP, and a Parasolid file saved as .step may go as STEP."""
    from solidseas_app.viewer.selftest import SelfTest, check_step_file
    from solidseas_app.viewer.window import MainWindow

    bad = tmp_path / "bad.step"
    bad.write_bytes(b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n")
    got = check_step_file(str(bad))
    assert got["checker"] == "tests/step_support.py" and got["problems"]
    window = MainWindow()
    (tmp_path / "f").mkdir()
    st = SelfTest(
        window, str(tmp_path / "f"), screenshot_dir=None, report=str(tmp_path / "r.json"), select=[]
    )
    st.print_format = "step"
    rec: dict = {}
    file = str(tmp_path / f"x {TODAY}.3mf")
    no_reason = {
        "file": file,
        "format": "3mf",
        "requested_format": "step",
        "format_fallback": None,
        "note": "",
    }
    assert st._check_format(rec, no_reason, ".3mf") == ["sent as 3mf, not step, without a reason"]
    wrong_ext = {"file": file, "format": "step", "requested_format": "step", "note": ""}
    shutil.copy(bad, file)
    problems = st._check_format(rec, wrong_ext, ".3mf")
    assert problems[0] == f"x {TODAY}.3mf does not end in step's extension" and len(problems) > 1
    reason = printing.step_unavailable("step", "part")
    inside = {
        "file": file,
        "format": "3mf",
        "requested_format": "step",
        "format_fallback": reason,
        "note": f"Saved {file} (sent as 3MF, not STEP, as {reason}).",
        "source": str(tmp_path / "f" / "stepinside.SLDPRT"),
        "source_format": "step",
        "doc_type": "part",
    }
    assert st._check_format(rec, inside, ".3mf") == []
    partial = {**inside, "format_fallback": printing.STEP_PARTIAL, "note": printing.STEP_PARTIAL}
    assert st._check_format(rec, partial, ".3mf") == [
        "a step file asked for as STEP did not go as 3MF for its format"
    ]
    monkeypatch.setattr(
        "solidseas_app.viewer.selftest.check_step_file", lambda path, data=None: {"problems": []}
    )
    para = {
        **inside,
        "file": str(tmp_path / f"para {TODAY}.step"),
        "format": "step",
        "format_fallback": None,
        "source": str(tmp_path / "f" / "para.step"),
        "source_format": "parasolid",
    }
    assert st._check_format(rec, para, ".step") == []
    window.close()
    window.deleteLater()


@needs_qt
def test_the_self_test_fails_a_format_run_that_finds_no_program(app, tmp_path, models):
    """With no 3D print program found the window would ask, so nothing is written in any
    format: a run asked to check one fails, once, rather than pass having checked
    nothing."""
    from PySide6.QtCore import QTimer

    from solidseas_app.viewer.selftest import SelfTest
    from solidseas_app.viewer.window import MainWindow

    window = MainWindow()
    window.resize(1200, 800)
    window.show()
    window.printer.detect = lambda: []
    (tmp_path / "temp").mkdir()
    window.printer.out_base = str(tmp_path / "temp")
    shots = tmp_path / "shots"
    shots.mkdir()
    st = SelfTest(
        window,
        str(models),
        screenshot_dir=None,
        report=str(shots / "selftest.json"),
        select=[PART, O16],
        print_dry_run=True,
        print_format="step",
    )
    QTimer.singleShot(0, st.start)
    assert app.exec() == 1  # failed
    window.shutdown()
    window.close()
    report = json.loads((shots / "selftest.json").read_text(encoding="utf-8"))
    assert not report["ok"]
    said = {"where": "print_format", "error": "no 3D print program found to send STEP to"}
    assert report["errors"].count(said) == 1, report["errors"]
    for doc in report["documents"]:
        assert [c["would_ask"] for c in doc["print_checks"]] == [True]
        assert doc["print_checks"][0]["problems"] and doc["errors"]
    assert not [n for n in os.listdir(models) if TODAY in n or n.endswith(".part")]


@needs_qt
def test_the_self_test_waits_for_a_step_print_past_the_step_exports_limit(app, tmp_path, programs):
    """A STEP print may run to the STEP export's 300 seconds and then be made as 3MF:
    its wait is the STEP export's and a print's, others' a print's."""
    from solidseas_app.viewer import selftest
    from solidseas_app.viewer.selftest import SelfTest
    from solidseas_app.viewer.window import MainWindow

    window = MainWindow()
    window.printer.detect = lambda: list(programs["found"])
    (tmp_path / "f").mkdir()
    st = SelfTest(
        window, str(tmp_path / "f"), screenshot_dir=None, report=str(tmp_path / "r.json"), select=[]
    )
    long = selftest.STEP_TIMEOUT_S + selftest.DOC_TIMEOUT_S
    assert selftest.STEP_TIMEOUT_S > 300
    window.printer.set_format("step")
    assert st._print_timeout() == long
    doc: dict = {"errors": []}
    got = []
    st._await_print(doc, lambda: None, got.append)  # pressed, and nothing started
    assert st.timer.isActive() and st.timer.interval() == int(long * 1000)
    window.printer.finished.emit({"ok": False})
    assert got == [{"ok": False}] and not st.timer.isActive()
    window.printer.set_format("stl")
    assert st._print_timeout() == selftest.DOC_TIMEOUT_S
    window.printer.set_program(next(x for x in programs["found"] if x.key == "cura"))
    window.printer.set_format("3mf")
    assert st._print_timeout() == selftest.DOC_TIMEOUT_S
    window.printer.detect = lambda: []
    window.printer.detected(refresh=True)
    assert st._print_timeout() == selftest.DOC_TIMEOUT_S
    window.close()
    window.deleteLater()


@needs_qt
def test_the_self_test_exports_step_into_a_temporary_folder_and_checks_it(app, tmp_path, models, monkeypatch):
    from PySide6.QtCore import QTimer

    from solidseas_app.viewer.selftest import SelfTest
    from solidseas_app.viewer.window import MainWindow

    made = []
    real = __import__("tempfile").mkdtemp

    def mkdtemp(**kw):
        made.append(real(dir=str(tmp_path), **kw))
        return made[-1]

    monkeypatch.setattr("solidseas_app.viewer.selftest.tempfile.mkdtemp", mkdtemp)
    window = MainWindow()
    window.resize(1200, 800)
    window.show()
    shots = tmp_path / "shots"
    shots.mkdir()
    st = SelfTest(
        window,
        str(models),
        screenshot_dir=None,
        report=str(shots / "selftest.json"),
        select=["o11_curved.SLDPRT", O16],
        export_step=True,
    )
    QTimer.singleShot(0, st.start)
    assert app.exec() == 0
    window.shutdown()
    window.close()
    report = json.loads((shots / "selftest.json").read_text(encoding="utf-8"))
    assert report["ok"], (report["errors"], [d["errors"] for d in report["documents"]])
    part, asm = (d["export_step"] for d in report["documents"])
    assert part["ok"] and part["file"] == "o11_curved.step" and part["exact"] and part["faces"] == 14
    assert part["step_check"]["problems"] == [] and part["step_check"]["solids"] == 1
    assert part["message"].startswith("Wrote ") and "kept_in" not in part
    assert asm["available"] and asm.get("declined") == "instances_left_out" and not asm.get("problems"), asm
    assert asm["questions"] == [
        "Nothing was written: some of the assembly's components cannot be written as STEP."
    ]
    assert len(made) == 2 and not any(map(os.path.exists, made))  # a folder each, removed once checked
    assert not [n for n in os.listdir(models) if n.endswith(".step") and n not in os.listdir(FIXTURES)]


@pytest.mark.parametrize(
    ("args", "said"),
    [
        (["--print-format", "step"], "--print-format goes with --print-dry-run"),
        (["--export-step", "--select-all"], "--export-step goes with --select, not --select-all"),
    ],
)
def test_the_self_tests_format_options_are_checked(tmp_path, capsys, monkeypatch, args, said):
    from solidseas_app.viewer import app as viewer_app

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    code = viewer_app.main(["--self-test", str(tmp_path), "--report", str(tmp_path.parent / "r.json"), *args])
    assert code == viewer_app.EXIT_USAGE and said in capsys.readouterr().err
    code = viewer_app.main(["--print-format", "stl"])
    assert (
        code == viewer_app.EXIT_USAGE
        and "--export-step and --force go with --self-test" in capsys.readouterr().err
    )
