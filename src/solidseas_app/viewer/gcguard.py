"""Python's garbage collection on the GUI thread only.

Python collects cycles on whichever thread happens to allocate when a generation's count
passes its threshold. In the viewer that is often a worker reading a document, and a
cycle it frees may hold Qt objects (a dropped window, a model, a pixmap) whose C++ side
must be destroyed on the GUI thread: freed on a worker it can crash the program (an access
violation on Windows). :func:`install` turns automatic collection off and collects from a
timer on the GUI thread instead, by the same thresholds, so nothing is collected anywhere
else. A worker that makes many cycles only waits for the next tick to have them freed.

Nothing here runs without a QApplication. Installing again keeps the one timer and turns
automatic collection off again; it stays off when the application quits (Python's own
shutdown frees what is left).
"""

from __future__ import annotations

import gc

INTERVAL_MS = 500
_PROPERTY = "solidseas_gc_guard"


def collect_due() -> int:
    """Collect the oldest generation whose count has passed its threshold, as Python
    would; the generation collected, or -1 when none is due."""
    counts, thresholds = gc.get_count(), gc.get_threshold()
    due = -1
    for gen in range(min(len(counts), len(thresholds))):
        if thresholds[gen] and counts[gen] > thresholds[gen]:
            due = gen
    if due >= 0:
        gc.collect(due)
    return due


def install(app=None):
    """Collect on ``app``'s thread from now on (see the module notes); the timer, or None
    without an application."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    app = app or QApplication.instance()
    if app is None:
        return None
    gc.disable()  # each time: something may have turned it on again since
    timer = app.findChild(QTimer, _PROPERTY)
    if timer is None:
        timer = QTimer(app)
        timer.setObjectName(_PROPERTY)
        timer.setInterval(INTERVAL_MS)
        timer.timeout.connect(collect_due)
    if not timer.isActive():
        timer.start()
    return timer


__all__ = ["INTERVAL_MS", "collect_due", "install"]
