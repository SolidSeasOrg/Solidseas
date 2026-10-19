"""Settings: every setting in one window, its pages listed on the left
(``solidseas_app.viewer.settingswindow``)."""

import json

import pytest

from test_viewer import app, needs_qt  # noqa: F401  (the Qt application, as a fixture)

pytestmark = [needs_qt, pytest.mark.usefixtures("app")]


@pytest.fixture
def window(tmp_path):
    from solidseas_app.viewer.settings import SettingsStore
    from solidseas_app.viewer.window import MainWindow

    w = MainWindow(SettingsStore(str(tmp_path / "Viewer.ini")))
    w.drawings.settings_path = str(tmp_path / "Drawing.json")
    yield w
    w.close()


def _nav(dialog):
    out = []
    for i in range(dialog.nav.topLevelItemCount()):
        item = dialog.nav.topLevelItem(i)
        out.append((item.text(0), [item.child(k).text(0) for k in range(item.childCount())]))
    return out


def test_every_area_is_a_page_listed_on_the_left(window):
    from solidseas_app.viewer import settingswindow as SW
    from solidseas_app.viewer.drawingsettings import PAGES as DRAWING_PAGES

    d = SW.SettingsWindow(window)
    try:
        nav = _nav(d)
        assert [t for t, _ in nav] == list(SW.PAGES)
        assert dict(nav)[SW.DRAWINGS] == [p.title for p in DRAWING_PAGES]
        assert d.current_page() == SW.GENERAL and d.restore.isEnabled()
        for page in SW.PAGES:
            d.show_page(page)
            assert d.stack.currentIndex() == SW.PAGES.index(page) and d.current_page() == page
        d.show_page(DRAWING_PAGES[2].title)
        assert d.stack.currentIndex() == SW.PAGES.index(SW.DRAWINGS)
        assert d.drawings.current_page() == DRAWING_PAGES[2].title
        d.show_page(SW.EXTENSIONS)
        assert not d.restore.isEnabled(), "an extension's change takes effect at once"
        hosted = (d.drawings.buttons, d.drawings.page_list, d.ai.buttons, d.extensions.buttons)
        assert all(w.isHidden() for w in hosted), "only the window's own buttons and list"
        with pytest.raises(ValueError):
            d.show_page("Nowhere")
    finally:
        d.deleteLater()


def test_apply_saves_the_viewer_s_settings_and_drawing_settings(window, tmp_path):
    from solidseas_app.viewer import settingswindow as SW

    d = SW.SettingsWindow(window, page=SW.VIEW_3D)
    try:
        assert not window.settings.view_3d
        d.preferences.view_3d.setChecked(True)
        assert d.apply()
        assert window.settings.view_3d, "the viewer's setting applied at once"
        assert (tmp_path / "Drawing.json").is_file(), "Drawing Settings saved"
        saved = json.loads((tmp_path / "Drawing.json").read_text(encoding="utf-8"))
        assert saved["schema"].startswith("solidseas.drawing-settings/")
    finally:
        d.deleteLater()


def test_a_refused_value_shows_its_page_and_saves_nothing_of_that_area(window):
    from solidseas.ai.errors import InvalidSettingError
    from solidseas_app.viewer import settingswindow as SW

    def refused():
        raise InvalidSettingError("a bad model name")

    d = SW.SettingsWindow(window)
    try:
        d.ai.form_settings = refused
        assert not d.apply()
        assert d.current_page() == SW.AI and not d.error.isHidden()
        assert "AI settings were not saved" in d.error.text()
    finally:
        d.deleteLater()


def test_the_menus_open_the_settings_window_on_their_page(window, monkeypatch):
    from solidseas_app.viewer import settingswindow as SW

    opened = []
    monkeypatch.setattr(SW, "open_settings", lambda w, page=None: opened.append(page))
    window.act_preferences.trigger()
    window.act_ai_settings.trigger()
    window.act_extensions.trigger()
    window.drawings.settings_action.trigger()
    assert opened == [None, SW.AI, SW.EXTENSIONS, SW.DRAWINGS]
    assert (
        window.act_preferences.text() == "&Settings..."
        and window.act_preferences.shortcut().toString() == "Ctrl+,"
    )
