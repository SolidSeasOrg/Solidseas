"""The PDM menu's Library of Common Parts window and the Check Project copies.

**PDM > Library of Common Parts...** opens a window over the library's common parts
(``Vault.library``, ``docs/PDM.md`` 6), with two tabs:

* **Items**: every library item with its number, description, file, versions, the
  projects using it and whether any copy is behind, with a search box. Use in Project
  copies the item into a project (``Library.use``, never over a file), Show Copies lists
  the projects using it and the state of each copy, Update Copies brings the copies
  that are behind up to date (``Library.update``; a copy edited in its project only
  after a confirmation), and Add to Library makes the file selected in the list an item
  (``Library.add``).
* **Candidates**: the parts shared by two or more projects, most widely shared first
  (``Library.candidates``), each of which Add to Library makes an item.

The Check Project window's **Make Copies...** shows ``plan_copies``' list and, after a
confirmation, makes those copies (``Library.fix``) and checks the project again.

Every read and write runs in a worker thread of :class:`.PdmController`'s pool; the
windows here only show results and take input.
"""

import os
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .wording import error_message, plural, tip

LIBRARY_TEXT = "&Library of Common Parts..."
LIBRARY_TIP = (
    "The parts kept once in the library's Library folder, with item numbers, which projects copy from"
)
ADD_TIP = (
    "Copy this file into the library's Library folder as a common part with an item number. "
    "The file itself is not changed"
)
USE_TIP = (
    "Copy the item into a project, where SOLIDWORKS finds it. A file of that name already in the "
    "project is never replaced"
)
SHOW_TIP = "List the projects that have a copy of the item, and whether each copy is up to date"
UPDATE_TIP = (
    "Bring the copies that are behind up to date with the library's version. Each copy is kept as a "
    "version first"
)
MAKE_COPIES_TIP = (
    "Copy the files found outside the project into it, so it holds everything its documents use. "
    "Each copy is a new file"
)

# Plain sentences for the refusals a person can run into here.
RULE_WORDS = {
    "exists": (
        "A file of that name is already there, and a copy never replaces a file, so nothing was copied."
    ),
    "item_exists": "A library item already has that number. Choose another, or leave it empty.",
    "already_an_item": "The file is already a library item.",
    "not_tracked": "Only CAD files, and drawings' PDF and DXF exports, can be library items.",
    "edited": "The copy was edited in its project, so it was left as it is.",
    "not_linked": "The project has no copy of that item.",
    "file_changing": "The copy changed while it was being updated. Save it, then try again.",
}


def problem_text(error: dict[str, Any] | None) -> str:
    """One refusal in a sentence, or the full error message for anything else."""
    rule = ((error or {}).get("detail") or {}).get("rule")
    return RULE_WORDS.get(rule) or error_message(error)


# --------------------------------------------------------------------------- work, off the UI thread
def library_work(root: str):
    """A Job's work: the items, every copy of them, and the projects of the library."""

    def work(_emit, _cancelled) -> dict[str, Any]:
        from solidseas import pdm

        vault = pdm.open(root)
        lib = vault.library
        listing = lib.list()
        links = lib.updates(all_links=True)["links"]
        projects = [p.path for p in vault.projects() if not p.archived]
        return {
            "ok": True,
            "kind": "library",
            "library": vault.root,
            "section": listing["section"],
            "items": listing["items"],
            "links": links,
            "projects": projects,
        }

    return work


def candidates_work(root: str):
    def work(_emit, _cancelled) -> dict[str, Any]:
        from solidseas import pdm

        vault = pdm.open(root)
        return {"ok": True, "kind": "candidates", "library": vault.root, "data": vault.library.candidates()}

    return work


def add_work(path: str, item: str | None, description: str):
    def work(_emit, _cancelled) -> dict[str, Any]:
        from solidseas import pdm

        vault = pdm.open(path)
        data = vault.library.add(path, item, description)
        return {"ok": True, "kind": "library_add", "path": path, "data": data}

    return work


def use_work(root: str, item: str, project: str, to: str | None):
    def work(_emit, _cancelled) -> dict[str, Any]:
        from solidseas import pdm

        vault = pdm.open(root)
        data = vault.library.use(item, vault.absolute(project), to)
        return {"ok": True, "kind": "library_use", "data": data}

    return work


def update_work(root: str, item: str, projects: list[tuple[str, bool]]):
    """A Job's work: ``Library.update`` of the item in each project, with ``force`` for
    the projects whose edited copies the person agreed to replace. One project's
    refusal does not stop the others."""

    def work(_emit, _cancelled) -> dict[str, Any]:
        from solidseas import model, pdm

        vault = pdm.open(root)
        lib = vault.library
        done = []
        for project, force in projects:
            try:
                data = lib.update(vault.absolute(project), item, force=force)
                done.append({"project": project, "ok": True, "data": data})
            except Exception as exc:
                done.append({"project": project, "ok": False, "error": model.error_info(exc)})
        return {"ok": True, "kind": "library_update", "item": item, "done": done}

    return work


def fix_work(folder: str, plan):
    """A Job's work: the copies of ``plan`` made in the project at ``folder``, then the
    project checked again."""

    def work(_emit, _cancelled) -> dict[str, Any]:
        from pathlib import Path

        from solidseas import pdm
        from solidseas.pdm.check import check_project, plan_copies

        vault = pdm.open(folder)
        proj = vault.project_of(folder)
        if proj is None:
            return {"ok": True, "kind": "check", "project": None, "result": None}
        done = vault.library.fix(proj, plan)
        section = vault.library.section_path
        library = Path(section) if os.path.isdir(section) else None
        result = check_project(Path(folder), library=library)
        return {
            "ok": True,
            "kind": "check",
            "project": folder,
            "name": proj.path,
            "result": result,
            "plan": plan_copies(result),
            "items": item_paths(vault),
            "fix": done,
        }

    return work


def item_paths(vault) -> dict[str, str]:
    """Each library item's number by its file's full path (normalised)."""
    return {os.path.normcase(vault.absolute(i.path)): i.id for i in vault.library.items()}


# --------------------------------------------------------------------------- words
def copy_state(row: dict[str, Any]) -> str:
    """One copy's state in words: unchanged, edited, gone or behind."""
    if row["copy"] == "gone":
        return "Gone from the project"
    behind = ""
    if row["behind"]:
        have = f"v{row['number']}" if row.get("number") else "an older version"
        newest = f"v{row['newest_number']}" if row.get("newest_number") else "a newer version"
        behind = f"Behind: the copy is {have}, the library has {newest}"
    if row["copy"] == "edited":
        return "Edited in the project" + (f". {behind}" if behind else "")
    return behind or "Unchanged"


def versions_text(row: dict[str, Any]) -> str:
    if not row["exists"]:
        return "File gone"
    number = (row.get("version") or {}).get("number")
    text = str(number) if number else "None"
    return text if row["stored"] else text + ", changed since"


def plan_rows(plan, project: str, items: dict[str, str]) -> list[tuple[str, list[list[str]]]]:
    """A copy plan as the window's groups: the copies to make, the ones that cannot be
    made and the files already in place, each row the source, the destination below the
    project and why."""
    from .pdmaction import PLACE_WORDS

    def rel(p) -> str:
        return os.path.relpath(str(p), project)

    def users(c) -> str:
        names = [os.path.basename(str(p)) for p in c.referenced_by]
        return "Used by " + ", ".join(names) if names else ""

    def why(c) -> str:
        words = [users(c)]
        place = PLACE_WORDS.get(c.place or "")
        if place:
            words.append("found " + place)
        item = items.get(os.path.normcase(str(c.source)))
        if item:
            words.append(f"library item {item}")
        return "; ".join(w for w in words if w)

    out = []
    if plan.copies:
        out.append(("copies", [[str(c.source), rel(c.destination), why(c)] for c in plan.copies]))
    if plan.conflicts:
        out.append(
            (
                "conflicts",
                [
                    [str(c.source), rel(c.destination), f"{c.reason[:1].upper()}{c.reason[1:]}. {users(c)}"]
                    for c in plan.conflicts
                ],
            )
        )
    if plan.present:
        out.append(("present", [[str(c.source), rel(c.destination), why(c)] for c in plan.present]))
    return out


PLAN_WORDS = {
    "copies": "Copies to make",
    "conflicts": "Cannot be copied",
    "present": "Already in the project",
}


def fix_line(fix: dict[str, Any]) -> str:
    made = len(fix["copied"])
    text = f"Made {plural(made, 'copy', 'copies')} in the project." if made else "No copy was made."
    if fix["failed"]:
        text += f" {plural(len(fix['failed']), 'copy', 'copies')} could not be made: " + "; ".join(
            f"{os.path.basename(f['destination'])} ({f['message']})" for f in fix["failed"]
        )
        text += "."
    return text


# --------------------------------------------------------------------------- the windows
def _tree(headers: list[str]) -> QTreeWidget:
    tree = QTreeWidget()
    tree.setColumnCount(len(headers))
    tree.setHeaderLabels(headers)
    tree.setRootIsDecorated(False)
    tree.setUniformRowHeights(True)
    tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
    tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    return tree


def _label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


def _button(text: str, tip_text: str) -> QPushButton:
    b = QPushButton(text)
    b.setToolTip(tip(tip_text))
    b.setEnabled(False)
    return b


class LibraryDialog(QDialog):
    """PDM > Library of Common Parts: the items and the candidates (see the module
    notes). :class:`.PdmController` fills it and runs its buttons."""

    def __init__(self, parent: QWidget, library: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Library of Common Parts: {os.path.basename(library) or library}")
        self.library = library
        self.data: dict[str, Any] | None = None
        self.candidates: list[dict[str, Any]] | None = None
        self.tabs = QTabWidget()

        # Items
        page = QWidget()
        self.line = _label("Reading the library...")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by item number, description or file")
        self.search.setClearButtonEnabled(True)
        self.items = _tree(["Item", "Description", "File", "Versions", "Projects", "Behind"])
        self.use_button = _button("Use in Project...", USE_TIP)
        self.show_button = _button("Show Copies", SHOW_TIP)
        self.update_button = _button("Update Copies...", UPDATE_TIP)
        self.add_button = _button("Add to Library...", ADD_TIP)
        self.add_button.setEnabled(True)  # the file selected in the list; it says when there is none
        row = QHBoxLayout()
        for b in (self.use_button, self.show_button, self.update_button):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.add_button)
        self.copies_line = _label("")
        self.copies = _tree(["Project", "Copy", "State"])
        self.copies.hide()
        layout = QVBoxLayout(page)
        layout.addWidget(self.line)
        layout.addWidget(self.search)
        layout.addWidget(self.items, 2)
        layout.addLayout(row)
        layout.addWidget(self.copies_line)
        layout.addWidget(self.copies, 1)
        self.tabs.addTab(page, "Items")

        # Candidates
        page = QWidget()
        self.candidates_line = _label(
            "Parts and assemblies whose identical content sits in two or more projects, the most widely "
            "shared first."
        )
        self.candidates_tree = _tree(["Part", "Projects", "Copies", "Where"])
        self.candidate_button = _button(
            "Add to Library...", "Make this part a library item, from its first copy. No project file changes"
        )
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.candidate_button)
        layout = QVBoxLayout(page)
        layout.addWidget(self.candidates_line)
        layout.addWidget(self.candidates_tree, 1)
        layout.addLayout(row)
        self.tabs.addTab(page, "Candidates")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        outer = QVBoxLayout(self)
        outer.addWidget(self.tabs, 1)
        outer.addWidget(buttons)
        self.search.textChanged.connect(self._filter)
        self.items.currentItemChanged.connect(lambda *_a: self._update())
        self.candidates_tree.currentItemChanged.connect(
            lambda *_a: self.candidate_button.setEnabled(self.chosen_candidate() is not None)
        )
        self.resize(900, 600)

    # -- items ---------------------------------------------------------------------------
    def show_result(self, result: dict[str, Any]) -> None:
        chosen = self.chosen_item()
        self.items.clear()
        if not result.get("ok"):
            self.data = None
            self.line.setText("The library could not be read. " + error_message(result.get("error")))
            self._update()
            return
        self.data = result
        rows = result["items"]
        for r in rows:
            behind = self.behind(r["item"])
            item = QTreeWidgetItem(
                [
                    r["item"],
                    r["description"],
                    r["path"],
                    versions_text(r),
                    f"{r['projects']:,}",
                    f"{behind:,} of {r['copies']:,} copies" if behind else "No",
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, r["item"])
            item.setToolTip(2, tip(os.path.join(self.library, *r["path"].split("/"))))
            if r["description"]:
                item.setToolTip(1, tip(r["description"]))
            self.items.addTopLevelItem(item)
            if chosen is not None and r["item"] == chosen["item"]:
                self.items.setCurrentItem(item)
        if rows:
            behind = sum(1 for r in rows if self.behind(r["item"]))
            text = f"{plural(len(rows), 'item')} in the {result['section']} folder."
            if behind:
                text += f" {plural(behind, 'item has', 'items have')} copies that are behind."
        else:
            text = (
                "The library has no items yet. Add to Library makes the file selected in the list one, "
                "and the Candidates tab lists parts that several projects share."
            )
        self.line.setText(text)
        for c in range(6):
            self.items.resizeColumnToContents(c)
        self._filter(self.search.text())
        self._update()

    def links_of(self, ident: str) -> list[dict[str, Any]]:
        if self.data is None:
            return []
        return [r for r in self.data["links"] if r["item"].casefold() == ident.casefold()]

    def behind(self, ident: str) -> int:
        return sum(1 for r in self.links_of(ident) if r["behind"])

    def chosen_item(self) -> dict[str, Any] | None:
        current = self.items.currentItem()
        if current is None or self.data is None or current.isHidden():
            return None
        ident = current.data(0, Qt.ItemDataRole.UserRole)
        return next((r for r in self.data["items"] if r["item"] == ident), None)

    def choose(self, ident: str) -> bool:
        for i in range(self.items.topLevelItemCount()):
            item = self.items.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == ident:
                self.items.setCurrentItem(item)
                return True
        return False

    def _filter(self, text: str) -> None:
        words = text.casefold().split()
        for i in range(self.items.topLevelItemCount()):
            item = self.items.topLevelItem(i)
            hay = " ".join(item.text(c) for c in range(3)).casefold()
            item.setHidden(not all(w in hay for w in words))
        self._update()

    def _update(self) -> None:
        row = self.chosen_item()
        self.use_button.setEnabled(
            row is not None and row["exists"] and bool(self.data and self.data["projects"])
        )
        self.show_button.setEnabled(row is not None)
        self.update_button.setEnabled(row is not None and self.behind(row["item"]) > 0)

    def show_copies(self, ident: str) -> None:
        links = self.links_of(ident)
        self.copies.clear()
        self.copies.show()
        if not links:
            self.copies_line.setText(f"No project has a copy of {ident}.")
            return
        projects = {r["project"] for r in links}
        self.copies_line.setText(
            f"{ident} is copied into {plural(len(projects), 'project')} "
            f"({plural(len(links), 'copy', 'copies')}):"
        )
        for r in links:
            item = QTreeWidgetItem([r["project"], r["path"], copy_state(r)])
            item.setToolTip(1, tip(os.path.join(self.library, *r["path"].split("/"))))
            item.setToolTip(2, tip(copy_state(r)))
            self.copies.addTopLevelItem(item)
        for c in range(3):
            self.copies.resizeColumnToContents(c)

    # -- candidates ----------------------------------------------------------------------
    def show_candidates(self, result: dict[str, Any]) -> None:
        self.candidates_tree.clear()
        if not result.get("ok"):
            self.candidates = None
            self.candidates_line.setText(
                "The candidates could not be found. " + error_message(result.get("error"))
            )
            return
        data = result["data"]
        self.candidates = data["candidates"]
        for n, r in enumerate(self.candidates):
            where = ", ".join(sorted({c["project"] for c in r["copies"]}, key=str.casefold))
            item = QTreeWidgetItem([r["name"], f"{r['projects']:,}", f"{len(r['copies']):,}", where])
            item.setData(0, Qt.ItemDataRole.UserRole, n)
            item.setToolTip(0, tip("\n".join(c["path"] for c in r["copies"])))
            item.setToolTip(3, tip(where))
            self.candidates_tree.addTopLevelItem(item)
        if self.candidates:
            self.candidates_line.setText(
                f"{plural(len(self.candidates), 'part sits', 'parts sit')} in two or more projects "
                "with the same content, the most widely shared first "
                f"({plural(data['documents'], 'document')} looked at)."
            )
        else:
            self.candidates_line.setText(
                f"No part sits in two or more projects with the same content "
                f"({plural(data['documents'], 'document')} looked at)."
            )
        for c in range(4):
            self.candidates_tree.resizeColumnToContents(c)
        self.candidate_button.setEnabled(self.chosen_candidate() is not None)

    def chosen_candidate(self) -> dict[str, Any] | None:
        current = self.candidates_tree.currentItem()
        if current is None or not self.candidates:
            return None
        n = current.data(0, Qt.ItemDataRole.UserRole)
        return self.candidates[n] if isinstance(n, int) and n < len(self.candidates) else None


class UseDialog(QDialog):
    """Use in Project: the project, an optional folder inside it, and what happens."""

    def __init__(self, parent: QWidget, row: dict[str, Any], projects: list[str], chosen: str | None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Use {row['item']} in a Project")
        self.row = row
        name = row["path"].rsplit("/", 1)[-1]
        number = (row.get("version") or {}).get("number")
        what = f"{row['item']}" + (f" v{number}" if number else "") + f" ({name})"
        self.line = _label(
            f"Copies {what} into the project's top folder, where SOLIDWORKS finds it from any folder below, "
            "or into the folder you name. A file of that name already in the project is never replaced. "
            "In SOLIDWORKS, insert the part from the project's copy."
        )
        self.project = QComboBox()
        self.project.addItems(projects)
        if chosen in projects:
            self.project.setCurrentIndex(projects.index(chosen))
        self.to = QLineEdit()
        self.to.setPlaceholderText("Optional, such as parts\\hardware")
        form = QFormLayout()
        form.addRow("Project", self.project)
        form.addRow("Folder in it", self.to)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.ok = self.buttons.addButton("Copy Into Project", QDialogButtonBox.ButtonRole.AcceptRole)
        self.ok.setEnabled(bool(projects))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.line)
        layout.addLayout(form)
        layout.addWidget(self.buttons)
        self.resize(520, 200)

    def values(self) -> tuple[str, str | None]:
        return self.project.currentText(), self.to.text().strip() or None


class AddDialog(QDialog):
    """Add to Library: the item number (optional) and the description."""

    def __init__(self, parent: QWidget, path: str, section: str, in_section: bool) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add to Library")
        self.path = path
        name = os.path.basename(path)
        if in_section:
            text = f"Makes {name} a library item where it is, and keeps its first version."
        else:
            text = (
                f"Copies {name} into the library's {section} folder as a library item and keeps its first "
                f"version. {name} itself is not changed, and a file of that name already in {section} is "
                "never replaced."
            )
        self.line = _label(text)
        self.item = QLineEdit()
        self.item.setMaxLength(40)
        self.item.setPlaceholderText("Optional: the next number, such as SS-00001, when empty")
        self.description = QLineEdit()
        self.description.setPlaceholderText("Such as M6 x 20 bolt")
        form = QFormLayout()
        form.addRow("Item number", self.item)
        form.addRow("Description", self.description)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.ok = self.buttons.addButton("Add to Library", QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.line)
        layout.addLayout(form)
        layout.addWidget(self.buttons)
        self.resize(520, 180)

    def values(self) -> tuple[str | None, str]:
        return self.item.text().strip() or None, " ".join(self.description.text().split())


class PlanDialog(QDialog):
    """Check Project > Make Copies: the copies that would make the project
    self-contained, the ones that cannot be made and why, and the files already there."""

    def __init__(self, parent: QWidget, name: str, plan, project: str, items: dict[str, str]) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Make Copies: {name}")
        self.plan = plan
        n = len(plan.copies)
        if n:
            text = (
                f"{plural(n, 'file')} found outside the project can be copied into it. Each copy goes into "
                "the deepest folder that holds every document using it, so SOLIDWORKS finds it from each "
                "of them. Each copy is a new file: nothing in the project is replaced, and the documents "
                "themselves are not changed."
            )
        else:
            text = "There is nothing to copy."
        if plan.conflicts:
            text += (
                f" {plural(len(plan.conflicts), 'file')} cannot be copied, because the folder already has "
                "another file of that name or another copy takes it. Open the assembly in SOLIDWORKS to "
                "sort those out."
            )
        self.line = _label(text)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["File", "Copied to", "Why"])
        self.tree.setUniformRowHeights(True)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        for kind, rows in plan_rows(plan, project, items):
            top = QTreeWidgetItem([f"{PLAN_WORDS[kind]} ({len(rows):,})", "", ""])
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            self.tree.addTopLevelItem(top)
            for r in rows:
                item = QTreeWidgetItem(top, r)
                for c, t in enumerate(r):
                    item.setToolTip(c, tip(t))
            top.setExpanded(kind != "present")
        for c in range(3):
            self.tree.resizeColumnToContents(c)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.ok = self.buttons.addButton(
            f"Make {plural(n, 'Copy', 'Copies')}" if n else "Make Copies",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.ok.setEnabled(n > 0)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.line)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.buttons)
        self.resize(860, 420)


__all__ = [
    "AddDialog",
    "LibraryDialog",
    "PlanDialog",
    "UseDialog",
    "copy_state",
    "plan_rows",
    "problem_text",
]
