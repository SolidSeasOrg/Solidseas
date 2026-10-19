"""The OCCT oracle (opt-in, ``tests/README.md``): Open CASCADE, in a child process of its
own, reads the STEP files SolidSeas writes and the ones it reads, and measures them.

Marked ``occt`` and skipped unless ``SOLIDSEAS_OCCT_PYTHON`` names an interpreter where
``import OCP`` works; ``occt_support`` has the process model and the measurement
settings, ``test_occt_corpus.py`` the tiers over the private corpus.

* **The pin.** The ``cadquery-ocp`` wheel and OCCT are the versions every tolerance here
  was measured with (``occt_support.PINNED``).
* **STEP export, fixtures.** Every configuration of every fixture part that has bodies
  (o01 and o06's ``OracleAlt`` have none) is exported by SolidSeas and read by OCCT's
  basic reader: the read is done, every root transferred, no check fails, the only
  healing is "Missing seam-edge added" (a closed periodic face written whole), the
  solids are the ones SOLIDWORKS counts and the faces the ones SolidSeas wrote, every
  shell is closed, no edge is free and ``BRepCheck_Analyzer`` finds the shape valid. The Gauss-Kronrod
  volume and the adaptive area are within 1e-12 of SOLIDWORKS' own
  (``ground_truth.json``), the centre of mass within 1e-12 of the box's diagonal and
  the box within 1e-8 of it; OCCT's own fine mesh agrees with its integrators within
  1e-4. SOLIDWORKS' STEP of o02 passes the same checks, as a control.
* **STEP export, synthetic bodies.** Two Parasolid bodies no fixture has, built by code
  (``xt_bodies``) and exported through the same mapper: a cube with a cavity (a
  BREP_WITH_VOIDS) and a part of one sheet, which File > Export STEP sends as its sheet.
  OCCT reads the cavity's shell negative and both exactly; SolidSeas' reader of the file
  pairs the cavity with OCCT's void, of its sign. OCCT orients voids by their geometry,
  so that pairing, and ``test_step.py``'s check of the file itself, are what would see a
  cavity written inside out.
* **The reader.** SolidSeas' STEP reader against OCCT face by face, shell by shell and
  in total (``occt_support.reader_report``), tessellated at a 2 micrometre chord: on
  every synthetic file of ``occt_shapes.SHAPES``, on SolidSeas' STEP of every fixture
  and of the synthetic bodies, and on SOLIDWORKS' STEP of o02. Each face is within 3e-3
  of OCCT's area, each shell has OCCT's sign and volume, no edge of a solid is open or
  used twice the same way and no face is skipped.
* **As the viewer and 3D Print draw them.** The same files read at the viewer's chord
  and at 3D Print's: no face larger than its surface, no shell inside out, no edge open
  or folded and no face skipped (``occt_support.SOUNDNESS``), since what the
  user sees and prints is not the 2 micrometre tessellation.
* **The defects.** Each file of ``occt_shapes.DEFECTS`` reproduces a reader defect the
  oracle found in real files. OCCT reads each to its true volume, and so, since the
  reader's fixes for voids and for faces whose loops run against them, does the reader
  (the tests were expected failures, strict, until then).
* **OCCT's own integrators.** Its adaptive area is 1.2 % high on the side of an
  elliptic prism, a surface of linear extrusion. OCCT's own fine mesh is a second
  opinion on every face: a SolidSeas face agrees with OCCT when it agrees with either,
  and the faces where the two disagree are counted.
* **The corpus tiers' steps.** Their SolidSeas child exports a fixture as File > Export
  STEP does, a part of sheets as its sheets, and reads a STEP as the oracle does, at a
  chord or as drawn; their export step reads each file back and pairs its shells with
  OCCT's.
* **The harness.** A native crash in a child ends it at once, without a crash dump.
"""

import json
import math
import os
import sys
import time
from pathlib import Path

import pytest

import occt_shapes as S
import occt_support as O
import xt_bodies as X
from solidseas import open_document
from solidseas.formats.solidworks import parasolid as ps
from solidseas.step import step_bytes, step_model, step_transmit
from support import FIXTURES, fixture_path

pytestmark = [
    pytest.mark.occt,
    pytest.mark.skipif(O.occt_python() is None, reason=f"{O.OCCT_PYTHON_ENV} is not set"),
]

GT = json.loads((FIXTURES / "ground_truth.json").read_text(encoding="utf-8"))
STAMP = "2026-10-04T00:00:00Z"
NOTHING_TO_EXPORT = {("o01_empty.SLDPRT", "Default"), ("o06_boxA_props_mat_cfg.SLDPRT", "OracleAlt")}
EXPORTED = [
    (name, cfg)
    for name, doc in sorted(GT.items())
    if name.upper().endswith(".SLDPRT")
    for cfg in doc["api"]["configurations"]
    if (name, cfg) not in NOTHING_TO_EXPORT
]
CHORD_M = 2e-6  # SolidSeas' tessellation for the reader tier
READER_TOL = 3e-3  # per face, per shell and in total, against OCCT
SELF_TOL = 5e-3  # OCCT's adaptive area against its own mesh, per face
MESH_MM = 0.001  # OCCT's fine mesh, for its self-checks
EXACT = 1e-12
BOX = 1e-8
BAND = (0.01, 0.003, -0.5, 0.7)  # a torus band: R, r and the minor angles it spans (m, rad)
_R, _r, _v0, _v1 = BAND
BAND_AREA = 2 * math.pi * _r * (_R * (_v1 - _v0) + _r * (math.sin(_v1) - math.sin(_v0)))  # m^2


def _transmit(make, *args):
    xt = make(*args)
    xt.max_types = 231  # XtBuilder leaves it unset; a written transmit carries it
    return xt


# Parasolid bodies the fixtures lack, built by code (xt_bodies) and exported through the
# same mapper as a part's: label -> (transmit, body types asked for, solids, sheets, volume
# in mm^3, area in mm^2 (a sheet's for the sheet)).
SYNTHETIC = {
    "box with a cavity": (lambda: _transmit(X.void_box), ("solid",), 1, 0, 26000.0, 6 * 900.0 + 6 * 100.0),
    "torus band sheet": (
        lambda: _transmit(X.torus_band, *BAND),
        ("solid", "sheet"),
        0,
        1,
        None,
        BAND_AREA * 1e6,
    ),
}


@pytest.fixture(scope="module", autouse=True)
def _occt_ready():
    reason = O.skip_reason()
    if reason:
        pytest.skip(reason)


@pytest.fixture(scope="module")
def folder(tmp_path_factory):
    return tmp_path_factory.mktemp("occt")


_READ: dict = {}


def occt_read(data: bytes, folder: Path, key: str) -> dict:
    """OCCT's reading of ``data`` (faces and a fine mesh included), once per key."""
    if key not in _READ:
        path = folder / f"{len(_READ):03d}.step"
        path.write_bytes(data)
        _READ[key] = O.call({"op": "step", "path": str(path), "faces": True, "mesh_mm": MESH_MM})
    return _READ[key]


_FACES: dict = {}


def exported(name: str, configuration: str, folder: Path) -> tuple[bytes, dict]:
    """SolidSeas' STEP of a fixture, and OCCT's reading of it; :data:`_FACES` keeps how
    many faces SolidSeas says it wrote."""
    with open_document(fixture_path(name)) as doc:
        m = step_model(doc, configuration)
    data = step_bytes(m, time_stamp=STAMP)
    _FACES[(name, configuration)] = m.counts["faces"]
    return data, occt_read(data, folder, f"export:{name}:{configuration}")


def expect_sound(r: dict, *, solids: int, faces: int | None = None) -> None:
    """OCCT read the file cleanly into ``solids`` closed, valid solids."""
    where = f"(OCP {r['versions'].get('cadquery-ocp')})"
    assert r["read_status"] == "RetDone", where
    assert r["roots"] >= 1 and r["roots_transferred"] == r["roots"], where
    assert r["load_checks"] == {"warnings": {}, "fails": {}}, (r["load_checks"], where)
    healing = r["transfer_checks"]
    assert healing["fails"] == {} and set(healing["warnings"]) <= O.ALLOWED_HEALING, (healing, where)
    counts = r["counts"]
    assert (counts["solids"], counts["free_shells"], counts["free_faces"]) == (solids, 0, 0), (counts, where)
    if faces is not None:
        assert counts["faces"] == faces, (counts, where)
    assert r["open_solid_shells"] == 0 and r["solid_free_edges"] == 0 and r["solid_nonmanifold_edges"] == 0
    assert all(s["closed"] for s in r["shells"]) and all(v > 0 for v in r["solid_volumes"]), where
    assert r["valid"] is True, where


def expect_exact(r: dict, truth: dict) -> None:
    """OCCT's measures of the file against SOLIDWORKS' of the part (SI)."""
    box = truth["bounding_box_m"]
    diag = math.dist(box[:3], box[3:])
    got = {
        "volume": O.rel(r["volume"], truth["volume_m3"]),
        "area": O.rel(r["area"], truth["surface_area_m2"]),
        "centre": math.dist(r["centre_of_mass"], truth["center_of_mass_m"]) / diag,
        "box": O.box_deviation(r["box"], box),
        "mesh_volume": O.rel(r["mesh"]["volume"], r["volume"]),
        "mesh_area": O.rel(r["mesh"]["area"], r["area"]),
    }
    assert got["volume"] <= EXACT and got["area"] <= EXACT and got["centre"] <= EXACT, got
    assert got["box"] <= BOX, got
    assert r["mesh"]["complete"] and got["mesh_volume"] <= 1e-4 and got["mesh_area"] <= 1e-4, got


def reader_report(data: bytes, r: dict) -> dict:
    ours = O.solidseas_reading(data, chord_m=CHORD_M)
    return O.reader_report(r, ours, tol=READER_TOL, self_tol=SELF_TOL)


# --------------------------------------------------------------------------- the pin
def test_the_ocp_version_is_the_pinned_one():
    """Another OCCT may heal, integrate or check differently: move the pin, and the
    tolerances, only after the tiers pass with it."""
    got = O.versions()
    assert {k: got.get(k) for k in O.PINNED} == O.PINNED, got


# --------------------------------------------------------------------------- STEP export, fixtures
@pytest.mark.parametrize(("name", "configuration"), EXPORTED)
def test_occt_reads_solidseas_step_of_each_fixture_exactly(name, configuration, folder):
    """OCCT keeps every face SolidSeas wrote: at least as many as SOLIDWORKS counts, more
    where a closed periodic face is cut at its seams, as SOLIDWORKS' own STEP cuts it."""
    _data, r = exported(name, configuration, folder)
    truth = GT[name]["api"]["configurations"][configuration]
    faces = _FACES[(name, configuration)]
    assert faces >= sum(b["faces"] for b in truth["bodies"])
    expect_sound(r, solids=truth["solid_bodies"], faces=faces)
    expect_exact(r, truth)


def test_occt_reads_solidworks_own_step_of_o02_exactly(folder):
    data = fixture_path("o02_boxA.step").read_bytes()
    r = occt_read(data, folder, "solidworks:o02")
    expect_sound(r, solids=1, faces=6)
    assert r["transfer_checks"]["warnings"] == {}
    expect_exact(r, GT["o02_boxA.SLDPRT"]["api"]["configurations"]["Default"])


# --------------------------------------------------------------------------- STEP export, synthetic bodies
_SYNTH: dict = {}


def synthetic(label: str, folder: Path) -> tuple[bytes, dict, object]:
    """SolidSeas' STEP of a body of :data:`SYNTHETIC`, OCCT's reading of it and the model."""
    if label not in _SYNTH:
        make, types = SYNTHETIC[label][:2]
        m = step_transmit(make(), name="body", body_types=types)
        _SYNTH[label] = (step_bytes(m, time_stamp=STAMP), m)
    data, m = _SYNTH[label]
    return data, occt_read(data, folder, f"synthetic:{label}"), m


@pytest.mark.parametrize("label", list(SYNTHETIC))
def test_occt_reads_solidseas_step_of_each_synthetic_body_exactly(label, folder):
    """A cavity (BREP_WITH_VOIDS, which no fixture has) and a part of sheets (what File >
    Export STEP sends for a part of surfaces) read in OCCT as written: the cavity's shell
    negative, the sheet one free shell, their volume and area exact."""
    solids, sheets, volume_mm3, area_mm2 = SYNTHETIC[label][2:]
    _data, r, m = synthetic(label, folder)
    assert (m.counts["solids"], m.counts["sheets"]) == (solids, sheets)
    if solids:
        expect_sound(r, solids=solids, faces=m.counts["faces"])
        assert O.rel(r["volume"], volume_mm3 * 1e-9) <= EXACT and O.rel(r["area"], area_mm2 * 1e-6) <= EXACT
        assert sorted(s["volume"] * 1e9 for s in r["shells"]) == pytest.approx([-1000.0, 27000.0], rel=EXACT)
    else:
        assert r["read_status"] == "RetDone" and r["roots_transferred"] == r["roots"]
        healing = r["transfer_checks"]
        assert healing["fails"] == {} and set(healing["warnings"]) <= O.ALLOWED_HEALING, healing
        assert r["counts"] == {"solids": 0, "free_shells": 1, "free_faces": 0, "faces": m.counts["faces"]}
        assert r["valid"] is True
        assert O.rel(r["sheet_area"], area_mm2 * 1e-6) <= EXACT
    assert r["mesh"]["complete"]


@pytest.mark.parametrize("label", list(SYNTHETIC))
def test_the_reader_agrees_with_occt_on_solidseas_step_of_each_synthetic_body(label, folder):
    """SolidSeas' reader takes the cavity SolidSeas wrote as a void, its piece negative at
    the void's place, as OCCT does. OCCT orients a void by its geometry whatever the file
    says, so this is the export tier's check that the cavity is written facing into
    itself (``test_step.py`` checks the file itself, without either reader)."""
    data, r, _m = synthetic(label, folder)
    report = reader_report(data, r)
    assert O.reader_problems(report, READER_TOL) == [] and report["occt_unsure"] == 0
    if SYNTHETIC[label][2]:
        assert report["shells"]["pairs"] == 2 and report["shells"]["inverted"] == []


def test_the_fixture_tier_is_quick(folder):
    """The fixture tier stays a few seconds of OCCT per file (it ran in about 1.5 s
    each when it was written)."""
    for name, configuration in EXPORTED[:2]:
        _data, r = exported(name, configuration, folder)
        assert r["child_seconds"] < 30, r["seconds"]


# --------------------------------------------------------------------------- the reader
@pytest.mark.parametrize("label", list(S.SHAPES))
def test_the_reader_agrees_with_occt_on_each_synthetic_file(label, folder):
    data = S.SHAPES[label]()
    r = occt_read(data, folder, f"shape:{label}")
    assert r["read_status"] == "RetDone" and r["roots_transferred"] == r["roots"] and r["valid"] is True
    report = reader_report(data, r)
    assert O.reader_problems(report, READER_TOL) == []
    assert report["occt_unsure"] == (1 if label == "elliptic prism" else 0)


@pytest.mark.parametrize(("name", "configuration"), EXPORTED)
def test_the_reader_agrees_with_occt_on_solidseas_step_of_each_fixture(name, configuration, folder):
    data, r = exported(name, configuration, folder)
    report = reader_report(data, r)
    assert O.reader_problems(report, READER_TOL) == []
    assert report["occt_unsure"] == 0


def test_the_reader_agrees_with_occt_on_solidworks_own_step_of_o02(folder):
    data = fixture_path("o02_boxA.step").read_bytes()
    report = reader_report(data, occt_read(data, folder, "solidworks:o02"))
    assert O.reader_problems(report, READER_TOL) == [] and report["occt_unsure"] == 0


# --------------------------------------------------------------------------- as the viewer and 3D Print draw
def drawn_kinds(data: bytes, r: dict, drawn: str) -> list[str]:
    """The disagreements no chord excuses, in what the viewer draws or 3D Print
    tessellates (``occt_support.SOUNDNESS``)."""
    report = O.reader_report(r, O.solidseas_reading(data, drawn=drawn), tol=READER_TOL, self_tol=SELF_TOL)
    return [k for k in O.reader_kinds(report, READER_TOL) if k in O.SOUNDNESS]


@pytest.mark.parametrize("drawn", O.DRAWN)
@pytest.mark.parametrize("label", list(S.SHAPES))
def test_what_the_viewer_and_3d_print_draw_of_each_synthetic_file_is_sound(label, drawn, folder):
    """At their own chords (1e-3 of the box diagonal, and 2.5e-4 of it up to 10
    micrometres) no face is larger than its surface, no shell inside out, no edge of a
    solid open or folded and no face skipped."""
    data = S.SHAPES[label]()
    assert drawn_kinds(data, occt_read(data, folder, f"shape:{label}"), drawn) == []


@pytest.mark.parametrize("drawn", O.DRAWN)
@pytest.mark.parametrize(("name", "configuration"), EXPORTED)
def test_what_the_viewer_and_3d_print_draw_of_solidseas_step_of_each_fixture_is_sound(
    name, configuration, drawn, folder
):
    data, r = exported(name, configuration, folder)
    assert drawn_kinds(data, r, drawn) == []


@pytest.mark.parametrize("drawn", O.DRAWN)
@pytest.mark.parametrize("label", list(SYNTHETIC))
def test_what_the_viewer_and_3d_print_draw_of_solidseas_step_of_each_synthetic_body_is_sound(
    label, drawn, folder
):
    data, r, _m = synthetic(label, folder)
    assert drawn_kinds(data, r, drawn) == []


# --------------------------------------------------------------------------- the defects
@pytest.mark.parametrize("label", list(S.DEFECTS))
def test_occt_reads_each_defect_file_to_its_true_volume(label, folder):
    make, volume_mm3, _what = S.DEFECTS[label]
    r = occt_read(make(), folder, f"defect:{label}")
    expect_sound(r, solids=1)
    assert O.rel(r["volume"], volume_mm3 * 1e-9) <= 1e-9
    assert O.rel(r["mesh"]["volume"], r["volume"]) <= 1e-6


@pytest.mark.parametrize("label", list(S.DEFECTS))
def test_the_reader_agrees_with_occt_on_each_defect_file(label, folder):
    """Expected failures (strict) until the reader's fixes landed: void shells turned by
    their signed volume (bead 1) and faces whose loops all run against them read with
    their loops reversed (bead 3). The reader now agrees with OCCT on each."""
    make = S.DEFECTS[label][0]
    data = make()
    report = reader_report(data, occt_read(data, folder, f"defect:{label}"))
    assert O.reader_problems(report, READER_TOL) == []


# --------------------------------------------------------------------------- OCCT's integrators
def _ellipse_perimeter(a: float, b: float, n: int = 200_000) -> float:
    """By the midpoint rule on the arc length (error far below 1e-9 at this n)."""
    h = 2.0 * math.pi / n
    return sum(math.hypot(a * math.sin((k + 0.5) * h), b * math.cos((k + 0.5) * h)) for k in range(n)) * h


def test_occt_adaptive_area_fails_on_an_elliptic_extrusion_and_its_mesh_is_right(folder):
    """The elliptic prism of ``p21_writers`` (semi-axes 8 and 4 mm, 10 mm tall): OCCT's
    adaptive SurfaceProperties puts its side 1.2 % high even at eps 1e-9, while its
    mesh and SolidSeas agree with the exact area. The oracle counts the face as one
    where OCCT disagrees with itself, and SolidSeas' face agrees with the mesh."""
    data = S.SHAPES["elliptic prism"]()
    r = occt_read(data, folder, "shape:elliptic prism")
    (side,) = [f for f in r["faces"] if f["kind"] == "extrusion"]
    exact = _ellipse_perimeter(8.0, 4.0) * 10.0 * 1e-6
    assert O.rel(side["area"], exact) > 1e-2
    assert O.rel(side["mesh_area"], exact) < 1e-4
    report = reader_report(data, r)
    assert report["occt_unsure"] == 1 and O.reader_problems(report, READER_TOL) == []
    assert O.rel(r["volume"], math.pi * 8 * 4 * 10 * 1e-9) <= 1e-12  # the Gauss-Kronrod volume is right


# --------------------------------------------------------------------------- the corpus pipeline on fixtures
def test_the_corpus_children_export_and_read_a_fixture_as_the_tests_do(tmp_path):
    """The corpus tiers' SolidSeas child (``occt_solidseas_child.py``) exports o11 as
    File > Export STEP does and reads a STEP as ``solidseas_reading`` does, in a job of
    its own: the same numbers as in this process."""
    here = Path(__file__).parent
    child = here / "occt_solidseas_child.py"
    sys_path = [str(here.parent / "src"), str(here)]
    out = tmp_path / "r0.step"
    got = O.run_child(
        {"op": "export", "path": str(fixture_path("o11_curved.SLDPRT")), "out": str(out), "name": "r0",
         "sys_path": sys_path},
        python=sys.executable, script=child, timeout_s=300, memory_mb=2048,
    )  # fmt: skip
    assert got.ok and got.reply["status"] == "written" and got.reply["solids"] == 1, got.describe()
    r = O.call({"op": "step", "path": str(out)})
    truth = GT["o11_curved.SLDPRT"]["api"]["configurations"]["Default"]
    assert O.rel(r["volume"], truth["volume_m3"]) <= EXACT
    data = out.read_bytes()
    assert b"'r0'" in data and b"o11" not in data  # the product is named as asked, not after the part
    got = O.run_child(
        {"op": "read", "path": str(out), "chord_m": CHORD_M, "max_seconds": 300, "sys_path": sys_path},
        python=sys.executable, script=child, timeout_s=300, memory_mb=2048,
    )  # fmt: skip
    assert got.ok, got.describe()
    here_ = O.solidseas_reading(data, chord_m=CHORD_M)
    assert got.reply["volume"] == pytest.approx(here_["volume"], rel=1e-12)
    assert [f[0] for f in got.reply["faces"]] == pytest.approx([f.area for f in here_["faces"]], rel=1e-12)
    for drawn in O.DRAWN:
        got = O.run_child(
            {"op": "read", "path": str(out), "drawn": drawn, "max_seconds": 300, "sys_path": sys_path},
            python=sys.executable, script=child, timeout_s=300, memory_mb=2048,
        )  # fmt: skip
        assert got.ok and got.reply["drawn"] == drawn, got.describe()
        here_ = O.solidseas_reading(data, drawn=drawn)
        assert got.reply["chord_m"] == here_["chord_m"]
        assert got.reply["volume"] == pytest.approx(here_["volume"], rel=1e-12)


def _x_t(xt, path: Path) -> Path:
    """``xt`` as a Parasolid text transmit file at ``path``."""
    text = ps.text_header(xt, fmt="text", key="k", file="k.x_t") + ps.write_text(xt) + "\n"
    path.write_bytes(text.encode("latin-1"))
    return path


def _child_export(src: Path, out: Path) -> O.ChildResult:
    here = Path(__file__).parent
    return O.run_child(
        {"op": "export", "path": str(src), "out": str(out), "name": "r1",
         "sys_path": [str(here.parent / "src"), str(here)]},
        python=sys.executable, script=here / "occt_solidseas_child.py", timeout_s=300, memory_mb=2048,
    )  # fmt: skip


def test_the_corpus_child_sends_a_part_of_sheets_as_file_export_step_does(tmp_path):
    """A part with no solid, only a sheet: the STEP export refuses it unless sheets are
    asked for (rule ``sheets_not_asked``), and File > Export STEP then sends the sheet, so
    the corpus tier's child does too. OCCT reads one free shell of the band's true area."""
    got = _child_export(_x_t(_transmit(X.torus_band, *BAND), tmp_path / "band.x_t"), tmp_path / "r1.step")
    assert got.ok and got.reply["status"] == "written", got.describe()
    assert (got.reply["sheets_fallback"], got.reply["solids"], got.reply["sheets"]) == (True, 0, 1)
    r = O.call({"op": "step", "path": str(tmp_path / "r1.step")})
    assert r["counts"]["free_shells"] == 1 and r["valid"] is True
    assert O.rel(r["sheet_area"], BAND_AREA) <= EXACT
    got = _child_export(_x_t(_transmit(X.void_box), tmp_path / "void.x_t"), tmp_path / "r2.step")
    assert got.ok and (got.reply["sheets_fallback"], got.reply["solids"]) == (False, 1), got.describe()


def test_the_corpus_export_tier_reads_each_file_back_and_compares_sheets(tmp_path):
    """The corpus export tier's own steps (``test_occt_corpus.export_one`` and
    ``_against_truth``) on synthetic parts: a cavity is read back by SolidSeas, its shell
    paired with OCCT's void and of its sign; a part of sheets is sent as its sheets and
    compared with SOLIDWORKS' sheet area and box of all bodies."""
    import test_occt_corpus as C

    out = tmp_path / "out"
    out.mkdir()
    rec = C.export_one((1, str(_x_t(_transmit(X.void_box), tmp_path / "void.x_t")), str(out), None))
    assert (rec["export"], rec["occt"], rec["changed"]) == ("written", "ok", False)
    assert rec["reread"] == {"voids": 1, "shells": [2, 2], "pairs": 2, "inverted": 0}
    assert not C._unsound(rec) and os.listdir(out) == []
    rec = C.export_one((2, str(_x_t(_transmit(X.torus_band, *BAND), tmp_path / "band.x_t")), str(out), None))
    assert rec["export"] == "written" and rec["sheets_fallback"] and "reread" not in rec
    assert not C._unsound(rec) and rec["r"]["valid"] is True
    R, r, v0, v1 = BAND
    box = [-(R + r), -(R + r), r * math.sin(v0), R + r, R + r, r * math.sin(v1)]
    truth = {"native_active": {"sheet_bodies": 1, "hidden_sheet_bodies": 0, "sheet_area_m2": BAND_AREA,
                               "bbox_all_bodies_m": box}}  # fmt: skip
    got = C._against_truth(rec, truth)
    assert got["sheet_area"] <= EXACT and got["box_all"] <= 1e-6, got


# --------------------------------------------------------------------------- the harness
@pytest.mark.skipif(sys.platform != "win32", reason="Job Objects and Windows Error Reporting")
def test_a_native_crash_ends_the_child_without_a_crash_dump(tmp_path):
    """An access violation in native code, as OCCT gives on damaged files, in a child that
    sets no error mode of its own: it inherits a quiet one from ``run_child``, so it ends
    at once and Windows Error Reporting writes no dump to the LocalDumps folder (on for
    every program on the development PC). The child clears a list's type pointer and
    lets the interpreter follow it (ctypes would turn a fault inside one of its own calls
    into OSError)."""
    script = tmp_path / "crash.py"
    script.write_text(
        "import ctypes\n"
        "x = [1, 2, 3]\n"
        "ctypes.memset(id(x) + ctypes.sizeof(ctypes.c_ssize_t), 0, ctypes.sizeof(ctypes.c_void_p))\n"
        "len(x)\n",
        encoding="utf-8",
    )
    dumps = Path(os.environ.get("LOCALAPPDATA", str(tmp_path))) / "CrashDumps"

    def listing() -> set[str]:
        try:
            return set(os.listdir(dumps))
        except OSError:
            return set()

    before = listing()
    got = O.run_child({"op": "crash"}, python=sys.executable, script=script, timeout_s=60, memory_mb=512)
    assert (got.status, got.crash) == ("crash", "access_violation"), got.describe()
    deadline = time.monotonic() + 5.0  # Windows Error Reporting writes a dump from another process
    while time.monotonic() < deadline:
        assert not listing() - before, "a crash dump was written"
        time.sleep(0.5)
