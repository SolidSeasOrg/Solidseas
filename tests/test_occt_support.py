"""The OCCT oracle's harness (``occt_support``), without OCCT: these run on every machine.

* **The process model.** ``run_child`` with stand-in children run by this interpreter:
  the request goes in on standard input, never the command line; one answer line comes
  back and the rest of the output is dropped; a timeout kills the whole child (a venv's
  interpreter as well as its launcher); an exit, a Python exception, running out of
  memory under the cap, no answer and a broken answer are each reported as such, an
  exception by its class name only. On Windows the child runs inside the Job Object,
  below normal priority, with the quiet error mode.
* **The comparisons**, on numbers that reproduce each defect the oracle found in real
  files: a face larger than its whole surface (folded triangles), a void inside out, a
  face dropped, an open or folded mesh, OCCT's adaptive area failing its self-check,
  and two faces sharing a centroid. Shells pair by place, so that a piece OCCT does not
  have does not pair the rest with unrelated shells; a face may fall short by its
  polygons' own error on a curved surface, never exceed.
* **What is drawn.** The oracle's readings as the viewer draws a STEP and as 3D Print
  tessellates it are those very meshes.
* **The boundaries.** The library never imports OCP, the OCCT child imports nothing of
  SolidSeas or pytest, and without ``SOLIDSEAS_OCCT_PYTHON`` the oracle says why it is
  skipped.
"""

import ast
import json
import math
import os
import sys
import time
from array import array
from pathlib import Path

import pytest

import occt_support as O
from support import within

HERE = Path(__file__).parent
SRC = HERE.parent / "src"


def stand_in(tmp_path: Path, body: str) -> Path:
    """A child script: reads the request, then runs ``body`` with ``req`` and ``answer``."""
    script = tmp_path / "child.py"
    script.write_text(
        "import json, os, sys\n"
        "req = json.loads(sys.stdin.readline())\n"
        "def answer(obj, raw=None):\n"
        f"    line = raw if raw is not None else {O.MARK!r} + json.dumps(obj)\n"
        "    os.write(1, (line + '\\n').encode())\n" + body + "\n",
        encoding="utf-8",
    )
    return script


def run(tmp_path, body, request=None, **kw):
    kw.setdefault("timeout_s", 60.0)
    kw.setdefault("memory_mb", 512)
    return O.run_child(
        request or {"op": "test"}, python=sys.executable, script=stand_in(tmp_path, body), **kw
    )


# --------------------------------------------------------------------------- the process model
def test_the_request_goes_in_on_standard_input_and_one_answer_line_comes_back(tmp_path):
    got = run(
        tmp_path,
        "print('noise before'); sys.stdout.flush()\n"
        "answer({'echo': req, 'argv': sys.argv[1:], 'isolated': sys.flags.isolated})\n"
        "print('noise after')",
        request={"op": "echo", "path": "a private place"},
    )
    assert got.ok and got.status == "ok" and got.returncode == 0, got.describe()
    assert got.reply["echo"] == {"op": "echo", "path": "a private place"}
    assert "a private place" not in json.dumps(got.reply["argv"]) and got.reply["isolated"] == 1


@pytest.mark.skipif(sys.platform != "win32", reason="the Job Object is Windows'")
def test_the_child_runs_in_its_job_below_normal_with_the_quiet_error_mode(tmp_path):
    got = run(
        tmp_path,
        "import ctypes\n"
        "k = ctypes.WinDLL('kernel32')\n"
        "k.GetCurrentProcess.restype = ctypes.c_void_p\n"
        "k.IsProcessInJob.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int))\n"
        "k.GetPriorityClass.argtypes = (ctypes.c_void_p,)\n"
        "b = ctypes.c_int(0)\n"
        "k.IsProcessInJob(k.GetCurrentProcess(), None, ctypes.byref(b))\n"
        "answer({'job': b.value, 'priority': k.GetPriorityClass(k.GetCurrentProcess()),"
        " 'mode': k.GetErrorMode()})",
    )
    assert got.ok, got.describe()
    assert got.reply == {"job": 1, "priority": 0x4000, "mode": 0x8003}
    assert got.peak_mb is not None and got.peak_mb > 0


@pytest.mark.skipif(sys.platform == "win32", reason="the POSIX limits")
def test_the_child_runs_niced_without_core_files_under_its_memory_cap(tmp_path):  # pragma: no cover
    got = run(
        tmp_path,
        "import resource\n"
        "answer({'nice': os.nice(0), 'core': resource.getrlimit(resource.RLIMIT_CORE)[0],"
        " 'as': resource.getrlimit(resource.RLIMIT_AS)[0]})",
        memory_mb=1024,
    )
    assert got.ok, got.describe()
    assert got.reply["nice"] >= 10 and got.reply["core"] == 0
    assert got.reply["as"] in (1024 << 20, -1)  # -1: a system that refuses RLIMIT_AS


def _alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32))
        k32.CloseHandle.argtypes = (ctypes.c_void_p,)
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_uint32(0)
            return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_a_child_past_its_timeout_is_killed_whole(tmp_path):
    """The interpreter that runs the script (a venv's launcher starts it as a second
    process) is gone when the call returns, not only the process this one started."""
    pid_file = tmp_path / "pid"
    got = run(
        tmp_path,
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\nimport time\ntime.sleep(120)",
        timeout_s=within(3.0),  # time for a slow interpreter to start and write its pid first
    )
    assert got.status == "timeout" and got.reply is None, got.describe()
    assert got.seconds < 60
    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 10
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not _alive(pid)


def test_an_exit_without_an_answer_is_a_crash_with_its_code(tmp_path):
    got = run(tmp_path, "os._exit(3)")
    assert (got.status, got.returncode, got.crash) == ("crash", 3, "0x3"), got.describe()


def test_an_exception_is_reported_by_its_class_name_only(tmp_path):
    got = run(tmp_path, "raise ValueError('C:/a private folder/part.step')")
    assert (got.status, got.exception) == ("error", "ValueError"), got.describe()
    assert "private" not in got.describe() and "private" not in json.dumps(got.notes)


def test_an_error_answer_is_an_error(tmp_path):
    got = run(tmp_path, "answer({'error': 'StepReadError'})")
    assert (got.status, got.exception) == ("error", "StepReadError")


def test_running_out_of_memory_under_the_cap_is_memory(tmp_path):
    got = run(tmp_path, "data = bytearray(2048 << 20)\nanswer({'n': len(data)})", memory_mb=512)
    assert got.status == "memory", got.describe()


def test_an_end_without_an_answer_is_no_result(tmp_path):
    got = run(tmp_path, "print('just text')")
    assert got.status == "no_result" and got.reply is None


@pytest.mark.parametrize(
    ("body", "why"),
    [
        ("answer({'a': 1}); answer({'b': 2})", "more than one answer line"),
        ("answer(None, raw=MARK + '{\"v\": NaN}')", "the answer is not strict JSON"),
        ("answer(None, raw=MARK + '[1, 2]')", "the answer is not an object"),
        ("answer(None, raw=MARK + '{\"v\": 1')", "the answer is not strict JSON"),
    ],
)
def test_a_broken_answer_is_refused(tmp_path, body, why):
    got = run(tmp_path, f"MARK = {O.MARK!r}\n{body}")
    assert got.status == "bad_reply" and got.reply is None and got.notes == [why], got.describe()


def test_an_answer_over_the_cap_is_refused(tmp_path):
    got = run(tmp_path, "answer({'text': 'x' * 100000})", max_reply_bytes=50_000)
    assert got.status == "bad_reply" and got.notes == ["the output is larger than max_reply_bytes"]


def test_parse_reply_reads_only_the_answer_line():
    out = b"OCCT says: reading a file\n" + O.MARK.encode() + b'{"volume": 1.5}\nmore\n'
    assert O.parse_reply(out) == ({"volume": 1.5}, None)
    assert O.parse_reply(b"nothing\n") == (None, "no answer line")


# --------------------------------------------------------------------------- comparisons
def face(area, centroid, kind=None, surface=None, mesh=None):
    return O.FaceMeasure(area, centroid, kind, surface, mesh)


BOX = [face(200e-6, (0.005, 0.01, 0.0), "plane"), face(600e-6, (0.0, 0.01, 0.015), "plane")]


def test_matching_faces_agree():
    got = O.match_faces(BOX, [face(200.1e-6, (0.005, 0.01, 0.0)), face(600e-6, (0.0, 0.0100001, 0.015))],
                        tol=1e-3, near=0.002)  # fmt: skip
    assert got == {"pairs": 2, "wrong": [], "folded": [], "missing": [], "extra": []}


def test_a_face_larger_than_its_whole_surface_is_folded():
    """step#903 and step#1175: a face whose triangles cover more than the whole surface
    it lies on must have triangles folded over each other."""
    occt = [face(932.1e-6, (0.0, 0.0, 0.01), "sphere", 1017.9e-6), face(300e-6, (0.0, 0.0, 0.0), "plane")]
    ours = [face(1067.8e-6, (0.0, 0.0, 0.0105)), face(300e-6, (0.0, 0.0, 0.0))]
    got = O.match_faces(occt, ours, tol=1e-2, near=0.005)
    assert [f["kind"] for f in got["folded"]] == ["sphere"] and [f["kind"] for f in got["wrong"]] == [
        "sphere"
    ]
    assert got["wrong"][0]["rel"] == pytest.approx(1067.8 / 932.1 - 1)


def test_a_dropped_face_is_missing_and_a_stray_one_extra():
    got = O.match_faces(
        BOX, [face(200e-6, (0.005, 0.01, 0.0)), face(50e-6, (1.0, 1.0, 1.0))], tol=1e-3, near=0.002
    )
    assert got["missing"] == [{"face": 1, "kind": "plane", "occt": 600e-6}]
    assert got["extra"] == [{"area": 50e-6}]


def test_faces_sharing_a_centroid_pair_by_size():
    """A hollow cylinder's outer and inner walls have the same centroid on its axis."""
    occt = [face(603e-6, (0, 0, 0.006), "cylinder"), face(377e-6, (0, 0, 0.006), "cylinder")]
    ours = [face(376.9e-6, (0, 0, 0.006)), face(602.8e-6, (0, 0, 0.006))]
    got = O.match_faces(occt, ours, tol=1e-3, near=0.002)
    assert got["wrong"] == [] and got["pairs"] == 2


def shell(volume, centroid=None):
    return {"volume": volume, "centroid": centroid}


def test_a_void_inside_out_is_inverted():
    """step#38: the 7-face void shell's signed volume is OCCT's with the sign turned."""
    occt = [shell(1.13e-3, (0.05, 0.05, 0.02)), shell(-124870.11e-9, (0.05, 0.05, 0.03))]
    ours = [shell(1.13e-3, (0.05, 0.05, 0.02)), shell(124870.11e-9, (0.05, 0.05, 0.03))]
    for near in (None, 0.01):
        got = O.match_shells(occt, ours, tol=1e-3, near=near)
        assert got["inverted"] == [{"shell": 1, "occt": -124870.11e-9, "ours": 124870.11e-9}]
        assert got["wrong"] == [] and got["pairs"] == 2 and got["unpaired"] == (0, 0)
    got = O.match_shells([shell(6e-6)], [shell(4e-6)], tol=1e-3)
    assert got["wrong"] and not got["inverted"]
    assert O.match_shells([shell(6e-6)], [], tol=1e-3)["shells"] == (1, 0)


def test_shells_pair_by_place_when_the_counts_differ():
    """step#1098 and step#885: with pieces OCCT does not have, pairing by size alone pairs
    every shell after the first extra piece with an unrelated one, and reports a solid
    inside out where there is none. By place, each shell finds its own piece; without
    places, only the counts are reported."""
    occt = [
        shell(1000e-9, (0.0, 0.0, 0.0)),
        shell(-127.5e-9, (0.02, 0.0, 0.0)),  # a void
        shell(28.179e-9, (0.0, 0.03, 0.0)),
    ]
    ours = [
        shell(1000e-9, (0.0, 0.0, 0.0)),
        shell(200e-9, (0.0, 0.0, 0.04)),  # a piece OCCT has no shell for
        shell(-127.5e-9, (0.02, 0.0, 0.0)),
        shell(28.179e-9, (0.0, 0.03, 0.0)),
        shell(112.5e-9, (0.03, 0.03, 0.03)),  # and another
    ]
    blind = O.match_shells([shell(s["volume"]) for s in occt], [shell(s["volume"]) for s in ours], tol=1e-3)
    assert blind["pairs"] == 0 and blind["inverted"] == [] and blind["shells"] == (3, 5)
    got = O.match_shells(occt, ours, tol=1e-3, near=0.01)
    assert got["inverted"] == [] and got["wrong"] == []
    assert (got["pairs"], got["unpaired"]) == (3, (0, 2))
    report = {
        "faces": {"folded": [], "wrong": [], "missing": [], "extra": []},
        "shells": got,
        "volume_rel": 0.0,
        "area_rel": 0.0,
        "open_edges": 0,
        "doubled_edges": 0,
        "skipped": {},
    }
    assert O.reader_problems(report, 1e-3) == ["5 closed pieces against 3 shells"]
    assert O.reader_kinds(report, 1e-3) == ["shells_off"]
    # a void turned round still pairs with its own piece, and is caught
    ours[2] = shell(127.5e-9, (0.02, 0.0, 0.0))
    got = O.match_shells(occt, ours, tol=1e-3, near=0.01)
    assert got["inverted"] == [{"shell": 1, "occt": -127.5e-9, "ours": 127.5e-9}]
    assert O.reader_kinds(dict(report, shells=got), 1e-3) == ["shells_inverted", "shells_off"]


def _cube(flip: int | None = None, drop: int | None = None):
    pts = [(x, y, z) for x in (0.0, 1.0) for y in (0.0, 1.0) for z in (0.0, 1.0)]
    quads = [(0, 2, 6, 4), (1, 5, 7, 3), (0, 4, 5, 1), (2, 3, 7, 6), (0, 1, 3, 2), (4, 6, 7, 5)]
    tris = []
    for a, b, c, d in quads:
        tris += [(a, b, c), (a, c, d)]
    if flip is not None:
        a, b, c = tris[flip]
        tris[flip] = (a, c, b)
    if drop is not None:
        del tris[drop]
    return array("d", [v for p in pts for v in p]), array("I", [i for t in tris for i in t])


def test_mesh_pieces_measure_a_closed_cube():
    (piece,) = O.mesh_pieces(*_cube())
    assert piece["volume"] == pytest.approx(1.0) and piece["area"] == pytest.approx(6.0)
    assert piece["open"] == 0 and piece["doubled"] == 0
    assert piece["centroid"] == pytest.approx((0.5, 0.5, 0.5))


def test_a_pieces_centroid_is_its_volumes_when_closed_and_its_areas_when_open():
    """A void's volume and moment are both negative, so its centroid is where it is; an
    open piece's volume depends on the origin, so its centroid is its area's."""
    pos, tris = _cube()
    inner = array("d", [0.1 + 0.3 * v for v in pos])
    turned = array("I", [tris[k + j] + 8 for k in range(0, len(tris), 3) for j in (0, 2, 1)])
    outer, void = O.mesh_pieces(pos + inner, tris + turned)
    assert void["volume"] == pytest.approx(-0.027) and void["centroid"] == pytest.approx((0.25, 0.25, 0.25))
    assert outer["centroid"] == pytest.approx((0.5, 0.5, 0.5))
    (lid,) = O.mesh_pieces(*_cube(drop=0))  # the bottom loses its triangle (0, 0, 0), (0, 1, 0), (1, 1, 0)
    assert lid["open"] == 3
    gone = (1 / 3, 2 / 3, 0.0)
    assert lid["centroid"] == pytest.approx([(6 * 0.5 - 0.5 * g) / 5.5 for g in gone])


def test_mesh_pieces_find_open_and_folded_edges():
    """A missing triangle leaves three edges used one way only; a triangle turned round
    uses its edges the same way as its neighbours do (step#903: 30 such edges)."""
    (piece,) = O.mesh_pieces(*_cube(drop=0))
    assert piece["open"] == 3 and piece["doubled"] == 0
    (piece,) = O.mesh_pieces(*_cube(flip=0))
    assert piece["doubled"] == 3 and piece["open"] == 3


def test_mesh_pieces_separate_shells():
    pos, tris = _cube()
    inner = array("d", [0.25 + 0.5 * v for v in pos])
    turned = array("I", [tris[k + j] + 8 for k in range(0, len(tris), 3) for j in (0, 2, 1)])
    pieces = O.mesh_pieces(pos + inner, tris + turned)
    assert sorted(round(p["volume"], 9) for p in pieces) == [-0.125, 1.0]


def test_a_face_agrees_with_occt_when_it_agrees_with_either_of_occts_measures():
    """The elliptic prism's side: OCCT's adaptive area is 1.2 % high and its mesh right;
    beside a small fillet a mesh set by the part's size is the one that is off. A face
    off from both is wrong."""
    occt = [face(392.3e-6, (0, 0, 0.005), "extrusion", None, 387.5e-6)]
    assert O.match_faces(occt, [face(387.53e-6, (0, 0, 0.005))], tol=3e-3, near=0.01)["wrong"] == []
    assert O.match_faces(occt, [face(392.2e-6, (0, 0, 0.005))], tol=3e-3, near=0.01)["wrong"] == []
    (w,) = O.match_faces(occt, [face(420e-6, (0, 0, 0.005))], tol=3e-3, near=0.01)["wrong"]
    assert w["rel"] == pytest.approx(420 / 392.3 - 1)


def test_a_thin_fillet_is_allowed_its_chord_error_and_a_wrong_one_is_not():
    """step#569: a torus fillet of minor radius about 0.05 mm, tessellated at a 1.6
    micrometre chord, comes out 1 % short, as a polygon does; step#1146: torus faces
    16 % larger than OCCT's, their centroids off, are wrong whatever the chord."""
    occt = [face(0.04499e-6, (0.0, 0.0, 0.0), "torus", None, 0.04495e-6)]
    occt[0].min_radius = 0.05e-3
    short = [face(0.04448e-6, (0.0, 0.0, 0.0))]
    assert O.match_faces(occt, short, tol=1e-2, near=1e-3)["wrong"]
    assert O.match_faces(occt, short, tol=1e-2, near=1e-3, chord=1.6e-6)["wrong"] == []
    large = [face(0.0523e-6, (0.0, 0.0, 0.0002))]
    assert O.match_faces(occt, large, tol=1e-2, near=1e-3, chord=1.6e-6)["wrong"]


def _polygon_shortfall(chord: float, radius: float) -> float:
    """How far short of an arc of ``radius`` the chords of sagitta ``chord`` fall."""
    half = math.acos(1.0 - chord / radius)
    return 1.0 - math.sin(half) / half


@pytest.mark.parametrize(("kind", "curved"), [("cylinder", 1), ("sphere", 2), ("torus", 2)])
def test_the_chord_allowance_is_one_sided_and_a_polygons_own(kind, curved):
    """A 0.05 mm fillet of a 200 mm part, tessellated at the corpus tier's 4 micrometres:
    its polygons fall 2.7 % short of each arc, and a face up to that much short (twice on
    a surface curved both ways) agrees. A polygon is never larger than its surface, so a
    face 9 % too large is wrong, as is one 10 % short."""
    chord, radius = 4e-6, 0.05e-3
    o = face(1e-6, (0.0, 0.0, 0.0), kind)
    o.min_radius = radius

    def wrong(area: float) -> bool:
        got = O.match_faces([o], [face(area, (0.0, 0.0, 0.0))], tol=1e-2, near=1e-3, chord=chord)
        return bool(got["wrong"])

    short = curved * _polygon_shortfall(chord, radius)
    assert short == pytest.approx(curved * chord / (3 * radius), rel=0.05)
    assert not wrong(1e-6 * (1.0 - short))
    assert not wrong(1e-6 * (1.0 + 0.009))
    assert wrong(1e-6 * 1.09)
    assert wrong(1e-6 * 0.90)
    # with no chord given, or on a plane, only the tolerance
    assert O.match_faces([o], [face(1e-6 * (1.0 - short), (0.0, 0.0, 0.0))], tol=1e-2, near=1e-3)["wrong"]
    plane = face(1e-6, (0.0, 0.0, 0.0), "plane")
    plane.min_radius = radius
    got = O.match_faces([plane], [face(1e-6 * 0.98, (0.0, 0.0, 0.0))], tol=1e-2, near=1e-3, chord=chord)
    assert got["wrong"]


def test_the_report_counts_where_occt_disagrees_with_itself_and_lists_disagreements():
    occt = {
        "box": [0, 0, 0, 0.01, 0.01, 0.01],
        "faces": [
            {"kind": "extrusion", "area": 392.3e-6, "mesh_area": 387.5e-6, "centroid": [0, 0, 0.005]},
            {"kind": "plane", "area": 100.5e-6, "mesh_area": 100.5e-6, "centroid": [0, 0, 0]},
        ],
        "shells": [{"volume": 1.0053e-6}],
        "volume": 1.0053e-6,
        "mesh": {"complete": True, "volume": 1.0051e-6},
    }
    ours = {
        "faces": [face(387.53e-6, (0, 0, 0.005)), face(100.5e-6, (0, 0, 0))],
        "pieces": [{"volume": 1.0052e-6, "area": 488.03e-6, "open": 0, "doubled": 0, "solid": True}],
        "volume": 1.0052e-6,
        "area": 488.03e-6,
        "skipped": {},
    }
    report = O.reader_report(occt, ours, tol=3e-3, self_tol=5e-3)
    assert report["occt_unsure"] == 1 and O.reader_problems(report, 3e-3) == []
    bad = dict(ours, pieces=[dict(ours["pieces"][0], open=4)], skipped={"seam_configuration": 1})
    problems = O.reader_problems(O.reader_report(occt, bad, tol=3e-3), 3e-3)
    assert problems == ["4 open edges in solids", "faces skipped: {'seam_configuration': 1}"]


def test_the_drawn_readings_are_what_the_viewer_and_3d_print_make():
    """``solidseas_reading(drawn=...)`` measures the scene the viewer draws (the reader's
    own defaults) and the mesh 3D Print makes (``export.print_model``, welded), and its
    faces are those very tessellations: on SolidSeas' STEP of o11, whose cylinders and
    torus the chord changes, the same volume and area to the last bits."""
    from solidseas import export, open_document
    from solidseas.formats import open_model
    from solidseas.step import step_bytes, step_model
    from support import fixture_path

    with open_document(fixture_path("o11_curved.SLDPRT")) as doc:
        data = step_bytes(step_model(doc), time_stamp="2026-10-05T00:00:00Z")
    with open_model(data) as doc:
        viewer = [o.measures() for o in doc.scene(prefer="display").objects]
        printed = [export.mesh_measures(o.positions, o.triangles) for o in export.print_model(doc).objects]
    for drawn, made in (("viewer", viewer), ("print", printed)):
        got = O.solidseas_reading(data, drawn=drawn)
        assert got["volume"] == pytest.approx(sum(m["volume_m3"] for m in made), rel=1e-12, abs=0)
        assert got["area"] == pytest.approx(sum(m["area_m2"] for m in made), rel=1e-12, abs=0)
        assert sum(f.area for f in got["faces"]) == pytest.approx(got["area"], rel=1e-12, abs=0)
        assert got["faces_unmeasured"] == 0 and got["closed"] is True
    v, p = (O.solidseas_reading(data, drawn=d) for d in O.DRAWN)
    assert p["chord_m"] < v["chord_m"] and p["chord_m"] <= export.MAX_CHORD_M
    fine = O.solidseas_reading(data, chord_m=1e-6)
    assert abs(fine["volume"] - v["volume"]) > 1e-6 * fine["volume"]  # the chords differ, and it shows
    with pytest.raises(ValueError):
        O.solidseas_reading(data, chord_m=1e-6, drawn="viewer")


def test_rel_and_box_deviation():
    assert O.rel(1.0, 1.0) == 0.0 and O.rel(None, 1.0) == math.inf and O.rel(1.0, 0.0) == math.inf
    assert O.rel(0.0, 0.0) == 0.0
    assert O.box_deviation([0, 0, 0, 3, 4, 0], [0, 0, 0, 3, 4, 0.0]) == 0.0
    assert O.box_deviation([0, 0, 0, 3, 4, 0.05], [0, 0, 0, 3, 4, 0]) == pytest.approx(0.01)


# --------------------------------------------------------------------------- boundaries
def _imports(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_the_library_never_imports_ocp():
    # The OCCT backend's helper is the one module that does: it runs as a program of its own,
    # in the extension's package or an interpreter of its own, and nothing imports it
    # (tests/test_occt_backend.py checks both).
    offenders = [p.relative_to(SRC).as_posix() for p in SRC.rglob("*.py") if "OCP" in _imports(p)]
    assert offenders == ["solidseas_app/extensions/occt_helper.py"]
    assert "OCP" not in _imports(HERE / "occt_support.py")


def test_the_occt_child_imports_the_standard_library_and_ocp_only():
    names = _imports(HERE / "occt_child.py")
    assert "OCP" in names and not names & {"solidseas", "solidseas_app", "pytest", "occt_support"}
    assert names - {"OCP"} <= set(sys.stdlib_module_names)


def test_without_the_variable_the_oracle_says_why_it_is_skipped(monkeypatch):
    monkeypatch.delenv(O.OCCT_PYTHON_ENV, raising=False)
    O.probe.cache_clear()
    try:
        assert O.occt_python() is None and O.probe() is None
        assert O.OCCT_PYTHON_ENV in O.skip_reason()
    finally:
        O.probe.cache_clear()


def test_a_variable_naming_no_file_is_no_interpreter(monkeypatch, tmp_path):
    monkeypatch.setenv(O.OCCT_PYTHON_ENV, str(tmp_path / "missing" / "python.exe"))
    assert O.occt_python() is None
