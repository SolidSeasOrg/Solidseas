"""Write a ``ParametricDocumentIR`` part as a native ``.sldprt``, from a seed part.

This is the first, narrow writer: it does not author new SOLIDWORKS objects.
It takes the native feature records of a seed part that SOLIDWORKS made (the
fixture o02: a corner rectangle on the Front Plane, extruded blind) and writes
the IR's values into them: the rectangle's width and height into the sketch's
points, the depth into ``D1@Boss-Extrude1`` and its dimension's copies, and the
depth's text into the KeyWords mirror. A document that needs anything the seed
does not hold is refused, item by item; with ``allow_partial`` the writer
leaves those items out and lists each one in the report, which a caller must
show the user.

Whether SOLIDWORKS rebuilds such a file into the IR's model is what the PC's
``native-writer`` check measures; :attr:`WriteReport.validated` stays False
here. General authoring (new sketches, relations, dimensions and features) is
Experiment B of ``docs/NATIVE_SLDPRT_WRITER.md``, not this module.
"""

from dataclasses import dataclass, field
from pathlib import Path

from solidseas.nativewrite import ir
from solidseas.nativewrite.container import (
    SourceDocument,
    build_container,
    patch_in_place,
    read_document,
    with_changes,
)

from . import experiments as E
from . import features as F

SEED = E.FIXTURES / "o02_boxA.SLDPRT"
SEED_SKETCH, SEED_EXTRUDE = "Sketch1", "Boss-Extrude1"
SEED_RELATIONS = {"coincident", "horizontal", "vertical"}  # what a corner rectangle from the origin carries
# "drop" leaves the Parasolid partition out, and SOLIDWORKS builds the body from the features
# when it opens the part (candidates c1, b2 and p2 on 2026-10-19); "stale" keeps the seed's,
# which shows the seed's shape until the user rebuilds (a1, a2, p1).
GEOMETRY = ("drop", "stale")


class NativeWriteUnsupported(ValueError):
    """The document needs something this writer cannot write; ``items`` says what."""

    def __init__(self, items: list[str]):
        super().__init__("cannot write: " + "; ".join(items))
        self.items = items


@dataclass
class WriteReport:
    seed: str
    geometry: str
    names: dict[str, str] = field(default_factory=dict)  # IR feature name: native feature name
    written: list[str] = field(default_factory=list)
    left_out: list[str] = field(default_factory=list)
    validated: bool = False
    box_m: tuple[float, float, float] = (0.0, 0.0, 0.0)


def _rectangle(sk: ir.Sketch, problems: list[str]) -> tuple[float, float] | None:
    lines = [c for c in sk.curves if not c.construction]
    if any(c.kind != "line" for c in lines) or len(lines) != 4:
        problems.append(f"{sk.name}: the seed holds one rectangle of four lines, not this profile")
        return None
    pts = {p.id: (p.x, p.y) for p in sk.points}
    pts[ir.ORIGIN] = (0.0, 0.0)
    corners = {pts[q] for c in lines for q in c.points}
    xs, ys = sorted({x for x, _ in corners}), sorted({y for _, y in corners})
    if len(corners) != 4 or len(xs) != 2 or len(ys) != 2 or xs[0] != 0 or ys[0] != 0:
        problems.append(f"{sk.name}: the seed's rectangle has a corner at the origin and sides along x and y")
        return None
    for c in lines:
        (x0, y0), (x1, y1) = pts[c.points[0]], pts[c.points[1]]
        if x0 != x1 and y0 != y1:
            problems.append(f"{sk.name}.{c.id}: not along x or y")
            return None
    return xs[1], ys[1]


def plan(doc: ir.Document) -> tuple[dict, list[str], list[str]]:
    """What the seed can take from ``doc``: ``(values, written, problems)``."""
    ir.validate(doc)
    problems: list[str] = [f"{u.name} ({u.source_type}): {u.reason}" for u in doc.unsupported]
    written: list[str] = []
    for f in doc.features:
        if not isinstance(f, (ir.Sketch, ir.Extrude, ir.Unsupported)):
            problems.append(f"{f.name}: a {f.type} feature is not in the seed")
    sketches = [f for f in doc.features if isinstance(f, ir.Sketch)]
    extrudes = [f for f in doc.features if isinstance(f, ir.Extrude)]
    if len(sketches) != 1 or len(extrudes) != 1:
        problems.append(
            f"the seed holds one sketch and one extrusion, not {len(sketches)} and {len(extrudes)}"
        )
        return {}, written, problems
    sk, ex = sketches[0], extrudes[0]
    if sk.plane.base != "xy":
        problems.append(f"{sk.name}: the seed's sketch is on the Front Plane (xy), not {sk.plane.base!r}")
    size = _rectangle(sk, problems)
    for k in sk.constraints:
        if k.kind not in SEED_RELATIONS:
            problems.append(f"{sk.name}.{k.id}: a {k.kind} relation is not in the seed")
    for d in sk.dimensions:
        problems.append(
            f"{sk.name}.{d.id}: the {d.kind} dimension would be geometry only (the seed has none)"
        )
    if ex.end != "blind" or ex.direction != "forward" or ex.operation != "new_body":
        problems.append(f"{ex.name}: the seed's extrusion is blind, forward, a new body")
    if ex.suppressed or sk.suppressed:
        problems.append("suppressed features are not in the seed")
    prm = {p.name: p for p in doc.parameters}
    if ex.depth_parameter and prm.get(ex.depth_parameter) and prm[ex.depth_parameter].expression:
        expr = prm[ex.depth_parameter].expression
        try:
            float(expr)
        except ValueError:
            problems.append(f"{ex.name}: the depth's expression {expr!r} would be its value only")
    if size is None:
        return {}, written, problems
    written += [
        f"{sk.name} as {SEED_SKETCH}: rectangle {size[0] * 1e3:g} x {size[1] * 1e3:g} mm",
        f"{ex.name} as {SEED_EXTRUDE}: blind {ex.depth * 1e3:g} mm (D1@{SEED_EXTRUDE})",
    ]
    names = {sk.name: SEED_SKETCH, ex.name: SEED_EXTRUDE}
    return {"width": size[0], "height": size[1], "depth": ex.depth, "names": names}, written, problems


def write_sldprt(
    doc: ir.Document,
    *,
    allow_partial: bool = False,
    geometry: str = "drop",
    seed: SourceDocument | str | Path | None = None,
) -> tuple[bytes, WriteReport]:
    """The ``.sldprt`` bytes for ``doc`` and what went into them. Nothing is written to disk."""
    if geometry not in GEOMETRY:
        raise ValueError(f"geometry must be one of {GEOMETRY}")
    values, written, problems = plan(doc)
    if not values or (problems and not allow_partial):
        raise NativeWriteUnsupported(problems)
    src = seed if isinstance(seed, SourceDocument) else read_document(seed or SEED)
    w0, h0, d0 = E.BOX
    feats = src.data(E.FEATURES)
    feats = E.set_depth(feats, values["depth"], mirrors=True)
    feats = move_rectangle(feats, (w0, h0), (values["width"], values["height"]))
    changes: dict[str, bytes | None] = {
        E.FEATURES: feats,
        E.KEYWORDS: E.keywords_depth(src.data(E.KEYWORDS), round(values["depth"] * 1e3, 9)),
    }
    if geometry == "drop":
        changes.update({E.PARTITION: None, E.GHOST: None})
        data = build_container(with_changes(src.members, changes), key=src.key, signatures=src.signatures)
    else:
        data = patch_in_place(src, {k: v for k, v in changes.items() if v is not None})
    report = WriteReport(
        seed=Path(seed).name if isinstance(seed, (str, Path)) else SEED.name,
        geometry=geometry,
        names=values["names"],
        written=written,
        left_out=problems,
        box_m=(values["width"], values["height"], values["depth"]),
    )
    return data, report


def move_rectangle(features: bytes, old: tuple[float, float], new: tuple[float, float]) -> bytes:
    """The seed rectangle's far corner moved: its points, and the depth dimension's witness copies."""
    edits: dict[int, float] = {}
    for p in F.sketch_points(features):
        if p.record != "sgLineHandle":
            continue
        if p.x == old[0]:
            edits[p.offset] = new[0]
        if p.y == old[1]:
            edits[p.offset + 8] = new[1]
    if len(edits) != 4:
        raise F.FeatureStreamError("the seed's rectangle points were not where they should be")
    # The witness points follow the depth parameter; the box centre before it is left stale.
    start = F.parameter(features, E.DEPTH).value_offset + 8
    _, end = F.feature_span(features, SEED_EXTRUDE)
    for o, n in zip(old, new, strict=True):
        for sign in (1, -1):
            for off in F.doubles_equal_to(features, sign * o, start, end):
                edits.setdefault(off, sign * n)
    return F.set_doubles(features, edits)
