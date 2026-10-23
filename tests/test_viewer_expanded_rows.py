"""Rows on the Components tab for the parts read from a sub-assembly's own file.

An assembly's tree may name a sub-assembly and list none of its components. The 3D
view's read expands such a sub-assembly from its own file (``solidseas.geometry``);
the read now says what it expanded (``DisplayGeometry.expanded``), the mesh process
sends those instances as rows (``mesh3d.expanded_rows``), the window checks them
(``meshproc.checked_expanded``) and the Components tab adds them under the
sub-assembly's row, where they are picked, and go to their files, as every row does.
"""

import math
import os
import shutil
from pathlib import Path

import pytest

from builders import TreeXml, assembly_with_tree
from solidseas import Root, Roots, open_document
from solidseas import geometry as geo
from solidseas_app.viewer import mesh3d, meshproc, reading
from support import fixture_path

try:
    import PySide6.QtWidgets  # noqa: F401
except ImportError:  # the window tests need the [app] extra
    HAVE_QT = False
else:
    HAVE_QT = True

needs_qt = pytest.mark.skipif(not HAVE_QT, reason="PySide6 is not installed: the panel is not tested")

O15, O16 = "o15_sub_asm.SLDASM", "o16_asm_features.SLDASM"
PARTS = ("o02_boxA-1", "o07_boxB_h31-1")


def _o16_transform(ident: str) -> str:
    with open_document(fixture_path(O16)) as doc:
        node = next(n for n in doc.components().walk() if n.id == ident)
        return " ".join(repr(v) for v in node.transform.stored)


def _unlisted_top(sub: str = O15, name: str = "o15_sub_asm") -> bytes:
    """top -> one instance of ``sub``, turned as o16 turns o15, its components not listed."""
    t = TreeXml()
    t.top("m1")
    t.file("2", sub, "ASSEMBLY")
    t.model("m2", "2")
    t.ref("m1", name, 1, "m2", transform=_o16_transform("o15_sub_asm-1"))
    return assembly_with_tree(t)


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    """top.SLDASM naming o15 alone, with o15 and its two parts beside it."""
    f = tmp_path / "jobs"
    f.mkdir()
    (f / "top.SLDASM").write_bytes(_unlisted_top())
    for name in (O15, "o02_boxA.SLDPRT", "o07_boxB_h31.SLDPRT"):
        shutil.copy2(fixture_path(name), f / name)
    return f


def _geometry(path: Path, **kw):
    with open_document(path) as doc:
        return geo.display_geometry(doc, roots=Roots([Root("jobs", str(path.parent))]), **kw)


# --------------------------------------------------------------------------- the library
def test_the_read_lists_each_sub_assembly_it_expanded_from_its_own_file(folder):
    g = _geometry(folder / "top.SLDASM", allow_outside_roots=False)
    (e,) = g.expanded
    assert (e.id, e.file, e.configuration) == ("o15_sub_asm-1", "2", "Default")
    assert [n.id for n in e.tree.children] == list(PARTS)
    with open_document(folder / "top.SLDASM") as doc:
        (top,) = doc.components().children
    assert e.placement == top.placement
    # Its parts were read from their own files, so its files were looked for.
    found = {r.match.path for r in e.resolution.results.values() if r.match is not None}
    assert found == {"o02_boxA.SLDPRT", "o07_boxB_h31.SLDPRT"}
    # Drawn from o15's own meshes no file of it is looked for, unless asked.
    stored = _geometry(folder / "top.SLDASM", allow_outside_roots=False, sources=("assembly", "subassembly"))
    assert stored.expanded[0].resolution is None
    asked = _geometry(
        folder / "top.SLDASM",
        allow_outside_roots=False,
        sources=("assembly", "subassembly"),
        resolve_expanded=True,
    )
    assert {r.match.path for r in asked.expanded[0].resolution.results.values() if r.match} == found
    # Its two identity reads are files opened, like every resolution's.
    assert asked.counts["files_opened"] == stored.counts["files_opened"] + 2


def test_a_sub_assembly_used_twice_is_listed_for_each_instance_with_one_tree(tmp_path):
    t = TreeXml()
    t.top("m1")
    t.file("2", O15, "ASSEMBLY")
    t.model("m2", "2")
    t.ref("m1", "o15_sub_asm", 1, "m2")
    t.ref("m1", "o15_sub_asm", 2, "m2", transform="1 0 0 0 0 1 0 0 0 0 1 0 0.5 0 0 1")
    f = tmp_path / "jobs"
    f.mkdir()
    (f / "top.SLDASM").write_bytes(assembly_with_tree(t))
    shutil.copy2(fixture_path(O15), f / O15)
    g = _geometry(f / "top.SLDASM", allow_outside_roots=False)
    assert [e.id for e in g.expanded] == ["o15_sub_asm-1", "o15_sub_asm-2"]
    assert g.expanded[0].tree is g.expanded[1].tree
    assert g.expanded[1].placement.translation_m == pytest.approx((0.5, 0, 0))


# --------------------------------------------------------------------------- the mesh process
def test_the_mesh_read_sends_rows_under_the_sub_assembly_in_the_top_frame(folder):
    result = mesh3d.read_assembly_scene(str(folder / "top.SLDASM"), str(folder), str(folder), 1_000_000)
    assert result["state"] == "ok"
    (entry,) = result["data"].expanded
    assert (entry["id"], entry["file"], entry["configuration"], entry["nodes"]) == (
        "o15_sub_asm-1",
        "2",
        "Default",
        2,
    )
    rows = {r["id"]: r for r in entry["children"]}
    assert sorted(rows) == [f"o15_sub_asm-1/{p}" for p in PARTS]
    # Each row's placement is where the 3D view drew that instance.
    g = _geometry(folder / "top.SLDASM")
    for inst in g.instances:
        row = rows[inst.id]
        assert row["parent"] == "o15_sub_asm-1" and row["file"].startswith("2/")
        assert row["placement"]["translation_m"] == pytest.approx(
            list(inst.placement.translation_m), abs=1e-12
        )
        rotation = [v for r in row["placement"]["rotation"] for v in r]
        assert rotation == pytest.approx([v for r in inst.placement.rotation for v in r], abs=1e-12)
    files = {f["key"]: f for f in entry["files"]}
    for row in rows.values():
        f = files[row["file"]]
        assert f["resolution"]["key"] == row["file"]
        assert f["resolution"]["match"] == {"root": reading.ROOT_ID, "path": f["file_name"]}
    # What crosses the pipe is checked and comes back as it was sent.
    assert (
        meshproc.checked_expanded(result["data"].expanded)[0]["children"][0]["id"]
        == entry["children"][0]["id"]
    )


def test_the_rows_from_the_mesh_process_are_checked_before_the_window_uses_them():
    def node(**kw):
        n = {
            "id": "s-1/p-1",
            "name": "p-1",
            "file": "2/3",
            "configuration": "Default",
            "suppressed": False,
            "hidden": False,
            "excluded_from_bom": False,
            "virtual": False,
            "children_state": "none",
            "placement": {"rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "translation_m": [0.1, 0, 0]},
            "transform": {"translation_m": [0.1, 0, 0], "stored": [1] * 16},
            "children": [],
        }
        n.update(kw)
        return n

    def file(match, **kw):
        f = {
            "key": "2/3",
            "file_name": "p.SLDPRT",
            "doc_type": "part",
            "resolution": {"status": "moved", "match": match},
        }
        f.update(kw)
        return f

    good = {
        "id": "s-1",
        "file": "2",
        "configuration": "Default",
        "nodes": 1,
        "children": [node()],
        "files": [],
    }
    (kept,) = meshproc.checked_expanded([good, "not an entry", {"id": 5, "file": "2"}])
    assert kept["children"][0]["placement"]["translation_m"] == [0.1, 0, 0]
    assert "stored" not in kept["children"][0]["transform"]  # only what the tab reads crosses
    bad_nodes = [
        node(id=7),
        node(suppressed="no"),
        node(children_state=None),
        node(name=None),
    ]
    assert meshproc.checked_expanded([{**good, "children": bad_nodes}])[0]["children"] == []
    odd = meshproc.checked_expanded(
        [
            {
                **good,
                "children": [
                    node(
                        placement={
                            "rotation": [[math.nan, 0, 0], [0, 1, 0], [0, 0, 1]],
                            "translation_m": [0, 0, 0],
                        }
                    )
                ],
            }
        ]
    )
    assert odd[0]["children"][0]["placement"] is None  # kept, with no place to show
    root = reading.ROOT_ID
    absolute = os.path.abspath("p.SLDPRT")
    places = {
        "inside": ({"root": root, "path": "sub/p.SLDPRT"}, {"root": root, "path": "sub/p.SLDPRT"}),
        "outside": ({"root": None, "path": absolute}, {"root": None, "path": absolute}),
        "climbs": ({"root": root, "path": "../p.SLDPRT"}, None),
        "rooted": ({"root": root, "path": absolute}, None),
        "relative outside": ({"root": None, "path": "p.SLDPRT"}, None),
        "another root": ({"root": "other", "path": "p.SLDPRT"}, None),
        "stream": ({"root": root, "path": "p.SLDPRT:hidden"}, None),
    }
    for what, (sent, expected) in places.items():
        (got,) = meshproc.checked_expanded([{**good, "files": [file(sent)]}])
        assert got["files"][0]["resolution"]["match"] == expected, what
    many = {**good, "children": [node(id=f"s-1/p-{k}") for k in range(10)]}
    assert len(meshproc.checked_expanded([many], most=4)[0]["children"]) == 4


# --------------------------------------------------------------------------- the Components tab
@pytest.fixture
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _panel(folder: Path, name: str = "top.SLDASM"):
    from solidseas_app.viewer.details import DetailsPanel

    panel = DetailsPanel()
    panel.begin({"path": name, "type": "file", "status": "ok"})
    for section, data in reading.read_document(str(folder / name), str(folder)):
        panel.set_section(section, data)
    return panel


def _arrive(panel, folder: Path, name: str = "top.SLDASM", configuration: str = "Default") -> None:
    scene = mesh3d.read_assembly_scene(str(folder / name), str(folder), str(folder), 1_000_000)["data"]
    panel.preview.expanded_rows = meshproc.checked_expanded(scene.expanded)
    panel.preview.expanded_configuration = configuration
    panel.preview.rowsArrived.emit()


def _children(item) -> list[str]:
    return [item.child(i).text(0) for i in range(item.childCount())]


@needs_qt
def test_the_components_tab_lists_the_parts_read_from_a_sub_assemblys_own_file(app, folder):
    from solidseas_app.viewer import navigate
    from solidseas_app.viewer.reading import mm

    panel = _panel(folder)
    host = panel.instance_item("o15_sub_asm-1")
    assert host is not None and host.childCount() == 0
    ident = f"o15_sub_asm-1/{PARTS[0]}"
    assert panel.instance_item(ident) is None and panel.row_of(ident) == "o15_sub_asm-1"
    _arrive(panel, folder)
    assert _children(host) == list(PARTS) and host.isExpanded()
    row = panel.instance_item(ident)
    assert row is not None and row.parent() is host and panel.row_of(ident) == ident
    key, parent, configuration = panel.instance_link(ident)
    assert key.startswith("2/") and (parent, configuration) == ("2", "Default")
    g = _geometry(folder / "top.SLDASM")
    placed = next(i for i in g.instances if i.id == ident)
    assert [row.text(c) for c in (3, 4, 5)] == [mm(v) for v in placed.placement.translation_m]
    assert "own file" in row.toolTip(0)
    t = panel.target(key)
    assert (t.kind, t.rel, t.doc_type) == (navigate.LISTED, "o02_boxA.SLDPRT", "part")
    assert panel.select_instance(ident) and panel.instances.currentItem() is row
    # The same rows again add nothing; another configuration's rows wait for their tab.
    _arrive(panel, folder)
    assert _children(host) == list(PARTS)
    panel.deleteLater()


@needs_qt
def test_rows_that_arrive_before_the_components_go_under_them_when_they_come(app, folder):
    from solidseas_app.viewer.details import DetailsPanel

    panel = DetailsPanel()
    panel.begin({"path": "top.SLDASM", "type": "file", "status": "ok"})
    _arrive(panel, folder)  # the 3D view's read came first: nothing to put them under yet
    for section, data in reading.read_document(str(folder / "top.SLDASM"), str(folder)):
        panel.set_section(section, data)
    assert _children(panel.instance_item("o15_sub_asm-1")) == list(PARTS)
    other = _panel(folder)
    _arrive(other, folder, configuration="Another")  # read for another configuration
    assert other.instance_item("o15_sub_asm-1").childCount() == 0
    panel.deleteLater()
    other.deleteLater()


@needs_qt
def test_a_virtual_part_of_the_sub_assembly_points_to_the_sub_assembly(app, tmp_path):
    """o16 named by a top assembly that lists none of its components: o16's virtual part
    is stored inside o16's own file, so its row cannot go to a file of its own, and says
    it is stored in the sub-assembly (3D Print looks for it there)."""
    from solidseas_app.viewer import navigate
    from solidseas_app.viewer.details import IDENT_ROLE

    f = tmp_path / "jobs"
    f.mkdir()
    (f / "top.SLDASM").write_bytes(_unlisted_top(O16, "o16_asm_features"))
    shutil.copy2(fixture_path(O16), f / O16)
    panel = _panel(f)
    _arrive(panel, f)
    host = panel.instance_item("o16_asm_features-1")
    assert host is not None and host.childCount() > 0
    virtual = [
        item
        for item in (host.child(i) for i in range(host.childCount()))
        if item.text(0).startswith("Part12^")
    ]
    (item,) = virtual
    key = panel.instance_link(item.data(0, IDENT_ROLE))[0]
    t = panel.target(key)
    assert (t.kind, t.status) == (navigate.MISSING, "embedded_in_subassembly")
    assert "sub-assembly" in t.why
    panel.deleteLater()


def test_no_file_read_is_changed(folder):
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in folder.iterdir()}
    mesh3d.read_assembly_scene(str(folder / "top.SLDASM"), str(folder), str(folder), 1_000_000)
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in folder.iterdir()} == before
