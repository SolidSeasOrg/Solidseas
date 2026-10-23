"""Each document's looks in the 3D view, kept from one run of the viewer to the next
(``solidseas_app.viewer.lookstore``).

What is hidden or transparent and which sub-assemblies explode or stay together come
back when a document is shown again, in the same run and, through ``ViewerLooks.json``
beside ``Viewer.ini``, in the next one. These tests check the store on its own (what it
writes, what it reads back from a damaged or hand-edited file, which documents it keeps)
and then the window: two runs sharing one file, with a stand-in for the OpenGL view.
"""

import hashlib
import json
import os
import re

import pytest

from solidseas_app.viewer import lookstore
from solidseas_app.viewer.appearance import FILE, ID, Look, Looks
from solidseas_app.viewer.lookstore import LookStore, document_id
from support import FIXTURES
from test_viewer import Viewer, _state, needs_qt
from test_viewer_looks import O08, O16, ROTATED, SUB, _actions, _assembly_3d, _looks, _show

A = hashlib.sha256(b"a document").hexdigest()


def _chosen() -> dict:
    looks = Looks()
    looks.transparent((ID, SUB), 75)
    looks.hide((FILE, "3"))
    return {"looks": looks.state(), "explode": {SUB: True}}


# --------------------------------------------------------------------------- the store, no Qt
def test_a_document_is_kept_under_a_digest_of_where_it_is(tmp_path):
    frame = str(tmp_path / "Proj" / "frame.SLDASM")
    ident = document_id((frame, "frame.SLDASM"))
    assert re.fullmatch("[0-9a-f]{64}", ident)
    assert document_id((frame, "sub/frame.SLDASM")) == ident  # whichever folder was opened above it
    assert document_id((str(tmp_path / "Proj" / "." / "frame.SLDASM"), "frame.SLDASM")) == ident
    if os.name == "nt":
        assert document_id((frame.upper(), "FRAME.SLDASM")) == ident  # as Windows compares names
    virtual = document_id((frame, "Part12^frame"))  # a virtual part stored inside it
    assert virtual is not None and virtual != ident
    assert document_id((str(tmp_path / "Other" / "frame.SLDASM"), "frame.SLDASM")) != ident
    assert document_id(None) is None and document_id(("", "frame.SLDASM")) is None


def test_the_looks_are_written_and_read_back(tmp_path):
    path = tmp_path / "SolidSeas" / "ViewerLooks.json"
    store = LookStore(str(path))
    changed: list[int] = []
    store.on_change = lambda: changed.append(1)
    store.put(A, _chosen())
    assert changed == [1] and store.dirty and not path.exists()  # written by flush, once settled
    store.put(A, _chosen())  # the same again: nothing to write
    assert changed == [1]
    assert store.flush() and path.is_file() and not store.dirty
    again = LookStore(str(path))
    kept = again.get(A)
    assert kept == lookstore.clean(_chosen())
    looks = Looks.from_state(kept["looks"])
    assert looks.look(f"{SUB}/o02_boxA-1") == Look(transparency=75)
    assert looks.look("o02_boxA-1", ["3"]) == Look(hidden=True)
    kept["explode"].clear()  # a copy: the store keeps its own
    assert again.get(A)["explode"] == {SUB: True}
    again.put(A, {"looks": Looks().state(), "explode": {}})  # Reset appearance: forgotten
    assert again.get(A) is None and again.flush()
    assert json.loads(path.read_text(encoding="utf-8")) == {"version": 1, "documents": []}


def test_only_the_documents_changed_last_are_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(lookstore, "MAX_DOCUMENTS", 3)
    path = tmp_path / "ViewerLooks.json"
    store = LookStore(str(path))
    ids = [hashlib.sha256(str(i).encode()).hexdigest() for i in range(5)]
    for ident in ids:
        store.put(ident, _chosen())
    store.put(ids[2], {"looks": None, "explode": {SUB: False}})  # changed again: the latest
    assert store.flush()
    listed = json.loads(path.read_text(encoding="utf-8"))["documents"]
    assert [d["id"] for d in listed] == [ids[2], ids[4], ids[3]]
    assert listed[0] == {"id": ids[2], "looks": None, "explode": {SUB: False}}


def test_two_viewers_keep_each_others_changes(tmp_path):
    """Each write puts the documents changed in that viewer over what the file holds then."""
    path = tmp_path / "ViewerLooks.json"
    one, two = LookStore(str(path)), LookStore(str(path))
    b, c = hashlib.sha256(b"b").hexdigest(), hashlib.sha256(b"c").hexdigest()
    assert one.get(A) is None and two.get(A) is None  # both read the file before either wrote
    one.put(A, _chosen())
    two.put(b, _chosen())
    assert one.flush() and two.flush()
    listed = json.loads(path.read_text(encoding="utf-8"))["documents"]
    assert [d["id"] for d in listed] == [b, A]
    assert two.get(A) == lookstore.clean(_chosen())  # the other viewer's, read back as it wrote
    one.put(c, _chosen())
    one.put(A, {"looks": None, "explode": {}})  # Reset appearance there
    assert one.flush()
    assert [d["id"] for d in json.loads(path.read_text(encoding="utf-8"))["documents"]] == [c, b]


def test_the_file_names_no_path_or_document(tmp_path):
    path = tmp_path / "ViewerLooks.json"
    store = LookStore(str(path))
    store.put(document_id((str(tmp_path / "Client Project" / "frame.SLDASM"), "frame.SLDASM")), _chosen())
    assert store.flush()
    text = path.read_text(encoding="utf-8")
    assert "Client Project" not in text and "frame" not in text and str(tmp_path) not in text


@pytest.mark.parametrize(
    "data",
    [
        b"not JSON",
        b"[]",
        b'{"version": 2, "documents": []}',
        b'{"version": 1, "documents": {}}',
        b"[" * 100_000,  # nested past what the parser takes
        "{é".encode("latin-1"),  # not UTF-8
    ],
)
def test_a_damaged_or_foreign_file_is_taken_as_empty_and_replaced(tmp_path, data):
    path = tmp_path / "ViewerLooks.json"
    path.write_bytes(data)
    store = LookStore(str(path))
    assert store.get(A) is None
    store.put(A, _chosen())
    assert store.flush() and LookStore(str(path)).get(A) == lookstore.clean(_chosen())


def test_a_file_too_large_to_be_ours_is_not_read(tmp_path, monkeypatch):
    path = tmp_path / "ViewerLooks.json"
    store = LookStore(str(path))
    store.put(A, _chosen())
    assert store.flush()
    monkeypatch.setattr(lookstore, "MAX_FILE_BYTES", path.stat().st_size - 1)
    assert LookStore(str(path)).get(A) is None


def test_choices_that_do_not_check_out_are_left_out(tmp_path):
    good = [["id", SUB, "transparency", 75, 2], ["boxes", "", "hidden", True, 8]]
    bad = [
        ["id", "o02_boxA-1", "transparency", 95, 3],  # more than the most offered
        ["id", "o02_boxA-1", "hidden", "yes", 4],
        ["shape", "o02_boxA-1", "hidden", True, 5],  # no such scope
        ["id", "o02_boxA-1", "hidden", True, -1],
        ["id", 7, "hidden", True, 6],
        ["id", "o02_boxA-1", "transparency", True, 7],  # a yes or no is no percentage
        "a choice",
    ]
    doc = {
        "id": A,
        "looks": {"seq": 9, "choices": [good[0], *bad, good[1]]},
        "explode": {SUB: True, "o02_boxA-1": "yes", "": True},
    }
    others = [{"id": "../ViewerLooks.json", **_chosen()}, {"id": A.upper(), **_chosen()}, "a document"]
    path = tmp_path / "ViewerLooks.json"
    path.write_text(json.dumps({"version": 1, "documents": [doc, *others]}), encoding="utf-8")
    store = LookStore(str(path))
    assert store.get(A) == {"looks": {"seq": 9, "choices": good}, "explode": {SUB: True}}
    assert len(store._loaded()) == 1


def test_a_store_without_a_file_keeps_them_in_memory():
    store = LookStore(None)
    changed: list[int] = []
    store.on_change = lambda: changed.append(1)
    store.put(A, _chosen())
    assert store.get(A) == lookstore.clean(_chosen()) and not store.dirty and changed == []
    assert store.flush()


def test_a_failed_write_keeps_the_change_and_says_so(tmp_path):
    blocker = tmp_path / "SolidSeas"
    blocker.write_text("a file where the folder would be", encoding="utf-8")
    store = LookStore(str(blocker / "ViewerLooks.json"))
    store.put(A, _chosen())
    assert not store.flush() and store.write_failed and store.dirty
    assert store.get(A) == lookstore.clean(_chosen())


# --------------------------------------------------------------------------- the window, offscreen
class Run(Viewer):
    """A run of the viewer that keeps the looks in ``path``, as the launcher's does."""

    def __init__(self, app, path) -> None:
        from solidseas_app.viewer.window import MainWindow

        self.app = app
        self.window = MainWindow(looks_path=str(path))
        self.window.show()
        self.finished: list[int] = []
        self.window.detailsFinished.connect(self.finished.append)


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from solidseas_app.viewer.app import use_system_fonts

    use_system_fonts()
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@needs_qt
def test_looks_and_explode_switches_come_back_in_the_same_run_and_the_next(app, tmp_path):
    path = tmp_path / "ViewerLooks.json"
    before = _state(FIXTURES)
    first = Run(app, path)
    try:
        w, pane, view = _assembly_3d(first)
        pane.set_transparency(("instance", SUB), 75)
        pane.set_hidden(("instance", "o09_import_step-1"))
        pane.set_subassembly_explodes(SUB, True)
        drawn = _looks(pane, view)
        assert drawn == {
            f"{SUB}/o02_boxA-1": (0.25, False),
            f"{SUB}/o07_boxB_h31-1": (0.25, False),
            "o09_import_step-1": (1.0, True),
        }
        _show(first, O08)  # another document has its own: none
        assert not pane.looks.changed and pane.explode_choices == {} and _looks(pane, view) == {}
        _show(first, O16)  # selected again, not by Back: everything as it was
        assert _looks(pane, view) == drawn and view.explode_choices == {SUB: True}
    finally:
        first.close()  # the window writes what changed as it closes
    listed = json.loads(path.read_text(encoding="utf-8"))["documents"]
    assert [d["id"] for d in listed] == [document_id((str(FIXTURES / O16), O16))]

    second = Run(app, path)
    try:
        w, pane, view = _assembly_3d(second)
        assert _looks(pane, view) == drawn
        assert pane.explode_choices == {SUB: True} == view.explode_choices
        _actions(w.details.instance_menu(ROTATED))["Reset appearance"].trigger()
        assert _looks(pane, view) == {} and pane.explode_choices == {}
    finally:
        second.close()
    assert json.loads(path.read_text(encoding="utf-8"))["documents"] == []

    third = Run(app, path)
    try:
        w, pane, view = _assembly_3d(third)
        assert _looks(pane, view) == {} and pane.explode_choices == {} and not pane.looks.changed
    finally:
        third.close()
    assert _state(FIXTURES) == before


@needs_qt
def test_a_window_without_a_looks_file_keeps_them_for_the_run(app):
    """The tests' and the self-test's windows are given no file: the looks still come back
    within the run, and nothing is written."""
    viewer = Viewer(app)
    try:
        w, pane, view = _assembly_3d(viewer)
        assert w.look_store.path is None and pane.view_store is w.look_store
        pane.set_hidden(("instance", "o09_import_step-1"))
        kept = w.look_store.get(document_id((str(FIXTURES / O16), O16)))
        assert kept["looks"]["choices"][0][:4] == ["id", "o09_import_step-1", "hidden", True]
        assert not w.look_store.dirty
    finally:
        viewer.close()
