"""STEP (ISO 10303, AP214) export of a part's Parasolid bodies, without SOLIDWORKS
(provisional).

``docs/API.md`` section 3.19 has the API. :func:`step_model` maps the bodies that
:meth:`Document.parasolid` returns, read through SolidSeas' own transmit reader
(:mod:`solidseas.tessellate.topology`), to STEP entities (:mod:`.mapper`), checks
what it would write (:mod:`.checks`) and builds the Part 21 data section in memory;
:func:`write_step` adds the header and writes the file, created new.

A STEP that opens wrong is worse than none: every face and edge is written exactly,
approximated by a B-spline whose deviation is measured and reported (and allowed
for in the file's uncertainty), or it is not representable. A body holding
anything not representable, or failing the export's own checks, refuses the whole
export (:class:`~solidseas.errors.NotRepresentableError`) unless ``allow_partial``,
which leaves such bodies out whole, says so in the result and in the file, and
never writes a solid with a face missing. ``exact_only`` refuses approximations too.

A Parasolid transmit file opened as a model file (:mod:`solidseas.formats`, an
``.x_t`` or ``.x_b``) goes through the same mapper: :func:`step_model` takes its
``ModelDocument`` and maps the bodies of its transmit as :func:`step_transmit` does.
So does a part read from a STEP, ACIS SAB or Alibre Design file, whose reader builds
its bodies as Parasolid transmits in memory (:data:`BODY_FILE_FORMATS`). Any other
model file is refused with ``not_implemented`` (rule ``model_file``): it holds only
triangles.

Pure Python, standard library only. Every read is bounded as ``parasolid()``
bounds it, and the work by faces, entities, bytes and seconds.
"""

import datetime
import math
import os
import time
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Any

from .. import __version__
from ..errors import (
    InvalidArgumentError,
    NothingToExportError,
    NotRepresentableError,
    ReaderWarning,
    SldLimitError,
)
from ..formats.solidworks.parasolid import BODY_TYPES, XtTransmit, body_hidden
from ..tessellate.topology import BODY, Clock, FaceFailed, TimeUp, Topology
from . import part21 as p21
from .checks import check_body
from .mapper import REASONS, BodyMapper, Options, Refused, body_name
from .product import Contexts, part_shape, product
from .split import edge_span, split_seams

FORMAT = "step"
EXTENSIONS = (".step", ".stp")
MIME_TYPE = "model/step"
SCHEMA = "AP214"
DEFAULT_MAX_FACES = 200_000
DEFAULT_MAX_ENTITIES = 20_000_000
DEFAULT_MAX_SECONDS = 300.0
DEFAULT_MAX_BYTES = 2 << 30
FIT_TOLERANCE_M = 1e-7
MAX_DEVIATION_M = 1e-6
MIN_UNCERTAINTY_M = 1e-8  # Parasolid's resolution: 1e-5 mm, as SOLIDWORKS writes it
TOLERANCE_WARNING_M = 1e-6  # tolerant gaps of 1e-3 mm and more, beyond the uncertainty, are warned about
DISPLAY_AGREEMENT = 0.01  # of the box diagonal
MAX_LISTED = 1_000
LEFT_OUT = ("not_asked", "unsupported_body", "hidden")  # reasons a body is left out rather than refused
HIDDEN_MESSAGE = "hidden in SOLIDWORKS, which leaves hidden bodies out of its own STEP"
# The model files (solidseas.formats) whose bodies the mapper takes: Parasolid transmits, and
# the parts of the formats whose readers build their bodies as Parasolid transmits in memory.
BODY_FILE_FORMATS = ("step", "acis", "alibre")
MODEL_FILE_FORMATS = ("parasolid", *BODY_FILE_FORMATS)


@dataclass(frozen=True)
class StepBody:
    """One body of the export: ``product`` (index into ``StepModel.products``), its body
    ``name`` (SOLIDWORKS' body name where the part stores it), ``configuration``,
    ``kind`` (``solid``, ``sheet``, ``wire``, ``general``), ``source`` (``partition``,
    ``local-bodies`` or ``transmit``), its counts as written (``faces``, ``edges``,
    ``vertices``; ``split_faces`` of the source's faces are written as two, cut at
    their seams, which added ``edges_added`` edges), what was approximated and how far
    from the source (metres), the largest tolerance of its edges and vertices, and
    whether it was ``written``; when not, ``reason`` (a key of
    :data:`~.mapper.REASONS`, ``not_asked`` for a sheet when only solids were asked
    for, or ``hidden`` for a body hidden in SOLIDWORKS) and ``message``. A body left out
    with ``not_asked``, ``hidden`` or ``unsupported_body`` (a wire body) does not
    refuse the export; any other reason does, unless ``allow_partial``."""

    product: int
    name: str
    configuration: str | None
    kind: str
    source: str
    faces: int = 0
    edges: int = 0
    vertices: int = 0
    split_faces: int = 0
    edges_added: int = 0
    approximated_faces: int = 0
    approximated_edges: int = 0
    approximated: dict[str, int] = field(default_factory=dict)
    max_deviation_m: float | None = None
    max_tolerance_m: float | None = None
    written: bool = False
    reason: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class StepProduct:
    """A product of the file (the part), with the ``uncertainty_m`` of its own
    geometric context."""

    name: str
    kind: str
    file: str | None
    configuration: str | None
    uncertainty_m: float


@dataclass(frozen=True)
class StepModel:
    """A document mapped to STEP, ready to write: :func:`write_step`.

    ``counts`` has ``products``, ``instances``, ``bodies`` (written), ``solids``,
    ``sheets``, ``faces``, ``edges``, ``vertices``, ``entities`` and
    ``bodies_left_out``; ``uncertainty_m`` is the largest product's uncertainty,
    ``max_deviation_m`` the largest approximation's measured deviation (None: none)
    and ``max_tolerance_m`` the largest tolerance of a written edge or vertex (None:
    none), ``max_gap_m`` the largest gap of the source's own (a vertex off its curve or
    surface, or a point of an edge off one of its faces, by more than Parasolid's
    resolution, with no tolerance declared) that the checks accepted and the uncertainty
    covers (None: none); ``exact`` says nothing was approximated and ``partial`` that
    bodies were left out (``allow_partial``). ``source_format`` is the registry id of
    the file the bodies came from: ``solidworks``, or ``parasolid`` for a transmit
    file."""

    name: str
    doc_type: str
    configuration: str | None
    products: tuple[StepProduct, ...]
    bodies: tuple[StepBody, ...]
    counts: dict[str, int]
    uncertainty_m: float
    max_deviation_m: float | None
    max_tolerance_m: float | None
    approximated: dict[str, int]
    exact: bool
    partial: bool
    max_gap_m: float | None
    originating_system: str
    incomplete: str | None = None
    instances: tuple[Any, ...] = ()
    skipped: tuple[Any, ...] = ()
    warnings: tuple[ReaderWarning, ...] = ()
    seconds: float = 0.0
    source_format: str = "solidworks"
    face_map: dict[int, tuple[int, int]] = field(default_factory=dict, repr=False, compare=False)
    edge_map: dict[int, tuple[int, int]] = field(default_factory=dict, repr=False, compare=False)
    edge_pieces: dict[int, tuple[int, int]] = field(default_factory=dict, repr=False, compare=False)
    _data: list[str] = field(default_factory=list, repr=False, compare=False)

    @property
    def closed(self) -> bool:
        """Every written solid's shells passed the closed-shell check (they all do: a
        body that fails is not written)."""
        return self.counts.get("solids", 0) > 0


@dataclass(frozen=True)
class StepResult:
    """A STEP file written: ``path``, ``format`` (``step``), size in ``bytes``,
    ``merged`` (always False) and the ``model``."""

    path: str
    format: str
    bytes: int
    merged: bool
    model: StepModel


# --------------------------------------------------------------------------- options
def _number(value: Any, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise InvalidArgumentError(
            f"{name} must be a number from {low:g} to {high:g}", detail={"parameter": name}
        )
    return float(value)


def _whole(value: Any, name: str, low: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < low:
        raise InvalidArgumentError(
            f"{name} must be a whole number of at least {low}", detail={"parameter": name}
        )
    return value


def _body_types(body_types) -> frozenset[str]:
    if isinstance(body_types, str) or not all(isinstance(t, str) for t in body_types):
        raise InvalidArgumentError(
            "body_types is a sequence of body type names", detail={"parameter": "body_types"}
        )
    types = frozenset(body_types)
    if not types or not types <= {"solid", "sheet"}:
        raise InvalidArgumentError("body_types takes solid and sheet", detail={"parameter": "body_types"})
    return types


def uncertainty(deviation_m: float | None) -> float:
    """The uncertainty of a product's context: the larger of :data:`MIN_UNCERTAINTY_M`
    and 1.5 times its largest measured deviation, rounded up to 1, 2 or 5 times a power
    of ten (metres)."""
    want = max(MIN_UNCERTAINTY_M, 1.5 * (deviation_m or 0.0))
    if want <= MIN_UNCERTAINTY_M:
        return MIN_UNCERTAINTY_M
    e = math.floor(math.log10(want))
    for m in (1.0, 2.0, 5.0, 10.0):
        v = m * 10.0**e
        if v >= want * (1.0 - 1e-12):
            return float(f"{v:.1g}")
    return 10.0 ** (e + 1)


# --------------------------------------------------------------------------- mapping bodies
class _Job:
    """One body to map: a label, its transmit and BODY node, where it came from, and
    whether SOLIDWORKS hides it (None: not known, or not a SOLIDWORKS part's body)."""

    def __init__(
        self, name, xt, node, kind, source, configuration, topo=None, hidden=None, label=None
    ) -> None:
        self.name, self.xt, self.node, self.kind = name, xt, node, kind
        self.source, self.configuration, self.topo = source, configuration, topo
        self.hidden = hidden
        self.label = label  # the body's name where its transmit names none (another reader's body)


def _left_hidden(j: _Job, opts: Options) -> bool:
    return j.hidden is True and not opts.include_hidden


def _map(jobs: list[_Job], types, opts: Options, clock: Clock, max_faces: int):
    """Map every body asked for: ``(mapped bodies, StepBody records, warnings)``."""
    for j in jobs:
        clock.check()
        if j.topo is None:
            j.topo = Topology(j.xt)
    # The faces every body asked for would map, counted before any is mapped; bodies that
    # share faces count them each time, as each maps them. Stopped as soon as the total
    # passes the limit, so many bodies on one long face chain cost no more than the limit.
    faces = 0
    for j in jobs:
        clock.check()
        if j.kind in types and not _left_hidden(j, opts):
            try:
                faces += len(j.topo.faces(j.node))
            except FaceFailed:
                pass
        if faces > max_faces:
            raise SldLimitError(
                f"the bodies have more than the {max_faces:,} faces allowed", detail={"limit": "max_faces"}
            )
    out = []
    records: list[StepBody] = []
    unnamed = 0
    for j in jobs:
        clock.check()  # between bodies, whatever their size
        name = None
        if j.topo is not None:
            name = body_name(j.xt, j.topo, j.node)
        if not name and j.label:
            name = j.label
        if not name:
            unnamed += 1
            name = "Body" if unnamed == 1 else f"Body{unnamed}"
        base = {
            "product": 0,
            "name": name,
            "configuration": j.configuration,
            "kind": j.kind,
            "source": j.source,
        }
        if _left_hidden(j, opts):
            # Hidden in SOLIDWORKS, which leaves hidden bodies out of its own STEP: left
            # out, and said so, whatever its type.
            records.append(StepBody(**base, reason="hidden", message=HIDDEN_MESSAGE))
            out.append(None)
            continue
        if j.kind not in types:
            # Left out, and said so: a sheet not asked for and a wire body, which no STEP
            # shape of solids and sheets holds. Anything else is refused: a general body,
            # and a body whose type is damaged or unknown, which cannot be said to be safe
            # to leave out.
            if j.kind == "sheet":
                reason, why = "not_asked", "a sheet (surface) body, and only solids were asked for"
            elif j.kind == "wire":
                reason, why = "unsupported_body", REASONS["unsupported_body"]
            elif j.kind == "general":
                reason, why = "non_manifold", REASONS["non_manifold"]
            else:
                reason, why = "bad_reference", f"a body of unknown type ({j.kind})"
            records.append(StepBody(**base, reason=reason, message=why))
            out.append(None)
            continue
        mapper = BodyMapper(j.xt, j.node, opts, clock, j.topo)
        try:
            mapped = mapper.run(name)
            check_body(mapper, mapped)
            if opts.split_seams:
                split_seams(mapper, mapped)
        except Refused as exc:
            records.append(StepBody(**base, reason=exc.reason, message=str(exc)))
            out.append(None)
            continue
        except FaceFailed as exc:
            records.append(StepBody(**base, reason="check_failed", message=str(exc)))
            out.append(None)
            continue
        except (ValueError, ZeroDivisionError, OverflowError, IndexError, KeyError, TypeError) as exc:
            # the checks met something they could not evaluate: the body is not written
            why = f"its checks could not evaluate it ({type(exc).__name__})"
            records.append(StepBody(**base, reason="check_failed", message=why))
            out.append(None)
            continue
        records.append(
            StepBody(
                **base,
                faces=len(mapped.faces),
                edges=len(mapped.edges),
                vertices=len(mapped.vertices),
                split_faces=mapped.split_faces,
                edges_added=mapped.edges_added,
                approximated_faces=mapped.approximated_faces,
                approximated_edges=mapped.approximated_edges,
                approximated=dict(mapped.approximated),
                max_deviation_m=mapped.max_deviation if mapped.approximated else None,
                max_tolerance_m=mapped.max_tolerance or None,
                written=True,
            )
        )
        out.append(mapped)
    return out, records


def _clock(max_seconds: float, t0: float) -> Clock:
    return Clock(max_seconds - (time.perf_counter() - t0))


def _limit_from(exc: BaseException) -> SldLimitError:
    if isinstance(exc, TimeUp):
        return SldLimitError(
            "the STEP export stopped at its max_seconds limit; nothing was written",
            detail={"limit": "max_seconds"},
        )
    return SldLimitError(
        "the STEP export would need more entities than its max_entities limit; nothing was written",
        detail={"limit": "max_entities"},
    )


def _policy(records: list[StepBody], allow_partial: bool, warnings: list[ReaderWarning]) -> str | None:
    """Refuse, or with ``allow_partial`` say what is left out; returns the incomplete
    description line for the file, or None."""
    refused = [r for r in records if not r.written and r.reason not in LEFT_OUT]
    left = [r for r in records if not r.written and r.reason in LEFT_OUT]
    if left:
        why = Counter(r.reason for r in left)
        said = []
        if why.get("hidden"):
            n = why["hidden"]
            said.append(
                f"{n} {'body is' if n == 1 else 'bodies are'} hidden in SOLIDWORKS and not written, as "
                "SOLIDWORKS leaves hidden bodies out of its own STEP (include_hidden writes them)"
            )
        if why.get("not_asked"):
            n = why["not_asked"]
            said.append(
                f"{n} sheet (surface) {'body is' if n == 1 else 'bodies are'} "
                "not written: only solids were asked for (ask for sheets to write them)"
            )
        if why.get("unsupported_body"):
            n = why["unsupported_body"]
            said.append(
                f"{n} wire {'body is' if n == 1 else 'bodies are'} not written: "
                "a STEP shape of solids and sheets holds no wire body"
            )
        warnings.append(ReaderWarning("bodies_left_out", "; ".join(said)))
    if not refused:
        return None
    reasons = Counter(r.reason for r in refused)
    listed = "; ".join(f"{r.name} ({r.reason}: {r.message})" for r in refused[:20])
    if not allow_partial:
        raise NotRepresentableError(
            f"{len(refused)} of {len(records)} bodies cannot be written to STEP without loss, so nothing was "
            f"written: {listed}",
            detail={"rule": refused[0].reason, "value": len(refused)},
            bodies=refused,
        )
    by = ", ".join(f"{k} {n}" for k, n in sorted(reasons.items()))
    warnings.append(
        ReaderWarning(
            "step_bodies_left_out",
            f"{len(refused)} of {len(records)} bodies cannot be written to STEP without loss and are "
            f"left out whole, as asked ({by}): {listed}",
        )
    )
    return f"incomplete: {len(refused)} of {len(records)} bodies left out ({by})"


def _approx_warnings(mapped, warnings: list[ReaderWarning], dev: float | None) -> None:
    by: Counter = Counter()
    faces = edges = 0
    for m in mapped:
        if m is None:
            continue
        by.update(m.approximated)
        faces += m.approximated_faces
        edges += m.approximated_edges
    if by:
        warnings.append(
            ReaderWarning(
                "step_approximated",
                f"{faces} faces and {edges} edges are approximated by B-splines, at most {dev:.3g} m from "
                "the true geometry (" + ", ".join(f"{k} {n}" for k, n in sorted(by.items())) + ")",
            )
        )


def _box_of(mapped) -> tuple[list[float], list[float]] | None:
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for m in mapped:
        if m is None:
            continue
        pts = [v.metres() for v in m.vertices]
        for f in m.faces:
            if f.extent:
                pts.extend(tuple(x / p21.SCALE for x in q) for q in f.extent)
        for e in m.edges:
            if e.start is e.end and e.curve.closed:  # a ring: its circle's or ellipse's extent
                pts.extend(e.curve.evaluator().extent())
            elif e.curve.closed:  # an arc (a ring cut at its seams among them): its extremes
                pts.extend(_arc_extremes(e))
        for p in pts:
            for k in range(3):
                lo[k] = min(lo[k], p[k])
                hi[k] = max(hi[k], p[k])
    if lo[0] > hi[0]:
        return None
    return lo, hi


def _arc_extremes(e) -> list:
    """The points of a circular or elliptical arc edge farthest along each axis, where
    they lie on the arc (metres)."""
    ev = e.curve.evaluator()
    try:
        _ev, ts, te, _period = edge_span(e)
    except TimeUp:  # the export's time limit, never one arc's problem
        raise
    except Exception:  # an arc whose span cannot be found adds nothing to an estimate
        return []
    lo, hi = min(ts, te), max(ts, te)
    out = []
    for k in range(3):
        t0 = math.atan2(ev.b * ev.Y[k], ev.a * ev.X[k])
        for t in (t0, t0 + math.pi):
            t = lo + (t - lo) % (2.0 * math.pi)
            if t <= hi:
                out.append(ev.point(t))
    return out


def _display_warning(doc, mapped, warnings: list[ReaderWarning]) -> None:
    """Compare the written bodies' box with the display mesh SOLIDWORKS saved."""
    box = _box_of(mapped)
    if box is None:
        return
    try:
        mesh = doc.mesh()
    except Exception:  # an unreadable display mesh says nothing about the bodies
        return
    if mesh is None or not mesh.n_triangles:
        return
    p = mesh.positions
    mlo = [min(p[k::3]) for k in range(3)]
    mhi = [max(p[k::3]) for k in range(3)]
    diag = max(math.dist(box[0], box[1]), math.dist(mlo, mhi))
    off = max(math.dist(box[0], mlo), math.dist(box[1], mhi))
    if diag > 0.0 and off > DISPLAY_AGREEMENT * diag:
        warnings.append(
            ReaderWarning(
                "step_differs_from_display",
                "the bodies SOLIDWORKS stored differ from what it last displayed (their boxes are "
                f"{100.0 * off / diag:.1f}% of the diagonal apart); the STEP holds the stored bodies",
            )
        )


@dataclass
class _Prepared:
    """One part's bodies mapped and judged, before anything is written: what
    :func:`_write_bodies` writes and the model's figures are made from."""

    mapped: list
    records: list[StepBody]
    written: list[StepBody]
    uncertainty: float
    deviation: float | None
    tolerance: float | None
    gaps: list[float]
    incomplete: str | None
    approximated: Counter


def _prepare(
    *,
    jobs: list[_Job],
    types,
    opts: Options,
    allow_partial: bool,
    max_faces: int,
    clock: Clock,
    warnings: list[ReaderWarning],
    configuration: str | None,
    doc=None,
) -> _Prepared:
    """Map ``jobs`` and apply the export's rules to them (what is left out, what refuses
    the export, the warnings); raises as :func:`step_model` does."""
    try:
        mapped, records = _map(jobs, types, opts, clock, max_faces)
    except TimeUp as exc:
        raise _limit_from(exc) from None
    written = [r for r in records if r.written]
    if not written and not any(not r.written and r.reason not in LEFT_OUT for r in records):
        # A shown sheet not asked for comes first: asked for, it would be written, whatever
        # else is hidden, and File > Export STEP asks for sheets on this rule alone.
        if any(r.reason == "not_asked" for r in records):
            hides = any(r.reason == "hidden" for r in records)
            what = "the bodies it shows are" if hides else "the part's bodies are"
            raise NothingToExportError(
                f"nothing to export: {what} sheets (surfaces); ask for sheets to write them",
                detail={"rule": "sheets_not_asked"},
            )
        if any(r.reason == "hidden" for r in records):
            raise NothingToExportError(
                "nothing to export: every body the export would write is hidden in SOLIDWORKS, which leaves "
                "hidden bodies out of its own STEP",
                detail={"rule": "hidden"},
            )
        raise NothingToExportError("nothing to export: the document stores no solid body")
    incomplete = _policy(records, allow_partial, warnings)
    if not written:
        raise NothingToExportError("nothing to export: every body was left out")
    # Whether a written solid might be one SOLIDWORKS hides: only where the part does not say
    # (FORMAT.md 10.9; most imported bodies carry no such mark) and it has several solids.
    solids = [j for j, r in zip(jobs, records, strict=True) if r.written and r.kind == "solid"]
    unknown = sum(1 for j in solids if j.hidden is None)
    if doc is not None and len(solids) > 1 and unknown and not opts.include_hidden:
        warnings.append(
            ReaderWarning(
                "step_hidden_bodies_unknown",
                f"the part has {len(solids)} solid bodies and all are written, but it does not say whether "
                f"{'one' if unknown == 1 else unknown} of them {'is' if unknown == 1 else 'are'} hidden: "
                "SOLIDWORKS leaves hidden bodies out of its own STEP",
            )
        )
    devs = [m.max_deviation for m in mapped if m is not None and m.approximated]
    dev = max(devs) if devs else None
    gaps = [m.max_gap for m in mapped if m is not None and m.max_gap]
    tols = [m.max_tolerance for m in mapped if m is not None and m.max_tolerance]
    tol = max(tols) if tols else None
    _approx_warnings(mapped, warnings, dev)
    unc = uncertainty(max([dev or 0.0, *gaps]) or None)
    if tol is not None and tol >= TOLERANCE_WARNING_M and tol > unc:
        warnings.append(
            ReaderWarning(
                "step_tolerant_geometry",
                f"some edges or vertices are tolerant, with gaps up to {tol * 1000.0:.3g} mm, larger than "
                f"the file's uncertainty of {unc * 1000.0:.3g} mm; they are written as Parasolid holds them",
            )
        )
    if doc is not None and configuration == doc.active_configuration:
        _display_warning(doc, mapped, warnings)  # the display mesh shows the active configuration
    by: Counter = Counter()
    for m in mapped:
        if m is not None:
            by.update(m.approximated)
    return _Prepared(mapped, records, written, unc, dev, tol, gaps, incomplete, by)


def _write_bodies(
    ctx: Contexts, pd: int, name: str, prep: _Prepared, clock: Clock, maps=None
) -> tuple[int, int]:
    """Write a prepared part's bodies and its shape into ``ctx``'s file, for the product
    definition ``pd``; returns :func:`.product.part_shape`'s ``(representation,
    origin)``. ``maps`` (face, edge and edge piece maps) is filled from the entities
    written. Raises ``SldLimitError`` and ``NotRepresentableError`` as the export does."""
    w = ctx.w
    face_map, edge_map, edge_pieces = maps if maps is not None else ({}, {}, {})
    try:
        solids: list[int] = []
        sheets: list[int] = []
        for k, m in enumerate(prep.mapped):
            if m is None:
                continue
            for item in m.items:
                clock.tick()
                (solids if item.kind != "SHELL_BASED_SURFACE_MODEL" else sheets).append(item.write(w))
            for f in m.faces:
                face_map[w.memo[f]] = (k, f.source)
            for e, index in m.edge_sources:
                edge_map[w.memo[e]] = (k, index)
            for e, index in m.piece_sources:
                edge_pieces[w.memo[e]] = (k, index)
        return part_shape(ctx, pd, name, solids, sheets, prep.uncertainty * p21.SCALE)
    except (TimeUp, p21.EntityLimit) as exc:
        raise _limit_from(exc) from None
    except ValueError as exc:  # a value that cannot be written: refused, as a body would be
        raise NotRepresentableError(
            f"a value cannot be written to STEP: {exc}", detail={"rule": "bad_geometry", "value": 1}
        ) from None


def _part_counts(prep: _Prepared) -> dict[str, int]:
    written, mapped = prep.written, prep.mapped
    return {
        "products": 1,
        "instances": 0,
        "bodies": len(written),
        "solids": sum(
            1 for m in mapped if m is not None for it in m.items if it.kind != "SHELL_BASED_SURFACE_MODEL"
        ),
        "sheets": sum(1 for r in written if r.kind == "sheet"),
        "faces": sum(r.faces for r in written),
        "edges": sum(r.edges for r in written),
        "vertices": sum(r.vertices for r in written),
        "split_faces": sum(r.split_faces for r in written),
        "edges_added": sum(r.edges_added for r in written),
        "bodies_left_out": len(prep.records) - len(written),
    }


def _build(
    *,
    name: str,
    doc_type: str,
    configuration: str | None,
    jobs: list[_Job],
    types,
    opts: Options,
    allow_partial: bool,
    max_faces: int,
    max_entities: int,
    max_seconds: float,
    t0: float,
    warnings: list[ReaderWarning],
    originating: str,
    doc=None,
) -> StepModel:
    clock = _clock(max_seconds, t0)
    prep = _prepare(
        jobs=jobs,
        types=types,
        opts=opts,
        allow_partial=allow_partial,
        max_faces=max_faces,
        clock=clock,
        warnings=warnings,
        configuration=configuration,
        doc=doc,
    )
    w = p21.Writer(max_entities)
    maps: tuple[dict, dict, dict] = ({}, {}, {})
    try:
        ctx = Contexts(w)
        pd = product(ctx, name, "part")
    except p21.EntityLimit as exc:
        raise _limit_from(exc) from None
    _write_bodies(ctx, pd, name, prep, clock, maps)
    face_map, edge_map, edge_pieces = maps
    unc, dev, tol, gaps, by = prep.uncertainty, prep.deviation, prep.tolerance, prep.gaps, prep.approximated
    records, incomplete = prep.records, prep.incomplete
    counts = _part_counts(prep)
    left_out = counts.pop("bodies_left_out")
    counts.update(entities=w.count, bodies_left_out=left_out)  # in the order the model has always given
    return StepModel(
        name=name,
        doc_type=doc_type,
        configuration=configuration,
        products=(StepProduct(name, "part", None, configuration, unc),),
        bodies=tuple(records),
        counts=counts,
        uncertainty_m=unc,
        max_deviation_m=dev,
        max_tolerance_m=tol,
        max_gap_m=max(gaps) if gaps else None,
        approximated=dict(by),
        exact=not by,
        partial=incomplete is not None,
        originating_system=originating,
        incomplete=incomplete,
        warnings=tuple(warnings),
        seconds=time.perf_counter() - t0,
        face_map=face_map,
        edge_map=edge_map,
        edge_pieces=edge_pieces,
        _data=w.lines,
    )


def _stem(name: str | None, fallback: str) -> str:
    from ..export import _stem as stem

    return stem(name, fallback)


def _options(
    fit_tolerance_m, max_deviation_m, exact_only, body_types, split_periodic=True, include_hidden=False
):
    fit = _number(fit_tolerance_m, "fit_tolerance_m", 1e-9, 1e-4)
    dev = _number(max_deviation_m, "max_deviation_m", fit, 1e-3)
    types = _body_types(body_types)
    return Options(
        exact_only=bool(exact_only),
        fit_tolerance_m=fit,
        max_deviation_m=dev,
        sheets="sheet" in types,
        split_seams=bool(split_periodic),
        include_hidden=bool(include_hidden),
    ), types


def step_configurations(doc) -> list[str]:
    """The names of the configurations whose bodies the part stores, in the document's
    order (a configuration the document does not name is ``Config-<id>``). A model file
    has none of its own: ``[]``."""
    if doc.doc_type != "part" or _is_model_file(doc):
        return []
    res = doc.parasolid()
    ids = {b.configuration_id for b in res.bodies}
    names = []
    for c in doc.configurations:
        if c.id in ids:
            names.append(c.name)
            ids.discard(c.id)
    names.extend(f"Config-{i}" for i in sorted(ids))
    return names


def _part_jobs(doc, configuration: str | None) -> tuple[str | None, list[_Job], list[ReaderWarning]]:
    """The bodies of the part ``doc`` in ``configuration`` (None: the active one) as jobs
    to map: ``(configuration name, jobs, warnings)``. Raises ``NothingToExportError``
    when the part does not store that configuration's bodies."""
    from ..tessellate import bodies_of

    cfg_name, bodies, warnings, _n = bodies_of(doc, configuration)
    warnings = [w for w in warnings if w.code != "no_stored_bodies"]
    if not bodies:
        stored = step_configurations(doc)
        where = (
            f"it stores the bodies of {', '.join(repr(s) for s in stored)}"
            if stored
            else "it stores no bodies at all"
        )
        raise NothingToExportError(
            f"nothing to export: the part does not store the bodies of configuration {cfg_name!r} ({where}); "
            "SolidSeas does not take another configuration's geometry in its place"
        )
    jobs = []
    for b in bodies:
        root = b.transmit.by_index().get(1)
        if root is None or root.type != BODY:
            root = next((n for n in b.transmit.nodes if n.type == BODY), None)
        if root is None:
            continue
        hidden = body_hidden(b.transmit, root)
        jobs.append(
            _Job(b.name, b.transmit, root, b.body_type, b.source, b.configuration_name, hidden=hidden)
        )
    return cfg_name, jobs, warnings


def step_model(
    doc,
    configuration: str | None = None,
    *,
    name: str | None = None,
    body_types=("solid",),
    allow_partial: bool = False,
    exact_only: bool = False,
    fit_tolerance_m: float = FIT_TOLERANCE_M,
    max_deviation_m: float = MAX_DEVIATION_M,
    max_faces: int = DEFAULT_MAX_FACES,
    max_entities: int = DEFAULT_MAX_ENTITIES,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    split_periodic: bool = True,
    include_hidden: bool = False,
    roots=None,
    path_map=(),
    allow_outside_roots: bool = True,
    cache=None,
) -> StepModel:
    """The part or assembly ``doc`` in ``configuration`` (None: the active one) mapped to
    STEP AP214, ready for :func:`write_step`. Provisional (``docs/API.md`` 3.19).

    An assembly is one product for itself and one for each part it places, every
    instance an occurrence at its placement (:mod:`.assembly`); ``roots``, ``path_map``,
    ``allow_outside_roots`` and ``cache`` find its component files as
    :func:`~solidseas.geometry.display_geometry` does. A component not found, not
    readable or placed mirrored raises ``NotRepresentableError`` (rule
    ``instances_left_out``) unless ``allow_partial`` leaves it out.

    Raises :class:`~solidseas.errors.NotRepresentableError` when a body holds what
    cannot be written (unless ``allow_partial``), ``NothingToExportError`` for a
    drawing, a configuration whose bodies the part does not store (no other
    configuration's are taken instead) and a part with no body to write,
    ``SldLimitError`` at a limit, ``ConfigurationNotFoundError`` and
    ``InvalidArgumentError``.

    ``doc`` may be a model file (:mod:`solidseas.formats`): a Parasolid transmit file's
    bodies are mapped as :func:`step_transmit` maps them, in its one configuration, and
    so are the bodies the reader of a STEP, ACIS SAB or Alibre Design part builds
    (:func:`_bodies_file`); any other format raises ``UnsupportedOperationError``
    (``not_implemented``, rule ``model_file``). A transmit whose assemblies place bodies
    by instances is written as an assembly (:func:`.assembly.transmit_assembly_model`).

    ``split_periodic`` (as SOLIDWORKS' own "split periodic faces" option) writes a face
    that goes round a closed surface as two, cut at its seams (:mod:`.split`). A body
    SOLIDWORKS hides is left out, as SOLIDWORKS' own STEP leaves it out, unless
    ``include_hidden``."""
    t0 = time.perf_counter()
    if _is_model_file(doc):
        return _model_file(
            doc,
            configuration,
            name=name,
            body_types=body_types,
            allow_partial=allow_partial,
            exact_only=exact_only,
            fit_tolerance_m=fit_tolerance_m,
            max_deviation_m=max_deviation_m,
            max_faces=max_faces,
            max_entities=max_entities,
            max_seconds=max_seconds,
            split_periodic=split_periodic,
            include_hidden=include_hidden,
        )
    opts, types = _options(
        fit_tolerance_m, max_deviation_m, exact_only, body_types, split_periodic, include_hidden
    )
    max_faces = _whole(max_faces, "max_faces", 1)
    max_entities = _whole(max_entities, "max_entities", 1)
    max_seconds = _number(max_seconds, "max_seconds", 0.0, 1e6)
    if name is not None and not isinstance(name, str):
        raise InvalidArgumentError("name is a string", detail={"parameter": "name"})
    kind = doc.doc_type
    label = name or _stem(getattr(doc, "name", None), kind or "model")
    originating = getattr(doc.saved_version, "release", None) or "SOLIDWORKS"
    if kind == "assembly":
        from .assembly import assembly_model

        return assembly_model(
            doc,
            configuration,
            name=label,
            types=types,
            opts=opts,
            allow_partial=allow_partial,
            max_faces=max_faces,
            max_entities=max_entities,
            max_seconds=max_seconds,
            t0=t0,
            originating=originating,
            geometry_options={
                "roots": roots,
                "path_map": path_map,
                "allow_outside_roots": allow_outside_roots,
                "cache": cache,
            },
        )
    if kind != "part":
        raise NothingToExportError(
            f"nothing to export: a {kind or 'document of unknown type'} has no 3D model"
        )
    cfg_name, jobs, warnings = _part_jobs(doc, configuration)
    return _build(
        name=label,
        doc_type="part",
        configuration=cfg_name,
        jobs=jobs,
        types=types,
        opts=opts,
        allow_partial=allow_partial,
        max_faces=max_faces,
        max_entities=max_entities,
        max_seconds=max_seconds,
        t0=t0,
        warnings=warnings,
        originating=originating,
        doc=doc,
    )


def step_transmit(
    xt,
    *,
    name: str = "body",
    body_types=("solid",),
    allow_partial: bool = False,
    exact_only: bool = False,
    fit_tolerance_m: float = FIT_TOLERANCE_M,
    max_deviation_m: float = MAX_DEVIATION_M,
    max_faces: int = DEFAULT_MAX_FACES,
    max_entities: int = DEFAULT_MAX_ENTITIES,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    originating: str = "Parasolid",
    split_periodic: bool = True,
    include_hidden: bool = False,
) -> StepModel:
    """Every BODY of a parsed transmit (an .x_t or .x_b read with
    :func:`~solidseas.formats.solidworks.parasolid.read_file`, or a body's transmit),
    or of each of a sequence of them, as one STEP product named ``name``. A transmit's
    bodies are all written: whether SOLIDWORKS hid them is a SOLIDWORKS part's to say
    (``include_hidden`` changes nothing here)."""
    transmits = [xt] if isinstance(xt, XtTransmit) else list(xt) if isinstance(xt, (list, tuple)) else None
    if not transmits or not all(isinstance(x, XtTransmit) for x in transmits):
        raise InvalidArgumentError(
            "xt is a parsed XtTransmit or a sequence of them", detail={"parameter": "xt"}
        )
    t0 = time.perf_counter()
    opts, types = _options(
        fit_tolerance_m, max_deviation_m, exact_only, body_types, split_periodic, include_hidden
    )
    jobs = []
    for one in transmits:
        topo = Topology(one)
        for node in topo.bodies():
            code = topo.get(node, "body_type", 0)
            kind = BODY_TYPES.get(code, "unknown") if isinstance(code, int) else "unknown"
            jobs.append(_Job(name, one, node, kind, "transmit", None, topo))
    if not jobs:
        raise NothingToExportError("nothing to export: the transmit holds no body")
    return _build(
        name=name,
        doc_type="part",
        configuration=None,
        jobs=jobs,
        types=types,
        opts=opts,
        allow_partial=allow_partial,
        max_faces=_whole(max_faces, "max_faces", 1),
        max_entities=_whole(max_entities, "max_entities", 1),
        max_seconds=_number(max_seconds, "max_seconds", 0.0, 1e6),
        t0=t0,
        warnings=[],
        originating=originating,
    )


def _is_model_file(doc) -> bool:
    from ..formats.base import ModelDocument

    return isinstance(doc, ModelDocument)


def _model_file(doc, configuration: str | None, *, name: str | None, **options: Any) -> StepModel:
    """:func:`step_model` of a model file: a Parasolid transmit file's bodies through
    :func:`step_transmit`, the same mapper, named ``name`` (default: the file's name).
    Raises ``UnsupportedOperationError`` for any other format and
    ``ConfigurationNotFoundError`` for a configuration it does not have. A transmit
    whose assemblies place bodies by instances is written as an assembly
    (:func:`.assembly.transmit_assembly_model`), but for one whose one assembly only
    gathers its bodies at the identity, as SOLIDWORKS writes a multi-body part's .x_b:
    that is the part, its bodies written as one product, as SOLIDWORKS' own STEP of the
    part writes them."""
    from ..errors import ConfigurationNotFoundError, UnsupportedOperationError
    from ..formats._source import Clock as ReadClock
    from ..formats.xt import ASSEMBLY, INSTANCE, bodies_in_place

    if doc.format in BODY_FILE_FORMATS:
        return _bodies_file(doc, configuration, name=name, **options)
    if doc.format not in MODEL_FILE_FORMATS:
        raise UnsupportedOperationError(
            "the STEP export writes Parasolid bodies, from SOLIDWORKS parts and Parasolid transmit files, "
            f"not {doc.format_name} files",
            detail={"rule": "model_file", "value": doc.format},
        )
    if name is not None and not isinstance(name, str):
        raise InvalidArgumentError("name is a string", detail={"parameter": "name"})
    if configuration is not None and configuration != doc.active_configuration:
        raise ConfigurationNotFoundError(f"the file has no configuration named {configuration!r}")
    xt = doc.transmit(ReadClock(doc.limits.seconds))
    app = doc.application or {}
    originating = " ".join(str(v) for v in (app.get("name"), app.get("version")) if v) or "Parasolid"
    if not bodies_in_place(xt) and any(n.type in (ASSEMBLY, INSTANCE) for n in xt.nodes):
        from .assembly import transmit_assembly_model

        opts, types = _options(
            options["fit_tolerance_m"],
            options["max_deviation_m"],
            options["exact_only"],
            options["body_types"],
            options["split_periodic"],
            options["include_hidden"],
        )
        model = transmit_assembly_model(
            doc,
            xt,
            name=name or _stem(doc.name, "assembly"),
            types=types,
            opts=opts,
            allow_partial=options["allow_partial"],
            max_faces=_whole(options["max_faces"], "max_faces", 1),
            max_entities=_whole(options["max_entities"], "max_entities", 1),
            max_seconds=_number(options["max_seconds"], "max_seconds", 0.0, 1e6),
            t0=time.perf_counter(),
            originating=originating,
        )
        return replace(model, source_format=doc.format)
    model = step_transmit(xt, name=name or _stem(doc.name, "part"), originating=originating, **options)
    # SOLIDWORKS' own STEP leaves hidden bodies out; a transmit file has no such bodies to hide
    warnings = tuple(w for w in model.warnings if w.code != "step_hidden_bodies_unknown")
    return replace(model, warnings=warnings, source_format=doc.format)


def _reader_bodies(doc, max_seconds: float) -> tuple[list[tuple[str | None, Any, int]], bool, int]:
    """A part's bodies as its reader built them, ``(name, body or None, faces left out)``
    each, whether they lie in the part's own frame, and how many mesh items it holds."""
    if doc.format == "step":
        return doc.part_bodies(max(max_seconds, 1e-3))
    from ..formats._source import Clock as ReadClock

    clock = ReadClock(doc.limits.seconds)
    if doc.format == "acis":
        builds = doc.builds(clock)
        refs = doc.bodies()
        return [(b.label, r, len(b.skipped)) for b, r in zip(builds, refs, strict=True)], True, 0
    refs = doc.bodies() or []  # an Alibre part's one ACIS body
    lost = len(doc.body_build(clock).skipped) if refs else 0
    return [(r.name, r, lost) for r in refs], True, 0


def _bodies_file(doc, configuration: str | None, *, name: str | None, **options: Any) -> StepModel:
    """STEP of a part read from a file whose reader builds its bodies as Parasolid
    transmits in memory (:data:`BODY_FILE_FORMATS`: a STEP, ACIS SAB or Alibre Design
    part): those bodies, mapped as :func:`step_transmit` maps a transmit's, as one part
    named ``name`` (default: the file's name), each body named as the reader names it.

    What the reader holds of an assembly, and of a STEP part whose bodies do not all lie
    once at the part's origin (a body placed in its product, or placed twice), is not one
    part's bodies: they raise ``UnsupportedOperationError`` (rules ``model_assembly`` and
    ``model_placed``). A body the reader built without some of its faces, a body it could
    not read, and a STEP file's faceted and tessellated items (triangles, not faces)
    cannot be written without loss: they raise ``NotRepresentableError`` (rule
    ``faces_left_out``) unless ``allow_partial`` leaves them out and says so."""
    from ..errors import ConfigurationNotFoundError, UnsupportedOperationError

    if name is not None and not isinstance(name, str):
        raise InvalidArgumentError("name is a string", detail={"parameter": "name"})
    if configuration is not None and configuration != doc.active_configuration:
        raise ConfigurationNotFoundError(f"the file has no configuration named {configuration!r}")
    if doc.doc_type == "assembly":
        raise UnsupportedOperationError(
            f"the STEP export writes a {doc.format_name} part's bodies, and this file is an assembly",
            detail={"rule": "model_assembly", "value": doc.format},
        )
    t0 = time.perf_counter()
    max_seconds = _number(options["max_seconds"], "max_seconds", 0.0, 1e6)
    found, in_place, meshes = _reader_bodies(doc, max_seconds)
    if not in_place:
        raise UnsupportedOperationError(
            f"the STEP export writes a {doc.format_name} part's bodies where they lie in the part, and this "
            "file places a body away from its product's origin, or more than once",
            detail={"rule": "model_placed", "value": doc.format},
        )
    left = [
        f"{n or 'body'} ({k} face{'' if k == 1 else 's'} not read)" for n, ref, k in found if ref is None or k
    ]
    if any(w.code == "bodies_left_out" for w in doc.warnings):
        left.append("a body the reader could not read")
    if meshes:
        left.append(f"{meshes} faceted or tessellated items (triangles, not faces)")
    if left and not options["allow_partial"]:
        raise NotRepresentableError(
            "the file's bodies cannot be written to STEP without loss, so nothing was written: "
            + "; ".join(left[:20]),
            detail={"rule": "faces_left_out", "value": len(left)},
        )
    whole = [(n, ref) for n, ref, k in found if ref is not None and not k]
    if not whole:
        raise NothingToExportError(
            "nothing to export: the file holds no B-rep body the STEP export can write",
            detail={"rule": "no_bodies"},
        )
    opts, types = _options(
        options["fit_tolerance_m"],
        options["max_deviation_m"],
        options["exact_only"],
        options["body_types"],
        options["split_periodic"],
        options["include_hidden"],
    )
    product_name = name or _stem(doc.name, "part")
    jobs = []
    for label, ref in whole:
        topo = Topology(ref.transmit)
        for node in topo.bodies():
            code = topo.get(node, "body_type", 0)
            kind = BODY_TYPES.get(code, "unknown") if isinstance(code, int) else "unknown"
            jobs.append(_Job(product_name, ref.transmit, node, kind, "transmit", None, topo, label=label))
    app = doc.application or {}
    originating = " ".join(str(v) for v in (app.get("name"), app.get("version")) if v) or doc.format_name
    warnings: list[ReaderWarning] = []
    if left:
        warnings.append(
            ReaderWarning(
                "step_bodies_left_out",
                f"{len(left)} of the file's bodies and items cannot be written to STEP without loss and are "
                f"left out whole, as asked: {'; '.join(left[:20])}",
            )
        )
    model = _build(
        name=product_name,
        doc_type="part",
        configuration=None,
        jobs=jobs,
        types=types,
        opts=opts,
        allow_partial=options["allow_partial"],
        max_faces=_whole(options["max_faces"], "max_faces", 1),
        max_entities=_whole(options["max_entities"], "max_entities", 1),
        max_seconds=max_seconds,
        t0=t0,
        warnings=warnings,
        originating=originating,
    )
    if left:
        said = f"incomplete: {len(left)} of the file's bodies and items left out"
        model = replace(model, partial=True, incomplete="; ".join(x for x in (model.incomplete, said) if x))
    return replace(model, source_format=doc.format)


# --------------------------------------------------------------------------- writing
def _stamp(time_stamp) -> str:
    if time_stamp is None:
        return p21.time_stamp()
    if isinstance(time_stamp, datetime.datetime):
        return p21.time_stamp(time_stamp)
    if isinstance(time_stamp, str) and len(time_stamp) <= 64:
        return time_stamp
    raise InvalidArgumentError(
        "time_stamp is a datetime or an ISO 8601 string", detail={"parameter": "time_stamp"}
    )


def _chunks(model: StepModel, file_name: str, stamp: str):
    yield p21.header(
        file_name=file_name,
        stamp=stamp,
        system=f"SolidSeas {__version__}",
        originating=model.originating_system,
        incomplete=model.incomplete,
    )
    batch: list[str] = []
    size = 0
    for i, body in enumerate(model._data, 1):
        line = f"#{i}={body};\n"
        batch.append(line)
        size += len(line)
        if size >= 1 << 20:
            yield "".join(batch)
            batch, size = [], 0
    if batch:
        yield "".join(batch)
    yield p21.CLOSING


def write_step_to(
    model: StepModel, fh, *, file_name: str, max_bytes: int | None = DEFAULT_MAX_BYTES, time_stamp=None
) -> int:
    """Write the model's Part 21 file to the open binary file ``fh``; returns its size.
    Raises ``SldLimitError`` once it passes ``max_bytes``."""
    stamp = _stamp(time_stamp)
    n = 0
    for chunk in _chunks(model, file_name, stamp):
        data = chunk.encode("ascii")
        n += len(data)
        if max_bytes is not None and n > max_bytes:
            raise SldLimitError(
                f"the STEP file would be larger than its {max_bytes:,}-byte limit",
                detail={"limit": "max_bytes"},
            )
        fh.write(data)
    return n


def step_bytes(
    model: StepModel,
    *,
    file_name: str | None = None,
    max_bytes: int | None = DEFAULT_MAX_BYTES,
    time_stamp=None,
) -> bytes:
    """The model's Part 21 file in memory: for small models and tests."""
    import io

    buf = io.BytesIO()
    write_step_to(
        model, buf, file_name=file_name or f"{model.name}.step", max_bytes=max_bytes, time_stamp=time_stamp
    )
    return buf.getvalue()


def write_step(
    model: StepModel,
    path: str | os.PathLike,
    *,
    overwrite: bool = False,
    max_bytes: int | None = DEFAULT_MAX_BYTES,
    time_stamp=None,
    file_name: str | None = None,
) -> StepResult:
    """Write ``model`` to ``path`` as a STEP file, created new as
    :func:`solidseas.export.write_export` creates its files: an existing file raises
    ``OutputRefusedError`` (rule ``exists``) unless ``overwrite``, a link or a device is
    refused, and a write that fails removes what it created. The FILE_NAME in the
    header is the file's own name (or ``file_name``, for a file written under a
    temporary name first); ``time_stamp`` (a datetime or an ISO 8601 string) fixes the
    header's time stamp, as tests do."""
    from ..export import write_new

    if max_bytes is not None:
        max_bytes = _whole(max_bytes, "max_bytes", 1)
    stamp = _stamp(time_stamp)
    file_name = file_name or os.path.basename(os.fspath(path))

    def write(fh) -> int:
        return write_step_to(model, fh, file_name=file_name, max_bytes=max_bytes, time_stamp=stamp)

    target, size = write_new(path, write, overwrite=overwrite)
    return StepResult(target, FORMAT, size, False, model)


__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_ENTITIES",
    "DEFAULT_MAX_FACES",
    "DEFAULT_MAX_SECONDS",
    "EXTENSIONS",
    "FIT_TOLERANCE_M",
    "MAX_DEVIATION_M",
    "MIME_TYPE",
    "REASONS",
    "StepBody",
    "StepModel",
    "StepProduct",
    "StepResult",
    "step_bytes",
    "step_configurations",
    "step_model",
    "step_transmit",
    "uncertainty",
    "write_step",
    "write_step_to",
]
