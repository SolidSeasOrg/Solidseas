"""The viewer's 3D Print button (``solidseas_app.viewer.printing`` and ``.printaction``).

No program is ever started here: every window's launcher is replaced by a
recorder, and the session-wide guard of ``conftest.py`` replaces
:func:`printing.launch` itself, for every test module, with one that fails the
test. Program detection runs against made-up install folders and a made-up
registry; the real ones on the machine running the tests are never consulted,
so the results do not depend on what is installed. The export runs in its own
process here as in the viewer, except where a test stands in for it to hold it
open.

A print file goes next to its model, so every test that exports one works on a
copy of the fixtures (``models``) in its own temporary folder: nothing is ever
written into ``tests/fixtures``, which the session-wide guard checks.
"""

import errno
import hashlib
import json
import os
import shutil
import stat
import sys
import threading
import time
import types
import zipfile
from pathlib import Path

import pytest

from solidseas.errors import OutputRefusedError
from solidseas_app.viewer import opening, printing
from support import FIXTURES, fixture_path

try:
    import PySide6.QtWidgets  # noqa: F401
except ImportError:
    HAVE_QT = False
else:
    HAVE_QT = True

needs_qt = pytest.mark.skipif(not HAVE_QT, reason="PySide6 is not installed: the window is not tested")
# Taken when the module is imported, before conftest's guard replaces it: tested once,
# with subprocess.Popen stood in for.
REAL_LAUNCH = printing.launch
TODAY = "2026-10-03"  # the date the prints made here are named with
O16 = "o16_asm_features.SLDASM"
INNER = "o15_sub_asm-1/o07_boxB_h31-1"  # a part of o16's sub-assembly
VIRTUAL_INSTANCE = "Part12^o16_asm_features-1"  # a virtual part, stored inside o16
VIRTUAL_FILE = "Part12^o16_asm_features.SLDPRT"


@pytest.fixture
def models(tmp_path) -> Path:
    """A copy of the fixtures folder, for prints to go next to their models."""
    folder = tmp_path / "models"
    shutil.copytree(FIXTURES, folder)
    return folder


def _files(folder: Path) -> dict[str, tuple[str, int]]:
    """Every file below ``folder``: its content's hash and its modification time."""
    return {
        str(p.relative_to(folder)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


def test_the_session_guard_refuses_every_launch():
    with pytest.raises(AssertionError, match="tried to start"):
        printing.launch("slicer.exe", "x.3mf")


def _install(root: Path, rel: str) -> Path:
    exe = root / rel
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"MZ")
    exe.chmod(0o755)  # an executable outside Windows too
    return exe


@pytest.fixture
def programs(tmp_path) -> dict:
    """Program Files, Program Files (x86) and a per-user Programs folder holding Bambu
    Studio, two PrusaSlicer versions and two Cura versions, as installers lay them out."""
    pf, x86, local = tmp_path / "Program Files", tmp_path / "Program Files (x86)", tmp_path / "Local"
    for p in (pf, x86, local / "Programs"):
        p.mkdir(parents=True)
    env = {
        "ProgramW6432": str(pf),
        "ProgramFiles": str(pf),
        "ProgramFiles(x86)": str(x86),
        "LOCALAPPDATA": str(local),
    }
    return {
        "env": env,
        "bambu": _install(pf, "Bambu Studio/bambu-studio.exe"),
        "prusa": _install(pf, "Prusa3D/PrusaSlicer/prusa-slicer.exe"),
        "prusa_old": _install(pf, "Prusa3D/PrusaSlicer-2.5.2+win64/prusa-slicer.exe"),
        "cura_old": _install(pf, "Ultimaker Cura 4.10.0/Cura.exe"),
        "cura": _install(pf, "UltiMaker Cura 5.7.1/UltiMaker-Cura.exe"),
        "cura_empty": (pf / "Ultimaker Cura 4.7").mkdir() or None,
    }


def _detect(env, app_paths=None):
    app_paths = app_paths or {}
    return printing.detect(env, app_path=lambda exe: app_paths.get(exe), windows=True)


# --------------------------------------------------------------------------- finding programs
def test_detect_finds_the_known_slicers_in_their_install_folders(programs):
    found = {p.key: p for p in _detect(programs["env"])}
    assert list(found) == ["bambu", "prusa", "cura"]  # SLICERS order; OrcaSlicer is not installed
    assert (
        found["bambu"].path == os.path.normpath(programs["bambu"]) and found["bambu"].name == "Bambu Studio"
    )
    assert found["prusa"].path == os.path.normpath(programs["prusa"])  # the plain folder first
    assert found["cura"].path == os.path.normpath(programs["cura"])  # the newest version
    assert found["cura"].formats == ("3mf", "stl") and found["bambu"].formats == ("3mf", "stl", "step")


def test_detect_reads_app_paths_first_and_skips_what_is_not_there(programs, tmp_path):
    orca = _install(tmp_path / "Elsewhere", "orca-slicer.exe")
    found = _detect(
        programs["env"],
        {"orca-slicer.exe": str(orca), "bambu-studio.exe": str(tmp_path / "gone" / "bambu-studio.exe")},
    )
    assert [p.key for p in found] == ["bambu", "orca", "prusa", "cura"]
    by = {p.key: p.path for p in found}
    assert by["orca"] == str(orca) and by["bambu"] == os.path.normpath(programs["bambu"])
    assert printing.detect({}, windows=True) == [] and printing.detect(programs["env"], windows=False) == []


def test_detect_never_writes_the_registry():
    import ast

    source = Path(printing.__file__).read_text(encoding="utf-8")
    calls = {
        node.func.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not calls & {"SetValue", "SetValueEx", "CreateKey", "CreateKeyEx", "DeleteKey", "DeleteValue"}
    assert "KEY_READ" in source and "KEY_WRITE" not in source and "KEY_ALL_ACCESS" not in source


@pytest.mark.skipif(os.name != "nt", reason="the registry is Windows'")
def test_registry_app_path_reads_without_failing():
    # Whatever this machine has: a path or None, never an exception or a write.
    for exe in ("bambu-studio.exe", "no-such-program-solidseas.exe"):
        value = printing.registry_app_path(exe)
        assert value is None or isinstance(value, str)


# --------------------------------------------------------------------------- the choice
def test_bambu_studio_is_the_first_choice_when_installed(programs):
    found = _detect(programs["env"])
    first = printing.first_choice(found)
    assert first == printing.PrintChoice("bambu")
    assert printing.resolve(first, found).path == os.path.normpath(programs["bambu"])
    assert printing.first_choice([p for p in found if p.key != "bambu"]) is None
    assert "Bambu Studio" in printing.describe(printing.PrintChoice(), found)
    assert "asks" in printing.describe(printing.PrintChoice(), [])


def test_formats_follow_the_program(programs):
    found = {p.key: p for p in _detect(programs["env"])}
    cura, bambu = found["cura"], found["bambu"]
    assert printing.format_for(cura, printing.PrintChoice("cura")) == "3mf"
    assert printing.format_for(cura, printing.PrintChoice("cura", None, "stl")) == "stl"
    assert printing.format_for(bambu, printing.PrintChoice("bambu", None, "stl")) == "stl"
    assert printing.format_for(cura, printing.PrintChoice("cura", None, "step")) == "3mf"  # no STEP for Cura
    switched = printing.with_program(printing.PrintChoice("cura", None, "stl"), bambu)
    assert switched == printing.PrintChoice("bambu", None, "stl")  # Bambu Studio takes STL too
    dropped = printing.with_program(printing.PrintChoice("bambu", None, "step"), cura)
    assert dropped == printing.PrintChoice("cura")
    other = printing.other_program(str(programs["bambu"]))
    assert other.key == "other" and other.formats == ("3mf", "stl", "step")
    assert printing.describe(printing.PrintChoice("cura", None, "stl"), list(found.values())).startswith(
        "UltiMaker Cura, sent as STL"
    )


def test_a_program_no_longer_found_resolves_without_a_path(programs):
    gone = printing.resolve(printing.PrintChoice("orca"), _detect(programs["env"]))
    assert gone.name == "OrcaSlicer" and gone.path == ""
    assert "no longer found" in printing.describe(printing.PrintChoice("orca"), [])
    assert printing.resolve(printing.PrintChoice(), []) is None


class _Store:
    """Viewer.ini's sections in memory, as :class:`.settings.SettingsStore` keeps them
    for the print choice, without Qt: what ``load_section`` reads back is what
    ``save_section`` was given, as text, one value a line."""

    def __init__(self) -> None:
        self.sections: dict[str, dict[str, str]] = {}

    def load_section(self, name: str) -> dict[str, str]:
        return dict(self.sections.get(name, {}))

    def save_section(self, name: str, values) -> bool:
        assert values is None or all(len(v.splitlines()) == 1 for v in values.values()), values
        if values is None:
            self.sections.pop(name, None)
        else:
            self.sections[name] = dict(values)
        return True


def test_the_choice_round_trips_through_its_section(tmp_path):
    store = _Store()
    assert printing.load_choice(store) == printing.PrintChoice()
    for path in (
        str(tmp_path / "Tools" / "My Slicer.exe"),
        str(tmp_path / "Prüfung 中" / "slicer.exe"),
        str(tmp_path / ("a\u2028b\u2029c\x85d")) + os.sep + "slicer.exe",  # line breaks to str.splitlines
    ):
        choice = printing.PrintChoice("other", os.path.normpath(path), "stl")
        assert printing.save_choice(store, choice)
        assert store.sections["print"]["program"] == "other"
        assert printing.load_choice(store) == choice
    assert printing.save_choice(store, printing.PrintChoice("cura"))
    assert (
        printing.load_choice(store) == printing.PrintChoice("cura") and "path" not in store.sections["print"]
    )
    assert printing.save_choice(store, printing.PrintChoice()) and "print" not in store.sections


@needs_qt
def test_the_choice_is_remembered_in_viewer_ini(tmp_path):
    from solidseas_app.viewer.settings import SettingsStore

    odd = tmp_path / "Tools\u2028x" / "slicer.exe"  # U+2028 ended a line of Viewer.ini and reset it all
    store = SettingsStore(str(tmp_path / "Viewer.ini"))
    assert printing.save_choice(store, printing.PrintChoice("other", str(odd), "stl"))
    again = SettingsStore(str(tmp_path / "Viewer.ini"))
    assert printing.load_choice(again) == printing.PrintChoice("other", str(odd), "stl")
    assert again.load() is not None and again.reset_keys == []
    (tmp_path / "Viewer.ini").unlink()
    store = SettingsStore(str(tmp_path / "Viewer.ini"))
    exe = str(tmp_path / "Tools" / "My Slicer.exe")
    assert printing.load_choice(store) == printing.PrintChoice()
    assert printing.save_choice(store, printing.PrintChoice("other", exe, "stl"))
    assert printing.load_choice(SettingsStore(str(tmp_path / "Viewer.ini"))) == printing.PrintChoice(
        "other", exe, "stl"
    )
    text = (tmp_path / "Viewer.ini").read_text(encoding="utf-8")
    assert "[Print]" in text and "program=other" in text and "format=stl" in text
    store.save_session(None)  # other sections are kept as they are
    assert printing.load_choice(store) == printing.PrintChoice("other", exe, "stl")
    assert printing.save_choice(store, printing.PrintChoice("cura"))
    assert printing.load_choice(store) == printing.PrintChoice("cura")


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"program": "bambu", "format": "3mf"}, printing.PrintChoice("bambu", None, "3mf")),
        ({"program": "BAMBU", "format": "STL"}, printing.PrintChoice("bambu", None, "stl")),
        ({"program": "slicer9000"}, printing.PrintChoice()),
        ({"program": "other"}, printing.PrintChoice()),  # another program needs its path
        ({"program": "other", "path": '"relative.exe"'}, printing.PrintChoice()),
        ({"program": "other", "path": '"@Variant(x)"'}, printing.PrintChoice()),
        ({"program": "cura", "format": "obj"}, printing.PrintChoice("cura")),
        ({"program": "cura", "path": json.dumps(os.path.abspath("x.exe"))}, printing.PrintChoice("cura")),
    ],
)
def test_a_hand_edited_choice_is_checked(values, expected):
    assert printing.parse_choice(values) == expected


def test_only_an_executable_can_be_the_program(tmp_path):
    exe = tmp_path / "slicer.exe"
    exe.write_bytes(b"MZ")
    if os.name != "nt":
        exe.chmod(0o755)
    assert printing.program_problem(str(exe)) is None
    assert printing.program_problem("slicer.exe") is not None  # not a full path
    assert printing.program_problem(str(tmp_path / "missing.exe")) is not None
    assert printing.program_problem(str(tmp_path)) is not None  # a folder
    if os.name == "nt":
        for name in ("run.bat", "run.cmd", "run.ps1", "run.lnk", "run.js", "run.com"):
            (tmp_path / name).write_text("echo")
            assert "batch file" in printing.program_problem(str(tmp_path / name)), name


# --------------------------------------------------------------------------- the export folder
def test_the_export_folder_is_the_users_own(tmp_path):
    folder = printing.export_folder(str(tmp_path))
    assert os.path.isdir(folder) and os.path.dirname(folder) == str(tmp_path)
    assert printing.export_folder(str(tmp_path)) == folder
    if os.name != "nt":
        assert os.stat(folder).st_mode & 0o077 == 0


def test_a_linked_export_folder_is_refused(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    base = tmp_path / "base"
    base.mkdir()
    name = "SolidSeas Print" if os.name == "nt" else f"SolidSeas-Print-{os.getuid()}"
    if os.name == "nt":  # a junction needs no privilege
        import _winapi

        _winapi.CreateJunction(str(elsewhere), str(base / name))
    else:
        os.symlink(elsewhere, base / name, target_is_directory=True)
    with pytest.raises(OutputRefusedError) as exc:
        printing.export_folder(str(base))
    assert exc.value.detail["rule"] == "link" and not list(elsewhere.iterdir())


@pytest.mark.parametrize(
    ("name", "stem"),
    [
        ("bracket", "bracket"),
        ("bracket (Long)", "bracket (Long)"),
        ('a/b\\c:d*e?f"g<h>i|j', "a_b_c_d_e_f_g_h_i_j"),
        ("деталь", "деталь"),
        ("  .hidden. ", "hidden"),
        ("CON", "_CON"),
        ("nul.txt", "_nul.txt"),
        ("nul .x", "_nul .x"),  # Windows reads a device name and spaces before a dot as the device
        ("con .a", "_con .a"),
        ("aux  .b", "_aux  .b"),
        ("COM1 .x", "_COM1 .x"),
        ("lpt1 .y", "_lpt1 .y"),
        ("Nul ", "_Nul"),
        ("console", "console"),
        ("nul x", "nul x"),
        ("", "model"),
        ("...", "model"),
        ("x" * 200, "x" * 80),
        ("a;b&c|d`e$f%g", "a_b_c_d_e_f_g"),
    ],
)
def test_export_names_are_sanitized(name, stem):
    assert printing.safe_stem(name) == stem


def test_old_exports_are_cleaned_and_nothing_else(tmp_path):
    folder = Path(printing.export_folder(str(tmp_path)))
    now = time.time()
    old, new, other = folder / "old.3mf", folder / "new.stl", folder / "notes.txt"
    stale = folder / ".old.3mf.1234.part"
    for p in (old, new, other, stale):
        p.write_bytes(b"x")
    week = printing.KEEP_SECONDS
    for p in (old, other, stale):
        os.utime(p, (now - week - 60, now - week - 60))
    sub = folder / "kept.3mf"
    sub.mkdir()  # a folder named like an export is left alone
    assert printing.clean_old(str(folder), now=now) == 2
    assert sorted(p.name for p in folder.iterdir()) == ["kept.3mf", "new.stl", "notes.txt"]


def _export(models: Path, name: str, fmt: str = "3mf", tmp: Path | None = None, **kw) -> dict:
    kw.setdefault("date", TODAY)
    base = str(tmp) if tmp is not None else str(models.parent / "temp")
    os.makedirs(base, exist_ok=True)  # the system's temporary folder, always there
    return printing.export_for_print(str(models / name), str(models), fmt, out_base=base, **kw)


def test_export_for_print_writes_next_to_the_model_named_with_the_date(models):
    before = _files(models)
    out = _export(models, "o02_boxA.SLDPRT")
    assert out["file"] == str(models / f"o02_boxA {TODAY}.3mf") and out["closed"] and out["triangles"] == 12
    assert out["place"] == printing.MODEL and out["fallback"] is None and out["stem"] == f"o02_boxA {TODAY}"
    assert out["model_folder"] == out["out_folder"] == str(models) and out["date"] == TODAY
    with zipfile.ZipFile(out["file"]) as z:
        assert "3D/3dmodel.model" in z.namelist()
    again = _export(models, "o02_boxA.SLDPRT", "stl")
    third = _export(models, "o02_boxA.SLDPRT")
    fourth = _export(models, "o02_boxA.SLDPRT")
    assert os.path.basename(again["file"]) == f"o02_boxA {TODAY}.stl"  # each format counts its own
    assert os.path.basename(third["file"]) == f"o02_boxA {TODAY} (2).3mf"
    assert os.path.basename(fourth["file"]) == f"o02_boxA {TODAY} (3).3mf"
    asm = _export(models, O16, configuration="Lite")
    assert asm["file"] == str(models / f"o16_asm_features (Lite) {TODAY}.3mf")
    assert asm["items"] == 10 and asm["doc_type"] == "assembly" and asm["closed"]
    active = _export(models, O16, configuration="Default")  # the active one: not in the name
    assert os.path.basename(active["file"]) == f"o16_asm_features {TODAY}.3mf" and active["items"] == 12
    assert not [n for n in os.listdir(models) if n.endswith(".part")]  # each named once written
    assert not os.path.exists(printing.export_folder_path(str(models.parent / "temp")))  # never made
    after = _files(models)
    assert {k: v for k, v in after.items() if k in before} == before  # what was there is untouched
    assert sorted(set(after) - set(before)) == sorted(
        os.path.basename(o["file"]) for o in (out, again, third, fourth, asm, active)
    )


def test_a_model_file_of_another_format_prints_from_its_scene(models):
    """An STL goes through 3D Print as a SOLIDWORKS part does: opened as a model file in
    the export's own process, welded, checked closed and written next to it, marked
    (STL) as o02_boxA.SLDPRT is beside it."""
    out = _export(models, "o02_boxA.STL")
    assert out["file"] == str(models / f"o02_boxA (STL) {TODAY}.3mf") and out["format_mark"] == "STL"
    assert out["closed"] and out["triangles"] == 12
    assert out["doc_type"] == "part" and out["display_mesh_objects"] == 0
    assert "units_assumed" in {w["code"] for w in out["warnings"]}
    with zipfile.ZipFile(out["file"]) as z:
        assert "3D/3dmodel.model" in z.namelist()


def test_a_new_print_is_numbered_past_the_highest_of_the_day(models):
    """The highest number is the newest print of the day, even when the user deleted some
    in between; other names, formats and days keep their own numbers, and no file that
    is there is opened, renamed or replaced."""
    stem = f"o02_boxA {TODAY}"
    planted = {
        f"{stem}.3mf": b"first",
        f"{stem} (4).3mf": b"fourth",  # (2) and (3) were deleted
        f"O02_BOXA {TODAY} (7).STL": b"another format",
        f"{stem} (x).3mf": b"not a number",
        f"{stem}-copy (9).3mf": b"another name",
        "o02_boxA 2026-10-02 (8).3mf": b"another day",
    }
    for name, data in planted.items():
        (models / name).write_bytes(data)
    before = _files(models)
    out = _export(models, "o02_boxA.SLDPRT")
    assert os.path.basename(out["file"]) == f"{stem} (5).3mf"
    stl = _export(models, "o02_boxA.SLDPRT", "stl")
    assert os.path.basename(stl["file"]) == f"{stem} (8).stl"
    after = _files(models)
    assert {k: v for k, v in after.items() if k in before} == before
    assert printing.highest_number(str(models), stem, ".3mf") == 5
    assert printing.highest_number(str(models), "nothing like it", ".3mf") == 0
    assert printing.highest_number(str(models / "no such folder"), stem, ".3mf") == 0


def test_print_names_are_the_document_and_the_date():
    assert printing.print_stem("bracket", TODAY) == f"bracket {TODAY}"
    assert printing.print_stem("frame (Lite)", TODAY) == f"frame (Lite) {TODAY}"
    assert printing.print_stem("nul", TODAY) == f"_nul {TODAY}"  # never a device name
    assert printing.print_stem("x" * 200, TODAY) == "x" * 80 + f" {TODAY}"
    for bad in ("", "2026-1-3", "today", "2026-10-03 (2)", "../2026-10-03"):
        with pytest.raises(ValueError):
            printing.print_stem("bracket", bad)
    assert list(printing.candidate_names("b", ".3mf"))[:3] == ["b.3mf", "b (2).3mf", "b (3).3mf"]
    assert next(printing.candidate_names("b", ".3mf", 5)) == "b (5).3mf"
    assert next(printing.candidate_names("b", ".3mf", 1001)) == "b (1001).3mf"  # no cap at a thousand
    assert len(list(printing.candidate_names("b", ".3mf", 1001))) == printing.MAX_TRIES
    assert list(printing.candidate_names("b", ".3mf", printing.MAX_NUMBER))[-1] == "b (9999999).3mf"
    assert list(printing.candidate_names("b", ".3mf", printing.MAX_NUMBER + 1)) == []
    assert len(printing.today()) == 10 and printing.print_stem("b", printing.today())


def test_a_long_name_keeps_the_configuration_in_the_print_name():
    """The configuration keeps its place however long the document's name: the name is cut
    first, so prints of two configurations never share a name or its numbering."""
    long = "Housing bottom shell with snap fits and bosses for the M3 threaded inserts rev C"
    lite = printing.print_label(long, "Lite")
    assert lite.endswith(" (Lite)") and len(lite) == printing.MAX_STEM and lite.startswith(long[:60])
    assert printing.print_label(long) == long[: printing.MAX_STEM]
    assert len({printing.print_label(long, c) for c in ("Lite", "Light", "Heavy", None)}) == 4
    cfg = printing.print_label("frame", "c" * 200)  # a configuration has a cap of its own
    assert cfg == "frame (" + "c" * printing.MAX_CONFIG_STEM + ")"
    assert printing.print_label("frame", "a/b:c") == "frame (a_b_c)"
    assert printing.print_label("frame", assembly=True) == "frame (assembly)"
    assert printing.print_label("frame", "Lite", assembly=True) == "frame (assembly) (Lite)"
    assert (
        printing.print_label("nul", "Lite") == "_nul (Lite)"
        and printing.print_label("x" * 200, "L")[-4:] == " (L)"
    )
    assert printing.document_name("Part12^o16_asm_features.SLDPRT") == "Part12^o16_asm_features"
    assert printing.document_name("v1.2 bracket") == "v1.2 bracket"  # only a SOLIDWORKS extension goes


def test_long_names_and_configurations_print_apart(models):
    long = "Housing bottom shell with snap fits and bosses for the M3 threaded inserts rev C"
    shutil.copy2(models / O16, models / f"{long}.SLDASM")
    lite = _export(models, f"{long}.SLDASM", configuration="Lite")
    default = _export(models, f"{long}.SLDASM", configuration="Default")
    assert os.path.basename(lite["file"]) == f"{printing.print_label(long, 'Lite')} {TODAY}.3mf"
    assert lite["items"] == 10 and lite["named_configuration"] == "Lite"
    assert os.path.basename(default["file"]) == f"{long} {TODAY}.3mf"  # the active one: no number taken
    assert default["items"] == 12 and default["named_configuration"] is None


def test_an_assembly_named_as_a_part_beside_it_says_it_is_one(models):
    """A part and an assembly of one name in one folder never share a numbering: the
    assembly's print says it is the assembly, so (2) is always a newer print of the same."""
    shutil.copy2(models / "o08_asm_2x_boxA.SLDASM", models / "o02_boxA.SLDASM")
    part = _export(models, "o02_boxA.SLDPRT")
    asm = _export(models, "o02_boxA.SLDASM")
    again = _export(models, "o02_boxA.SLDPRT")
    assert os.path.basename(part["file"]) == f"o02_boxA {TODAY}.3mf" and part["triangles"] == 12
    assert os.path.basename(asm["file"]) == f"o02_boxA (assembly) {TODAY}.3mf" and asm["assembly_mark"]
    assert asm["triangles"] == 24 and asm["doc_type"] == "assembly"
    assert os.path.basename(again["file"]) == f"o02_boxA {TODAY} (2).3mf"
    # Without a part of its name beside it, an assembly is named as any document is.
    alone = _export(models, "o08_asm_2x_boxA.SLDASM")
    assert os.path.basename(alone["file"]) == f"o08_asm_2x_boxA {TODAY}.3mf" and not alone["assembly_mark"]


def test_a_part_is_named_after_the_configuration_it_was_exported_in(models):
    """A part that stores no bodies of the configuration asked for is exported in its active
    one, with a warning: the file is named after what it holds, and says which."""
    out = _export(models, "o06_boxA_props_mat_cfg.SLDPRT", configuration="OracleAlt")
    assert out["configuration"] == "Default" and out["requested_configuration"] == "OracleAlt"
    assert os.path.basename(out["file"]) == f"o06_boxA_props_mat_cfg {TODAY}.3mf"
    assert out["named_configuration"] is None
    assert "mesh_configuration_differs" in [w["code"] for w in out["warnings"]]


def test_a_stray_high_number_never_stops_a_print(models):
    """A file numbered past a thousand only moves the next number on; only the highest
    number a print is given sends one to the temporary folder, and the reason says so."""
    stem = f"o02_boxA {TODAY}"
    (models / f"{stem} (1000).3mf").write_bytes(b"stray")
    out = _export(models, "o02_boxA.SLDPRT")
    assert out["place"] == printing.MODEL and os.path.basename(out["file"]) == f"{stem} (1001).3mf"
    (models / f"{stem} ({printing.MAX_NUMBER}).3mf").write_bytes(b"the last")
    full = _export(models, "o02_boxA.SLDPRT")
    assert full["place"] == printing.TEMP and full["fallback"] == printing.FULL
    assert "numbered 9,999,999" in printing.FULL and "1,000" not in printing.FULL
    assert not [n for n in os.listdir(models) if n.endswith(".part")]


def test_two_prints_at_once_never_take_one_name(tmp_path):
    """The name is claimed by a rename that refuses a name taken: one claimed by another
    print since the folder was looked at is passed over, and it is left as it was."""
    folder = tmp_path
    (folder / "b (2).3mf").write_bytes(b"theirs")
    part = folder / ".token.part"
    part.write_bytes(b"mine")
    got = printing._claim(str(part), str(folder), printing.candidate_names("b", ".3mf", 2))
    assert got == str(folder / "b (3).3mf") and Path(got).read_bytes() == b"mine" and not part.exists()
    assert (folder / "b (2).3mf").read_bytes() == b"theirs"


# --------------------------------------------------------------------------- where it cannot go
def test_a_model_folder_that_refuses_the_file_falls_back_to_the_temporary_folder(models, monkeypatch):
    real = printing._write_named

    def refused(model, folder, fmt, stem, token):
        if os.path.normcase(folder) == os.path.normcase(str(models)):
            raise PermissionError(13, "Access is denied")
        return real(model, folder, fmt, stem, token)

    monkeypatch.setattr(printing, "_write_named", refused)
    before = _files(models)
    out = _export(models, "o02_boxA.SLDPRT")
    temp = printing.export_folder(str(models.parent / "temp"))
    assert out["place"] == printing.TEMP and out["fallback"] == printing.DENIED
    assert out["file"] == os.path.join(temp, f"o02_boxA {TODAY}.3mf") and out["model_folder"] == str(models)
    assert _files(models) == before


def test_why_a_write_failed_is_said_plainly():
    assert printing.write_problem(PermissionError(13, "Access is denied")) == printing.DENIED
    assert printing.write_problem(OSError(errno.EROFS, "Read-only file system")) == printing.READ_ONLY
    taken = OutputRefusedError("taken", detail={"rule": "exists"})
    assert printing.write_problem(taken) == printing.TAKEN
    full = OutputRefusedError("full", detail={"rule": "exists", "highest": printing.MAX_NUMBER})
    assert printing.write_problem(full) == printing.FULL
    assert "could not be written (No space left" in printing.write_problem(
        OSError(28, "No space left on device")
    )
    if os.name == "nt":
        protected = OSError(None, "The media is write protected", None, 19)
        assert printing.write_problem(protected) == printing.READ_ONLY
    no_links = OutputRefusedError("no links", detail={"rule": printing.NO_HARD_LINKS})
    assert printing.write_problem(no_links) == printing.NO_LINKS


# Outside Windows a print file is named by a second link to its part (rename_new), which a
# file system without hard links refuses: EPERM on Linux (FAT, exFAT, a FUSE file system
# without them, as link(2) says), EOPNOTSUPP from an SMB share that refuses them, ENOSYS from
# an older FUSE. EPERM reaches Python as a PermissionError, which once read as "denied".
no_links_here = pytest.mark.skipif(os.name == "nt", reason="Windows names a new file by a rename, not a link")


def _refuse_links_in(folder: Path, monkeypatch, code: int) -> list[str]:
    """Make every link into ``folder`` fail with ``code``, as a file system without hard
    links fails it; the names asked for there."""
    real = os.link
    asked: list[str] = []

    def link(src, dst, *args, **kwargs):
        if os.path.dirname(os.path.abspath(dst)) == str(folder):
            asked.append(str(dst))
            raise OSError(code, os.strerror(code))
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "link", link)
    return asked


@no_links_here
@pytest.mark.parametrize("code", [errno.EPERM, errno.EOPNOTSUPP, errno.ENOSYS])
def test_a_file_system_without_hard_links_is_said_to_be_one_not_permission_denied(models, monkeypatch, code):
    """The link that names the print file is refused: the print goes to the temporary
    folder as before, saying why, and nothing is left next to the model, its part
    included."""
    asked = _refuse_links_in(models, monkeypatch, code)
    before = _files(models)
    out = _export(models, "o02_boxA.SLDPRT")
    assert asked == [str(models / f"o02_boxA {TODAY}.3mf")]
    assert out["place"] == printing.TEMP and out["fallback"] == printing.NO_LINKS
    temp = printing.export_folder(str(models.parent / "temp"))
    assert out["file"] == os.path.join(temp, f"o02_boxA {TODAY}.3mf") and os.path.isfile(out["file"])
    assert _files(models) == before


@no_links_here
def test_only_a_link_the_file_system_refuses_reads_as_one_without_hard_links(tmp_path, monkeypatch):
    part = tmp_path / ".0123456789abcdef.part"
    part.write_bytes(b"mine")
    _refuse_links_in(tmp_path, monkeypatch, errno.EPERM)
    with pytest.raises(OutputRefusedError) as err:
        printing._claim(str(part), str(tmp_path), printing.candidate_names("b", ".3mf"))
    assert err.value.detail == {"rule": printing.NO_HARD_LINKS, "errno": "EPERM"}
    assert os.listdir(tmp_path) == [part.name]  # nothing named; the caller removes its part
    _refuse_links_in(tmp_path, monkeypatch, errno.EACCES)  # a folder that really denies it
    with pytest.raises(PermissionError) as denied:
        printing._claim(str(part), str(tmp_path), printing.candidate_names("b", ".3mf"))
    assert printing.write_problem(denied.value) == printing.DENIED


@no_links_here
def test_export_for_3d_printing_says_a_folder_without_hard_links_is_one(models, tmp_path, monkeypatch):
    from solidseas_app.viewer.wording import refusal_text

    out_dir = tmp_path / "stick"
    out_dir.mkdir()
    _refuse_links_in(out_dir, monkeypatch, errno.EPERM)
    with pytest.raises(OutputRefusedError) as err:
        printing.export_to_folder(str(models / "o02_boxA.SLDPRT"), str(models), "3mf", str(out_dir))
    assert err.value.detail["rule"] == printing.NO_HARD_LINKS and os.listdir(out_dir) == []
    assert "FAT or exFAT" in refusal_text({"detail": err.value.detail})


@no_links_here
@pytest.mark.parametrize("fstype", ["vfat", "msdos", "exfat"])
def test_a_folder_on_a_fat_or_exfat_drive_is_known_before_anything_is_written(models, monkeypatch, fstype):
    """The mount table says a FAT or exFAT drive keeps no hard links: a print of a model
    there goes to the temporary folder without anything, not even its part, written
    beside the model first."""
    from solidseas import netfs

    stick = models / "stick"
    stick.mkdir()
    shutil.copy2(models / "o02_boxA.SLDPRT", stick / "o02_boxA.SLDPRT")
    monkeypatch.setattr(netfs, "mount_table", lambda: [("/", "ext4"), (str(stick), fstype)])
    asked = _refuse_links_in(stick, monkeypatch, errno.EPERM)
    assert printing.folder_problem(str(stick), str(models)) == printing.NO_LINKS
    assert printing.folder_problem(str(models), str(models)) is None  # the drive around it
    out = _export(models, "stick/o02_boxA.SLDPRT")
    assert out["place"] == printing.TEMP and out["fallback"] == printing.NO_LINKS
    assert asked == [] and os.listdir(stick) == ["o02_boxA.SLDPRT"]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the mount table faked here is Linux's")
@pytest.mark.parametrize("fstype", ["nfs4", "cifs", "fuse.sshfs"])
def test_a_network_mount_outside_the_opened_folder_never_takes_a_print(models, tmp_path, monkeypatch, fstype):
    """A share is a mount like any other here, its type in the mount table
    (:mod:`solidseas.netfs`): a model found on one outside the opened folder prints to the
    temporary folder, nothing written on the share; the share opened is the user's choice."""
    from solidseas import netfs

    share = tmp_path / "share"
    share.mkdir()
    shutil.copy2(models / "o02_boxA.SLDPRT", share / "o02_boxA.SLDPRT")
    monkeypatch.setattr(netfs, "mount_table", lambda: [("/", "ext4"), (str(share), fstype)])
    out = printing.export_for_print(
        str(share / "o02_boxA.SLDPRT"),
        str(models),
        "3mf",
        within=str(share),
        out_base=str(tmp_path),
        date=TODAY,
    )
    assert out["place"] == printing.TEMP and out["fallback"] == printing.NETWORK
    assert os.listdir(share) == ["o02_boxA.SLDPRT"]
    opened = _export(share, "o02_boxA.SLDPRT", tmp=tmp_path)
    assert opened["place"] == printing.MODEL and opened["file"] == str(share / f"o02_boxA {TODAY}.3mf")


def test_only_a_plain_folder_takes_a_print(models, tmp_path):
    assert printing.folder_problem(str(models), str(models)) is None
    (models / "sub" / "deeper").mkdir(parents=True)
    assert printing.folder_problem(str(models / "sub" / "deeper"), str(models)) is None
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert printing.folder_problem(str(elsewhere), str(models)) is None  # found outside, on this computer
    assert printing.folder_problem(str(models / "no such folder"), str(models)).startswith(
        "the model's folder could not be looked at"
    )
    (models / "a file").write_bytes(b"x")
    assert printing.folder_problem(str(models / "a file"), str(models)) == printing.NOT_A_FOLDER
    assert printing.folder_problem("", str(models)) == printing.ODD_PATH


def _link_folder(target: Path, link: Path) -> None:
    if os.name == "nt":  # a junction needs no privilege
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def test_a_print_never_goes_through_a_link_or_a_junction(models, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    _link_folder(real, models / "linked")
    _link_folder(real, tmp_path / "linked outside")
    _link_folder(models, tmp_path / "opened through a link")
    (models / "linked" / "deeper").mkdir()
    assert printing.folder_problem(str(models / "linked"), str(models)) == printing.LINKED
    assert printing.folder_problem(str(models / "linked" / "deeper"), str(models)) == printing.LINKED
    assert printing.folder_problem(str(tmp_path / "linked outside"), str(models)) == printing.LINKED
    opened = tmp_path / "opened through a link"
    assert printing.folder_problem(str(opened), str(opened)) == printing.LINKED
    # A part found outside the opened folder, in a linked folder: read there, printed elsewhere.
    shutil.copy2(models / "o02_boxA.SLDPRT", real / "o02_boxA.SLDPRT")
    outside = tmp_path / "linked outside"
    out = printing.export_for_print(
        str(outside / "o02_boxA.SLDPRT"),
        str(models),
        "3mf",
        within=str(outside),
        out_base=str(tmp_path),
        date=TODAY,
    )
    assert out["place"] == printing.TEMP and out["fallback"] == printing.LINKED
    assert sorted(os.listdir(real)) == ["deeper", "o02_boxA.SLDPRT"]


def test_a_link_above_the_models_folder_is_seen_whichever_folder_was_opened(models, tmp_path):
    """The folders from the drive's root down are looked at, not only those below the
    folder opened: a junction above a model found outside the opened folder, or above the
    folder opened, sends the print to the temporary folder as one below it does."""
    real = tmp_path / "Real"
    (real / "sub").mkdir(parents=True)
    _link_folder(real, tmp_path / "lib")
    shutil.copy2(models / "o02_boxA.SLDPRT", real / "sub" / "o02_boxA.SLDPRT")
    outside = tmp_path / "lib" / "sub"
    assert printing.folder_problem(str(outside), str(models)) == printing.LINKED
    out = printing.export_for_print(
        str(outside / "o02_boxA.SLDPRT"),
        str(models),
        "3mf",
        within=str(outside),
        out_base=str(tmp_path),
        date=TODAY,
    )
    assert out["place"] == printing.TEMP and out["fallback"] == printing.LINKED
    assert sorted(os.listdir(real / "sub")) == ["o02_boxA.SLDPRT"]
    # A folder opened below a junction: the same answer as opening the junction itself.
    _link_folder(models, tmp_path / "Projects")
    (models / "Job").mkdir()
    shutil.copy2(models / "o02_boxA.SLDPRT", models / "Job" / "o02_boxA.SLDPRT")
    job = tmp_path / "Projects" / "Job"
    projects = str(tmp_path / "Projects")
    assert printing.folder_problem(str(job), str(job)) == printing.LINKED
    assert printing.folder_problem(str(job), projects) == printing.folder_problem(projects, projects)
    out = _export(models.parent / "Projects" / "Job", "o02_boxA.SLDPRT", tmp=tmp_path)
    assert out["place"] == printing.TEMP and out["fallback"] == printing.LINKED
    assert sorted(os.listdir(models / "Job")) == ["o02_boxA.SLDPRT"]
    # Every folder from the root down is named, the root first.
    chain = printing.ancestry(str(models / "Job"))
    assert chain[-1] == str(models / "Job") and chain[-2] == str(models)
    assert os.path.dirname(chain[0]) == chain[0]  # the root


@pytest.mark.skipif(os.name != "nt", reason="drive letters, UNC paths and streams are Windows'")
def test_network_folders_devices_and_streams_never_take_a_print(models, monkeypatch):
    # Text only: nothing here is looked at, so no server is contacted.
    looked: list[str] = []
    real_lstat = os.lstat
    monkeypatch.setattr(os, "lstat", lambda p, *a, **k: looked.append(str(p)) or real_lstat(p, *a, **k))
    assert printing.folder_problem(r"\\server\share\jobs", str(models)) == printing.NETWORK
    assert printing.folder_problem(r"\\?\C:\jobs", str(models)) == printing.ODD_PATH
    assert printing.folder_problem(r"\\.\C:\jobs", str(models)) == printing.ODD_PATH
    assert printing.folder_problem(r"C:\jobs\file.3mf:stream", str(models)) == printing.ODD_PATH
    monkeypatch.setattr(printing, "drive_type", lambda root: printing.DRIVE_REMOTE)  # a mapped drive
    assert printing.folder_problem(r"Z:\jobs", str(models)) == printing.NETWORK
    assert looked == []
    # The folder the user opened may be a share: what is inside it is the user's choice.
    assert printing.folder_problem(str(models), str(models)) is None


def test_a_cloud_placeholder_folder_never_takes_a_print(models, monkeypatch):
    real_lstat = os.lstat
    cloud = str(models / "cloud")
    os.mkdir(cloud)

    def lstat(path, *args, **kwargs):
        if os.path.normcase(str(path)) == os.path.normcase(cloud):
            return types.SimpleNamespace(
                st_mode=stat.S_IFDIR | 0o755, st_file_attributes=0x400000, st_reparse_tag=0
            )
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", lstat)
    assert printing.folder_problem(cloud, str(models)) == printing.PLACEHOLDER


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="a folder's mode, for an account not root")
def test_a_read_only_folder_never_takes_a_print(models):
    (models / "locked").mkdir()
    shutil.copy2(models / "o02_boxA.SLDPRT", models / "locked" / "o02_boxA.SLDPRT")
    os.chmod(models / "locked", 0o555)
    try:
        assert printing.folder_problem(str(models / "locked"), str(models)) == printing.READ_ONLY
        out = _export(models, "locked/o02_boxA.SLDPRT")
        assert out["place"] == printing.TEMP and out["fallback"] == printing.READ_ONLY
        assert os.listdir(models / "locked") == ["o02_boxA.SLDPRT"]
    finally:
        os.chmod(models / "locked", 0o755)


def test_nothing_next_to_a_model_is_ever_removed(models, monkeypatch):
    """The week-old cleanup is the temporary folder's alone: old prints, old parts and old
    exports next to a model stay whatever is printed there, and only the temporary folder
    is cleaned when a print goes there."""
    old = time.time() - 2 * printing.KEEP_SECONDS
    planted = [
        models / "an old print.3mf",
        models / "an old print.stl",
        models / ".0123456789abcdef.part",
        models / f"o02_boxA {TODAY}.3mf",
    ]
    for p in planted:
        p.write_bytes(b"keep")
        os.utime(p, (old, old))
    cleaned: list[str] = []
    real_clean = printing.clean_old

    def clean(folder, **kwargs):
        cleaned.append(folder)
        return real_clean(folder, **kwargs)

    monkeypatch.setattr(printing, "clean_old", clean)
    out = _export(models, "o02_boxA.SLDPRT")
    assert out["place"] == printing.MODEL and cleaned == []
    temp = Path(printing.export_folder(str(models.parent / "temp")))
    stale = temp / "stale.3mf"
    stale.write_bytes(b"x")
    os.utime(stale, (old, old))
    out = _export(models, "o02_boxA.SLDPRT", next_to_model=False)  # the setting off
    assert out["place"] == printing.TEMP and out["fallback"] is None and not stale.exists()
    assert cleaned == [str(temp)]
    real_write = printing._write_named

    def refused(model, folder, fmt, stem, token):
        if os.path.normcase(folder) == os.path.normcase(str(models)):
            raise PermissionError(13, "Access is denied")
        return real_write(model, folder, fmt, stem, token)

    monkeypatch.setattr(printing, "_write_named", refused)
    out = _export(models, "o02_boxA.SLDPRT")  # a fallback cleans the temporary folder only
    assert out["place"] == printing.TEMP and cleaned == [str(temp), str(temp)]
    assert all(p.read_bytes() == b"keep" for p in planted)
    # The source calls it once, on the temporary folder it has just made.
    source = Path(printing.__file__).read_text(encoding="utf-8")
    assert (
        source.count("clean_old(") == 2 and "out = export_folder(out_base)\n        clean_old(out)" in source
    )


# --------------------------------------------------------------------------- the export's own process
def _request(models: Path, name="o02_boxA.SLDPRT", fmt="3mf", **kw) -> dict:
    (models.parent / "temp").mkdir(exist_ok=True)  # the system's temporary folder, always there
    return {
        "path": str(models / name),
        "folder": str(models),
        "fmt": fmt,
        "out_base": str(models.parent / "temp"),
        "date": TODAY,
        **kw,
    }


def test_the_export_runs_in_a_process_of_its_own(models):
    before = _files(models)
    result = printing.export_in_process(_request(models))
    assert result["ok"], result
    data = result["data"]
    assert (
        data["file"] == str(models / f"o02_boxA {TODAY}.3mf") and data["closed"] and data["triangles"] == 12
    )
    assert data["display_mesh_objects"] == 0 and os.path.getsize(data["file"]) == data["bytes"]
    assert set(_files(models)) - set(before) == {f"o02_boxA {TODAY}.3mf"}
    empty = printing.export_in_process(_request(models, "o01_empty.SLDPRT"))
    assert not empty["ok"] and empty["error"]["code"] == "nothing_to_export"
    assert set(_files(models)) - set(before) == {f"o02_boxA {TODAY}.3mf"}
    temp = printing.export_in_process(_request(models, next_to_model=False))
    folder = printing.export_folder(str(models.parent / "temp"))
    assert temp["ok"] and temp["data"]["file"] == os.path.join(folder, f"o02_boxA {TODAY}.3mf")
    assert temp["data"]["place"] == printing.TEMP and temp["data"]["fallback"] is None


def test_a_cancelled_export_ends_its_process_and_leaves_nothing(models):
    before = _files(models)
    t0 = time.monotonic()
    answers = iter([False])  # not before it starts; at the first look while it runs, 50 ms in,
    # well before a new process has even read the part
    result = printing.export_in_process(_request(models, "o11_curved.SLDPRT"), lambda: next(answers, True))
    assert result == printing.CANCELLED
    assert time.monotonic() - t0 < 5  # ended, not waited for
    assert _files(models) == before
    assert printing.export_in_process(_request(models), lambda: True) == printing.CANCELLED  # never started
    temp = printing.export_folder_path(str(models.parent / "temp"))
    assert _files(models) == before and (not os.path.exists(temp) or os.listdir(temp) == [])


def test_a_stopped_export_leaves_no_part_next_to_the_model(models, monkeypatch):
    """What a process ended while writing leaves, its part by its random name, is removed
    from next to the model and from the temporary folder; nothing else there is."""
    from solidseas_app.viewer import meshproc

    made: list[str] = []

    class Proc:
        def is_alive(self) -> bool:
            return False

        def join(self, *_a) -> None:
            pass

        def kill(self) -> None:
            pass

    class Conn:
        def send_bytes(self, raw) -> None:  # the child got as far as its part, then stopped
            request = json.loads(raw)
            for folder in (str(models), printing.export_folder(request["out_base"])):
                part = printing.part_path(folder, request["token"])
                Path(part).write_bytes(b"half")
                made.append(part)

        def poll(self, _t) -> bool:
            return False

        def close(self) -> None:
            pass

    monkeypatch.setattr(meshproc, "_start", lambda memory, target, name: (Proc(), Conn(), None))
    before = _files(models)
    (models / ".someone-else.part").write_bytes(b"theirs")
    result = printing.export_in_process(_request(models))
    assert result["ok"] is False and result["error"]["code"] == "print_export_stopped"
    assert len(made) == 2 and not any(os.path.exists(p) for p in made)
    assert (models / ".someone-else.part").read_bytes() == b"theirs"
    assert {k: v for k, v in _files(models).items() if k != ".someone-else.part"} == before


def test_a_part_left_by_a_viewer_that_ended_is_removed_by_the_next_print(models, monkeypatch):
    """A viewer ended while it wrote an export (a crash, End task) leaves its part next to
    the model, named to say what it is, and the record of it in the temporary folder: the
    next 3D Print removes that part, by its own name, and the record. A record whose
    window still holds it open is an export that runs: nothing of it is touched, and
    nothing else next to the model is."""
    temp = str(models.parent / "temp")
    os.makedirs(temp, exist_ok=True)
    folders = [printing.export_folder_path(temp), str(models)]
    dead, live = "0123456789abcdef", "fedcba9876543210"
    dead_journal = printing._journal(temp, dead, folders)
    live_journal = printing._journal(temp, live, folders)
    parts = {t: Path(printing.part_path(str(models), t)) for t in (dead, live)}
    for part in parts.values():
        part.write_bytes(b"half written")
    assert parts[dead].name == ".solidseas-print-0123456789abcdef.part"
    dead_journal[0].close()  # the viewer ended: its handle closed, the record left behind
    (models / ".solidseas-print-not-a-token.part").write_bytes(b"not one of ours")
    (models / ".0123456789abcdef.part").write_bytes(b"another name")
    before = {k: v for k, v in _files(models).items() if k != parts[dead].name}
    result = printing.export_in_process(_request(models))
    assert result["ok"], result
    assert not parts[dead].exists() and not os.path.exists(dead_journal[1])
    assert parts[live].read_bytes() == b"half written" and os.path.exists(live_journal[1])
    after = _files(models)
    assert {k: v for k, v in after.items() if k in before} == before
    assert set(after) - set(before) == {f"o02_boxA {TODAY}.3mf"}
    printing._close_journal(live_journal)
    assert not os.path.exists(live_journal[1])
    # A record that is not one of ours, or names what is not a folder path, removes nothing.
    odd = Path(printing.export_folder_path(temp)) / f"{dead}{printing.JOURNAL_SUFFIX}"
    for raw in (b"not json", b'{"folders": "C:/"}', b'{"folders": ["relative"]}', b"[1]"):
        odd.write_bytes(raw)
        parts[dead].write_bytes(b"x")
        assert printing.sweep_abandoned(temp, str(models)) == 0 and parts[dead].exists()
        assert not odd.exists()
    # A record naming a network share other than the one opened waits, a week at most.
    if os.name == "nt":
        share = json.dumps({"folders": ["\\\\server\\share\\jobs"]}).encode()
        odd.write_bytes(share)
        looked: list[str] = []
        real_lstat = os.lstat
        monkeypatch.setattr(os, "lstat", lambda q, *a, **k: looked.append(str(q)) or real_lstat(q, *a, **k))
        assert printing.sweep_abandoned(temp, str(models)) == 0 and odd.exists()
        assert not any(q.startswith("\\\\") for q in looked)
        assert printing.sweep_abandoned(temp, str(models), now=time.time() + 2 * printing.KEEP_SECONDS) == 0
        assert not odd.exists() and not any(q.startswith("\\\\") for q in looked)


def test_an_export_out_of_memory_says_so(monkeypatch):
    """The child's answer when the export runs past its memory: said, not a crash, and in
    JSON, as everything that crosses the export's pipe is."""

    def big(**request):
        raise MemoryError

    class Conn:
        def __init__(self) -> None:
            self.sent = []

        def recv_bytes(self, maxlength=None):
            return json.dumps({"path": "x"}).encode()

        def send_bytes(self, value) -> None:
            self.sent.append(json.loads(value))

    monkeypatch.setattr(printing, "export_for_print", big)
    conn = Conn()
    printing._export_serve(conn)
    assert conn.sent == [{"ok": False, "error": printing.TOO_LARGE}]


@pytest.mark.skipif(os.name != "nt", reason="the memory limit is a Windows job object")
def test_an_export_process_held_to_its_memory_limit(models):
    before = _files(models)
    result = printing.export_in_process(_request(models))
    assert result["ok"] and 0 < result["memory_peak"] < printing.EXPORT_MEMORY
    # Too little for the interpreter to start: the window is told the process stopped.
    result = printing.export_in_process(_request(models, "o11_curved.SLDPRT"), memory=8 << 20)
    assert not result["ok"] and result["error"]["code"] == "print_export_stopped", result
    assert set(_files(models)) - set(before) == {f"o02_boxA {TODAY}.3mf"}


# --------------------------------------------------------------------------- the window
@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from solidseas_app.viewer.app import use_system_fonts

    use_system_fonts()
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _wait(app, condition, timeout: float = 60.0) -> None:
    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            raise AssertionError("timed out waiting for the viewer")
        app.processEvents()
        time.sleep(0.005)


class Printer:
    """A window whose print controller detects ``detected``, records what it would start,
    and exports under ``tmp``."""

    def __init__(self, app, tmp: Path, detected, store=None) -> None:
        from solidseas_app.viewer.window import MainWindow

        self.app = app
        self.window = MainWindow(store)
        self.window.show()
        self.started: list[tuple[str, str]] = []
        self.outcomes: list[dict] = []
        p = self.window.printer
        p.detect = lambda: list(detected)
        p.launch = lambda program, path: self.started.append((program, path))
        p.today = lambda: TODAY
        self.messages: list[str] = []  # what the window would say in a message box (never shown here)
        p._message = lambda icon, text: self.messages.append(text)
        p.out_base = str(tmp)
        p.finished.connect(self.outcomes.append)
        self.finished: list[int] = []
        self.window.detailsFinished.connect(self.finished.append)

    def open(self, folder: Path, name: str) -> None:
        self.window.open_folder(str(folder))
        _wait(self.app, lambda: self.window.listing_info is not None)
        assert self.window.select_document(name), name
        generation = self.window.generation
        _wait(self.app, lambda: generation in self.finished)

    def press(self) -> dict:
        return self.choose(self.window.printer.action)

    def choose(self, action) -> dict:
        """Trigger a 3D Print button or menu entry and wait for what the print did."""
        n = len(self.outcomes)
        action.trigger()
        _wait(self.app, lambda: len(self.outcomes) > n)
        return self.outcomes[-1]

    def record_requests(self) -> list[dict]:
        """The export requests the window makes from now on, still exported as usual."""
        requests: list[dict] = []

        def export(request, cancelled):
            requests.append(request)
            return printing.export_in_process(request, cancelled)

        self.window.printer.export = export
        return requests

    def close(self) -> None:
        assert self.window.shutdown()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()


@pytest.fixture
def printer(app, tmp_path, programs):
    made = []

    def make(detected=None, store=None) -> Printer:
        found = _detect(programs["env"]) if detected is None else detected
        (tmp_path / "temp").mkdir(exist_ok=True)  # the system's temporary folder, always there
        p = Printer(app, tmp_path / "temp", found, store)
        made.append(p)
        return p

    yield make
    for p in made:
        p.close()


@needs_qt
def test_the_button_is_in_the_toolbar_and_the_file_menu(printer):
    w = printer().window
    assert w.act_print in w.toolbar.actions() and w.act_print.iconText() == "3D Print"
    file_menu = w.menuBar().actions()[0].menu()
    assert w.act_print in file_menu.actions()
    settings = w.settings_menu
    assert w.printer.menu.menuAction() in settings.actions()
    assert not w.act_print.isEnabled()  # nothing selected


@needs_qt
def test_one_click_sends_a_part_to_bambu_studio_and_remembers_it(printer, programs, tmp_path, models):
    from solidseas_app.viewer.settings import SettingsStore

    store = SettingsStore(str(tmp_path / "Viewer.ini"))
    p = printer(store=store)
    p.open(models, "o02_boxA.SLDPRT")
    assert p.window.act_print.isEnabled()
    outcome = p.press()
    assert outcome["ok"], (outcome, p.messages)
    assert outcome["program"] == "Bambu Studio" and outcome["started"]
    assert p.started == [(os.path.normpath(programs["bambu"]), outcome["file"])]
    assert outcome["arguments"] == [outcome["file"]] and outcome["format"] == "3mf"
    assert outcome["file"] == str(models / f"o02_boxA {TODAY}.3mf") and outcome["place"] == printing.MODEL
    assert printing.load_choice(SettingsStore(str(tmp_path / "Viewer.ini"))) == printing.PrintChoice("bambu")
    # Said with the result, which no later message of the same press replaces: where the file
    # is, in full, and that it was opened.
    said = p.window.statusBar().currentMessage()
    assert (
        said.startswith(f"Saved {outcome['file']} and opened it in Bambu Studio.") and outcome["chosen_now"]
    )
    assert "Bambu Studio is now the 3D Print program; Settings > 3D Print Program changes it." in said
    assert outcome["note"] == said
    again = p.press()
    assert not again["chosen_now"] and "now the 3D Print program" not in p.window.statusBar().currentMessage()
    assert again["file"] == str(models / f"o02_boxA {TODAY} (2).3mf")  # the newer, numbered higher
    assert p.window.statusBar().currentMessage() == f"Saved {again['file']} and opened it in Bambu Studio."


def _hold(started: threading.Event):
    """An export that waits until it is cancelled, as a long one would."""

    def export(request, cancelled):
        started.set()
        while not cancelled():
            time.sleep(0.01)
        return dict(printing.CANCELLED)

    return export


@needs_qt
def test_an_export_runs_apart_from_the_details_and_can_be_cancelled(printer, models):
    p = printer()
    c, w = p.window.printer, p.window
    started = threading.Event()
    c.export = _hold(started)
    p.open(models, "o02_boxA.SLDPRT")
    c.action.trigger()
    _wait(p.app, started.is_set)
    assert c.busy and w.act_print.isEnabled() and c.action.text() == "Cancel &3D Print"
    assert "Cancel 3D Print stops it" in w.statusBar().currentMessage()
    p.open(models, "o11_curved.SLDPRT")  # the details panel does not wait behind the export
    assert c.busy and w.act_print.isEnabled()
    c.action.trigger()  # Cancel 3D Print
    _wait(p.app, lambda: p.outcomes)
    assert p.outcomes == [{"ok": False, "program": "Bambu Studio", "cancelled": True}] and p.started == []
    assert not c.busy and c.action.text() == "&3D Print..." and c.action.iconText() == "3D Print"
    said = w.statusBar().currentMessage()  # the first press chose Bambu Studio: said even so
    assert said == "3D Print cancelled: nothing was sent. Bambu Studio is now the 3D Print program; " + (
        "Settings > 3D Print Program changes it."
    )


@needs_qt
def test_closing_the_window_stops_the_export(printer, models):
    p = printer()
    c = p.window.printer
    started = threading.Event()
    c.export = _hold(started)
    p.open(models, "o02_boxA.SLDPRT")
    c.action.trigger()
    _wait(p.app, started.is_set)
    t0 = time.monotonic()
    assert p.window.shutdown(5000) and time.monotonic() - t0 < 2
    assert p.started == []


@needs_qt
def test_the_status_line_says_where_display_meshes_came_from(printer, models):
    p = printer()
    c = p.window.printer
    data = {
        "file": "",
        "format": "3mf",
        "doc_type": "assembly",
        "closed": True,
        "skipped": 0,
        "display_mesh_objects": 2,
        "warnings": [],
    }

    def export(request, cancelled):
        folder = printing.export_folder(request["out_base"])
        return {"ok": True, "data": {**data, "file": os.path.join(folder, "made.3mf")}}

    c.export = export
    c._save(printing.PrintChoice("bambu"))
    p.open(models, "o08_asm_2x_boxA.SLDASM")
    p.press()
    said = p.window.statusBar().currentMessage()
    assert said.startswith("Saved ") and "made.3mf and opened it in Bambu Studio (2 parts from the" in said
    assert "2 parts from the display mesh SOLIDWORKS saved" in said
    assert "file was not found or has no solid body" in said and "no solid body is stored" not in said
    data["doc_type"] = "part"
    data["display_mesh_objects"] = 1
    p.open(models, "o02_boxA.SLDPRT")
    p.press()
    assert "as the part has no solid body to use" in p.window.statusBar().currentMessage()


@needs_qt
def test_an_assembly_goes_in_the_configuration_shown(printer, tmp_path, models):
    p = printer()
    p.open(models, "o16_asm_features.SLDASM")
    outcome = p.press()
    shown = p.window.details.configuration_shown()
    assert outcome["ok"] and outcome["doc_type"] == "assembly" and outcome["configuration"] == shown
    assert outcome["items"] == {"Default": 12, "Lite": 10}[shown]
    assert len(p.started) == 1 and p.started[0][1].endswith(".3mf")


@needs_qt
def test_with_no_bambu_studio_the_window_asks_and_remembers(printer, programs, models):
    found = [x for x in _detect(programs["env"]) if x.key != "bambu"]
    p = printer(detected=found)
    asked = []

    def ask(detected):
        asked.append([x.name for x in detected])
        return next(x for x in detected if x.key == "cura")

    p.window.printer.ask = ask
    p.open(models, "o02_boxA.SLDPRT")
    outcome = p.press()
    assert asked == [["PrusaSlicer", "UltiMaker Cura"]] and outcome["program"] == "UltiMaker Cura"
    assert p.window.printer.choice == printing.PrintChoice("cura")
    p.press()
    assert len(asked) == 1 and len(p.started) == 2  # asked once, remembered after


@needs_qt
def test_cancelling_the_question_sends_nothing(printer, models):
    p = printer(detected=[])
    p.window.printer.ask = lambda detected: None
    p.open(models, "o02_boxA.SLDPRT")
    p.window.printer.action.trigger()
    p.app.processEvents()
    assert p.started == [] and p.outcomes == [] and p.window.printer.choice == printing.PrintChoice()


@needs_qt
def test_the_program_menu_chooses_programs_and_formats(printer, programs, tmp_path, models):
    p = printer()
    c = p.window.printer
    c.fill_menu()
    texts = [a.text() for a in c.menu.actions() if not a.isSeparator()]
    assert texts[:3] == ["Bambu Studio", "PrusaSlicer", "UltiMaker Cura"]
    assert "Choose Another Program..." in texts
    assert texts[-3:] == ["Send as 3MF", "Send as STL", "Send as STEP"]  # what Bambu Studio takes
    checked = [a.text() for a in c.menu.actions() if a.isChecked()]
    assert checked == ["Bambu Studio", "Send as 3MF"]
    next(a for a in c.menu.actions() if a.text() == "UltiMaker Cura").trigger()
    offered = [a.text() for a in c.menu.actions() if a.text().startswith("Send as")]
    assert offered == ["Send as 3MF", "Send as STL"]  # Cura takes no STEP
    next(a for a in c.menu.actions() if a.text() == "Send as STL").trigger()
    assert c.choice == printing.PrintChoice("cura", None, "stl")
    exe = _install(tmp_path / "Tools", "my-slicer.exe")
    c.pick_file = lambda parent: printing.other_program(str(exe))
    next(a for a in c.menu.actions() if a.text() == "Choose Another Program...").trigger()
    assert c.choice == printing.PrintChoice("other", str(exe), "stl")
    c.fill_menu()
    assert [a.text() for a in c.menu.actions() if a.isChecked()] == ["my-slicer", "Send as STL"]
    p.open(models, "o02_boxA.SLDPRT")
    outcome = p.press()
    assert outcome["format"] == "stl" and p.started == [(str(exe), outcome["file"])]


@needs_qt
def test_a_program_that_is_gone_is_said_plainly(printer, models):
    p = printer()
    p.window.printer._save(printing.PrintChoice("orca"))  # chosen once, not installed now
    p.open(models, "o02_boxA.SLDPRT")
    outcome = p.press()
    assert not outcome["ok"] and p.started == []
    assert (
        len(p.messages) == 1
        and "OrcaSlicer cannot be started" in p.messages[0]
        and "3D Print Program" in p.messages[0]
    )


@needs_qt
def test_a_failed_export_is_said_plainly(printer, tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    shutil.copy2(fixture_path("o01_empty.SLDPRT"), folder / "o01_empty.SLDPRT")
    p = printer()
    p.open(folder, "o01_empty.SLDPRT")
    outcome = p.press()
    assert not outcome["ok"] and outcome["error"]["code"] == "nothing_to_export" and p.started == []
    assert p.messages and p.messages[0].startswith("The export for 3D printing failed.")


@needs_qt
def test_a_program_that_will_not_start_is_said_plainly(printer, models):
    p = printer()

    def broken(program, path):
        raise PermissionError(13, "Access is denied")

    p.window.printer.launch = broken
    p.open(models, "o02_boxA.SLDPRT")
    outcome = p.press()
    assert not outcome["ok"] and not outcome["started"] and os.path.exists(outcome["file"])
    assert (
        "Bambu Studio could not be started: Access is denied" in p.messages[0]
        and outcome["file"] in p.messages[0]
    )


@needs_qt
def test_drawings_cannot_be_printed(printer, models):
    p = printer()
    p.open(models, "o18_drw_boxA.SLDDRW")
    assert not p.window.act_print.isEnabled() and p.window.print_target() is None


@needs_qt
def test_the_dry_run_starts_nothing(printer, models):
    p = printer()
    p.window.printer.dry_run = True
    p.open(models, "o02_boxA.SLDPRT")
    outcome = p.press()
    assert outcome["ok"] and outcome["dry_run"] and not outcome["started"] and p.started == []
    assert outcome["executable"].endswith("bambu-studio.exe") and outcome["arguments"] == [outcome["file"]]
    q = printer(detected=[])
    q.window.printer.dry_run = True
    q.open(models, "o02_boxA.SLDPRT")
    assert q.press() == {"ok": False, "would_ask": True, "detected": []}


@needs_qt
def test_preferences_show_the_choice(printer):
    from solidseas_app.viewer.preferences import PRINT_HERE_TEXT, PreferencesDialog

    p = printer()
    w = p.window
    dialog = PreferencesDialog(w, w.settings, None, print_text=w.printer.describe())
    assert dialog.print_here.text() == PRINT_HERE_TEXT == "Save 3D print files next to the model"
    assert dialog.print_here.isChecked() and "highest number" in dialog.print_here.toolTip()
    assert (
        dialog.print_program.text()
        == "3D Print program: Bambu Studio, found here and used until you choose another"
    )
    dialog.deleteLater()
    w.printer.set_format("3mf")
    dialog = PreferencesDialog(w, w.settings, None, print_text=w.printer.describe())
    assert dialog.print_program.text() == "3D Print program: Bambu Studio, sent as 3MF"
    dialog.deleteLater()
    plain = PreferencesDialog(w, w.settings, None)
    assert not hasattr(plain, "print_program")
    plain.deleteLater()


def test_the_launcher_starts_one_argument_with_no_shell(monkeypatch):
    """The launcher itself, with ``subprocess.Popen`` stood in for: a list of two, no shell."""
    import subprocess

    seen = {}

    class FakePopen:
        def __init__(self, args, **kwargs):
            seen["args"], seen["kwargs"] = args, kwargs

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", "somewhere")
    REAL_LAUNCH(r"C:\Programs\slicer.exe", r"C:\Temp\a b & c.3mf")
    assert seen["args"] == [r"C:\Programs\slicer.exe", r"C:\Temp\a b & c.3mf"]
    assert seen["kwargs"]["shell"] is False and seen["kwargs"]["stdin"] == subprocess.DEVNULL
    env = seen["kwargs"]["env"]
    assert not any(k.upper().startswith("_PYI_") for k in env) and env.get("PATH") == os.environ.get("PATH")


def test_the_launcher_leaves_the_viewers_packaging_behind(tmp_path):
    bundle = str(tmp_path / "_MEI12345")
    system = str(tmp_path / "Windows" / "System32")
    env = {
        "PATH": os.pathsep.join([bundle, system, os.path.join(bundle, "PySide6")]),
        "_PYI_APPLICATION_HOME_DIR": bundle,
        "_PYI_PARENT_PROCESS_LEVEL": "1",
        "QT_PLUGIN_PATH": os.path.join(bundle, "PySide6", "plugins"),
        "QML2_IMPORT_PATH": os.path.join(bundle, "PySide6", "qml"),
        "USERPROFILE": str(tmp_path),
    }
    packaged = printing.launch_environment(env, bundle)
    assert packaged == {"PATH": system, "USERPROFILE": str(tmp_path), "PYINSTALLER_RESET_ENVIRONMENT": "1"}
    plain = printing.launch_environment(env, None)  # run from source: only PyInstaller's own go
    assert plain == {k: v for k, v in env.items() if not k.startswith("_PYI_")}
    mine = {**env, "QT_PLUGIN_PATH": str(tmp_path / "my plugins")}  # the user's own is kept
    assert printing.launch_environment(mine, bundle)["QT_PLUGIN_PATH"] == str(tmp_path / "my plugins")


@pytest.mark.skipif(os.name != "nt", reason="the DLL directory is Windows'")
def test_a_packaged_viewer_starts_programs_with_the_default_dll_search(monkeypatch, tmp_path):
    """PyInstaller sets the packaged viewer's DLL directory to its unpacked folder, and a
    program started inherits it: the launcher clears it for the start and puts it back."""
    import ctypes
    import subprocess
    import sys

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetDllDirectoryW.argtypes = (ctypes.c_uint32, ctypes.c_wchar_p)
    k32.SetDllDirectoryW.argtypes = (ctypes.c_wchar_p,)

    def current() -> str:
        buf = ctypes.create_unicode_buffer(32768)
        return buf.value if k32.GetDllDirectoryW(32768, buf) else ""

    seen = {}

    class FakePopen:
        def __init__(self, args, **kwargs):
            seen["dll"], seen["env"] = current(), kwargs["env"]

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    before = current()
    assert k32.SetDllDirectoryW(str(tmp_path))
    try:
        REAL_LAUNCH(r"C:\Programs\slicer.exe", r"C:\Temp\a.3mf")
        after = current()
    finally:
        k32.SetDllDirectoryW(before or None)
    assert seen["dll"] == "" and after == str(tmp_path)
    assert seen["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


# --------------------------------------------------------------------------- the setting
@needs_qt
def test_saving_next_to_the_model_is_a_setting_remembered_in_viewer_ini(app, tmp_path):
    from solidseas_app.viewer.settings import Settings, SettingsStore
    from solidseas_app.viewer.window import MainWindow

    assert Settings().print_next_to_model is True  # on by default
    path = tmp_path / "Viewer.ini"
    w = MainWindow(SettingsStore(str(path)))
    try:
        assert w.act_print_here in w.settings_menu.actions() and w.act_print_here.isChecked()
        assert w.act_print_here.text() == "Save 3D Print Files &Next to the Model"
        w.act_print_here.trigger()
        assert not w.settings.print_next_to_model
        assert "print_next_to_model=false" in path.read_text(encoding="utf-8")
        assert SettingsStore(str(path)).load() == Settings(print_next_to_model=False)
        assert "temporary folder" in w.printer.where_text()
        path.write_text("[Preferences]\nprint_next_to_model=maybe\n", encoding="utf-8")
        store = SettingsStore(str(path))
        assert store.load() == Settings() and store.reset_keys == ["print_next_to_model"]
    finally:
        w.shutdown()
        w.close()


@needs_qt
def test_preferences_choose_where_print_files_go(app, tmp_path):
    from PySide6.QtWidgets import QDialogButtonBox

    from solidseas_app.viewer.preferences import PreferencesDialog
    from solidseas_app.viewer.settings import Settings, SettingsStore
    from solidseas_app.viewer.window import MainWindow

    path = tmp_path / "Viewer.ini"
    w = MainWindow(SettingsStore(str(path)))
    dialog = PreferencesDialog(w, w.settings, w.store.path)
    try:
        assert dialog.print_here.isChecked() and dialog.values() == Settings()
        dialog.print_here.setChecked(False)
        dialog.applied.connect(w.apply_settings)
        dialog.buttons.button(QDialogButtonBox.StandardButton.Apply).click()
        assert w.settings == Settings(print_next_to_model=False) and not w.act_print_here.isChecked()
        assert SettingsStore(str(path)).load() == w.settings
        dialog.buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).click()
        assert dialog.print_here.isChecked()
        assert dialog.sizeHint().height() <= 800  # still fits a 1080p screen at 125 percent
    finally:
        dialog.deleteLater()
        w.shutdown()
        w.close()


@needs_qt
def test_with_the_setting_off_the_button_prints_to_the_temporary_folder(printer, models, tmp_path):
    p = printer()
    p.window.change_settings(print_next_to_model=False)
    before = _files(models)
    p.open(models, "o02_boxA.SLDPRT")
    outcome = p.press()
    temp = printing.export_folder(str(tmp_path / "temp"))
    assert outcome["ok"] and outcome["place"] == printing.TEMP and outcome["fallback"] is None
    assert outcome["file"] == os.path.join(temp, f"o02_boxA {TODAY}.3mf") and not outcome["next_to_model"]
    assert (
        p.window.statusBar()
        .currentMessage()
        .startswith(
            f"Saved {outcome['file']} in the temporary folder, not next to the model, as Save 3D Print Files "
            "Next to the Model is off; opened it in Bambu Studio."
        )
    )
    assert outcome["note"] == p.window.statusBar().currentMessage()
    assert _files(models) == before


@needs_qt
def test_a_fallback_is_said_in_the_status_line_and_the_note(printer, models, tmp_path):
    p = printer()
    c = p.window.printer
    temp = printing.export_folder(str(tmp_path / "temp"))
    data = {
        "file": os.path.join(temp, f"o02_boxA {TODAY}.3mf"),
        "format": "3mf",
        "place": printing.TEMP,
        "fallback": printing.READ_ONLY,
        "doc_type": "part",
        "closed": True,
        "skipped": 0,
        "display_mesh_objects": 0,
        "warnings": [],
    }
    c.export = lambda request, cancelled: {"ok": True, "data": dict(data)}
    c._save(printing.PrintChoice("bambu"))
    p.open(models, "o02_boxA.SLDPRT")
    outcome = p.press()
    said = p.window.statusBar().currentMessage()
    assert said == (
        f"Saved {data['file']} in the temporary folder, not next to the model, as the model's folder is "
        "read-only; opened it in Bambu Studio."
    )
    assert outcome["note"] == said and outcome["fallback"] == printing.READ_ONLY


# --------------------------------------------------------------------------- the right-click menus
def _texts(menu) -> list[str]:
    return [a.text() for a in menu.actions()]


def _entry(menu, start: str):
    found = [a for a in menu.actions() if a.text().startswith(start)]
    assert len(found) == 1, (start, _texts(menu))
    return found[0]


@needs_qt
def test_a_row_of_the_list_prints_its_part_or_assembly(printer, models):
    from solidseas_app.viewer.documents import NAME

    (models / "~$o02_boxA.SLDPRT").write_bytes(b"\x00" * 64)  # a SOLIDWORKS lock file
    p = printer()
    w = p.window
    p.open(models, "o08_asm_2x_boxA.SLDASM")
    w.set_lock_files(True)
    requests = p.record_requests()

    def index(name: str):
        row = w.model.find(name)
        return w.proxy.mapFromSource(w.model.index(row, NAME))

    for view in (w.table, w.icons):  # details and icons share the rows and the menu
        from PySide6.QtCore import Qt

        assert view.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
    opens = [opening.OPEN_TEXT, opening.show_text()]
    assert _texts(w.list_menu(index("o18_drw_boxA.SLDDRW"))) == opens  # a drawing is not printed
    assert w.list_menu(index("~$o02_boxA.SLDPRT")) is None
    menu = w.list_menu(index("o02_boxA.SLDPRT"))  # not the one shown
    assert _texts(menu) == [*opens, "", "3D Print o02_boxA.SLDPRT"]
    assert "next to the model" in menu.actions()[-1].toolTip()
    outcome = p.choose(menu.actions()[-1])
    assert outcome["ok"] and outcome["file"] == str(models / f"o02_boxA {TODAY}.3mf")
    assert requests[-1]["path"] == str(models / "o02_boxA.SLDPRT") and requests[-1]["configuration"] is None
    again = p.choose(w.list_menu(index("o02_boxA.SLDPRT")).actions()[-1])
    assert again["file"] == str(models / f"o02_boxA {TODAY} (2).3mf")
    # The row shown prints as the button does, in the configuration shown.
    shown = p.choose(_entry(w.list_menu(index("o08_asm_2x_boxA.SLDASM")), "3D Print"))
    assert shown["ok"] and requests[-1]["configuration"] == w.details.configuration_shown()
    assert shown["file"] == str(models / f"o08_asm_2x_boxA {TODAY}.3mf") and shown["items"] == 2
    menu.deleteLater()


@needs_qt
def test_component_rows_print_their_file_in_the_rows_configuration(printer, models):
    from solidseas_app.viewer.details import CONFIG_ROLE, KEY_ROLE, TABS

    p = printer()
    w = p.window
    d = w.details
    p.open(models, O16)
    requests = p.record_requests()
    # An instance's row: the part it uses, in the configuration it uses.
    item = d.instance_item(INNER)
    menu = d.component_menu(item)
    assert _texts(menu)[:7] == [
        opening.OPEN_TEXT,
        opening.show_text(),
        "",
        "Go to file",
        "Show in folder list",
        "",
        "3D Print o07_boxB_h31.SLDPRT",
    ]
    outcome = p.choose(_entry(menu, "3D Print"))
    assert outcome["ok"] and outcome["file"] == str(models / os.path.basename(outcome["file"]))
    assert requests[-1]["path"] == str(models / "o07_boxB_h31.SLDPRT")
    assert requests[-1]["configuration"] == (item.data(0, CONFIG_ROLE) or None)
    assert os.path.basename(outcome["file"]).endswith(f" {TODAY}.3mf")
    assert outcome["file"] in w.statusBar().currentMessage()
    # A sub-assembly's row prints the sub-assembly.
    sub = p.choose(_entry(d.component_menu(d.instance_item("o15_sub_asm-1")), "3D Print"))
    assert (
        sub["ok"]
        and sub["doc_type"] == "assembly"
        and requests[-1]["path"] == str(models / "o15_sub_asm.SLDASM")
    )
    # A file's row: the one configuration its instances use, else the active one.
    row = d.find_item("files", "o02_boxA.SLDPRT")
    used = d.only_configuration(row.data(0, KEY_ROLE))
    outcome = p.choose(_entry(d.component_menu(row), "3D Print"))
    assert outcome["ok"] and requests[-1]["path"] == str(models / "o02_boxA.SLDPRT")
    assert requests[-1]["configuration"] == (used or None)
    # A row of the BOM tab.
    d.tabs.setCurrentIndex(TABS.index("BOM"))
    bom = next(
        i for i in (d.find_item("bom", str(n)) for n in range(1, 20)) if i is not None and "boxA" in i.text(1)
    )
    outcome = p.choose(_entry(d.component_menu(bom), "3D Print"))
    assert outcome["ok"] and requests[-1]["path"] == str(models / "o02_boxA.SLDPRT")
    assert requests[-1]["configuration"] == (bom.data(0, CONFIG_ROLE) or None)
    # The legend's menu for a file has it too.
    legend = d._file_link_menu(row.data(0, KEY_ROLE))
    assert "3D Print o02_boxA.SLDPRT" in _texts(legend)
    menu.deleteLater()
    legend.deleteLater()


@needs_qt
def test_the_3d_views_menu_prints_the_part_and_each_sub_assembly(printer, models):
    p = printer()
    w = p.window
    d, pane = w.details, w.details.preview
    p.open(models, O16)
    requests = p.record_requests()
    menu = d.instance_menu(INNER)  # what a right-click on the part in the 3D view opens
    assert _texts(menu) == [
        opening.OPEN_TEXT,
        opening.show_text(),
        "",
        "Go to file",
        "Show in folder list",
        "Show on Components tab",
        "",
        "3D Print Part o07_boxB_h31.SLDPRT",
        "3D Print Sub-assembly o15_sub_asm.SLDASM",  # each sub-assembly on its path, nearest first
    ]
    part = p.choose(_entry(menu, "3D Print Part"))
    assert part["ok"] and requests[-1]["path"] == str(models / "o07_boxB_h31.SLDPRT")
    assert requests[-1]["configuration"] == (d.instance_link(INNER)[2] or None)
    sub = p.choose(_entry(menu, "3D Print Sub-assembly"))
    assert sub["ok"] and requests[-1]["path"] == str(models / "o15_sub_asm.SLDASM")
    assert requests[-1]["configuration"] == (d.instance_link("o15_sub_asm-1")[2] or None)
    # Empty space: this assembly, in the configuration shown.
    space = pane.space_menu()
    assert _texts(space) == ["3D Print This Assembly"]
    whole = p.choose(space.actions()[0])
    assert whole["ok"] and requests[-1]["path"] == str(models / O16)
    assert requests[-1]["configuration"] == d.configuration_shown()
    assert os.path.basename(whole["file"]) == f"o16_asm_features {TODAY}.3mf"
    # A part's view offers 3D Print This Part.
    p.open(models, "o02_boxA.SLDPRT")
    assert _texts(pane.space_menu()) == ["3D Print This Part"]
    menu.deleteLater()


@needs_qt
def test_a_virtual_part_prints_next_to_the_assembly_that_stores_it(printer, models):
    p = printer()
    d = p.window.details
    p.open(models, O16)
    requests = p.record_requests()
    menu = d.instance_menu(VIRTUAL_INSTANCE)
    outcome = p.choose(_entry(menu, "3D Print Part"))
    assert outcome["ok"] and outcome["place"] == printing.MODEL, (outcome, p.messages)
    assert requests[-1]["path"] == str(models / O16) and requests[-1]["nested"] == (
        "VirtualComp/Part12-sldprt",
    )
    # Named after the component, as the menu shows it: Part12^o16_asm_features.SLDPRT.
    assert outcome["file"] == str(models / f"Part12_o16_asm_features {TODAY}.3mf")
    assert outcome["document"] == "Part12^o16_asm_features" and requests[-1]["name"] == VIRTUAL_FILE
    menu.deleteLater()


@pytest.fixture
def no_drive_q(monkeypatch):
    """Drive Q: does not exist, whatever this machine has: stored Q:\\ paths are never touched."""
    from solidseas.resolve import gateway as gateway_mod

    real = gateway_mod._drive_type

    def drive_type(root: str) -> int:
        return gateway_mod.DRIVE_NO_ROOT_DIR if root.upper().startswith("Q:") else real(root)

    monkeypatch.setattr(gateway_mod, "_drive_type", drive_type)


def _crafted_assembly(stored: list[str], *, folder_at_save: str = "") -> bytes:
    """An assembly with one instance, ``c2-1``, ``c3-1``..., of each stored path. The
    fixtures' own assemblies store paths of the account that made them, which may be
    there on the machine running the tests: a crafted one names only drive Q:."""
    from builders import TreeXml, resolving_assembly

    t = TreeXml()
    t.top("m1")
    for i, path in enumerate(stored, start=2):
        t.file(str(i), path, swCreationTime="1700000000")
        t.model(f"m{i}", str(i))
        t.ref("m1", f"c{i}", 1, f"m{i}")
    return resolving_assembly(t, folder_at_save=folder_at_save)


@needs_qt
def test_a_component_whose_file_is_missing_says_why_instead_of_printing(printer, tmp_path, no_drive_q):
    folder = tmp_path / "Job"
    folder.mkdir()
    (folder / "top.SLDASM").write_bytes(_crafted_assembly(["Q:\\Gone\\gone.SLDPRT"]))
    before = _files(folder)
    from solidseas_app.viewer.details import KEY_ROLE

    p = printer()
    w = p.window
    d = w.details
    p.open(folder, "top.SLDASM")
    # The entry is off, as Show in folder list beside it is, with the reason in a few words
    # after it and in full in its tooltip, which the menu shows.
    menu = d.component_menu(d.instance_item("c2-1"))
    assert _texts(menu)[4:] == ["Show in folder list (not found)", "", "3D Print gone.SLDPRT (not found)"]
    entry = _entry(menu, "3D Print gone.SLDPRT")
    assert not entry.isEnabled() and menu.toolTipsVisible()
    key = d.instance_item("c2-1").data(0, KEY_ROLE)
    said = w.component_print_target(key)
    assert said.startswith("gone.SLDPRT cannot be 3D printed from here.\n\nNo file of that name was found.")
    assert said.endswith("Stored path: Q:\\Gone\\gone.SLDPRT")
    assert "No file of that name was found." in entry.toolTip() and "Q:\\Gone\\gone.SLDPRT" in entry.toolTip()
    view = d.instance_menu("c2-1")  # the 3D view's menu of it, and the legend's, the same
    assert "3D Print Part gone.SLDPRT (not found)" in _texts(view)
    assert "3D Print gone.SLDPRT (not found)" in _texts(d._file_link_menu(key))
    # Were it chosen all the same (by a script, say), it says why and prints nothing.
    w.printer.print_resolved(lambda: w.component_print_target(key))
    assert p.outcomes[-1] == {"ok": False, "cannot": said} and p.messages[-1] == said and p.started == []
    assert _files(folder) == before
    menu.deleteLater()
    view.deleteLater()


@needs_qt
def test_a_component_found_outside_the_opened_folder_prints_next_to_its_file(printer, tmp_path, no_drive_q):
    from builders import part_with_creation_time

    new = tmp_path / "New"
    (new / "lib").mkdir(parents=True)
    (new / "Proj").mkdir()
    (new / "lib" / "p.SLDPRT").write_bytes(part_with_creation_time(1_700_000_000))
    (new / "Proj" / "asm.SLDASM").write_bytes(
        _crafted_assembly(["Q:\\Old\\lib\\p.SLDPRT"], folder_at_save="Q:\\Old\\Proj\\")
    )
    p = printer()
    d = p.window.details
    p.open(new / "Proj", "asm.SLDASM")
    requests = p.record_requests()
    menu = d.component_menu(d.instance_item("c2-1"))
    outcome = p.choose(_entry(menu, "3D Print p.SLDPRT"))
    assert outcome["ok"] and outcome["place"] == printing.MODEL, (outcome, p.messages)
    assert outcome["file"] == str(new / "lib" / f"p {TODAY}.3mf")
    assert requests[-1]["within"] == str(new / "lib") and requests[-1]["folder"] == str(new / "Proj")
    assert sorted(os.listdir(new / "Proj")) == ["asm.SLDASM"]
    menu.deleteLater()


@needs_qt
def test_a_component_found_through_a_junction_outside_the_opened_folder_is_never_written_through(
    printer, tmp_path, no_drive_q
):
    """Reference resolution may find a component outside the opened folder through a
    junction above its folder (the system follows it): the print goes to the temporary
    folder, and the status line says why, as for a junction inside the opened folder."""
    from builders import part_with_creation_time

    new, real = tmp_path / "New", tmp_path / "Real"
    (real / "sub").mkdir(parents=True)
    (new / "Proj").mkdir(parents=True)
    _link_folder(real, new / "lib")
    (real / "sub" / "p.SLDPRT").write_bytes(part_with_creation_time(1_700_000_000))
    (new / "Proj" / "asm.SLDASM").write_bytes(
        _crafted_assembly(["Q:\\Old\\lib\\sub\\p.SLDPRT"], folder_at_save="Q:\\Old\\Proj\\")
    )
    p = printer()
    d = p.window.details
    p.open(new / "Proj", "asm.SLDASM")
    menu = d.component_menu(d.instance_item("c2-1"))
    outcome = p.choose(_entry(menu, "3D Print p.SLDPRT"))
    assert outcome["ok"] and outcome["place"] == printing.TEMP and outcome["fallback"] == printing.LINKED
    assert outcome["model_folder"] == str(new / "lib" / "sub")
    assert sorted(os.listdir(real / "sub")) == ["p.SLDPRT"]
    said = p.window.statusBar().currentMessage()
    assert said.startswith(f"Saved {outcome['file']} in the temporary folder, not next to the model, as ")
    assert printing.LINKED in said
    menu.deleteLater()


def _virtual_in_sub(folder: Path, *, stored: bool = True) -> None:
    """top.SLDASM holding sub-1, sub.SLDASM, whose virtual part Part12^o16_asm_features
    only sub.SLDASM stores (o16 with that part's document replaced by o02's), as
    tests/test_geometry.py builds it; without ``stored``, sub.SLDASM is o15, which stores
    none."""
    from builders import TreeXml, assembly_with_tree, rebuild

    o02 = fixture_path("o02_boxA.SLDPRT").read_bytes()
    sub = rebuild(fixture_path(O16), {"VirtualComp/Part12-sldprt": o02}) if stored else None
    (folder / "sub.SLDASM").write_bytes(sub or fixture_path("o15_sub_asm.SLDASM").read_bytes())
    t = TreeXml()
    t.top("m1")
    t.file("2", "sub.SLDASM", "ASSEMBLY")
    t.file("3", VIRTUAL_FILE)
    t.model("m2", "2")
    t.model("m3", "3")
    t.ref("m1", "sub", 1, "m2", transform="1 0 0 0 0 1 0 0 0 0 1 0 1 2 3 1")
    t.ref("m2", "Part12^o16_asm_features", 1, "m3", virtual=True)
    (folder / "top.SLDASM").write_bytes(assembly_with_tree(t))


@needs_qt
def test_a_virtual_part_of_a_sub_assembly_prints_from_inside_that_sub_assembly(printer, tmp_path):
    """A virtual part that a sub-assembly stores, not the assembly shown: its row, its
    file's row and the 3D view's menu of it print it from inside the sub-assembly, found
    by its stored name, next to the sub-assembly's file and named after the component."""
    from solidseas_app.viewer.details import KEY_ROLE

    folder = tmp_path / "jobs"
    folder.mkdir()
    _virtual_in_sub(folder)
    before = _files(folder)
    p = printer()
    d = p.window.details
    p.open(folder, "top.SLDASM")
    requests = p.record_requests()
    ident = "sub-1/Part12^o16_asm_features-1"
    row = d.instance_item(ident)
    assert d.target(row.data(0, KEY_ROLE)).status == "embedded_in_subassembly"
    view = d.instance_menu(ident)
    assert _texts(view)[6:] == ["", f"3D Print Part {VIRTUAL_FILE}", "3D Print Sub-assembly sub.SLDASM"]
    outcome = p.choose(_entry(view, "3D Print Part"))
    assert outcome["ok"] and outcome["place"] == printing.MODEL, (outcome, p.messages)
    assert (
        outcome["file"] == str(folder / f"Part12_o16_asm_features {TODAY}.3mf") and outcome["triangles"] == 12
    )
    assert requests[-1]["path"] == str(folder / "sub.SLDASM") and requests[-1]["nested"] == ()
    assert requests[-1]["virtual"] == (VIRTUAL_FILE,) and outcome["nested"] == ["VirtualComp/Part12-sldprt"]
    again = p.choose(_entry(d.component_menu(row), "3D Print"))
    assert again["file"] == str(folder / f"Part12_o16_asm_features {TODAY} (2).3mf")
    files_row = d.find_item("files", VIRTUAL_FILE)  # no sub-assembly on the row: the one it is used in
    third = p.choose(_entry(d.component_menu(files_row), "3D Print"))
    assert third["ok"] and requests[-1]["virtual"] == (VIRTUAL_FILE,), p.messages
    after = _files(folder)
    assert {k: v for k, v in after.items() if k in before} == before
    assert sorted(set(after) - set(before)) == [
        f"Part12_o16_asm_features {TODAY} (2).3mf",
        f"Part12_o16_asm_features {TODAY} (3).3mf",
        f"Part12_o16_asm_features {TODAY}.3mf",
    ]
    view.deleteLater()


@needs_qt
def test_a_virtual_part_its_sub_assembly_does_not_store_says_so(printer, tmp_path):
    folder = tmp_path / "jobs"
    folder.mkdir()
    _virtual_in_sub(folder, stored=False)
    before = _files(folder)
    p = printer()
    d = p.window.details
    p.open(folder, "top.SLDASM")
    outcome = p.choose(
        _entry(d.component_menu(d.instance_item("sub-1/Part12^o16_asm_features-1")), "3D Print")
    )
    assert not outcome["ok"] and outcome["error"]["code"] == "stream_not_found"
    assert p.messages[-1].startswith("The export for 3D printing failed.")
    assert f"the sub-assembly that uses '{VIRTUAL_FILE}' stores no copy of it" in p.messages[-1]
    assert _files(folder) == before and p.started == []


@needs_qt
def test_a_part_read_from_a_sub_assemblys_own_file_prints_from_the_3d_view(printer, models):
    """An assembly that stores no components below a sub-assembly: the 3D view reads them
    from the sub-assembly's own file, and no row of the Components tab stands for them.
    Right-clicking one still offers 3D Print Part for it, the document its mesh was read
    from, in the configuration its instance uses, then the sub-assembly."""
    from builders import TreeXml, assembly_with_tree
    from solidseas_app.viewer.details import TABS
    from solidseas_app.viewer.preview import MODEL
    from test_viewer import _stub_view_factory

    t = TreeXml()
    t.top("m1")
    t.file("2", "o15_sub_asm.SLDASM", "ASSEMBLY")
    t.model("m2", "2")
    t.ref("m1", "o15_sub_asm", 1, "m2")
    (models / "top2.SLDASM").write_bytes(assembly_with_tree(t))
    p = printer()
    w = p.window
    d, pane = w.details, w.details.preview
    pane.view_factory = _stub_view_factory([])
    pane.gl_check = lambda: (True, "test")
    w.change_settings(view_3d=True)
    d.tabs.setCurrentIndex(TABS.index("Preview"))
    p.open(models, "top2.SLDASM")
    pane.set_mode(MODEL)
    _wait(p.app, lambda: pane.mesh_state not in ("idle", "starting", "loading") and not w.busy)
    ident = "o15_sub_asm-1/o02_boxA-1"
    assert pane.mesh_state == "ready" and ident in pane.instance_ids
    assert d.instance_item(ident) is None and d.row_of(ident) == "o15_sub_asm-1"
    document = pane.instance_documents[ident]
    assert document == {
        "path": str(models / "o02_boxA.SLDPRT"),
        "nested": [],
        "configuration": "Default",
        "name": "o02_boxA.SLDPRT",
    }
    requests = p.record_requests()
    menu = d.instance_menu(ident)
    assert _texts(menu)[6:9] == [
        "",
        "3D Print Part o02_boxA.SLDPRT",
        "3D Print Sub-assembly o15_sub_asm.SLDASM",
    ]
    assert "in configuration Default" in _entry(menu, "3D Print Part").toolTip() and menu.toolTipsVisible()
    outcome = p.choose(_entry(menu, "3D Print Part"))
    assert outcome["ok"] and outcome["file"] == str(models / f"o02_boxA {TODAY}.3mf"), (outcome, p.messages)
    assert (
        requests[-1]["path"] == str(models / "o02_boxA.SLDPRT") and requests[-1]["configuration"] == "Default"
    )
    assert requests[-1]["within"] == str(models)
    sub = p.choose(_entry(menu, "3D Print Sub-assembly"))
    assert sub["ok"] and requests[-1]["path"] == str(models / "o15_sub_asm.SLDASM")
    menu.deleteLater()


def test_the_scene_keeps_the_document_of_each_part_no_row_stands_for(models):
    """What the 3D view keeps for 3D Print: the part's own document for an instance read
    from a sub-assembly's own file (keyed below that sub-assembly's key), none for one the
    components section lists, nor for one drawn from what its sub-assembly stores of it."""
    from types import SimpleNamespace

    from builders import TreeXml, assembly_with_tree
    from solidseas import Root, Roots, open_document
    from solidseas import geometry as geo
    from solidseas_app.viewer import mesh3d

    t = TreeXml()
    t.top("m1")
    t.file("2", "o15_sub_asm.SLDASM", "ASSEMBLY")
    t.model("m2", "2")
    t.ref("m1", "o15_sub_asm", 1, "m2")
    (models / "top2.SLDASM").write_bytes(assembly_with_tree(t))
    with open_document(models / "top2.SLDASM", within=models) as doc:
        g = geo.display_geometry(doc, roots=Roots([Root("opened", str(models))]), allow_outside_roots=True)
    docs = mesh3d.instance_documents(g)
    assert sorted(docs) == ["o15_sub_asm-1/o02_boxA-1", "o15_sub_asm-1/o07_boxB_h31-1"]
    assert docs["o15_sub_asm-1/o07_boxB_h31-1"]["path"] == str(models / "o07_boxB_h31.SLDPRT")
    scene = mesh3d.scene_from_geometry(g)
    assert scene is not None and scene.documents == docs
    with open_document(models / O16, within=models) as doc:  # every instance has a row
        g16 = geo.display_geometry(doc, roots=Roots([Root("opened", str(models))]), allow_outside_roots=True)
    assert mesh3d.instance_documents(g16) == {}
    # Drawn from its sub-assembly's own mesh of it, a part's own document is not known.
    inst = g.instances[0]
    held = SimpleNamespace(
        instances=[inst],
        meshes={
            inst.mesh: SimpleNamespace(kind="subassembly", path=str(models / "o15_sub_asm.SLDASM"), nested=())
        },
        files=g.files,
    )
    assert mesh3d.instance_documents(held) == {}


def _top_of_o15(models: Path) -> None:
    """top2.SLDASM, storing no components of the o15_sub_asm-1 it holds: the 3D view reads
    them from o15's own file, and no row of the Components tab stands for them."""
    from builders import TreeXml, assembly_with_tree

    t = TreeXml()
    t.top("m1")
    t.file("2", "o15_sub_asm.SLDASM", "ASSEMBLY")
    t.model("m2", "2")
    t.ref("m1", "o15_sub_asm", 1, "m2")
    (models / "top2.SLDASM").write_bytes(assembly_with_tree(t))


def test_the_scene_says_which_parts_no_row_stands_for_were_not_found(models):
    """A part read from a sub-assembly's own file whose own file is not there is drawn from
    what the sub-assembly stores of it: the geometry says why its file gave no mesh, and
    the scene keeps its name, stored path and that reason for the 3D view's menu. A part
    whose file was found but gave no mesh for another reason (no display mesh) is not
    said to be missing."""
    from types import SimpleNamespace

    from solidseas import Root, Roots, open_document
    from solidseas import geometry as geo
    from solidseas_app.viewer import mesh3d

    _top_of_o15(models)
    os.remove(models / "o02_boxA.SLDPRT")
    with open_document(models / "top2.SLDASM", within=models) as doc:
        g = geo.display_geometry(doc, roots=Roots([Root("opened", str(models))]), allow_outside_roots=True)
    gone = next(i for i in g.instances if i.id == "o15_sub_asm-1/o02_boxA-1")
    assert g.meshes[gone.mesh].kind == "subassembly" and g.file_failures[gone.file] == "missing"
    stored = g.files[gone.file].stored_path
    assert stored and stored.endswith("o02_boxA.SLDPRT")
    missing = mesh3d.instance_missing(g)
    assert missing == {gone.id: {"name": "o02_boxA.SLDPRT", "stored_path": stored, "reason": "missing"}}
    assert sorted(mesh3d.instance_documents(g)) == ["o15_sub_asm-1/o07_boxB_h31-1"]  # found: printable
    scene = mesh3d.scene_from_geometry(g)
    assert scene is not None and scene.missing == missing
    for reason, said in (("no_mesh", False), ("ambiguous", True), ("unreadable", True)):
        other = SimpleNamespace(
            instances=[gone], meshes=g.meshes, files=g.files, file_failures={gone.file: reason}
        )
        assert bool(mesh3d.instance_missing(other)) is said, reason


@needs_qt
def test_a_part_whose_own_file_is_not_found_has_its_3d_print_off_with_the_reason(printer, models):
    """Right-clicking, in the 3D view, a part read from a sub-assembly's own file and drawn
    from what that sub-assembly stores of it, its own file not found, offers 3D Print Part
    off with the reason, as a row's entry is for a file not found, and still 3D Print
    Sub-assembly; a part of the same sub-assembly whose file is there still prints."""
    from solidseas_app.viewer.details import TABS
    from solidseas_app.viewer.preview import MODEL
    from test_viewer import _stub_view_factory

    _top_of_o15(models)
    os.remove(models / "o02_boxA.SLDPRT")
    p = printer()
    w = p.window
    d, pane = w.details, w.details.preview
    pane.view_factory = _stub_view_factory([])
    pane.gl_check = lambda: (True, "test")
    w.change_settings(view_3d=True)
    d.tabs.setCurrentIndex(TABS.index("Preview"))
    p.open(models, "top2.SLDASM")
    pane.set_mode(MODEL)
    _wait(p.app, lambda: pane.mesh_state not in ("idle", "starting", "loading") and not w.busy)
    ident = "o15_sub_asm-1/o02_boxA-1"
    assert pane.mesh_state == "ready" and ident in pane.instance_ids
    assert ident not in pane.instance_documents and pane.instance_missing[ident]["reason"] == "missing"
    menu = d.instance_menu(ident)
    texts = _texts(menu)
    entry = _entry(menu, "3D Print Part")
    assert texts[texts.index("3D Print Part o02_boxA.SLDPRT (not found)") + 1] == (
        "3D Print Sub-assembly o15_sub_asm.SLDASM"
    )
    assert not entry.isEnabled() and menu.toolTipsVisible()
    said = entry.toolTip()  # plain text, escaped (wording.tip)
    assert "o02_boxA.SLDPRT cannot be 3D printed from here.<br><br>No file of that name was found." in said
    assert "what its sub-assembly stores of it" in said and "Stored path: " in said
    assert _entry(menu, "3D Print Sub-assembly").isEnabled()
    menu.deleteLater()
    found = d.instance_menu("o15_sub_asm-1/o07_boxB_h31-1")
    assert _entry(found, "3D Print Part").isEnabled() and "3D Print Part o07_boxB_h31.SLDPRT" in _texts(found)
    found.deleteLater()


@needs_qt
def test_a_part_printed_in_a_configuration_it_stores_no_bodies_of_says_so(printer, models):
    """o16 uses o06 in OracleAlt, of which o06 stores no bodies: its Default ones are
    exported, the file is named after what it holds, and the status line says so."""
    p = printer()
    d = p.window.details
    p.open(models, O16)
    requests = p.record_requests()
    row = d.instance_item("o06_boxA_props_mat_cfg-1")
    outcome = p.choose(_entry(d.component_menu(row), "3D Print"))
    assert requests[-1]["configuration"] == "OracleAlt"
    assert outcome["ok"] and outcome["configuration"] == "Default"
    assert outcome["file"] == str(models / f"o06_boxA_props_mat_cfg {TODAY}.3mf")
    said = p.window.statusBar().currentMessage()
    assert said == (
        f"Saved {outcome['file']} and opened it in Bambu Studio (in configuration Default, as the part "
        "stores no geometry of OracleAlt). Bambu Studio is now the 3D Print program; Settings > 3D Print "
        "Program changes it."
    )


def _drawing_of_o02(configurations: tuple[str, str]) -> bytes:
    """A drawing of o02 with two views, in ``configurations``, as tests/test_viewer.py
    makes one."""
    from builders import drawing_keywords, rebuild, sheet_names
    from support import ASSEMBLY

    changes = {
        "swXmlContents/KeyWords": drawing_keywords(
            {
                "Sheet1": [
                    ("Drawing View1", configurations[0], "o02_boxa.sldprt"),
                    ("Drawing View2", configurations[1], "o02_boxa.sldprt"),
                ]
            }
        ),
        "SheetPreviews/SheetNames": sheet_names(["Sheet1"]),
    }
    return rebuild(
        fixture_path(ASSEMBLY), changes, drop=("Contents/Definition", "swXmlContents/COMPINSTANCETREE")
    )


@needs_qt
def test_a_drawings_rows_print_in_the_configuration_they_show(printer, models):
    """A drawing's views print the model in the configuration each shows, its Models table
    and the References tab in the one configuration the drawing uses it in, else the
    active one; their menus show the entry's tooltip, which names the configuration."""
    from solidseas_app.viewer.details import KEY_ROLE

    (models / "sheet.SLDDRW").write_bytes(_drawing_of_o02(("Default", "Long")))
    (models / "same.SLDDRW").write_bytes(_drawing_of_o02(("Default", "Default")))
    p = printer()
    w = p.window
    d = w.details
    requests: list[dict] = []

    def record(request, cancelled):
        requests.append(request)
        return {"ok": False, "error": {"code": "recorded", "message": "recorded"}}

    w.printer.export = record
    p.open(models, "sheet.SLDDRW")
    sheet = d.sheets.topLevelItem(0)
    for i, configuration in enumerate(("Default", "Long")):
        menu = d.component_menu(sheet.child(i))
        assert _texts(menu) == [
            opening.OPEN_TEXT,
            opening.show_text(),
            "",
            "Go to file",
            "Show in folder list",
            "",
            "3D Print o02_boxA.SLDPRT",
        ]
        assert menu.toolTipsVisible() and f"in configuration {configuration}" in menu.actions()[-1].toolTip()
        p.choose(menu.actions()[-1])
        assert requests[-1]["configuration"] == configuration and requests[-1]["path"] == str(
            models / "o02_boxA.SLDPRT"
        )
        menu.deleteLater()
    key = sheet.child(0).data(0, KEY_ROLE)
    assert d.only_configuration(key) == ""  # used in two
    for tree in ("models", "references"):
        row = d.find_item(tree, "o02_boxA.SLDPRT")
        p.choose(_entry(d.component_menu(row), "3D Print o02_boxA.SLDPRT"))
        assert requests[-1]["configuration"] is None, tree
    p.open(models, "same.SLDDRW")  # used in one: that one
    for tree in ("models", "references"):
        row = d.find_item(tree, "o02_boxA.SLDPRT")
        p.choose(_entry(d.component_menu(row), "3D Print o02_boxA.SLDPRT"))
        assert requests[-1]["configuration"] == "Default", tree


@needs_qt
def test_every_component_menu_shows_its_entries_tooltip(printer, models):
    p = printer()
    d = p.window.details
    p.open(models, O16)
    from solidseas_app.viewer.details import KEY_ROLE

    row = d.instance_item("o06_boxA_props_mat_cfg-1")
    files_row = d.find_item("files", "o02_boxA.SLDPRT")
    menus = [
        d.component_menu(row),
        d.component_menu(files_row),
        d.instance_menu(INNER),
        d._file_link_menu(files_row.data(0, KEY_ROLE)),
        d.component_menu(d.find_item("references", "o02_boxA.SLDPRT")),
    ]
    for menu in menus:
        assert menu.toolTipsVisible(), _texts(menu)
    assert "in configuration OracleAlt" in _entry(menus[0], "3D Print").toolTip()
    for menu in menus:
        menu.deleteLater()


@needs_qt
def test_while_an_export_runs_every_menu_offers_cancel(printer, models):
    p = printer()
    w = p.window
    c, d = w.printer, w.details
    started = threading.Event()
    c.export = _hold(started)
    p.open(models, O16)
    c.print_resolved(w.print_target)
    _wait(p.app, started.is_set)
    from solidseas_app.viewer.documents import NAME

    index = w.proxy.mapFromSource(w.model.index(w.model.find("o02_boxA.SLDPRT"), NAME))
    menus = [
        w.list_menu(index),
        d.component_menu(d.instance_item(INNER)),
        d.instance_menu(INNER),
        w.details.preview.space_menu(),
    ]
    for menu in menus:
        assert "Cancel 3D Print" in _texts(menu) and not any(t.startswith("3D Print") for t in _texts(menu))
    assert _texts(menus[2]).count("Cancel 3D Print") == 1  # one for the part and the sub-assembly
    n = len(p.outcomes)
    _entry(menus[1], "Cancel 3D Print").trigger()
    _wait(p.app, lambda: len(p.outcomes) > n)
    assert p.outcomes[-1]["cancelled"] and not c.busy and p.started == []
    assert any(t.startswith("3D Print") for t in _texts(d.component_menu(d.instance_item(INNER))))
    for menu in menus:
        menu.deleteLater()


# --------------------------------------------------------------------------- the self-test
@needs_qt
def test_the_self_tests_dry_run_writes_nothing_outside_the_folder_under_test(
    app, tmp_path, programs, no_drive_q
):
    """A component the self-test's folder finds outside itself, on a drive of this
    computer, is printed into the temporary folder with the reason said: the run writes
    print files next to the models of the folder it was pointed at, and nowhere else."""
    from PySide6.QtCore import QTimer

    from builders import part_with_creation_time
    from solidseas_app.viewer.selftest import SelfTest
    from solidseas_app.viewer.window import MainWindow

    new = tmp_path / "New"
    (new / "lib").mkdir(parents=True)
    (new / "Proj").mkdir()
    (new / "lib" / "p.SLDPRT").write_bytes(part_with_creation_time(1_700_000_000))
    (new / "Proj" / "asm.SLDASM").write_bytes(
        _crafted_assembly(["Q:\\Old\\lib\\p.SLDPRT"], folder_at_save="Q:\\Old\\Proj\\")
    )
    outside = _files(new / "lib")
    window = MainWindow()
    window.resize(1200, 800)
    window.show()
    window.printer.detect = lambda: _detect(programs["env"])
    window.printer.today = lambda: TODAY
    (tmp_path / "temp").mkdir()
    window.printer.out_base = str(tmp_path / "temp")
    shots = tmp_path / "shots"
    st = SelfTest(
        window,
        str(new / "Proj"),
        screenshot_dir=str(shots),
        select=["asm.SLDASM"],
        print_dry_run=True,
        print_menus={"asm.SLDASM": [("row", "c2-1", "")]},
    )
    QTimer.singleShot(0, st.start)
    assert app.exec() == 0
    window.shutdown()
    window.close()
    report = json.loads((shots / "selftest.json").read_text(encoding="utf-8"))
    assert report["ok"], (report["errors"], [d["errors"] for d in report["documents"]])
    menus = report["documents"][0]["print_menus"]
    temp = printing.export_folder_path(str(tmp_path / "temp"))
    assert [m["via"] for m in menus] == ["row c2-1", "row c2-1 again"]
    for m, name in zip(menus, (f"p {TODAY}.3mf", f"p {TODAY} (2).3mf"), strict=True):
        assert m["ok"] and m["place"] == printing.TEMP and m["fallback"] == printing.CONFINED
        assert m["file"] == os.path.join(temp, name) and printing.CONFINED in m["note"]
    assert _files(new / "lib") == outside


@needs_qt
def test_the_self_test_dry_run_reports_what_it_would_start(app, tmp_path, programs, models):
    from PySide6.QtCore import QTimer

    from solidseas_app.viewer.selftest import SelfTest
    from solidseas_app.viewer.window import MainWindow

    window = MainWindow()
    window.resize(1200, 800)
    window.show()
    window.printer.detect = lambda: _detect(programs["env"])
    window.printer.today = lambda: TODAY
    (tmp_path / "temp").mkdir()
    window.printer.out_base = str(tmp_path / "temp")
    shots = tmp_path / "shots"
    before = _files(models)
    st = SelfTest(
        window,
        str(models),
        screenshot_dir=str(shots),
        select=["o02_boxA.SLDPRT", O16, "o18_drw_boxA.SLDDRW"],
        print_dry_run=True,
        print_menus={
            O16: [
                ("row", "o15_sub_asm-1", ""),
                ("row", "o07_boxB_h31.SLDPRT", ""),
                ("view", INNER, "part"),
                ("view", INNER, "sub"),
                ("view", "", "space"),
            ]
        },
    )
    QTimer.singleShot(0, st.start)
    assert app.exec() == 0
    window.shutdown()
    window.close()
    report = json.loads((shots / "selftest.json").read_text(encoding="utf-8"))
    assert report["ok"], (report["errors"], [d["errors"] for d in report["documents"]])
    part, asm, drawing = (d["print"] for d in report["documents"])
    bambu = os.path.normpath(programs["bambu"])
    for outcome, kind in ((part, "part"), (asm, "assembly")):
        assert outcome["ok"] and outcome["dry_run"] and not outcome["started"] and outcome["doc_type"] == kind
        assert outcome["executable"] == bambu and outcome["arguments"] == [outcome["file"]]
        assert os.path.dirname(outcome["file"]) == str(models) and outcome["place"] == printing.MODEL
        assert zipfile.is_zipfile(outcome["file"]) and outcome["closed"]
    assert part["file"] == str(models / f"o02_boxA {TODAY}.3mf")
    assert asm["items"] == 12 and drawing == {"ok": False, "printable": False}
    doc_part, doc_asm, doc_drawing = report["documents"]
    assert doc_part["print_again"]["file"] == str(models / f"o02_boxA {TODAY} (2).3mf")
    assert [c["number"] for c in doc_part["print_checks"]] == [1, 2]
    assert [c["number"] for c in doc_asm["print_checks"]] == [1, 2]
    menus = doc_asm["print_menus"]
    assert [m["via"] for m in menus] == [
        "row o15_sub_asm-1",
        "row o15_sub_asm-1 again",
        "row o07_boxB_h31.SLDPRT",
        "row o07_boxB_h31.SLDPRT again",
        f"view {INNER},part",
        f"view {INNER},part again",
        f"view {INNER},sub",
        f"view {INNER},sub again",
        "view .",
        "view . again",
    ]
    assert all(m["ok"] and "problems" not in m and m["place"] == printing.MODEL for m in menus)
    # The sub-assembly printed from its row first, from the 3D view later: numbered on.
    subs = [m for m in menus if os.path.basename(m["file"]).startswith("o15_sub_asm")]
    assert [m["number"] for m in subs] == [1, 2, 3, 4]
    assert [m["number"] for m in menus if m["via"].startswith("view .")] == [3, 4]  # after the button's two
    names = [os.path.basename(p) for p in report["screenshots"]]
    assert sum("print_button" in n for n in names) == 2 and sum("print_program_menu" in n for n in names) == 2
    assert sum("print_preferences" in n for n in names) == 2 and sum("print_busy" in n for n in names) == 2
    menus_saved = [n for n in names if "_print_menu_" in n]  # each menu once, as it opened
    assert len(menus_saved) == 5 and all(n.startswith(tuple("0123456789")) for n in menus_saved)
    inner = "o16_asm_features_print_menu_view_o15_sub_asm-1_o07_boxB_h31-1_part.png"
    assert any(n.endswith(inner) for n in names)
    assert [d.get("print_busy_button") for d in report["documents"]] == ["Cancel 3D Print"] * 2 + [None]
    assert all(Path(p).stat().st_size > 0 for p in report["screenshots"])
    after = _files(models)
    assert {k: v for k, v in after.items() if k in before} == before  # only new print files
    assert all(k.endswith(".3mf") and TODAY in k for k in set(after) - set(before))


def _top_of_one_sub_assembly(folder: Path) -> None:
    """top2.SLDASM, holding o15_sub_asm-1 with none of its components stored: the 3D view
    reads them from o15's own file, and no row of the Components tab stands for them."""
    from builders import TreeXml, assembly_with_tree

    t = TreeXml()
    t.top("m1")
    t.file("2", "o15_sub_asm.SLDASM", "ASSEMBLY")
    t.model("m2", "2")
    t.ref("m1", "o15_sub_asm", 1, "m2")
    (folder / "top2.SLDASM").write_bytes(assembly_with_tree(t))


@needs_qt
def test_the_self_test_prints_through_real_right_clicks_on_the_3d_view(tmp_path, programs):
    """On the real display: the self-test right-clicks a part the 3D view read from a
    sub-assembly's own file, and a virtual part a sub-assembly stores, and chooses 3D
    Print Part in the menu that opens; each is printed twice next to the file it comes
    from, named after it. On Windows a slicer of the made-up install folders is found;
    elsewhere none is looked for (:func:`printing.detect`), so the run's own settings
    file holds the program, as Settings > 3D Print Program would. The dry run starts
    nothing."""
    import subprocess

    from gl_support import display_env
    from solidseas_app.viewer.selftest import SETTINGS_NAME

    models = tmp_path / "models"
    shutil.copytree(FIXTURES, models)
    _top_of_one_sub_assembly(models)
    _virtual_in_sub(models)
    from solidseas_app.viewer import samples

    (models / "box.stl").write_bytes(samples.stl_binary())  # a model file prints named as one too
    before = _files(models)
    shots = tmp_path / "shots"
    args = ["--self-test", str(models), "--screenshot-dir", str(shots), "--3d", "--print-dry-run"]
    args += ["--select", "box.stl"]
    args += ["--select", "top2.SLDASM", "--print-view", "o15_sub_asm-1/o02_boxA-1"]
    args += ["--select", "top.SLDASM", "--print-view", "sub-1/Part12^o16_asm_features-1"]
    if os.name != "nt":
        # The run's settings file is its own, next to its report: written first, it is kept
        # (--force) and only its own section of preferences is saved over.
        shots.mkdir()
        chosen = json.dumps(str(programs["bambu"]))
        (shots / SETTINGS_NAME).write_text(f"[print]\nprogram=other\npath={chosen}\n", encoding="utf-8")
        args.append("--force")
    env = display_env(APPDATA=str(tmp_path / "Roaming"), **programs["env"])
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "solidseas_app", *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        pytest.skip("the display did not answer in time")
    if "Traceback" in proc.stderr:
        pytest.fail(f"the self-test raised:\n{proc.stderr.strip()[-3000:]}")
    if not (shots / "selftest.json").exists():
        pytest.skip(f"no display to draw on here: {proc.stderr.strip()[-300:]}")
    report = json.loads((shots / "selftest.json").read_text(encoding="utf-8"))
    if not (report.get("opengl") or {}).get("available"):
        pytest.skip("OpenGL is not available here")
    assert proc.returncode == 0 and report["ok"], (
        report["errors"],
        [d["errors"] for d in report["documents"]],
    )
    stl, *assemblies = report["documents"]
    top2, top = (d["print_menus"] for d in assemblies)
    assert [m["via"] for m in top2] == [
        "view o15_sub_asm-1/o02_boxA-1,part (right-click)",
        "view o15_sub_asm-1/o02_boxA-1,part (right-click) again",
    ]
    day = printing.today()  # the child names its prints with the local date, as the window does
    assert stl["print"]["ok"] and stl["print"]["file"] == str(models / f"box {day}.3mf")
    assert [m["file"] for m in top2] == [str(models / f"o02_boxA {day}{n}.3mf") for n in ("", " (2)")]
    assert [m["file"] for m in top] == [
        str(models / f"Part12_o16_asm_features {day}{n}.3mf") for n in ("", " (2)")
    ]
    assert all(m["ok"] and m["place"] == printing.MODEL for m in top2 + top)
    names = [Path(p).name for p in report["screenshots"]]
    assert any(n.endswith("top2_print_menu_view_o15_sub_asm-1_o02_boxA-1_part.png") for n in names), names
    assert sum("_print_menu_" in n for n in names) == 2
    assert all(d["print"]["dry_run"] and not d["print"]["started"] for d in report["documents"])
    after = _files(models)
    assert {k: v for k, v in after.items() if k in before} == before
    assert all(k.endswith(".3mf") for k in set(after) - set(before))
