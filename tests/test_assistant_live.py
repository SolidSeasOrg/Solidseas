"""The assistant's live SOLIDWORKS (``solidseas_app.assistant.live_sessions``), against a
stand-in bridge that answers from a table and records what it was asked. Nothing here
starts a bridge or reaches a SOLIDWORKS; ``tests/test_swapi_live.py`` does, opt-in,
against SolidSeas' own instance."""

from __future__ import annotations

import math
import os

import pytest

from solidseas.ai.context import build_model_summary
from solidseas.swapi.bridge import BridgeExitedError, BridgeRequestError
from solidseas.swapi.live import LiveError
from solidseas_app.assistant import live_sessions
from solidseas_app.assistant.live_sessions import (
    NONE_RUNNING,
    BridgeSessions,
    bridge_arguments,
    snapshot_from,
    version_name,
)
from solidseas_app.assistant.session import LiveDocument, LiveSession, NoSessions

FRONT, TOP, RIGHT = "UGxhbmUx", "UGxhbmUy", "UGxhbmUz"
SKETCH, BOSS = "U2tldGNoMQ==", "Qm9zczE="
TOP_FACE, SIDE_FACE = "RmFjZTE=", "RmFjZTI="
EDGE = "RWRnZTE="
PATH = "C:\\work\\bracket.SLDPRT"


def raw_snapshot(**changes) -> dict:
    raw = {
        "document": PATH,
        "title": "bracket.SLDPRT",
        "path": PATH,
        "type": "part",
        "length_unit": "mm",
        "active_configuration": "Default",
        "configurations": ["Default"],
        "planes": [
            {
                "ref": FRONT,
                "name": "Front Plane",
                "origin": [0, 0, 0],
                "sketch_x": [1, 0, 0],
                "normal": [0, 0, 1],
            },
            {
                "ref": TOP,
                "name": "Top Plane",
                "origin": [0, 0, 0],
                "sketch_x": [1, 0, 0],
                "normal": [0, 1, 0],
            },
            {
                "ref": RIGHT,
                "name": "Right Plane",
                "origin": [0, 0, 0],
                "sketch_x": [0, 0, -1],
                "normal": [1, 0, 0],
            },
        ],
        "axes": [],
        "features": [
            {
                "ref": SKETCH,
                "name": "Sketch1",
                "type": "ProfileFeature",
                "suppressed": False,
                "parents": [FRONT],
            },
            {
                "ref": BOSS,
                "name": "Boss-Extrude1",
                "type": "Extrusion",
                "suppressed": False,
                "parents": [SKETCH],
            },
        ],
        "dimensions": [
            {
                "ref": f"dim:{SKETCH}:D1",
                "name": "D1@Sketch1",
                "feature": SKETCH,
                "kind": "linear",
                "value": 0.04,
            },
            {
                "ref": f"dim:{BOSS}:D1",
                "name": "D1@Boss-Extrude1",
                "feature": BOSS,
                "kind": "linear",
                "value": 0.01,
            },
        ],
        "faces": [
            {
                "ref": TOP_FACE,
                "type": "plane",
                "area": 0.0008,
                "point": [0, 0, 0.01],
                "sketch_x": [1, 0, 0],
                "normal": [0, 0, 1],
            },
            {
                "ref": SIDE_FACE,
                "type": "plane",
                "area": 0.0004,
                "point": [0, 0, 0],
                "sketch_x": [0, 1, 0],
                "normal": [-1, 0, 0],
            },
        ],
        "edges": [
            {
                "ref": EDGE,
                "type": "line",
                "start": [0, 0, 0.01],
                "end": [0, 0.02, 0.01],
                "length": 0.02,
                "faces": [TOP_FACE, SIDE_FACE],
            },
        ],
        "truncated": False,
        "solid_bodies": 1,
        "volume": 8e-6,
        "box_min": [0, 0, 0],
        "box_max": [0.04, 0.02, 0.01],
        "custom_properties": {"PartNo": "SECRET-123"},
        "configuration_properties": {"Default": {"Finish": "anodised"}},
        "material": "6061 Alloy",
        "equations": [],
    }
    raw.update(changes)
    return raw


SESSIONS = {
    "sessions": [
        {
            "pid": 100,
            "solidseas": False,
            "reachable": True,
            "revision": "32.1.0",
            "documents": [
                {"key": PATH, "title": "bracket.SLDPRT", "path": PATH, "type": "part", "visible": True},
                {
                    "key": "C:\\work\\screw.SLDPRT",
                    "title": "screw.SLDPRT",
                    "path": "C:\\work\\screw.SLDPRT",
                    "type": "part",
                    "visible": False,
                },  # loaded by an assembly, not open in a window
                {"key": "Part1", "title": "Part1", "path": "", "type": "part", "visible": True},
            ],
        },
        {"pid": 200, "solidseas": True, "reachable": True, "revision": "32.1.0", "documents": []},
        {"pid": 300, "solidseas": False, "reachable": False, "note": "administrator"},
    ],
    "attached": None,
}


class StandIn:
    """A started bridge: answers each operation from ``replies`` (a value, a function of the
    arguments, or an exception to raise) and records every request."""

    def __init__(self, replies: dict | None = None) -> None:
        self.replies = dict(replies or {})
        self.sent: list[tuple[str, dict]] = []
        self.alive = True
        self.closed = False

    def request(self, op, args=None, *, timeout=None):
        assert timeout is not None and 0 < timeout <= 600
        self.sent.append((op, dict(args or {})))
        reply = self.replies.get(op, {})
        if isinstance(reply, BaseException):
            raise reply
        if callable(reply):
            return reply(dict(args or {}))
        return reply

    def close(self):
        self.closed = True
        self.alive = False

    def ops(self) -> list[str]:
        return [op for op, _ in self.sent]


def sessions_with(replies: dict | None = None, **kwargs):
    started: list[StandIn] = []

    def factory():
        b = StandIn({"list_sessions": SESSIONS, "live_snapshot": raw_snapshot(), **(replies or {})})
        started.append(b)
        return b

    return BridgeSessions(factory, **kwargs), started


SESSION = LiveSession(100, "2024 SP1.0", (LiveDocument(PATH, "bracket.SLDPRT", "part", PATH),))
DOCUMENT = SESSION.documents[0]


# --------------------------------------------------------------------------- listing
def test_version_names_follow_the_release_year():
    assert version_name("32.1.0") == "2024 SP1.0"
    assert version_name("33.0.0") == "2025 SP0.0"
    assert version_name("") == "?" and version_name(None) == "?" and version_name("beta") == "beta"


def test_the_list_leaves_out_solidseas_own_instances_and_documents_not_in_a_window():
    s, started = sessions_with()
    found = s.list()
    assert [x.pid for x in found.sessions] == [100, 300]
    first = found.sessions[0]
    assert first.version == "2024 SP1.0" and first.note == ""
    assert [d.key for d in first.documents] == [PATH, "Part1"]
    assert first.documents[0] == LiveDocument(PATH, "bracket.SLDPRT", "part", PATH)
    assert "administrator" in found.sessions[1].note and found.sessions[1].documents == ()
    assert started[0].sent == [("list_sessions", {})]


def test_tests_may_list_solidseas_own_instance_in_place_of_a_persons():
    s, _ = sessions_with(include_solidseas=True)
    assert [x.pid for x in s.list().sessions] == [100, 200, 300]


def test_no_solidworks_running_says_so():
    s, _ = sessions_with({"list_sessions": {"sessions": [], "attached": None}})
    found = s.list()
    assert found.sessions == () and found.why_none == NONE_RUNNING


# --------------------------------------------------------------------------- the snapshot
def test_the_snapshot_reads_into_a_part_snapshot_with_handles_for_each_entity():
    snap = snapshot_from(raw_snapshot())
    assert [p.name for p in snap.planes] == ["Front Plane", "Top Plane", "Right Plane"]
    assert snap.planes[2].sketch_x == (0.0, 0.0, -1.0)
    assert [f.type for f in snap.features] == ["ProfileFeature", "Extrusion"]
    assert snap.features[0].parents == (FRONT,)
    assert snap.dimensions[1].value == 0.01 and snap.dimensions[1].feature == BOSS
    assert snap.edges[0].faces == (TOP_FACE, SIDE_FACE) and snap.edges[0].length == 0.02
    assert snap.faces[0].point == (0.0, 0.0, 0.01) and snap.faces[0].sketch_x == (1.0, 0.0, 0.0)
    assert snap.solid_bodies == 1 and snap.box_max == (0.04, 0.02, 0.01)
    assert snap.custom_properties == {"PartNo": "SECRET-123"} and snap.material == "6061 Alloy"
    summary = build_model_summary(snap)
    assert summary.handles.resolve("P1").ref == FRONT and summary.handles.resolve("E1").ref == EDGE
    assert summary.handles.resolve("D2").ref == f"dim:{BOSS}:D1"
    for private in ("SECRET-123", "bracket", "6061", "Front Plane", "work"):
        assert private not in summary.text, private


def test_whatever_is_malformed_in_a_snapshot_is_left_out():
    raw = raw_snapshot()
    raw["edges"].append({"ref": 7, "type": "line"})  # a reference that is not text
    raw["faces"].append({"ref": "RmFjZTM=", "type": "plane", "normal": [0, "x", 1], "area": "big"})
    raw["dimensions"].append({"ref": "dim:x:D9", "value": None})
    raw["planes"].append({"ref": "UGxhbmU0", "name": "Bad", "origin": [0, 0], "normal": [0, 0, 1]})
    raw["solid_bodies"] = -1
    snap = snapshot_from(raw)
    assert len(snap.edges) == 1 and len(snap.planes) == 3
    face = snap.faces[-1]
    assert face.normal is None and face.area is None
    assert math.isnan(snap.dimensions[-1].value)
    assert snap.solid_bodies == 0


def test_the_snapshot_attaches_once_and_is_kept_for_the_scripts_handles():
    s, started = sessions_with()
    snap = s.snapshot(SESSION, DOCUMENT)
    s.snapshot(SESSION, DOCUMENT)
    assert started[0].ops() == ["live_attach", "live_snapshot", "live_snapshot"]
    assert started[0].sent[0] == ("live_attach", {"pid": 100})
    assert started[0].sent[1] == ("live_snapshot", {"document": PATH})
    assert snap.title == "bracket.SLDPRT"


def test_a_part_too_large_to_describe_is_refused():
    s, _ = sessions_with({"live_snapshot": raw_snapshot(truncated=True)})
    with pytest.raises(LiveError) as caught:
        s.snapshot(SESSION, DOCUMENT)
    assert caught.value.code == "too_large"


# --------------------------------------------------------------------------- a script
def test_a_script_writes_the_safety_copy_then_opens_one_undo_entry(tmp_path):
    s, started = sessions_with(runs_folder=str(tmp_path))
    path = s.begin_script(SESSION, DOCUMENT)
    folder = os.path.dirname(path)
    run_id = os.path.basename(folder)
    assert os.path.dirname(folder) == str(tmp_path) and os.path.isdir(folder)
    assert os.path.basename(path) == f"checkpoint-{run_id}.sldprt"
    assert started[0].sent == [
        ("live_attach", {"pid": 100}),
        ("live_checkpoint", {"document": PATH, "path": path}),
        ("live_begin_undo", {"document": PATH}),
    ]
    s.end_script(SESSION, DOCUMENT)
    assert started[0].sent[-1] == ("live_end_undo", {"document": PATH})


def test_no_run_folder_stays_when_the_safety_copy_fails(tmp_path):
    failed = BridgeRequestError("live_checkpoint: SaveAs3 failed", code="save_failed", op="live_checkpoint")
    s, started = sessions_with({"live_checkpoint": failed}, runs_folder=str(tmp_path))
    with pytest.raises(BridgeRequestError):
        s.begin_script(SESSION, DOCUMENT)
    assert list(tmp_path.iterdir()) == []
    assert "live_begin_undo" not in started[0].ops()  # no undo entry without the safety copy


def test_a_script_changes_a_part_only(tmp_path):
    s, started = sessions_with(runs_folder=str(tmp_path))
    drawing = LiveDocument(
        "C:\\work\\bracket.SLDDRW", "bracket.SLDDRW", "drawing", "C:\\work\\bracket.SLDDRW"
    )
    with pytest.raises(LiveError) as caught:
        s.begin_script(SESSION, drawing)
    assert caught.value.code == "not_a_part" and started == [] and list(tmp_path.iterdir()) == []


def test_an_operation_is_validated_against_the_parts_handles_and_sent_in_si_units():
    s, started = sessions_with({"live_operation": {"feature": "RmlsbGV0MQ==", "name": "Fillet1"}})
    s.snapshot(SESSION, DOCUMENT)
    result = s.call(SESSION, DOCUMENT, "fillet", {"edges": ["E1"], "radius": {"value": 2, "unit": "mm"}})
    assert result["name"] == "Fillet1"
    op, args = started[0].sent[-1]
    assert op == "live_operation"
    assert args == {"document": PATH, "op": "fillet", "edges": [EDGE], "radius": pytest.approx(0.002)}
    s.call(SESSION, DOCUMENT, "set_dimension", {"dimension": "D2", "value": {"value": 0.5, "unit": "in"}})
    assert started[0].sent[-1][1] == {
        "document": PATH,
        "op": "set_dimension",
        "dimension": f"dim:{BOSS}:D1",
        "value": pytest.approx(0.0127),
    }


def test_a_profile_goes_to_the_bridge_in_metres_in_the_planes_frame():
    s, started = sessions_with()
    s.snapshot(SESSION, DOCUMENT)
    profile = {
        "unit": "mm",
        "segments": [
            {"type": "line", "start": [0, 0], "end": [10, 0]},
            {"type": "arc", "center": [10, 5], "start": [10, 0], "end": [10, 10], "direction": "ccw"},
            {"type": "line", "start": [10, 10], "end": [0, 10]},
            {"type": "line", "start": [0, 10], "end": [0, 0]},
            {"type": "circle", "center": [4, 5], "radius": 2},
        ],
    }
    s.call(
        SESSION,
        DOCUMENT,
        "sketch_extrude_cut",
        {"plane": "Fa1", "profile": profile, "direction": "normal", "end": "through_all"},
    )
    op, args = started[0].sent[-1]
    assert op == "live_operation" and args["plane"] == TOP_FACE and args["end"] == "through_all"
    assert "depth" not in args and "profile" not in args
    lines = args["segments"]
    assert lines[0] == {"type": "line", "start": [0.0, 0.0], "end": [pytest.approx(0.01), 0.0]}
    assert lines[1]["type"] == "arc" and lines[1]["clockwise"] is False
    assert lines[1]["center"] == [pytest.approx(0.01), pytest.approx(0.005)]
    assert lines[4] == {
        "type": "circle",
        "center": [pytest.approx(0.004), pytest.approx(0.005)],
        "radius": pytest.approx(0.002),
    }


def test_an_operation_naming_what_the_part_lacks_is_refused_and_nothing_is_sent():
    s, started = sessions_with()
    s.snapshot(SESSION, DOCUMENT)
    sent = len(started[0].sent)
    bad = [
        ("fillet", {"edges": ["E99"], "radius": {"value": 2, "unit": "mm"}}),  # no such edge
        ("fillet", {"edges": ["Fa1"], "radius": {"value": 2, "unit": "mm"}}),  # a face, not an edge
        ("fillet", {"edges": ["E1"], "radius": {"value": float("nan"), "unit": "mm"}}),
        ("fillet", {"edges": ["E1"], "radius": {"value": 2, "unit": "cm"}}),
        ("set_property", {"name": "PartNo", "value": "X", "scope": "file"}),  # a key downstream systems use
        (
            "sketch_extrude_boss",
            {
                "plane": "P1",
                "profile": {"unit": "mm", "segments": [{"type": "line", "start": [0, 0], "end": [10, 0]}]},
                "depth": {"value": 5, "unit": "mm"},
                "direction": "normal",
                "end": "blind",
            },
        ),  # not closed
    ]
    for op, args in bad:
        with pytest.raises(LiveError) as caught:
            s.call(SESSION, DOCUMENT, op, args)
        assert caught.value.code == "refused", op
    with pytest.raises(LiveError) as caught:
        s.call(SESSION, DOCUMENT, "delete_feature", {})
    assert caught.value.code == "unknown_operation"
    assert len(started[0].sent) == sent


def test_an_operation_before_the_part_was_read_names_nothing():
    s, started = sessions_with()
    with pytest.raises(LiveError) as caught:
        s.call(SESSION, DOCUMENT, "fillet", {"edges": ["E1"], "radius": {"value": 2, "unit": "mm"}})
    assert caught.value.code == "no_snapshot" and started == []


def test_queries_go_to_the_live_queries_with_the_arguments_they_take():
    s, started = sessions_with({"live_features": {"features": [{"name": "Sketch1"}]}})
    assert s.call(SESSION, DOCUMENT, "list_features", {"limit": 5}) == {"features": [{"name": "Sketch1"}]}
    assert started[0].sent[-1] == ("live_features", {"document": PATH, "limit": 5})
    s.call(SESSION, DOCUMENT, "mass_properties", {})
    assert started[0].sent[-1] == ("live_mass_properties", {"document": PATH})
    with pytest.raises(LiveError) as caught:
        s.call(SESSION, DOCUMENT, "document_info", {"path": "C:\\elsewhere.sldprt"})
    assert caught.value.code == "refused"
    assert set(live_sessions.QUERY_OPERATIONS.values()) <= {
        "live_document_info",
        "live_features",
        "live_dimensions",
        "live_properties",
        "live_mass_properties",
    }


def test_an_ended_bridge_is_started_again_and_attaches_again():
    s, started = sessions_with()
    s.snapshot(SESSION, DOCUMENT)
    first = started[0]
    first.replies["live_snapshot"] = BridgeExitedError("the bridge was ended: live_snapshot had no reply")
    first.alive = False
    s.snapshot(SESSION, DOCUMENT)  # a new bridge, attached again before it is asked
    assert len(started) == 2 and started[1].ops() == ["live_attach", "live_snapshot"]


def test_close_ends_the_bridge_and_nothing_else():
    s, started = sessions_with()
    s.list()
    s.close()
    assert started[0].closed and started[0].ops() == ["list_sessions"]
    s.close()  # twice is fine


def test_bridge_arguments_cover_every_kind_of_argument():
    s, _ = sessions_with()
    s.snapshot(SESSION, DOCUMENT)
    step = s._validated(SESSION, DOCUMENT, "suppress", {"features": ["F2"]})
    assert bridge_arguments(step) == {"features": [BOSS]}
    step = s._validated(
        SESSION, DOCUMENT, "set_property", {"name": "Finish", "value": "black", "scope": "file"}
    )
    assert bridge_arguments(step) == {"name": "Finish", "value": "black", "scope": "file"}


# --------------------------------------------------------------------------- what the app offers
def test_the_app_offers_no_sessions_where_the_bridge_cannot_run(monkeypatch, never_reach_a_live_solidworks):
    real = never_reach_a_live_solidworks
    monkeypatch.setattr(live_sessions.sys, "platform", "linux")
    assert isinstance(real(), NoSessions) and "Windows" in real().why
    monkeypatch.setattr(live_sessions.sys, "platform", "win32")
    from solidseas.swapi import bridge

    monkeypatch.setattr(bridge, "find_bridge", lambda explicit=None: None)
    offered = real()
    assert isinstance(offered, NoSessions) and "SolidSeas.SwBridge.exe" in offered.why


def test_tests_never_reach_a_live_solidworks():
    offered = live_sessions.default_sessions()
    assert isinstance(offered, NoSessions)
    assert offered.list().sessions == ()
