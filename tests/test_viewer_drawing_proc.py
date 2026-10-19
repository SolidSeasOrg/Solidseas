"""The drawing child process (``solidseas_app.viewer.drawingproc``; ``docs/DRAWINGS.md``
15.3 and 15.4).

The child runs for real: it makes drawings of copies of the o02, o07 and o11 fixtures
under fictional names in a temporary folder, edits them, regenerates, checks, releases
and exports them. One worker serves most tests, so the suite starts few children; the
tests that must end or crash a child, or hold it to tiny limits, start their own.
Garbled answers come from a stand-in for the child (this module's functions, which the
child imports), as the mail tests stand in for Simple MAPI. Nothing here needs Qt.

The children of the shared worker run under an audit hook that records every file they
open for writing, rename, make or remove; the last test checks that nothing was
written, and that the window's side wrote nothing outside pytest's temporary folder.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

import dxf_reader
from pdf_reader import PdfDocument
from solidseas.drawing import DrawingLimits, DrawingOptions, document, edit
from solidseas.drawing import settings as S
from solidseas.drawing.release import ReleaseRefusedError
from solidseas.drawing.types import FrameCell
from solidseas.errors import (
    ConfigurationNotFoundError,
    DrawingInvalidError,
    DrawingReleasedError,
    DrawingTooComplexError,
    InvalidArgumentError,
    ModelNotFoundError,
    UnsupportedOperationError,
    WorkerJobError,
)
from solidseas_app.viewer import drawingproc
from solidseas_app.viewer.drawingproc import DrawingWorker, ProcessStopped
from support import fixture_path, parts_at_stored_paths

TODAY = "2026-10-04"
FIELDS = {"number": "SS-1", "drawn_by": "Ann Bee", "material": "6061-T6", "finish": "None"}
AUDIT_ENV = "SOLIDSEAS_TEST_DRAWINGPROC_AUDIT"
GARBLE_ENV = "SOLIDSEAS_TEST_DRAWINGPROC_GARBLE"
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


def people():
    """Drawing Settings of the fictional Example Engineering Co., with two people."""
    s = S.with_value(S.DrawingSettings(), "company", "name", "Example Engineering Co.")
    return S.with_value(
        s, "people", "people", [{"name": "Ann Bee", "initials": "AB"}, {"name": "Carl Dee", "initials": "CD"}]
    )


# --------------------------------------------------------------------------- what the child writes
def _writes(event: str, args: tuple) -> list[str]:
    """The paths an audit event writes: a file opened for writing, a rename, a folder
    made, a file removed or truncated."""
    paths = []
    if event == "open" and len(args) >= 3:
        path, mode, flags = args[0], args[1], args[2]
        writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & _WRITE_FLAGS
        )
        if writing and isinstance(path, (str, bytes, os.PathLike)):
            paths.append(os.path.abspath(os.fsdecode(path)))
    elif event in ("os.rename", "os.replace", "os.remove", "os.mkdir", "os.truncate", "os.rmdir") and args:
        for p in args[:2] if event in ("os.rename", "os.replace") else args[:1]:
            if isinstance(p, (str, bytes, os.PathLike)):
                paths.append(os.path.abspath(os.fsdecode(p)))
    # Python's own bytecode cache, written when a module is first imported, is not the child's
    return [p for p in paths if "__pycache__" not in Path(p).parts]


def serve_audited(conn) -> None:
    """The child of the shared worker: the real one, under an audit hook that appends
    every write it sees to the file :data:`AUDIT_ENV` names (opened before the hook)."""
    target = os.environ.get(AUDIT_ENV)
    if target:
        log = open(target, "a", encoding="utf-8")  # noqa: SIM115 - held for the child's life

        def hook(event: str, args: tuple) -> None:
            for p in _writes(event, args):
                log.write(f"{event} {p}\n")
                log.flush()

        sys.addaudithook(hook)
        log.write("audited\n")  # the hook is in place in this child
        log.flush()
    drawingproc._serve(conn)


@dataclass
class Place:
    root: Path
    parts: Path
    log: Path
    worker: DrawingWorker

    def part(self, name: str = "bracket.SLDPRT") -> str:
        return str(self.parts / name)


@pytest.fixture(scope="module")
def place(tmp_path_factory):
    """The folder the tests work in, the parts they draw (copies under fictional names)
    and the worker most of them share."""
    root = tmp_path_factory.mktemp("drawingproc")
    parts = root / "parts"
    parts.mkdir()
    for fixture, name in (
        ("o02_boxA.SLDPRT", "bracket.SLDPRT"),
        ("o07_boxB_h31.SLDPRT", "bracket taller.SLDPRT"),
        ("o11_curved.SLDPRT", "plate.SLDPRT"),
        ("o08_asm_2x_boxA.SLDASM", "pair.SLDASM"),
    ):
        shutil.copyfile(fixture_path(fixture), parts / name)
    log = root / "writes.log"
    log.write_text("", encoding="utf-8")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv(AUDIT_ENV, str(log))  # every child the shared worker starts audits itself
        worker = DrawingWorker(serve=serve_audited)
        try:
            yield Place(root, parts, log, worker)
        finally:
            worker.close()


@pytest.fixture(scope="module")
def made(place):
    """A drawing of the bracket, made once and shared by the tests that only read it."""
    return place.worker.make(place.part(), fields=FIELDS, settings=people())


def dim(drawing, key):
    return next(d for d in drawing.dimensions if d.key == key)


# --------------------------------------------------------------------------- making
def test_a_real_child_makes_the_bracket_and_the_plate(place, made):
    worker = place.worker
    assert made.drawing.status == "PRELIMINARY" and made.summary["status"] == "PRELIMINARY"
    assert made.summary["id"] == made.drawing.id
    assert dict(made.drawing.title)["number"].text == "SS-1"
    assert document.dumps(made.drawing) == made.data  # the bytes are the drawing the window reads
    assert made.checks and all(c.level in ("error", "warning", "information") for c in made.checks)
    assert made.drawing.checks == made.checks and made.coverage.complete
    for stage in ("source", "model", "features", "views", "plan", "assemble", "total", "wall"):
        assert made.seconds[stage] >= 0.0
    plate = worker.make(place.part("plate.SLDPRT"), DrawingOptions(units="mm"), {"number": "SS-2"}, people())
    assert plate.drawing.options.units == "mm" and len(plate.drawing.features) > len(made.drawing.features)
    assert plate.drawing.id != made.drawing.id and isinstance(plate.thread_candidates, tuple)
    assert worker.running and worker.started >= 1


def test_a_make_says_each_stage_as_it_starts(place):
    seen: list[dict] = []
    got = place.worker.make(place.part(), fields=FIELDS, settings=people(), progress=seen.append)
    stages = ["source", "model", "features", "views", "plan", "assemble"]
    assert seen == [{"stage": name, "step": k, "of": 6} for k, name in enumerate(stages, 1)]
    assert got.drawing.status == "PRELIMINARY"
    assert drawingproc.progress_in(json.dumps({"ok": True}).encode()) is None  # a header is no progress


def test_settings_cross_as_their_file_content(place):
    s = S.with_value(people(), "company", "name", "Example Engineering Co. West")
    got = place.worker.make(place.part(), fields={"number": "SS-3"}, settings=S.to_dict(s))
    assert (
        got.drawing.settings.company.name == "Example Engineering Co. West"
    )  # unsaved choices reach the child
    bad = {**S.to_dict(s), "sheets": {**S.to_dict(s)["sheets"], "size": "Z"}}
    warned = place.worker.make(place.part(), fields={"number": "SS-4"}, settings=bad)
    assert any(w.startswith("settings: ") for w in warned.warnings)


def test_the_probe_says_what_page_one_needs(place):
    p = place.worker.probe(place.part("plate.SLDPRT"))
    assert p.name == "plate.SLDPRT" and p.configurations == ("Default",) and p.configuration == "Default"
    assert p.unit == "mm" and p.unit_origin == "file" and p.evidence is None and p.refused is None
    assert [round(v, 6) for v in p.size_mm] == [40.0, 30.0, 10.0]  # the corner fillets stay inside the block
    assert p.counts == {"bodies": 1, "faces": 12, "edges": 27, "blends": 0}
    assert len(p.bodies) == 1 and p.bodies[0].selected and p.bodies[0].faces == 12
    assert [round(v, 4) for v in place.worker.probe(place.part()).size_in] == [0.3937, 0.7874, 1.1811]
    if not parts_at_stored_paths(place.part("pair.SLDASM")):  # else the kit's output holds its part
        asm = place.worker.probe(place.part("pair.SLDASM"))  # an assembly whose part is not beside it
        assert asm.refused and asm.refused_code == "not_implemented" and asm.refused_rule == "no_instances"
        assert asm.bodies == () and asm.size_m is None and asm.assembly is None
    with pytest.raises(ConfigurationNotFoundError):
        place.worker.probe(place.part("plate.SLDPRT"), "Nowhere")


def test_the_probe_of_an_assembly_lists_its_instances_and_it_is_drawn(place, tmp_path):
    for name in ("o08_asm_2x_boxA.SLDASM", "o02_boxA.SLDPRT"):
        shutil.copyfile(fixture_path(name), tmp_path / name)  # the assembly beside its part
    p = place.worker.probe(tmp_path / "o08_asm_2x_boxA.SLDASM")
    assert p.refused is None and p.assembly == drawingproc.AssemblyProbe(1, 2, ())
    assert [(b.name, b.type, b.faces, b.selected) for b in p.bodies] == [
        ("o02_boxA-1", "part", 6, True),
        ("o02_boxA-2", "part", 6, True),
    ]
    assert p.counts == {"bodies": 1, "faces": 12, "edges": 24, "blends": 0}  # the part's body once
    assert [round(v, 6) for v in p.size_mm] == [60.0, 20.0, 30.0]  # both instances, placed
    made = place.worker.make(
        tmp_path / "o08_asm_2x_boxA.SLDASM", fields={"number": "SS-8"}, settings=people()
    )
    counts = made.summary["counts"]
    # one item, its balloon, and the overall size as three reference dimensions
    assert (counts["items"], counts["balloons"], counts["dimensions"]) == (1, 1, 3)
    assert made.summary["model"]["format"] == "sldasm" and made.drawing.features == ()


def test_the_overall_size_takes_the_arcs_that_bulge_past_their_ends():
    import drawing_parts as P

    xt, _truth = P.link_plate()  # 120 x 30 x 8 mm with full-round ends: its vertices span 90 mm
    box, blends = drawingproc._extent([xt])
    size = [round((hi - lo) * 1000.0, 6) for lo, hi in zip(box[0], box[1], strict=True)]
    assert size == [120.0, 30.0, 8.0] and blends == 0
    assert drawingproc._extent([]) == (None, 0)


def test_a_part_over_the_bounds_is_refused_on_page_one():
    worker = DrawingWorker(DrawingLimits(faces=5))
    try:
        p = worker.probe(fixture_path("o11_curved.SLDPRT"))
        assert p.refused == "the part has 12 faces, more than the 5 a drawing takes"
        assert p.refused_code == "drawing_too_complex" and p.refused_rule == "faces"
        assert p.size_m is not None  # read all the same, from the topology alone
        with pytest.raises(DrawingTooComplexError) as info:  # and the library refuses it too
            worker.make(fixture_path("o11_curved.SLDPRT"))
        assert info.value.code == "drawing_too_complex" and info.value.detail["limit"] == "faces"
    finally:
        worker.close()


# --------------------------------------------------------------------------- editing
def test_an_edit_and_its_undo(place, made):
    worker = place.worker
    first = dim(made.drawing, "size/f-1")
    removed = worker.edit(made, "remove", [first.id])
    assert dim(removed.drawing, "size/f-1").state == "removed" and removed.coverage is not None
    assert removed.seconds["total"] < 5.0
    back = worker.edit(removed.data, "restore", {"ident": first.id})  # bytes, keyword arguments
    assert back.drawing.dimensions == made.drawing.dimensions
    frame = FrameCell("position", 0.1, True, None, ())
    framed = worker.edit(back, "set_frame", [first.id, frame])
    assert dim(framed.drawing, "size/f-1").frame == frame
    found = worker.candidates(back, ["f-1"])
    assert found == () or all(isinstance(c, edit.Candidate) for c in found)
    restored = worker.candidates(removed, ["f-1"])
    assert [c.kind for c in restored] == ["restore"]
    again = worker.edit(removed, "add", [restored[0]])  # the candidate crosses back
    assert dim(again.drawing, "size/f-1").state == "shown"


def test_an_edit_after_a_restart_asks_for_the_model_then_attaches(place, made, tmp_path):
    worker = place.worker
    worker.warm()
    started = worker.started
    worker._proc.kill()  # as if the child crashed
    worker._proc.join(5)
    with pytest.raises(ModelNotFoundError) as info:
        worker.edit(made, "remove", ["d-1"])
    assert isinstance(info.value, InvalidArgumentError) and info.value.detail["rule"] == "model_not_found"
    assert worker.started == started + 1
    attached = worker.attach(made, place.part())
    assert attached.same_file and attached.checks
    assert dim(worker.edit(made, "remove", ["d-1"]).drawing, "size/f-1").state == "removed"
    # The model found from where the drawing is saved (13.6), as the editor does for a file it opens.
    path = place.parts / "bracket.ssdrw"
    if not path.exists():
        document.save(made.drawing, str(path))
    worker._proc.kill()
    worker._proc.join(5)
    with pytest.raises(ModelNotFoundError):
        worker.edit(made, "remove", ["d-1"])
    assert worker.attach(made, drawing_path=path).same_file
    assert worker.edit(made, "remove", ["d-1"]).drawing.status == "PRELIMINARY"
    worker.forget(made)  # as the editor does on closing the drawing
    with pytest.raises(ModelNotFoundError):
        worker.edit(made, "remove", ["d-1"])
    worker.attach(made, place.part())


def test_update_from_model_merges_the_taller_bracket(place):
    worker = place.worker
    d = worker.make(place.part(), fields=FIELDS, settings=people())
    a, b = dim(d.drawing, "size/f-1"), dim(d.drawing, "size/f-2")
    d = worker.edit(d, "remove", [a.id])
    d = worker.edit(d, "move", [b.id, 3.0, 6.0])
    merged = worker.regenerate(d, place.part("bracket taller.SLDPRT"))
    assert merged.merge.changed >= 1 and merged.merge.words().endswith("needs attention")
    assert dim(merged.drawing, a.key).state == "removed"
    kept = dim(merged.drawing, b.key)
    assert kept.id == b.id and kept.placement.moved
    again = worker.edit(merged, "restore", [a.id])  # the merged drawing is editable at once
    assert dim(again.drawing, a.key).state == "shown"
    same = worker.regenerate(merged, place.part("bracket taller.SLDPRT"))
    assert same.merge.model_unchanged and same.coverage is None


# --------------------------------------------------------------------------- exports and release
def test_the_exports_are_the_writers_bytes(place, made):
    pdf = place.worker.export(made, "pdf")
    doc = PdfDocument(pdf.data)
    assert str(doc.info()["Producer"]).startswith("SolidSeas")
    words = " ".join(r.text for r in doc.text_runs())
    assert "SS-1" in words and "PRELIMINARY" in words
    dxf = place.worker.export(made.data, "dxf")
    read = dxf_reader.read(dxf.data)
    assert read.comments[0].startswith("SolidSeas") and dxf_reader.drawn(read)
    assert pdf.seconds["total"] >= 0.0 and dxf.kind == "dxf"


def test_release_is_refused_then_allowed(place):
    worker = place.worker
    d = worker.make(place.part(), fields=FIELDS, settings=people())
    with pytest.raises(ReleaseRefusedError) as info:
        worker.release(d, today=TODAY)
    assert "CHECKED is not signed" in info.value.reasons and info.value.detail["rule"] == "release_refused"
    d = worker.edit(d, "sign", ["CHECKED", "Carl Dee", TODAY])
    assert d.drawing.status == "CHECKED"
    d = worker.edit(d, "sign", {"row": "APPROVED", "person": "Ann Bee", "today": TODAY})
    assert worker.checks(d, at_release=True) is not None
    released = worker.release(d, today=TODAY)
    assert released.drawing.status == "RELEASED" and released.summary["status"] == "RELEASED"
    with pytest.raises(DrawingReleasedError) as info:
        worker.edit(released, "remove", ["d-1"])
    assert info.value.code == "drawing_released" and info.value.detail["rule"] == "drawing_released"
    opened = worker.edit(released, "start_revision", {"description": "HEIGHT CHANGED", "today": TODAY})
    assert opened.drawing.status == "PRELIMINARY" and [r.rev for r in opened.drawing.revisions] == ["A", "B"]


def test_a_released_drawing_is_revised_from_its_changed_model_in_one_step(place):
    worker = place.worker
    d = worker.make(place.part(), fields=FIELDS, settings=people())
    d = worker.edit(d, "sign", ["CHECKED", "Carl Dee", TODAY])
    d = worker.edit(d, "sign", ["APPROVED", "Ann Bee", TODAY])
    released = worker.release(d, today=TODAY)
    worker.forget(released)  # as a released drawing opened from its file
    with pytest.raises(DrawingReleasedError):
        worker.regenerate(released, place.part("bracket taller.SLDPRT"))
    taller = place.part("bracket taller.SLDPRT")
    revised = worker.regenerate(released, taller, revision="HEIGHT CHANGED", drawn_by="Ann Bee", today=TODAY)
    d = revised.drawing
    assert d.status == "PRELIMINARY" and [r.rev for r in d.revisions] == ["A", "B"]
    assert d.revisions[-1].description == "HEIGHT CHANGED" and revised.merge.changed >= 1
    words = " ".join(r.text for r in PdfDocument(worker.export(revised, "pdf").data).text_runs())
    assert "PRELIMINARY" in words and "HEIGHT CHANGED" in words


# --------------------------------------------------------------------------- errors
def test_errors_cross_with_their_codes(place, made):
    worker = place.worker
    with pytest.raises(InvalidArgumentError) as info:
        worker.edit(made, "remove", ["d-999"])
    assert type(info.value) is InvalidArgumentError and info.value.detail == {"parameter": "id"}
    with pytest.raises(UnsupportedOperationError) as info:
        worker.edit(made, "add_view", ["section"])
    assert info.value.code == "not_implemented" and info.value.detail["rule"] == "later_release"
    with pytest.raises(DrawingInvalidError) as info:
        worker.checks(b'{"schema": "solidseas.drawing/9", "id": "x"}')
    assert type(info.value) is document.DrawingFileError and info.value.detail["value"] == "schema_newer"
    with pytest.raises(FileNotFoundError):
        worker.make(str(place.parts / "missing.SLDPRT"))
    with pytest.raises(InvalidArgumentError) as info:
        worker.edit(made, "remove", {"ident": "d-1", "limits": {}})
    assert info.value.detail == {"parameter": "args"}
    with pytest.raises(InvalidArgumentError) as info:
        worker.edit(made, "set_frame", ["d-1", {"characteristic": "position", "value": 0.1, "colour": "red"}])
    assert info.value.detail == {"parameter": "frame"}
    with pytest.raises(InvalidArgumentError):  # refused here, before anything crosses
        worker.edit(made, "forget", [])
    assert worker.running  # an error answered leaves the child as it was


def test_an_error_object_is_raised_again_as_its_class():
    raise_ = drawingproc._raise_error
    with pytest.raises(ReleaseRefusedError) as info:
        raise_(
            {
                "code": "invalid_argument",
                "message": "x",
                "detail": {"parameter": "drawing", "rule": "release_refused", "value": 1},
                "exception": "ReleaseRefusedError",
                "reasons": ["CHECKED is not signed"],
            }
        )
    assert info.value.reasons == ("CHECKED is not signed",)
    with pytest.raises(WorkerJobError) as info:
        raise_({"code": "internal", "message": "boom", "detail": {}, "exception": "ZeroDivisionError"})
    assert info.value.code == "internal" and str(info.value) == "boom"
    with pytest.raises(PermissionError):
        raise_(
            {"code": "permission_denied", "message": "denied", "detail": None, "exception": "PermissionError"}
        )
    with pytest.raises(drawingproc.BadAnswer):
        raise_({"code": "no_such_code", "message": "x", "detail": {}, "exception": "X"})
    with pytest.raises(drawingproc.BadAnswer):  # a member detail may not carry, such as a path
        raise_({"code": "internal", "message": "x", "detail": {"path": "/tmp/x"}, "exception": "X"})


def test_every_operation_of_the_edit_module_is_named():
    assert set(drawingproc.OPERATIONS) | set(drawingproc.NOT_OPERATIONS) == set(edit.__all__)
    for op in drawingproc.OPERATIONS:
        assert next(iter(drawingproc.inspect.signature(getattr(edit, op)).parameters)) == "drawing", op


# --------------------------------------------------------------------------- the codecs
def test_the_codecs_go_both_ways_and_refuse_what_the_library_refuses():
    frame = FrameCell("position", 0.25, True, "mmc", ("A", "B"))
    assert drawingproc.frame_from_json(drawingproc.frame_to_json(frame)) == frame
    for bad in (
        {"characteristic": "nonsense", "value": 0.1},
        {"characteristic": "position", "value": float("nan")},
        {"characteristic": "position", "value": 0.1, "datums": ["A", "B", "C", "D"]},
        {"characteristic": "position", "value": 0.1, "datums": ["a"]},
        {"characteristic": "position", "value": 0.1, "modifier": "rfs"},
        {"characteristic": "position", "value": 0.1, "colour": "red"},
    ):
        with pytest.raises(InvalidArgumentError):
            drawingproc.frame_from_json(bad)
    candidate = edit.Candidate(
        "distance", "user/distance/f-1/f-2/x", 0.02, "20.00 along X", ("f-1", "f-2"), "x", "v-1"
    )
    assert drawingproc.candidate_from_json(drawingproc.candidate_to_json(candidate)) == candidate
    good = drawingproc.candidate_to_json(candidate)
    for change in ({"kind": "other"}, {"features": []}, {"axis": "w"}, {"key": "Bad Key"}, {"value": "1"}):
        with pytest.raises(InvalidArgumentError):
            drawingproc.candidate_from_json({**good, **change})
    with pytest.raises(InvalidArgumentError):
        drawingproc.candidate_from_json({**good, "extra": 1})
    options = DrawingOptions(
        process="printed",
        units="in",
        views=("front", "top"),
        scale=(1, 2),
        arrangement=(("v-1/x", "ordinate"),),
    )
    assert (
        drawingproc.options_from_json(json.loads(json.dumps(drawingproc.options_to_json(options)))) == options
    )
    with pytest.raises(InvalidArgumentError):
        drawingproc.options_from_json({"process": "turned"})
    with pytest.raises(InvalidArgumentError):
        drawingproc.options_from_json({"colour": "red"})
    s = people()
    assert drawingproc.settings_from_json(drawingproc.settings_to_json(s)) == (s, [])
    with pytest.raises(InvalidArgumentError):
        drawingproc._jsonable({"x": object()}, "args")


def test_the_limits_of_time_and_memory():
    assert drawingproc.time_limit() == 150.0 + drawingproc.MARGIN_SECONDS
    assert drawingproc.time_limit(DrawingLimits(seconds_total=10.0), 2.0) == 12.0
    real = drawingproc._physical_memory
    try:
        drawingproc._physical_memory = lambda: 1 << 30
        assert drawingproc.memory_limit() == 512 << 20  # at most half the PC's memory
        drawingproc._physical_memory = lambda: None
        assert drawingproc.memory_limit() == 3072 << 20
    finally:
        drawingproc._physical_memory = real
    with pytest.raises(InvalidArgumentError):
        DrawingWorker(margin=-1)


def test_the_window_never_unpickles_what_the_child_sends():
    code = Path(drawingproc.__file__).read_text(encoding="utf-8")
    assert re.findall(r"conn\.recv\(", code) == []
    assert re.findall(r"\.send\(", code) == []
    assert re.findall(r"import pickle|\bpickle\.|\.recv\(\)", code) == []


# --------------------------------------------------------------------------- cancel and the time limit
def test_a_cancel_during_a_make_ends_the_child(place):
    worker = place.worker
    worker.warm()
    started = worker.started
    out: dict = {}

    def run() -> None:
        try:
            out["answer"] = worker.make(place.part("plate.SLDPRT"), settings=people())
        except ProcessStopped as exc:
            out["error"] = exc

    th = threading.Thread(target=run)
    th.start()
    end = time.monotonic() + 30
    while not worker.busy and time.monotonic() < end:
        time.sleep(0.002)
    time.sleep(0.05)  # into the make, which takes a few tenths of a second
    t = time.monotonic()
    assert worker.cancel()
    th.join(10)
    assert out["error"].reason == "cancelled" and out["error"].code == "interrupted"
    assert time.monotonic() - t < 5 and not worker.running and not worker.busy
    assert not worker.cancel()  # nothing in progress now
    again = worker.make(place.part("plate.SLDPRT"), settings=people())  # a new child
    assert again.drawing.status == "PRELIMINARY" and worker.started == started + 1
    assert "start" in again.seconds and again.seconds["wall"] >= again.seconds["start"]


def test_a_request_past_the_time_limit_ends_the_child(place):
    worker = DrawingWorker(DrawingLimits(seconds_total=0.001), margin=0.0)
    try:
        worker.warm()
        assert worker.time_limit == 0.001
        t = time.monotonic()
        # Either side may end it first: the parent stops the child at its limit, or under a
        # loaded machine the child's own check of the same limit answers before that.
        with pytest.raises((ProcessStopped, DrawingTooComplexError)) as info:
            worker.make(place.part("plate.SLDPRT"))
        if isinstance(info.value, ProcessStopped):
            assert info.value.reason == "timeout" and info.value.code == "timeout"
            assert info.value.detail == {"limit": "seconds_total", "value": 1}
            assert not worker.running
        else:
            assert (
                "seconds_total" in str(info.value)
                or getattr(info.value, "detail", {}).get("limit") == "seconds_total"
            )
        assert time.monotonic() - t < 10
    finally:
        worker.close()
    with pytest.raises(ProcessStopped) as info:
        worker.make(place.part())
    assert info.value.reason == "cancelled"  # closed: no request starts


@pytest.mark.skipif(os.name != "nt", reason="job objects are a Windows feature")
def test_the_drawing_process_is_held_to_its_memory_limit(place):  # pragma: no cover - Windows
    # On the PC the child peaks at about 36 MB making this part's drawing, its start and
    # imports included, so 64 MB held nothing; at 24 MB it is ended before it answers.
    worker = DrawingWorker(DrawingLimits(child_memory_mb=24))
    try:
        with pytest.raises(ProcessStopped) as info:
            worker.make(place.part("plate.SLDPRT"))
        assert info.value.reason == "too_large" and worker.contained
        assert info.value.detail == {"limit": "child_memory_mb", "value": 24}
    finally:
        worker.close()


# --------------------------------------------------------------------------- garbled answers
def _announce(kind: str, data: bytes, size: int | None = None, sha: str | None = None) -> bytes:
    spec = {"kind": kind, "bytes": len(data) if size is None else size}
    spec["sha256"] = sha or hashlib.sha256(data).hexdigest()
    return json.dumps({"ok": True, "result": {"warnings": []}, "frames": [spec]}).encode()


PROGRESS = json.dumps({"progress": {"stage": "source", "step": 1, "of": 6}}).encode()
GARBLES = {
    "not_json": [b"{not json"],
    "not_an_object": [b"[1, 2]"],
    "a_key_twice": [b'{"ok": true, "ok": false}'],
    "no_result": [b'{"ok": true, "frames": []}'],
    "a_frame_longer_than_announced": [_announce("ssdrw", b"x" * 10), b"x" * 20],
    "a_frame_not_the_one_announced": [_announce("ssdrw", b"x" * 10, sha="0" * 64), b"x" * 10],
    "a_frame_too_large": [_announce("ssdrw", b"x", size=1 << 40)],
    "a_frame_not_asked_for": [_announce("pdf", b"%PDF-1.7")],
    "an_error_with_a_code_unknown": [
        b'{"ok": false, "error": {"code": "nope", "message": "", "exception": "X"}}'
    ],
    "a_drawing_without_its_checks": [_announce("ssdrw", b"x"), b"x"],
    "a_progress_frame_not_one": [b'{"progress": {"stage": "nope", "step": 1, "of": 6}}'],
    "a_progress_frame_too_long": [b'{"progress":' + b" " * 600 + b"}"],
    "progress_frames_without_end": [PROGRESS] * (drawingproc.MAX_PROGRESS + 1),
    "not_ready": [],
    "crash": [],
}


def serve_garbled(conn) -> None:
    """A stand-in for the child that says it is ready (unless told not to), then answers
    the first request with the frames of the garble :data:`GARBLE_ENV` names, and waits
    for the window to end it; ``crash`` ends at the first request."""
    garble = os.environ.get(GARBLE_ENV, "not_json")
    conn.send_bytes(b'{"ready": false}' if garble == "not_ready" else json.dumps(drawingproc.READY).encode())
    try:
        conn.recv_bytes()
        if garble == "crash":
            os._exit(3)
        for frame in GARBLES[garble]:
            conn.send_bytes(frame)
        conn.recv_bytes()
    except (EOFError, OSError):
        return


@pytest.mark.parametrize("garble", sorted(GARBLES))
def test_a_garbled_answer_is_refused(garble, monkeypatch):
    monkeypatch.setenv(GARBLE_ENV, garble)
    worker = DrawingWorker(serve=serve_garbled)
    try:
        with pytest.raises(ProcessStopped) as info:
            worker.edit(b"{}", "remove", ["d-1"])  # a request whose answer is a drawing
        assert info.value.reason == ("stopped" if garble == "crash" else "bad_answer")
        assert info.value.code == "worker_crashed" and not worker.running
    finally:
        worker.close()


# --------------------------------------------------------------------------- nothing written
def test_nothing_is_written_outside_tmp_path(place, tmp_path):
    seen: list[str] = []
    active = True

    def hook(event: str, args: tuple) -> None:
        if active:
            seen.extend(_writes(event, args))

    sys.addaudithook(hook)  # idle once this test ends
    try:
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in place.parts.glob("*.SLD*")}
        worker = place.worker
        d = worker.make(place.part(), fields=FIELDS, settings=people())
        d = worker.edit(d, "set_precision", ["d-1", 3])
        worker.regenerate(d, place.part("bracket taller.SLDPRT"))
        worker.export(d, "pdf")
        worker.export(d, "dxf")
        worker.probe(place.part("plate.SLDPRT"))
        worker.checks(d)
    finally:
        active = False
    roots = [os.path.realpath(place.root), os.path.realpath(tmp_path)]
    outside = [p for p in seen if not any(os.path.commonpath([os.path.realpath(p), r]) == r for r in roots)]
    assert outside == []  # the window's side wrote nothing outside the temporary folders
    child = place.log.read_text(encoding="utf-8").splitlines()
    assert child and set(child) == {"audited"}  # every child of the shared worker wrote nothing at all
    assert _writes("open", (str(tmp_path / "x"), "w", 0)) and not _writes(
        "open", (str(tmp_path / "x"), "r", 0)
    )
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in place.parts.glob("*.SLD*")}
    assert after == before  # the parts were opened read-only


def test_each_request_carries_the_folder_the_window_has_open_then(monkeypatch):
    from solidseas_app.viewer.drawingproc import DrawingWorker

    worker = DrawingWorker()
    sent = []

    def exchange(payload, accept, token, progress):
        sent.append(json.loads(payload))
        return {"ok": True}, {}, {}

    monkeypatch.setattr(worker, "_exchange", exchange)
    opened = ["C:/Projects/one"]
    worker.folder = lambda: opened[0]
    try:
        worker._request({"op": "boms"}, ())
        opened[0] = "C:/Projects/two"
        worker._request({"op": "boms"}, ())
        worker.folder = None
        worker._request({"op": "boms"}, ())
    finally:
        worker.close()
    assert [r.get("folder") for r in sent] == ["C:/Projects/one", "C:/Projects/two", None]
