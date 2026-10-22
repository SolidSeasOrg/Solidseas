"""Settings: every setting SolidSeas has, in one window, with its pages listed on the left.

The pages, in order:

* **General**: the document list, what happens at start, the folders' indexes and where a
  referenced file is looked for (Preferences).
* **3D View**: the interactive 3D view, its mesh limit, and the mouse and keys (Preferences).
* **3D Print**: printing from the shown folder or as is, and the program and format 3D
  Print uses (Preferences).
* **Drawings**: drawings on or off (Preferences), and under it each page of Drawing Settings
  (:mod:`.drawingsettings`).
* **AI Assistant**: the AI provider, model, key and limits (the AI settings page).
* **Extensions**: what is added and switched on, each one's Details and Settings
  (:mod:`.extensionsdialog`; its changes take effect at once, as before).

Drawings, the AI Assistant and the Extensions are experimental: each of their pages starts
with the note of :mod:`.experimental` saying what that means.

Each area keeps its own page and its own way of saving: the dialogs that showed them are
hosted here with their buttons hidden. OK and Apply save every area (Preferences through
the window's ``apply_settings``, Drawing Settings to ``Drawing.json``, the AI settings to
their file and the key store); an area that refuses a value saves nothing of its own,
shows its page and says why, and OK then leaves the window open. Restore Defaults restores
the page shown. Cancel saves nothing more.

The window's Settings menu opens it with :func:`open_settings`, on the page asked for:
Preferences on General, AI Settings on AI Assistant, Drawing Settings on Drawings and
Tools > Extensions on Extensions.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import experimental

TITLE = "Settings"
GENERAL, VIEW_3D, PRINT, DRAWINGS, AI, EXTENSIONS = (
    "General",
    "3D View",
    "3D Print",
    "Drawings",
    "AI Assistant",
    "Extensions",
)
PAGES = (GENERAL, VIEW_3D, PRINT, DRAWINGS, AI, EXTENSIONS)
_ROLE = Qt.ItemDataRole.UserRole


def _embedded(dialog: QDialog) -> QDialog:
    """``dialog`` shown inside the Settings window rather than as a window of its own."""
    dialog.setWindowFlags(Qt.WindowType.Widget)
    buttons = getattr(dialog, "buttons", None)
    if buttons is not None:
        buttons.hide()
    return dialog


def _scrolled(widget: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setWidget(widget)
    return area


def _page(*widgets: QWidget, note: str | None = None, first: str | None = None) -> QScrollArea:
    """A page of ``widgets``, with ``first`` (an experimental note) above them and ``note``
    below."""
    page = QWidget()
    layout = QVBoxLayout(page)
    if first:
        layout.addWidget(experimental.note_label(first))
    for w in widgets:
        layout.addWidget(w)
        w.show()  # a group its dialog keeps hidden when shown on its own
    if note:
        label = QLabel(note)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        layout.addWidget(label)
    layout.addStretch(1)
    return _scrolled(page)


class SettingsWindow(QDialog):
    """The Settings window of ``window`` (see the module notes), on ``page`` (a title of
    :data:`PAGES`, or a Drawing Settings page's title). ``preferences``, ``drawings``,
    ``ai`` and ``extensions`` are the hosted dialogs, made from ``window`` when None (a
    test passes its own)."""

    def __init__(
        self,
        window: Any,
        *,
        page: str | None = None,
        preferences: Any = None,
        drawings: Any = None,
        ai: Any = None,
        extensions: Any = None,
    ) -> None:
        super().__init__(window)
        self.setWindowTitle(TITLE)
        self.resize(1040, 720)
        self.window_ = window
        self.preferences = preferences if preferences is not None else self._make_preferences()
        self.drawings = drawings if drawings is not None else self._make_drawings()
        self.ai = ai if ai is not None else self._make_ai()
        self.extensions = extensions if extensions is not None else self._make_extensions()

        self.nav = QTreeWidget()
        self.nav.setHeaderHidden(True)
        self.nav.setMaximumWidth(240)
        self.nav.setRootIsDecorated(True)
        self.stack = QStackedWidget()
        self._items: dict[str, QTreeWidgetItem] = {}
        self._drawing_pages: list[str] = []

        prefs = self.preferences
        self._add(GENERAL, _page(*prefs.sections["general"], prefs.where))
        self._add(VIEW_3D, _page(*prefs.sections["view3d"]))
        print_rows = prefs.sections["print"]
        self._add(PRINT, _page(*print_rows))
        # The Drawings page: drawings on or off, with what experimental means for them, above
        # Drawing Settings' own first page.
        drawings_page = QWidget()
        dl = QVBoxLayout(drawings_page)
        dl.setContentsMargins(0, 0, 0, 0)
        for w in prefs.sections["drawings"]:
            dl.addWidget(w)
            w.show()
        dl.addWidget(_embedded(self.drawings.dialog), 1)
        self._add(DRAWINGS, drawings_page)
        self.drawings.page_list.hide()
        self.drawings.buttons.hide()  # the wrapper's buttons; the window's OK and Apply save it
        from .drawingsettings import PAGES as DRAWING_PAGES

        for spec in DRAWING_PAGES:
            child = QTreeWidgetItem([spec.title])
            child.setData(0, _ROLE, (DRAWINGS, spec.title))
            self._items[f"{DRAWINGS}/{spec.title}"] = child
            self._items[DRAWINGS].addChild(child)
            self._drawing_pages.append(spec.title)
        self._add(AI, _page(_embedded(self.ai), first=experimental.assistant_note()))
        self._add(EXTENSIONS, _page(_embedded(self.extensions)))
        self.nav.expandItem(self._items[DRAWINGS])
        self.nav.currentItemChanged.connect(self._shown)

        self.error = QLabel("")
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setWordWrap(True)
        bold = self.error.font()
        bold.setBold(True)
        self.error.setFont(bold)
        self.error.hide()
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        self.buttons.accepted.connect(self.ok)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply)
        self.restore = self.buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults)
        self.restore.clicked.connect(self.restore_defaults)

        middle = QHBoxLayout()
        middle.addWidget(self.nav)
        middle.addWidget(self.stack, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(middle, 1)
        layout.addWidget(self.error)
        layout.addWidget(self.buttons)
        self.show_page(page or GENERAL)

    # ------------------------------------------------------------------ the hosted areas
    def _make_preferences(self) -> Any:
        from .preferences import PreferencesDialog

        w = self.window_
        dialog = PreferencesDialog(self, w.settings, w.store.path, **w.printer.preferences_options())
        dialog.applied.connect(w.apply_settings)
        dialog.print_format_chosen.connect(w.printer.set_format)
        return dialog

    def _make_drawings(self) -> Any:
        from .drawingsettings import DrawingSettingsDialog

        controller = self.window_.drawings
        return DrawingSettingsDialog(
            self, path=controller.settings_file(), on_saved=controller._settings_saved
        )

    def _make_ai(self) -> Any:
        from ..assistant.settings_dialog import AISettingsDialog

        dialog = AISettingsDialog(self, self.window_.ai_config())
        dialog.changed.connect(self.window_._ai_settings_changed)
        return dialog

    def _make_extensions(self) -> Any:
        from .extensionsdialog import ExtensionsDialog

        dialog = ExtensionsDialog(self)
        dialog.changed.connect(self.window_.extensions_changed)  # IGES and BREP follow at once
        return dialog

    def _add(self, title: str, widget: QWidget) -> int:
        index = self.stack.addWidget(widget)
        item = QTreeWidgetItem([title])
        item.setData(0, _ROLE, (title, None))
        self.nav.addTopLevelItem(item)
        self._items[title] = item
        return index

    # ------------------------------------------------------------------ pages
    def show_page(self, page: str) -> None:
        """Show ``page``: a title of :data:`PAGES`, or a Drawing Settings page's."""
        key = page if page in self._items else f"{DRAWINGS}/{page}"
        item = self._items.get(key)
        if item is None:
            raise ValueError(f"there is no settings page {page!r}")
        self.nav.setCurrentItem(item)
        self._shown(item)

    def current_page(self) -> str:
        item = self.nav.currentItem()
        area, sub = item.data(0, _ROLE) if item is not None else (GENERAL, None)
        return sub or area

    def _shown(self, item: QTreeWidgetItem | None, _previous: Any = None) -> None:
        if item is None:
            return
        area, sub = item.data(0, _ROLE)
        self.stack.setCurrentIndex(PAGES.index(area))  # the stack holds the areas in this order
        if area == DRAWINGS:
            self.drawings.show_page(sub or self._drawing_pages[0])
        self.restore.setEnabled(area in (GENERAL, VIEW_3D, PRINT, DRAWINGS))
        self.restore.setToolTip(
            "Restore the General, 3D View and 3D Print settings as they come"
            if area in (GENERAL, VIEW_3D, PRINT)
            else "Restore this page's settings as they come"
        )

    # ------------------------------------------------------------------ the buttons
    def restore_defaults(self) -> None:
        """The page shown back to the settings as they come."""
        area = self.nav.currentItem().data(0, _ROLE)[0]
        if area == DRAWINGS:
            self.drawings.restore_defaults()
        elif area in (GENERAL, VIEW_3D, PRINT):
            self.preferences.restore_defaults()

    def apply(self) -> bool:
        """Save every area (see the module notes); whether all were saved."""
        self.error.hide()
        self.preferences.apply()
        if not self.drawings.apply():
            self._refused(DRAWINGS, "Drawing Settings were not saved: see the page.")
            return False
        if not self.ai.save():
            self._refused(AI, "The AI settings were not saved: see the page.")
            return False
        return True

    def _refused(self, area: str, words: str) -> None:
        if area == DRAWINGS:
            refused = getattr(self.drawings, "refused", ())
            page = refused[0][0] if refused and refused[0][0] else None
            self.show_page(page or DRAWINGS)
        else:
            self.show_page(area)
        self.error.setText(words)
        self.error.show()

    def ok(self) -> None:
        if self.apply():
            self.accept()


def open_settings(window: Any, page: str | None = None) -> SettingsWindow:
    """The window's Settings, on ``page``: one at a time (``window.settings_window``),
    brought forward on that page when open already; it does not hold the window, so the
    assistant and the viewer stay usable beside it, and it is gone once closed."""
    dialog = getattr(window, "settings_window", None)
    if dialog is None:
        dialog = SettingsWindow(window, page=page)
        window.settings_window = dialog

        def closed(_result: int, d: SettingsWindow = dialog) -> None:
            if getattr(window, "settings_window", None) is d:
                window.settings_window = None
            d.deleteLater()

        dialog.finished.connect(closed)
        dialog.show()
    elif page is not None:
        dialog.show_page(page)
    dialog.raise_()
    dialog.activateWindow()
    return dialog


__all__ = [
    "AI",
    "DRAWINGS",
    "EXTENSIONS",
    "GENERAL",
    "PAGES",
    "PRINT",
    "TITLE",
    "VIEW_3D",
    "SettingsWindow",
    "open_settings",
]
