"""Right-click menus that show their status tips in the window's status bar.

Qt sends the status tip of a hovered menu entry to the menu at the top of the
chain that opened it, and from there up the parents only as far as the first
window. A menu of the menu bar starts that chain at the bar, inside the main
window, so its tips reach the status bar. A right-click menu is a popup window
of its own, so they stop at the menu. :func:`relay_status_tips` passes them on
to the widget the menu belongs to, from where they reach the window's status
bar as the menu bar's do, and clears the bar when the menu closes.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QStatusTipEvent
from PySide6.QtWidgets import QApplication, QMenu


class _Relay(QObject):
    def __init__(self, menu: QMenu) -> None:
        super().__init__(menu)
        self.menu = menu
        menu.installEventFilter(self)
        menu.aboutToHide.connect(lambda: self._send(""))

    def _send(self, text: str) -> None:
        owner = self.menu.parentWidget()
        if owner is not None:
            QApplication.sendEvent(owner, QStatusTipEvent(text))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.menu and event.type() == QEvent.Type.StatusTip:
            self._send(event.tip())
            return True
        return False


def relay_status_tips(menu: QMenu) -> QMenu:
    """Pass the status tips of ``menu``'s entries, its submenus' included, to the
    widget it belongs to; returns ``menu``."""
    _Relay(menu)
    return menu


__all__ = ["relay_status_tips"]
