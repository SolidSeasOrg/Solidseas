"""Opening a component's file from an assembly's or a drawing's contents, and Back.

The details panel holds the document's references, resolved against the
opened folder; Go to file (a double-click on an instance, a file, a drawing view
or a model) goes where that resolution says. These tests check each outcome on
the fixtures and on crafted folders: a file in the list is selected there
(switching the list's filters only as far as needed), one outside the opened
folder or stored inside the assembly is shown on its own with a note, an
ambiguous one asks which, and a missing one says what was searched and why it
was not found. Back returns to the document with its tab, configuration and
selected row.

The resolution itself is checked against ``ground_truth.json``: in a moved copy
of the fixtures, every instance SOLIDWORKS reported goes to the file SOLIDWORKS
named for it, and every virtual one to its nested document.

Every test that reads files checks that none of them changed. Stored paths on
drive Q: are never touched: the drive is made absent for the resolution, so
the crafted cases do not depend on this machine's drives.
"""

import json
import os
import shutil
from pathlib import Path

import pytest

from builders import TreeXml, part_with_creation_time, resolving_assembly
from solidseas import open_document
from solidseas_app.viewer import mesh3d, navigate, reading
from support import ASSEMBLY, DOCUMENTS, FIXTURES, fixture_path
from test_viewer import Viewer, _state, _wait, needs_qt

O16 = "o16_asm_features.SLDASM"
VIRTUAL = "VirtualComp/Part12-sldprt"
CT = 1_700_000_000  # the creation time the crafted parts claim and the crafted assemblies store
GT = json.loads((FIXTURES / "ground_truth.json").read_text(encoding="utf-8"))


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
def no_drive_q(monkeypatch):
    """Drive Q: does not exist, whatever this machine has: stored Q:\\ paths are never touched."""
    from solidseas.resolve import gateway as gateway_mod

    real = gateway_mod._drive_type

    def drive_type(root: str) -> int:
        return gateway_mod.DRIVE_NO_ROOT_DIR if root.upper().startswith("Q:") else real(root)

    monkeypatch.setattr(gateway_mod, "_drive_type", drive_type)


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _assembly(stored: list[str], *, folder_at_save: str = "") -> bytes:
    """An assembly with one instance, ``c2``, ``c3``..., of each stored path; its file keys
    are "2", "3"... and each stores the creation time :data:`CT`."""
    t = TreeXml()
    t.top("m1")
    for i, path in enumerate(stored, start=2):
        t.file(str(i), path, swCreationTime=str(CT))
        t.model(f"m{i}", str(i))
        t.ref("m1", f"c{i}", 1, f"m{i}")
    return resolving_assembly(t, folder_at_save=folder_at_save)


# --------------------------------------------------------------------------- where a file is, no Qt
def _ref(status: str, **resolution) -> dict:
    return {
        "key": "6",
        "file_name": "p.SLDPRT",
        "stored_path": "Q:\\Old\\p.SLDPRT",
        "doc_type": "part",
        "nested": resolution.get("nested"),
        "resolution": {"status": status, "warnings": [], **resolution},
    }


def test_a_referenced_files_target_says_where_to_go():
    found = _ref(
        "moved",
        match={"root": reading.ROOT_ID, "path": "parts/p.SLDPRT"},
        rule="rebased",
        confidence="high",
        identity="match",
    )
    t = navigate.target(found, key="6")
    assert (t.kind, t.rel, t.openable, t.in_folder_list) == ("listed", "parts/p.SLDPRT", True, True)
    assert navigate.found_text(t) == "p.SLDPRT: moved, same place relative to this document (high confidence)"

    outside = _ref(
        "resolved",
        match={"root": None, "path": "D:\\Lib\\p.SLDPRT"},
        rule="stored_path",
        confidence="low",
        identity="differ",
    )
    t = navigate.target(outside, key="6")
    assert (t.kind, t.path, t.in_folder_list) == ("outside", "D:\\Lib\\p.SLDPRT", False)
    assert t.not_listed_reason == "outside the opened folder"
    assert "may be another document with the same name" in navigate.found_text(t)

    t = navigate.target(_ref("embedded", nested=VIRTUAL, rule="embedded"), key="6")
    assert (t.kind, t.nested, t.openable, t.in_folder_list) == ("nested", VIRTUAL, True, False)
    assert VIRTUAL in navigate.found_text(t)

    cands = [
        {"root": reading.ROOT_ID, "path": "a/p.SLDPRT", "found_by": "name_index", "identity": "match"},
        {"root": None, "path": "D:\\p.SLDPRT", "found_by": "stored_path", "identity": "differ"},
        {"root": reading.ROOT_ID, "path": "c/p.SLDPRT", "found_by": "name_index", "placeholder": True},
    ]
    t = navigate.target(_ref("ambiguous", candidates=cands), key="6")
    assert t.kind == "choose" and [c.location for c in t.candidates] == [c["path"] for c in cands]
    assert (navigate.choose(t, 0).kind, navigate.choose(t, 0).rel) == ("listed", "a/p.SLDPRT")
    assert (navigate.choose(t, 1).kind, navigate.choose(t, 1).path) == ("outside", "D:\\p.SLDPRT")
    assert "another document" in navigate.found_text(navigate.choose(t, 1))
    placeholder = navigate.choose(t, 2)
    assert placeholder.kind == "missing" and "cloud placeholder" in placeholder.why

    unc = _ref(
        "missing",
        warnings=[
            {"code": "stored_unc_not_checked", "stream": None, "message": "..."},
            {"code": "a_code_from_a_later_version", "stream": None, "message": "..."},
        ],
    )
    t = navigate.target(unc, key="6")
    assert t.kind == "missing" and not t.openable and t.not_listed_reason == "not found"
    assert t.why.startswith("No file of that name was found. Searched the opened folder")
    assert "network share" in t.why and "later_version" not in t.why
    sub = navigate.target(_ref("embedded_in_subassembly"), key="6")
    assert (sub.kind, sub.status) == ("missing", "embedded_in_subassembly")
    assert "sub-assembly's own file" in sub.why
    assert "holds no copy" in navigate.target(_ref("embedded_not_found"), key="6").why
    assert navigate.target(_ref("a_status_from_a_later_version"), key="6").kind == "missing"  # an open set
    assert navigate.target({**found, "resolution": None}, key="6", pending=True).kind == "pending"
    assert navigate.target(None, key="9", pending=True).in_folder_list is None
    assert navigate.target(None, key="9").kind == "unknown"


def _nodes(tree: dict) -> dict[str, dict]:
    out, stack = {}, list(tree["children"] or [])
    while stack:
        n = stack.pop()
        out[n["id"]] = n
        stack.extend(n["children"] or [])
    return out


def test_every_instance_solidworks_reported_goes_to_the_file_it_named(tmp_path):
    """In a moved copy of the fixtures, so that every stored path is stale: each instance
    of each configuration in ``ground_truth.json`` (a suppressed one, a rotated one, the
    Cyrillic part, the sub-assembly and the parts inside it) goes to the copy of the
    file SOLIDWORKS named, and each virtual one to a part stored inside the assembly.
    Each drawing view goes to its model."""
    kit = tmp_path / "Moved" / "Kit"
    kit.mkdir(parents=True)
    for name in DOCUMENTS:
        shutil.copy2(fixture_path(name), kit / name)
    before = _state(kit)
    instances = virtual = 0
    for name, entry in GT.items():
        if not isinstance(entry, dict) or entry.get("type") not in ("assembly", "drawing"):
            continue
        path = str(kit / name)
        sections = dict(reading.read_document(path, str(kit)))
        refs = sections["references"]["data"]["references"]
        files = {f["key"]: f for f in refs["files"]}
        if entry["type"] == "drawing":
            views = [v for s in refs["sheets"] for v in s["views"]]
            wanted = [v["referenced_document"] for s in entry["api"]["sheets"] for v in s["views"]]
            assert len(views) == len(wanted) >= 1, name
            for view, model in zip(views, wanted, strict=True):
                t = navigate.target(files[view["file"]], key=view["file"])
                assert (t.kind, t.rel) == ("listed", os.path.basename(model)), (name, view["name"])
            continue
        for cfg, reported in entry["api"]["configurations"].items():
            tree = reading.read_components(path, str(kit), cfg)["data"]["components"]
            nodes = _nodes(tree)
            for inst in reported["components"]:
                key = nodes[inst["name"]]["file"]
                t = navigate.target(files[key], key=key)
                if inst["virtual"]:
                    assert t.kind == "nested", (name, cfg, inst["name"])
                    nested = dict(reading.read_document(path, str(kit), nested=(t.nested,)))
                    assert nested["summary"]["data"]["summary"]["doc_type"] == "part"
                    virtual += 1
                else:
                    assert (t.kind, t.rel) == ("listed", inst["path"]), (name, cfg, inst["name"])
                    assert "high confidence" in t.how
                instances += 1
    assert instances >= 30 and virtual == 2  # o16's virtual part, in Default and in Lite
    assert _state(kit) == before


def test_a_virtual_part_is_read_and_exported_from_inside_its_assembly(tmp_path):
    before = _state(FIXTURES)
    asm = str(fixture_path(O16))
    sections = dict(reading.read_document(asm, str(FIXTURES), nested=(VIRTUAL,)))
    assert list(sections) == list(reading.SECTIONS) and all(s["ok"] for s in sections.values())
    summary = sections["summary"]["data"]["summary"]
    assert summary["doc_type"] == "part" and summary["file"]["name"] == "Part12-sldprt"
    assert json.loads(sections["summary"]["data"]["json"])["source"] == {"file": asm, "nested": VIRTUAL}
    assert sections["components"]["data"] == {"kind": "part"}
    out = tmp_path / "out"
    out.mkdir()
    result = reading.export_parasolid(
        asm, str(FIXTURES), str(out), text=False, overwrite=False, nested=(VIRTUAL,)
    )
    assert result["written"]
    assert all(
        os.path.basename(w["output"]).startswith("o16_asm_features_Part12-sldprt") for w in result["written"]
    )
    assert mesh3d.read_part_mesh(asm, str(FIXTURES), 1000)["state"] == "not_part"
    # Its own nested document has no display mesh: the one o16 keeps of it is drawn, and it is
    # the mesh o16's 3D view draws for its instance.
    with open_document(asm) as doc:
        assert doc.nested(VIRTUAL).mesh() is None or doc.nested(VIRTUAL).mesh().n_triangles == 0
        g = doc.display_geometry()
    (inst,) = [i for i in g.instances if i.id == "Part12^o16_asm_features-1"]
    own = g.meshes[inst.mesh].mesh
    virtual = mesh3d.read_part_mesh(asm, str(FIXTURES), 1000, nested=(VIRTUAL,))
    assert virtual["state"] == "ok" and virtual["stored_in"] == "assembly"
    assert virtual["data"].positions == own.positions.tobytes() and virtual["data"].n_triangles == 12
    over = mesh3d.read_part_mesh(asm, str(FIXTURES), 11, nested=(VIRTUAL,))  # o16's mesh of it is over
    assert over | {"seconds": None} == {"state": "too_large", "in_assembly": True, "cap": 11, "seconds": None}
    gone = list(reading.read_document(asm, str(FIXTURES), nested=("VirtualComp/nothing-sldprt",)))
    assert [name for name, _ in gone] == ["open"] and gone[0][1]["error"]["code"] == "stream_not_found"
    assert _state(FIXTURES) == before


def test_a_file_outside_the_opened_folder_is_read_within_its_own(tmp_path):
    opened = tmp_path / "Proj"
    opened.mkdir()
    part = _write(tmp_path / "lib" / "p.SLDPRT", fixture_path("o02_boxA.SLDPRT").read_bytes())
    refused = list(reading.read_document(str(part), str(opened)))  # never within the opened folder
    assert [name for name, _ in refused] == ["open"] and refused[0][1]["error"]["code"] == "path_refused"
    sections = dict(reading.read_document(str(part), str(opened), within=str(part.parent)))
    assert all(s["ok"] for s in sections.values())


# --------------------------------------------------------------------------- the window, offscreen
def _tab(name: str) -> int:
    from solidseas_app.viewer.details import TABS

    return TABS.index(name)


def _settle(v: Viewer) -> None:
    """Wait until the details are read and Back has put everything back."""
    _wait(v.app, lambda: not v.window.busy)


def _row(v: Viewer, tree: str, ident: str):
    """The row of ``tree`` named ``ident`` there: an instance id, a file key..."""
    from solidseas_app.viewer.details import _walk

    for item in _walk(v.window.details.linked_trees[tree]):
        if _ident(item) == ident:
            return item
    raise AssertionError(f"no row {ident} in {tree}")


def _ident(item) -> str | None:
    from solidseas_app.viewer.details import IDENT_ROLE

    return None if item is None else item.data(0, IDENT_ROLE)


def _go(v: Viewer, tree: str, item, mode: str = "open") -> None:
    """Double-click ``item`` of ``tree`` as the mouse does, press Enter on it (``enter``:
    how a sub-assembly's row, which a double-click opens and closes, goes to its file),
    or choose the context menu's Show in folder list, and wait until the file is shown."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    d = v.window.details
    d.tabs.setCurrentIndex(_tab("References" if tree == "references" else "Components"))
    widget = d.linked_trees[tree]
    widget.setCurrentItem(item)
    widget.scrollToItem(item)
    v.app.processEvents()
    if mode == "enter":
        QTest.keyClick(widget, Qt.Key.Key_Return)
    elif mode == "open":  # a double-click is a click and then the double-click event
        rect = widget.visualItemRect(item)  # a wide row runs past the view: click its first column
        point = QPoint(rect.left() + min(40, rect.width() // 2), rect.center().y())
        for send in (QTest.mouseClick, QTest.mouseDClick):
            send(widget.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    else:
        menu = d.component_menu(item)
        (show,) = [a for a in menu.actions() if a.text().startswith("Show in folder list")]
        assert show.isEnabled(), show.text()
        show.trigger()
        menu.deleteLater()
    v.app.processEvents()
    _settle(v)


def _listed(v: Viewer) -> str | None:
    """The path of the list's current row, or None when it has none."""
    w = v.window
    index = w.table.selectionModel().currentIndex()
    entry = w.model.entry(w.proxy.mapToSource(index))
    return entry["path"] if entry else None


def _back(v: Viewer, title: str, tab: str = "Components", *, key: bool = False) -> None:
    """Back, with the toolbar's action or (``key``) Alt+Left typed into the instance tree."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    w = v.window
    assert w.act_back.isEnabled()
    if key:
        w.activateWindow()
        QTest.keyClick(w.details.instances, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
    else:
        w.act_back.trigger()
    v.app.processEvents()
    _settle(v)
    assert w.details.title.text() == title and w.details.tabs.currentIndex() == _tab(tab)


@needs_qt
def test_o16_opens_each_kind_of_component_and_back_returns(viewer):
    w, d = viewer.window, viewer.window.details
    before = _state(FIXTURES)
    viewer.open(FIXTURES)
    viewer.select(O16)
    assert w.act_back.shortcut().toString() == "Alt+Left" and not w.act_back.isEnabled()
    d.tabs.setCurrentIndex(_tab("Components"))

    # o02_boxA-1: a part in the list, shown on its Preview tab; Back selects the instance again.
    _go(viewer, "instances", _row(viewer, "instances", "o02_boxA-1"))
    assert _listed(viewer) == "o02_boxA.SLDPRT" and d.title.text() == "o02_boxA.SLDPRT"
    assert d.tabs.currentIndex() == _tab("Preview") and w.apart is None and d.note.isHidden()
    assert w.statusBar().currentMessage().startswith("o02_boxA.SLDPRT: moved, ")
    assert "Back (Alt+Left) returns to o16_asm_features.SLDASM" in w.statusBar().currentMessage()
    _back(viewer, O16, key=True)
    assert _listed(viewer) == O16 and d.instances.currentItem().text(0) == "o02_boxA-1"
    assert not w.act_back.isEnabled() and not w.history

    # The sub-assembly opens on its Components tab (with Enter: a double-click opens and
    # closes its row); a part inside it opens from there, and each Back steps out one level.
    _go(viewer, "instances", _row(viewer, "instances", "o15_sub_asm-1"), mode="enter")
    assert _listed(viewer) == "o15_sub_asm.SLDASM" and d.tabs.currentIndex() == _tab("Components")
    _go(viewer, "instances", _row(viewer, "instances", "o07_boxB_h31-1"))
    assert _listed(viewer) == "o07_boxB_h31.SLDPRT" and len(w.history) == 2
    _back(viewer, "o15_sub_asm.SLDASM")
    assert d.instances.currentItem().text(0) == "o07_boxB_h31-1"
    _back(viewer, O16)
    assert _ident(d.instances.currentItem()) == "o15_sub_asm-1"

    # The part inside the sub-assembly, from o16's own tree.
    _go(viewer, "instances", _row(viewer, "instances", "o15_sub_asm-1/o02_boxA-1"))
    assert _listed(viewer) == "o02_boxA.SLDPRT"
    _back(viewer, O16)
    assert _ident(d.instances.currentItem()) == "o15_sub_asm-1/o02_boxA-1"

    # The Cyrillic part.
    _go(viewer, "instances", _row(viewer, "instances", "o17_деталь-1"))
    assert _listed(viewer) == "o17_деталь.SLDPRT" and d.title.text() == "o17_деталь.SLDPRT"
    _back(viewer, O16)

    # The virtual part: the nested document, shown on its own; the list has no selection.
    item = _row(viewer, "instances", "Part12^o16_asm_features-1")
    show = [a for a in d.component_menu(item).actions() if a.text().startswith("Show in folder list")]
    assert not show[0].isEnabled() and show[0].text() == "Show in folder list (stored inside the document)"
    _go(viewer, "instances", item)
    viewer.app.processEvents()
    _wait(viewer.app, lambda: not w._select_timer.isActive())
    assert d.title.text() == "Part12^o16_asm_features.SLDPRT" and _listed(viewer) is None
    assert d.tabs.currentIndex() == _tab("Overview")  # a virtual part stores no preview image
    assert w.apart is not None and w.source.nested == (VIRTUAL,) and w.source.path == str(fixture_path(O16))
    assert d.subtitle.text() == "Part, saved with SOLIDWORKS 2024, inside o16_asm_features.SLDASM"
    assert not d.note.isHidden() and d.note.text().startswith("A virtual component, stored inside")
    assert VIRTUAL in d.note.text() and "Back (Alt+Left) returns to o16_asm_features.SLDASM" in d.note.text()
    assert viewer.page("Overview").showing_content and d.summary["doc_type"] == "part"
    assert json.loads(d.summary_json)["source"]["nested"] == VIRTUAL
    assert w.act_parasolid.isEnabled() and not w.act_preview.isEnabled()  # it stores no preview image
    _back(viewer, O16)
    assert _listed(viewer) == O16 and d.note.isHidden() and w.apart is None
    assert d.instances.currentItem().text(0) == "Part12^o16_asm_features-1"

    # A row of the Files table, and Show in folder list, which keeps the tab.
    _go(viewer, "files", _row(viewer, "files", "11"))
    assert _listed(viewer) == "o06_boxA_props_mat_cfg.SLDPRT"
    _back(viewer, O16)
    assert d.files.currentItem().text(0) == "o06_boxA_props_mat_cfg.SLDPRT"
    _go(viewer, "instances", _row(viewer, "instances", "o09_import_step-1"), mode="show")
    assert _listed(viewer) == "o09_import_step.SLDPRT" and d.tabs.currentIndex() == _tab("Components")
    _back(viewer, O16)

    # The References tab goes there too.
    _go(viewer, "references", _row(viewer, "references", "18"))
    assert _listed(viewer) == "o07_boxB_h31.SLDPRT"
    _back(viewer, O16, "References")
    assert d.references.currentItem().text(0) == "o07_boxB_h31.SLDPRT"
    assert _state(FIXTURES) == before


@needs_qt
def test_a_double_click_on_a_sub_assembly_row_opens_and_closes_it(viewer):
    """As in Explorer and in SOLIDWORKS' FeatureManager, a double-click on a row with rows
    under it shows or hides them, and the document stays; Enter and Go to file go to its
    file. A part's row still goes to its file on a double-click."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    d = viewer.window.details
    viewer.open(FIXTURES)
    viewer.select(O16)
    d.tabs.setCurrentIndex(_tab("Components"))
    item = _row(viewer, "instances", "o15_sub_asm-1")
    assert item.childCount() == 2
    item.setExpanded(False)
    tree = d.instances
    asked: list = []
    d.componentRequested.connect(lambda *a: asked.append(a))
    for expanded in (True, False):
        rect = tree.visualItemRect(item)
        point = QPoint(rect.left() + min(40, rect.width() // 2), rect.center().y())
        for send in (QTest.mouseClick, QTest.mouseDClick):  # the events of a real double-click
            send(tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        viewer.app.processEvents()
        assert item.isExpanded() is expanded and asked == [] and d.title.text() == O16
    assert "A sub-assembly&#x27;s row opens and closes on a double-click" in tree.headerItem().toolTip(0)
    _go(viewer, "instances", item, mode="enter")
    assert _listed(viewer) == "o15_sub_asm.SLDASM" and len(asked) == 1
    _back(viewer, O16)
    _go(viewer, "instances", _row(viewer, "instances", "o09_import_step-1"))  # a part: a double-click
    assert _listed(viewer) == "o09_import_step.SLDPRT"
    _back(viewer, O16)


@needs_qt
def test_a_part_opened_from_an_instance_says_which_configuration_the_instance_uses(viewer):
    """o16's o06_boxA_props_mat_cfg-1 uses OracleAlt, and o06 was saved in Default: the
    status line says which configuration the instance uses, a note says the preview shows
    the file's active one, and Overview and Properties mark OracleAlt. A part used in its
    active configuration gets no note."""
    w, d = viewer.window, viewer.window.details
    viewer.open(FIXTURES)
    viewer.select(O16)
    _go(viewer, "instances", _row(viewer, "instances", "o06_boxA_props_mat_cfg-1"))
    assert d.title.text() == "o06_boxA_props_mat_cfg.SLDPRT"
    assert d.summary["active_configuration"] == "Default"
    assert "The instance uses its configuration OracleAlt." in w.statusBar().currentMessage()
    assert not d.note.isHidden()
    assert d.note.text() == (
        "Opened from an instance in o16_asm_features.SLDASM that uses this part's configuration OracleAlt. "
        "The file's active configuration is Default: the preview and the 3D view show Default, as the "
        "file was saved, and the Overview and Properties tabs mark OracleAlt."
    )
    rows = {}
    for item in _walk_items(d.overview):
        rows[item.text(0)] = item.text(1)
    assert rows["Used by the instance"] == "OracleAlt (in o16_asm_features.SLDASM)"
    assert "OracleAlt (used by the instance you opened it from)" in rows
    labels = [d.properties.topLevelItem(i).text(0) for i in range(d.properties.topLevelItemCount())]
    assert any(t.startswith("Configuration OracleAlt (used by the instance)") for t in labels), labels
    _back(viewer, O16)
    assert d.note.isHidden() and d.used_configuration is None
    _go(viewer, "instances", _row(viewer, "instances", "o09_import_step-1"))  # in its active configuration
    assert d.note.isHidden() and "The instance uses its configuration" in w.statusBar().currentMessage()


@needs_qt
def test_the_mouse_back_button_and_the_back_key_go_back(viewer):
    """The thumb button most mice have (XButton1, Qt's BackButton) and a keyboard's Back key
    go back as Alt+Left does, wherever the pointer is: the window sees them before the widget
    under the pointer, which would otherwise take them (the 3D view takes every button)."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QGuiApplication, QKeyEvent, QMouseEvent

    w, d = viewer.window, viewer.window.details
    viewer.open(FIXTURES)
    viewer.select(O16)
    handle = w.windowHandle()
    assert handle is not None

    def thumb(kind=QEvent.Type.MouseButtonPress):
        at = QPointF(w.width() * 0.8, w.height() * 0.5)  # over the details panel
        back, none = Qt.MouseButton.BackButton, Qt.KeyboardModifier.NoModifier
        QGuiApplication.sendEvent(handle, QMouseEvent(kind, at, handle.mapToGlobal(at), back, back, none))

    thumb()  # nothing to go back to: nothing happens
    assert d.title.text() == O16
    for press in ("button", "double", "key"):
        _go(viewer, "instances", _row(viewer, "instances", "o02_boxA-1"))
        assert d.title.text() == "o02_boxA.SLDPRT" and w.act_back.isEnabled()
        if press == "button":
            thumb()
        elif press == "double":  # a second quick press arrives as a double-click
            thumb(QEvent.Type.MouseButtonDblClick)
        else:
            key = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Back, Qt.KeyboardModifier.NoModifier)
            QGuiApplication.sendEvent(handle, key)
        viewer.app.processEvents()
        _settle(viewer)
        assert d.title.text() == O16 and _ident(d.instances.currentItem()) == "o02_boxA-1", press


def _walk_items(tree):
    from solidseas_app.viewer.details import _walk

    return list(_walk(tree))


@needs_qt
def test_back_returns_to_the_configuration_that_was_shown(viewer):
    d = viewer.window.details
    viewer.open(FIXTURES)
    viewer.select(O16)
    d.tabs.setCurrentIndex(_tab("Components"))
    d.configurationRequested.emit("Lite")
    _wait(viewer.app, lambda: d.configuration_shown() == "Lite" and d.pages["Components"].showing_content)
    _go(viewer, "instances", _row(viewer, "instances", "o02_boxA-3"))
    assert _listed(viewer) == "o02_boxA.SLDPRT"
    _back(viewer, O16)
    assert d.configuration_shown() == "Lite" and d.config_combo.currentText() == "Lite"
    assert d.instances.currentItem().text(0) == "o02_boxA-3"


@needs_qt
def test_a_drawings_views_and_models_go_to_their_files(viewer):
    d = viewer.window.details
    viewer.open(FIXTURES)
    viewer.select("o19_drw_asm.SLDDRW")
    _go(viewer, "sheets", d.find_item("sheets", "Drawing View1"))
    assert _listed(viewer) == O16 and d.tabs.currentIndex() == _tab("Components")
    _back(viewer, "o19_drw_asm.SLDDRW")
    assert d.sheets.currentItem().text(0) == "Drawing View1"
    viewer.select("o18_drw_boxA.SLDDRW")
    _go(viewer, "models", d.find_item("models", "o02_boxA.SLDPRT"))
    assert _listed(viewer) == "o02_boxA.SLDPRT" and d.tabs.currentIndex() == _tab("Preview")
    _back(viewer, "o18_drw_boxA.SLDDRW")


@needs_qt
def test_a_moved_copy_of_o08_opens_its_part_where_it_is_now(viewer, tmp_path):
    folder = tmp_path / "Moved"
    folder.mkdir()
    for name in (ASSEMBLY, "o02_boxA.SLDPRT"):
        shutil.copy2(fixture_path(name), folder / name)
    before = _state(folder)
    viewer.open(folder)
    viewer.select(ASSEMBLY)
    _go(viewer, "instances", _row(viewer, "instances", "o02_boxA-2"))
    w = viewer.window
    assert _listed(viewer) == "o02_boxA.SLDPRT" and w.apart is None
    assert w.source == reading.Source(str(folder / "o02_boxA.SLDPRT"), str(folder))
    assert w.statusBar().currentMessage().startswith("o02_boxA.SLDPRT: moved, ")
    _back(viewer, ASSEMBLY)
    assert w.details.instances.currentItem().text(0) == "o02_boxA-2"
    assert _state(folder) == before


@needs_qt
def test_the_list_filters_widen_only_as_far_as_the_file_needs(viewer, tmp_path, no_drive_q):
    proj = tmp_path / "Proj"
    _write(proj / "parts" / "p.SLDPRT", part_with_creation_time(CT))
    _write(
        proj / "asm" / "top.SLDASM",
        _assembly(["Q:\\Old\\parts\\p.SLDPRT"], folder_at_save="Q:\\Old\\asm\\"),
    )
    before = _state(proj)
    w = viewer.window
    viewer.open(proj)
    viewer.select("asm/top.SLDASM")
    w.tree.setCurrentItem(w._folders["asm"])  # the list shows the asm folder, filtered by name
    w.filter.setText("top")
    assert _listed(viewer) == "asm/top.SLDASM"
    _go(viewer, "instances", _row(viewer, "instances", "c2-1"))
    assert _listed(viewer) == "parts/p.SLDPRT"
    assert w.proxy.folder == "" and w.filter.text() == ""  # the folder holding both, no name filter
    _back(viewer, "top.SLDASM")
    assert w.proxy.folder == "asm" and w.filter.text() == "top" and _listed(viewer) == "asm/top.SLDASM"
    assert _state(proj) == before


@needs_qt
def test_a_component_outside_the_opened_folder_opens_on_its_own(viewer, tmp_path, no_drive_q):
    new = tmp_path / "New"
    lib = _write(new / "lib" / "p.SLDPRT", part_with_creation_time(CT))
    _write(
        new / "Proj" / "asm.SLDASM", _assembly(["Q:\\Old\\lib\\p.SLDPRT"], folder_at_save="Q:\\Old\\Proj\\")
    )
    before = _state(new)
    w, d = viewer.window, viewer.window.details
    viewer.open(new / "Proj")
    viewer.select("asm.SLDASM")
    item = _row(viewer, "instances", "c2-1")
    show = [a for a in d.component_menu(item).actions() if a.text().startswith("Show in folder list")]
    assert not show[0].isEnabled() and show[0].text().endswith("(outside the opened folder)")
    generation = w.generation
    w.go_to_component("2", "show")  # asked for anyway: it says why, and nothing is opened
    assert w.generation == generation and not w.history
    assert w.statusBar().currentMessage() == "p.SLDPRT is not in the list: outside the opened folder."
    _go(viewer, "instances", item)
    _wait(viewer.app, lambda: not w._select_timer.isActive())
    assert d.title.text() == "p.SLDPRT" and _listed(viewer) is None
    assert w.source == reading.Source(str(lib), str(lib.parent))
    assert d.subtitle.text().endswith(f"outside the opened folder, in {lib.parent}")
    assert d.note.text().startswith("Outside the folder you opened, so it is not in the list")
    assert viewer.page("Overview").showing_content and viewer.page("Paths").showing_content
    assert "moved, same place relative to this document" in w.statusBar().currentMessage()
    out = tmp_path / "out"
    out.mkdir()
    exported = reading.export_preview(
        w.source.path, w.folder, str(out), overwrite=False, within=w.source.within
    )  # what Export Preview Image runs for it
    assert Path(exported["output"]).parent == out
    _back(viewer, "asm.SLDASM")
    assert _listed(viewer) == "asm.SLDASM" and d.note.isHidden()
    assert _state(new) == before


@needs_qt
def test_a_missing_component_says_where_it_was_looked_for(viewer, tmp_path, no_drive_q):
    folder = tmp_path / "Job"
    _write(
        folder / "top.SLDASM", _assembly(["Q:\\Gone\\gone.SLDPRT", "\\\\fs01\\share\\far.SLDPRT"])
    )
    before = _state(folder)
    w, d = viewer.window, viewer.window.details
    told: list[tuple] = []
    w.explain = lambda title, text, offer=None: told.append((title, text, offer)) or False
    viewer.open(folder)
    viewer.select("top.SLDASM")
    generation = w.generation
    _go(viewer, "instances", _row(viewer, "instances", "c2-1"))
    _go(viewer, "instances", _row(viewer, "instances", "c3-1"))
    assert w.generation == generation and d.title.text() == "top.SLDASM" and not w.history
    (title, gone, offer), (_, far, _) = told
    assert title == "Go to file" and offer is None
    assert gone.startswith("gone.SLDPRT cannot be opened from here.\n\nNo file of that name was found.")
    assert gone.endswith("Stored path: Q:\\Gone\\gone.SLDPRT")
    assert "network share" in far and "Stored path: \\\\fs01\\share\\far.SLDPRT" in far
    show = [
        a for a in d.component_menu(_row(viewer, "instances", "c2-1")).actions() if "folder list" in a.text()
    ]
    assert show[0].text() == "Show in folder list (not found)" and not show[0].isEnabled()
    assert _state(folder) == before


@needs_qt
def test_an_ambiguous_component_asks_which_file(viewer, tmp_path, no_drive_q):
    from solidseas_app.viewer.window import CandidateDialog

    folder = tmp_path / "Job"
    for sub in ("a", "b"):
        _write(folder / sub / "p.SLDPRT", part_with_creation_time(CT))
    _write(folder / "top.SLDASM", _assembly(["Q:\\Gone\\p.SLDPRT"]))
    before = _state(folder)
    w = viewer.window
    asked: list = []
    w.choose_candidate = lambda t: asked.append(t) or None  # Cancel: nothing happens
    viewer.open(folder)
    viewer.select("top.SLDASM")
    _go(viewer, "instances", _row(viewer, "instances", "c2-1"))
    assert len(asked) == 1 and _listed(viewer) == "top.SLDASM" and not w.history
    t = asked[0]
    assert [c.location for c in t.candidates] == ["a/p.SLDPRT", "b/p.SLDPRT"]

    dialog = CandidateDialog(w, t)
    assert dialog.list.topLevelItemCount() == 2 and dialog.chosen() == 0 and dialog.open_button.isEnabled()
    assert dialog.list.topLevelItem(1).text(1) == "by name in the opened folder"
    dialog.list.setCurrentItem(dialog.list.topLevelItem(1))
    assert dialog.chosen() == 1
    dialog.deleteLater()

    w.choose_candidate = lambda t: 1
    _go(viewer, "instances", _row(viewer, "instances", "c2-1"))
    assert _listed(viewer) == "b/p.SLDPRT" and "chosen from 2 files" in w.statusBar().currentMessage()
    _back(viewer, "top.SLDASM")
    assert _state(folder) == before


@needs_qt
def test_a_virtual_part_of_a_sub_assembly_offers_the_sub_assembly(viewer, tmp_path, no_drive_q):
    folder = tmp_path / "Job"
    t = TreeXml()
    t.file("2", "Q:\\J\\sub.SLDASM", "ASSEMBLY")
    t.file("3", "Q:\\J\\Part1^sub.SLDPRT")
    t.top("m1")
    t.model("m2", "2")
    t.model("m3", "3")
    t.ref("m1", "sub", 1, "m2")
    t.ref("m2", "Part1^sub", 1, "m3", virtual=True)
    _write(folder / "top.SLDASM", resolving_assembly(t))
    shutil.copy2(fixture_path("o15_sub_asm.SLDASM"), folder / "sub.SLDASM")
    before = _state(folder)
    w = viewer.window
    told: list = []
    w.explain = lambda title, text, offer=None: told.append((text, offer)) or True  # takes the offer
    viewer.open(folder)
    viewer.select("top.SLDASM")
    _go(viewer, "instances", _row(viewer, "instances", "sub-1/Part1^sub-1"))
    ((text, offer),) = told
    assert offer == "Open the Sub-assembly" and "inside that sub-assembly's own file" in text
    _settle(viewer)
    assert _listed(viewer) == "sub.SLDASM" and w.details.tabs.currentIndex() == _tab("Components")
    _back(viewer, "top.SLDASM")
    assert _ident(w.details.instances.currentItem()) == "sub-1/Part1^sub-1"
    assert _state(folder) == before


@needs_qt
def test_a_sub_assembly_opens_in_the_configuration_its_instance_uses(viewer, tmp_path, no_drive_q):
    """As SOLIDWORKS opens a component in the configuration the assembly references."""
    folder = tmp_path / "Job"
    t = TreeXml()
    t.file("2", "Q:\\J\\sub.SLDASM", "ASSEMBLY")
    t.top("m1")
    t.model("m2", "2", config="Lite")
    t.model("m3", "2")
    t.ref("m1", "sub", 1, "m2", config="Lite")
    t.ref("m1", "sub", 2, "m3")
    _write(folder / "top.SLDASM", resolving_assembly(t))
    shutil.copy2(fixture_path(O16), folder / "sub.SLDASM")  # its active configuration is Default
    before = _state(folder)
    d = viewer.window.details
    viewer.open(folder)
    viewer.select("top.SLDASM")
    _go(viewer, "instances", _row(viewer, "instances", "sub-1"))
    assert _listed(viewer) == "sub.SLDASM" and d.configuration_shown() == "Lite"
    assert _row(viewer, "instances", "o15_sub_asm-1").text(2) == "suppressed"  # Lite's own tree
    _back(viewer, "top.SLDASM")
    _go(viewer, "instances", _row(viewer, "instances", "sub-2"))
    assert _listed(viewer) == "sub.SLDASM" and d.configuration_shown() == "Default"
    assert _state(folder) == before


@needs_qt
def test_a_file_asked_for_before_the_references_are_read_waits_for_them(viewer):
    w = viewer.window
    viewer.open(FIXTURES)
    assert w.select_document(O16)  # the read has started; no section has been shown yet
    w.go_to_component("26")  # o17
    assert w.busy and "once its location is worked out" in w.statusBar().currentMessage()
    _settle(viewer)
    assert _listed(viewer) == "o17_деталь.SLDPRT" and len(w.history) == 1
    _back(viewer, O16, "Overview")


@needs_qt
def test_the_self_test_opens_components_and_goes_back(app, tmp_path, monkeypatch):
    import sys

    from solidseas_app.viewer import app as viewer_app

    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)  # main() installs its own
    before = _state(FIXTURES)
    shots = tmp_path / "shots"
    opened = ["o02_boxA-1", "o15_sub_asm-1", "Part12^o16_asm_features-1"]
    args = ["--self-test", str(FIXTURES), "--screenshot-dir", str(shots), "--select", O16]
    args += [a for n in opened for a in ("--open-component", n)]
    args += ["--select", "o19_drw_asm.SLDDRW", "--open-component", "Drawing View1"]  # each its own rows
    assert viewer_app.main(args) == 0
    report = json.loads((shots / "selftest.json").read_text(encoding="utf-8"))
    assert report["ok"]
    got = [
        (d["name"], c["name"], c["outcome"], c["shown"], c["back"])
        for d in report["documents"]
        for c in d["components_opened"]
    ]
    assert got == [
        (O16, "o02_boxA-1", "listed", "o02_boxA.SLDPRT", True),
        (O16, "o15_sub_asm-1", "listed", "o15_sub_asm.SLDASM", True),
        (O16, "Part12^o16_asm_features-1", "apart", "Part12^o16_asm_features.SLDPRT", True),
        ("o19_drw_asm.SLDDRW", "Drawing View1", "listed", O16, True),
    ]
    names = [os.path.basename(p) for p in report["screenshots"]]
    assert len(names) == 2 + 1 + 2 * (9 + 1) + 2 * (len(opened) + 1)
    assert any(n.endswith("o16_asm_features_open_o02_boxA-1.png") for n in names)
    assert any(n.endswith("o16_asm_features_back_from_Part12_o16_asm_features-1.png") for n in names)
    assert any(n.endswith("o19_drw_asm_open_Drawing_View1.png") for n in names)
    assert viewer_app.main(["--open-component", "x"]) == viewer_app.EXIT_USAGE  # it belongs to the self-test
    usage = viewer_app.main(
        [
            "--self-test",
            str(FIXTURES),
            "--report",
            str(tmp_path / "r.json"),
            "--select-all",
            "--open-component",
            "x",
        ]
    )
    assert usage == viewer_app.EXIT_USAGE
    assert _state(FIXTURES) == before
