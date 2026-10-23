"""CadQuery models recorded with CadQuery itself, translated, and held to CadQuery's own
geometry: each model is built in CadQuery while ``solidseas.nativewrite.cqrecorder`` records
it, translated by ``solidseas.nativewrite.cqrecording``, and the IR it gives is built again in
CadQuery from the IR alone (sketches, then extrusions and cuts as the IR says them). The two
solids must remove and keep exactly the same material: the same volume, bounding box and
number of bodies, and no volume in either that the other lacks. Models the native part writer
takes are then written as parts and read back.

CadQuery is an optional extra, so this file skips where it is not installed (as in CI).
Checked with CadQuery 2.8.0 (OCCT 7.9.3).
"""

import json

import pytest

cq = pytest.importorskip("cadquery")

from solidseas.formats.solidworks import open_document  # noqa: E402
from solidseas.nativewrite import cqrecorder, ir  # noqa: E402
from solidseas.nativewrite import cqrecording as R  # noqa: E402

W = cq.Workplane
THROUGH = 10_000.0  # millimetres: as far as a cut through all goes here


def ir_solid(doc: ir.Document):
    """The IR's material as a CadQuery shape, in millimetres, from the IR alone."""
    sketches: dict[str, ir.Sketch] = {}
    bodies: list = []
    for f in doc.features:
        if isinstance(f, ir.Sketch):
            sketches[f.id] = f
            continue
        sk = sketches[f.sketch]
        origin = cq.Vector(*sk.plane.origin) * 1000
        x, y = cq.Vector(*sk.plane.x_dir), cq.Vector(*sk.plane.y_dir)
        normal = x.cross(y)
        points = {p.id: (p.x * 1000, p.y * 1000) for p in sk.points}

        def at(u, v, origin=origin, x=x, y=y):
            return origin + x * u + y * v

        wires, after = [], {}
        for c in sk.curves:
            if c.kind == "circle":
                wires.append(cq.Wire.makeCircle(c.radius * 1000, at(*points[c.points[0]]), normal))
            else:
                after[c.points[0]] = c.points[1]
        while after:
            loop = [next(iter(after))]
            while after[loop[-1]] != loop[0]:
                loop.append(after[loop[-1]])
            for p in loop:
                del after[p]
            wires.append(cq.Wire.makePolygon([at(*points[p]) for p in loop + loop[:1]]))
        faces = [cq.Face.makeFromWires(w) for w in wires]

        def inside(a, b):
            return b.Area() > a.Area() and abs(a.intersect(b).Area() - a.Area()) < 1e-9

        regions = []
        for n, outer in enumerate(faces):
            if any(inside(outer, other) for m, other in enumerate(faces) if m != n):
                continue
            holes = [wires[m] for m, inner in enumerate(faces) if m != n and inside(inner, outer)]
            regions.append(cq.Face.makeFromWires(wires[n], holes))
        d = f.depth * 1000
        if f.end == "through_all":
            span = {"midplane": (-THROUGH, THROUGH), "forward": (0, THROUGH), "reverse": (-THROUGH, 0)}
        else:
            span = {"midplane": (-d / 2, d / 2), "forward": (0, d), "reverse": (-d, 0)}
        lo, hi = span[f.direction]
        prisms = [
            cq.Solid.extrudeLinear(r.moved(cq.Location(normal * lo)), normal * (hi - lo)) for r in regions
        ]
        if f.operation == "new_body":
            bodies += prisms
        elif f.operation == "join":
            bodies = list(cq.Compound.makeCompound(bodies + prisms).fuse().Solids())
        else:
            shape = cq.Compound.makeCompound(bodies)
            for p in prisms:
                shape = shape.cut(p)
            bodies = list(shape.Solids())
    return cq.Compound.makeCompound(bodies)


def record(build, **options):
    with cqrecorder.Recorder() as rec:
        model = build()
    recording = rec.recording(model, **options)
    return model, recording, R.to_ir(recording)


MODELS = {
    # what the native part writer takes
    "plate with a hole": lambda: (
        W("XY")
        .rect(40, 30, centered=False)
        .extrude(10)
        .faces(">Z")
        .workplane(centerOption="CenterOfMass")
        .hole(8)
    ),
    "centred rectangle": lambda: W("XY").rect(40, 30).extrude(10),
    "box on the plane with a hole": lambda: (
        W("XY").box(40, 30, 10, centered=(True, True, False)).faces(">Z").workplane().hole(6)
    ),
    "circle cut through all": lambda: (
        W("XY").rect(40, 30).extrude(10).faces(">Z").workplane().circle(4).cutThruAll()
    ),
    "two boxes apart": lambda: (
        W("XY").rect(10, 10, centered=False).extrude(5).center(20, 0).rect(10, 10, centered=False).extrude(3)
    ),
    "hole from the bottom": lambda: (
        W("XY").rect(40, 30).extrude(10).faces("<Z").workplane().center(5, 5).hole(6)
    ),
    "hole at a point": lambda: (
        W("XY").rect(40, 30, centered=False).extrude(10).faces(">Z").workplane().moveTo(30, 20).hole(5)
    ),
    "hole at a face's centre": lambda: W("XY").rect(40, 30, centered=False).extrude(10).faces(">Z").hole(8),
    "front plane": lambda: W("front").rect(40, 30).extrude(10),
    "a Plane of its own": lambda: W(cq.Plane((1, 2, 0), (1, 0, 0), (0, 0, 1))).rect(10, 10).extrude(5),
    "kept apart": lambda: (
        W("XY")
        .rect(10, 10, centered=False)
        .extrude(5)
        .center(20, 0)
        .rect(10, 10, centered=False)
        .extrude(3, combine=False)
    ),
    "a large part": lambda: (
        W("XY")
        .rect(4000, 3000, centered=False)
        .extrude(100)
        .faces(">Z")
        .workplane(centerOption="CenterOfMass")
        .hole(80)
    ),
    "a small part": lambda: (
        W("XY")
        .rect(0.4, 0.3, centered=False)
        .extrude(0.1)
        .faces(">Z")
        .workplane(centerOption="CenterOfMass")
        .hole(0.08)
    ),
    # translated, and refused by the writer for now
    "two holes": lambda: (
        W("XY").rect(40, 30).extrude(10).faces(">Z").workplane().pushPoints([(-10, 0), (10, 0)]).hole(5)
    ),
    "XZ plane": lambda: W("XZ").rect(40, 30).extrude(10),
    "YZ plane": lambda: W("YZ").rect(40, 30, centered=False).extrude(10),
    "back plane": lambda: W("back").rect(40, 30, centered=False).extrude(10),
    "right plane": lambda: W("right").rect(40, 30).extrude(10),
    "ZY plane": lambda: W("ZY").rect(40, 30, centered=False).extrude(10),
    "box about the plane": lambda: W("XY").box(40, 30, 10),
    "extruded the other way": lambda: W("XY").rect(40, 30).extrude(-10),
    "extruded both ways": lambda: W("XY").rect(40, 30).extrude(5, both=True),
    "pocket": lambda: W("XY").rect(40, 30).extrude(10).faces(">Z").workplane().rect(10, 10).cutBlind(-3),
    "pocket by extrude": lambda: (
        W("XY").rect(40, 30).extrude(10).faces(">Z").workplane().rect(10, 10).extrude(-3, combine="cut")
    ),
    "ring": lambda: W("XY").rect(40, 30).circle(5).extrude(10),
    "offset workplane": lambda: W("XY").workplane(offset=5).rect(20, 20).extrude(4),
    "inverted face": lambda: (
        W("XY").rect(40, 30).extrude(10).faces(">Z").workplane(invert=True).rect(10, 10).extrude(2)
    ),
    "joined boxes": lambda: (
        W("XY").rect(10, 10, centered=False).extrude(5).center(10, 0).rect(10, 10, centered=False).extrude(3)
    ),
    "boxes at points": lambda: (
        W("XY").pushPoints([(0, 0), (30, 0)]).box(10, 10, 4, centered=(True, True, False))
    ),
    "hole from a side": lambda: W("XY").rect(40, 30).extrude(10).faces(">X").workplane().hole(4),
    "cut from the middle": lambda: (
        W("XY").rect(40, 30).extrude(10).faces(">Z").workplane(offset=-5).rect(6, 6).cutThruAll()
    ),
    "tag and end": lambda: (
        W("XY")
        .rect(40, 30)
        .extrude(10)
        .tag("base")
        .faces(">Z")
        .workplane()
        .hole(5)
        .end(3)
        .faces("<Z")
        .workplane()
        .rect(4, 4)
        .cutThruAll()
    ),
    "second hole": lambda: (
        W("XY")
        .rect(40, 30, centered=False)
        .extrude(10)
        .faces(">Z")
        .workplane(centerOption="CenterOfMass")
        .hole(8)
        .faces(">Z")
        .workplane(centerOption="CenterOfMass")
        .center(10, 0)
        .hole(4)
    ),
    "hole partly off the part": lambda: (
        W("XY").rect(40, 30).extrude(10).faces(">Z").workplane().center(19, 0).hole(6)
    ),
    "tops of two boxes": lambda: (
        W("XY")
        .rect(10, 10, centered=False)
        .extrude(5)
        .center(20, 0)
        .rect(10, 10, centered=False)
        .extrude(5)
        .faces(">Z")
        .workplane(centerOption="CenterOfMass")
        .rect(2, 2)
        .extrude(1)
    ),
}
WRITTEN = {
    "plate with a hole",
    "centred rectangle",
    "box on the plane with a hole",
    "circle cut through all",
    "two boxes apart",
    "hole from the bottom",
    "hole at a point",
    "hole at a face's centre",
    "front plane",
    "a Plane of its own",
    "kept apart",
    "a large part",
    "a small part",
}
NOT_TRANSLATED = {
    "fillet": (lambda: W("XY").rect(40, 30).extrude(10).edges("|Z").fillet(2), "fillet(2)"),
    "hole from inside": (
        lambda: W("XY").rect(40, 30).extrude(10).faces(">Z").workplane(offset=-5).hole(4),
        "hole(4)",
    ),
    "polygon": (lambda: W("XY").polygon(6, 20).extrude(5), "polygon(6, 20)"),
    "union": (lambda: W("XY").box(10, 10, 10).union(W("XY").center(20, 0).box(10, 10, 10)), "union("),
    "cut by operator": (lambda: W("XY").box(10, 10, 10) - W("XY").box(2, 2, 20), "- <workplane"),
    "rarray": (
        lambda: W("XY").box(40, 30, 10).faces(">Z").workplane().rarray(10, 10, 2, 2).hole(2),
        "rarray(",
    ),
    "sketch": (lambda: W("XY").sketch().rect(10, 10).finalize().extrude(5), "extrude(5)"),
    "taper": (lambda: W("XY").rect(10, 10).extrude(5, taper=5), "extrude(5, taper=5)"),
}


@pytest.mark.parametrize("name", list(MODELS))
def test_the_translation_keeps_cadquery_s_material(name):
    model, _, doc = record(MODELS[name], name="model")
    assert not [f for f in doc.features if isinstance(f, ir.Unsupported)]
    real = cq.Compound.makeCompound([s for o in model.vals() for s in o.Solids()])
    made = ir_solid(doc)
    volume = real.Volume()
    assert made.Volume() == pytest.approx(volume, rel=1e-9)
    assert real.cut(made).Volume() + made.cut(real).Volume() <= 1e-9 * volume
    assert len(made.Solids()) == len(real.Solids())
    a, b = real.BoundingBox(), made.BoundingBox()
    assert (a.xmin, a.ymin, a.zmin, a.xmax, a.ymax, a.zmax) == pytest.approx(
        (b.xmin, b.ymin, b.zmin, b.xmax, b.ymax, b.zmax), abs=1e-6
    )


@pytest.mark.parametrize("name", sorted(WRITTEN))
def test_models_the_native_writer_takes_become_parts(name):
    gen = pytest.importorskip("solidseas.nativewrite.generate")
    _, _, doc = record(MODELS[name], name="model", properties={"PartNo": "SS-1001"})
    plan = gen.plan(doc)
    assert list(plan.left_out) == []
    with open_document(gen.write_part(doc), name="model.SLDPRT") as part:
        assert part.doc_type == "part"
        props = {p["name"]: p["value"] for p in part.summary(include=("properties",))["properties"]}
    assert props == {"PartNo": "SS-1001"}


def test_the_other_models_are_refused_by_the_writer_with_its_reasons():
    gen = pytest.importorskip("solidseas.nativewrite.generate")
    for name in sorted(set(MODELS) - WRITTEN):
        _, _, doc = record(MODELS[name])
        with pytest.raises(gen.NativeWriteUnsupported):
            gen.plan(doc)


@pytest.mark.parametrize("name", list(NOT_TRANSLATED))
def test_what_is_not_translated_is_named(name):
    build, called = NOT_TRANSLATED[name]
    _, _, doc = record(build)
    entries = [f"{f.name}: {f.reason}" for f in doc.features if isinstance(f, ir.Unsupported)]
    assert entries and any(e.startswith(called) for e in entries), entries


def test_the_recording_reads_back_from_its_file(tmp_path):
    model, recording, doc = record(MODELS["a Plane of its own"], name="block", units="mm")
    path = tmp_path / "block.json"
    path.write_text(R.to_json(recording), encoding="utf-8")
    assert R.read_ir(path) == doc
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["cadquery"] == cq.__version__ and data["steps"][0]["call"] == "Workplane"
    assert data["steps"][0]["args"][0] == {"plane": {"origin": [1.0, 2.0, 0.0], "x_dir": [1.0, 0.0, 0.0],
                                                     "normal": [0.0, 0.0, 1.0]}}  # fmt: skip


def test_the_recorder_puts_cadquery_s_workplane_back():
    before = {k: v for k, v in vars(W).items() if callable(v)}
    with cqrecorder.Recorder():
        assert vars(W)["extrude"] is not before["extrude"]
        W("XY").box(1, 1, 1)
    assert {k: v for k, v in vars(W).items() if callable(v)} == before
    assert not hasattr(W.extrude, "__solidseas_recorded__")
