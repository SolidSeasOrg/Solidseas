"""Experimental and in-development features say so (``solidseas_app.viewer.experimental``):
the tag beside their entries and titles, the note on their Settings pages, and drawings on
by default yet switchable off."""

import pytest

from test_viewer import app, needs_qt  # noqa: F401  (the Qt application, as a fixture)

URL = "https://github.com/SolidSeas/SolidSeas/issues"


def test_the_tag_and_the_notes_read_the_same_everywhere():
    from solidseas_app.viewer import experimental as E

    assert E.tag() == "Experimental" and E.tag(E.IN_DEVELOPMENT) == "In development"
    assert E.tagged("New &Drawing...") == "New &Drawing... (Experimental)"
    assert E.tagged("OCCT backend", E.IN_DEVELOPMENT) == "OCCT backend (In development)"
    with pytest.raises(ValueError):
        E.tagged("x", "Beta")
    notes = [E.drawings_note(), E.assistant_note(), E.extensions_note(), E.note(E.IN_DEVELOPMENT)]
    for text in notes:
        assert text.endswith(f"Report problems at {URL}"), text
        assert "incomplete or wrong" in text and "change between versions" in text
        assert "—" not in text and "–" not in text, "no em or en dashes"
    assert "check every drawing before you use it" in E.drawings_note()
    assert E.extension_stage("occt") == E.IN_DEVELOPMENT and E.extension_stage("video") == E.EXPERIMENTAL
    assert E.extension_stage("unknown") == E.EXPERIMENTAL


@needs_qt  # the settings module reads Qt's QSettings
def test_drawings_are_on_for_a_fresh_settings_file_and_stay_off_once_saved_off(tmp_path):
    from solidseas_app.viewer.settings import Settings, SettingsStore

    path = tmp_path / "Viewer.ini"
    assert SettingsStore(str(path)).load().drawings, "no file yet: on"
    path.write_text("[Preferences]\nview_3d=true\n", encoding="utf-8")
    assert SettingsStore(str(path)).load().drawings, "a file saved before the setting existed: on"
    store = SettingsStore(str(path))
    assert store.save(Settings().but(drawings=False))
    assert "drawings=false" in path.read_text(encoding="utf-8")
    assert not SettingsStore(str(path)).load().drawings, "a saved off stays off"
    assert store.save(Settings())
    assert SettingsStore(str(path)).load().drawings


@pytest.fixture
def window(tmp_path, app):  # noqa: F811
    from solidseas_app.viewer.settings import SettingsStore
    from solidseas_app.viewer.window import MainWindow

    w = MainWindow(SettingsStore(str(tmp_path / "Viewer.ini")))
    w.drawings.settings_path = str(tmp_path / "Drawing.json")
    yield w
    w.close()


def _labels(widget):
    from PySide6.QtWidgets import QLabel

    return [label.text() for label in widget.findChildren(QLabel)]


@needs_qt
def test_the_settings_pages_say_what_experimental_means_and_switch_drawings_off(window, tmp_path):
    from solidseas_app.viewer import experimental as E
    from solidseas_app.viewer import settingswindow as SW
    from solidseas_app.viewer.settings import SettingsStore

    d = SW.SettingsWindow(window, page=SW.DRAWINGS)
    try:
        drawings = d.stack.widget(SW.PAGES.index(SW.DRAWINGS))
        assert E.drawings_note() in _labels(drawings)
        switch = d.preferences.drawings
        assert switch.isChecked() and switch.isVisibleTo(d), "on by default, on the Drawings page"
        assert d.preferences.drawings_note.isVisibleTo(d)
        assert E.assistant_note() in _labels(d.stack.widget(SW.PAGES.index(SW.AI)))
        assert E.extensions_note() in _labels(d.stack.widget(SW.PAGES.index(SW.EXTENSIONS)))
        for page in (SW.GENERAL, SW.VIEW_3D, SW.PRINT):
            assert not any("Report problems at" in t for t in _labels(d.stack.widget(SW.PAGES.index(page))))

        switch.setChecked(False)
        assert d.apply()
        assert not window.settings.drawings and not window.drawings.new_action.isVisible()
        assert not SettingsStore(str(tmp_path / "Viewer.ini")).load().drawings, "saved off"
    finally:
        d.deleteLater()


@needs_qt
def test_the_menus_and_the_extensions_page_carry_the_tag(window, tmp_path):
    from solidseas_app import extensions as X
    from solidseas_app.viewer import experimental as E
    from solidseas_app.viewer.extensionsdialog import ExtensionsDialog

    assert window.act_assistant.text() == "&Modeling Assistant... (Experimental)"
    file_menu = [a.text() for a in window.menuBar().actions()[0].menu().actions()]
    assert "New &Drawing... (Experimental)" in file_menu and "Open Dra&wing... (Experimental)" in file_menu
    assert "&Drawing Settings... (Experimental)" in [a.text() for a in window.settings_menu.actions()]

    page = ExtensionsDialog(root=str(tmp_path / "ext"), state_file=str(tmp_path / "Extensions.json"))
    try:
        for mid, m in X.CATALOG.items():
            assert page.names[mid].text() == E.tagged(f"<b>{m.name}</b>", E.extension_stage(mid))
        assert page.names["occt"].text().endswith("(In development)")
        assert page.names["gridfinity"].text().endswith("(Experimental)")
        assert page.experimental_note.text() == E.extensions_note()
    finally:
        page.deleteLater()


@needs_qt
def test_extension_fronts_carry_their_extension_tag(window):
    from solidseas_app.viewer import animationaction, convertaction
    from solidseas_app.viewer import experimental as E

    assert convertaction.TEXT == E.tagged("Con&vert...", E.extension_stage("occt"))
    assert window.act_convert.text() == "Con&vert... (In development)"
    assert animationaction.MENU_TEXT == E.tagged("Save Animation...", E.extension_stage("video"))
    assert animationaction.MENU_TEXT == "Save Animation... (Experimental)"

