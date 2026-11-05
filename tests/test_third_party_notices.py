"""THIRD_PARTY_NOTICES.txt covers every package of the Windows build's lock at the version the
lock pins, the licence texts it names are in licenses/, and the builds carry them: the viewer's
spec puts them inside the executable, the extension packages carry theirs, and Help > Licences
shows them."""

import hashlib
import os
import re
from pathlib import Path

import pytest
from packaging.utils import canonicalize_name

from test_build_lock import locked

ROOT = Path(__file__).resolve().parent.parent
NOTICES = ROOT / "THIRD_PARTY_NOTICES.txt"
LICENCES = ROOT / "licenses"
SPEC = ROOT / "packaging" / "SolidSeasViewer.spec"
EXTENSIONS = ROOT / "scripts" / "build-extensions.ps1"
# Texts a build writes or takes from elsewhere, so not in the repository: Python's licence and
# the list of libraries (the viewer's build), ffmpeg's build record and its own licence files
# (the video package), and SolidCraft's files (its release zip).
MADE_BY_THE_BUILD = {
    "Python-LICENSE.txt",
    "BUNDLED-FILES.txt",
    "ffmpeg-build.txt",
    # the OCCT package's build record (the wheels and where their exact source is)
    "occt-build.txt",
    "THIRD-PARTY-LICENSES.txt",
    # what packaging/ffmpeg/build.sh writes beside ffmpeg.exe
    "COPYING.LGPLv2.1.txt",
    "LICENSE-zlib.txt",
    "LICENSE-mingw-w64.txt",
}
# The third-party packages inside the executable and the texts of their licences.
CARRIED = {
    "pyside6-essentials": ["LGPL-3.0.txt", "GPL-3.0.txt", "Qt-third-party.txt"],
    "shiboken6": ["LGPL-3.0.txt", "GPL-3.0.txt"],
    "olefile": ["olefile-LICENSE.txt"],
    "truststore": ["truststore-LICENSE.txt"],
}


def notices() -> str:
    return NOTICES.read_text(encoding="utf-8")


def test_the_notices_list_every_locked_package_at_its_locked_version():
    text = notices()
    for name, (version, _) in locked().items():
        row = rf"^\s*{re.escape(name)}\s+{re.escape(version)}\s"
        assert re.search(row, text, re.M), f"THIRD_PARTY_NOTICES.txt has no row for {name} {version}"


def test_every_package_the_executable_carries_has_its_licence_texts():
    pins = locked()
    for name, texts in CARRIED.items():
        assert name in pins, name
        for t in texts:
            assert (LICENCES / t).is_file(), f"{name} needs licenses/{t}"
    # The spec's own list of what it may carry is this one, so neither drifts from the other.
    spec = SPEC.read_text(encoding="utf-8")
    listed = dict(re.findall(r'^\s*"(\w+)": "(\w+)",$', spec[spec.index("NOTICED = {") :], re.M)[:4])
    assert {canonicalize_name(d) for d in listed.values()} == set(CARRIED)


def test_every_licence_file_the_notices_name_is_in_the_repository():
    named = set(re.findall(r"\b[\w.-]+\.txt\b", notices())) - MADE_BY_THE_BUILD
    named -= {"THIRD_PARTY_NOTICES.txt", "build-windows.txt", "occt-helper.txt"}  # two in requirements/
    assert named
    for name in named:
        assert (LICENCES / name).is_file() or (ROOT / name).is_file(), name
    for name in ("LICENSE", "NOTICE"):
        assert (ROOT / name).is_file()


def test_the_gnu_licences_are_the_fsf_s_texts():
    # The SHA-256 of each text as gnu.org publishes it (lgpl-3.0.txt, gpl-3.0.txt and
    # old-licenses/lgpl-2.1.txt), so a text cannot change by accident or by line endings.
    published = {
        "LGPL-3.0.txt": "e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118",
        "GPL-3.0.txt": "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986",
        "LGPL-2.1.txt": "20e50fe7aae3e56378ebf0417d9de904f55a0e61e4df315333e632a4d3555d95",
    }
    for name, digest in published.items():
        assert hashlib.sha256((LICENCES / name).read_bytes()).hexdigest() == digest, name


def test_the_qt_notices_and_source_links_are_for_the_locked_qt():
    qt = locked()["pyside6-essentials"][0]
    assert locked()["shiboken6"][0] == qt
    third = (LICENCES / "Qt-third-party.txt").read_text(encoding="utf-8")
    assert third.startswith(f"Third-party code in Qt Core and Qt GUI {qt}\n")
    assert "The FreeType Project LICENSE" in third and "Portions of this software are copyright" in third
    text = notices()
    major_minor = ".".join(qt.split(".")[:2])
    assert f"/qt/{major_minor}/{qt}/single/qt-everywhere-src-{qt}.tar.xz" in text
    assert f"PySide6-{qt}-src/pyside-setup-everywhere-src-{qt}.zip" in text


def test_the_viewer_build_carries_the_licence_texts_and_checks_the_notices():
    spec = SPEC.read_text(encoding="utf-8")
    for needed in (
        'a.datas += [(f"licenses/{n}", os.path.join(LICENCES, n), "DATA")',
        '("licenses/Python-LICENSE.txt", PYTHON_LICENCE, "DATA")',
        '("licenses/BUNDLED-FILES.txt", BUNDLED, "DATA")',
        'OWN_TEXTS = ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.txt")',
        "sys.stdlib_module_names",
        '"solidseas_app.viewer.licences"',
    ):
        assert needed in spec, needed
    # The licence texts are added after the filter that drops Qt's translations, and before the
    # executable is made from the data.
    assert spec.index("a.datas = [d for d in a.datas") < spec.index('a.datas += [(f"licenses/')
    assert spec.index('a.datas += [("licenses/BUNDLED-FILES.txt"') < spec.index("exe = EXE(")


def test_the_extension_packages_carry_their_licence_texts():
    build = EXTENSIONS.read_text(encoding="utf-8")
    assert "function Copy-Licences" in build
    steps = build[build.index("if ('cad-bridge' -in $Only) {") :]
    solidworks = steps[: steps.index("if ('video' -in $Only) {")]
    video = steps[len(solidworks) : steps.index("if ('solidcraft' -in $Only)")]
    for needed in (
        "--enable-(gpl|nonfree)",
        "-hide_banner -version",
        "$FfmpegSource",
        "LGPL-2.1.txt",
        "PyInstaller-COPYING.txt",
        "Python-LICENSE.txt",
        "Copy-Licences $folder ($ownLicences",
    ):
        assert needed in video, needed
    assert "Copy-Licences $folder $ownLicences" in solidworks
    assert "Invoke-Package 'cad-bridge' $folder @()" not in solidworks
    for name in ("LICENSE-MIT", "LICENSE-APACHE", "NOTICE", "THIRD-PARTY-LICENSES.txt"):
        assert name in build
    viewer = (ROOT / "scripts" / "build-viewer.ps1").read_text(encoding="utf-8")
    assert "-FfmpegSource $FfmpegSource" in viewer


def test_licence_files_from_a_checkout_list_the_notices_first():
    licences = pytest.importorskip("solidseas_app.viewer.licences")
    files = [os.path.basename(p) for p in licences.licence_files()]
    assert files[:3] == ["THIRD_PARTY_NOTICES.txt", "NOTICE", "LICENSE"]
    assert {"LGPL-3.0.txt", "GPL-3.0.txt", "Qt-third-party.txt", "olefile-LICENSE.txt"} <= set(files)


def test_licence_files_in_the_executable_come_from_its_own_folder(tmp_path, monkeypatch):
    import sys

    licences = pytest.importorskip("solidseas_app.viewer.licences")
    folder = tmp_path / "licenses"
    folder.mkdir()
    for name in ("LGPL-3.0.txt", "BUNDLED-FILES.txt", "LICENSE", "THIRD_PARTY_NOTICES.txt"):
        (folder / name).write_text(name, encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    files = [os.path.basename(p) for p in licences.licence_files()]
    assert files == ["THIRD_PARTY_NOTICES.txt", "LICENSE", "BUNDLED-FILES.txt", "LGPL-3.0.txt"]


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    return widgets.QApplication.instance() or widgets.QApplication([])


def test_help_licences_lists_the_texts_and_shows_the_one_picked(app, tmp_path):
    from solidseas_app.viewer.licences import LicencesDialog

    a = tmp_path / "THIRD_PARTY_NOTICES.txt"
    b = tmp_path / "LGPL-3.0.txt"
    a.write_text("the notices", encoding="utf-8")
    b.write_bytes("﻿GNU LESSER GENERAL PUBLIC LICENSE".encode())
    dialog = LicencesDialog(None, [str(a), str(b)])
    try:
        assert [dialog.names.item(i).text() for i in range(dialog.names.count())] == [a.name, b.name]
        assert dialog.text.toPlainText() == "the notices" and dialog.text.isReadOnly()
        dialog.names.setCurrentRow(1)
        assert dialog.text.toPlainText() == "GNU LESSER GENERAL PUBLIC LICENSE"
    finally:
        dialog.deleteLater()
    empty = LicencesDialog(None, [])
    try:
        assert "licenses folder" in empty.text.toPlainText()
    finally:
        empty.deleteLater()


def test_the_help_menu_has_licences_and_the_about_box_names_the_lgpl(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from solidseas_app.viewer.settings import SettingsStore
    from solidseas_app.viewer.window import MainWindow

    w = MainWindow(SettingsStore(str(tmp_path / "Viewer.ini")))
    try:
        help_menu = next(a.menu() for a in w.menuBar().actions() if a.text() == "&Help")
        assert [a.text() for a in help_menu.actions()] == ["&Licences...", "&About SolidSeas Viewer"]
        shown = []
        monkeypatch.setattr(QMessageBox, "about", lambda parent, title, text: shown.append(text))
        w.about()
        assert "GNU Lesser General Public License version 3" in shown[0] and "Licences" in shown[0]
    finally:
        w.shutdown()
        w.close()


def test_each_library_from_python_has_its_own_licence_where_the_spec_names_one():
    spec = (ROOT / "packaging" / "SolidSeasViewer.spec").read_text(encoding="utf-8")
    named = re.findall(r'\("(?:[a-z]+)", "([A-Za-z0-9_.-]+\.txt)"\)', spec)
    assert {
        "OpenSSL-LICENSE.txt",
        "SQLite-public-domain.txt",
        "xz-COPYING.txt",
        "mpdecimal-LICENSE.txt",
    } <= set(named)
    notices = (ROOT / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8")
    for name in named:
        assert (ROOT / "licenses" / name).is_file(), name
        assert name in notices, name


def test_the_library_notices_the_three_js_its_viewer_carries():
    """The service's reference viewer carries three.js in the wheel (THIRD_PARTY_NOTICES.txt
    section 1): the row names the vendored release, and its licence text is the one shipped
    beside the files."""
    vendored = ROOT / "src" / "solidseas" / "serve" / "viewer" / "three"
    core = (vendored / "build" / "three.core.min.js").read_text("utf-8")[:400]
    revision = re.search(r'const \w+="(\d+)"', core).group(1)
    text = notices()
    library = text[text.index("1. The library\n---") : text.index("2. SolidSeas Viewer (")]
    row = rf"^\s*three\.js\s+0\.{revision}\.\d+\s+MIT\s+three\.js-LICENSE\.txt$"
    assert re.search(row, library, re.M)
    assert (LICENCES / "three.js-LICENSE.txt").read_bytes() == (vendored / "LICENSE").read_bytes()


def _video_and_occt_steps() -> tuple[str, str]:
    build = EXTENSIONS.read_text(encoding="utf-8")
    video = build[build.index("if ('video' -in $Only) {") : build.index("if ('solidcraft' -in $Only)")]
    occt = build[build.index("if ('occt' -in $Only) {") : build.index("$zips = @(")]
    return video, occt


def test_the_python_helpers_carry_the_licences_of_what_python_brings():
    """solidseas-video.exe and solidseas-occt.exe are PyInstaller programs: besides Python's own
    LICENSE.txt they carry OpenSSL, mpdecimal and xz from the standard library, and the code
    Python incorporates (expat, the Mersenne Twister and others), whose notices Python's
    LICENSE.txt leaves out."""
    build = EXTENSIONS.read_text(encoding="utf-8")
    parts = re.search(r"^\$pythonParts = @\(([^)]*)\)$", build, re.M)
    assert parts, "build-extensions.ps1 lists no $pythonParts"
    names = re.findall(r"'([^']+)'", parts.group(1))
    assert {
        "Python-incorporated.txt",
        "OpenSSL-LICENSE.txt",
        "mpdecimal-LICENSE.txt",
        "xz-COPYING.txt",
    } <= set(names)
    for name in names:
        assert (LICENCES / name).is_file(), name
    for step in _video_and_occt_steps():
        assert "'SOURCE.txt') + $pythonParts" in step
    incorporated = (LICENCES / "Python-incorporated.txt").read_text(encoding="utf-8")
    for notice in ("Mersenne Twister", "SipHash24", "strtod and dtoa", "expat", "cfuhash"):
        assert f"\n{notice}\n" in incorporated, notice


def test_the_viewer_leaves_out_only_texts_that_ship_elsewhere():
    spec = SPEC.read_text(encoding="utf-8")
    block = spec[spec.index("NOT_IN_VIEWER = {") :]
    left_out = set(re.findall(r'"([^"]+\.txt)"', block[: block.index("}")]))
    assert left_out
    _, occt = _video_and_occt_steps()
    for name in left_out:
        assert (LICENCES / name).is_file(), name
        assert name in occt or name == "three.js-LICENSE.txt", name
    # The program's own components keep their texts, and so does where the LGPL source is.
    for name in ("LGPL-3.0.txt", "GPL-3.0.txt", "Qt-third-party.txt", "SOURCE.txt"):
        assert name not in left_out
    assert "if n not in NOT_IN_VIEWER]" in spec


def test_source_txt_names_the_shipped_versions_and_no_host_that_may_not_exist():
    """licenses/SOURCE.txt is the direction to the LGPL source that travels with the program and
    is published beside it. It must name the versions the build carries, and stay true wherever
    a release is published: no release of the project's own named by its address."""
    source = (LICENCES / "SOURCE.txt").read_text(encoding="utf-8")
    qt = locked()["pyside6-essentials"][0]
    assert f"qt-everywhere-src-{qt}.tar.xz" in source
    assert f"pyside-setup-everywhere-src-{qt}.zip" in source
    build_sh = (ROOT / "packaging" / "ffmpeg" / "build.sh").read_text(encoding="utf-8")
    ffmpeg = re.search(r"^FFMPEG_VERSION=(\S+)$", build_sh, re.M).group(1)
    assert f"ffmpeg-{ffmpeg}.tar.xz" in source
    for text in (source, notices()):
        assert "SolidSeas/SolidSeas/releases/tag/" not in text
        assert not re.search(r"releases/tag/(qt|ffmpeg)-[\d.]+-source", text)
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "'licenses\\SOURCE.txt'" in release


def test_the_wheel_metadata_declares_the_licences_of_what_it_carries():
    import tomllib

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    # three.js (MIT) ships in the wheel; the earcut port (ISC) is in the tessellator.
    assert set(re.split(r"\s+AND\s+", project["license"])) == {"Apache-2.0", "MIT", "ISC"}
    for name in project["license-files"]:
        assert (ROOT / name).is_file(), name
    assert "THIRD_PARTY_NOTICES.txt" in project["license-files"]
    assert "src/solidseas/serve/viewer/three/LICENSE" in project["license-files"]
