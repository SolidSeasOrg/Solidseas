"""Look for Referenced Files Only in the Opened Folder (Settings > General).

An assembly names each component file by the path it had when it was saved. By default
the viewer also looks at that path when it lies outside the opened folder on a drive of
this computer, as the References tab, the 3D view, 3D Print, the exports and drawings all
do. With the setting on, every one of those reads keeps to the opened folder: these tests
build a project whose one part sits beside it, found only by a look outside, and check
each read both ways, the first as the control that proves the part is reachable. Then the
window: its requests carry the setting, and turning it on forgets the documents only that
look found.
"""

import json
import os

import pytest

from builders import part_with_creation_time
from solidseas.errors import NothingToExportError, UnsupportedOperationError
from test_viewer import Viewer, _state, _wait, needs_qt
from test_viewer_open_component import (
    CT,
    _assembly,
    _back,
    _go,
    _row,
    _write,
    no_drive_q,  # noqa: F401  (a fixture, used by every test here)
)

pytestmark = pytest.mark.usefixtures("no_drive_q")  # stored Q:\ paths are never touched
CAP = 1_000_000


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


@pytest.fixture
def project(tmp_path):
    """``New/Proj/asm.SLDASM``, saved in ``Q:\\Old\\Proj`` with its part in ``Q:\\Old\\lib``:
    the part, now at ``New/lib/p.SLDPRT``, is found only by the stored path's place
    relative to the assembly, outside the opened folder ``New/Proj``."""
    new = tmp_path / "New"
    _write(new / "lib" / "p.SLDPRT", part_with_creation_time(CT))
    asm = _assembly(["Q:\\Old\\lib\\p.SLDPRT"], folder_at_save="Q:\\Old\\Proj\\")
    _write(new / "Proj" / "asm.SLDASM", asm)
    return new


# --------------------------------------------------------------------------- each read, no Qt
def test_the_details_find_the_part_outside_only_when_allowed(project):
    from solidseas_app.viewer import navigate, reading

    asm, proj = project / "Proj" / "asm.SLDASM", project / "Proj"
    before = _state(project)
    for outside, status in ((True, "moved"), (False, "missing")):
        sections = dict(reading.read_document(str(asm), str(proj), outside=outside))
        refs = sections["references"]["data"]["references"]
        assert refs["resolution"]["outside_roots"] is outside
        (file,) = refs["files"]
        assert file["resolution"]["status"] == status, outside
        (row,) = sections["bom"]["data"]["boms"]["top"]["rows"]
        assert row["resolution"] == status, outside
        again = reading.read_bom(str(asm), str(proj), None, outside=outside)
        assert again["data"]["boms"]["top"]["rows"][0]["resolution"] == status, outside
        t = navigate.target(file, key="2", outside_roots=outside)
        if outside:
            assert t.kind == navigate.OUTSIDE and t.path == str(project / "lib" / "p.SLDPRT")
        else:
            assert t.kind == navigate.MISSING
            assert t.why.endswith(navigate.OUTSIDE_NOT_SEARCHED)
            assert "and the stored path when it is on a drive" not in t.why
    assert _state(project) == before


def test_the_3d_view_draws_the_part_outside_only_when_allowed(project):
    from solidseas_app.viewer import mesh3d
    from solidseas_app.viewer.meshproc import MeshReader

    asm, proj = str(project / "Proj" / "asm.SLDASM"), str(project / "Proj")
    drawn = mesh3d.read_assembly_scene(asm, proj, proj, CAP)
    assert drawn["state"] == "ok" and drawn["geometry"]["placed"] == 1
    kept = mesh3d.read_assembly_scene(asm, proj, proj, CAP, outside=False)
    assert kept["state"] == "no_mesh" and kept["geometry"]["skipped_reasons"] == {"missing": 1}
    reader = MeshReader()  # through the mesh process, as the window reads it
    try:
        assert reader.read(asm, proj, CAP, assembly=True, root=proj)["state"] == "ok"
        assert reader.read(asm, proj, CAP, assembly=True, root=proj, outside=False)["state"] == "no_mesh"
    finally:
        reader.close()


def test_prints_and_exports_take_the_part_outside_only_when_allowed(project, tmp_path):
    from solidseas_app.viewer import printing, stepexport

    asm, proj = str(project / "Proj" / "asm.SLDASM"), str(project / "Proj")
    out = tmp_path / "out"
    out.mkdir()
    assert printing.export_to_folder(asm, proj, "stl", str(out))["file"]
    with pytest.raises(NothingToExportError):
        printing.export_to_folder(asm, proj, "3mf", str(out), outside=False)
    assert stepexport.export_step_file(asm, proj, str(out / "a.step"))["file"]
    with pytest.raises(NothingToExportError):
        stepexport.export_step_file(asm, proj, str(out / "b.step"), outside=False)
    temp = tmp_path / "temp"
    temp.mkdir()
    printed = printing.export_for_print(asm, proj, "stl", out_base=str(temp), next_to_model=False)
    assert printed["place"] == printing.TEMP
    with pytest.raises(NothingToExportError):
        printing.export_for_print(asm, proj, "stl", out_base=str(temp), next_to_model=False, outside=False)


def test_drawings_take_the_part_outside_only_when_allowed(project):
    from solidseas.drawing import assembly
    from solidseas.drawing.source import open_source
    from solidseas_app.viewer.drawingproc import DrawingWorker

    asm, proj = project / "Proj" / "asm.SLDASM", project / "Proj"
    with assembly.searching([proj]):
        assert len(open_source(asm).assembly.instances) == 1
    with assembly.searching([proj], outside=False):
        with pytest.raises(UnsupportedOperationError) as info:
            open_source(asm)
    assert info.value.detail["rule"] == "no_instances"

    worker = DrawingWorker()  # each request says whether the window allows the look outside
    sent = []

    def exchange(payload, accept, token, progress):
        sent.append(json.loads(payload))
        return {"ok": True}, {}, {}

    worker._exchange = exchange
    allowed = [True]
    worker.outside = lambda: allowed[0]
    try:
        worker._request({"op": "boms"}, ())
        allowed[0] = False
        worker._request({"op": "boms"}, ())
    finally:
        worker.close()
    assert [r.get("outside") for r in sent] == [None, False]


# --------------------------------------------------------------------------- the window, offscreen
@needs_qt
def test_the_setting_is_kept_and_offered_on_the_general_page(app, tmp_path):
    from solidseas_app.viewer import settingswindow as SW
    from solidseas_app.viewer.preferences import INSIDE_ONLY_TEXT
    from solidseas_app.viewer.settings import Settings, SettingsStore
    from solidseas_app.viewer.window import MainWindow

    assert Settings().references_inside_only is False  # the look outside stays on unless chosen
    store = SettingsStore(str(tmp_path / "Viewer.ini"))
    assert store.save(Settings().but(references_inside_only=True))
    assert "references_inside_only=true" in (tmp_path / "Viewer.ini").read_text(encoding="utf-8")
    assert store.load().references_inside_only is True
    w = MainWindow(store)
    d = SW.SettingsWindow(w)
    try:
        prefs = d.preferences
        assert prefs.inside_only.text() == INSIDE_ONLY_TEXT and prefs.inside_only.isChecked()
        assert prefs.inside_only.parent() in prefs.sections["general"]
        prefs.inside_only.setChecked(False)
        assert d.apply()
        assert w.settings.references_inside_only is False and store.load().references_inside_only is False
        prefs.restore_defaults()
        assert prefs.values() == Settings()
    finally:
        d.deleteLater()
        w.close()


@needs_qt
def test_turning_it_on_keeps_every_read_of_the_window_inside(viewer, project, tmp_path, monkeypatch):
    from solidseas_app.viewer import navigate, printing, reading
    from solidseas_app.viewer import window as window_module

    w, d = viewer.window, viewer.window.details
    asm, part = str(project / "Proj" / "asm.SLDASM"), str(project / "lib" / "p.SLDPRT")
    before = _state(project)
    viewer.open(project / "Proj")
    viewer.select("asm.SLDASM")
    assert d.target("2").kind == navigate.OUTSIDE
    _go(viewer, "instances", _row(viewer, "instances", "c2-1"))  # the part, found outside
    assert d.title.text() == "p.SLDPRT" and w.source.within == str(project / "lib")
    w.go_to_listed("asm.SLDASM")  # and on from it, so Back holds a place outside the folder
    _wait(viewer.app, lambda: not w.busy)
    assert [p.source.path for p in w.history] == [asm, part]

    w.change_settings(references_inside_only=True)  # Back forgets the part; the assembly is read again
    _wait(viewer.app, lambda: not w.busy)
    assert [p.source.path for p in w.history] == [asm] and d.title.text() == "asm.SLDASM"
    t = d.target("2")
    assert t.kind == navigate.MISSING and t.why.endswith(navigate.OUTSIDE_NOT_SEARCHED)
    menu = d.component_menu(_row(viewer, "instances", "c2-1"))
    show = [a for a in menu.actions() if a.text().startswith("Show in folder list")]
    assert show[0].text() == "Show in folder list (not found)"
    menu.deleteLater()

    # The 3D view, Export STEP, Export for 3D Printing and 3D Print ask for the opened folder alone.
    asked: list[dict] = []

    class Reader:
        def read(self, *args, **kwargs):
            asked.append(kwargs)
            return {"state": "cancelled", "seconds": {}}

        def cancel(self, token):
            pass

        def warm(self, cap):
            pass

        def close(self):
            pass

    real, w.mesh_reader = w.mesh_reader, Reader()
    try:
        w._mesh_requested()
        _wait(viewer.app, lambda: bool(asked))
    finally:
        w.mesh_reader = real
    assert asked[0]["outside"] is False
    requests: list[dict] = []

    def record(request, cancelled):
        requests.append(dict(request))
        return {"ok": False, "error": {"code": "recorded", "message": "recorded"}}

    w.step.ask_path = lambda suggested: str(tmp_path / "a.step")
    w.step.message = lambda icon, text: None
    w.step.export = record
    w.step.start()
    _wait(viewer.app, lambda: len(requests) == 1)

    exe = tmp_path / "bambu-studio.exe"  # a program file 3D Print would start, never started here
    exe.write_bytes(b"")
    exe.chmod(0o755)
    p = w.printer
    p.detect = lambda: [printing.Program("bambu", "Bambu Studio", str(exe), ("3mf", "stl", "step"))]
    p.launch = lambda program, path: None
    p._message = lambda icon, text: None
    p.export = record
    p.print_selection()
    _wait(viewer.app, lambda: len(requests) == 2 and not p.busy)

    class Dialog:  # File > Export for 3D Printing's dialog, answered
        def __init__(self, *args, **kwargs):
            self.folder = type("Line", (), {"text": lambda _self: str(tmp_path)})()
            self.format = type("Combo", (), {"currentData": lambda _self: "stl"})()
            self.overwrite = type("Box", (), {"isChecked": lambda _self: False})()

        def exec(self):
            return window_module.QDialog.DialogCode.Accepted

    monkeypatch.setattr(window_module, "ExportDialog", Dialog)
    monkeypatch.setattr(window_module, "show_message", lambda *args: None)
    monkeypatch.setattr(printing, "export_in_process", record)
    w.export_for_printing()
    _wait(viewer.app, lambda: len(requests) == 3 and w._export_job is None)
    step, printed, exported = requests
    assert step["job"] == "step" and printed["fmt"] == "3mf" and exported["out_dir"] == str(tmp_path)
    assert [r["outside"] for r in requests] == [False, False, False]
    assert w.drawings.ensure_worker().outside() is False

    w.change_settings(references_inside_only=False)  # off again: the assembly is read again
    _wait(viewer.app, lambda: not w.busy)
    assert d.target("2").kind == navigate.OUTSIDE
    assert w.drawings.ensure_worker().outside() is True
    assert w.source == reading.Source(asm, str(project / "Proj"))
    _go(viewer, "instances", _row(viewer, "instances", "c2-1"))  # found outside again, and shown

    w.change_settings(references_inside_only=True)  # what only a look outside found is closed
    assert w.source is None and d.title.text() == "No document selected"
    assert w.statusBar().currentMessage() == (
        "p.SLDPRT was found outside the opened folder, where referenced files are no longer looked for."
    )
    _back(viewer, "asm.SLDASM")
    assert _state(project) == before
