"""The SolidSeas Viewer preview (``solidseas_app.viewer``).

The reading, export and wording helpers import no Qt and are tested
everywhere. The window tests need PySide6 and are skipped without it; they run
offscreen (``QT_QPA_PLATFORM=offscreen``), open real folders, wait for the
background reads and check what the tabs show. Every test that reads files
checks that none of them changed: same SHA-256, same modification time.

Several tests reproduce what a review of the first preview found: tooltips
that rendered document text as rich text (and so loaded the images it named),
self-test outputs and exports that could land in the folder being read,
children of a suppressed sub-assembly drawn as active, trees that held the
window for seconds, and labels that showed the library's codes.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from builders import (
    TreeXml,
    assembly_with_tree,
    build_modern,
    drawing_keywords,
    fixture_streams,
    rebuild,
    sheet_names,
)
from solidseas import model
from solidseas.errors import OutputRefusedError
from solidseas_app.viewer import mesh3d, reading, viewmath, wording
from support import ASSEMBLY, DOCUMENTS, FIXTURES, fixture_path

# The fixtures of other formats (STL, 3MF, STEP, Parasolid) that the viewer lists beside
# the SOLIDWORKS documents.
MODEL_FIXTURES = sorted(
    p.name for p in FIXTURES.iterdir() if p.suffix.lower() in (".stl", ".3mf", ".step", ".x_t", ".x_b")
)

WINDOWS = os.name == "nt"
_SRC = str(Path(__file__).resolve().parent.parent / "src")

try:
    import PySide6.QtWidgets  # noqa: F401
except ImportError:  # the window tests need the [app] extra
    HAVE_QT = False
else:
    HAVE_QT = True

needs_qt = pytest.mark.skipif(
    not HAVE_QT,
    reason="PySide6 is not installed (pip install solidseas[app]): the viewer window is not tested",
)


def _state(folder: Path) -> dict[str, tuple[str, int]]:
    return {
        str(p.relative_to(folder)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


@pytest.fixture
def crafted(tmp_path: Path) -> Path:
    """A folder with a part, a part without a preview, a file that is not a document
    and a truncated assembly."""
    folder = tmp_path / "docs"
    folder.mkdir()
    shutil.copy2(fixture_path("o02_boxA.SLDPRT"), folder / "o02_boxA.SLDPRT")
    (folder / "no_preview.SLDPRT").write_bytes(
        rebuild(fixture_path("o02_boxA.SLDPRT"), drop=("Preview", "PreviewPNG"))
    )
    (folder / "garbage.SLDPRT").write_bytes(b"this is not a SOLIDWORKS document\r\n" * 64)
    (folder / "truncated.SLDASM").write_bytes(fixture_path(ASSEMBLY).read_bytes()[:3000])
    return folder


# --------------------------------------------------------------------------- reading, no Qt
def test_rotation_text():
    assert reading.rotation_text([[1, 0, 0], [0, 1, 0], [0, 0, 1]]) == "none"
    assert reading.rotation_text([[0, -1, 0], [1, 0, 0], [0, 0, 1]]) == "90° about Z"
    assert reading.rotation_text([[0, 1, 0], [-1, 0, 0], [0, 0, 1]]) == "90° about -Z"
    assert reading.rotation_text([[1, 0, 0], [0, -1, 0], [0, 0, -1]]) == "180° about X"
    a, b, c = 0.8440296287459854, -0.2931284138572722, 0.4490987851112869  # 40 degrees about (1, 1, 1)
    assert reading.rotation_text([[a, b, c], [c, a, b], [b, c, a]]) == "40° about (0.577, 0.577, 0.577)"


def test_millimetres():
    assert reading.mm(0.05) == "50"
    assert reading.mm(-0.0) == "0"
    assert reading.mm(0.025321) == "25.321"
    assert reading.mm(None) == ""


def test_read_document_gives_every_section():
    sections = dict(reading.read_document(str(fixture_path(ASSEMBLY)), str(FIXTURES)))
    assert list(sections) == list(reading.SECTIONS)
    assert all(s["ok"] for s in sections.values())
    tree = sections["components"]["data"]["components"]
    assert [n["name"] for n in tree["children"]] == ["o02_boxA-1", "o02_boxA-2"]
    assert json.loads(sections["summary"]["data"]["json"])["kind"] == "document_summary"
    refs = sections["references"]["data"]["references"]
    assert refs["files"][0]["resolution"]["match"] == {"root": reading.ROOT_ID, "path": "o02_boxA.SLDPRT"}


def test_read_document_reports_a_file_that_does_not_open(crafted):
    before = _state(crafted)
    sections = list(reading.read_document(str(crafted / "garbage.SLDPRT"), str(crafted)))
    assert [name for name, _ in sections] == ["open"]
    assert sections[0][1]["error"]["code"] == "unknown_format"
    assert _state(crafted) == before


def test_exports_write_only_where_asked(crafted, tmp_path):
    before = _state(crafted)
    part = str(crafted / "o02_boxA.SLDPRT")
    out = tmp_path / "out"
    out.mkdir()
    result = reading.export_parasolid(part, str(crafted), str(out), text=True, overwrite=False)
    assert sorted(w["kind"] for w in result["written"]) == ["x_b", "x_t"]
    assert all(os.path.getsize(w["output"]) > 0 for w in result["written"])
    shot = reading.export_preview(part, str(crafted), str(out), overwrite=False)
    assert Path(shot["output"]).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    with pytest.raises(OutputRefusedError):  # an existing file is replaced only when asked
        reading.export_preview(part, str(crafted), str(out), overwrite=False)
    reading.export_preview(part, str(crafted), str(out), overwrite=True)
    assert _state(crafted) == before


@pytest.mark.parametrize("where", [".", "sub"])
def test_exports_refuse_the_opened_folder(crafted, where):
    before = _state(crafted)
    part = str(crafted / "o02_boxA.SLDPRT")
    target = crafted / where
    target.mkdir(exist_ok=True)
    with pytest.raises(OutputRefusedError):
        reading.export_parasolid(part, str(crafted), str(target), text=False, overwrite=True)
    with pytest.raises(OutputRefusedError):
        reading.export_preview(part, str(crafted), str(target), overwrite=True)
    assert _state(crafted) == before


def _admin_share(path: Path) -> str | None:
    r"""``\\localhost\C$\...`` for a local folder, or None when that share is not reachable."""
    drive, rest = os.path.splitdrive(str(path))
    if not WINDOWS or len(drive) != 2:
        return None
    alias = f"\\\\localhost\\{drive[0]}${rest}"
    return alias if os.path.isdir(alias) else None


@pytest.mark.skipif(not WINDOWS, reason="Windows administrative shares")
def test_exports_refuse_an_admin_share_alias_of_the_opened_folder(crafted):
    alias = _admin_share(crafted)
    if alias is None:
        pytest.skip("the administrative share \\\\localhost\\C$ is not reachable here")
    before = _state(crafted)
    part = str(crafted / "o02_boxA.SLDPRT")
    for out in (alias, alias + "\\new"):
        with pytest.raises(OutputRefusedError) as refused:
            reading.export_parasolid(part, str(crafted), out, text=True, overwrite=True)
        assert refused.value.detail == {"rule": "source_folder"}
        with pytest.raises(OutputRefusedError):
            reading.export_preview(part, str(crafted), out, overwrite=True)
    assert _state(crafted) == before and not (crafted / "new").exists()


def test_export_refusals_carry_a_rule_the_window_can_explain(crafted, tmp_path):
    part = str(crafted / "o02_boxA.SLDPRT")
    with pytest.raises(OutputRefusedError) as inside:
        reading.export_preview(part, str(crafted), str(crafted / "sub"), overwrite=False)
    reading.export_preview(part, str(crafted), str(tmp_path), overwrite=False)
    with pytest.raises(OutputRefusedError) as again:
        reading.export_preview(part, str(crafted), str(tmp_path), overwrite=False)
    for exc, rule in ((inside.value, "source_folder"), (again.value, "exists")):
        info = model.error_info(exc)
        assert info["detail"] == {"rule": rule}
        text = wording.refusal_text(info)
        assert "--" not in text and text != wording.refusal_text({})  # no command-line flags


# --------------------------------------------------------------------------- wording, no Qt
def test_short_times_never_read_as_nothing():
    assert wording.seconds_text(0.0) == wording.seconds_text(0.0049) == "under 0.01 s"
    assert wording.seconds_text(0.006) == "0.01 s" and wording.seconds_text(2.4321) == "2.43 s"


def test_counts_are_plural_english():
    assert wording.plural(1, "part") == "1 part"
    assert wording.plural(3, "assembly", "assemblies") == "3 assemblies"
    assert wording.plural(1, "property", "properties") == "1 property"
    assert wording.plural(26, "property", "properties") == "26 properties"
    assert wording.plural(1301, "entry", "entries") == "1,301 entries"


def test_codes_become_sentences_with_the_details_kept_apart():
    path = os.path.join("C:\\", "jobs", "zero.SLDDRW") if WINDOWS else "/jobs/zero.SLDDRW"
    empty = {
        "code": "unknown_format",
        "message": "The file is not a SOLIDWORKS document.",
        "reader_message": f"{path}: not a SOLIDWORKS document (first bytes <empty>)",
    }
    text = wording.error_message(empty, size=0, path=path)
    assert text.startswith("The file is empty.")
    assert "Technical details: unknown_format: zero.SLDDRW: not a SOLIDWORKS" in text
    assert path not in text and text.count("not a SOLIDWORKS document") == 1
    damaged = {
        "code": "damaged_file",
        "reader_message": "no self-consistent end-of-central-directory record found",
    }
    assert wording.error_message(damaged).startswith("The file is damaged or incomplete")
    locked = {"code": "locked", "retryable": True}
    assert wording.RETRY in wording.error_message(locked)
    entry = {"path": "a/~$part.SLDPRT", "type": "file", "status": "skipped", "reason": "lock_file"}
    assert wording.status_short(entry) == "SOLIDWORKS lock file"
    assert wording.unread_text(entry).startswith(
        "A SOLIDWORKS lock file. SOLIDWORKS keeps it while someone has part.SLDPRT open"
    )
    step = {"path": "x.SLDPRT", "type": "file", "status": "not_solidworks", "detected": "step"}
    assert wording.unread_text(step).startswith("This is a STEP file with a SOLIDWORKS extension.")
    assert wording.status_short({"path": "x", "type": "file", "status": "error", "error": damaged}) == (
        "Damaged or incomplete"
    )
    assert wording.rule_text("stored_unmoved") == "at its saved location"
    assert wording.name_source("header2_user") == "the file's list of users"
    assert wording.stream_text("_MO_VERSION_17000/Biography") == "save history"
    assert wording.stream_text("Header2") == "file header"
    assert (
        wording.refusal_text({"detail": {"rule": "unheard_of"}})
        == "A write guard refused the output location."
    )


def test_tooltip_text_is_always_escaped():
    crafted = '<img src="file://server/share/x.png">\nsecond line'
    tip = wording.tip(crafted)
    assert tip.startswith("<qt>") and tip.endswith("</qt>") and "<img" not in tip and "<br>" in tip
    assert wording.tip("") == "" and wording.tip(None) == ""


def test_a_date_property_shows_its_day():
    # SOLIDWORKS stored 3/15/2024 as 16:00 UTC; local time east of UTC+8 is the next day.
    assert reading.date_text("2024-03-15T16:00:00Z") == "2024-03-15"
    assert reading.date_text("2024-03-15T16:00:00+10:00") == "2024-03-15"
    assert reading.date_text("2024-03-15T23:30:00") == "2024-03-15"
    assert reading.date_text("not a date") == "not a date"


# --------------------------------------------------------------------------- the window, offscreen
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


class Viewer:
    def __init__(self, app) -> None:
        from solidseas_app.viewer.window import MainWindow

        self.app = app
        self.window = MainWindow()
        self.window.show()
        self.finished: list[int] = []
        self.window.detailsFinished.connect(self.finished.append)

    def open(self, folder: Path) -> dict:
        self.window.open_folder(str(folder))
        _wait(self.app, lambda: self.window.listing_info is not None)
        return self.window.listing_info

    def select(self, name: str) -> None:
        assert self.window.select_document(name), name
        generation = self.window.generation
        _wait(self.app, lambda: generation in self.finished)

    def page(self, tab: str):
        return self.window.details.pages[tab]

    def close(self) -> None:
        assert self.window.shutdown()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()


@pytest.fixture
def viewer(app):
    v = Viewer(app)
    yield v
    v.close()


@needs_qt
def test_window_is_titled_as_a_preview(viewer):
    from solidseas import __version__

    w = viewer.window
    assert w.windowTitle() == f"SolidSeas Viewer (preview {__version__})"
    tabs = [w.details.tabs.tabText(i) for i in range(w.details.tabs.count())]
    assert tabs == [
        "Overview",
        "Preview",
        "Properties",
        "Components",
        "BOM",
        "References",
        "Where Used",
        "History",
        "Paths",
        "Raw JSON",
    ]


@needs_qt
def test_o08_components_are_50_mm_apart(viewer):
    info = viewer.open(FIXTURES)
    assert len(MODEL_FIXTURES) == 8
    assert info["ok"] and info["counts"]["ok"] == len(DOCUMENTS) + len(MODEL_FIXTURES) == 27
    rows = viewer.window.model.rows
    assert sum(1 for r in rows if r.thumb is not None and not r.is_model) == len(DOCUMENTS)
    viewer.select(ASSEMBLY)
    assert viewer.page("Components").showing_content
    tree = viewer.window.details.instances
    header = [tree.headerItem().text(c) for c in range(tree.columnCount())]
    x = header.index("X (mm)")
    items = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    assert [i.text(0) for i in items] == ["o02_boxA-1", "o02_boxA-2"]
    xs = [float(i.text(x)) for i in items]
    assert abs(xs[1] - xs[0]) == pytest.approx(50)
    for tab in ("Overview", "Preview", "References", "Paths", "Raw JSON"):
        assert viewer.page(tab).showing_content, tab
    assert "No custom properties" in viewer.page("Properties").message_text
    assert json.loads(viewer.window.details.json.toPlainText())["data"]["doc_type"] == "assembly"


@needs_qt
def test_bad_files_show_their_message(viewer, crafted):
    before = _state(crafted)
    info = viewer.open(crafted)
    assert info["counts"]["ok"] == 2 and info["counts"]["error"] == 2
    viewer.select("garbage.SLDPRT")
    assert "unknown_format" in viewer.page("Overview").message_text
    viewer.select("truncated.SLDASM")
    entry = viewer.window.model.rows[viewer.window.model.find("truncated.SLDASM")].entry
    assert entry["error"]["code"] in viewer.page("Overview").message_text
    viewer.select("no_preview.SLDPRT")
    assert viewer.page("Overview").showing_content
    assert "No preview stored" in viewer.page("Preview").message_text
    assert not viewer.window.act_preview.isEnabled()
    assert _state(crafted) == before


@needs_qt
def test_a_section_the_panel_cannot_show_becomes_a_message(app):
    from solidseas_app.viewer.details import DetailsPanel

    panel = DetailsPanel()
    panel.begin({"path": "odd.SLDASM", "type": "file", "status": "ok"})
    panel.set_section("components", {"ok": True, "data": {"kind": "assembly", "components": {}}})
    assert "could not be shown" in panel.pages["Components"].message_text
    panel.set_section("paths", {"ok": False, "error": {"code": "damaged_file", "message": "damaged"}})
    assert "damaged_file" in panel.pages["Paths"].message_text
    panel.deleteLater()


@needs_qt
def test_reading_every_fixture_changes_nothing(viewer):
    before = _state(FIXTURES)
    viewer.open(FIXTURES)
    for name in DOCUMENTS:
        viewer.select(name)
        assert viewer.page("Overview").showing_content, name
        assert viewer.page("Paths").showing_content, name
    assert _state(FIXTURES) == before


@needs_qt
def test_self_test_writes_screenshots_and_a_report(app, tmp_path):
    from PySide6.QtCore import QTimer

    from solidseas_app.viewer.selftest import SelfTest
    from solidseas_app.viewer.window import MainWindow

    window = MainWindow()
    window.resize(1200, 800)
    window.show()
    st = SelfTest(window, str(FIXTURES), screenshot_dir=str(tmp_path), select=None)
    QTimer.singleShot(0, st.start)
    assert app.exec() == 0
    window.shutdown()
    window.close()
    report = json.loads((tmp_path / "selftest.json").read_text(encoding="utf-8"))
    assert report["ok"] and report["listing"]["counts"]["ok"] == len(DOCUMENTS) + len(MODEL_FIXTURES)
    assert [d["name"] for d in report["documents"]] == [ASSEMBLY]  # the first assembly
    assert len(report["screenshots"]) == 2 + 1 + 10 + 1  # listing, Settings, tabs, zoomed preview
    assert all(Path(p).stat().st_size > 0 for p in report["screenshots"])


# --------------------------------------------------------------------------- crafted documents
def _part_with_description(text: str) -> bytes:
    """o04 with its Description custom property set to ``text`` (under 255 characters)."""
    streams = fixture_streams(fixture_path("o04_boxA_props.SLDPRT"))
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    streams["docProps/custom.xml"] = streams["docProps/custom.xml"].replace(
        b"Oracle test box", escaped.encode("utf-8")
    )
    old = b"\xff\xfe\xff\x0f" + "Oracle test box".encode("utf-16-le")
    new = b"\xff\xfe\xff" + bytes([len(text)]) + text.encode("utf-16-le")
    streams["Contents/CusProps"] = streams["Contents/CusProps"].replace(old, new)
    return build_modern(streams)


def _part_with_properties(n: int) -> bytes:
    """o04 with ``n`` more text properties."""
    streams = fixture_streams(fixture_path("o04_boxA_props.SLDPRT"))
    extra = "".join(
        f'<property name="P{i}" pid="{i + 10}" IsEquation="False" TypeID="30"><vt:lpstr>v{i}</vt:lpstr>'
        "</property>"
        for i in range(n)
    )
    end = b"</propertySection></Properties>"
    streams["docProps/custom.xml"] = streams["docProps/custom.xml"].replace(end, extra.encode() + end)
    return build_modern(streams)


def _drawing() -> bytes:
    """A drawing of o02 whose view stores the model's name in lower case, as SOLIDWORKS does."""
    changes = {
        "swXmlContents/KeyWords": drawing_keywords(
            {
                "Sheet1": [
                    ("Drawing View1", "Default", "o02_boxa.sldprt"),
                    ("Drawing View2", "", "other.sldprt"),
                ]
            }
        ),
        "SheetPreviews/SheetNames": sheet_names(["Sheet1"]),
    }
    return rebuild(
        fixture_path(ASSEMBLY), changes, drop=("Contents/Definition", "swXmlContents/COMPINSTANCETREE")
    )


def _red_png(path: Path) -> None:
    from PySide6.QtGui import QColor, QImage

    img = QImage(60, 60, QImage.Format.Format_RGB32)
    img.fill(QColor(255, 0, 0))
    assert img.save(str(path), "PNG")


def _red(widget) -> int:
    """Red samples in what ``widget`` draws: the probe image, if it was loaded."""
    img = widget.grab().toImage()
    red = 0
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            c = img.pixelColor(x, y)
            red += c.red() > 200 and c.green() < 60 and c.blue() < 60
    return red


def _hover(app, tree, item, column):
    """Hover a tree cell as the mouse does; the tooltip label Qt shows, or None."""
    from PySide6.QtCore import QEvent, QPoint
    from PySide6.QtGui import QHelpEvent
    from PySide6.QtWidgets import QApplication, QToolTip

    tree.scrollToItem(item)
    app.processEvents()
    pos = QPoint(tree.header().sectionViewportPosition(column) + 5, tree.visualItemRect(item).center().y())
    QToolTip.hideText()
    app.processEvents()
    event = QHelpEvent(QEvent.Type.ToolTip, pos, tree.viewport().mapToGlobal(pos))
    QApplication.sendEvent(tree.viewport(), event)
    for _ in range(10):
        app.processEvents()
    labels = [
        w
        for w in QApplication.topLevelWidgets()
        if w.metaObject().className() == "QTipLabel" and w.isVisible()
    ]
    return labels[0] if labels else None


def _items(tree):
    from PySide6.QtWidgets import QTreeWidgetItemIterator

    it = QTreeWidgetItemIterator(tree)
    while it.value():
        yield it.value()
        it += 1


# --------------------------------------------------------------------------- the window: review findings
@needs_qt
def test_tooltips_never_load_what_a_document_names(viewer, tmp_path):
    """An ``<img>`` in a custom property or a stored path is shown as text. Qt takes a
    tooltip that looks like markup for rich text and loads the images it names; for a
    ``file://server/share`` source Windows then connects to that server."""
    from PySide6.QtWidgets import QLabel, QTreeWidget

    probe = tmp_path / "probe.png"
    _red_png(probe)
    tag = f'<img src="{probe.as_uri()}">'
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "tip.SLDPRT").write_bytes(_part_with_description(tag))
    t = TreeXml()
    t.top("m1")
    t.ref("m1", "box", 1, t.model("pm1", t.file("10", f"C:\\Parts\\{tag}\\box.sldprt")))
    (folder / "tip.SLDASM").write_bytes(assembly_with_tree(t))

    control = QLabel(tag)  # the raw text in a label: Qt loads the image
    control.adjustSize()
    assert _red(control) > 0
    control.deleteLater()

    viewer.open(folder)
    hovered = set()
    for name, tab in (
        ("tip.SLDPRT", "Properties"),
        ("tip.SLDASM", "Components"),
        ("tip.SLDASM", "References"),
        ("tip.SLDASM", "Paths"),
    ):
        viewer.select(name)
        tabs = viewer.window.details.tabs
        tabs.setCurrentIndex(tabs.indexOf(viewer.page(tab)))
        viewer.app.processEvents()
        for n, tree in enumerate(viewer.page(tab).findChildren(QTreeWidget)):
            for item in _items(tree):
                for col in range(tree.columnCount()):
                    text = item.toolTip(col)
                    if "img" not in text:
                        continue
                    assert text.startswith("<qt>") and "<img" not in text, (tab, text)
                    if tree.isVisible() and (tab, n, col) not in hovered:
                        label = _hover(viewer.app, tree, item, col)
                        assert label is not None and label.text() == text, (tab, col)
                        assert _red(label) == 0, (tab, col)
                        hovered.add((tab, n, col))
    assert {tab for tab, _, _ in hovered} == {"Properties", "Components", "References", "Paths"}


@needs_qt
def test_children_of_a_suppressed_subassembly_look_suppressed(app, tmp_path):
    from PySide6.QtGui import QPalette

    from solidseas_app.viewer.details import DetailsPanel

    t = TreeXml()
    t.file("2", "C:\\J\\sub.SLDASM", "ASSEMBLY")
    t.file("3", "C:\\J\\p.SLDPRT")
    t.top("m1")
    t.model("m2", "2")
    t.model("m3", "3")
    t.ref("m1", "sub", 1, "m2", suppressed=True)
    t.ref("m2", "p", 1, "m3")
    t.ref("m1", "p", 2, "m3")
    path = tmp_path / "top.SLDASM"
    path.write_bytes(assembly_with_tree(t))
    section = reading.read_components(str(path), str(tmp_path), None)
    assert section["ok"]
    panel = DetailsPanel()
    panel.begin({"path": "top.SLDASM", "type": "file", "status": "ok"})
    panel.set_section("components", section)
    rows = {item.text(0): item for item in _items(panel.instances)}
    assert rows["sub-1"].text(2) == "suppressed"
    assert rows["p-1"].parent() is rows["sub-1"] and rows["p-1"].text(2) == "suppressed (parent)"
    assert rows["p-2"].text(2) == ""
    grey = panel.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
    assert rows["p-1"].foreground(0).color() == grey and rows["p-2"].foreground(0).color() != grey
    files = {item.text(0): item for item in _items(panel.files)}
    assert (files["p.SLDPRT"].text(2), files["p.SLDPRT"].text(3)) == ("2", "1")  # the Files table agrees
    panel.deleteLater()


@needs_qt
def test_long_lists_are_cut_short_and_say_how_many_are_left(viewer, tmp_path, monkeypatch):
    from solidseas_app.viewer import details

    monkeypatch.setattr(details, "JSON_VIEW_CHARS", 5000)
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "many.SLDPRT").write_bytes(_part_with_properties(details.MAX_ROWS + 500))
    viewer.open(folder)
    viewer.select("many.SLDPRT")
    panel = viewer.window.details
    total = len(panel.summary["properties"])
    group = panel.properties.topLevelItem(0)
    assert group.text(0) == f"File properties ({total:,})"
    assert group.childCount() == details.MAX_ROWS + 1
    more = group.child(details.MAX_ROWS).text(0)
    assert more.startswith(f"{total - details.MAX_ROWS:,} properties more not shown")
    shown = panel.json.toPlainText()
    assert len(shown) < 5200 and shown.endswith("Edit > Copy Summary JSON copies all of it.")
    assert len(panel.summary_json) > 100_000 and json.loads(panel.summary_json)["data"]["counts"]


@needs_qt
def test_large_previews_are_decoded_small_in_the_worker(app):
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QColor, QImage

    from solidseas_app.viewer import workers

    def png(w: int, h: int) -> bytes:
        img = QImage(w, h, QImage.Format.Format_RGB32)
        img.fill(QColor(0, 0, 255))
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        return bytes(buf.data())

    big = workers.preview_image(png(4000, 1000))
    assert (big.width(), big.height()) == (workers.PREVIEW_MAX, workers.PREVIEW_MAX // 4)
    assert workers.preview_image(png(300, 200)).size().toTuple() == (300, 200)  # never enlarged
    assert workers.preview_image(b"not an image").isNull()
    small = QImage.fromData(workers.thumbnail(png(64, 48)))
    assert (small.width(), small.height()) == (workers.THUMB_WIDTH, workers.THUMB_HEIGHT)


@needs_qt
@pytest.mark.skipif(not WINDOWS, reason="byte-range locks through msvcrt")
def test_a_locked_document_is_read_again_when_selected(viewer, tmp_path):
    import msvcrt

    folder = tmp_path / "docs"
    folder.mkdir()
    for name in ("locked.SLDPRT", "free.SLDPRT"):
        shutil.copy2(fixture_path("o02_boxA.SLDPRT"), folder / name)
    size = (folder / "locked.SLDPRT").stat().st_size
    with open(folder / "locked.SLDPRT", "rb") as holder:
        msvcrt.locking(holder.fileno(), msvcrt.LK_NBLCK, size)
        try:
            viewer.open(folder)
            rows = viewer.window.model.rows
            entry = rows[viewer.window.model.find("locked.SLDPRT")].entry
            assert entry["status"] == "error" and entry["error"]["code"] == "locked"
            viewer.select("locked.SLDPRT")
            text = viewer.page("Overview").message_text
            assert "locked" in text and wording.RETRY in text
        finally:
            holder.seek(0)
            msvcrt.locking(holder.fileno(), msvcrt.LK_UNLCK, size)
    viewer.select("free.SLDPRT")
    viewer.select("locked.SLDPRT")  # the lock is gone: read now, not the listing's error again
    assert viewer.page("Overview").showing_content and viewer.page("Paths").showing_content


@needs_qt
def test_counts_read_as_english_and_lock_files_stay_out_of_the_way(viewer, crafted):
    shutil.copy2(fixture_path("o02_boxA.SLDPRT"), crafted / "~$o02_boxA.SLDPRT")
    (crafted / "sub").mkdir()
    shutil.copy2(fixture_path(ASSEMBLY), crafted / "sub" / ASSEMBLY)
    w = viewer.window
    viewer.open(crafted)
    expected = "3 documents read (1 assembly, 2 parts); 2 could not be read, 1 SOLIDWORKS lock file (hidden);"
    assert w.status_label.text().startswith(expected)
    root = w._folders[""]
    assert root.text(0) == "docs (3 of 5)" and w._folders["sub"].text(0) == "sub (1)"
    assert w.proxy.rowCount() == 5
    w.set_lock_files(True)
    assert w.proxy.rowCount() == 6 and root.text(0) == "docs (3 of 6)"
    assert "1 SOLIDWORKS lock file;" in w.status_label.text()
    header = w.table.horizontalHeader()
    assert not header.isSectionHidden(2) and not header.isSectionHidden(6)  # Status and Folder have content
    rows = {r.name: r for r in w.model.rows}
    assert rows["garbage.SLDPRT"].display[2] == "Not a SOLIDWORKS file"
    assert rows["~$o02_boxA.SLDPRT"].display[2] == "SOLIDWORKS lock file"


@needs_qt
def test_columns_fit_the_list_at_the_default_size(viewer):
    w = viewer.window
    w.resize(1440, 900)
    viewer.open(FIXTURES)
    header = w.table.horizontalHeader()

    def settled() -> bool:
        # The rows' scroll bar can come up after the listing is done, narrowing the list,
        # and the refit it starts runs a moment later: wait for both.
        viewer.app.processEvents()
        visible = [c for c in range(header.count()) if not header.isSectionHidden(c)]
        width = sum(header.sectionSize(c) for c in visible)
        return not w._fit_timer.isActive() and width <= w.table.viewport().width() + 1

    _wait(viewer.app, settled, 5)
    shown = [c for c in range(header.count()) if not header.isSectionHidden(c)]
    names = [w.model.headerData(c, header.orientation()) for c in shown]
    every = ["Name", "Type", "Saved with", "Modified", "Size"]  # no subfolder, no status to show
    if sys.platform == "win32":
        assert names == every  # Segoe UI, Windows' own font, fits them all
    else:
        assert names in (every, every[:4])  # a wider font (DejaVu Sans) may need Size to give way first
    assert sum(header.sectionSize(c) for c in shown) <= w.table.viewport().width() + 1


@needs_qt
def test_a_message_box_no_test_answers_is_closed_and_named(app, monkeypatch):
    """Offscreen nobody can click a message box: the run's watch (tests/modalguard.py)
    closes one left open past its limit and names it, so the test that opened it fails
    instead of waiting for the run's time-out."""
    from PySide6.QtWidgets import QMessageBox

    import modalguard
    from solidseas_app.viewer import window as window_module

    monkeypatch.setattr(modalguard, "LIMIT_S", 0.5)
    modalguard.watch(app)
    t0 = time.monotonic()
    window_module.show_message(None, QMessageBox.Icon.Warning, "Export STEP", "nothing to write")
    assert time.monotonic() - t0 < 10
    assert modalguard.left_open == ["Export STEP: nothing to write"]
    modalguard.left_open.clear()  # left open on purpose: this test passes


@needs_qt
def test_select_all_fails_when_a_section_fails(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QTimer

    from solidseas.formats.solidworks import SldFormatError
    from solidseas_app.viewer.selftest import SelfTest
    from solidseas_app.viewer.window import MainWindow

    def broken(_doc):
        raise SldFormatError("crafted")

    monkeypatch.setattr(reading, "_preview", broken)
    window = MainWindow()
    window.show()
    report = tmp_path / "report.json"
    st = SelfTest(
        window, str(FIXTURES), screenshot_dir=None, select=None, select_all=True, report=str(report)
    )
    QTimer.singleShot(0, st.start)
    assert app.exec() == 1
    window.shutdown()
    window.close()
    r = json.loads(report.read_text(encoding="utf-8"))
    assert not r["ok"] and r["documents"] == []  # never names in this mode
    # The model files are read in the window's worker pool, not by reading._preview.
    assert r["select_all"]["documents_read"] == len(DOCUMENTS) + len(MODEL_FIXTURES)
    assert r["select_all"]["documents_with_errors"] == len(DOCUMENTS)
    assert r["select_all"]["error_codes"]["preview:damaged_file"] == len(DOCUMENTS)


@needs_qt
def test_the_self_test_never_writes_where_it_reads(app, crafted, tmp_path):
    from solidseas_app.viewer import app as viewer_app
    from solidseas_app.viewer.selftest import outputs

    before = _state(crafted)
    part = str(crafted / "o02_boxA.SLDPRT")
    refused = [
        (None, part),  # the report onto a document
        (None, str(crafted / "report.json")),  # the report in the folder under test
        (str(crafted), None),  # screenshots into it
        (str(crafted / "shots"), None),  # or below it
        (str(tmp_path / "shots"), str(tmp_path / "report.SLDPRT")),  # a SOLIDWORKS name anywhere
    ]
    for shots, report in refused:
        with pytest.raises(OutputRefusedError):
            outputs(str(crafted), shots, report)
    old = tmp_path / "old.json"
    old.write_text("{}")
    with pytest.raises(OutputRefusedError):  # an existing report is replaced only with --force
        outputs(str(crafted), None, str(old))
    assert outputs(str(crafted), None, str(old), force=True)[1] == str(old)
    shots = tmp_path / "shots"
    assert outputs(str(crafted), str(shots), None) == (str(shots), str(shots / "selftest.json"))
    assert viewer_app.main(["--self-test", str(crafted), "--report", part]) == viewer_app.EXIT_REFUSED
    args = ["--self-test", str(crafted), "--screenshot-dir", str(crafted)]
    assert viewer_app.main(args) == viewer_app.EXIT_REFUSED
    assert _state(crafted) == before


@needs_qt
def test_a_right_click_menu_shows_its_status_tips_in_the_status_bar(app):
    from PySide6.QtGui import QStatusTipEvent
    from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QMenu

    from solidseas_app.viewer.menus import relay_status_tips

    window = QMainWindow()
    owner = QLabel("view")
    window.setCentralWidget(owner)
    bar = window.statusBar()
    plain, relayed = QMenu(owner), relay_status_tips(QMenu(owner))
    # Qt sends a hovered entry's tip to the menu at the top of its chain (a submenu's
    # too), and a popup menu is a window, where the tip stops.
    QApplication.sendEvent(plain, QStatusTipEvent("Hidden"))
    assert bar.currentMessage() == ""
    QApplication.sendEvent(relayed, QStatusTipEvent("Writes a 3MF next to the model"))
    assert bar.currentMessage() == "Writes a 3MF next to the model"
    relayed.aboutToHide.emit()
    assert bar.currentMessage() == ""
    window.deleteLater()


@needs_qt
def test_the_self_test_of_a_folder_that_is_not_there_stops_at_once(app, tmp_path):
    from solidseas_app.viewer import app as viewer_app

    started = time.perf_counter()
    args = ["--self-test", str(tmp_path / "missing"), "--report", str(tmp_path / "r.json")]
    assert viewer_app.main(args) == viewer_app.EXIT_USAGE
    plain = tmp_path / "plain.txt"
    plain.write_text("")
    args[1] = str(plain)  # a file, not a folder
    assert viewer_app.main(args) == viewer_app.EXIT_USAGE
    assert time.perf_counter() - started < 30
    assert not (tmp_path / "r.json").exists()


@needs_qt
def test_export_refusals_speak_the_windows_language(viewer, crafted, tmp_path, monkeypatch):
    from solidseas_app.viewer import window as window_module
    from solidseas_app.viewer.window import ExportDialog

    shown: list[str] = []
    monkeypatch.setattr(
        window_module, "show_message", lambda _parent, _icon, _title, text: shown.append(text)
    )
    w = viewer.window
    viewer.open(crafted)
    viewer.select("o02_boxA.SLDPRT")
    part = str(crafted / "o02_boxA.SLDPRT")
    for out in (str(crafted), str(tmp_path), str(tmp_path)):  # the opened folder, then one file twice
        try:
            result = {"ok": True, "data": reading.export_preview(part, str(crafted), out, overwrite=False)}
        except OutputRefusedError as exc:
            result = {"ok": False, "error": model.error_info(exc)}
        w._export_done("Export Preview Image", result, False, out_dir=out, path=part)
    inside, wrote, exists = shown
    assert inside.startswith("Nothing was written.") and "folder you opened" in inside
    assert wrote.startswith("Wrote the ")
    assert "Tick Overwrite existing files" in exists
    assert not any("--" in text for text in shown)
    dialog = ExportDialog(w, "Export", "", text_option=False)
    assert not dialog.export_button.isEnabled()
    dialog.folder.setText(str(tmp_path))
    assert dialog.export_button.isEnabled()
    dialog.folder.setText("   ")
    assert not dialog.export_button.isEnabled()
    dialog.deleteLater()


@needs_qt
def test_drawings_name_their_models_and_have_no_configurations(viewer, tmp_path):
    from solidseas_app.viewer import details

    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "sheet.SLDDRW").write_bytes(_drawing())
    viewer.open(folder)
    viewer.select("sheet.SLDDRW")
    panel = viewer.window.details
    sheet = panel.sheets.topLevelItem(0)
    assert [sheet.child(i).text(1) for i in range(sheet.childCount())] == ["o02_boxA.SLDPRT", "other.sldprt"]
    overview = {item.text(0): item.text(1) for item in _items(panel.overview)}
    assert overview["Active"] == "none stored (drawings have no configurations)"
    summary = json.loads(json.dumps(panel.summary))
    summary["doc_type"] = "part"
    panel._overview(summary)
    assert {item.text(0): item.text(1) for item in _items(panel.overview)}["Active"] == "none stored"
    assert details._value_text({"type": "date", "value": "2024-03-15T16:00:00Z"}) == "2024-03-15"


def _o14_with_more_links() -> bytes:
    """o14 with its text property linked to another property (``$PRP:``, which names no
    ``@``) and a new text property whose typed value is a quoted e-mail address."""
    end = b"</propertySection></Properties>"
    extra = (
        '<property name="" pid="16777219" IsEquation="False" TypeID="30">'  # TextProp's, pid 3
        "<vt:lpstr>$PRP:&quot;SW-Mass&quot;</vt:lpstr></property>"
        '<property name="Contact" pid="20" IsEquation="False" TypeID="30">'
        "<vt:lpstr>&quot;sales@example.com&quot;</vt:lpstr></property>"
    )
    o14 = fixture_path("o14_property_types.SLDPRT")
    xml = fixture_streams(o14)["docProps/custom.xml"]
    return rebuild(o14, {"docProps/custom.xml": xml.replace(end, extra.encode() + end)})


@needs_qt
def test_the_computed_column_says_what_the_library_found_linked(viewer, tmp_path):
    """Computed is the library's ``linked``: a ``$PRP:`` link to another property is
    computed though it names no ``@``, and a typed value that only looks like a link is
    not, nor are a date and a number kept as typed."""
    from solidseas_app.viewer import details

    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "props.SLDPRT").write_bytes(_o14_with_more_links())
    viewer.open(folder)
    viewer.select("props.SLDPRT")
    rows = {item.text(0): item for item in _items(viewer.window.details.properties) if item.parent()}
    computed = {name: item.text(4) for name, item in rows.items()}
    assert computed == {
        "TextProp": "yes",
        "NumberProp": "",
        "DoubleProp": "",
        "YesNoProp": "",
        "DateProp": "",
        "Mass": "yes",
        "Material": "yes",
        "Contact": "",
        "CfgProp": "",  # the configuration's own
    }
    assert rows["TextProp"].text(3) == '$PRP:"SW-Mass"'
    assert rows["Contact"].text(3) == '"sales@example.com"'
    assert details.is_computed({"expression": "3/15/2024", "linked": True})
    assert not details.is_computed({"expression": '"SW-Mass@o14_property_types.SLDPRT"', "linked": False})
    assert not details.is_computed({"expression": '"SW-Mass@o14_property_types.SLDPRT"'})


@needs_qt
def test_a_section_for_a_document_left_behind_still_releases_the_worker(viewer):
    import threading

    shown = threading.Event()
    viewer.window._section(viewer.window.generation - 1, "summary", {"ok": True, "data": {}}, shown)
    assert shown.is_set()


# --------------------------------------------------------------------------- pan, zoom and rotate, no Qt
def test_zooming_at_the_cursor_keeps_the_picture_point_under_it():
    z = viewmath.ImageZoom()
    z.resize(800, 600)
    z.set_image(640, 480)
    assert z.fitted and z.scale == pytest.approx(min(792 / 640, 592 / 480))
    x, y, w, h = z.rect()
    assert (x + w / 2, y + h / 2) == pytest.approx((400, 300))  # fitted pictures are centred
    for cursor, factor in (((300, 200), 2.0), ((610, 455), 1.25), ((420, 330), 0.5), ((400, 300), 7.0)):
        before = z.to_image(*cursor)
        z.zoom(factor, cursor)
        assert z.to_image(*cursor) == pytest.approx(before), (cursor, factor)
    assert not z.fitted
    before = z.to_image(500, 300)
    z.pan(-35, 12)
    assert z.to_image(500, 300) == pytest.approx((before[0] + 35 / z.scale, before[1] - 12 / z.scale))
    z.zoom(1e9)
    assert z.scale == z.MAX_SCALE
    z.zoom(1e-9)
    assert z.scale == z.MIN_SCALE
    z.zoom_to(3.0)
    z.pan(-1e7, -1e7)  # flung away: a strip of the picture stays in view
    x, y, w, h = z.rect()
    assert x + w >= z.KEEP - 1e-9 and y + h >= z.KEEP - 1e-9
    z.pan(1e7, 1e7)
    x, y, w, h = z.rect()
    assert x <= z.view_w - z.KEEP and y <= z.view_h - z.KEEP
    z.fit()
    assert z.fitted
    z.resize(400, 300)  # a fitted picture refits when the view changes size
    assert z.scale == pytest.approx(min(392 / 640, 292 / 480))
    z.actual_size()
    assert z.scale == 1.0
    z.set_image(10, 10)
    assert z.scale == z.FIT_MAX  # fitting enlarges a small picture at most twice


def test_mouse_styles_map_buttons_as_their_programs_do():
    std, sw = viewmath.STANDARD, viewmath.SOLIDWORKS
    rotate, pan, zoom = viewmath.ROTATE, viewmath.PAN, viewmath.ZOOM
    assert viewmath.drag_action(std, "left") == rotate
    assert viewmath.drag_action(std, "right") == pan
    assert viewmath.drag_action(std, "middle") == pan
    assert viewmath.drag_action(std, "left", ctrl=True) == rotate
    assert viewmath.drag_action(sw, "middle") == rotate
    assert viewmath.drag_action(sw, "middle", ctrl=True) == pan
    assert viewmath.drag_action(sw, "middle", shift=True) == zoom
    assert viewmath.drag_action(sw, "left") is None and viewmath.drag_action(sw, "right") is None
    assert viewmath.ndc(0, 0, 400, 300) == (-1.0, 1.0) and viewmath.ndc(200, 150, 400, 300) == (0.0, 0.0)


def test_each_mouse_style_zooms_with_the_wheel_the_way_its_program_does():
    """A positive step is the wheel rolled away from you. Standard zooms in, as most
    programs do; SOLIDWORKS zooms out, as SOLIDWORKS does out of the box, and
    toward you zooms in. Reversing flips either, like SOLIDWORKS's own option."""
    std, sw, wf = viewmath.STANDARD, viewmath.SOLIDWORKS, viewmath.wheel_factor
    assert wf(1) == wf(1, style=std) == viewmath.WHEEL_STEP and wf(-1, style=std) == 1 / viewmath.WHEEL_STEP
    assert wf(1, style=sw) == 1 / viewmath.WHEEL_STEP and wf(-1, style=sw) == viewmath.WHEEL_STEP
    assert wf(1, style=std, invert=True) == pytest.approx(wf(1, style=sw))
    assert wf(1, style=sw, invert=True) == pytest.approx(wf(1, style=std))
    assert wf(2, style=sw) == pytest.approx(wf(1, style=sw) ** 2)
    assert viewmath.wheel_text(std) == "roll the wheel away from you to zoom in"
    assert viewmath.wheel_text(sw) == "roll the wheel toward you to zoom in"
    assert viewmath.wheel_text(sw, invert=True) == viewmath.wheel_text(std)
    assert (
        "toward you zooms in" in viewmath.MOUSE_STYLES[sw] and "away from you" in viewmath.MOUSE_STYLES[std]
    )


def _o11_box():
    return ((0.0, 0.0, 0.0), (0.04, 0.03, 0.01))  # the size of fixture o11, in metres


def test_the_camera_starts_isometric_and_fits_the_bounding_box():
    cam = viewmath.OrbitCamera(_o11_box())
    cam.aspect = 1.5
    cam.reset()
    s = 1 / 3**0.5
    assert cam.back == pytest.approx((s, s, s))  # looking down the (1, 1, 1) diagonal, as SOLIDWORKS does
    assert cam.up[1] > 0.8 and abs(cam.right[1]) < 1e-12  # Y is up, the screen's x axis stays level
    assert viewmath._dot(cam.right, cam.up) == pytest.approx(0, abs=1e-12)
    points = [cam.project(c) for c in viewmath.corners(_o11_box())]
    assert max(max(abs(p[0]), abs(p[1])) for p in points) == pytest.approx(1 / 1.15)
    assert all(-1 <= p[2] <= 1 for p in points)  # inside the depth range too
    assert cam.project(cam.center)[:2] == pytest.approx((0, 0))
    for aspect in (0.3, 1.0, 4.0):  # tall and wide views fit as well
        cam.aspect = aspect
        cam.fit()
        assert max(max(abs(p[0]), abs(p[1])) for p in map(cam.project, viewmath.corners(_o11_box()))) <= 1


def test_the_camera_orbits_pans_and_zooms_toward_the_cursor():
    width, height = 900, 600
    cam = viewmath.OrbitCamera(_o11_box(), mode=viewmath.TURNTABLE)
    cam.aspect = width / height
    cam.reset()
    cam.rotate(100, 0)  # drag right: the front turns right
    assert cam.yaw == pytest.approx(viewmath.ISO_YAW - 100 * viewmath.DEGREES_PER_PIXEL)
    cam.rotate(0, 10_000)
    assert cam.pitch == viewmath.PITCH_LIMIT  # tilting stops short of looking straight down
    cam.reset()
    point = (0.03, 0.01, 0.005)
    before = cam.project(point)
    cam.pan(30, -20, height)  # right and up by a few pixels: the model follows the cursor exactly
    after = cam.project(point)
    assert after[0] - before[0] == pytest.approx(2 * 30 / width)
    assert after[1] - before[1] == pytest.approx(2 * 20 / height)
    at = (0.5, -0.3)
    on_plane = cam.point_at(*at)
    half = cam.half_height
    cam.zoom(2.0, at)
    assert cam.half_height == pytest.approx(half / 2)
    assert cam.project(on_plane)[:2] == pytest.approx(at)
    corner = (0.04, 0.0, 0.01)  # off that plane: orthographic, so it stays put as well
    where = cam.project(corner)[:2]
    cam.zoom(1.7, where)
    assert cam.project(corner)[:2] == pytest.approx(where)
    cam.zoom(1e-12)
    assert cam.half_height == pytest.approx(cam.radius * cam.ZOOM_OUT_LIMIT)
    cam.zoom(1e12)
    assert cam.half_height == cam.MIN_HALF


def _x_extent(cam) -> float:
    """How far across the view the model reaches: 1 touches the sides."""
    return max(abs(cam.project(c)[0]) for c in viewmath.corners(cam.bbox))


def test_a_fitted_camera_refits_when_the_view_changes_shape():
    long_box = ((0.0, 0.0, 0.0), (0.2, 0.01, 0.01))  # 200 x 10 x 10 mm, much wider than high
    cam = viewmath.OrbitCamera(long_box)
    cam.aspect = 640 / 480  # a new view's size, before it is laid out
    cam.reset()
    assert cam.fitted and _x_extent(cam) == pytest.approx(1 / 1.15)
    cam.aspect = 392 / 636  # what the old code did on a resize: the ends were cut off
    assert _x_extent(cam) > 1.5
    cam.aspect = 640 / 480
    cam.set_aspect(392 / 636)  # the panel's real shape arrives: fitted, so it refits
    assert _x_extent(cam) == pytest.approx(1 / 1.15)
    cam.rotate(20, 0)  # the user moved it: the zoom is theirs now
    assert not cam.fitted
    half = cam.half_height
    cam.set_aspect(1.5)
    assert cam.half_height == half
    cam.fit()
    cam.pan(5, 5, 600)
    assert not cam.fitted
    cam.fit()
    cam.zoom(1.5)
    assert not cam.fitted


def test_the_camera_gives_the_standard_views_as_solidworks_does():
    cam = viewmath.OrbitCamera(_o11_box(), mode=viewmath.TURNTABLE)
    cam.aspect = 1.0
    expected = {  # the direction toward the eye, the screen's right and up, in model axes
        "front": ((0, 0, 1), (1, 0, 0), (0, 1, 0)),
        "back": ((0, 0, -1), (-1, 0, 0), (0, 1, 0)),
        "left": ((-1, 0, 0), (0, 0, 1), (0, 1, 0)),
        "right": ((1, 0, 0), (0, 0, -1), (0, 1, 0)),
        "top": ((0, 1, 0), (1, 0, 0), (0, 0, -1)),
        "bottom": ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
    }
    for name, (back, right, up) in expected.items():
        cam.rotate(33, 17)
        cam.set_view(name)
        assert cam.fitted, name
        assert cam.back == pytest.approx(back, abs=1e-12), name
        assert cam.right == pytest.approx(right, abs=1e-12), name
        assert cam.up == pytest.approx(up, abs=1e-12), name
        assert max(max(abs(p[0]), abs(p[1])) for p in map(cam.project, viewmath.corners(cam.bbox))) <= 1
    cam.set_view("isometric")
    s = 1 / 3**0.5
    assert cam.back == pytest.approx((s, s, s))
    assert set(viewmath.VIEW_KEYS.values()) == set(viewmath.VIEWS)  # Ctrl+1 to Ctrl+7 reach every one
    cam.turn(0, 500)  # the turntable stops at straight down, where the screen axes stay defined
    assert cam.pitch == 90 and cam.up == pytest.approx((cam.right[2], 0, -cam.right[0]), abs=1e-12)


def test_the_3d_view_reads_a_parts_display_mesh_and_nothing_else(crafted, tmp_path):
    before = _state(FIXTURES)
    part = str(fixture_path("o02_boxA.SLDPRT"))
    result = mesh3d.read_part_mesh(part, str(FIXTURES), 1_000_000)
    assert result["state"] == "ok"
    data = result["data"]
    assert (data.n_triangles, data.n_vertices) == (12, 24)  # the box SOLIDWORKS drew: 6 faces of 2
    assert [*data.bbox[0], *data.bbox[1]] == pytest.approx([0, 0, 0, 0.01, 0.02, 0.03])  # 10 x 20 x 30 mm
    assert len(data.positions) == len(data.normals) == 24 * 12 and len(data.indices) == 12 * 12
    assert set(result["seconds"]) == {"open", "read", "build"}
    assert mesh3d.read_part_mesh(part, str(FIXTURES), 11) | {"seconds": None} == {
        "state": "too_large",
        "triangles": 12,
        "cap": 11,
        "seconds": None,
    }
    assert mesh3d.read_part_mesh(part, str(FIXTURES), 1000, lambda: True)["state"] == "cancelled"
    empty = str(fixture_path("o01_empty.SLDPRT"))
    assert mesh3d.read_part_mesh(empty, str(FIXTURES), 1000)["state"] == "no_mesh"
    assembly = str(fixture_path(ASSEMBLY))
    assert mesh3d.read_part_mesh(assembly, str(FIXTURES), 1000)["state"] == "not_part"
    assert _state(FIXTURES) == before
    # Saved without a display mesh, the part is drawn from its own bodies: the same box.
    no_display = tmp_path / "no_display.SLDPRT"
    no_display.write_bytes(rebuild(fixture_path("o02_boxA.SLDPRT"), drop=("Contents/DisplayLists",)))
    brep = mesh3d.read_part_mesh(str(no_display), str(tmp_path), 1000)
    assert brep["state"] == "ok" and brep["stored_in"] == "bodies"
    assert brep["data"].n_triangles == 12
    assert [*brep["data"].bbox[0], *brep["data"].bbox[1]] == pytest.approx([0, 0, 0, 0.01, 0.02, 0.03])
    assert set(brep["seconds"]) == {"open", "read", "tessellate", "build"}
    assert mesh3d.read_part_mesh(str(no_display), str(tmp_path), 11) | {"seconds": None} == {
        "state": "too_large",
        "triangles": 12,
        "from_bodies": True,
        "cap": 11,
        "seconds": None,
    }
    # With neither a display mesh nor bodies there is nothing to draw.
    bare = tmp_path / "bare.SLDPRT"
    streams = fixture_streams(fixture_path("o02_boxA.SLDPRT"))
    bare.write_bytes(
        rebuild(
            fixture_path("o02_boxA.SLDPRT"),
            drop=("Contents/DisplayLists", *(n for n in streams if n.endswith("-Partition"))),
        )
    )
    assert mesh3d.read_part_mesh(str(bare), str(tmp_path), 1000)["state"] == "no_mesh"
    garbage = mesh3d.read_part_mesh(str(crafted / "garbage.SLDPRT"), str(crafted), 1000)
    assert garbage["state"] == "error" and garbage["error"]["code"] == "unknown_format"


def test_a_display_list_over_the_byte_budget_is_refused_without_reading_it(monkeypatch):
    """Reading costs time and memory by the stream's size, not by its triangles, and
    cannot stop partway: the size is checked first, from the container's directory."""
    from solidseas import open_document

    assert mesh3d.byte_budget(mesh3d.DEFAULT_TRIANGLE_CAP) == 256_000_000
    assert mesh3d.byte_budget(mesh3d.MIN_TRIANGLE_CAP) == 64 << 20
    assert mesh3d.byte_budget(mesh3d.MAX_TRIANGLE_CAP) == 1 << 30  # what the library reads at most
    part = fixture_path("o02_boxA.SLDPRT")
    with open_document(part) as doc:
        size = mesh3d.display_list_bytes(doc)
    assert size and size < 64 << 20
    monkeypatch.setattr(mesh3d, "MIN_BYTE_BUDGET", size - 1)
    monkeypatch.setattr(mesh3d, "BUDGET_BYTES_PER_TRIANGLE", 0)
    result = mesh3d.read_part_mesh(str(part), str(FIXTURES), 1_000_000)
    assert result["state"] == "too_large" and result["bytes"] == size and result["budget"] == size - 1
    assert "read" not in result["seconds"]  # refused before Document.mesh()
    monkeypatch.setattr(mesh3d, "MIN_BYTE_BUDGET", size)
    assert mesh3d.read_part_mesh(str(part), str(FIXTURES), 1_000_000)["state"] == "ok"


# --------------------------------------------------------------------------- settings
@needs_qt
def test_settings_round_trip_through_their_file(tmp_path):
    from solidseas_app.viewer.settings import Session, Settings, SettingsStore

    path = tmp_path / "SolidSeas" / "Viewer.ini"
    store = SettingsStore(str(path))
    assert store.load() == Settings() and not path.exists()  # reading writes nothing
    assert Settings().view_3d is False and Settings().mouse_style == "standard"  # the defaults asked for
    changed = Settings(
        view_3d=True,
        mouse_style="solidworks",
        invert_wheel=True,
        triangle_cap=250_000,
        thumbnail_size="large",
        list_view="icons",
        show_lock_files=True,
        remember_session=False,
    )
    assert store.save(changed)
    assert SettingsStore(str(path)).load() == changed and not store.reset_keys
    folder = str(tmp_path / "Prüfung 中")
    assert store.save_session(Session(folder=folder, geometry=b"\x00\x01g", splitter=b"s"))
    assert SettingsStore(str(path)).load_session() == Session(folder, b"\x00\x01g", b"s")
    text = path.read_text(encoding="utf-8")
    assert "geometry=AAFn" in text and "@" not in text  # every value is text: base64 for the two states
    assert f"folder={json.dumps(folder, ensure_ascii=False)}" in text and "view_3d=true" in text
    assert store.save_session(None)
    assert SettingsStore(str(path)).load_session() == Session()
    assert SettingsStore(str(path)).load() == changed  # forgetting the session keeps the rest
    memory = SettingsStore(None)
    assert memory.save(changed) and memory.load() == changed and memory.path is None


@needs_qt
@pytest.mark.parametrize(
    ("content", "expected", "reset"),
    [
        (bytes(range(256)) * 8, {}, None),
        (b"[Preferences\nview_3d=true\n=====\n[[[\nmouse_style=solidworks\n", {}, None),
        (
            b"[Preferences]\nview_3d=perhaps\nmouse_style=trackball\ntriangle_cap=-5\nthumbnail_size=huge\n"
            b"list_view=\nshow_lock_files=2\nremember_session=@ByteArray(x)\ninvert_wheel=1,2\n",
            {},
            {
                "view_3d",
                "mouse_style",
                "triangle_cap",
                "thumbnail_size",
                "list_view",
                "show_lock_files",
                "remember_session",
                "invert_wheel",
            },
        ),
        (b"[Preferences]\ntriangle_cap=99999999999999999999999\n", {}, {"triangle_cap"}),
        (
            b"[Preferences]\nview_3d=TRUE\nmouse_style=SolidWorks\ntriangle_cap=1,500,000\n",
            {"view_3d": True, "mouse_style": "solidworks", "triangle_cap": 1_500_000},
            set(),
        ),
        ("[Preferences]\nview_3d=true\n".encode("utf-16"), {}, None),
        (b"", {}, set()),
    ],
)
def test_a_damaged_or_hand_edited_settings_file_gives_defaults(tmp_path, content, expected, reset):
    from solidseas_app.viewer.settings import Session, Settings, SettingsStore

    path = tmp_path / "Viewer.ini"
    path.write_bytes(content + b"\n[Session]\ngeometry=hello\nsplitter=@ByteArray()\nfolder=\n")
    store = SettingsStore(str(path))
    assert store.load() == Settings().but(**expected)
    if reset is not None:
        assert set(store.reset_keys) == reset
    assert store.load_session() == Session()
    assert store.save(Settings(view_3d=True))  # the next save writes a whole, valid file
    assert SettingsStore(str(path)).load() == Settings(view_3d=True)


# QSettings decodes "@Variant(...)" with QDataStream: a QStringList (type 11) or a
# QVariantList (type 9) with a forged element count made Qt reserve that many elements
# before reading any, which committed 49 GB or aborted the process inside load().
# Escaped ("\x40") or inside a list, Qt decoded it all the same.
_FORGED = [
    rb"@Variant(\0\0\0\xb\x7f\xff\xff\xff)",
    rb"@Variant(\0\0\0\t\x7f\xff\xff\xfd)",
    rb"@DateTime(\0\0\0\xb\x7f\xff\xff\xff)",
    rb"\x40Variant(\0\0\0\xb\x7f\xff\xff\xff)",
    rb"a, @Variant(\0\0\0\xb\x7f\xff\xff\xff)",
]


@needs_qt
@pytest.mark.parametrize("value", _FORGED)
def test_a_forged_qt_variant_in_the_settings_file_is_only_text(tmp_path, value):
    from solidseas_app.viewer.settings import Settings, SettingsStore

    path = tmp_path / "Viewer.ini"
    path.write_bytes(
        b"[Preferences]\nview_3d=" + value + b"\nlist_view=icons\n[Session]\nfolder=" + value + b"\n"
        b"geometry=" + value + b"\nsplitter=" + value + b"\n"
    )
    store = SettingsStore(str(path))
    assert store.load() == Settings(list_view="icons") and store.reset_keys == ["view_3d"]
    session = store.load_session()
    assert session.geometry is None and session.splitter is None
    assert session.folder in (None, os.path.normpath(value.decode()))  # a path that is not there, at most


_LOAD_SETTINGS = """
import ctypes, json, os, sys
from solidseas_app.viewer.settings import SettingsStore
store = SettingsStore(sys.argv[1])
settings, session = store.load(), store.load_session()
peak = None
if os.name == "nt":
    from ctypes import wintypes
    names = ("peak_ws", "ws", "peak_paged", "paged", "peak_np", "np", "commit", "peak")
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)]
        _fields_ += [(n, ctypes.c_size_t) for n in names]
    k32 = ctypes.WinDLL("kernel32")
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.K32GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD)
    c = Counters()
    c.cb = ctypes.sizeof(c)
    k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb)
    peak = c.peak
out = {"view_3d": settings.view_3d, "reset": store.reset_keys, "folder": session.folder, "peak": peak}
print(json.dumps(out))
"""


@needs_qt
def test_loading_a_forged_settings_file_costs_no_memory(tmp_path):
    """The forged value from review, in a fresh process: it used to commit 49 GB or
    abort before the viewer's window could open. Its peak commit is measured."""
    path = tmp_path / "Viewer.ini"
    path.write_bytes(b"[Preferences]\nview_3d=" + _FORGED[0] + b"\n[Session]\nfolder=" + _FORGED[1] + b"\n")
    env = dict(os.environ, PYTHONPATH=_SRC)
    proc = subprocess.run(
        [sys.executable, "-c", _LOAD_SETTINGS, str(path)], env=env, capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["view_3d"] is False and out["reset"] == ["view_3d"] and out["folder"] is None
    if out["peak"] is not None:
        assert out["peak"] < 300 << 20, out["peak"]  # Python and QtCore: tens of megabytes


@needs_qt
@pytest.mark.skipif(not WINDOWS, reason="the roaming application-data folder is a Windows idea")
def test_settings_live_in_the_roaming_app_data_folder(monkeypatch, tmp_path):
    from solidseas_app.viewer.settings import default_path

    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert default_path() == str(tmp_path / "Roaming" / "SolidSeas" / "Viewer.ini")


@needs_qt
def test_the_settings_menu_toggles_apply_at_once_and_are_saved(app, tmp_path):
    from solidseas_app.viewer.settings import Session, Settings, SettingsStore
    from solidseas_app.viewer.window import MainWindow

    path = tmp_path / "Viewer.ini"
    w = MainWindow(SettingsStore(str(path)))
    w.show()
    try:
        menus = [a.text() for a in w.menuBar().actions()]
        assert menus == ["&File", "&Edit", "&View", "&Tools", "P&DM", "&Settings", "&Help"]
        assert w.act_preferences.shortcut().toString() == "Ctrl+,"
        assert w.act_preferences in w.settings_menu.actions()
        pane = w.details.preview
        assert not w.act_3d.isChecked() and pane.model_button.isHidden()
        w.act_3d.trigger()
        assert w.settings.view_3d and pane.enabled_3d and not pane.model_button.isHidden()
        w.act_mouse["solidworks"].trigger()
        assert w.settings.mouse_style == "solidworks" and pane.mouse_style == "solidworks"
        w.act_invert_wheel.trigger()
        assert w.settings.invert_wheel and pane.image.invert_wheel
        w.act_lock_files.trigger()
        assert w.settings.show_lock_files and w.proxy.lock_files
        assert SettingsStore(str(path)).load() == w.settings  # each toggle was saved
        w.store.save_session(Session(folder=str(tmp_path)))
        w.act_remember.trigger()  # off: the remembered folder and layout are forgotten at once
        assert not w.settings.remember_session
        assert SettingsStore(str(path)).load_session() == Session()
        w.set_lock_files(False)  # the View menu's entry is the same setting
        assert not w.act_lock_files.isChecked() and not SettingsStore(str(path)).load().show_lock_files
        w.act_3d.trigger()
        assert pane.model_button.isHidden() and pane.mode == "image"
        assert SettingsStore(str(path)).load() == Settings(
            mouse_style="solidworks", invert_wheel=True, remember_session=False
        )
    finally:
        w.shutdown()
        w.close()


@needs_qt
def test_preferences_edit_a_copy_and_restore_defaults(app, tmp_path):
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QDialogButtonBox

    from solidseas_app.viewer.preferences import VIEW_3D_NOTE, PreferencesDialog
    from solidseas_app.viewer.settings import Settings, SettingsStore
    from solidseas_app.viewer.window import MainWindow

    path = tmp_path / "Viewer.ini"
    w = MainWindow(SettingsStore(str(path)))
    dialog = PreferencesDialog(w, w.settings, w.store.path)
    try:
        assert dialog.values() == Settings() and not dialog.cap.isEnabled()
        # The note gives the cost as measured: the window held while OpenGL starts, which the
        # launcher does before the window appears (PreviewPane.prepare_view), not at the
        # first part, then reads in a separate process that leave the window responding.
        assert "holds the whole window for about 0.6 seconds" in VIEW_3D_NOTE
        assert "when you turn this on, and when the viewer starts with it on" in VIEW_3D_NOTE
        assert "separate process" in VIEW_3D_NOTE
        assert dialog.invert_wheel.text() == "Reverse the wheel's zoom direction"
        assert "toward you zooms in" in dialog.solidworks.text() and "away from you" in dialog.standard.text()
        dialog.view_3d.setChecked(True)
        dialog.cap.setValue(500_000)
        dialog.solidworks.setChecked(True)
        dialog.thumbnail_size.setCurrentIndex(dialog.thumbnail_size.findData("large"))
        dialog.list_view.setCurrentIndex(dialog.list_view.findData("icons"))
        assert w.settings == Settings()  # nothing happens before Apply or OK
        dialog.applied.connect(w.apply_settings)
        dialog.buttons.button(QDialogButtonBox.StandardButton.Apply).click()
        assert w.settings == Settings(
            view_3d=True,
            triangle_cap=500_000,
            mouse_style="solidworks",
            thumbnail_size="large",
            list_view="icons",
        )
        assert w.icons.iconSize() == QSize(192, 144) and w.act_icons_view.isChecked()
        assert w.model.thumb_size == (192, 144)
        assert SettingsStore(str(path)).load() == w.settings
        dialog.buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).click()
        assert dialog.values() == Settings()
        assert w.settings.view_3d  # restoring defaults in the dialog is not applied by itself
    finally:
        dialog.deleteLater()
        w.shutdown()
        w.close()


@needs_qt
def test_a_damaged_settings_file_never_stops_the_window(app, tmp_path):
    from solidseas_app.viewer.settings import Settings, SettingsStore
    from solidseas_app.viewer.window import MainWindow

    path = tmp_path / "Viewer.ini"
    path.write_bytes(
        b"[Preferences]\nview_3d=perhaps\ntriangle_cap=lots\n\x00\xff[[\n[Session]\ngeometry=xx\n"
    )
    w = MainWindow(SettingsStore(str(path)))
    try:
        assert w.settings == Settings()
        assert "back to their defaults" in w.statusBar().currentMessage()
        assert w.restore_session() is None
    finally:
        w.shutdown()
        w.close()


@needs_qt
def test_the_window_layout_and_folder_are_remembered(app, tmp_path):
    from solidseas_app.viewer.settings import SettingsStore
    from solidseas_app.viewer.window import MainWindow

    path = tmp_path / "Viewer.ini"
    first = MainWindow(SettingsStore(str(path)))
    first.resize(760, 540)  # inside the offscreen platform's 800 x 800 screen
    first.show()
    first.open_folder(str(FIXTURES))
    _wait(app, lambda: first.listing_info is not None)
    first.split.setSizes([100, 400, 500])
    sizes = first.split.sizes()
    first.close()  # saves the session
    second = MainWindow(SettingsStore(str(path)))
    try:
        assert second.restore_session() == str(FIXTURES)
        second.show()
        app.processEvents()
        assert second.split.sizes() == sizes
        assert (second.width(), second.height()) == (760, 540)
        second.reopen(str(tmp_path / "gone"))  # a folder that is no longer there: nothing opens
        second.reopen(str(FIXTURES))
        _wait(app, lambda: second.listing_info is not None)
        assert second.folder == str(FIXTURES)
    finally:
        second.shutdown()
        second.close()


@needs_qt
def test_a_forged_splitter_state_never_reaches_qt(app, tmp_path):
    import struct

    from solidseas_app.viewer.settings import Session, SettingsStore
    from solidseas_app.viewer.window import MainWindow, splitter_state_ok

    w = MainWindow()
    try:
        real = bytes(w.split.saveState().data())
        assert splitter_state_ok(real)
        forged = struct.pack(">iiI", 0xFF, 1, 0x7FFFFFFF) + b"\0" * 64  # "two billion sizes follow"
        assert (
            not splitter_state_ok(forged) and not splitter_state_ok(b"") and not splitter_state_ok(real[:11])
        )
        store = SettingsStore(str(tmp_path / "Viewer.ini"))
        store.save_session(Session(splitter=forged))
        w.store = store
        restored = []
        w.split.restoreState = lambda state: restored.append(state) or True
        w.restore_session()
        assert restored == [] and not w._session_restored
    finally:
        w.shutdown()
        w.close()


@needs_qt
def test_a_remembered_folder_on_a_dead_server_holds_up_no_other_folder(app, monkeypatch):
    """Asking a server that has gone away whether the remembered folder is there takes
    the network's time-out. A folder opened meanwhile lists at once, and the late
    answer is ignored."""
    import threading

    from solidseas_app.viewer import window as window_module
    from solidseas_app.viewer.window import MainWindow

    gone = r"\\gone.invalid\share\parts"  # a reserved name: never a real server
    release = threading.Event()
    real = window_module.folder_exists

    def slow(path):
        if path == gone:
            release.wait(30)
            return True  # it came back, too late
        return real(path)

    monkeypatch.setattr(window_module, "folder_exists", slow)
    w = MainWindow()
    try:
        w.show()
        w.reopen(gone)
        t = time.monotonic()
        w.open_folder(str(FIXTURES))
        _wait(app, lambda: w.listing_info is not None, 20)
        assert time.monotonic() - t < 10 and not release.is_set()  # listed while the check still waits
        release.set()
        _wait(app, lambda: w.check_pool.activeThreadCount() == 0, 10)
        app.processEvents()
        assert w.folder == str(FIXTURES)
    finally:
        release.set()
        assert w.shutdown()
        w.close()


@needs_qt
@pytest.mark.parametrize("remember", [False, True])
def test_the_folder_dialogs_record_is_put_back_unless_folders_are_remembered(
    app, tmp_path, monkeypatch, remember
):
    """Qt's folder dialog writes the folder it showed to a store every Qt program shares
    (the registry on Windows) when it closes. With Remember Last Folder off, the
    viewer puts that record back as it was. Here the store is redirected to a file."""
    import shiboken6
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QFileDialog

    from solidseas_app.viewer import window as window_module
    from solidseas_app.viewer.settings import Settings
    from solidseas_app.viewer.window import MainWindow

    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "qt"))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    try:
        before = QSettings(QSettings.Scope.UserScope, "QtProject")
        before.setValue("FileDialog/lastVisited", "file:///somewhere-else")
        before.sync()
        chosen = tmp_path / "chosen"
        chosen.mkdir()

        class Dialog:
            @staticmethod
            def getExistingDirectory(parent, title, start):
                d = QFileDialog(None, title, str(chosen))
                shiboken6.delete(d)  # Qt records the folder the dialog showed as it goes
                return str(chosen)

        monkeypatch.setattr(window_module, "QFileDialog", Dialog)
        w = MainWindow()
        w.settings = Settings(remember_session=remember)
        opened = []
        w.open_folder = lambda folder, select=None: opened.append(folder)
        try:
            w.choose_folder()
        finally:
            w.shutdown()
            w.close()
        assert opened == [str(chosen)]
        after = QSettings(QSettings.Scope.UserScope, "QtProject").value("FileDialog/lastVisited")
        if remember:
            assert after != "file:///somewhere-else" and "chosen" in str(after)
        else:
            assert after == "file:///somewhere-else"
    finally:
        QSettings.setDefaultFormat(QSettings.Format.NativeFormat)


# --------------------------------------------------------------------------- the Preview tab
@needs_qt
def test_the_preview_image_pans_and_zooms_without_decoding_again(viewer):
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent, QWheelEvent
    from PySide6.QtWidgets import QApplication

    from solidseas_app.viewer.details import TABS

    w = viewer.window
    w.resize(1400, 900)
    viewer.open(FIXTURES)
    viewer.select("o02_boxA.SLDPRT")
    w.details.tabs.setCurrentIndex(TABS.index("Preview"))
    viewer.app.processEvents()
    pane = w.details.preview
    view = pane.image
    pix = view.pixmap
    assert pix is not None and pane.zoom_label.text().endswith("%")
    assert pane.model_button.isHidden()  # the 3D setting is off by default
    fitted = view.zoom.scale
    cursor = QPointF(view.width() * 0.4, view.height() * 0.45)
    under = view.zoom.to_image(cursor.x(), cursor.y())
    wheel = QWheelEvent(
        cursor,
        view.mapToGlobal(cursor),
        QPoint(),
        QPoint(0, 240),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(view, wheel)
    assert view.zoom.scale == pytest.approx(fitted * viewmath.WHEEL_STEP**2)
    assert view.zoom.to_image(cursor.x(), cursor.y()) == pytest.approx(under)
    assert pane.zoom_label.text() == f"{view.percent:.0f}%"

    def drag(button, start, end):
        for kind, pos, b, held in (
            (QEvent.Type.MouseButtonPress, start, button, button),
            (QEvent.Type.MouseMove, end, Qt.MouseButton.NoButton, button),
            (QEvent.Type.MouseButtonRelease, end, button, Qt.MouseButton.NoButton),
        ):
            QApplication.sendEvent(
                view, QMouseEvent(kind, QPointF(*pos), QPointF(*pos), b, held, Qt.KeyboardModifier.NoModifier)
            )

    for button in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
        x0 = view.zoom.x
        drag(button, (200, 200), (230, 210))
        assert view.zoom.x == pytest.approx(x0 + 30)
    view.grab()  # draws at this zoom
    pane.zoom_out.click()
    view.grab()
    QApplication.sendEvent(
        view,
        QMouseEvent(
            QEvent.Type.MouseButtonDblClick,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert view.zoom.fitted and view.zoom.scale == pytest.approx(fitted)
    pane.actual_button.click()
    assert view.percent == pytest.approx(100)
    pane.fit_button.click()
    assert view.zoom.fitted
    assert view.pixmap is pix  # every frame drew the image decoded once, in the worker


def _stub_view_factory(made: list):
    from PySide6.QtCore import QPoint, Signal
    from PySide6.QtWidgets import QWidget

    class StubView(QWidget):
        """Stands in for the OpenGL view, which Qt's offscreen platform cannot make. Tests
        emit its ``picked``, ``activated`` and ``menuRequested`` as the real view does
        for a click, a double-click and a right-click on an instance."""

        failed = Signal(str)
        picked = Signal(int)
        activated = Signal(int)
        menuRequested = Signal(int, QPoint)
        hideRequested = Signal(int)
        showAllRequested = Signal()

        def __init__(self) -> None:
            super().__init__()
            self.mesh = None
            self.assembly = None
            self.boxes = True  # whether the assembly is drawn with its boxes
            self.error = None
            self.mouse_style = "standard"
            self.invert_wheel = False
            self.explode_level = "top"
            self.explode = 0.0
            self.explode_calls: list[tuple[float, bool | str]] = []  # (amount, animate or "follow")
            self.selected: set[int] = set()
            self.describe = None
            self.any_hidden = None
            self.cam = self.FITTED
            self.camera_calls: list[dict] = []
            self.keep_calls: list[bool] = []  # keep_camera, for each scene shown
            self.opacity: list[float] = []  # each instance's, as the pane asked
            self.hidden: list[bool] = []
            self.looks_calls = 0
            self.explode_choices: dict[str, bool] = {}

        FITTED = {"yaw": 45.0, "pitch": 35.26, "target": [0.0, 0.0, 0.0], "half_height": 1.0, "fitted": True}

        def set_mesh(self, mesh, *, keep_camera: bool = False) -> None:
            self.mesh, self.assembly = mesh, None
            self.explode = 0.0
            self.selected = set()
            self._shown(mesh, keep_camera)

        def set_assembly(self, scene, *, boxes: bool = True, keep_camera: bool = False) -> None:
            self.mesh, self.assembly, self.boxes = None, scene, boxes
            self.explode = 0.0
            self.selected = set()
            self._shown(scene, keep_camera)

        def _shown(self, scene, keep_camera: bool) -> None:
            """A new scene is shown isometric and fitted, as the real view does, unless the
            pane keeps the camera (another configuration of the same document)."""
            if scene is not None:
                self.keep_calls.append(keep_camera)
            if not keep_camera:
                self.cam = self.FITTED

        def camera_state(self) -> dict:
            return dict(self.cam)

        def set_camera_state(self, state: dict) -> None:
            self.cam = dict(state)
            self.camera_calls.append(dict(state))

        def set_highlight(self, indices) -> None:
            self.selected = set(indices)

        def set_looks(self, opacity, hidden) -> None:
            self.opacity, self.hidden = list(opacity or ()), list(hidden or ())
            self.looks_calls += 1

        def set_explode_choices(self, choices) -> None:
            self.explode_choices = dict(choices or {})

        def set_explode_level(self, level: str) -> None:
            self.explode_level = level

        def explode_to(self, amount: float, *, animate: bool = True, follow: bool = False) -> None:
            self.explode = amount
            self.explode_calls.append((amount, "follow" if follow else animate))

        def fit(self) -> None:
            pass

        def reset_view(self) -> None:
            pass

    def make():
        made.append(StubView())
        return made[-1]

    return make


def _show_3d(viewer, name: str) -> None:
    """Select ``name`` with the Preview tab showing and wait while OpenGL starts and its
    mesh is read, if either happens."""
    from solidseas_app.viewer.details import TABS

    w = viewer.window
    w.details.tabs.setCurrentIndex(TABS.index("Preview"))
    viewer.select(name)
    pane = w.details.preview
    _wait(viewer.app, lambda: pane.mesh_state not in ("starting", "loading"))


@needs_qt
def test_a_part_saved_without_a_display_mesh_is_drawn_from_its_bodies(viewer, tmp_path):
    w = viewer.window
    pane = w.details.preview
    made: list = []
    pane.view_factory = _stub_view_factory(made)
    pane.gl_check = lambda: (True, "test")
    plain = rebuild(fixture_path("o02_boxA.SLDPRT"), drop=("Contents/DisplayLists",))
    (tmp_path / "plain.SLDPRT").write_bytes(plain)
    viewer.open(tmp_path)
    w.change_settings(view_3d=True)
    _show_3d(viewer, "plain.SLDPRT")
    assert pane.mesh_state == "ready" and made[-1].mesh.n_triangles == 12
    assert "made from the part's own bodies, as it saved no display mesh" in pane.caption.text()


@needs_qt
def test_the_3d_view_says_what_it_can_show(viewer, crafted):
    w = viewer.window
    pane = w.details.preview
    made: list = []
    pane.view_factory = _stub_view_factory(made)
    pane.gl_check = lambda: (True, "test")
    warmed: list = []
    pane.warmUp.connect(lambda: warmed.append(pane.model_message.text()))
    before = _state(FIXTURES)
    viewer.open(FIXTURES)
    w.change_settings(view_3d=True)
    assert pane.mode == "3d" and pane.preferred == "3d" and not pane.model_button.isHidden()
    # Turning 3D on makes the view at once (the window turns to OpenGL drawing then, not at
    # the first part) and starts the mesh process meanwhile.
    assert len(warmed) == 1 and made and pane.view is made[-1]

    _show_3d(viewer, "o02_boxA.SLDPRT")
    assert w.mesh_reader.started == 1 and len(made) == 1
    assert pane.mesh_state == "ready" and made and made[-1].mesh.n_triangles == 12
    assert pane.model_stack.currentWidget() is made[-1]
    caption = pane.caption.text()
    assert (
        caption.startswith("12 triangles and 24 vertices from the display mesh") and "0.00 s" not in caption
    )
    assert "Left-drag rotates, right-drag pans, roll the wheel away from you to zoom in" in caption
    w.change_settings(mouse_style="solidworks")
    assert "Middle-drag rotates, Ctrl+middle-drag pans" in pane.caption.text()
    assert "roll the wheel toward you to zoom in" in pane.caption.text()
    assert made[-1].mouse_style == "solidworks" and pane.image.mouse_style == "solidworks"

    _show_3d(viewer, "o01_empty.SLDPRT")
    assert pane.mesh_state == "no_mesh" and pane.model_message.text().startswith("No saved display mesh")
    assert viewer.page("Preview").showing_content  # no stored image either, but 3D has its say

    # An assembly is drawn too, each file in its colour with a legend, and its configuration
    # list is on the bar.
    _show_3d(viewer, ASSEMBLY)
    assert pane.mode == "3d" and pane.mesh_state == "ready" and made[-1].assembly.n_instances == 2
    assert pane.legend is not None and pane.legend.count() == 1 and not pane.legend.isHidden()
    assert pane.legend.item(0).text() == "o02_boxA.SLDPRT (2)"
    assert not pane.config_combo.isHidden() and pane.config_combo.currentText() == "Default"
    assert pane.caption.text().startswith("2 instances of 1 file, 24 triangles drawn from 12 read")
    assert pane.status.isHidden()  # every instance is shown

    # A drawing shows the preview SOLIDWORKS stored, with 3D off and a note saying why;
    # the choice of 3D stays for the next part.
    w.mesh_result = None
    _show_3d(viewer, "o18_drw_boxA.SLDDRW")
    assert pane.mode == "image" and pane.preferred == "3d" and pane.mesh_state == "no_3d"
    assert pane.stack.currentWidget() is pane.image and pane.image.pixmap is not None
    assert pane.image_button.isChecked() and not pane.model_button.isEnabled()
    assert "a drawing has no 3D model of its own" in pane.model_button.toolTip()
    assert "The 3D view is for parts and assemblies: a drawing has no 3D model" in pane.caption.text()
    assert pane.fit_button.isEnabled() and not pane.zoom_in.isHidden()  # the image's own controls
    assert pane.config_combo.isHidden() and pane.legend_button.isHidden()
    assert w.mesh_result is None  # a drawing's mesh is never read

    w.settings = w.settings.but(triangle_cap=5)  # below any real setting, to see the refusal
    _show_3d(viewer, "o03_boxA_again.SLDPRT")
    assert pane.mode == "3d" and pane.model_button.isEnabled()  # back in 3D without a click
    assert pane.mesh_state == "too_large"
    assert "has 12 triangles, more than the 3D view's limit of 5" in pane.model_message.text()
    w.change_settings(triangle_cap=1_000_000)  # a higher limit reads it again
    _wait(viewer.app, lambda: pane.mesh_state == "ready")

    # Choosing Image holds for the next part too, and nothing is read for it.
    pane.image_button.click()
    w.mesh_result = None
    _show_3d(viewer, "o04_boxA_props.SLDPRT")
    assert pane.mode == "image" and pane.preferred == "image" and pane.mesh_state == "idle"
    assert w.mesh_result is None and "from the stream" in pane.caption.text()  # the image's own caption
    pane.model_button.click()
    _wait(viewer.app, lambda: pane.mesh_state == "ready")
    assert pane.mode == "3d" and made[-1].mesh.n_triangles == 12

    # Once OpenGL has failed in the view, the next part says so without reading its mesh.
    made[-1].error = "the shaders did not link"
    made[-1].failed.emit(made[-1].error)
    assert pane.mesh_state == "gl_failed"
    w.mesh_result = None
    _show_3d(viewer, "o05_boxA_props_mat.SLDPRT")
    assert pane.mesh_state == "gl_failed" and "the shaders did not link" in pane.model_message.text()
    assert w.mesh_result is None and pane.caption.text() == ""

    w.change_settings(view_3d=False)
    assert pane.view is None and pane.model_button.isHidden() and pane.mode == "image"
    pane.gl_result = None  # a fresh check, which says there is no OpenGL
    pane.gl_check = lambda: (False, "no OpenGL context can be made on the offscreen platform")
    w.change_settings(view_3d=True)
    w.mesh_result = None
    _show_3d(viewer, "o04_boxA_props.SLDPRT")
    assert pane.mesh_state == "no_gl"
    assert pane.model_message.text().startswith("The 3D view needs OpenGL, which is not available here")
    assert w.mesh_result is None and pane.view is None

    pane.set_mode("image")
    assert pane.stack.currentWidget() is pane.image and pane.image.pixmap is not None
    w.change_settings(view_3d=False)
    assert _state(FIXTURES) == before
    w.change_settings(view_3d=True)  # a part saved without a preview image still shows in 3D
    pane.gl_result, pane.gl_check = None, lambda: (True, "test")
    viewer.open(crafted)
    _show_3d(viewer, "no_preview.SLDPRT")
    assert pane.mesh_state == "ready" and viewer.page("Preview").showing_content


@needs_qt
def test_a_mesh_read_in_progress_is_ended_when_it_is_not_wanted(tmp_path):
    """The mesh is read in a child process: a cancel ends it at once, so the next read
    does not wait behind a long one, and a child that dies says so."""
    import threading

    from solidseas_app.viewer import meshproc

    folder = tmp_path / "parts"
    folder.mkdir()
    (folder / "strip.SLDPRT").write_bytes(
        rebuild(fixture_path("o02_boxA.SLDPRT"), {"Contents/DisplayLists": _strip_display_list(1_500_000)})
    )
    shutil.copy2(fixture_path("o02_boxA.SLDPRT"), folder / "o02_boxA.SLDPRT")
    before = _state(folder)
    reader = meshproc.MeshReader()
    try:
        slow = str(folder / "strip.SLDPRT")

        def read_in_thread(token, wait=0.3):
            out: dict = {}
            th = threading.Thread(
                target=lambda: out.update(r=reader.read(slow, str(folder), 50_000_000, token=token))
            )
            th.start()
            _wait_for(lambda: reader.running, 30)
            time.sleep(wait)  # into the read, which takes a few seconds
            return th, out

        # Ended while it is still starting, before it has taken over its end of the
        # pipe: the pipe never breaks, and the read used to wait forever.
        token = object()
        th, out = read_in_thread(token, wait=0)
        reader.cancel(token)
        th.join(5)
        assert out.get("r", {}).get("state") == "cancelled" and not reader.running

        token = object()
        th, out = read_in_thread(token)
        t = time.monotonic()
        reader.cancel(object())  # another read's token: nothing happens
        assert reader.running
        reader.cancel(token)
        th.join(10)
        assert out.get("r", {}).get("state") == "cancelled" and time.monotonic() - t < 2
        assert not reader.running
        ok = reader.read(str(folder / "o02_boxA.SLDPRT"), str(folder), 1_000_000)
        assert ok["state"] == "ok" and ok["data"].n_triangles == 12 and reader.started == 3
        assert "start" in ok["seconds"] and ok["wall"] >= ok["seconds"]["start"]

        th, out = read_in_thread(object())
        reader._proc.kill()  # as if it crashed
        th.join(10)
        assert out.get("r", {}).get("state") == "error"
        assert out["r"]["error"]["code"] == "mesh_process_stopped"
        assert "stopped before it finished" in wording.error_message(out["r"]["error"])
    finally:
        reader.close()
    assert not reader.running and reader.read(slow, str(folder), 1000)["state"] == "cancelled"  # closed
    assert _state(folder) == before


@needs_qt
@pytest.mark.skipif(not WINDOWS, reason="job objects are a Windows feature")
def test_the_mesh_process_is_held_to_its_memory_limit(tmp_path, monkeypatch):
    from solidseas_app.viewer import meshproc

    assert meshproc.memory_limit(mesh3d.DEFAULT_TRIANGLE_CAP) == (
        (768 << 20) + 4 * 256_000_000 + meshproc.TESSELLATION_CACHE_BYTES
    )
    folder = tmp_path / "parts"
    folder.mkdir()
    (folder / "strip.SLDPRT").write_bytes(
        rebuild(fixture_path("o02_boxA.SLDPRT"), {"Contents/DisplayLists": _strip_display_list(1_500_000)})
    )
    monkeypatch.setattr(meshproc, "memory_limit", lambda cap: 60 << 20)
    reader = meshproc.MeshReader()
    try:
        result = reader.read(str(folder / "strip.SLDPRT"), str(folder), 50_000_000)
        assert reader.contained
        assert result["state"] == "too_large" and result["memory"]
        assert reader.peak_memory() <= 60 << 20
    finally:
        reader.close()


def _wait_for(condition, timeout: float) -> None:
    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            raise AssertionError("timed out")
        time.sleep(0.01)


def _strip_display_list(n: int) -> bytes:
    """A ``Contents/DisplayLists`` stream holding one triangle strip of ``n`` vertices,
    which takes the library a few seconds to expand into triangles."""
    import struct
    from array import array

    pos = array("f", bytes(12 * n))
    pos[0::3] = array("f", range(n))
    pos[1::3] = array("f", [0.0, 1.0]) * (n // 2)
    head = struct.pack("<IIIII", 4, 8, 2, 1, n) + struct.pack("<IIII", 12, 100, 2, n)
    tail = struct.pack("<IIII", 12, 100, 2, 0) + struct.pack("<IIII", 4, 8, 2, 0)
    tail += struct.pack("<IIIII", 4, 8, 2, 1, 2 * n - 2) + struct.pack("<IIII", 1, 8, 2, 0)
    return head + pos.tobytes() + tail


@needs_qt
def test_the_3d_view_is_off_by_default_and_never_loads_opengl_then(tmp_path):
    script = (
        "import os, sys, time\n"
        "from PySide6.QtWidgets import QApplication\n"
        "app = QApplication([])\n"
        "from solidseas_app.viewer.window import MainWindow\n"
        "from solidseas_app.viewer.details import TABS\n"
        "from solidseas_app.viewer import indexer\n"
        "indexer.DEFAULT_ON = False  # the indexer is a process of its own, not what this counts\n"
        "w = MainWindow(); w.show(); w.open_folder(sys.argv[1])\n"
        "end = time.monotonic() + 60\n"
        "while w.listing_info is None and time.monotonic() < end: app.processEvents()\n"
        "w.details.tabs.setCurrentIndex(TABS.index('Preview'))\n"
        "w.select_document('o02_boxA.SLDPRT')\n"
        "for _ in range(200): app.processEvents(); time.sleep(0.002)\n"
        "import multiprocessing\n"
        "print(sorted(m for m in sys.modules if 'OpenGL' in m or m.endswith('view3d')),"
        " w.mesh_reader.started,"
        # The window's workers read the fixtures of other formats (an STL, a 3MF...).
        " len([c for c in multiprocessing.active_children() if c.name != 'solidseas-worker']))\n"
        "w.shutdown()\n"
    )
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=_SRC)
    proc = subprocess.run(
        [sys.executable, "-c", script, str(FIXTURES)], env=env, capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().splitlines()[-1] == "[] 0 0"  # no OpenGL, and no mesh process either


@needs_qt
def test_the_3d_view_turns_mouse_input_into_camera_moves(app):
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
    from PySide6.QtWidgets import QApplication

    from solidseas_app.viewer import view3d

    data = mesh3d.read_part_mesh(str(fixture_path("o02_boxA.SLDPRT")), str(FIXTURES), 1000)["data"]
    view = view3d.ModelView(rotation_mode=viewmath.TURNTABLE)  # never shown: no OpenGL needed
    view.resize(400, 300)
    view.set_mesh(data)
    cam = view.camera
    no = Qt.KeyboardModifier.NoModifier

    def drag(button, dx, dy, mods=no):
        start, end = QPointF(200, 150), QPointF(200 + dx, 150 + dy)
        for kind, pos, b, held in (
            (QEvent.Type.MouseButtonPress, start, button, button),
            (QEvent.Type.MouseMove, end, Qt.MouseButton.NoButton, button),
            (QEvent.Type.MouseButtonRelease, end, button, Qt.MouseButton.NoButton),
        ):
            QApplication.sendEvent(view, QMouseEvent(kind, pos, pos, b, held, mods))

    def state():
        return (
            round(cam.yaw, 6),
            round(cam.pitch, 6),
            tuple(round(v, 9) for v in cam.target),
            cam.half_height,
        )

    left, right, middle = Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton
    fitted = state()

    def press(button, mods=no):
        pos = QPointF(200, 150)
        QApplication.sendEvent(
            view, QMouseEvent(QEvent.Type.MouseButtonPress, pos, pos, button, button, mods)
        )
        shape = view.cursor().shape()
        QApplication.sendEvent(
            view, QMouseEvent(QEvent.Type.MouseButtonRelease, pos, pos, button, Qt.MouseButton.NoButton, mods)
        )
        return shape

    # Rotating shows curved arrows (Qt has none, so the view draws them); panning the
    # closed hand the preview image pans with; the four-way arrow, which means move, neither.
    assert press(left) == Qt.CursorShape.BitmapCursor
    assert press(right) == Qt.CursorShape.ClosedHandCursor
    assert view3d.rotate_cursor().pixmap().size().width() == 32
    drag(left, 50, 0)  # standard: left rotates
    assert cam.yaw == pytest.approx(viewmath.ISO_YAW - 50 * viewmath.DEGREES_PER_PIXEL)
    s = state()
    drag(right, 40, 0)  # right pans
    assert state()[:2] == s[:2] and state()[2] != s[2]
    s = state()
    drag(middle, 0, 40)  # middle pans too
    assert state()[:2] == s[:2] and state()[2] != s[2]
    view.mouse_style = viewmath.SOLIDWORKS
    s = state()
    drag(left, 50, 50)
    drag(right, 50, 50)
    assert state() == s  # SOLIDWORKS selects with these: nothing moves
    drag(middle, 0, 30)
    assert cam.pitch != s[1] and state()[2] == s[2]  # middle rotates
    s = state()
    drag(middle, 30, 0, Qt.KeyboardModifier.ControlModifier)
    assert state()[:2] == s[:2] and state()[2] != s[2]  # Ctrl+middle pans
    s = state()
    drag(middle, 0, -50, Qt.KeyboardModifier.ShiftModifier)
    assert cam.half_height < s[3]  # Shift+middle, dragged up, zooms in

    def roll(notches):
        pos = QPointF(300, 100)
        QApplication.sendEvent(
            view,
            QWheelEvent(
                pos,
                view.mapToGlobal(pos),
                QPoint(),
                QPoint(0, 120 * notches),
                Qt.MouseButton.NoButton,
                no,
                Qt.ScrollPhase.NoScrollPhase,
                False,
            ),
        )

    half = cam.half_height
    roll(1)  # SOLIDWORKS: rolled away from you, it zooms out, as SOLIDWORKS does
    assert cam.half_height == pytest.approx(half * viewmath.WHEEL_STEP)
    view.invert_wheel = True
    roll(1)
    assert cam.half_height == pytest.approx(half)
    view.mouse_style, view.invert_wheel = viewmath.STANDARD, False
    roll(1)  # Standard: away from you zooms in
    assert cam.half_height == pytest.approx(half / viewmath.WHEEL_STEP)
    QApplication.sendEvent(
        view,
        QMouseEvent(QEvent.Type.MouseButtonDblClick, QPointF(5, 5), QPointF(5, 5), left, left, no),
    )
    assert tuple(round(v, 9) for v in cam.target) == fitted[2]  # double-click fits

    def key(k, mods=no):
        QApplication.sendEvent(view, QKeyEvent(QEvent.Type.KeyPress, k, mods))

    key(Qt.Key.Key_R)
    assert state() == fitted  # R: back to the isometric view, fitted
    cam.rotate(10, 10)
    key(Qt.Key.Key_F)
    assert cam.yaw != viewmath.ISO_YAW and tuple(round(v, 9) for v in cam.target) == fitted[2]

    # The keys turn the model without a middle button, as in SOLIDWORKS.
    ctrl, shift = Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.ShiftModifier
    key(Qt.Key.Key_1, ctrl)
    assert (cam.yaw, cam.pitch) == viewmath.VIEWS["front"] and cam.fitted
    key(Qt.Key.Key_Right)  # as a drag to the right: the front turns right
    assert cam.yaw == pytest.approx(360 - viewmath.ARROW_STEP) and not cam.fitted
    key(Qt.Key.Key_Down, shift)  # 90 degrees: looking straight down
    assert cam.pitch == 90
    key(Qt.Key.Key_5, ctrl)
    assert (cam.yaw, cam.pitch) == viewmath.VIEWS["top"]
    target = cam.target
    key(Qt.Key.Key_Left, ctrl)  # Ctrl+arrow pans a tenth of the view
    assert cam.target != target and (cam.yaw, cam.pitch) == viewmath.VIEWS["top"]
    key(Qt.Key.Key_7, ctrl)
    assert state() == fitted  # Ctrl+7: isometric
    view.deleteLater()


def _long_box_mesh():
    """A 200 x 10 x 10 mm box as display-mesh buffers: much wider than high."""
    import struct

    lo, hi = (0.0, 0.0, 0.0), (0.2, 0.01, 0.01)
    corners = [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    tris = [i for a, b, c, d in faces for i in (a, b, c, a, c, d)]
    return mesh3d.MeshBuffers(
        positions=struct.pack(f"<{24}f", *[v for p in corners for v in p]),
        normals=bytes(8 * 12),
        indices=struct.pack(f"<{len(tris)}I", *tris),
        n_vertices=8,
        n_triangles=12,
        bbox=(lo, hi),
    )


@needs_qt
def test_the_first_part_in_a_new_3d_view_is_fitted_to_the_view_it_lands_in(app):
    """A new view is 640 x 480 until it is laid out, and the first mesh arrived then:
    a long part fitted to that shape lost both ends in the narrower panel."""
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from solidseas_app.viewer import view3d

    view = view3d.ModelView()
    assert (view.width(), view.height()) == (640, 480)
    view.set_mesh(_long_box_mesh())
    host = QWidget()
    QVBoxLayout(host).addWidget(view)
    host.resize(392, 636)
    host.show()  # offscreen: no OpenGL, but the view is laid out and resized all the same
    app.processEvents()
    assert view.width() < view.height()
    assert _x_extent(view.camera) == pytest.approx(1 / 1.15)  # refitted: both ends in view
    host.resize(700, 400)
    app.processEvents()
    assert _x_extent(view.camera) <= 1 / 1.15 + 1e-9
    view.camera.zoom(2.0)  # the user zoomed: a resize keeps their zoom
    half = view.camera.half_height
    host.resize(500, 500)
    app.processEvents()
    assert view.camera.half_height == half
    host.deleteLater()


_GL_DRAW = """
from solidseas_app.viewer import mesh3d
data = mesh3d.read_part_mesh(sys.argv[1], sys.argv[2], 1000)["data"]
view = view3d.ModelView()
view.resize(320, 240)
view.set_mesh(data)

def shot():
    img = view.grabFramebuffer()
    bg = img.pixelColor(1, 1)
    covered = sum(
        img.pixelColor(x, y) != bg for y in range(0, img.height(), 4) for x in range(0, img.width(), 4)
    )
    return img, covered, bg.name()

first, covered, background = shot()
view.camera.rotate(120, 30)
second, _, _ = shot()

# A long part shown first in a new view, which is 640 x 480 until it is laid out
# narrow: both ends must be in view.
import struct
lo, hi = (0.0, 0.0, 0.0), (0.2, 0.01, 0.01)
corners = [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
tris = [i for a, b, c, d in faces for i in (a, b, c, a, c, d)]
positions = struct.pack("<24f", *[v for p in corners for v in p])
long_box = mesh3d.MeshBuffers(positions, bytes(96), struct.pack("<36I", *tris), 8, 12, (lo, hi))
narrow = view3d.ModelView()
narrow.set_mesh(long_box)
narrow.resize(200, 400)
img = narrow.grabFramebuffer()
bg = img.pixelColor(1, 1)
w, h = img.width(), img.height()
edges = sum(img.pixelColor(x, y) != bg for y in range(h) for x in (0, 1, w - 2, w - 1))
xs = [x for x in range(0, w, 2) for y in range(0, h, 2) if img.pixelColor(x, y) != bg]
span = max(xs) - min(xs) if xs else 0
print(json.dumps({
    "gl": True, "why": why, "error": view.error, "covered": covered, "samples": 80 * 60,
    "background": background, "rotated_differs": first != second,
    "centre": first.pixelColor(160, 120).name(),
    "long": {"size": [w, h], "edge_pixels": edges, "span": span, "error": narrow.error},
}))
"""


@needs_qt
def test_the_3d_view_draws_a_part_with_opengl():
    """Qt's offscreen platform has no OpenGL on Windows, so this draws on the real display,
    in a window that is never shown, and skips where there is none (:mod:`gl_support`)."""
    from gl_support import run_gl

    out = run_gl(_GL_DRAW, str(fixture_path("o02_boxA.SLDPRT")), str(FIXTURES))
    assert out["error"] is None
    assert out["background"] in ("#e9edf2", "#2b2f36")
    assert out["centre"] != out["background"]  # the box sits in the middle, fitted
    assert 0.1 * out["samples"] < out["covered"] < 0.9 * out["samples"]
    assert out["rotated_differs"]
    long = out["long"]
    assert long["error"] is None and long["size"] == [200, 400]
    assert long["edge_pixels"] == 0  # neither end cut off by the sides
    assert long["span"] > 0.75 * 200  # and it spans most of the width, fitted to it


@needs_qt
def test_the_self_test_turns_3d_on_in_its_own_settings_only(app, tmp_path, monkeypatch):
    from solidseas_app.viewer import app as viewer_app
    from solidseas_app.viewer.settings import SettingsStore

    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)  # main() installs its own
    before = _state(FIXTURES)
    shots = tmp_path / "shots"
    args = ["--self-test", str(FIXTURES), "--screenshot-dir", str(shots), "--select", "o02_boxA.SLDPRT"]
    assert viewer_app.main([*args, "--select", ASSEMBLY, "--3d"]) == 0
    report = json.loads((shots / "selftest.json").read_text(encoding="utf-8"))
    assert report["ok"] and report["view_3d"]
    assert report["settings"] == str(shots / "selftest-settings.ini")
    stored = SettingsStore(report["settings"]).load()
    assert stored.view_3d and not stored.remember_session
    assert not (tmp_path / "Roaming").exists()  # the user's settings were never read or written
    part, assembly = report["documents"]
    assert part["mesh"]["state"] in ("ready", "no_gl") and assembly["mesh"]["state"] in ("ready", "no_gl")
    if part["mesh"]["state"] == "ready":
        assert part["mesh"]["triangles"] == 12
        assert (assembly["mesh"]["instances"], assembly["mesh"]["triangles"]) == (2, 24)
    names = [os.path.basename(p) for p in report["screenshots"]]
    assert "03_settings_3d_print.png" in names  # the Settings window, closed unapplied:
    assert not (shots / "selftest-Drawing.json").exists()  # its Drawing Settings were never saved
    for stem in ("o02_boxA", "o08_asm_2x_boxA"):
        assert any(n.endswith(f"{stem}_preview_zoomed.png") for n in names)
        assert any(n.endswith(f"{stem}_preview_3d.png") for n in names)
    assert viewer_app.main(args) == viewer_app.EXIT_REFUSED  # its outputs exist: --force replaces them
    assert viewer_app.main(["--3d"]) == viewer_app.EXIT_USAGE  # --3d belongs to the self-test
    assert viewer_app.main([*args, "--configuration", "Lite"]) == viewer_app.EXIT_USAGE  # and needs --3d
    assert _state(FIXTURES) == before


@needs_qt
def test_the_self_test_keeps_its_caches_in_a_folder_of_its_own(app, tmp_path, monkeypatch):
    """A self-test indexes the folder and saves its index as the viewer does, but in a
    temporary folder of its own that it removes when it ends: the person's cache and data
    folders gain nothing, and the variables that name them are put back (SolidSeas-a0j9)."""
    from solidseas.catalog import store as catalog_store
    from solidseas_app.viewer import app as viewer_app
    from solidseas_app.viewer import indexer, savedindex
    from solidseas_app.viewer.selftest import SelfTest

    cache, data = tmp_path / "cache", tmp_path / "data"  # the person's, as the variables name them
    monkeypatch.setenv("SOLIDSEAS_CACHE_DIR", str(cache))
    monkeypatch.setenv("SOLIDSEAS_DATA_DIR", str(data))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)  # main() installs its own
    monkeypatch.setattr(indexer, "DEFAULT_ON", True)  # opened folders are indexed, as on a PC

    def indexes() -> str:  # the saved index where the viewer keeps it: in the cache folder of the moment
        return os.path.join(catalog_store.cache_dir(), "indexes")

    monkeypatch.setattr(savedindex, "index_folder", indexes)
    seen: dict = {}
    finish = SelfTest._finish

    def finish_once_indexed(self) -> None:  # the catalog and the saved index are written first
        self.timer.stop()
        own = Path(catalog_store.cache_dir())
        _wait(app, lambda: self.window.where_used.job is None and any(own.glob("indexes/*.sqlite")), 120.0)
        seen.update(cache=own, index=self.window.where_used.result)
        finish(self)

    monkeypatch.setattr(SelfTest, "_finish", finish_once_indexed)
    assert viewer_app.main(["--self-test", str(FIXTURES), "--report", str(tmp_path / "r.json")]) == 0
    own = seen["cache"]
    assert own.name == "cache" and own.parent.name.startswith("solidseas-selftest-cache-")
    assert seen["index"]["ok"] and own in Path(seen["index"]["db"]).parents
    assert not own.parent.exists()  # removed when the run ended
    assert not cache.exists() and not data.exists()  # the person's folders were never made
    assert (os.environ["SOLIDSEAS_CACHE_DIR"], os.environ["SOLIDSEAS_DATA_DIR"]) == (str(cache), str(data))


@needs_qt
def test_the_self_tests_cache_folder_goes_however_the_run_ends(monkeypatch):
    from solidseas_app.viewer.selftest import OWN_FOLDERS, own_cache_folder

    for name in OWN_FOLDERS:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError), own_cache_folder() as work:
        assert os.environ["SOLIDSEAS_CACHE_DIR"] == os.path.join(work, "cache")
        assert os.environ["SOLIDSEAS_DATA_DIR"] == os.path.join(work, "data")
        os.makedirs(os.path.join(work, "cache", "catalogs"))  # something the run wrote
        raise RuntimeError("the window failed")
    assert not os.path.exists(work)
    assert not any(name in os.environ for name in OWN_FOLDERS)  # unset before, unset again


@needs_qt
def test_saved_settings_apply_when_the_window_opens(app, tmp_path):
    from PySide6.QtCore import QSize

    from solidseas_app.viewer.settings import Settings, SettingsStore
    from solidseas_app.viewer.window import MainWindow

    store = SettingsStore(str(tmp_path / "Viewer.ini"))
    store.save(
        Settings(
            view_3d=True,
            mouse_style="solidworks",
            invert_wheel=True,
            thumbnail_size="small",
            list_view="icons",
            show_lock_files=True,
        )
    )
    w = MainWindow(SettingsStore(store.path))
    try:
        pane = w.details.preview
        assert w.act_3d.isChecked() and pane.enabled_3d and pane.mode == "3d"
        assert w.act_mouse["solidworks"].isChecked() and pane.mouse_style == "solidworks"
        assert w.act_invert_wheel.isChecked() and pane.image.invert_wheel
        assert w.act_icons_view.isChecked() and w.icons.iconSize() == QSize(96, 72)
        assert w.act_lock_files.isChecked() and w.proxy.lock_files
        w.open_folder(str(FIXTURES))
        _wait(app, lambda: w.listing_info is not None)
        assert w.list_stack.currentWidget() is w.icons and w.model.thumb_size == (96, 72)
        assert all(r.thumb is None or _fits(r.thumb, 96, 72) for r in w.model.rows)
    finally:
        w.shutdown()
        w.close()


def _fits(png: bytes, width: int, height: int) -> bool:
    """A thumbnail made to fit ``width`` x ``height``: inside it, touching one side."""
    from PySide6.QtGui import QImage

    img = QImage.fromData(png)
    inside = img.width() <= width and img.height() <= height
    return inside and (img.width() == width or img.height() == height)


@needs_qt
def test_no_two_settings_share_a_mnemonic(viewer):
    """Alt+S then a letter reaches one setting: each item and submenu of the Settings
    menu that has an access key has its own."""
    keys = []
    for a in viewer.window.settings_menu.actions():
        text = a.text() or (a.menu().title() if a.menu() is not None else "")
        if "&" in text.replace("&&", ""):
            keys.append(text.replace("&&", "")[text.replace("&&", "").index("&") + 1].lower())
    assert keys and len(keys) == len(set(keys)), keys


@needs_qt
def test_a_prints_result_line_goes_when_another_document_is_shown(viewer):
    """The status line's word on how a print ended is about that document: showing another
    takes it away, but not a message that has replaced it since."""
    w = viewer.window
    viewer.open(FIXTURES)
    viewer.select("o02_boxA.SLDPRT")
    said = "Saved o02_boxA 2026-10-09.3mf and opened it in a slicer."
    w.printer._say(said, 12000)
    assert w.statusBar().currentMessage() == said
    viewer.select("o03_boxA_again.SLDPRT")
    assert w.statusBar().currentMessage() == ""
    w.printer._say(said, 12000)
    w.statusBar().showMessage("Something else", 5000)
    viewer.select("o02_boxA.SLDPRT")
    assert w.statusBar().currentMessage() == "Something else"


@needs_qt
def test_where_used_says_not_indexed_yet_while_the_catalog_is_being_made(app, tmp_path):
    import sqlite3

    from solidseas.catalog import schema
    from solidseas_app.viewer.whereused import where_used_work

    db = tmp_path / "catalog.sqlite"
    con = sqlite3.connect(db)
    con.execute(f"PRAGMA application_id={schema.APPLICATION_ID}")
    con.close()
    got = where_used_work(str(db), str(tmp_path), str(tmp_path / "a.SLDPRT"), None)(None, lambda: False)
    assert got == {"ok": True, "data": None, "state": None, "folder_root": None}
