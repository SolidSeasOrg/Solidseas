"""Open in SolidCraft's plumbing (``solidseas_app.extensions.solidcraft.open_copy``): the
shown model written as STEP to a new file in SolidCraft's own folder, then started in
SolidCraft's desktop program from the extension's package. The package here is built
from stand-in programs, and the launcher is stood in for, so nothing is started (the
session guard in ``conftest.py`` refuses the real one); the real check needs Windows and
SolidCraft."""

import hashlib
import os
from pathlib import Path

import pytest

from solidseas_app import extensions as X
from solidseas_app.extensions import solidcraft as S
from support import FIXTURES, fixture_path


def _add(tmp_path: Path, programs=("solidcraft-cli.exe", "solidcraft.exe"), on: bool = True) -> None:
    from solidseas_app.extensions import package

    folder = tmp_path / "solidcraft-package"
    folder.mkdir()
    for name in programs:
        (folder / name).write_bytes(b"MZ a stand-in for " + name.encode())
    pkg = Path(package.build_package("solidcraft", str(folder), str(tmp_path / "zips")))
    accepted = {"solidcraft": [hashlib.sha256(pkg.read_bytes()).hexdigest()]}
    X.add_package(X.check_package(str(pkg), accepted=accepted))
    X.write_state(X.state_path(), X.switched(X.read_state(), "solidcraft", on))


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SOLIDSEAS_CACHE_DIR", str(tmp_path / "cache"))
    return tmp_path / "cache"


def test_the_desktop_program_is_found_only_in_a_package_that_is_on_and_unchanged(tmp_path, cache):
    with pytest.raises(X.HelperRefused, match="off"):
        S.desktop_program()
    _add(tmp_path)
    program = S.desktop_program()
    assert program == os.path.join(X.installed_dir("solidcraft"), "solidcraft.exe")
    with open(program, "ab") as fh:
        fh.write(b"changed")
    with pytest.raises(X.HelperRefused, match="not the file it was added with"):
        S.desktop_program()


def test_a_package_without_the_desktop_program_says_what_to_add(tmp_path, cache):
    _add(tmp_path, programs=("solidcraft-cli.exe",))
    with pytest.raises(X.HelperRefused, match="has no solidcraft.exe"):
        S.desktop_program()


def test_a_copy_never_takes_the_name_of_a_file_there(tmp_path):
    folder = tmp_path / "SolidCraft"
    folder.mkdir()
    assert S.copy_path("bracket", str(folder)) == str(folder / "bracket.step")
    (folder / "bracket.step").write_text("an earlier copy")
    (folder / "bracket (2).step").write_text("another")
    assert S.copy_path("bracket", str(folder)) == str(folder / "bracket (3).step")
    assert S.copy_path('a:b/c<d>"', str(folder)) == str(folder / "a_b_c_d_.step")
    assert S.copy_path(" . ", str(folder)) == str(folder / "model.step")


def test_open_copy_writes_the_step_into_solidcraft_s_folder_and_starts_the_program(tmp_path, cache):
    _add(tmp_path)
    started = []
    before = sorted(os.listdir(FIXTURES))
    got = S.open_copy(
        str(fixture_path("o02_boxA.SLDPRT")), str(FIXTURES), launch=lambda p, f: started.append((p, f))
    )
    assert got["ok"] and got["data"]["opened"] is True
    written = got["data"]["file"]
    assert os.path.dirname(written) == S.workspace() and os.path.basename(written) == "o02_boxA.step"
    assert Path(written).read_bytes().startswith(b"ISO-10303-21;") and got["data"]["solids"] == 1
    assert started == [(S.desktop_program(), written)]
    assert sorted(os.listdir(FIXTURES)) == before  # nothing beside the document
    # a second time gets a new name: the first copy, perhaps edited, is never replaced
    again = S.open_copy(str(fixture_path("o02_boxA.SLDPRT")), str(FIXTURES), launch=lambda p, f: None)
    assert os.path.basename(again["data"]["file"]) == "o02_boxA (2).step"
    # a STEP file is copied as it is
    step = S.open_copy(str(fixture_path("o02_boxA.step")), str(FIXTURES), launch=lambda p, f: None)
    assert Path(step["data"]["file"]).read_bytes() == fixture_path("o02_boxA.step").read_bytes()


def test_a_failed_export_starts_nothing(tmp_path, cache):
    _add(tmp_path)
    started = []
    refused = {"ok": False, "error": {"code": "not_representable"}}
    got = S.open_copy(
        str(fixture_path("o02_boxA.SLDPRT")),
        str(FIXTURES),
        export=lambda request: refused,
        launch=lambda p, f: started.append(f),
    )
    assert got is refused and started == []
    with pytest.raises(X.HelperRefused):
        X.write_state(X.state_path(), X.switched(X.read_state(), "solidcraft", False))
        part = str(fixture_path("o02_boxA.SLDPRT"))
        S.open_copy(part, str(FIXTURES), launch=lambda p, f: started.append(f))
    assert started == []
