"""Each folder's index kept and shown again, its age and re-indexing, and the recent folders
(``solidseas_app.viewer.savedindex`` and the window)."""

import shutil
import time

import pytest

from support import FIXTURES
from test_viewer import _wait, app, needs_qt  # noqa: F401  (the Qt application, as a fixture)

pytestmark = [needs_qt, pytest.mark.usefixtures("app")]
PARTS = ("o02_boxA.SLDPRT", "o11_curved.SLDPRT", "o07_boxB_h31.SLDPRT")


def _qt():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance()


def _folder(tmp_path, name="Jobs", parts=PARTS):
    folder = tmp_path / name
    folder.mkdir()
    for p in parts:
        shutil.copyfile(FIXTURES / p, folder / p)
    return str(folder)


def _window(tmp_path, **settings):
    from solidseas_app.viewer.settings import Settings, SettingsStore
    from solidseas_app.viewer.window import MainWindow

    store = SettingsStore(str(tmp_path / "Viewer.ini"))
    if settings:
        store.save(Settings().but(**settings))
    w = MainWindow(store)
    w.where_used.enabled = False
    return w


def _listed(qt, w, folder):
    w.open_folder(folder)
    _wait(qt, lambda: w.listing_info is not None)


def _saved(w, folder):
    from solidseas_app.viewer import savedindex

    return savedindex.load(folder, w._formats(), w.settings.thumbnail_pixels)


def test_a_folder_opened_again_shows_its_saved_index_at_once_with_its_age(tmp_path):
    qt = _qt()
    folder = _folder(tmp_path)
    first = _window(tmp_path)
    try:
        _listed(qt, first, folder)
        assert not first.listing_info.get("saved") and first.index_bar.isHidden()
        rows = len(first.model.rows)
        _wait(qt, lambda: _saved(first, folder) is not None)
    finally:
        first.shutdown()
        first.close()
    second = _window(tmp_path)
    try:
        second.open_folder(folder)
        assert second.listing_info is not None and second.listing_info["saved"], "shown at once"
        assert len(second.model.rows) == rows and second._listing is None, "no file read again"
        assert not second.index_bar.isHidden()
        assert "index is less than a minute old" in second.index_label.text()
    finally:
        second.shutdown()
        second.close()


def test_re_index_keeps_the_list_until_the_new_one_is_read(tmp_path):
    qt = _qt()
    folder = _folder(tmp_path)
    w = _window(tmp_path)
    try:
        _listed(qt, w, folder)
        _wait(qt, lambda: _saved(w, folder) is not None)
        w.open_folder(folder)  # the saved index
        before = len(w.model.rows)
        shutil.copyfile(FIXTURES / "o12_multibody.SLDPRT", f"{folder}/o12_multibody.SLDPRT")
        w.index_button.click()
        assert w._listing is not None and len(w.model.rows) == before, "the list stays while it is read"
        assert "while it is read again" in w.index_label.text() and not w.index_button.isEnabled()
        _wait(qt, lambda: w._listing is None)
        assert len(w.model.rows) == before + 1 and w.index_bar.isHidden()
        assert not w.listing_info.get("saved")
        _wait(qt, lambda: (_saved(w, folder) or None) is not None and _saved(w, folder).rows == before + 1)
    finally:
        w.shutdown()
        w.close()


def test_an_index_older_than_the_setting_is_read_again_by_itself(tmp_path):
    qt = _qt()
    from solidseas_app.viewer import savedindex

    folder = _folder(tmp_path)
    w = _window(tmp_path, reindex_after_hours=1)
    try:
        _listed(qt, w, folder)
        rows = [(r.entry, r.thumb) for r in w.model.rows]
        # the window saves its own index on a thread: let it land first, or it replaces this one
        _wait(qt, lambda: _saved(w, folder) is not None)
        savedindex.save(
            folder, w._formats(), w.settings.thumbnail_pixels, rows, read_at=time.time() - 2 * 3600
        )
        w.open_folder(folder)
        assert w.listing_info["saved"] and w._listing is not None, "shown, and read again at once"
        assert "2 h" in w.index_label.text()
        _wait(qt, lambda: w._listing is None)
        assert w.index_bar.isHidden()
    finally:
        w.shutdown()
        w.close()


def test_without_keeping_indexes_every_opening_reads_the_folder(tmp_path):
    qt = _qt()
    folder = _folder(tmp_path)
    w = _window(tmp_path, keep_index=False)
    try:
        _listed(qt, w, folder)
        time.sleep(0.2)
        assert _saved(w, folder) is None
        w.open_folder(folder)
        assert w._listing is not None and w.index_bar.isHidden()
        _wait(qt, lambda: w._listing is None)
    finally:
        w.shutdown()
        w.close()


def test_recent_folders_newest_first_kept_to_the_setting_and_cleared(tmp_path):
    qt = _qt()
    folders = [_folder(tmp_path, f"Job{n}", PARTS[:1]) for n in range(3)]
    w = _window(tmp_path, recent_count=2, keep_index=False)
    try:
        for f in folders:
            _listed(qt, w, f)
        texts = [a.text() for a in w.recent_menu.actions() if not a.isSeparator()]
        assert len(texts) == 3 and texts[0].startswith("&1") and "Job2" in texts[0] and "Job1" in texts[1]
        assert texts[2] == "Clear Recent Folders"
        assert w.store.load_session().recent == (folders[2], folders[1])
        w.recent_menu.actions()[1].trigger()
        _wait(qt, lambda: w.folder == folders[1] and w.listing_info is not None)
        assert w.store.load_session().recent[0] == folders[1]
        w.clear_recent()
        assert [a.text() for a in w.recent_menu.actions()] == ["No recent folders"]
    finally:
        w.shutdown()
        w.close()
