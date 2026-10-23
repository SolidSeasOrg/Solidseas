"""``solidseas drawing ACTION`` (docs/DRAWINGS.md 14, docs/drawings/cli.md): every action
on the o02, o03, o07 and o10 fixtures, the ``drawing_result`` kind validated strictly
against its schema, the files and their names (12.5, 12.6), the refusals (a released
drawing, a model not found, a file the CLI did not write, ``--units part`` on a part
that states no unit), exit codes, the four drawing error codes, and that nothing is
written outside pytest's temporary folder.

Parts are copied under fictional names; Drawing Settings name the fictional "Example
Engineering Co." and its people. The checks module is built in parallel, so the
checks come from a stand-in put in its place, or from what the drawing carries when
the module is missing.
"""

import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

import solidseas
from builders import fixture_streams, rebuild
from jsonschema_subset import validate
from solidseas import cli, model
from solidseas.drawing import document, merge, pipeline, release
from solidseas.drawing import settings as S
from solidseas.drawing.limits import DrawingLimits
from solidseas.errors import (
    DrawingInvalidError,
    DrawingReleasedError,
    DrawingTooComplexError,
    InvalidArgumentError,
    ModelNotFoundError,
    SldLimitError,
)
from support import fixture_path

TODAY = "2026-10-07"
SETTINGS = {
    "schema": "solidseas.drawing-settings/1",
    "company": {"name": "Example Engineering Co."},
    "people": {"people": [{"name": "Ann Bee", "initials": "AB"}, {"name": "Carl Dee", "initials": "CD"}]},
}


def _no_constants(name):
    raise ValueError(f"{name} is not strict JSON")


def run(capsys, *argv) -> tuple[int, dict]:
    """One ``drawing`` command with --json: one strict JSON document, nothing on stderr,
    validated strictly against its kind's envelope schema."""
    code = cli.main(["drawing", *argv, "--json"])
    out, err = capsys.readouterr()
    assert err == "", err
    env = json.loads(out, parse_constant=_no_constants)
    kind = env["kind"]
    assert kind in ("drawing_result", "error") and env["ok"] is (kind != "error")
    errors = validate(env, model.envelope_schema(kind), strict=True)
    assert errors == [], errors[:5]
    return code, env


def data_of(env: dict) -> dict:
    assert env["ok"], env.get("error")
    return env["data"]


def error_of(env: dict) -> dict:
    assert not env["ok"]
    return env["error"]


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree(folder: Path) -> dict[str, str]:
    """Every file below ``folder``, by path relative to it, with its hash."""
    return {p.relative_to(folder).as_posix(): sha(p) for p in sorted(folder.rglob("*")) if p.is_file()}


# --------------------------------------------------------------------------- what nothing may write outside
_WRITES: list[tuple[str, str]] | None = None
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


def _audit(event: str, args: tuple) -> None:
    """Record every file a test's command opens for writing, renames, makes or removes."""
    if _WRITES is None:
        return
    if event == "open" and len(args) >= 3:
        path, mode, flags = args[0], args[1], args[2]
        writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & _WRITE_FLAGS
        )
        if writing and isinstance(path, (str, bytes, os.PathLike)):
            _WRITES.append((event, os.path.abspath(os.fsdecode(path))))
    elif event in ("os.rename", "os.remove", "os.mkdir", "os.truncate") and args:
        for p in args[:2] if event == "os.rename" else args[:1]:
            if isinstance(p, (str, bytes, os.PathLike)):
                _WRITES.append((event, os.path.abspath(os.fsdecode(p))))


_HOOKED = False


@pytest.fixture
def writes():
    """The files commands write while the test runs: an audit hook (installed once, idle
    outside these tests) records them."""
    global _WRITES, _HOOKED
    if not _HOOKED:
        sys.addaudithook(_audit)
        _HOOKED = True
    _WRITES = []
    try:
        yield _WRITES
    finally:
        _WRITES = None


# --------------------------------------------------------------------------- the place a test works in
@dataclass
class Place:
    root: Path
    parts: Path
    out: Path
    cfg: Path

    def part(self, fixture: str = "o02_boxA.SLDPRT", name: str = "bracket.SLDPRT") -> str:
        target = self.parts / name
        shutil.copyfile(fixture_path(fixture), target)
        return str(target)

    def settings(self, values: dict | None = None) -> str:
        path = self.cfg / "solidseas" / S.FILE_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(values or SETTINGS), encoding="utf-8")
        return str(path)


@pytest.fixture
def place(tmp_path, monkeypatch) -> Place:
    """Parts in ``parts``, drawings in ``out``, Drawing Settings in ``cfg`` (never the
    user's), the current folder ``cwd``: all inside ``tmp_path``."""
    p = Place(tmp_path, tmp_path / "parts", tmp_path / "out", tmp_path / "cfg")
    for folder in (p.parts, p.out, p.cfg, tmp_path / "cwd"):
        folder.mkdir()
    monkeypatch.setattr(S, "settings_folder", lambda *a, **k: str(p.cfg / "solidseas"))
    monkeypatch.chdir(tmp_path / "cwd")
    return p


@dataclass(frozen=True)
class Check:
    """A stand-in for ``checks.Check`` while the checks module is built elsewhere."""

    code: str
    level: str
    message: str
    item: str = ""
    fixes: tuple[str, ...] = ()


def stand_in(monkeypatch, checks=(), calls=None):
    """Put ``run_checks`` returning ``checks`` where ``pipeline.resolve`` finds it."""
    real = pipeline.resolve

    def run_checks(drawing, *, planned=None, layout=None, release=False):
        if calls is not None:
            calls.append((drawing.id, planned, layout, release))
        return tuple(checks)

    def resolve(name, path):
        return run_checks if name == "checks" else real(name, path)

    monkeypatch.setattr(pipeline, "resolve", resolve)


def no_checks_module(monkeypatch):
    real = pipeline.resolve

    def resolve(name, path):
        if name == "checks":
            raise pipeline.stage_missing(name)
        return real(name, path)

    monkeypatch.setattr(pipeline, "resolve", resolve)


def new(capsys, place: Place, *extra, part=None) -> dict:
    code, env = run(
        capsys,
        "new",
        part or place.part(),
        "--out",
        str(place.out),
        "--title",
        "BRACKET, MOTOR MOUNT",
        "--number",
        "1234-001",
        "--drawn-by",
        "Ann Bee",
        "--material",
        "6061-T6",
        "--finish",
        "None",
        *extra,
    )
    assert code == 0, env
    return data_of(env)


TITLE_GAPS = {
    "the title block's MATERIAL is empty",
    "the title block's FINISH is empty",
    "the title block names no company; Drawing Settings hold none",
    "nobody is named as DRAWN, with the date",
}


def only_title_gaps(code: int, env: dict) -> bool:
    """Whether a check found nothing wrong but title block gaps: a part checked without a
    material, finish and DRAWN, or with no Drawing Settings, always has them (R6.title is an
    error, so the command exits 4)."""
    errors = [c for c in data_of(env)["checks"] if c["level"] == "error"]
    gaps = {c["message"] for c in errors if c["code"] == "R6.title"}
    return code == cli.EXIT_PARTIAL and errors and len(errors) == len(gaps) and gaps <= TITLE_GAPS


# --------------------------------------------------------------------------- new
def test_new_writes_the_drawing_and_its_preliminary_exports(capsys, place):
    part = place.part()
    data = new(capsys, place, "--pdf", "--dxf", part=part)
    assert data["action"] == "new" and not data["dry_run"]
    names = [f["name"] for f in data["files"]]
    assert names == ["1234-001.ssdrw", "1234-001 A PRELIMINARY.pdf", "1234-001 A PRELIMINARY.dxf"]
    assert [f["kind"] for f in data["files"]] == ["ssdrw", "pdf", "dxf"]
    for f in data["files"]:
        assert Path(f["path"]).parent == place.out and sha(f["path"]) == f["sha256"]
        assert f["bytes"] == os.path.getsize(f["path"]) and not f["replaced"] and not f["renamed"]
    assert sorted(os.listdir(place.out)) == sorted(names)
    d = data["drawing"]
    assert d["status"] == "PRELIMINARY" and d["revision"] == "A"
    assert d["title"]["title"] == {"text": "BRACKET, MOTOR MOUNT", "from": "typed"}
    assert d["title"]["number"] == {"text": "1234-001", "from": "typed"}
    assert [(s["row"], s["name"], s["current"]) for s in d["signatures"]] == [("DRAWN", "Ann Bee", True)]
    assert d["model"]["name"] == "bracket.SLDPRT" and d["model"]["unit"] == "mm"
    assert d["model"]["unit_origin"] == "file" and d["counts"]["dimensions"] == 6
    assert d["counts"]["views"] == 3 and d["options"]["scale"] == "2:1"
    assert [o["name"] for o in d["outputs"]] == names[1:]  # the exports, recorded in the drawing
    assert data["coverage"]["complete"] and data["coverage"]["faces"] == 6
    assert data["merge"] is None and data["settings"] is None and data["model_check"] is None
    stages = list(data["seconds"])
    assert stages[:6] == ["source", "model", "features", "views", "plan", "assemble"]
    assert {"checks", "pdf", "dxf", "total"} <= set(stages)
    # the file holds what the result says, and names the model where it is
    loaded = document.read(data["files"][0]["path"])
    assert loaded.problems == ()  # the file reads back whole: every feature's descriptor too
    assert loaded.drawing.id == d["id"] and [o.sha256 for o in loaded.drawing.outputs] == [
        f["sha256"] for f in data["files"][1:]
    ]
    assert (
        loaded.drawing.model["stored"] == os.path.abspath(part) and loaded.drawing.model["relative"] is None
    )
    assert sha(part) == sha(fixture_path("o02_boxA.SLDPRT"))  # the part is never written


def test_new_in_plain_words(capsys, place):
    code = cli.main(["drawing", "new", place.part(), "--out", str(place.out), "--number", "1234-001"])
    out, err = capsys.readouterr()
    assert code == 0 and err == ""
    assert f"wrote {place.out / '1234-001.ssdrw'}" in out
    assert "PRELIMINARY drawing 1234-001, revision A: 6 dimensions in 3 views" in out
    assert "coverage: every recognised face is dimensioned" in out


def test_new_never_replaces_a_file_it_did_not_write(capsys, place):
    (place.out / "1234-001.ssdrw").write_bytes(b"someone else's file")
    (place.out / "1234-001 A PRELIMINARY.pdf").write_bytes(b"%PDF-1.7 someone else's")
    before = tree(place.out)
    data = new(capsys, place, "--pdf")
    assert [(f["name"], f["renamed"], f["replaced"]) for f in data["files"]] == [
        ("1234-001 (2).ssdrw", True, False),
        ("1234-001 A PRELIMINARY (2).pdf", True, False),
    ]
    assert {k: v for k, v in tree(place.out).items() if k in before} == before
    assert any("1234-001.ssdrw is taken" in w for w in data["warnings"])
    again = new(capsys, place)  # a second drawing is another drawing: its own new name
    assert again["files"][0]["name"] == "1234-001 (3).ssdrw"


def test_new_takes_every_option_of_the_table(capsys, place, tmp_path):
    data = new(
        capsys,
        place,
        "--process",
        "printed",
        "--scheme",
        "plusminus",
        "--units",
        "in",
        "--views",
        "front,top,right",
        "--sheet",
        "B",
        "--scale",
        "1:1",
        "--front",
        "+z",
        "--turn",
        "1",
        "--part-number",
        "PN-77",
        "--revision",
        "C",
        "--material",
        "ALUMINUM 6061-T6",
        "--finish",
        "ANODIZE CLEAR",
        "--settings",
        place.settings(),
    )
    d = data["drawing"]
    assert d["options"] == {
        "process": "printed",
        "scheme": "plusminus",
        "detail": "full",
        "units": "in",
        "views": ["front", "top", "right"],
        "sheet": "B",
        "scale": "1:1",
    }
    assert d["revision"] == "C" and d["title"]["part_number"]["text"] == "PN-77"
    assert d["title"]["finish"]["text"] == "ANODIZE CLEAR" and 1 <= d["counts"]["views"] <= 3


@pytest.mark.parametrize(
    "extra",
    [
        ("--scale", "1-2"),
        ("--views", "front,nowhere"),
        ("--turn", "5"),
        ("--process", "sheet_metal"),
        ("--units", "cm"),
    ],
)
def test_bad_options_are_usage_errors(capsys, place, extra):
    code, env = run(capsys, "new", place.part(), "--out", str(place.out), *extra)
    assert code == cli.EXIT_USAGE and error_of(env)["code"] == "invalid_argument"
    assert os.listdir(place.out) == []


def test_the_out_folder_is_checked(capsys, place):
    part = place.part()
    code, env = run(capsys, "new", part, "--out", str(place.root / "nowhere"))
    assert code == 3 and error_of(env)["code"] == "output_refused"
    assert error_of(env)["detail"]["rule"] == "output_folder"
    code, env = run(capsys, "new", part, "--out", str(place.parts))  # next to the part
    assert code == 3 and error_of(env)["detail"]["rule"] == "source_folder"
    assert os.listdir(place.parts) == ["bracket.SLDPRT"]
    code, env = run(capsys, "new", part, "--out", str(place.parts), "--allow-source-dir")
    assert code == 0 and [f["name"] for f in data_of(env)["files"]] == ["BRACKET.ssdrw"]
    loaded = document.read(place.parts / "BRACKET.ssdrw")
    assert loaded.drawing.model["relative"] == "bracket.SLDPRT"  # next to the part: relative


def _unitless(place: Place) -> str:
    """o02 saved as if its part stated no unit of length."""
    o02 = fixture_path("o02_boxA.SLDPRT")
    info = fixture_streams(o02)["docProps/ISolidWorksInformation.xml"]
    path = place.parts / "plate.SLDPRT"
    path.write_bytes(
        rebuild(
            o02, {"docProps/ISolidWorksInformation.xml": info.replace(b"SW_UnitSystem", b"XX_UnitSystem")}
        )
    )
    return str(path)


def test_units_part_needs_a_unit_when_the_part_states_none(capsys, place):
    part = _unitless(place)
    code, env = run(capsys, "new", part, "--out", str(place.out))
    err = error_of(env)
    assert code == 2 and err["code"] == "invalid_argument"
    assert err["detail"] == {"parameter": "units", "rule": "units_unstated"} and os.listdir(place.out) == []
    code, env = run(capsys, "new", part, "--out", str(place.out), "--units", "part")
    assert code == 2 and error_of(env)["detail"]["rule"] == "units_unstated"
    code, env = run(capsys, "new", part, "--out", str(place.out), "--units", "mm")
    d = data_of(env)["drawing"]
    assert code == 0 and d["options"]["units"] == "mm" and d["model"]["unit_origin"] == "user"
    # check never writes, so it goes on and says the unit was guessed
    code, env = run(capsys, "check", part)
    assert only_title_gaps(code, env) and any("states no unit" in w for w in data_of(env)["warnings"])


def test_new_refuses_what_is_not_a_part_or_an_assembly(capsys, place):
    drw = place.parts / "frame.SLDDRW"
    shutil.copyfile(fixture_path("o18_drw_boxA.SLDDRW"), drw)
    code, env = run(capsys, "new", str(drw), "--out", str(place.out))
    err = error_of(env)
    assert code == 1 and err["code"] == "not_implemented" and err["detail"]["rule"] == "drawing"
    code, env = run(capsys, "new", str(place.parts / "missing.SLDPRT"), "--out", str(place.out))
    assert code == 1 and error_of(env)["code"] == "not_found"
    assert os.listdir(place.out) == []


def test_new_draws_an_assembly_with_its_parts_list(capsys, place):
    asm = place.part("o08_asm_2x_boxA.SLDASM", "o08_asm_2x_boxA.SLDASM")
    place.part("o02_boxA.SLDPRT", "o02_boxA.SLDPRT")  # its part, beside it
    place.settings()
    extra = ("--number", "1234-100", "--drawn-by", "Ann Bee", "--pdf", "--dxf")
    code, env = run(capsys, "new", asm, "--out", str(place.out), *extra)
    assert code == 0, env
    data = data_of(env)
    d = data["drawing"]
    assert d["model"]["format"] == "sldasm" and d["model"]["name"] == "o08_asm_2x_boxA.SLDASM"
    # one item, its balloon, and the overall size as three reference dimensions
    assert d["counts"]["items"] == 1 and d["counts"]["balloons"] == 1 and d["counts"]["dimensions"] == 3
    assert data["coverage"] is None
    assert sorted(f["kind"] for f in data["files"]) == ["dxf", "pdf", "ssdrw"]
    assert [c["code"] for c in data["checks"] if c["level"] != "information"] == []
    saved = next(f["path"] for f in data["files"] if f["kind"] == "ssdrw")
    assert cli.main(["drawing", "show", saved]) == 0
    out, _err = capsys.readouterr()
    assert "PRELIMINARY assembly drawing 1234-100, revision A: 1 item and 1 balloon in 4 views" in out


# --------------------------------------------------------------------------- thread candidates
def test_confirmed_threads_reach_the_callout_and_the_feature(capsys, place):
    part = place.part("o10_import_step_cut.SLDPRT", "plate.SLDPRT")
    place.settings()
    code, env = run(capsys, "check", part)
    assert only_title_gaps(code, env)
    assert data_of(env)["thread_candidates"] == [
        {
            "feature": "f-1",
            "kind": "hole",
            "count": 1,
            "diameter_mm": 5.0,
            "threads": ["M6 x 1"],
            "answered": False,
            "confirmed": None,
        }
    ]
    answers = place.root / "threads.json"
    answers.write_text(json.dumps({"f-1": {"thread": "M6 x 1", "depth_mm": 8}}), encoding="utf-8")
    data = new(capsys, place, "--confirm-threads", str(answers), part=part)
    assert data["thread_candidates"][0]["confirmed"] == "M6 x 1-6H"
    saved = data["files"][0]["path"]
    loaded = document.read(saved).drawing
    assert dict(loaded.features[0].decisions)["thread"] == "M6 x 1-6H"
    assert "M6 x 1-6H" in Path(saved).read_text(encoding="utf-8")  # on the sheet's hole callout
    # read back from the file, the candidate keeps its answer
    code, env = run(capsys, "check", saved)
    assert data_of(env)["thread_candidates"][0]["confirmed"] == "M6 x 1-6H"
    answers.write_text(json.dumps({"f-1": None}), encoding="utf-8")
    plain = new(capsys, place, "--confirm-threads", str(answers), part=part)
    assert plain["thread_candidates"][0]["answered"] and plain["thread_candidates"][0]["confirmed"] is None


@pytest.mark.parametrize(
    "text",
    [
        '{"f-9": "M6 x 1"}',  # not a candidate
        '{"f-1": "M8 x 1.25"}',  # not what the diameter taps
        '{"f-1": "M6 x 1", "f-1": null}',  # a key twice
        '["f-1"]',
        '{"hole": "M6 x 1"}',
        '{"f-1": {"thread": null, "depth_mm": 4}}',
        "{not json",
    ],
)
def test_bad_thread_answers_are_usage_errors(capsys, place, text):
    part = place.part("o10_import_step_cut.SLDPRT", "plate.SLDPRT")
    answers = place.root / "threads.json"
    answers.write_text(text, encoding="utf-8")
    code, env = run(capsys, "new", part, "--out", str(place.out), "--confirm-threads", str(answers))
    assert code == 2 and error_of(env)["detail"]["parameter"] == "confirm-threads"
    assert os.listdir(place.out) == []


def test_thread_candidates_from_a_drawings_records():
    from solidseas.drawing import keys
    from solidseas.drawing import types as T

    def hole(d, kind="simple"):
        return keys.descriptor("Hole", {"kind": kind, "diameters": (d,)}, {}, (0.0, 0.0, 0.0))

    pattern = keys.descriptor("Pattern", {"kind": "linear", "count": 4, "hole": (0.0068,)}, {}, (0, 0, 0))
    drawing = T.Drawing(
        "x",
        T.DrawingOptions(),
        S.DrawingSettings(),
        features=(
            T.FeatureRecord("f-1", hole(0.005)),
            T.FeatureRecord("f-2", hole(0.005, "counterbore")),
            T.FeatureRecord("f-3", hole(0.0123)),
            T.FeatureRecord("f-4", pattern, (("thread", "M8 x 1.25-6H"),)),
        ),
    )
    got = model.drawing_thread_candidates(drawing)
    assert [(c["feature"], c["kind"], c["count"], c["threads"], c["confirmed"]) for c in got] == [
        ("f-1", "hole", 1, ["M6 x 1"], None),
        ("f-4", "pattern", 4, ["M8 x 1.25"], "M8 x 1.25-6H"),
    ]


# --------------------------------------------------------------------------- export
def test_export_rewrites_only_its_own_unchanged_preliminary_files(capsys, place):
    made = new(capsys, place, "--pdf")
    drawing = made["files"][0]["path"]
    exports = place.root / "exports"
    exports.mkdir()
    code, env = run(capsys, "export", drawing, "--out", str(exports))
    data = data_of(env)
    assert code == 0 and [f["name"] for f in data["files"]] == [
        "1234-001 A PRELIMINARY.pdf",
        "1234-001 A PRELIMINARY.dxf",
    ]  # neither flag: both
    assert data["drawing"]["id"] == made["drawing"]["id"]
    # into the drawing's own folder: the PDF there is its own unchanged file, rewritten
    before = sha(drawing)
    code, env = run(capsys, "export", drawing, "--pdf", "--out", str(place.out), "--allow-source-dir")
    (pdf,) = data_of(env)["files"]
    assert code == 0 and pdf["name"] == "1234-001 A PRELIMINARY.pdf" and pdf["replaced"]
    assert sha(drawing) == before  # export never changes the drawing file
    # a PRELIMINARY export changed by someone else is never replaced
    (place.out / "1234-001 A PRELIMINARY.pdf").write_bytes(b"%PDF-1.7 edited by hand")
    code, env = run(capsys, "export", drawing, "--pdf", "--out", str(place.out), "--allow-source-dir")
    (pdf,) = data_of(env)["files"]
    assert pdf["name"] == "1234-001 A PRELIMINARY (2).pdf" and pdf["renamed"] and not pdf["replaced"]
    assert (place.out / "1234-001 A PRELIMINARY.pdf").read_bytes() == b"%PDF-1.7 edited by hand"
    code, env = run(capsys, "export", drawing, "--out", str(place.out))  # the drawing's folder
    assert code == 3 and error_of(env)["detail"]["rule"] == "source_folder"


def _released(capsys, place: Place) -> tuple[str, Path]:
    """A drawing made by the CLI, then signed and released through the library (the CLI
    never signs or releases), saved over its own file."""
    made = new(capsys, place, "--settings", place.settings())
    path = made["files"][0]["path"]
    loaded = document.read(path)
    d, _w = release.sign(loaded.drawing, "CHECKED", "Ann Bee", TODAY)
    d, _w = release.sign(d, "APPROVED", "Carl Dee", TODAY)
    d = release.release(d, TODAY)
    document.save(d, path, replaces=loaded.sha256)
    return path, Path(path).parent


def test_a_released_drawing_exports_its_released_revision_and_never_replaces(capsys, place):
    path, folder = _released(capsys, place)
    (folder / "1234-001 A.pdf").write_bytes(b"%PDF-1.7 the released file")
    exports = place.root / "exports"
    exports.mkdir()
    code, env = run(capsys, "export", path, "--pdf", "--out", str(exports))
    data = data_of(env)
    (pdf,) = data["files"]
    assert code == 0 and pdf["name"] == "1234-001 A.pdf" and pdf["released"] and not pdf["replaced"]
    assert data["drawing"]["status"] == "RELEASED"
    assert release.RECORD_MISMATCH not in data["warnings"]  # no released export recorded yet
    code, env = run(capsys, "export", path, "--pdf", "--out", str(folder), "--allow-source-dir")
    (pdf,) = data_of(env)["files"]
    assert pdf["name"] == "1234-001 A (2).pdf" and pdf["renamed"]
    assert (folder / "1234-001 A.pdf").read_bytes() == b"%PDF-1.7 the released file"


def test_show_says_when_a_release_record_does_not_match_the_files(capsys, place):
    path, folder = _released(capsys, place)
    loaded = document.read(path)
    recorded = document.record_output(loaded.drawing, "pdf", "1234-001 A.pdf", "0" * 64, released=True)
    document.save(recorded, path, replaces=loaded.sha256)
    code, env = run(capsys, "show", path)
    data = data_of(env)
    assert code == 0 and data["warnings"][0] == release.RECORD_MISMATCH
    assert data["drawing"]["outputs"] == [
        {"kind": "pdf", "name": "1234-001 A.pdf", "sha256": "0" * 64, "revision": "A", "released": True}
    ]


# --------------------------------------------------------------------------- update
def test_update_takes_a_new_model_reference_and_writes_over_its_own_file(capsys, place):
    part = place.part()
    made = new(capsys, place, part=part)
    path = made["files"][0]["path"]
    code, env = run(capsys, "update", path)
    data = data_of(env)
    assert code == 0 and data["merge"]["model_unchanged"] and data["files"] == []
    shutil.copyfile(fixture_path("o03_boxA_again.SLDPRT"), part)  # saved again, same geometry
    code, env = run(capsys, "update", path)  # a changed file is offered, never taken
    err = error_of(env)
    assert code == 1 and err["code"] == "model_not_found" and err["detail"]["rule"] == "model_not_found"
    assert "--model" in err["reader_message"]
    before = sha(path)
    code, env = run(capsys, "update", path, "--model", part, "--dry-run")
    data = data_of(env)
    assert code == 0 and data["dry_run"] and data["files"] == [] and sha(path) == before
    assert data["merge"]["words"] == merge.GEOMETRY_UNCHANGED and data["merge"]["geometry_unchanged"]
    code, env = run(capsys, "update", path, "--model", part)
    data = data_of(env)
    (f,) = data["files"]
    assert code == 0 and f["path"] == path and f["replaced"] and not f["renamed"] and sha(path) == f["sha256"]
    assert document.read(path).drawing.model["sha256"] == sha(fixture_path("o03_boxA_again.SLDPRT"))
    assert os.listdir(place.out) == ["1234-001.ssdrw"]


def test_update_merges_a_changed_geometry(capsys, place, monkeypatch):
    part = place.part()
    path = new(capsys, place, part=part)["files"][0]["path"]
    shutil.copyfile(fixture_path("o07_boxB_h31.SLDPRT"), part)
    stand_in(monkeypatch, [Check("R9.lines", "warning", "a line is too thin")])
    code, env = run(capsys, "update", path, "--model", part)
    data = data_of(env)
    report = data["merge"]
    assert code == 0 and not report["model_unchanged"] and not report["geometry_unchanged"]
    assert report["unchanged"] + report["changed"] + report["new"] == 6 and report["changed"] >= 1
    assert data["check_counts"] == {"error": 0, "warning": 1, "information": 0}
    assert data["coverage"]["complete"] and data["files"][0]["replaced"]


def test_update_refuses_a_released_drawing(capsys, place):
    path, _folder = _released(capsys, place)
    before = sha(path)
    code, env = run(capsys, "update", path, "--model", place.part("o07_boxB_h31.SLDPRT", "other.SLDPRT"))
    err = error_of(env)
    assert code == 3 and err["code"] == "drawing_released"
    assert err["detail"] == {"parameter": "drawing", "rule": "drawing_released"} and sha(path) == before


def test_update_with_replace_own_files_off_writes_a_new_name(capsys, place):
    off = dict(SETTINGS, files={"replace_own_files": False})
    part = place.part()
    path = new(capsys, place, "--settings", place.settings(off), part=part)["files"][0]["path"]
    shutil.copyfile(fixture_path("o03_boxA_again.SLDPRT"), part)
    before = sha(path)
    code, env = run(capsys, "update", path, "--model", part)
    (f,) = data_of(env)["files"]
    assert code == 0 and f["name"] == "1234-001 (2).ssdrw" and f["renamed"] and sha(path) == before


def test_update_finds_the_model_next_to_the_drawing(capsys, place):
    part = place.part()
    code, env = run(capsys, "new", part, "--out", str(place.parts), "--allow-source-dir")
    path = data_of(env)["files"][0]["path"]
    os.remove(part)
    code, env = run(capsys, "update", path)
    assert code == 1 and error_of(env)["code"] == "model_not_found"
    shutil.copyfile(fixture_path("o02_boxA.SLDPRT"), part)
    code, env = run(capsys, "update", path)
    assert code == 0 and data_of(env)["merge"]["model_unchanged"]


# --------------------------------------------------------------------------- check, show, settings
def test_check_uses_run_checks_and_strict_fails_on_warnings(capsys, place, monkeypatch):
    calls = []
    stand_in(
        monkeypatch,
        [
            Check("R9.lines", "warning", "a centre line is missing", "v-1", ("Add Centre Line",)),
            Check("R3.roles", "information", "precisions by role", ""),
        ],
        calls,
    )
    part = place.part()
    code, env = run(capsys, "check", part)
    data = data_of(env)
    assert code == 0 and data["check_counts"] == {"error": 0, "warning": 1, "information": 1}
    assert data["checks"][0] == {
        "code": "R9.lines",
        "level": "warning",
        "item": "v-1",
        "message": "a centre line is missing",
        "fixes": ["Add Centre Line"],
    }
    assert data["checks"][1]["item"] == "R3.roles"  # about the drawing: the code itself
    assert data["coverage"]["complete"] and data["files"] == [] and os.listdir(place.out) == []
    code, env = run(capsys, "check", part, "--strict")
    assert code == cli.EXIT_PARTIAL == 4
    drawing = new(capsys, place)["files"][0]["path"]
    code, env = run(capsys, "check", drawing)
    assert code == 0 and data_of(env)["coverage"] is None  # a file does not store coverage
    assert calls and calls[-1][1:] == (None, None, False)  # a file is checked without the model
    stand_in(monkeypatch, [Check("R4.complete", "error", "f-2 is not located along X", "f-2")])
    code, env = run(capsys, "check", drawing)
    assert code == 4 and data_of(env)["check_counts"]["error"] == 1


def test_without_a_checks_module_the_drawings_own_checks_are_reported(capsys, place, monkeypatch):
    no_checks_module(monkeypatch)
    code, env = run(capsys, "check", place.part())
    assert code == 0 and data_of(env)["checks"] == []


def test_check_model_verifies_a_model_against_the_drawing(capsys, place):
    part = place.part()
    place.settings()
    drawing = new(capsys, place, part=part)["files"][0]["path"]
    code, env = run(capsys, "check", drawing, "--model", part)
    mc = data_of(env)["model_check"]
    assert code == 0 and mc["verified"] and mc["reference_matches"] and mc["geometry_matches"] is None
    again = place.part("o03_boxA_again.SLDPRT", "copy.SLDPRT")
    code, env = run(capsys, "check", drawing, "--model", again)
    mc = data_of(env)["model_check"]
    assert code == 4 and not mc["verified"] and mc["geometry_matches"] and not mc["reference_matches"]
    assert mc["words"] == merge.GEOMETRY_UNCHANGED
    other = place.part("o07_boxB_h31.SLDPRT", "other.SLDPRT")
    code, env = run(capsys, "check", drawing, "--model", other)
    assert code == 4 and data_of(env)["model_check"]["geometry_matches"] is False
    code, env = run(capsys, "check", part, "--model", other)  # a part has no MODEL reference
    assert code == 2 and error_of(env)["detail"] == {"parameter": "model"}


def test_show(capsys, place):
    made = new(capsys, place)
    code, env = run(capsys, "show", made["files"][0]["path"])
    data = data_of(env)
    assert code == 0 and data["action"] == "show" and data["files"] == []
    assert data["drawing"]["id"] == made["drawing"]["id"]
    assert data["drawing"]["revisions"] == [
        {"rev": "A", "description": "INITIAL RELEASE", "zones": [], "date": None, "approved": None}
    ]
    assert cli.main(["drawing", "show", made["files"][0]["path"]]) == 0
    out = capsys.readouterr().out
    assert "  title: BRACKET, MOTOR MOUNT" in out and "  DRAWN: Ann Bee" in out


def test_settings(capsys, place):
    code, env = run(capsys, "settings")
    s = data_of(env)["settings"]
    assert code == 0 and not s["found"] and s["fallbacks"] == []
    assert s["first_use"] == ["standard.unit_for_unstated", "company.name", "people.people"]
    assert s["values"]["schema"] == S.SCHEMA and data_of(env)["drawing"] is None
    bad = dict(SETTINGS, standard={"units": "furlongs"})
    path = place.settings(bad)
    code, env = run(capsys, "settings")
    s = data_of(env)["settings"]
    assert code == 0 and s["found"] and s["path"] == path
    assert s["values"]["company"]["name"] == "Example Engineering Co."
    assert len(s["fallbacks"]) == 1 and s["fallbacks"][0].startswith("standard.units:")
    code, env = run(capsys, "settings", "--settings", str(place.root / "missing.json"))
    assert code == 1 and error_of(env)["code"] == "not_found"


# --------------------------------------------------------------------------- the four codes
def test_a_file_that_is_not_a_drawing_is_drawing_invalid(capsys, place):
    bad = place.out / "bad.ssdrw"
    bad.write_bytes(b'{"schema": "solidseas.drawing/9", "id": "x"}')
    for action in ("show", "check", "update"):
        code, env = run(capsys, action, str(bad))
        err = error_of(env)
        assert code == 1 and err["code"] == "drawing_invalid", action
        assert err["exception"] == "DrawingFileError" and err["detail"]["rule"] == "drawing_invalid"
    code, env = run(capsys, "show", str(place.part()))  # not a .ssdrw at all: a usage error
    assert code == 2 and error_of(env)["detail"] == {"parameter": "drawing"}


def test_a_drawing_file_over_its_bound_is_drawing_too_complex(capsys, place):
    big = place.out / "big.ssdrw"
    with open(big, "wb") as fh:
        fh.truncate(DrawingLimits().drawing_bytes + 1)
    code, env = run(capsys, "show", str(big))
    err = error_of(env)
    assert code == 1 and err["code"] == "drawing_too_complex" and err["detail"]["limit"] == "drawing_bytes"


def test_the_error_classes_keep_the_classes_raised_before():
    assert (
        issubclass(DrawingInvalidError, InvalidArgumentError)
        and DrawingInvalidError.code == "drawing_invalid"
    )
    assert issubclass(document.DrawingFileError, DrawingInvalidError)
    assert issubclass(DrawingTooComplexError, SldLimitError)
    assert DrawingTooComplexError.code == "drawing_too_complex"
    assert (
        issubclass(ModelNotFoundError, InvalidArgumentError) and ModelNotFoundError.code == "model_not_found"
    )
    assert issubclass(DrawingReleasedError, InvalidArgumentError)
    assert DrawingReleasedError.code == "drawing_released"
    for cls in (DrawingInvalidError, DrawingTooComplexError, ModelNotFoundError, DrawingReleasedError):
        assert getattr(solidseas, cls.__name__) is cls and cls.__name__ in solidseas.__all__
        assert model.ERROR_CODES[cls.code].cli_exit == cli.exit_code(cls.code)
    err = DrawingLimits(faces=10).exceeded("faces", "too many faces")
    assert type(err) is DrawingTooComplexError and err.detail == {"limit": "faces", "value": 10}
    assert model.error_info(err)["code"] == "drawing_too_complex"
    assert cli.exit_code("drawing_released") == cli.EXIT_REFUSED
    assert {cli.exit_code(c) for c in ("drawing_invalid", "drawing_too_complex", "model_not_found")} == {1}


def test_usage_errors_of_the_drawing_command(capsys, place):
    for argv in (["drawing"], ["drawing", "sign", "x.ssdrw"], ["drawing", "new", place.part()]):
        code = cli.main([*argv, "--json"])
        env = json.loads(capsys.readouterr().out)
        assert code == 2 and env["error"]["detail"]["usage"].startswith("usage: solidseas drawing"), argv
    code = cli.main(["drawing", "new", "--help", "--json"])
    env = json.loads(capsys.readouterr().out)
    assert code == 2 and "--confirm-threads" in env["error"]["detail"]["usage"]


# --------------------------------------------------------------------------- nothing outside tmp_path
def test_nothing_is_written_outside_the_temporary_folder(capsys, place, writes, tmp_path):
    part = place.part("o10_import_step_cut.SLDPRT", "plate.SLDPRT")
    place.settings()
    made = new(capsys, place, "--pdf", "--dxf", part=part)
    path = made["files"][0]["path"]
    exports = place.root / "exports"
    exports.mkdir()
    for argv in (
        ["export", path, "--out", str(exports)],
        ["check", path],
        ["check", part],
        ["show", path],
        ["settings"],
        ["update", path, "--dry-run"],
    ):
        code, _env = run(capsys, *argv)
        assert code == 0 or (argv == ["check", part] and only_title_gaps(code, _env)), argv
    shutil.copyfile(fixture_path("o10_import_step_cut.SLDPRT"), place.parts / "again.SLDPRT")
    code, _env = run(capsys, "update", path, "--model", str(place.parts / "again.SLDPRT"))
    assert code == 0
    assert writes, "the audit hook saw nothing"
    root = os.path.realpath(tmp_path)
    # Python's own bytecode cache, written when a module is first imported, is not the command's
    ours = [(e, p) for e, p in writes if "__pycache__" not in Path(p).parts]
    outside = [(e, p) for e, p in ours if os.path.commonpath([os.path.realpath(p), root]) != root]
    assert outside == []
    assert os.listdir(tmp_path / "cwd") == [] and sha(part) == sha(fixture_path("o10_import_step_cut.SLDPRT"))


def test_new_takes_its_detail_level_from_drawing_settings_unless_given(capsys, place):
    import copy

    values = copy.deepcopy(SETTINGS)
    values.setdefault("defaults", {})["detail"] = "simplified"
    path = place.settings(values)
    data = new(capsys, place, "--settings", path)
    assert data["drawing"]["options"]["detail"] == "simplified"
    data = new(capsys, place, "--settings", path, "--detail", "full")
    assert data["drawing"]["options"]["detail"] == "full"
