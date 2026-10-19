"""No window test waits forever on a dialog.

Offscreen, nobody can click a message box, so a test that reaches one it does not
answer (``show_message`` runs the box's own event loop) would wait until the run's
time-out. :func:`watch` starts a timer on the application that looks at the active
modal dialog twice a second: one left open longer than :data:`LIMIT_S` is closed and
named in :data:`left_open`, and ``conftest.py`` fails the test that opened it. A test
that answers its dialog, from a timer or another dialog's button, answers it long
before the limit. Nothing in Qt is replaced, so a dialog opened from C++ (the static
``QMessageBox.question``) is watched too.
"""

import time

LIMIT_S = 60.0  # how long a dialog may wait for an answer
CHECK_MS = 500
left_open: list[str] = []


def watch(app) -> None:
    """Start the watch on ``app``, a QApplication, once."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

    if not isinstance(app, QApplication) or app.property("solidseas_modal_watch"):
        return
    state: dict = {"widget": None, "since": 0.0}

    def check() -> None:
        widget = QApplication.activeModalWidget()
        now = time.monotonic()
        if widget is None or widget is not state["widget"]:
            state["widget"], state["since"] = widget, now
            return
        if now - state["since"] < LIMIT_S:
            return
        what = widget.windowTitle() or type(widget).__name__
        if isinstance(widget, QMessageBox) and widget.text():
            what = f"{what}: {widget.text()}"
        left_open.append(what)
        state["widget"] = None
        if isinstance(widget, QDialog):
            widget.reject()
        else:
            widget.close()

    timer = QTimer(app)
    timer.setInterval(CHECK_MS)
    timer.timeout.connect(check)
    timer.start()
    app.setProperty("solidseas_modal_watch", True)
