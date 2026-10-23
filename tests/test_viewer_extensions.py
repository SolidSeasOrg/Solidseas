"""The Extensions page (``solidseas_app.viewer.extensionsdialog``), offscreen."""

import hashlib
import os

import pytest

from solidseas import policy
from solidseas_app import extensions as X
from test_extensions import _accept, _package
from test_viewer import needs_qt


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _dialog(tmp_path, **kw):
    from solidseas_app.viewer.extensionsdialog import ExtensionsDialog

    asked = []
    kw.setdefault("ask", lambda title, text: asked.append(text) or True)
    d = ExtensionsDialog(
        root=str(tmp_path / "extensions"), state_file=str(tmp_path / "Extensions.json"), **kw
    )
    d.asked, d.warned = asked, []
    d.warn = lambda title, text: d.warned.append(text)
    return d


@needs_qt
def test_the_page_lists_the_extensions_and_switches_are_saved(app, tmp_path):
    d = _dialog(tmp_path, pol=policy.Policy)
    assert [d.status_labels[i].text() for i in X.CATALOG] == ["Built in"] + ["Not added"] * 4
    assert d.switches["gridfinity"].isChecked(), "on until the person switches it off"
    assert not d.switches["video"].isEnabled() and d.switches["video"].toolTip()
    d.switches["gridfinity"].setChecked(False)
    assert X.read_state(str(tmp_path / "Extensions.json")).on == frozenset()
    d.deleteLater()


@needs_qt
def test_a_package_is_added_switched_on_and_removed(app, tmp_path):
    pkg = _package(tmp_path)
    opened = []
    d = _dialog(
        tmp_path, pol=policy.Policy, accepted=_accept(pkg), ask_file=lambda: str(pkg), open_url=opened.append
    )
    assert d.add_from_file() and "Switch it on now?" in d.asked[-1]
    assert d.status_labels["video"].text().startswith("Added, version") and d.switches["video"].isChecked()
    assert X.on_ids(X.read_state(str(tmp_path / "Extensions.json")), pol=policy.Policy(), root=d.root) >= {
        "video"
    }
    assert d.remove("video") and d.status_labels["video"].text() == "Not added"
    assert not d.switches["video"].isChecked() and not d.remove_buttons["video"].isEnabled()
    d.findChildren(type(d.remove_buttons["video"]))[0].click()  # Get extensions...
    assert opened == [X.RELEASES_URL]
    d.deleteLater()


@needs_qt
def test_a_package_this_core_does_not_accept_is_refused_with_the_reason(app, tmp_path):
    pkg = _package(tmp_path)
    d = _dialog(
        tmp_path,
        pol=policy.Policy,
        accepted={"video": [hashlib.sha256(b"other").hexdigest()]},
        ask_file=lambda: str(pkg),
    )
    assert not d.add_from_file() and "not one this version of SolidSeas accepts" in d.warned[-1]
    assert not os.path.exists(tmp_path / "extensions" / "video")
    d.deleteLater()


@needs_qt
def test_a_package_an_administrator_left_off_is_never_unpacked(app, tmp_path):
    pkg = _package(tmp_path)
    for pol in (
        policy.Policy(extensions_disabled=True, locked=True),
        policy.Policy(allowed_extensions=("gridfinity",), locked=True),
    ):
        d = _dialog(tmp_path, pol=lambda pol=pol: pol, accepted=_accept(pkg), ask_file=lambda: str(pkg))
        assert not d.add_from_file() and "Set by your administrator" in d.warned[-1]
        assert not os.path.exists(tmp_path / "extensions" / "video") and d.asked == []
        d.deleteLater()


@needs_qt
def test_an_administrator_s_lock_shows_on_every_switch(app, tmp_path):
    d = _dialog(tmp_path, pol=lambda: policy.Policy(extensions_disabled=True, locked=True))
    assert all(not s.isEnabled() and not s.isChecked() for s in d.switches.values())
    assert d.status_labels["gridfinity"].text() == "Built in. Set by your administrator"
    d.deleteLater()


@needs_qt
def test_gridfinity_s_settings_are_saved_and_an_environment_variable_still_comes_first(
    app, tmp_path, monkeypatch
):
    from solidseas_app.gridfinity import connector
    from solidseas_app.viewer.extensionsdialog import SettingsDialog

    state_file = tmp_path / "Extensions.json"
    monkeypatch.setenv("SOLIDSEAS_EXTENSIONS_FILE", str(state_file))
    monkeypatch.delenv("SOLIDSEAS_GRIDFINITY_PHOTOS", raising=False)
    monkeypatch.setenv("SOLIDSEAS_TRACEFINITY_SSH", "me@the-server")
    d = _dialog(tmp_path, pol=policy.Policy)
    s = SettingsDialog(d, "gridfinity", d.state())
    assert not s.fields["ssh"].isEnabled() and s.fields["ssh"].text() == "me@the-server"
    photos = str(tmp_path / "My tool photos")
    s.fields["photos"].setText(photos)
    s.fields["bins"].setText("   ")
    s.accept()
    assert d.edit_settings("gridfinity", s)
    saved = X.read_state(str(state_file))
    assert saved.settings == {"gridfinity": {"photos": photos}} and saved.on == X.DEFAULT_ON
    assert connector.default_photos() == photos
    assert X.setting("gridfinity", "ssh") == "me@the-server", "the variable comes first"
    monkeypatch.setenv("SOLIDSEAS_GRIDFINITY_PHOTOS", str(tmp_path / "from the variable"))
    assert connector.default_photos() == str(tmp_path / "from the variable")
    with pytest.raises(X.ExtensionError):
        X.with_setting(saved, "gridfinity", "colour", "red")
    s.deleteLater()
    d.deleteLater()
