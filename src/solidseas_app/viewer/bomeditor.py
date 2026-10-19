"""The BOM editor: a window that shows an assembly's bill of materials the way a person
wants it, saved as a ``.ssbom`` or as an assembly drawing's parts list.

:class:`BomEditor` is opened from the BOM tab (Edit BOM...) with the BOMs the tab has
already read, one per type, as ``bom`` JSON, or from a ``.ssbom`` file. What it
shows is :func:`solidseas.bomtable.apply` of its table definition to the BOM of the
type chosen, so nothing is read again while editing:

* **Type:** top level only, parts only or indented.
* **Columns...:** which columns, in which order, and their headings; any property
  the parts have can be a column (:func:`~solidseas.bomtable.property_names`).
* **Rows:** Move Up and Move Down (Ctrl+Up, Ctrl+Down) reorder a row among those
  beside it, Hide Row leaves one out (with the rows under it), Show Hidden Rows
  brings them all back. The ITEM column numbers the rows as shown.
* **Cells:** typing in a cell (double-click or F2) replaces its text; the cell is
  then shown in italics on a tinted ground, its tooltip giving the text it
  replaced, and Reset Cell puts that back. ITEM cannot be typed in.
* **Edits that no longer apply** (their part is gone from the BOM, or their column
  is not shown) are counted in the status bar, and Remove Them forgets them.
* **Undo and Redo** step through the table definitions before and after each edit.
* **Save** writes the ``.ssbom`` (Save As picks a new one): created new, or written
  over only the file this window read or last saved (:mod:`solidseas.bomfile`).
  In a drawing's editor, **Apply** hands the definition back instead
  (:attr:`BomEditor.applied`).
* **Export...** writes CSV, Excel or PDF (:mod:`solidseas.bomexport`), as a new file
  or over one the save dialog has asked about, never a SOLIDWORKS file.

The files it writes are small and written here, on the UI thread; nothing it does
reads a part or an assembly.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QFont, QKeySequence, QUndoCommand, QUndoStack
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from solidseas import bomexport, bomfile
from solidseas.bom import BOM_TYPES, TYPE_NAMES
from solidseas.bomtable import (
    BUILT_IN,
    PROPERTY,
    BomTableSpec,
    Column,
    ShownTable,
    apply,
    column,
    property_names,
    spec,
)
from solidseas.errors import SolidSeasError

from .wording import plural, tip

EDITED_GROUND = QColor(255, 244, 214)
EXPORTS = (("csv", "CSV (*.csv)"), ("xlsx", "Excel workbook (*.xlsx)"), ("pdf", "PDF (*.pdf)"))


class _Change(QUndoCommand):
    def __init__(self, editor: BomEditor, before: BomTableSpec, after: BomTableSpec, text: str) -> None:
        super().__init__(text)
        self.editor, self.before, self.after = editor, before, after

    def redo(self) -> None:
        self.editor._set_spec(self.after)

    def undo(self) -> None:
        self.editor._set_spec(self.before)


class ColumnsDialog(QDialog):
    """Which columns, in which order, with which headings: the built-in columns and every
    property the parts have, each ticked to show it."""

    def __init__(self, parent: QWidget | None, current: tuple[Column, ...], properties: list[str]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Columns")
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        shown = {c.id: c for c in current}
        ids = [c.id for c in current]
        ids += [k for k in BUILT_IN if k not in shown]
        ids += [PROPERTY + p for p in properties if PROPERTY + p not in shown]
        for cid in ids:
            heading = shown[cid].heading if cid in shown else column(cid).heading
            item = QListWidgetItem(self._label(cid, heading))
            item.setData(Qt.ItemDataRole.UserRole, (cid, heading))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if cid in shown else Qt.CheckState.Unchecked)
            if cid == "item":
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)  # ITEM is always shown
            self.list.addItem(item)
        self.heading = QLineEdit()
        self.heading.setPlaceholderText("Heading of the column selected")
        self.list.currentItemChanged.connect(self._picked)
        self.heading.textEdited.connect(self._renamed)
        up, down = QPushButton("Move Up"), QPushButton("Move Down")
        up.clicked.connect(lambda: self._move(-1))
        down.clicked.connect(lambda: self._move(1))
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        side = QVBoxLayout()
        side.addWidget(up)
        side.addWidget(down)
        side.addStretch(1)
        row = QHBoxLayout()
        row.addWidget(self.list, 1)
        row.addLayout(side)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Tick the columns to show, and drag them into the order wanted."))
        layout.addLayout(row)
        layout.addWidget(self.heading)
        layout.addWidget(buttons)

    @staticmethod
    def _label(cid: str, heading: str) -> str:
        if cid.startswith(PROPERTY):
            return f"{heading}  (property {cid[len(PROPERTY) :]})"
        return heading

    def _picked(self, item: QListWidgetItem | None, _old: Any = None) -> None:
        self.heading.setText("" if item is None else item.data(Qt.ItemDataRole.UserRole)[1])

    def _renamed(self, text: str) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        cid, _old = item.data(Qt.ItemDataRole.UserRole)
        item.setData(Qt.ItemDataRole.UserRole, (cid, text))
        item.setText(self._label(cid, text))

    def _move(self, step: int) -> None:
        row = self.list.currentRow()
        if row < 0 or not 0 <= row + step < self.list.count():
            return
        item = self.list.takeItem(row)
        self.list.insertItem(row + step, item)
        self.list.setCurrentRow(row + step)

    def columns(self) -> list[tuple[str, str]]:
        out = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            cid, heading = item.data(Qt.ItemDataRole.UserRole)
            if cid == "item" or item.checkState() == Qt.CheckState.Checked:
                out.append((cid, heading or column(cid).heading))
        return out


class BomEditor(QMainWindow):
    """The BOM editor (module notes). ``boms`` maps each type to its ``bom`` JSON;
    ``assembly`` is the assembly's path and ``configuration`` the configuration the
    BOMs are of. ``path`` and ``sha256`` are the ``.ssbom`` this window edits, if any.
    With ``apply_to_drawing`` true the window has Apply in place of Save, and emits
    :attr:`applied` with the definition."""

    applied = Signal(object)  # the BomTableSpec, from Apply
    changed = Signal()

    def __init__(
        self,
        boms: Mapping[str, Mapping[str, Any]],
        assembly: str,
        configuration: str | None,
        *,
        table_spec: BomTableSpec | None = None,
        path: str | None = None,
        sha256: str | None = None,
        apply_to_drawing: bool = False,
        ask_path: Callable[[str, str, str], str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.boms = dict(boms)
        self.assembly = assembly
        self.configuration = configuration
        self.path = path
        self.sha256 = sha256
        self.apply_to_drawing = apply_to_drawing
        # (title, start, filter) -> a chosen path or "": tests replace it
        self.ask_path = ask_path or self._ask_path
        self.warn: Callable[[str, str], Any] = lambda title, text: QMessageBox.warning(self, title, text)
        first = "indented" if "indented" in self.boms else next(iter(self.boms))
        self.spec = table_spec or spec(first)
        self.shown: ShownTable | None = None
        self.undo_stack = QUndoStack(self)
        self.undo_stack.cleanChanged.connect(self._update_title)
        self._filling = False

        self.type = QComboBox()
        for t in BOM_TYPES:
            if t in self.boms:
                self.type.addItem(TYPE_NAMES[t].capitalize(), t)
        self.type.activated.connect(lambda _i: self._set_type(self.type.currentData()))
        self.table = QTableWidget()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.itemChanged.connect(self._typed)
        self.table.itemSelectionChanged.connect(self._update_actions)
        self.unused = QLabel()
        self.forget = QPushButton("Remove Them")
        self.forget.setToolTip(tip("Forget the edits whose part or column is no longer in the table"))
        self.forget.clicked.connect(self.forget_unused)
        self.statusBar().addPermanentWidget(self.unused)
        self.statusBar().addPermanentWidget(self.forget)
        self._build_actions()
        central = QWidget()
        layout = QVBoxLayout(central)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Type:"))
        bar.addWidget(self.type)
        bar.addStretch(1)
        layout.addLayout(bar)
        layout.addWidget(self.table, 1)
        self.setCentralWidget(central)
        self.resize(900, 560)
        self._show()
        self.undo_stack.setClean()
        self._update_title()

    # ----------------------------------------------------------------- actions
    def _build_actions(self) -> None:
        a = self.actions_by_name = {}
        bar = QToolBar("BOM")
        bar.setMovable(False)
        self.addToolBar(bar)

        def act(key: str, text: str, slot, shortcut=None, hint: str = "") -> QAction:
            action = QAction(text, self)
            if shortcut is not None:
                action.setShortcut(QKeySequence(shortcut))
            if hint:
                action.setToolTip(tip(hint))
                action.setStatusTip(hint)
            action.triggered.connect(lambda _on=False: slot())
            self.addAction(action)
            a[key] = action
            return action

        if self.apply_to_drawing:
            act("save", "Apply", self.apply, "Ctrl+S", "Use this table as the drawing's parts list")
        else:
            act("save", "Save", self.save, QKeySequence.StandardKey.Save, "Save this BOM as a .ssbom file")
            act(
                "save_as",
                "Save As...",
                self.save_as,
                QKeySequence.StandardKey.SaveAs,
                "Save this BOM in a new file",
            )
        act("export", "Export...", self.export, "Ctrl+E", "Write this table as CSV, Excel or PDF")
        act("undo", "Undo", self.undo_stack.undo, QKeySequence.StandardKey.Undo)
        act("redo", "Redo", self.undo_stack.redo, QKeySequence.StandardKey.Redo)
        act(
            "columns", "Columns...", self.choose_columns, None, "Choose the columns, their order and headings"
        )
        act(
            "up", "Move Up", lambda: self.move(-1), "Ctrl+Up", "Move the row selected above the one before it"
        )
        act(
            "down",
            "Move Down",
            lambda: self.move(1),
            "Ctrl+Down",
            "Move the row selected below the one after it",
        )
        act("hide", "Hide Row", self.hide_row, None, "Leave the row selected out, with the rows under it")
        act("unhide", "Show Hidden Rows", self.show_hidden, None, "Bring back every row left out")
        act("reset", "Reset Cell", self.reset_cell, None, "Put back the text the BOM gives this cell")
        for key in ("save", "export", "columns", "up", "down", "hide", "unhide", "reset", "undo", "redo"):
            bar.addAction(a[key])
            if key in ("export", "columns", "unhide"):
                bar.addSeparator()
        self.undo_stack.indexChanged.connect(self._update_actions)

    # ----------------------------------------------------------------- the table
    def bom(self) -> Mapping[str, Any]:
        return self.boms[self.spec.type]

    def _set_spec(self, new: BomTableSpec) -> None:
        self.spec = new
        self._show()
        self.changed.emit()

    def _edit(self, new: BomTableSpec, text: str) -> None:
        if new != self.spec:
            self.undo_stack.push(_Change(self, self.spec, new, text))

    def _show(self) -> None:
        self.shown = apply(self.spec, self.bom())
        self.type.setCurrentIndex(max(0, self.type.findData(self.spec.type)))
        cols = self.shown.columns
        self._filling = True
        try:
            self.table.clear()
            self.table.setColumnCount(len(cols))
            self.table.setHorizontalHeaderLabels([c.heading for c in cols])
            self.table.setRowCount(len(self.shown.rows))
            italic = QFont()
            italic.setItalic(True)
            for r, row in enumerate(self.shown.rows):
                for c, text in enumerate(row.cells):
                    item = QTableWidgetItem(text)
                    if cols[c].id == "item":
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if cols[c].numeric:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    if row.overridden[c]:
                        item.setFont(italic)
                        item.setBackground(QBrush(EDITED_GROUND))
                        was = apply(_without(self.spec, row.key, cols[c].id), self.bom()).rows[r].cells[c]
                        item.setToolTip(tip(f"Edited. The BOM gives: {was or '(empty)'}"))
                    self.table.setItem(r, c, item)
            self.table.resizeColumnsToContents()
        finally:
            self._filling = False
        n = len(self.shown.unused)
        self.unused.setText(f"{plural(n, 'edit')} no longer {'applies' if n == 1 else 'apply'}" if n else "")
        self.forget.setVisible(bool(n))
        self._update_actions()

    def _selected(self) -> int | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return rows[0].row() if rows else None

    def _update_actions(self, *_: Any) -> None:
        a = self.actions_by_name
        r = self._selected()
        cell = self.table.currentItem()
        a["undo"].setEnabled(self.undo_stack.canUndo())
        a["redo"].setEnabled(self.undo_stack.canRedo())
        a["up"].setEnabled(r is not None and self._sibling(r, -1) is not None)
        a["down"].setEnabled(r is not None and self._sibling(r, 1) is not None)
        a["hide"].setEnabled(r is not None)
        a["unhide"].setEnabled(bool(self.spec.hidden))
        a["reset"].setEnabled(
            cell is not None
            and self.shown is not None
            and self.shown.rows[cell.row()].overridden[cell.column()]
        )

    def _update_title(self, *_: Any) -> None:
        name = os.path.basename(self.path) if self.path else os.path.basename(self.assembly)
        mark = "" if self.undo_stack.isClean() else "*"
        config = f" ({self.configuration})" if self.configuration else ""
        self.setWindowTitle(f"{mark}{name}{config} - BOM - SolidSeas")

    def _set_type(self, bom_type: str) -> None:
        self._edit(replace(self.spec, type=bom_type), "Change Type")

    # ----------------------------------------------------------------- edits
    def _typed(self, item: QTableWidgetItem) -> None:
        if self._filling or self.shown is None:
            return
        row, col = self.shown.rows[item.row()], self.shown.columns[item.column()]
        text = item.text()
        given = apply(_without(self.spec, row.key, col.id), self.bom()).rows[item.row()].cells[item.column()]
        overrides = dict(self.spec.overrides)
        if text == given:
            overrides.pop((row.key, col.id), None)
        else:
            overrides[(row.key, col.id)] = text
        try:
            new = spec(
                self.spec.type,
                self.spec.columns,
                order=self.spec.order,
                hidden=self.spec.hidden,
                overrides=overrides,
            )
        except SolidSeasError as exc:
            self.warn("Edit Cell", str(exc))
            self._show()
            return
        self._edit(new, "Edit Cell")

    def reset_cell(self) -> None:
        cell = self.table.currentItem()
        if cell is None or self.shown is None:
            return
        row, col = self.shown.rows[cell.row()], self.shown.columns[cell.column()]
        self._edit(_without(self.spec, row.key, col.id), "Reset Cell")

    def _siblings(self, r: int) -> list[int]:
        """The rows shown beside row ``r``: those with its parent."""
        assert self.shown is not None
        parent = self.shown.rows[r].row.parent if self.spec.type == "indented" else None
        return [
            i
            for i, x in enumerate(self.shown.rows)
            if (x.row.parent if self.spec.type == "indented" else None) == parent
        ]

    def _sibling(self, r: int, step: int) -> int | None:
        if self.shown is None or not 0 <= r < len(self.shown.rows):
            return None
        group = self._siblings(r)
        at = group.index(r) + step
        return group[at] if 0 <= at < len(group) else None

    def move(self, step: int) -> None:
        r = self._selected()
        if r is None or self.shown is None:
            return
        other = self._sibling(r, step)
        if other is None:
            return
        group = [self.shown.rows[i].key for i in self._siblings(r)]
        a, b = group.index(self.shown.rows[r].key), group.index(self.shown.rows[other].key)
        group[a], group[b] = group[b], group[a]
        rest = [k for k in self.spec.order if k not in group]
        self._edit(replace(self.spec, order=tuple(rest + group)), "Move Row")
        moved = next(i for i, x in enumerate(self.shown.rows) if x.key == group[b])
        self.table.selectRow(moved)

    def hide_row(self) -> None:
        r = self._selected()
        if r is None or self.shown is None:
            return
        self._edit(replace(self.spec, hidden=(*self.spec.hidden, self.shown.rows[r].key)), "Hide Row")

    def show_hidden(self) -> None:
        self._edit(replace(self.spec, hidden=()), "Show Hidden Rows")

    def forget_unused(self) -> None:
        if self.shown is None:
            return
        gone = set(self.shown.unused)
        kept = {k: v for k, v in self.spec.overrides.items() if k not in gone}
        self._edit(replace(self.spec, overrides=kept), "Remove Edits")

    def choose_columns(self, dialog: ColumnsDialog | None = None) -> None:
        names = []
        for data in self.boms.values():
            names += [n for n in property_names(data) if n not in names]
        if dialog is None:  # a test hands in one it has answered already
            dialog = ColumnsDialog(self, self.spec.columns, names)
            dialog.exec()
        if dialog.result() != QDialog.DialogCode.Accepted:
            return
        try:
            new = spec(
                self.spec.type,
                dialog.columns(),
                order=self.spec.order,
                hidden=self.spec.hidden,
                overrides=self.spec.overrides,
            )
        except SolidSeasError as exc:
            self.warn("Columns", str(exc))
            return
        self._edit(new, "Change Columns")

    # ----------------------------------------------------------------- files
    def _ask_path(self, title: str, start: str, filters: str) -> str:
        chosen, _f = QFileDialog.getSaveFileName(self, title, start, filters)
        return chosen

    def apply(self) -> None:
        self.applied.emit(self.spec)
        self.undo_stack.setClean()

    def save(self) -> bool:
        if self.path is None:
            return self.save_as()
        return self._save_to(self.path, self.sha256)

    def save_as(self) -> bool:
        start = os.path.splitext(self.path or self.assembly)[0] + bomfile.EXTENSION
        chosen = self.ask_path("Save BOM As", start, f"SolidSeas BOM (*{bomfile.EXTENSION})")
        if not chosen:
            return False
        if not chosen.lower().endswith(bomfile.EXTENSION):
            chosen += bomfile.EXTENSION
        replaces = (
            self.sha256 if self.path and os.path.normcase(chosen) == os.path.normcase(self.path) else None
        )
        return self._save_to(chosen, replaces)

    def _save_to(self, path: str, replaces: str | None) -> bool:
        assert self.shown is not None
        made = bomfile.make(path, self.assembly, self.configuration, self.shown, self.spec)
        try:
            saved = bomfile.save(made, path, replaces=replaces)
        except (SolidSeasError, OSError) as exc:
            self.warn("Save BOM", f"The BOM was not saved: {exc}")
            return False
        self.path, self.sha256 = saved.path, saved.sha256
        self.undo_stack.setClean()
        self._update_title()
        self.statusBar().showMessage(f"Saved {os.path.basename(saved.path)}", 5000)
        return True

    def export(self) -> str | None:
        assert self.shown is not None
        base = os.path.splitext(self.path or self.assembly)[0] + " BOM"
        chosen = self.ask_path("Export BOM", base + ".xlsx", ";;".join(f for _k, f in EXPORTS))
        if not chosen:
            return None
        kind = os.path.splitext(chosen)[1].lower().lstrip(".")
        if kind not in dict(EXPORTS):
            self.warn("Export BOM", "Choose a .csv, .xlsx or .pdf file name.")
            return None
        name = os.path.splitext(os.path.basename(self.assembly))[0]
        title = f"BILL OF MATERIALS - {name}" + (f" ({self.configuration})" if self.configuration else "")
        problems: tuple[str, ...] = ()
        if kind == "csv":
            data = bomexport.csv_bytes(self.shown)
        elif kind == "xlsx":
            data = bomexport.xlsx_bytes(self.shown, name)
        else:
            out = bomexport.pdf_bytes(self.shown, title)
            data, problems = out.data, out.problems
        from solidseas.export import write_new

        try:
            # the save dialog has asked before a file there is replaced
            written, _size = write_new(chosen, lambda fh: fh.write(data), overwrite=True)
        except (SolidSeasError, OSError) as exc:
            self.warn("Export BOM", f"Nothing was written: {exc}")
            return None
        note = f" ({'; '.join(problems)})" if problems else ""
        self.statusBar().showMessage(f"Exported {os.path.basename(written)}{note}", 8000)
        return written

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt's name)
        if self.undo_stack.isClean():
            event.accept()
            return
        answer = QMessageBox.question(
            self,
            "BOM",
            "Save the changes to this BOM?"
            if not self.apply_to_drawing
            else "Apply the changes to the drawing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            event.ignore()
            return
        if answer == QMessageBox.StandardButton.Save:
            if self.apply_to_drawing:
                self.apply()
            elif not self.save():
                event.ignore()
                return
        event.accept()


def _without(table_spec: BomTableSpec, key: str, column_id: str) -> BomTableSpec:
    overrides = {k: v for k, v in table_spec.overrides.items() if k != (key, column_id)}
    return replace(table_spec, overrides=overrides)


__all__ = ["EXPORTS", "BomEditor", "ColumnsDialog"]
