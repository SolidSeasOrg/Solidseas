"""A part held in memory, standing in for SOLIDWORKS in Automatic mode's tests
(tests/test_assistant_run.py, tests/test_assistant_automatic.py): a 20 x 10 x 8 mm block,
the plan steps the tests use, and :class:`FakeLive`, which the run's operations change as
SOLIDWORKS would and which records what it was asked."""

from __future__ import annotations

import dataclasses
import itertools
import json
import math

from solidseas.ai.context import (
    Dimension,
    Edge,
    Face,
    Feature,
    PartSnapshot,
    RefPlane,
    build_model_summary,
)
from solidseas.ai.prompts import parse_plan
from solidseas_app.assistant.session import LiveDocument, LiveSession, SessionList

FRONT, TOP, RIGHT = "UFAx", "UFAy", "UFAz"
SKETCH, BOSS = "U2sx", "Qm9z"
TOP_FACE = "RmEx"
VERTICAL = ("RTE=", "RTI=", "RTM=", "RTQ=")
TOP_EDGE = "RTU="
SESSION = LiveSession(4242, "2024 SP1.0", ())
DOCUMENT = LiveDocument("C:\\work\\block.SLDPRT", "block.SLDPRT", "part", "C:\\work\\block.SLDPRT")
_pids = itertools.count(910_000)


def block() -> PartSnapshot:
    """A 20 x 10 x 8 mm block: a sketch on the front plane, extruded."""
    corners = [(0, 0), (0.02, 0), (0.02, 0.01), (0, 0.01)]
    return PartSnapshot(
        length_unit="mm",
        planes=(
            RefPlane(FRONT, "Front Plane", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)),
            RefPlane(TOP, "Top Plane", (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0)),
            RefPlane(RIGHT, "Right Plane", (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, -1.0)),
        ),
        features=(
            Feature(SKETCH, "Sketch1", "ProfileFeature", parents=(FRONT,)),
            Feature(BOSS, "Boss-Extrude1", "Extrusion", parents=(SKETCH,)),
        ),
        dimensions=(
            Dimension(f"dim:{SKETCH}:D1", "D1@Sketch1", SKETCH, "linear", 0.02),
            Dimension(f"dim:{SKETCH}:D2", "D2@Sketch1", SKETCH, "linear", 0.01),
            Dimension(f"dim:{BOSS}:D1", "D1@Boss-Extrude1", BOSS, "linear", 0.008),
        ),
        faces=(
            Face(TOP_FACE, "plane", 0.0002, (0.0, 0.0, 1.0), (0.0, 0.0, 0.008), sketch_x=(1.0, 0.0, 0.0)),
        ),
        edges=tuple(
            Edge(ref, "line", (x, y, 0.0), (x, y, 0.008), length=0.008)
            for ref, (x, y) in zip(VERTICAL, corners, strict=True)
        )
        + (Edge(TOP_EDGE, "line", (0.0, 0.0, 0.008), (0.02, 0.0, 0.008), length=0.02),),
        solid_bodies=1,
        volume=1.6e-6,
        box_min=(0.0, 0.0, 0.0),
        box_max=(0.02, 0.01, 0.008),
        configurations=("Default",),
        active_configuration="Default",
        custom_properties={"Description": "block"},
        configuration_properties={"Default": {}},
        material="6061 Alloy",
    )


def plan_of(snap: PartSnapshot, *steps: dict):
    return parse_plan(json.dumps({"vocabulary": 1, "steps": list(steps)}), build_model_summary(snap), goal="")


FILLET = {"op": "fillet", "args": {"edges": ["E1", "E2", "E3", "E4"], "radius": {"value": 1, "unit": "mm"}}}
DEPTH = {"op": "set_dimension", "args": {"dimension": "D3", "value": {"value": 9, "unit": "mm"}}}
FINISH = {"op": "set_property", "args": {"name": "Finish", "value": "black", "scope": "file"}}


class FakeLive:
    """The part in memory, changed by the run's operations as SOLIDWORKS would change it.
    ``effects`` overrides what an operation does: a function of (state, args) returning
    (new state, reply), or raising."""

    def __init__(self, state: PartSnapshot, effects: dict | None = None) -> None:
        self.state = state
        self.calls: list[tuple] = []
        self.info = {"active": True, "editing_sketch": False}
        self.effects = {**self.default_effects(), **(effects or {})}
        self.made: dict[str, PartSnapshot] = {}
        self.properties_before: list[PartSnapshot] = []
        self.after_operation = None  # a hook: what the person does once an operation returns
        self.renamed: dict[str, str] = {}  # references SOLIDWORKS has given anew: old to new

    # ----------------------------------------------------------------- what the run calls
    def snapshot(self, session, document):
        return self.state

    def document_info(self, session, document):
        return dict(self.info)

    def operation(self, session, document, op, args, *, undo_name=None, lock=False):
        self.calls.append(("operation", op, args, undo_name, lock))
        new, reply = self.effects[op](self.state, args)
        reply = {"undo_recorded": undo_name is not None, **reply}
        if isinstance(reply.get("feature"), str):
            self.made[reply["feature"]] = self.state
        self.state = new
        if self.after_operation is not None:
            self.after_operation(self)
        return reply

    def current_refs(self, session, document, refs):
        self.calls.append(("current_refs", tuple(refs)))
        present = {
            e.ref
            for group in (
                self.state.features,
                self.state.dimensions,
                self.state.faces,
                self.state.edges,
                self.state.planes,
                self.state.axes,
            )
            for e in group
        }
        return {r: (self.renamed.get(r, r) if r in present or r in self.renamed else None) for r in refs}

    def delete_feature(self, session, document, feature):
        self.calls.append(("delete", feature))
        self.state = self.made.pop(feature)
        return {"deleted": True}

    def restore_property(self, session, document, name, scope, value):
        self.calls.append(("restore_property", name, scope, value))
        props = dict(self.state.custom_properties)
        if value is None:
            props.pop(name, None)
        else:
            props[name] = value
        self.state = dataclasses.replace(self.state, custom_properties=props)
        return {"value": value}

    # ----------------------------------------------------------------- SOLIDWORKS, roughly
    @staticmethod
    def default_effects():
        def fillet(state, args):
            r = args["radius"]
            fillet = Feature("RmlsMQ==", "Fillet1", "Fillet", parents=(BOSS,))
            loss = len(args["edges"]) * (1 - math.pi / 4) * r * r * 0.008
            edges = tuple(e for e in state.edges if e.ref not in args["edges"])
            new = dataclasses.replace(
                state, features=state.features + (fillet,), edges=edges, volume=state.volume - loss
            )
            return new, {"feature": fillet.ref, "name": "Fillet1", "type": "Fillet"}

        def set_dimension(state, args):
            dims = tuple(
                dataclasses.replace(d, value=args["value"]) if d.ref == args["dimension"] else d
                for d in state.dimensions
            )
            depth = args["value"] if args["dimension"] == f"dim:{BOSS}:D1" else None
            new = dataclasses.replace(state, dimensions=dims)
            if depth is not None:
                new = dataclasses.replace(
                    new, box_max=(0.02, 0.01, depth), volume=state.volume * depth / state.box_max[2]
                )
            return new, {"before": None, "after": args["value"], "rebuilt": True}

        def set_property(state, args):
            props = dict(state.custom_properties)
            before = props.get(args["name"])
            props[args["name"]] = args["value"]
            return dataclasses.replace(state, custom_properties=props), {
                "before": before,
                "after": args["value"],
            }

        def suppression(wanted):
            def change(state, args):
                features = tuple(
                    dataclasses.replace(f, suppressed=wanted) if f.ref in args["features"] else f
                    for f in state.features
                )
                return dataclasses.replace(state, features=features), {"features": []}

            return change

        return {
            "fillet": fillet,
            "set_dimension": set_dimension,
            "set_property": set_property,
            "suppress": suppression(True),
            "unsuppress": suppression(False),
        }

    def ops(self) -> list[str]:
        """What changed or was asked of the part, in order, without the reference lookups."""
        return [c[1] if c[0] == "operation" else c[0] for c in self.calls if c[0] != "current_refs"]


class WindowLive(FakeLive):
    """The stand-in part as the window reaches it: one SOLIDWORKS session with the block."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.session = LiveSession(4242, "2024 SP1.0", (DOCUMENT,))

    def list(self):
        return SessionList((self.session,))

    def write_checkpoint(self, session, document, path):
        self.calls.append(("checkpoint", path))
        with open(path, "wb") as f:
            f.write(b"safety copy")
        return {"path": path}
