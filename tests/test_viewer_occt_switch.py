"""Switching the OCCT backend extension on or off while the viewer runs
(``docs/EXTENSIONS.md`` section 9): the window's worker processes, the listing and the
saved folder index follow the switch at once, without a restart, and while the backend is
off IGES and BREP files are listed saying what they need.

The switch is a stand-in, as in ``tests/test_occt_backend.py``: setting
``SOLIDSEAS_OCCT_HELPER_PYTHON`` makes the backend available from a checkout, and clearing
it makes it unavailable, as switching the extension on and off does. No Open CASCADE is
needed: the listing reads only an IGES file's head, which is pure Python. The model pool's
own rules are tested with a stand-in for its worker pool.
"""

import sys

import pytest

from solidseas.convert import occt
from solidseas.errors import WorkerCrashedError
from solidseas_app.viewer import modelpool, samples, wording
from test_viewer import _wait, app, needs_qt  # noqa: F401  (the Qt application, as a fixture)


def _switch(monkeypatch, on: bool) -> None:
    """The OCCT backend on or off, as the Extensions page's switch makes it."""
    if on:
        monkeypatch.setenv(occt.ENV_PYTHON, sys.executable)
    else:
        monkeypatch.delenv(occt.ENV_PYTHON, raising=False)
    occt.forget()


# --------------------------------------------------------------------------- the model pool
class FakePool:
    """Stands in for :class:`solidseas.workers.WorkerPool`: answers which pool ran a job and
    what its workers could start; ``during`` runs inside a call, as something happening
    while a worker reads."""

    made: list["FakePool"] = []

    def __init__(self, workers, *, helpers_per_worker=0, **_kw):
        self.helpers_per_worker = helpers_per_worker
        self.closed = False
        self.during = None
        FakePool.made.append(self)

    def call(self, job, params, *, timeout=None):
        if self.during is not None:
            during, self.during = self.during, None
            during()
        if self.closed:
            raise WorkerCrashedError("the worker pool is closed")
        return (FakePool.made.index(self), self.helpers_per_worker)

    def close(self):
        self.closed = True


@pytest.fixture
def fake_pools(monkeypatch):
    import solidseas.workers

    FakePool.made = []
    helpers = {"now": 0}
    monkeypatch.setattr(solidseas.workers, "WorkerPool", FakePool)
    monkeypatch.setattr(modelpool, "_helpers", lambda: helpers["now"])
    return helpers


def test_the_pool_s_workers_start_the_helper_only_while_the_backend_is_on(monkeypatch):
    _switch(monkeypatch, False)
    assert modelpool._helpers() == 0
    _switch(monkeypatch, True)
    assert modelpool._helpers() == 1
    _switch(monkeypatch, False)
    assert modelpool._helpers() == 0


def test_a_pool_started_before_a_switch_is_started_again_after_it(fake_pools):
    pool = modelpool.ModelPool(workers=1)
    assert not pool.stale() and not pool.restart(), "nothing runs yet: nothing to start again"
    assert pool.call("job", {}) == (0, 0) and pool.helpers == 0 and pool.started == 1
    assert not pool.stale()
    fake_pools["now"] = 1  # switched on: a pool started now would let its workers start the helper
    assert pool.stale()
    assert pool.restart() and FakePool.made[0].closed and not pool.running
    assert pool.call("job", {}) == (1, 1) and pool.helpers == 1 and pool.started == 2
    fake_pools["now"] = 0  # and off again: without the backend the workers start nothing
    assert pool.stale() and pool.restart()
    assert pool.call("job", {}) == (2, 0)
    pool.close()
    assert not pool.restart(), "a closed pool stays closed"
    with pytest.raises(WorkerCrashedError, match="closing"):
        pool.call("job", {})


def test_a_read_caught_by_a_restart_runs_again_on_the_new_pool(fake_pools):
    pool = modelpool.ModelPool(workers=1)
    pool.call("job", {})
    old = FakePool.made[0]
    fake_pools["now"] = 1
    old.during = pool.restart  # the switch changes while a worker reads
    assert pool.call("job", {}) == (1, 1)
    # a pool that stopped on its own is said, not run again
    FakePool.made[1].closed = True
    with pytest.raises(WorkerCrashedError, match="closed"):
        pool.call("job", {})
    # nor is a read caught by the window closing
    pool2 = modelpool.ModelPool(workers=1)
    pool2.call("job", {})
    FakePool.made[-1].during = pool2.close
    with pytest.raises(WorkerCrashedError):
        pool2.call("job", {})
    pool.close()


# --------------------------------------------------------------------------- the wording
def test_a_helper_that_would_not_start_is_not_called_switched_off():
    error = {
        "code": "format_not_supported",
        "message": "SolidSeas reads this file's format through an extension that is not added or not "
        "switched on.",
        "reader_message": "The OCCT backend could not start: [WinError 1816] Not enough quota is available",
        "detail": {"rule": "needs_extension"},
    }
    text = wording.not_supported_text(error)
    assert text == wording.HELPER_NOT_STARTED and "is on, but its program could not start" in text
    assert "switch it on" not in wording.error_message(error, path=r"C:\x\sheet.igs")
    plain = {"code": "format_not_supported", "detail": {"rule": "needs_extension", "value": "iges"}}
    assert "switch it on" in wording.not_supported_text(plain)


# --------------------------------------------------------------------------- the window
@pytest.fixture
def window(app):  # noqa: F811
    from solidseas_app.viewer.window import MainWindow

    w = MainWindow()
    w.where_used.enabled = False
    yield w
    assert w.shutdown()
    w.close()
    w.deleteLater()
    app.processEvents()


@pytest.fixture
def folder(tmp_path):
    every = tmp_path / "every"
    samples.write_samples(str(every))
    folder = tmp_path / "parts"
    folder.mkdir()
    for name in ("bracket.step", "sheet.igs"):
        (folder / name).write_bytes((every / name).read_bytes())
    return folder


def _status(w, name: str) -> str:
    return w.model.rows[w.model.find_path(name)].entry["status"]


def _listed(app, w):  # noqa: F811
    _wait(app, lambda: w.listing_info is not None and w._listing is None)


def _saved(w, folder):
    from solidseas_app.viewer import savedindex

    return savedindex.load(str(folder), w._formats(), w.settings.thumbnail_pixels)


@needs_qt
def test_switching_the_backend_reaches_the_running_viewer(app, window, folder, monkeypatch):  # noqa: F811
    w = window
    _switch(monkeypatch, False)
    w.open_folder(str(folder))
    _listed(app, w)
    assert _status(w, "sheet.igs") == "unsupported" and w.models.helpers == 0
    assert "1 IGES file needs the OCCT backend extension" in w.status_label.text()
    started = w.models.started
    _wait(app, lambda: _saved(w, folder) is not None)

    # Switched on: the pool started without the helper starts again, and the folder is
    # read again, so the IGES file is read and its row is no longer greyed.
    _switch(monkeypatch, True)
    w.extensions_changed()
    assert w._listing is not None, "read again at once"
    _listed(app, w)
    assert _status(w, "sheet.igs") == "ok" and w.models.helpers == 1
    assert w.models.started == started + 1
    assert "needs the OCCT backend" not in w.status_label.text()
    _wait(app, lambda: _saved(w, folder) is not None)
    kept = {e["path"]: e["status"] for batch in _saved(w, folder).entries() for e, _t in batch}
    assert kept["sheet.igs"] == "ok"

    # A change that changes nothing for IGES and BREP files leaves the pool and the list be.
    w.extensions_changed()
    assert w._listing is None and w.models.started == started + 1

    # Opened again with the backend on, its saved index is the one read with it on.
    w.open_folder(str(folder))
    assert w.listing_info["saved"] and _status(w, "sheet.igs") == "ok"

    # Switched off: the workers start nothing again, and the row says what it needs.
    _switch(monkeypatch, False)
    w.extensions_changed()
    _listed(app, w)
    assert _status(w, "sheet.igs") == "unsupported" and w.models.stale() is False
    assert w.model.rows[w.model.find_path("sheet.igs")].display[2] == "Needs the OCCT backend"
    # the folder's index read with the backend off is shown for it off, never the other
    w.open_folder(str(folder))
    assert w.listing_info.get("saved") and _status(w, "sheet.igs") == "unsupported"


@needs_qt
def test_a_switch_during_a_listing_reads_the_folder_again(app, window, folder, monkeypatch):  # noqa: F811
    w = window
    _switch(monkeypatch, False)
    w.settings = w.settings.but(keep_index=False)
    w.open_folder(str(folder))
    assert w._listing is not None
    _switch(monkeypatch, True)
    w.extensions_changed()
    _listed(app, w)
    assert _status(w, "sheet.igs") == "ok"


@needs_qt
def test_the_extensions_page_tells_the_window(app, window, monkeypatch):  # noqa: F811
    from solidseas_app.viewer.settingswindow import EXTENSIONS, SettingsWindow

    told = []
    monkeypatch.setattr(window, "extensions_changed", lambda: told.append(True))
    sw = SettingsWindow(window, page=EXTENSIONS)
    try:
        sw.extensions.switch("occt", True)
        assert told == [True]
    finally:
        sw.deleteLater()
