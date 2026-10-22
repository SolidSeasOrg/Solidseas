"""The drawings cross-check (``docs/DRAWINGS.md`` section 25, ``docs/OCCT.md`` section 8):
SolidSeas' views of a part against Open CASCADE's two hidden-line algorithms, as a
three-way vote, and its planned dimensions against the lines Open CASCADE draws.

A development tool, opt-in like the OCCT oracle (``occt_support``) and never a
dependency of ``solidseas.drawing``: Open CASCADE runs only in ``occt_hlr_child.py``,
in the interpreter ``SOLIDSEAS_OCCT_PYTHON`` names, through
:func:`occt_support.run_child` (a Job Object, a memory cap, a timeout). Everything
here is plain Python on numbers, so its own tests run without Open CASCADE.

* :func:`occt_views` reads SolidSeas' STEP of the part in the child and runs
  ``HLRBRep_Algo`` (``exact``) and ``HLRBRep_PolyAlgo`` (``poly``) for the views asked,
  each in the view's own frame (``ViewSpec.frame``), in millimetres.
* :func:`ours` takes SolidSeas' runs of a view the same way: ``visible``, ``hidden``,
  and its tangent edges drawn thin or phantom as ``smooth``.
* :func:`vote` samples the three sets' lines every ``tol / 2`` and says, by length,
  where all three agree and which one is the odd one out where they do not: the one
  that misses a line both others draw, or draws one neither draws. A stretch of hidden
  line on a visible line of its own set is left out first, since a drawing never draws
  it. A smooth (tangent) edge counts as a line where one is drawn, but is no line a set
  must draw, since a drawing shows tangent edges by a setting of its own.
* :func:`dimension_witnesses` checks each shown linear dimension: each of its positions
  (a face, or a round feature's two sides) must be where one of Open CASCADE's lines of
  that view lies, and a diameter's circle must be one Open CASCADE draws.
* :func:`cross_check` does all of it for one part: the six principal views with hidden
  lines, and the dimensions of the drawing SolidSeas plans for it.

``python tests/drawing_occt.py PART...`` prints the cross-check of each part, for a
look at parts no test names (the corpus, say); ``SOLIDSEAS_OCCT_PYTHON`` must be set.
"""

from __future__ import annotations

import math
import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

import occt_support as O

CHILD = Path(__file__).with_name("occt_hlr_child.py")
MM = 1e-3
KINDS = ("visible", "hidden")
SETS = ("ours", "exact", "poly")
PRINCIPAL = ("front", "top", "right", "left", "bottom", "back")


def tolerance_mm(model) -> float:
    """How far apart two lines may lie and still be one, in millimetres: a thousandth of
    the part's diagonal, at least 0.02 mm (OCCT's polygon algorithm draws on a mesh)."""
    lo, hi = model.box
    return max(0.02, 1e-3 * math.dist(lo, hi) / MM)


# --------------------------------------------------------------------------- line sets
def sample(polylines, step: float) -> list[tuple[float, float, float]]:
    """Points along ``polylines`` at most ``step`` apart, each with the length it stands
    for: (x, y, length)."""
    out = []
    for line in polylines:
        for (x0, y0), (x1, y1) in zip(line, line[1:], strict=False):
            span = math.hypot(x1 - x0, y1 - y0)
            n = max(1, math.ceil(span / step))
            for k in range(n):
                t = (k + 0.5) / n
                out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, span / n))
    return out


class Lines:
    """Polylines in a grid of cells, to ask whether a point lies within ``tol`` of one."""

    def __init__(self, polylines, tol: float) -> None:
        self.tol = tol
        self.cell = max(tol * 4, 1e-6)
        self.grid: dict[tuple[int, int], list] = defaultdict(list)
        for line in polylines:
            for a, b in zip(line, line[1:], strict=False):
                x0, x1 = sorted((a[0], b[0]))
                y0, y1 = sorted((a[1], b[1]))
                for i in range(self._k(x0 - tol), self._k(x1 + tol) + 1):
                    for j in range(self._k(y0 - tol), self._k(y1 + tol) + 1):
                        self.grid[(i, j)].append((a, b))

    def _k(self, v: float) -> int:
        return math.floor(v / self.cell)

    def near(self, x: float, y: float) -> bool:
        return any(_distance(x, y, a, b) <= self.tol for a, b in self.grid.get((self._k(x), self._k(y)), ()))


class _Hidden:
    """Where a set draws a hidden line: near one of its hidden lines and none of its
    visible ones."""

    def __init__(self, hidden: Lines, visible: Lines) -> None:
        self.hidden, self.visible = hidden, visible

    def near(self, x: float, y: float) -> bool:
        return self.hidden.near(x, y) and not self.visible.near(x, y)


def _smooth(lines: dict, kind: str) -> list:
    """A set's smooth (tangent) edges of one kind: ``smooth`` for SolidSeas' drawn tangent
    edges, ``smooth_visible`` or ``smooth_hidden`` for Open CASCADE's."""
    return lines.get("smooth", []) + lines.get(f"smooth_{kind}", [])


def _distance(x: float, y: float, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    span = dx * dx + dy * dy
    t = 0.0 if span == 0.0 else max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / span))
    return math.hypot(x - a[0] - t * dx, y - a[1] - t * dy)


# --------------------------------------------------------------------------- the two sides
def occt_views(
    step_path: str | os.PathLike, frames: dict, *, deflection_mm: float = 0.01, timeout_s: float = 300.0
):
    """Open CASCADE's lines of the views ``frames`` names (name: (right, up, d), as
    ``ViewSpec.frame`` gives them) for the STEP file at ``step_path``, and the versions
    that drew them: ({name: {"exact": sets, "poly": sets}}, versions), each set a dict of
    ``visible``, ``hidden``, ``smooth_visible`` and ``smooth_hidden`` polylines in
    millimetres, or ``{"error": ...}``. Raises AssertionError when the child did not
    answer."""
    views = {name: [list(d), list(right)] for name, (right, _up, d) in frames.items()}
    req = {"op": "hlr", "path": str(step_path), "views": views, "deflection_mm": deflection_mm}
    got = O.run_child(req, script=CHILD, timeout_s=timeout_s)
    assert got.ok, f"the OCCT child did not answer: {got.describe()}"
    return got.reply["views"], got.reply.get("versions") or {}


def ours(geometry) -> dict:
    """SolidSeas' runs of one view (a ``ViewGeometry``) as polylines in millimetres:
    ``visible``, ``hidden`` and ``smooth`` (tangent edges drawn thin or phantom)."""
    from solidseas.drawing import display as D
    from solidseas.drawing.painter import spline_points

    kinds = {"visible": "visible", "hidden": "hidden", "thin": "smooth", "phantom": "smooth"}
    out: dict[str, list] = {"visible": [], "hidden": [], "smooth": []}
    for run in geometry.runs:
        kind = kinds.get(run.style)
        if kind is None:
            continue
        p = run.primitive
        if isinstance(p, D.Segment):
            pts = [p.p0, p.p1]
        elif isinstance(p, D.Arc):
            n = max(8, math.ceil(p.sweep() / 2.0))
            pts = [p.point(p.start_deg + p.sweep() * k / n) for k in range(n + 1)]
        elif isinstance(p, D.EllipseArc):
            n = max(16, math.ceil(abs(p.t1 - p.t0) / math.radians(2.0)))
            pts = [p.point(p.t0 + (p.t1 - p.t0) * k / n) for k in range(n + 1)]
        elif isinstance(p, D.Spline):
            pts = spline_points(p, 1e-6)
        elif isinstance(p, D.Polyline):
            pts = [*p.points, p.points[0]] if p.closed and p.points else list(p.points)
        else:
            continue
        out[kind].append([(x / MM, y / MM) for x, y in pts])
    return out


# --------------------------------------------------------------------------- the vote
def vote(sets: dict, tol: float) -> dict:
    """The three-way vote of one view. ``sets`` maps ``ours``, ``exact`` and ``poly`` to
    their lines (``visible`` and ``hidden``, with ``smooth`` or ``smooth_visible`` and
    ``smooth_hidden``); ``tol`` is in millimetres. For each of ``visible`` and
    ``hidden``: the ``length`` of line any set draws, the length all three ``agreed`` on,
    each set's ``odd`` length (``missed``: lines both others draw; ``alone``: lines it
    alone draws), and ``covered``, the share of one set's line another draws too
    (``covered["ours_exact"]`` is ours' precision against exact, and
    ``covered["exact_ours"]`` its recall)."""
    step = tol / 2.0
    seen = {name: Lines(sets[name]["visible"], tol) for name in SETS}
    hid = {name: Lines(sets[name]["hidden"], tol) for name in SETS}
    out = {}
    for kind in KINDS:
        smooth = {name: Lines(_smooth(sets[name], kind), tol) for name in SETS}
        # where a set draws a line of this kind: a hidden one never on a visible line of its own
        drawn = seen if kind == "visible" else {name: _Hidden(hid[name], seen[name]) for name in SETS}
        weights: dict[tuple[bool, ...], float] = defaultdict(float)
        covered = {f"{a}_{b}": [0.0, 0.0] for a in SETS for b in SETS if a != b}
        for name in SETS:
            points = sample(sets[name][kind], step)
            if kind == "hidden":
                points = [(x, y, w) for x, y, w in points if not seen[name].near(x, y)]
            for x, y, w in points:
                drew = tuple(other == name or drawn[other].near(x, y) for other in SETS)
                has = tuple(d or smooth[other].near(x, y) for d, other in zip(drew, SETS, strict=True))
                weights[has] += w / sum(drew)  # a line several sets draw is sampled by each
                for k, other in enumerate(SETS):
                    if other != name:
                        covered[f"{name}_{other}"][0] += w
                        covered[f"{name}_{other}"][1] += w if has[k] else 0.0
        odd = {}
        for k, name in enumerate(SETS):
            missed = sum(w for has, w in weights.items() if not has[k] and sum(has) == 2)
            alone = sum(w for has, w in weights.items() if has[k] and sum(has) == 1)
            odd[name] = {"missed": missed, "alone": alone}
        out[kind] = {
            "length": sum(weights.values()),
            "agreed": weights.get((True, True, True), 0.0),
            "odd": odd,
            "covered": {key: (got / total if total else 1.0) for key, (total, got) in covered.items()},
        }
    return out


def odd_one_out(result: dict, kind: str = "visible", share: float = 0.01) -> str | None:
    """The set the vote of one view finds at odd the most, or None when no set is at
    odd for more than ``share`` of the view's line."""
    r = result[kind]
    worst = max(SETS, key=lambda n: r["odd"][n]["missed"] + r["odd"][n]["alone"])
    amount = r["odd"][worst]["missed"] + r["odd"][worst]["alone"]
    return worst if amount > share * max(r["length"], 1e-9) else None


# --------------------------------------------------------------------------- dimensions
def dimension_witnesses(plan, lines: dict, tol: float) -> list[dict]:
    """Each shown dimension of ``plan`` (a ``Plan``) in a view ``lines`` holds Open
    CASCADE's sets for ({view id: {"exact": sets, "poly": sets}}): ``{"id", "kind",
    "view", "checked", "ok", "missing"}``. A linear dimension is checked when its axis
    shows along the sheet in its view: each position must lie on one of Open CASCADE's
    lines (any set, any algorithm) within ``tol`` millimetres along that axis, a round
    feature's centre by both its sides. A diameter is checked when its anchor is given:
    Open CASCADE must draw at least a quarter of a circle of its radius about it.
    ``missing`` holds the positions or diameters not found, in millimetres."""
    specs = {s.id: s for s in plan.views}
    out = []
    for d in plan.dimensions:
        if d.state != "shown" or d.view not in lines or d.view not in specs:
            continue
        spec = specs[d.view]
        right, up, _d = spec.frame()
        drawn = [
            line
            for sets in lines[d.view].values()
            if isinstance(sets, dict)
            for key in ("visible", "hidden", "smooth_visible", "smooth_hidden")
            for line in sets.get(key, [])
        ]
        entry = {"id": d.id, "kind": d.kind, "view": d.view, "checked": False, "ok": True, "missing": []}
        if d.kind == "linear" and d.axis:
            along = {model: (sheet, sign) for sheet, (model, sign) in spec.axis_map().items()}.get(d.axis)
            if along is not None:
                entry["checked"] = True
                k = 0 if along[0] == "x" else 1
                coords = [p[k] for line in drawn for p in line]
                for pos in d.positions:
                    sides = [pos.value]
                    if pos.centre and pos.radius > 0:  # a round feature: both its sides
                        sides = [pos.value - pos.radius, pos.value + pos.radius]
                    for side in sides:
                        want = along[1] * side / MM
                        if not any(abs(c - want) <= tol for c in coords):
                            entry["ok"] = False
                            entry["missing"].append(round(want, 4))
        elif d.kind == "diameter" and d.anchor is not None and d.radius > 0:
            entry["checked"] = True
            cx = sum(a * b for a, b in zip(d.anchor, right, strict=True)) / MM
            cy = sum(a * b for a, b in zip(d.anchor, up, strict=True)) / MM
            r = d.radius / MM
            bins = {
                round(math.degrees(math.atan2(y - cy, x - cx)) / 5.0)
                for x, y, _w in sample(drawn, tol)
                if abs(math.hypot(x - cx, y - cy) - r) <= tol
            }
            if len(bins) < 18:  # a quarter of a circle, in five-degree bins
                entry["ok"] = False
                entry["missing"].append(round(2 * r, 4))
        out.append(entry)
    return out


# --------------------------------------------------------------------------- one part
def cross_check(
    part: str | os.PathLike, *, views=PRINCIPAL, plan: bool = True, tol: float | None = None
) -> dict:
    """The cross-check of the SOLIDWORKS part at ``part``: the drawing model and the STEP
    SolidSeas makes of it, each of ``views`` (principal view names) with hidden lines
    voted on (:func:`vote`), and with ``plan`` the dimensions of the drawing SolidSeas
    plans for it checked against Open CASCADE's lines of its views
    (:func:`dimension_witnesses`). Returns ``{"tol_mm", "occt", "views": {name: vote or
    {"error"}}, "dimensions": [...]}``."""
    from solidseas import open_document
    from solidseas.drawing import pipeline
    from solidseas.drawing import types as T
    from solidseas.drawing import views as V
    from solidseas.step import step_model, write_step

    made = pipeline.run(str(part), until="plan" if plan else "model")
    model = made.model
    planned = made.plan[0] if plan else None  # the plan stage gives (plan, sheet, features)
    frames_of = V.view_frames()
    specs = {n: T.ViewSpec(f"p-{k + 1}", "base", *frames_of[n], n, hidden=True) for k, n in enumerate(views)}
    frames = {n: s.frame() for n, s in specs.items()}
    if planned is not None:
        frames.update({s.id: s.frame() for s in planned.views if s.kind != "isometric"})
    tol = tol if tol is not None else tolerance_mm(model)
    with tempfile.TemporaryDirectory(prefix="solidseas-hlr-") as folder:
        step = os.path.join(folder, "part.step")
        with open_document(str(part)) as doc:
            write_step(step_model(doc, name="part", body_types=("solid", "sheet")), step)
        occt, versions = occt_views(step, frames)
    result: dict = {"tol_mm": tol, "occt": versions.get("occt"), "views": {}, "dimensions": []}
    for name, spec in specs.items():
        theirs = occt.get(name) or {}
        errors = {k: v["error"] for k, v in theirs.items() if isinstance(v, dict) and "error" in v}
        if errors or not theirs:
            result["views"][name] = {"error": errors or "no answer"}
            continue
        result["views"][name] = vote({"ours": ours(V.project(model, spec)), **theirs}, tol)
    if planned is not None:
        planned_views = {k: v for k, v in occt.items() if k not in specs}
        result["dimensions"] = dimension_witnesses(planned, planned_views, tol)
    return result


def main(argv: list[str]) -> int:  # pragma: no cover - a development tool
    for part in argv:
        got = cross_check(part)
        print(f"{part}: OCCT {got['occt']}, lines within {got['tol_mm']:.3f} mm are one")
        for name, r in got["views"].items():
            if "error" in r:
                print(f"  {name}: {r['error']}")
                continue
            for kind in KINDS:
                k = r[kind]
                odd = ", ".join(
                    f"{s} missed {v['missed']:.2f} and alone {v['alone']:.2f} mm"
                    for s, v in k["odd"].items()
                    if v["missed"] or v["alone"]
                )
                said = f"  {name} {kind}: {k['agreed']:.2f} of {k['length']:.2f} mm agreed"
                print(said + (f"; {odd}" if odd else ""))
        checked = [d for d in got["dimensions"] if d["checked"]]
        print(f"  dimensions: {sum(d['ok'] for d in checked)} of {len(checked)} checked are on OCCT's lines")
        for d in checked:
            if not d["ok"]:
                print(f"    {d['id']} ({d['kind']}, {d['view']}): nothing at {d['missing']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
