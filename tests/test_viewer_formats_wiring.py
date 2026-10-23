"""Where 3D files of other formats meet the viewer's features: STEP for 3D Print and File >
Export STEP (a Parasolid file's part through the same mapper as a SOLIDWORKS part, every
other format refused with its reason), Open 3MF and STL Files As They Are keeping its
meaning (a file goes as it is when it is sent in the format it holds and its name says,
a 3MF asked for as STEP included), a file judged by what it holds rather than its name,
print files marked with their source's extension beside a document of the same name,
the self-test's --export-step on such files, Where Used saying such files are not
indexed, and the 3D view's camera coming back with Back for a model file's assembly.

As in ``test_viewer_print_formats.py``: every print is made on a copy of the fixtures
and the samples, never in ``tests/fixtures``, nothing is started, and each STEP written is
read back with the tests' own checker (``step_support``), which shares no code with the
writer.
"""

import json
import os
import shutil
import time
from dataclasses import replace
from pathlib import Path

import pytest

import step_support as T
from solidseas import cli, open_document
from solidseas.errors import ConfigurationNotFoundError, UnsupportedOperationError
from solidseas.formats import open_any
from solidseas.step import BODY_FILE_FORMATS, MODEL_FILE_FORMATS, step_model, write_step
from solidseas_app.viewer import printing, samples, stepexport
from support import FIXTURES

try:
    import PySide6.QtWidgets  # noqa: F401
except ImportError:
    HAVE_QT = False
else:
    HAVE_QT = True

needs_qt = pytest.mark.skipif(not HAVE_QT, reason="PySide6 is not installed: the window is not tested")
TODAY = "2026-10-03"


@pytest.fixture
def models(tmp_path) -> Path:
    """A copy of the fixtures with every sample format beside them."""
    folder = tmp_path / "models"
    shutil.copytree(FIXTURES, folder)
    samples.write_samples(str(folder))
    return folder


def _export(models: Path, name: str, fmt: str, **kw) -> dict:
    kw.setdefault("date", TODAY)
    base = models.parent / "temp"
    base.mkdir(exist_ok=True)
    return printing.export_for_print(str(models / name), str(models), fmt, out_base=str(base), **kw)


def _checked(path: str, data: dict | None = None) -> dict:
    data = data or {}
    with open(path, "rb") as fh:
        got = T.file_check(
            fh.read(), deviation_mm=data.get("max_deviation_mm"), tolerance_mm=data.get("max_tolerance_mm")
        )
    assert got["problems"] == [], got["problems"]
    return got


# --------------------------------------------------------------------------- the library
@pytest.mark.parametrize(
    ("transmit", "part"),
    [
        ("o02_boxA.x_t", "o02_boxA.SLDPRT"),
        ("o02_boxA.x_b", "o02_boxA.SLDPRT"),
        ("o07_boxB_h31.x_b", "o07_boxB_h31.SLDPRT"),
        ("o11_curved.x_b", "o11_curved.SLDPRT"),
    ],
)
def test_a_parasolid_file_maps_to_step_as_its_solidworks_part_does(tmp_path, transmit, part):
    """The transmit SOLIDWORKS exported goes through the same mapper as the part's own
    bodies: the same solids, faces, edges and vertices, exact, and a file the checker
    passes, saying where its bodies came from."""
    with open_any(str(FIXTURES / transmit)) as doc:
        m = step_model(doc)
    with open_document(str(FIXTURES / part)) as sw:
        want = step_model(sw)
    for key in ("solids", "sheets", "faces", "edges", "vertices", "bodies"):
        assert m.counts[key] == want.counts[key], key
    assert m.exact and not m.partial and m.source_format == "parasolid" and want.source_format == "solidworks"
    assert m.name == os.path.splitext(transmit)[0] and m.originating_system.startswith("SOLIDWORKS")
    assert "step_hidden_bodies_unknown" not in {w.code for w in m.warnings}
    out = tmp_path / "out.step"
    write_step(m, str(out))
    got = _checked(str(out))
    assert got["solids"] == m.counts["solids"]


def test_other_model_files_are_refused_by_the_step_export_with_their_reason():
    # The viewer offers STEP for Parasolid files; the parts other readers build bodies of
    # (BODY_FILE_FORMATS) are written by the library and the command line only, for now.
    assert set(MODEL_FILE_FORMATS) - set(BODY_FILE_FORMATS) == {"parasolid"} < set(printing.STEP_SOURCES)
    with open_any(str(FIXTURES / "o02_boxA.step")) as doc:
        m = step_model(doc)
    assert m.source_format == "step" and m.counts["faces"] == 6 and m.exact
    for name, fmt in (("o02_boxA.STL", "stl"), ("o02_boxA.3mf", "3mf")):
        with open_any(str(FIXTURES / name)) as doc:
            with pytest.raises(UnsupportedOperationError) as info:
                step_model(doc)
        assert info.value.code == "not_implemented"
        assert info.value.detail == {"rule": "model_file", "value": fmt}
    with open_any(str(FIXTURES / "o12_multibody.x_b")) as doc:  # SOLIDWORKS writes it as an assembly
        assert doc.doc_type == "assembly"  # of its bodies, each at the identity: one part with two
        assert step_model(doc).counts["solids"] == 2  # (tests/test_step_multibody.py)
    with open_any(str(FIXTURES / "o02_boxA.x_t")) as doc:
        with pytest.raises(ConfigurationNotFoundError):
            step_model(doc, "Lite")


def test_the_command_line_exports_a_parasolid_file_as_step(tmp_path, capsys):
    out = tmp_path / "box.step"
    code = cli.main(["export", str(FIXTURES / "o02_boxA.x_t"), "--format", "step", "-o", str(out), "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert code == 0 and doc["ok"], doc
    data = doc["data"]
    assert data["format"] == "step" and data["source_format"] == "parasolid" and data["step"]["exact"]
    _checked(str(out))
    code = cli.main(["export", str(FIXTURES / "o02_boxA.STL"), "--format", "step", "-o", str(tmp_path)])
    capsys.readouterr()
    assert code == 1 and not (tmp_path / "o02_boxA.step").exists()


# --------------------------------------------------------------------------- 3D Print
def test_why_a_document_cannot_go_as_step_is_said_from_its_format():
    u = printing.step_unavailable
    assert u(None, "part") is None and u("solidworks", "part") is None and u("parasolid", "part") is None
    assert u(None, "assembly") is None and u("solidworks", "assembly") is None  # written as an assembly
    assert u("3mf", "assembly") == u("3mf", "part")  # a 3MF's own reason
    assert u("parasolid", "assembly") is None  # a multi-body part's .x_b: the export tells it from one
    assert u(None, "drawing") == u("solidworks", "drawing") == printing.STEP_DRAWING
    assert u("stl", "part") == "STL files hold triangles, not the exact faces and edges a STEP is made of"
    assert u("gltf", "part") == "glTF files hold triangles, not the exact faces and edges a STEP is made of"
    assert u("step", "part") == (
        "SolidSeas writes STEP from Parasolid bodies (SOLIDWORKS parts and Parasolid files), "
        "not from STEP files"
    )
    assert u("alibre", "part").endswith("not from Alibre Design files")
    assert u("acis", "part").endswith("not from ACIS files")
    assert printing.format_of("a.SLDPRT") is None and printing.format_of("a.x_b") == "parasolid"
    assert printing.format_of("a.stl") == "stl" and printing.format_of("a.txt") is None


def test_open_as_they_are_is_about_3mf_and_stl_only():
    assert printing.as_is("a.stl", "stl", "stl") and printing.as_is("a.3MF", "3mf", "3mf")
    assert not printing.as_is("a.stl", "3mf", "stl") and not printing.as_is("a.3mf", "stl", "3mf")
    assert not printing.as_is("a.step", "step", "step") and not printing.as_is("a.stp", "step", "step")


def test_a_reason_begins_a_sentence_without_changing_a_format_s_name():
    """Export STEP's tooltip is its reason as a sentence: a format's name keeps its case."""
    from solidseas_app.viewer.wording import sentence

    for fmt in ("gltf", "stl", "3mf", "step", "acis", "alibre"):
        why = printing.step_unavailable(fmt, "part")
        assert sentence(why).split(" ", 1)[0] == why.split(" ", 1)[0], why  # each begins with a name
    assert sentence(printing.STEP_PARTIAL).startswith("The STEP export would have left bodies out")
    assert sentence("glTF files hold triangles") == "glTF files hold triangles"
    assert sentence("eDrawings parts") == "eDrawings parts" and sentence("") == ""


def test_open_as_they_are_goes_by_what_a_file_holds_and_its_name():
    """A file whose name and content disagree is never handed over as it is: the slicer
    goes by the name, so it would read the file as a format it does not hold."""
    assert not printing.as_is("meshonly.3mf", "3mf", "stl")  # an STL saved as .3mf
    assert not printing.as_is("project.stl", "stl", "3mf")  # a 3MF saved as .stl
    assert not printing.as_is("box.stl", "stl", None)  # what it holds is not known
    assert not printing.as_is("box.SLDPRT", "3mf", "3mf")  # its name is not a 3MF's


def test_the_format_a_print_goes_in_is_known_before_it_is_read():
    s = printing.sent_format
    assert s("step", None, "part") == ("step", None) and s("step", "parasolid", "part") == ("step", None)
    assert s("step", "3mf", "part") == ("3mf", printing.step_unavailable("3mf", "part"))
    assert s("step", None, "assembly") == ("step", None)  # a SOLIDWORKS assembly goes as STEP
    assert s("step", "parasolid", "assembly") == ("step", None)  # the export reads it, and can still refuse
    assert s("3mf", "stl", "part") == ("3mf", None) and s("stl", "step", "assembly") == ("stl", None)


def test_a_model_file_beside_one_of_its_name_is_marked_with_its_extension(models):
    """Exports of each other often share a folder: each one's print says where it came
    from, as (assembly) marks an assembly beside a part of its name. A SOLIDWORKS
    document keeps its plain name, and a file with no namesake is not marked."""
    sw = _export(models, "o02_boxA.SLDPRT", "3mf")
    xt = _export(models, "o02_boxA.x_t", "3mf")
    stl = _export(models, "o02_boxA.STL", "3mf")
    shutil.copy(models / "box.stl", models / "single.stl")
    alone = _export(models, "single.stl", "3mf")
    names = [os.path.basename(o["file"]) for o in (sw, xt, stl, alone)]
    assert names == [
        f"o02_boxA {TODAY}.3mf",
        f"o02_boxA (X_T) {TODAY}.3mf",
        f"o02_boxA (STL) {TODAY}.3mf",
        f"single {TODAY}.3mf",
    ]
    assert [o["format_mark"] for o in (sw, xt, stl, alone)] == [None, "X_T", "STL", None]
    assert [o["source_format"] for o in (sw, xt, stl, alone)] == ["solidworks", "parasolid", "stl", "stl"]
    # the samples share names across formats, as exports of each other do
    names = [
        os.path.basename(_export(models, n, "3mf")["file"]) for n in ("pair.3mf", "pair.step", "pair.AD_ASM")
    ]
    assert names == [f"pair (3MF) {TODAY}.3mf", f"pair (STEP) {TODAY}.3mf", f"pair (AD_ASM) {TODAY}.3mf"]
    # an assembly of another format beside a SOLIDWORKS part of its name: its extension says
    # it all, so it is not marked (assembly) as well
    multi = _export(models, "o12_multibody.x_b", "3mf")
    assert (
        os.path.basename(multi["file"]) == f"o12_multibody (X_B) {TODAY}.3mf" and not multi["assembly_mark"]
    )
    again = _export(models, "o02_boxA.x_t", "3mf")  # numbered within its own name
    assert os.path.basename(again["file"]) == f"o02_boxA (X_T) {TODAY} (2).3mf"
    assert printing.print_label("frame", "Lite", source="STL") == "frame (STL) (Lite)"
    assert printing.format_mark("dir/frame.xmt_txt") == "XMT_TXT"


def test_a_parasolid_file_prints_as_its_exact_step(models):
    out = _export(models, "o02_boxA.x_t", "step")  # marked: o02_boxA.SLDPRT is beside it
    assert out["file"] == str(models / f"o02_boxA (X_T) {TODAY}.step") and out["format"] == "step"
    assert out["requested_format"] == "step" and out["format_fallback"] is None
    assert out["step"]["exact"] and out["step"]["solids"] == 1 and out["closed"]
    got = _checked(out["file"], out["step"])
    assert got["solids"] == 1
    again = _export(models, "o02_boxA.x_b", "step")  # a name of its own, numbered as any print
    assert again["file"] == str(models / f"o02_boxA (X_B) {TODAY}.step")
    lone = models / "lone"
    lone.mkdir()
    shutil.copy(models / "o02_boxA.x_t", lone / "bracket.x_t")
    alone = printing.export_for_print(
        str(lone / "bracket.x_t"), str(models), "step", out_base=str(models.parent / "temp"), date=TODAY
    )
    assert alone["file"] == str(lone / f"bracket {TODAY}.step") and alone["format_mark"] is None


@pytest.mark.parametrize(
    ("name", "why"),
    [
        ("o02_boxA.STL", "STL files hold triangles, not the exact faces and edges a STEP is made of"),
        ("block.off", "OFF files hold triangles, not the exact faces and edges a STEP is made of"),
        ("box.glb", "glTF files hold triangles, not the exact faces and edges a STEP is made of"),
        ("o02_boxA.step", printing.STEP_MODEL_FILE.format(name="STEP")),
        ("cube.sab", printing.STEP_MODEL_FILE.format(name="ACIS")),
        ("cube.AD_PRT", printing.STEP_MODEL_FILE.format(name="Alibre Design")),
        ("pair.3mf", printing.STEP_MESH.format(name="3MF")),
    ],
)
def test_any_other_model_file_asked_for_as_step_goes_as_3mf_and_says_why(models, name, why):
    out = _export(models, name, "step")
    stem = os.path.splitext(name)[0]
    assert out["format"] == "3mf" and out["requested_format"] == "step" and out["format_fallback"] == why
    made = os.path.basename(out["file"])  # an assembly beside a part of its name is marked (assembly)
    assert made.startswith(stem) and made.endswith(f" {TODAY}.3mf") and out["closed"] and out["triangles"] > 0
    assert not list(models.glob("*.step.*.part")) and not list(models.glob("*.part"))


def test_a_multi_body_parasolid_file_prints_as_one_step(models):
    """SOLIDWORKS writes a multi-body part's .x_b as an assembly of its bodies at the
    identity: it prints as the one part with its bodies, not as a 3MF."""
    out = _export(models, "o12_multibody.x_b", "step")
    assert out["format"] == "step" and out["requested_format"] == "step" and out["format_fallback"] is None
    assert out["file"].endswith(f"{TODAY}.step")


@pytest.mark.parametrize("name", ["o02_boxA.x_t", "box.amf", "pair.step", "cube.AD_PRT"])
def test_any_model_file_prints_as_stl_and_3mf(models, name):
    for fmt in ("stl", "3mf"):
        out = _export(models, name, fmt)
        assert out["format"] == fmt and out["format_fallback"] is None and out["closed"]
        assert out["file"].endswith(f"{TODAY}.{fmt}") and os.path.getsize(out["file"]) == out["bytes"]


def test_a_parasolid_step_print_and_export_step_run_in_the_export_process(models, tmp_path):
    """Both go through the export's own process, whose requests and answers are JSON."""
    base = tmp_path / "temp"
    base.mkdir()
    request = {
        "path": str(models / "o02_boxA.x_b"),
        "folder": str(models),
        "fmt": "step",
        "out_base": str(base),
        "date": TODAY,
        "nested": [],
        "virtual": [],
    }
    printed = printing.export_in_process(request)
    assert printed["ok"], printed
    assert printed["data"]["format"] == "step" and printed["data"]["step"]["exact"]
    _checked(printed["data"]["file"], printed["data"]["step"])
    target = tmp_path / "out" / "box.step"
    target.parent.mkdir()
    job = {
        "job": "step",
        "path": str(models / "o02_boxA.x_t"),
        "folder": str(models),
        "target": str(target),
        "nested": [],
    }
    exported = printing.export_in_process(job)
    assert exported["ok"], exported
    assert exported["data"]["source_format"] == "parasolid" and exported["data"]["exact"]
    _checked(str(target))
    refused = printing.export_in_process(
        {**job, "path": str(models / "box.stl"), "target": str(target) + "2.step"}
    )
    assert not refused["ok"] and refused["error"]["code"] == "not_implemented"
    assert not os.path.exists(str(target) + "2.step")


def test_export_step_says_where_a_parasolid_file_s_geometry_came_from(models, tmp_path):
    target = tmp_path / "curved.step"
    data = stepexport.export_step_file(str(models / "o11_curved.x_b"), str(models), str(target))
    assert data["source_format"] == "parasolid" and data["solids"] == 1 and data["exact"]
    with pytest.raises(UnsupportedOperationError):
        stepexport.export_step_file(str(models / "o02_boxA.3mf"), str(models), str(tmp_path / "no.step"))
    assert sorted(os.listdir(tmp_path)) == ["curved.step", "models"]


# --------------------------------------------------------------------------- the window
@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from solidseas_app.viewer.app import use_system_fonts

    use_system_fonts()
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _wait(app, condition, timeout: float = 120.0) -> None:
    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            raise AssertionError("timed out waiting for the viewer")
        app.processEvents()
        time.sleep(0.005)


@pytest.fixture
def window(app):
    from solidseas_app.viewer.window import MainWindow

    w = MainWindow()  # its settings in memory only
    w.show()
    w.finished_generations = []
    w.detailsFinished.connect(w.finished_generations.append)
    yield w
    assert w.shutdown()
    w.close()
    w.deleteLater()
    app.processEvents()


def _select(app, w, name: str) -> None:
    before = w.generation
    assert w.select_document(name), name
    _wait(app, lambda: any(g > before for g in w.finished_generations) and w._details is None)


@needs_qt
def test_export_step_is_offered_for_a_parasolid_part_and_says_why_not_otherwise(app, window, models):
    from solidseas_app.viewer.details import TABS
    from solidseas_app.viewer.stepaction import TIP
    from solidseas_app.viewer.whereused import not_indexed_text

    w = window
    w.open_folder(str(models))
    _wait(app, lambda: w.listing_info is not None)
    _select(app, w, "o02_boxA.x_t")
    assert w.act_step.isEnabled() and w.act_step.toolTip() == TIP and w.step_unavailable() is None
    _select(app, w, "o02_boxA.SLDPRT")
    assert w.act_step.isEnabled() and w.act_step.toolTip() == TIP
    for name, said in (
        ("o02_boxA.STL", "STL files hold triangles, not the exact faces and edges a STEP is made of."),
        ("box.glb", "glTF files hold triangles, not the exact faces and edges a STEP is made of."),
        ("o02_boxA.step", printing.STEP_MODEL_FILE.format(name="STEP") + "."),
        ("pair.3mf", "3MF files hold triangles, not the exact faces and edges a STEP is made of."),
        ("o18_drw_boxA.SLDDRW", printing.STEP_DRAWING + "."),
    ):
        _select(app, w, name)
        assert not w.act_step.isEnabled() and w.act_step.toolTip() == said, name
        assert w.act_step.statusTip() == said
    # Where Used: shown, and asking the index about a file of another format as about a document
    # (indexing is off in these tests, which the tab says for both)
    _select(app, w, "box.stl")
    d = w.details
    assert d.tabs.isTabVisible(TABS.index("Where Used"))
    off = d.pages["Where Used"].message_text
    assert off.startswith("Indexing of opened folders is off") and off != not_indexed_text("stl")
    assert not d.tabs.isTabVisible(TABS.index("BOM")) and not d.tabs.isTabVisible(TABS.index("Paths"))
    _select(app, w, "o02_boxA.SLDPRT")
    assert d.pages["Where Used"].message_text == off


@needs_qt
def test_the_print_progress_names_the_format_a_model_file_is_made_in(app):
    from solidseas_app.viewer import reading
    from solidseas_app.viewer.printaction import PrintTarget

    def target(name, doc_type="part", nested=()):
        return PrintTarget(
            reading.Source(str(FIXTURES / name), str(FIXTURES), nested),
            str(FIXTURES),
            None,
            name,
            doc_type=doc_type,
        )

    assert target("o02_boxA.SLDPRT").model_format is None
    assert target("o02_boxA.x_t").model_format == "parasolid"
    assert target("o02_boxA.STL").model_format == "stl"
    assert target("o16_asm_features.SLDASM", nested=("x",)).model_format is None
    # what the window found the file holds wins over its name
    assert replace(target("o02_boxA.SLDPRT"), content_format="step").model_format == "step"
    assert replace(target("o02_boxA.step"), content_format="parasolid").model_format == "parasolid"
    assert replace(target("o02_boxA.STL"), content_format="solidworks").model_format is None


@needs_qt
def test_back_gives_a_model_file_s_assembly_its_camera_again(app, window, models):
    """A component of an Alibre assembly opened from its 3D view, and Back: the assembly
    comes back turned and zoomed as it was left, as a SOLIDWORKS assembly does."""
    from solidseas_app.viewer.details import TABS
    from test_viewer import _stub_view_factory

    w = window
    pane = w.details.preview
    made: list = []
    pane.view_factory = _stub_view_factory(made)
    pane.gl_check = lambda: (True, "test")
    w.open_folder(str(models))
    _wait(app, lambda: w.listing_info is not None)
    w.change_settings(view_3d=True)
    w.details.tabs.setCurrentIndex(TABS.index("Preview"))
    _select(app, w, "pair.AD_ASM")
    _wait(app, lambda: pane.mesh_state not in ("idle", "starting", "loading"))
    assert pane.mesh_state == "ready" and pane.instance_ids
    view = made[-1]
    looked = {"yaw": 75.0, "pitch": 20.0, "target": [0.01, 0.02, 0.0], "half_height": 0.05, "fitted": False}
    view.cam = dict(looked)  # the user turned and zoomed the view
    view.activated.emit(0)  # a double-click on a component: its own file opens
    _wait(app, lambda: w.details.title.text() == "cube.AD_PRT" and w._details is None)
    _wait(app, lambda: pane.mesh_state not in ("starting", "loading"))
    assert w.history[-1].camera == looked
    assert w.go_back()
    _wait(app, lambda: w.details.title.text() == "pair.AD_ASM" and w._details is None)
    _wait(app, lambda: pane.mesh_state == "ready")
    assert made[-1].cam == looked and made[-1].camera_calls[-1] == looked


def _mislabelled(models: Path) -> None:
    """Files whose names say another format than they hold."""
    shutil.copy(models / "box.stl", models / "meshonly.3mf")  # an STL saved as .3mf
    shutil.copy(models / "pair.3mf", models / "project.stl")  # a 3MF saved as .stl
    shutil.copy(models / "o02_boxA.step", models / "stepinside.SLDPRT")  # a STEP saved as .SLDPRT
    shutil.copy(models / "o02_boxA.x_t", models / "para.step")  # a Parasolid file saved as .step


def _dry_printer(w, tmp_path: Path) -> list:
    """The window's 3D Print in a dry run, Bambu Studio found in a made-up Program Files and
    never started: the outcomes it reports."""
    pf = tmp_path / "Program Files"
    exe = pf / "Bambu Studio" / "bambu-studio.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    exe.chmod(0o755)  # a program on Linux and macOS too
    found = printing.detect(
        {"ProgramW6432": str(pf), "ProgramFiles": str(pf)}, app_path=lambda e: None, windows=True
    )
    c = w.printer
    c.detect = lambda: list(found)
    c.launch = lambda program, path: pytest.fail(f"{program} was started")
    c.dry_run = True
    c.today = lambda: TODAY
    (tmp_path / "temp").mkdir()
    c.out_base = str(tmp_path / "temp")
    outcomes: list = []
    c.finished.connect(outcomes.append)
    return outcomes


@needs_qt
def test_as_they_are_opens_a_3mf_asked_for_as_step_and_never_a_mislabelled_file(
    app, window, models, tmp_path
):
    """With Open 3MF and STL Files As They Are on: a 3MF asked for as STEP goes as 3MF, so it
    opens as it is, its slicer project kept, and the note says why it is not a STEP; a file
    whose name says another format than it holds is exported to a new file in the format
    sent; an STL asked for as STEP goes as a new 3MF, as with Send as 3MF."""
    w = window
    _mislabelled(models)
    outcomes = _dry_printer(w, tmp_path)
    w.open_folder(str(models))
    _wait(app, lambda: w.listing_info is not None)
    w.change_settings(print_as_is=True)
    c = w.printer

    def press(name: str, fmt: str) -> tuple[str, dict]:
        c._save(printing.PrintChoice("bambu", None, fmt))
        if w._entry is None or w._entry["path"].rpartition("/")[2] != name:
            _select(app, w, name)
        n = len(outcomes)
        c.print_selection()
        said = w.statusBar().currentMessage()
        _wait(app, lambda: len(outcomes) > n)
        return said, outcomes[-1]

    before = sorted(os.listdir(models))
    _said, out = press("o02_boxA.3mf", "step")
    why = printing.STEP_MESH.format(name="3MF")
    assert out["ok"] and out["as_is"] and out["file"] == str(models / "o02_boxA.3mf")
    assert (out["format"], out["requested_format"], out["format_fallback"]) == ("3mf", "step", why)
    assert out["note"].startswith("o02_boxA.3mf is already a 3MF file: ")
    assert f"(sent as 3MF, not STEP, as {why})" in out["note"]
    _said, out = press("box.stl", "stl")
    assert out["as_is"] and out["note"].startswith("box.stl is already an STL file: ")
    assert sorted(os.listdir(models)) == before  # nothing written so far
    _said, out = press("box.stl", "step")  # sent as 3MF, which an STL is not
    assert not out.get("as_is") and out["file"] == str(models / f"box (STL) {TODAY}.3mf")  # box.amf is there
    _said, out = press("meshonly.3mf", "3mf")
    assert not out.get("as_is") and out["format"] == "3mf"
    assert out["file"] == str(models / f"meshonly {TODAY}.3mf")
    assert out["source_format"] == "stl"
    _said, out = press("project.stl", "stl")
    assert not out.get("as_is") and out["format"] == "stl"
    assert out["file"] == str(models / f"project {TODAY}.stl")
    assert out["source_format"] == "3mf"


@needs_qt
def test_the_print_progress_goes_by_what_the_file_holds(app, window, models, tmp_path):
    """A STEP saved as .SLDPRT is made as 3MF, a Parasolid file saved as .step as STEP, and
    the progress line says so before the export has read either."""
    w = window
    _mislabelled(models)
    outcomes = _dry_printer(w, tmp_path)
    w.open_folder(str(models))
    _wait(app, lambda: w.listing_info is not None)
    c = w.printer
    c._save(printing.PrintChoice("bambu", None, "step"))
    for name, made in (("stepinside.SLDPRT", "3MF"), ("para.step", "STEP"), ("o02_boxA.SLDPRT", "STEP")):
        _select(app, w, name)
        n = len(outcomes)
        c.print_selection()
        said = w.statusBar().currentMessage()
        assert said.startswith(f"Preparing the {made} of {name} for Bambu Studio"), (name, said)
        _wait(app, lambda n=n: len(outcomes) > n)
        assert printing.FORMAT_LABELS[outcomes[-1]["format"]] == made, name
    assert outcomes[0]["format_fallback"] == printing.STEP_MODEL_FILE.format(name="STEP")
    # the list's right-click entry goes by what the listing found, too
    row = next(r.entry for r in w.model.rows if r.entry["path"].endswith("para.step"))
    target = w.entry_print_target(row)
    assert target.content_format == "parasolid" and target.model_format == "parasolid"
    row = next(r.entry for r in w.model.rows if r.entry["path"].endswith("stepinside.SLDPRT"))
    assert w.entry_print_target(row).model_format == "step"


@needs_qt
def test_the_self_test_export_step_expects_the_entry_off_with_its_reason(app, tmp_path, models, monkeypatch):
    """--export-step over parts of other formats: a Parasolid file's part is exported and
    checked; an STL, a glTF and a STEP saved as .SLDPRT find the entry off with the reason
    its tooltip gives, which passes, as an assembly does."""
    from PySide6.QtCore import QTimer

    from solidseas_app.viewer.selftest import SelfTest
    from solidseas_app.viewer.window import MainWindow

    _mislabelled(models)
    made = []
    real = __import__("tempfile").mkdtemp

    def mkdtemp(**kw):
        made.append(real(dir=str(tmp_path), **kw))
        return made[-1]

    monkeypatch.setattr("solidseas_app.viewer.selftest.tempfile.mkdtemp", mkdtemp)
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    shots = tmp_path / "shots"
    shots.mkdir()
    names = ["box.stl", "o02_boxA.x_t", "box.glb", "stepinside.SLDPRT", "pair.AD_ASM"]
    st = SelfTest(
        w,
        str(models),
        screenshot_dir=None,
        report=str(shots / "selftest.json"),
        select=names,
        export_step=True,
    )
    QTimer.singleShot(0, st.start)
    assert app.exec() == 0
    w.shutdown()
    w.close()
    report = json.loads((shots / "selftest.json").read_text(encoding="utf-8"))
    assert report["ok"], (report["errors"], [d["errors"] for d in report["documents"]])
    got = {d["name"]: d["export_step"] for d in report["documents"]}
    assert got["o02_boxA.x_t"]["ok"] and got["o02_boxA.x_t"]["step_check"]["problems"] == []
    for name, why in (
        ("box.stl", printing.step_unavailable("stl", "part")),
        ("box.glb", printing.step_unavailable("gltf", "part")),
        ("stepinside.SLDPRT", printing.step_unavailable("step", "part")),
        ("pair.AD_ASM", printing.step_unavailable("alibre", "assembly")),
    ):
        assert got[name]["available"] is False and got[name]["reason"] == why, name
        assert got[name]["tooltip"].endswith(why[1:] + "."), name
    assert len(made) == 1 and not os.path.exists(made[0])  # the X_T's own folder, removed once checked
