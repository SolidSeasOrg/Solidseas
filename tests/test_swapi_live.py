"""Live mode against a real SOLIDWORKS: SolidSeas' own, started hidden by one bridge for
batch work, standing in for a person's session, to which a second bridge attaches the
way the assistant does. Never a person's own SOLIDWORKS: the session list is asked about
that one process only.

Opt-in, on Windows with SOLIDWORKS 2024 and its MBD part template:
``SOLIDSEAS_SWAPI_SOLIDWORKS=1`` with ``SOLIDSEAS_SWAPI_BUILD_CHECK=1`` (which builds
the bridge) or ``SOLIDSEAS_SWBRIDGE`` (a built one). Starting SOLIDWORKS takes the
foreground for some seconds, so run it when nobody is working at the PC.

``SOLIDSEAS_SWAPI_ATTACH_PID=<pid>`` runs the same tests in the person's own open
SOLIDWORKS instead, as the person agreed on 2026-10-19 while SolidSeas' own instance could
not start: a bridge with ``--test-session`` attaches to that process, makes each test's
new part from the template there, and closes that part (unsaved) afterwards. It touches
no other document, imports nothing and never ends that SOLIDWORKS.

What it checks: the snapshot of a new part; a boss sketched on each reference plane and
on a face lands where the snapshot's frame for it says, to a micrometre; a cut, a
fillet, a chamfer, a dimension, suppression and a custom property change the part as
they should; the safety copy is written and leaves the part as it was; the undo entry
is recorded; a feature the bridge made is deleted on request and no other one is; an
undo entry a bridge left open when it was ended is closed by the next one; and steps
that use an earlier step's geometry, deleted newest first, give back each state before
them exactly (the measurement docs/ASSISTANT.md asks for before Automatic mode).
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import pytest

from solidseas.ai.context import build_model_summary
from solidseas.swapi import build
from solidseas.swapi.bridge import DEFAULT_SOLIDWORKS_EXE, ENV_BRIDGE, Bridge, BridgeRequestError
from solidseas.swapi.live import LiveError
from solidseas_app.assistant.live_sessions import BridgeSessions
from solidseas_app.assistant.session import LiveDocument, LiveSession

MBD_PART_TEMPLATE = Path(
    "C:/ProgramData/SolidWorks/SOLIDWORKS 2024/templates/MBD/part 0051mm to 0250mm.prtdot"
)
UM = 1e-6  # lengths agree within a micrometre


_ATTACH = os.environ.get("SOLIDSEAS_SWAPI_ATTACH_PID")
ATTACH_PID = int(_ATTACH) if _ATTACH else None


def _reason() -> str | None:
    if sys.platform != "win32":
        return "the bridge runs on Windows"
    if ATTACH_PID is None and os.environ.get("SOLIDSEAS_SWAPI_SOLIDWORKS") != "1":
        return "set SOLIDSEAS_SWAPI_SOLIDWORKS=1 (with the build check) to start SolidSeas' own SOLIDWORKS"
    if not os.environ.get(ENV_BRIDGE) and os.environ.get("SOLIDSEAS_SWAPI_BUILD_CHECK") != "1":
        return "set SOLIDSEAS_SWAPI_BUILD_CHECK=1 to build the bridge, or SOLIDSEAS_SWBRIDGE to a built one"
    if not DEFAULT_SOLIDWORKS_EXE.is_file() or not MBD_PART_TEMPLATE.is_file():
        return "needs SOLIDWORKS 2024 and the MBD part template it installs"
    return None


REASON = _reason()
pytestmark = pytest.mark.skipif(REASON is not None, reason=REASON or "")


@pytest.fixture(scope="module")
def exe(tmp_path_factory):
    given = os.environ.get(ENV_BRIDGE)
    return Path(given) if given else build.build_bridge(tmp_path_factory.mktemp("swbridge"))


@pytest.fixture
def own(exe):
    """SolidSeas' own hidden SOLIDWORKS, with a new part open: its PID and the part's key.

    With ``SOLIDSEAS_SWAPI_ATTACH_PID``, the person's session instead, and a new part made
    there for this test only, closed unsaved afterwards.
    """
    if ATTACH_PID is not None:
        with Bridge(exe, test_session=True) as b:
            b.request("live_attach", {"pid": ATTACH_PID}, timeout=60)
            new = b.request("test_session_new_part", {"template": str(MBD_PART_TEMPLATE)})
            try:
                yield ATTACH_PID, new["document"]
            finally:
                try:
                    b.request("test_session_close", {"document": new["document"]})
                finally:
                    b.request("live_detach")
        return
    with Bridge(exe) as b:
        pid = b.request("start_solidworks")["pid"]
        new = b.request("new_document", {"template": str(MBD_PART_TEMPLATE)})
        try:
            yield pid, new["title"]
        finally:
            b.request("exit_solidworks")


def _live(exe, cache: Path) -> BridgeSessions:
    env = {**os.environ, "SOLIDSEAS_CACHE_DIR": str(cache)}
    return BridgeSessions(
        lambda: Bridge(exe, env=env), include_solidseas=True, runs_folder=str(cache / "runs")
    )


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _at(origin, x, normal, u, v, w):
    y = _cross(normal, x)
    return tuple(origin[i] + u * x[i] + v * y[i] + w * normal[i] for i in range(3))


def _box(points):
    return tuple(min(p[i] for p in points) for i in range(3)), tuple(
        max(p[i] for p in points) for i in range(3)
    )


def _union(a, b):
    if a is None:
        return b
    return tuple(map(min, a[0], b[0])), tuple(map(max, a[1], b[1]))


def _close(a, b, tol=UM):
    return all(abs(p - q) <= tol for p, q in zip(a, b, strict=True))


def _rectangle(u0, v0, w, h):
    corners = [(u0, v0), (u0 + w, v0), (u0 + w, v0 + h), (u0, v0 + h)]
    return {
        "unit": "mm",
        "segments": [
            {"type": "line", "start": list(corners[i]), "end": list(corners[(i + 1) % 4])} for i in range(4)
        ],
    }


def test_live_mode_models_in_solidseas_own_solidworks(exe, own, tmp_path):
    pid, key = own
    live = _live(exe, tmp_path)
    try:
        listed = live._request("list_sessions", {"pids": [pid]}, timeout=60)
        (found,) = listed["sessions"]
        assert found["solidseas"] is (ATTACH_PID is None)
        assert found["reachable"] is True and found["writer"] is False
        assert key in [d["key"] for d in found["documents"]]
        session = LiveSession(pid, "test", ())
        document = LiveDocument(key, key, "part", "")
        snap = live.snapshot(session, document)
        assert snap.solid_bodies == 0 and len(snap.planes) >= 3 and snap.path is None

        checkpoint = Path(live.begin_script(session, document))
        assert checkpoint.is_file() and checkpoint.stat().st_size > 0
        assert checkpoint.parent.parent == tmp_path / "runs"
        info = live.call(session, document, "document_info", {})
        assert info["active"] is True and info["dirty"] is False  # the copy left the part as it was

        def call(op, **args):
            return live.call(session, document, op, args)

        # A boss on each reference plane lands where the plane's frame says.
        expected, volume = None, 0.0
        for i, plane in enumerate(snap.planes[:3]):
            u0, v0, w, h, depth = 10.0 + 40 * i, 30.0 + 40 * i, 10.0, 5.0, 5.0
            made = call(
                "sketch_extrude_boss",
                plane=f"P{i + 1}",
                profile=_rectangle(u0, v0, w, h),
                depth={"value": depth, "unit": "mm"},
                direction="normal",
                end="blind",
            )
            assert made["feature"] and made["error"] == 0, made
            mm = 0.001
            corners = [
                _at(plane.origin, plane.sketch_x, plane.normal, u * mm, v * mm, d * mm)
                for u in (u0, u0 + w)
                for v in (v0, v0 + h)
                for d in (0.0, depth)
            ]
            expected = _union(expected, _box(corners))
            volume += w * h * depth * 1e-9
            now = live.snapshot(session, document)
            assert now.box_min is not None and _close(now.box_min, expected[0]), (
                plane.name,
                now.box_min,
                expected,
            )
            assert _close(now.box_max, expected[1]), (plane.name, now.box_max, expected)
            assert math.isclose(now.volume, volume, rel_tol=1e-6)
        assert now.solid_bodies == 3

        # On a face: the top of the first boss, found by its normal and its place.
        front = snap.planes[0]
        top = [
            f
            for f in now.faces
            if f.type == "plane"
            and f.normal is not None
            and _close(f.normal, front.normal, 1e-9)
            and abs(sum((f.point[i] - front.origin[i]) * front.normal[i] for i in range(3)) - 0.005) <= UM
        ]
        assert len(top) == 1
        face = top[0]
        summary = build_model_summary(now)
        handle = next(h for h in summary.handles.handles() if summary.handles.resolve(h).ref == face.ref)
        # where the middle of the first boss is, in the face's own frame
        middle = _at(front.origin, front.sketch_x, front.normal, 0.015, 0.0325, 0.005)
        y = _cross(face.normal, face.sketch_x)
        rel = [middle[i] - face.point[i] for i in range(3)]
        u = sum(rel[i] * face.sketch_x[i] for i in range(3)) * 1000
        v = sum(rel[i] * y[i] for i in range(3)) * 1000
        call(
            "sketch_extrude_boss",
            plane=handle,
            profile={"unit": "mm", "segments": [{"type": "circle", "center": [u, v], "radius": 2}]},
            depth={"value": 3, "unit": "mm"},
            direction="normal",
            end="blind",
        )
        volume += math.pi * 2 * 2 * 3 * 1e-9
        after = live.snapshot(session, document)
        assert math.isclose(after.volume, volume, rel_tol=1e-6)
        rim = [
            e
            for e in after.edges
            if e.type == "circle" and e.radius is not None and abs(e.radius - 0.002) <= UM
        ]
        tops = [
            e
            for e in rim
            if _close(e.center, _at(front.origin, front.sketch_x, front.normal, 0.015, 0.0325, 0.008))
        ]
        assert len(tops) == 1, [e.center for e in rim]

        # A cut through all, into the part from the same face: a hole of radius 1 mm, 5 mm long.
        call(
            "sketch_extrude_cut",
            plane=handle,
            profile={"unit": "mm", "segments": [{"type": "circle", "center": [u + 3.5, v], "radius": 1}]},
            direction="normal",
            end="through_all",
        )
        volume -= math.pi * 1 * 1 * 5 * 1e-9
        assert math.isclose(live.snapshot(session, document).volume, volume, rel_tol=1e-6)

        # A fillet on the four edges of the second boss that run along its plane's normal.
        second = snap.planes[1]
        now = live.snapshot(session, document)
        summary = build_model_summary(now)
        along = [
            e
            for e in now.edges
            if e.type == "line"
            and e.length is not None
            and abs(e.length - 0.005) <= UM
            and _close(
                tuple(abs(c) for c in _unit(_minus(e.end, e.start))),
                tuple(abs(c) for c in second.normal),
                1e-9,
            )
            and _inside(
                e.start, _at(second.origin, second.sketch_x, second.normal, 0.055, 0.0725, 0.0025), 0.008
            )
        ]
        assert len(along) == 4, len(along)
        handles = [
            next(h for h in summary.handles.handles() if summary.handles.resolve(h).ref == e.ref)
            for e in along
        ]
        fillet = call("fillet", edges=handles, radius={"value": 1, "unit": "mm"})
        assert fillet["type"] == "Fillet" and fillet["error"] == 0
        volume -= 4 * (1 - math.pi / 4) * 1 * 1 * 5 * 1e-9
        assert math.isclose(live.snapshot(session, document).volume, volume, rel_tol=1e-6)

        # A chamfer on the four edges of the third boss that run along its plane's normal.
        third = snap.planes[2]
        now = live.snapshot(session, document)
        summary = build_model_summary(now)
        along = [
            e
            for e in now.edges
            if e.type == "line"
            and e.length is not None
            and abs(e.length - 0.005) <= UM
            and _close(
                tuple(abs(c) for c in _unit(_minus(e.end, e.start))),
                tuple(abs(c) for c in third.normal),
                1e-9,
            )
            and _inside(
                e.start, _at(third.origin, third.sketch_x, third.normal, 0.095, 0.1125, 0.0025), 0.008
            )
        ]
        assert len(along) == 4, len(along)
        handles = [
            next(h for h in summary.handles.handles() if summary.handles.resolve(h).ref == e.ref)
            for e in along
        ]
        chamfer = call("chamfer", edges=handles, distance={"value": 1, "unit": "mm"})
        assert chamfer["type"] == "Chamfer" and chamfer["error"] == 0
        volume -= 4 * 0.5 * 1 * 1 * 5 * 1e-9
        assert math.isclose(live.snapshot(session, document).volume, volume, rel_tol=1e-6)

        # Suppressing the fillet gives its volume back; unsuppressing takes it again.
        now = live.snapshot(session, document)
        summary = build_model_summary(now)
        fillet_handle = next(
            h for h in summary.handles.handles() if summary.handles.resolve(h).ref == fillet["feature"]
        )
        call("suppress", features=[fillet_handle])
        filleted = 4 * (1 - math.pi / 4) * 5 * 1e-9
        assert math.isclose(live.snapshot(session, document).volume, volume + filleted, rel_tol=1e-6)
        call("unsuppress", features=[fillet_handle])
        assert math.isclose(live.snapshot(session, document).volume, volume, rel_tol=1e-6)

        # A dimension: the first boss's depth, 5 mm to 6 mm, read back.
        now = live.snapshot(session, document)
        summary = build_model_summary(now)
        boss_ref = now.features[[f.type for f in now.features].index("Extrusion")].ref
        depth_handle = next(
            h
            for h in summary.handles.handles()
            if summary.handles.resolve(h).kind == "dimension"
            and summary.handles.resolve(h).ref.startswith(f"dim:{boss_ref}:")
        )
        changed = call("set_dimension", dimension=depth_handle, value={"value": 6, "unit": "mm"})
        assert changed["rebuilt"] is True and math.isclose(changed["after"], 0.006, abs_tol=1e-12)
        assert math.isclose(changed["before"], 0.005, abs_tol=1e-12)

        # A custom property, then the queries a script has.
        prop = call("set_property", name="SolidSeasTest", value="anodised", scope="file")
        assert prop["before"] is None and prop["after"] == "anodised"
        assert call("list_properties")["properties"]["SolidSeasTest"] == "anodised"
        names = [f["name"] for f in call("list_features")["features"]]
        assert "Fillet1" in names and "Chamfer1" in names
        assert any(d["name"].endswith("@Boss-Extrude1") for d in call("list_dimensions")["dimensions"])
        mass = call("mass_properties")
        assert mass["solid_bodies"] == 3 and mass["volume_m3"] > 0
        with pytest.raises(BridgeRequestError) as caught:
            call("mass_properties", configuration="Another")
        assert caught.value.code == "refused"

        live.end_script(session, document)
        state = list(tmp_path.glob("live-undo-*.txt"))
        assert state == []  # the entry is closed and its record gone

        # A feature this bridge made is deleted on request; one it did not make never is.
        with pytest.raises(BridgeRequestError) as caught:
            live._request("live_delete_feature", {"document": key, "feature": front.ref}, timeout=60, pid=pid)
        assert caught.value.code == "refused"
        deleted = live._request(
            "live_delete_feature", {"document": key, "feature": chamfer["feature"]}, timeout=60, pid=pid
        )
        assert deleted["deleted"] is True
        names = [f["name"] for f in call("list_features")["features"]]
        assert "Chamfer1" not in names
    finally:
        live.close()


def _minus(a, b):
    return tuple(a[i] - b[i] for i in range(3))


def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def _inside(p, centre, radius):
    return math.dist(p, centre) <= radius


def test_an_undo_entry_left_open_by_an_ended_bridge_is_closed_by_the_next(exe, own, tmp_path):
    pid, key = own
    session = LiveSession(pid, "test", ())
    document = LiveDocument(key, key, "part", "")
    first = _live(exe, tmp_path)
    first.snapshot(session, document)
    first._request("live_begin_undo", {"document": key}, timeout=60, pid=pid)
    assert len(list(tmp_path.glob("live-undo-*.txt"))) == 1
    first.call(  # something in the entry, or closing it records nothing
        session,
        document,
        "sketch_extrude_boss",
        {
            "plane": "P1",
            "profile": _rectangle(0, 0, 10, 10),
            "depth": {"value": 2, "unit": "mm"},
            "direction": "normal",
            "end": "blind",
        },
    )
    first._bridge.kill("a test ends it mid-script")  # as a hard timeout would; SOLIDWORKS stays
    second = _live(exe, tmp_path)
    try:
        attached = second._request("live_attach", {"pid": pid}, timeout=60)
        assert attached["undo_entry_closed"] is True
        assert list(tmp_path.glob("live-undo-*.txt")) == []
        assert second.snapshot(session, document).solid_bodies == 1
    finally:
        second.close()
        first.close()


def test_a_script_refuses_what_is_not_in_the_part(exe, own, tmp_path):
    pid, key = own
    live = _live(exe, tmp_path)
    session = LiveSession(pid, "test", ())
    document = LiveDocument(key, key, "part", "")
    try:
        live.snapshot(session, document)
        with pytest.raises(LiveError) as caught:
            live.call(session, document, "fillet", {"edges": ["E1"], "radius": {"value": 1, "unit": "mm"}})
        assert caught.value.code == "refused"  # a new part has no edges
        with pytest.raises(BridgeRequestError) as caught:
            live._request("live_snapshot", {"document": "C:\\nowhere\\else.sldprt"}, timeout=60, pid=pid)
        assert caught.value.code == "not_found"
    finally:
        live.close()


def _state(snap):
    """What a revert must give back exactly: the feature tree by reference, the dimensions,
    the faces and edges by reference, the bodies, the volume and the extents."""
    return {
        "features": [(f.ref, f.name, f.type, f.suppressed) for f in snap.features],
        "dimensions": [(d.ref, round(d.value, 12)) for d in snap.dimensions],
        "faces": sorted((f.ref, f.type) for f in snap.faces),
        "edges": sorted((e.ref, e.type) for e in snap.edges),
        "bodies": snap.solid_bodies,
        "volume": None if snap.volume is None else round(snap.volume, 15),
        "box": None if snap.box_min is None else tuple(round(c, 9) for c in (*snap.box_min, *snap.box_max)),
    }


def test_dependent_steps_revert_newest_first_to_each_state_before_them(exe, own, tmp_path):
    # The question left open before Automatic mode is built (docs/ASSISTANT.md, answer 6):
    # steps whose features use an earlier step's geometry (a fillet on a boss's edges, a sketch
    # on its face, a chamfer on the edge a cut made), each deleted newest first, by persist
    # reference with swDelete_Absorbed, must give back the state before it exactly.
    pid, key = own
    live = _live(exe, tmp_path)
    session = LiveSession(pid, "test", ())
    document = LiveDocument(key, key, "part", "")

    def handle_of(snap, ref):
        summary = build_model_summary(snap)
        return next(h for h in summary.handles.handles() if summary.handles.resolve(h).ref == ref)

    try:
        states = [live.snapshot(session, document)]
        made = []
        boss = live.call(
            session,
            document,
            "sketch_extrude_boss",
            {
                "plane": "P1",
                "profile": _rectangle(0, 0, 20, 10),
                "depth": {"value": 8, "unit": "mm"},
                "direction": "normal",
                "end": "blind",
            },
        )
        made.append(boss["feature"])
        states.append(live.snapshot(session, document))
        snap = states[-1]
        front = snap.planes[0]
        vertical = [
            e for e in snap.edges if e.type == "line" and e.length is not None and abs(e.length - 0.008) <= UM
        ]
        assert len(vertical) == 4
        fillet = live.call(
            session,
            document,
            "fillet",
            {"edges": [handle_of(snap, e.ref) for e in vertical], "radius": {"value": 2, "unit": "mm"}},
        )
        made.append(fillet["feature"])
        states.append(live.snapshot(session, document))
        snap = states[-1]
        top = next(
            f
            for f in snap.faces
            if f.type == "plane"
            and f.normal is not None
            and _close(f.normal, front.normal, 1e-9)
            and f.area is not None
            and f.area > 1e-4
        )
        y = _cross(top.normal, top.sketch_x)
        middle = _at(front.origin, front.sketch_x, front.normal, 0.010, 0.005, 0.008)
        rel = [middle[i] - top.point[i] for i in range(3)]
        u = sum(rel[i] * top.sketch_x[i] for i in range(3)) * 1000
        v = sum(rel[i] * y[i] for i in range(3)) * 1000
        cut = live.call(
            session,
            document,
            "sketch_extrude_cut",
            {
                "plane": handle_of(snap, top.ref),
                "profile": {"unit": "mm", "segments": [{"type": "circle", "center": [u, v], "radius": 3}]},
                "depth": {"value": 3, "unit": "mm"},
                "direction": "normal",
                "end": "blind",
            },
        )
        made.append(cut["feature"])
        states.append(live.snapshot(session, document))
        snap = states[-1]
        rims = [
            e
            for e in snap.edges
            if e.type == "circle" and e.radius is not None and abs(e.radius - 0.003) <= UM
        ]
        rim = max(
            rims, key=lambda e: sum(e.center[i] * front.normal[i] for i in range(3))
        )  # the one at the top
        chamfer = live.call(
            session,
            document,
            "chamfer",
            {"edges": [handle_of(snap, rim.ref)], "distance": {"value": 0.5, "unit": "mm"}},
        )
        made.append(chamfer["feature"])
        states.append(live.snapshot(session, document))

        for k in range(len(made) - 1, -1, -1):
            live._request("live_delete_feature", {"document": key, "feature": made[k]}, timeout=120, pid=pid)
            after = live.snapshot(session, document)
            assert _state(after) == _state(states[k]), (
                f"deleting step {k + 1} did not give back the state before it"
            )
    finally:
        live.close()


def _block(live, session, document):
    """A 20 x 10 x 8 mm block on the front plane, made the way a person's part would be."""
    live.call(
        session,
        document,
        "sketch_extrude_boss",
        {
            "plane": "P1",
            "profile": _rectangle(0, 0, 20, 10),
            "depth": {"value": 8, "unit": "mm"},
            "direction": "normal",
            "end": "blind",
        },
    )
    return live.snapshot(session, document)


def _automatic(live, session, document, snap, steps, tmp_path, goal=""):
    from solidseas.ai.prompts import parse_plan
    from solidseas_app.assistant.automatic import start_run
    from solidseas_app.assistant.run import AutomaticRun, SessionTarget

    plan = parse_plan(json.dumps({"vocabulary": 1, "steps": steps}), build_model_summary(snap), goal=goal)
    target = SessionTarget(live, session, document)
    start = start_run(target, plan, confirmed=True, runs_folder=str(tmp_path / "runs"))
    return AutomaticRun(live, session, document, start, baseline=target.snapshot)


def test_an_automatic_run_carries_out_checks_and_reverts_its_plan(exe, own, tmp_path):
    from solidseas_app.assistant.run import differences

    pid, key = own
    live = _live(exe, tmp_path)
    session = LiveSession(pid, "test", ())
    document = LiveDocument(key, key, "part", "")
    try:
        live.snapshot(session, document)
        baseline = _block(live, session, document)
        summary = build_model_summary(baseline)
        front = baseline.planes[0]

        def handle(ref):
            return next(h for h in summary.handles.handles() if summary.handles.resolve(h).ref == ref)

        vertical = [e for e in baseline.edges if e.type == "line" and abs((e.length or 0) - 0.008) <= UM]
        top = next(f for f in baseline.faces if f.normal is not None and _close(f.normal, front.normal, 1e-9))
        boss_ref = next(f.ref for f in baseline.features if f.type == "Extrusion")
        depth = next(
            h for h in summary.handles.handles() if summary.handles.resolve(h).ref == f"dim:{boss_ref}:D1"
        )
        y = _cross(top.normal, top.sketch_x)
        middle = _at(front.origin, front.sketch_x, front.normal, 0.010, 0.005, 0.008)
        rel = [middle[i] - top.point[i] for i in range(3)]
        u = sum(rel[i] * top.sketch_x[i] for i in range(3)) * 1000
        v = sum(rel[i] * y[i] for i in range(3)) * 1000
        steps = [
            {
                "op": "fillet",
                "args": {"edges": [handle(e.ref) for e in vertical], "radius": {"value": 1, "unit": "mm"}},
            },
            {
                "op": "sketch_extrude_boss",
                "args": {
                    "plane": handle(top.ref),
                    "profile": {
                        "unit": "mm",
                        "segments": [{"type": "circle", "center": [u, v], "radius": 2}],
                    },
                    "depth": {"value": 3, "unit": "mm"},
                    "direction": "normal",
                    "end": "blind",
                },
            },
            {"op": "set_dimension", "args": {"dimension": depth, "value": {"value": 10, "unit": "mm"}}},
            {"op": "set_property", "args": {"name": "Finish", "value": "black", "scope": "file"}},
        ]
        run = _automatic(live, session, document, baseline, steps, tmp_path)
        outcome = run.run()
        assert outcome.status == "done" and outcome.steps_done == 4, outcome.message
        lines = [json.loads(line) for line in open(run.journal.path, encoding="utf-8")]
        done = [line for line in lines if line["event"] == "step_done"]
        assert [d["undo_recorded"] for d in done] == [
            True,
            True,
            True,
            False,
        ]  # a property: no entry (answer 2)
        after = live.snapshot(session, document)
        assert after.custom_properties.get("Finish") == "black"
        assert any(f.type == "Fillet" for f in after.features) and after.box_max is not None
        assert list(tmp_path.glob("live-lock-*.txt")) == [] and list(tmp_path.glob("live-undo-*.txt")) == []
        assert run.revert() == []
        assert differences(baseline, live.snapshot(session, document)) == []
        assert not run.start.writer.held
    finally:
        live.close()


def test_an_automatic_step_solidworks_cannot_make_is_taken_back(exe, own, tmp_path):
    from solidseas_app.assistant.run import differences

    pid, key = own
    live = _live(exe, tmp_path)
    session = LiveSession(pid, "test", ())
    document = LiveDocument(key, key, "part", "")
    try:
        live.snapshot(session, document)
        baseline = _block(live, session, document)
        summary = build_model_summary(baseline)
        vertical = [e for e in baseline.edges if e.type == "line" and abs((e.length or 0) - 0.008) <= UM]
        handles = [
            h
            for h in summary.handles.handles()
            if summary.handles.resolve(h).ref in {e.ref for e in vertical}
        ]
        steps = [
            # a radius longer than the block itself: SOLIDWORKS makes no fillet
            {"op": "fillet", "args": {"edges": handles, "radius": {"value": 25, "unit": "mm"}}},
            {"op": "set_property", "args": {"name": "Finish", "value": "black", "scope": "file"}},
        ]
        run = _automatic(live, session, document, baseline, steps, tmp_path)
        outcome = run.run()
        assert outcome.status == "failed" and outcome.steps_done == 0, outcome.message
        assert differences(baseline, live.snapshot(session, document)) == []
        assert "Finish" not in live.snapshot(session, document).custom_properties
        run.keep()
    finally:
        live.close()


def test_a_chat_builds_through_the_mcp_server(exe, own, tmp_path, monkeypatch):
    """What Claude Desktop or Claude Code does through ``--mcp``: list, read, plan, run,
    revert; the session list asks about SolidSeas' own SOLIDWORKS only."""
    from solidseas.ai.factory import AISettings
    from solidseas_app.assistant.mcp_server import McpServer

    pid, key = own
    # this process writes the run's safety copy too, so it uses the test's folder as well
    monkeypatch.setenv("SOLIDSEAS_CACHE_DIR", str(tmp_path))
    env = {**os.environ, "SOLIDSEAS_CACHE_DIR": str(tmp_path)}
    live = BridgeSessions(lambda: Bridge(exe, env=env), include_solidseas=True, pids=(pid,))
    asked = []
    server = McpServer(
        lambda: live,
        confirm=lambda title, text: asked.append(text) or False,
        settings=AISettings,
        extensions_on=lambda: frozenset({"cad-bridge"}),  # the bridge is this test's own
    )

    def call(name, arguments):
        reply = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        result = reply["result"]
        assert result["isError"] is False, result["content"][0]["text"]
        return result["structuredContent"]

    try:
        sessions = call("cad_sessions", {})["sessions"]
        assert [s["session"] for s in sessions] == [pid]
        (document,) = [d["document"] for d in sessions[0]["documents"]]
        assert call("read_part", {"document": document})["summary"]["solid_bodies"] == 0
        boss = {
            "op": "sketch_extrude_boss",
            "args": {
                "plane": "P1",
                "profile": _rectangle(0, 0, 20, 10),
                "depth": {"value": 8, "unit": "mm"},
                "direction": "normal",
                "end": "blind",
            },
        }
        first = call("run_plan", {"document": document, "plan": {"vocabulary": 1, "steps": [boss]}})
        assert first["status"] == "done", first["message"]
        summary = first["summary"]
        assert summary["solid_bodies"] == 1 and summary["volume_mm3"] == pytest.approx(1600, rel=1e-6)
        vertical = [
            e["handle"] for e in summary["edges"] if e["type"] == "line" and abs(e["length_mm"] - 8) < 1e-3
        ]
        fillet = {"op": "fillet", "args": {"edges": vertical, "radius": {"value": 1, "unit": "mm"}}}
        second = call("run_plan", {"document": document, "plan": {"vocabulary": 1, "steps": [fillet]}})
        assert second["status"] == "done" and second["kept_before"] == [first["run"]]
        assert second["summary"]["volume_mm3"] < 1600
        reverted = call("revert_run", {"run": second["run"]})
        assert reverted["status"] == "reverted" and reverted["summary"]["volume_mm3"] == pytest.approx(
            1600, rel=1e-6
        )
        depth = next(
            d["handle"] for d in reverted["summary"]["dimensions"] if abs(d["value"]["value"] - 8) < 1e-6
        )
        set_depth = {
            "op": "set_dimension",
            "args": {"dimension": depth, "value": {"value": 12, "unit": "mm"}},
        }
        declined = call("run_plan", {"document": document, "plan": {"vocabulary": 1, "steps": [set_depth]}})
        assert declined["status"] == "declined" and "set_dimension" in asked[0]
        assert call("read_part", {"document": document})["summary"]["volume_mm3"] == pytest.approx(
            1600, rel=1e-6
        )
    finally:
        server.close()
