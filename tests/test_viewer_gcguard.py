"""Garbage collection on the GUI thread only (``solidseas_app.viewer.gcguard``)."""

import gc
import threading

import pytest

from test_viewer import _wait, needs_qt

pytestmark = needs_qt


@pytest.fixture
def qt():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_a_window_turns_collection_off_and_collects_on_its_own_thread(qt, tmp_path):
    from solidseas_app.viewer import gcguard
    from solidseas_app.viewer.settings import SettingsStore
    from solidseas_app.viewer.window import MainWindow

    w = MainWindow(SettingsStore(str(tmp_path / "Viewer.ini")))
    try:
        timer = gcguard.install(qt)
        assert timer is not None and timer.isActive() and gcguard.install(qt) is timer, "once"
        assert not gc.isenabled()
        gc.enable()  # turned on again by something else: the next window turns it off
        MainWindow(SettingsStore(str(tmp_path / "Other.ini"))).close()
        assert not gc.isenabled() and gcguard.install(qt) is timer
        threads = []
        gc.callbacks.append(lambda phase, _info: threads.append(threading.current_thread()))
        try:

            def make_cycles():
                for _ in range(20_000):
                    a = []
                    a.append(a)

            worker = threading.Thread(target=make_cycles)
            worker.start()
            worker.join()
            assert not threads, "nothing collected on the worker"
            _wait(qt, lambda: threads, 10)
            assert all(t is threading.main_thread() for t in threads)
        finally:
            gc.callbacks.pop()
    finally:
        w.close()


def test_collect_due_follows_the_thresholds():
    from solidseas_app.viewer.gcguard import collect_due

    old, was_on = gc.get_threshold(), gc.isenabled()
    gc.disable()  # as the guard leaves it; with collection on, Python collects first
    try:
        gc.collect()  # every generation's count starts from nought
        gc.set_threshold(10**9, 10**9, 10**9)
        assert collect_due() == -1
        gc.set_threshold(1, 10**9, 10**9)
        junk = [[] for _ in range(50)]
        assert collect_due() == 0
        del junk
    finally:
        gc.set_threshold(*old)
        if was_on:
            gc.enable()
