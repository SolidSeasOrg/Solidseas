"""The BOM editor window (``solidseas_app.viewer.bomeditor``), offscreen, on o16's BOMs as
the viewer's reader gives them."""

import os

import pytest

from solidseas import bom as bom_mod
from solidseas import bomfile, model, open_document
from support import fixture_path
from test_viewer import needs_qt

O16 = fixture_path("o16_asm_features.SLDASM")


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from solidseas_app.viewer.app import use_system_fonts

    use_system_fonts()
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def boms():
    with open_document(O16) as doc:
        return {t: model.bom_data(b) for t, b in bom_mod.build_boms(doc, bom_types=bom_mod.BOM_TYPES).items()}


@pytest.fixture
def editor(app, boms, tmp_path):
    from solidseas_app.viewer.bomeditor import BomEditor

    asked: list = []
    e = BomEditor(boms, str(O16), "Default", ask_path=lambda title, start, f: asked.pop(0) if asked else "")
    e.asked, e.warned = asked, []
    e.warn = lambda title, text: e.warned.append(text)
    yield e
    e.undo_stack.setClean()
    e.close()
    e.deleteLater()


def _column(e, row: int) -> list[str]:
    return [e.table.item(row, c).text() for c in range(e.table.columnCount())]


def _part_numbers(e) -> list[str]:
    return [e.table.item(r, 1).text().strip() for r in range(e.table.rowCount())]


@needs_qt
def test_it_opens_on_the_indented_bom_as_solidworks_numbers_it(editor):
    assert editor.table.rowCount() == 9 and _column(editor, 3)[:2] == ["3.1", "  o02_boxA"]
    assert [editor.table.horizontalHeaderItem(c).text() for c in range(4)] == [
        "ITEM NO.",
        "PART NUMBER",
        "DESCRIPTION",
        "QTY.",
    ]
    assert editor.windowTitle() == "o16_asm_features.SLDASM (Default) - BOM - SolidSeas"


@needs_qt
def test_typing_in_a_cell_edits_it_and_undo_and_reset_put_it_back(editor):
    from solidseas_app.viewer.bomeditor import EDITED_GROUND

    editor.table.item(0, 2).setText("Base plate")
    item = editor.table.item(0, 2)
    assert item.text() == "Base plate" and item.font().italic() and item.background().color() == EDITED_GROUND
    assert "The BOM gives: (empty)" in item.toolTip() and editor.windowTitle().startswith("*")
    editor.undo_stack.undo()
    assert editor.table.item(0, 2).text() == "" and not editor.table.item(0, 2).font().italic()
    editor.undo_stack.redo()
    editor.table.setCurrentCell(0, 2)
    editor.reset_cell()
    assert editor.spec.overrides == {}
    assert not editor.table.item(0, 0).flags() & editor.table.item(0, 2).flags().ItemIsEditable, (
        "ITEM is not typed in"
    )


@needs_qt
def test_moving_and_hiding_rows_numbers_them_again(editor):
    editor.table.selectRow(3)  # 3.1 o02_boxA under the sub-assembly
    editor.move(1)
    assert _part_numbers(editor)[3:5] == ["o07_boxB_h31", "o02_boxA"] and _column(editor, 3)[0] == "3.1"
    assert not editor.actions_by_name["down"].isEnabled(), "the last row of a sub-assembly stays under it"
    editor.table.selectRow(0)
    editor.hide_row()
    assert (
        editor.table.rowCount() == 8
        and _column(editor, 0)[0] == "1"
        and _part_numbers(editor)[0] == "o06_boxA_props_mat_cfg"
    )
    editor.show_hidden()
    assert editor.table.rowCount() == 9


@needs_qt
def test_a_type_and_a_property_column_come_from_what_was_read(editor):
    from solidseas_app.viewer.bomeditor import ColumnsDialog

    editor._set_type("parts")
    assert "o15_sub_asm" not in _part_numbers(editor)
    names = ["PartNo", "Description"]
    dialog = ColumnsDialog(editor, editor.spec.columns, names)
    for i in range(dialog.list.count()):
        item = dialog.list.item(i)
        if item.data(0x0100)[0] == "property:PartNo":
            item.setCheckState(item.checkState().Checked)
            dialog.list.setCurrentItem(item)
            dialog.heading.setText("ERP NO.")
            dialog._renamed("ERP NO.")
    dialog.accept()
    editor.choose_columns(dialog)
    headings = [editor.table.horizontalHeaderItem(c).text() for c in range(editor.table.columnCount())]
    assert headings[-1] == "ERP NO." and "ORACLE-PN-123" in [
        editor.table.item(r, 4).text() for r in range(editor.table.rowCount())
    ]
    dialog.deleteLater()


@needs_qt
def test_save_writes_a_bom_file_and_again_only_over_its_own(editor, tmp_path, boms):
    from solidseas_app.viewer.bomeditor import BomEditor

    editor.table.item(1, 2).setText("Oracle box, anodised")
    target = str(tmp_path / "o16.ssbom")
    editor.asked.append(target)
    assert editor.save() and editor.path == target and editor.undo_stack.isClean()
    loaded = bomfile.read(target)
    assert loaded.sha256 == editor.sha256 and loaded.bom_file.table[2][2] == "Oracle box, anodised"
    editor.table.item(1, 2).setText("Oracle box")
    assert editor.save(), "its own unchanged file is written over"
    (tmp_path / "o16.ssbom").write_text("{}")  # changed by someone else since
    editor.table.item(1, 2).setText("x")
    assert not editor.save()
    assert "changed since" in editor.warned[-1]
    reopened = BomEditor(
        boms, str(O16), "Default", table_spec=loaded.bom_file.spec, path=target, sha256=loaded.sha256
    )
    assert reopened.table.item(1, 2).text() == "Oracle box, anodised"
    reopened.close()
    reopened.deleteLater()


@needs_qt
@pytest.mark.parametrize("ext", ["csv", "xlsx", "pdf"])
def test_export_writes_each_format(editor, tmp_path, ext):
    target = str(tmp_path / f"o16 BOM.{ext}")
    editor.asked.append(target)
    written = editor.export()
    assert written == target
    data = open(written, "rb").read()
    assert data[:4] in (b"\xef\xbb\xbfI", b"PK\x03\x04", b"%PDF")
    editor.asked.append(str(tmp_path / "o16 BOM.SLDPRT"))
    assert editor.export() is None and "Choose a .csv" in editor.warned[-1], "never a SOLIDWORKS file"
