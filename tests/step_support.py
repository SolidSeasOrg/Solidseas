"""Independent checks of STEP files, for the STEP export's tests.

No STEP reader is installed and nothing external may run, so the tests read the
files themselves. Nothing here imports ``solidseas.step``: the re-reader, the
topology checker and the geometry checker are written from ISO 10303-21 and
ISO 10303-42, with their own evaluators of every curve and surface the writer
may use, so that a mistake in the writer is not repeated here.

* :func:`read` parses a Part 21 exchange structure: the header, every entity
  instance (simple or complex), strings with ``''``, ``\\\\``, ``\\X2\\``, ``\\X4\\``,
  ``\\S\\`` and ``\\X\\``, enumerations, ``$``, ``*``, typed parameters and lists.
* :func:`syntax_problems`: every reference resolves, every instance id is unique,
  every entity name is in :data:`SCHEMA` (a hand-kept list of the
  AUTOMOTIVE_DESIGN entities the writer may use, with the number of attributes
  each record has), complex instances list their records in alphabetical order.
* :func:`topology`: loops close, a closed shell's edges are used exactly twice in
  opposite senses (seam edges inside one face included), an open shell's at most
  so, and each solid's Euler-Poincare characteristic.
* :func:`geometry`: vertices on their edges' curves and on their faces' surfaces.
* :func:`orientation` and :func:`arcs`: against SolidSeas' tessellation of the
  source bodies (verified against SOLIDWORKS' volumes elsewhere), each face's
  normal and each edge's arc.
"""

import bisect
import math
import re
from collections import Counter

# --------------------------------------------------------------------------- the schema subset
# Entity name -> number of attributes in its Part 21 record (for a complex instance's
# partial records, the attributes that entity itself declares). Written from ISO 10303-214's
# AUTOMOTIVE_DESIGN schema and ISO 10303-41, -42 and -43; reviewed by hand.
SCHEMA = {
    "APPLICATION_CONTEXT": 1,
    "APPLICATION_PROTOCOL_DEFINITION": 4,
    "PRODUCT_CONTEXT": 3,
    "PRODUCT_DEFINITION_CONTEXT": 3,
    "PRODUCT": 4,
    "PRODUCT_RELATED_PRODUCT_CATEGORY": 3,
    "PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE": 4,
    "PRODUCT_DEFINITION": 4,
    "PRODUCT_DEFINITION_SHAPE": 3,
    "SHAPE_DEFINITION_REPRESENTATION": 2,
    "ADVANCED_BREP_SHAPE_REPRESENTATION": 3,
    "MANIFOLD_SURFACE_SHAPE_REPRESENTATION": 3,
    "SHAPE_REPRESENTATION": 3,
    "SHAPE_REPRESENTATION_RELATIONSHIP": 4,
    "NEXT_ASSEMBLY_USAGE_OCCURRENCE": 6,
    "CONTEXT_DEPENDENT_SHAPE_REPRESENTATION": 2,
    "ITEM_DEFINED_TRANSFORMATION": 4,
    "UNCERTAINTY_MEASURE_WITH_UNIT": 4,
    "CARTESIAN_POINT": 2,
    "DIRECTION": 2,
    "VECTOR": 3,
    "AXIS1_PLACEMENT": 3,
    "AXIS2_PLACEMENT_3D": 4,
    "LINE": 3,
    "CIRCLE": 3,
    "ELLIPSE": 4,
    "B_SPLINE_CURVE_WITH_KNOTS": 9,
    "PLANE": 2,
    "CYLINDRICAL_SURFACE": 3,
    "CONICAL_SURFACE": 4,
    "SPHERICAL_SURFACE": 3,
    "TOROIDAL_SURFACE": 4,
    "DEGENERATE_TOROIDAL_SURFACE": 5,
    "B_SPLINE_SURFACE_WITH_KNOTS": 13,
    "SURFACE_OF_LINEAR_EXTRUSION": 3,
    "SURFACE_OF_REVOLUTION": 3,
    "OFFSET_SURFACE": 4,
    "VERTEX_POINT": 2,
    "EDGE_CURVE": 5,
    "ORIENTED_EDGE": 5,
    "EDGE_LOOP": 2,
    "VERTEX_LOOP": 2,
    "FACE_OUTER_BOUND": 3,
    "FACE_BOUND": 3,
    "ADVANCED_FACE": 4,
    "CLOSED_SHELL": 2,
    "OPEN_SHELL": 2,
    "ORIENTED_CLOSED_SHELL": 4,
    "MANIFOLD_SOLID_BREP": 2,
    "BREP_WITH_VOIDS": 3,
    "SHELL_BASED_SURFACE_MODEL": 2,
}
# Partial records of the complex instances the writer uses (ISO 10303-21's external mapping:
# each record holds the attributes its own entity declares).
PARTIAL = {
    "LENGTH_UNIT": 0,
    "NAMED_UNIT": 1,
    "SI_UNIT": 2,
    "PLANE_ANGLE_UNIT": 0,
    "SOLID_ANGLE_UNIT": 0,
    "GEOMETRIC_REPRESENTATION_CONTEXT": 1,
    "GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT": 1,
    "GLOBAL_UNIT_ASSIGNED_CONTEXT": 1,
    "REPRESENTATION_CONTEXT": 2,
    "BOUNDED_CURVE": 0,
    "B_SPLINE_CURVE": 5,
    "B_SPLINE_CURVE_WITH_KNOTS": 3,
    "CURVE": 0,
    "GEOMETRIC_REPRESENTATION_ITEM": 0,
    "RATIONAL_B_SPLINE_CURVE": 1,
    "REPRESENTATION_ITEM": 1,
    "BOUNDED_SURFACE": 0,
    "B_SPLINE_SURFACE": 7,
    "B_SPLINE_SURFACE_WITH_KNOTS": 5,
    "RATIONAL_B_SPLINE_SURFACE": 1,
    "SURFACE": 0,
    "REPRESENTATION_RELATIONSHIP": 4,
    "REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION": 1,
    "SHAPE_REPRESENTATION_RELATIONSHIP": 0,
}
CURVES = {"LINE", "CIRCLE", "ELLIPSE", "B_SPLINE_CURVE_WITH_KNOTS", "B_SPLINE_CURVE"}
SURFACES = {
    "PLANE",
    "CYLINDRICAL_SURFACE",
    "CONICAL_SURFACE",
    "SPHERICAL_SURFACE",
    "TOROIDAL_SURFACE",
    "DEGENERATE_TOROIDAL_SURFACE",
    "B_SPLINE_SURFACE_WITH_KNOTS",
    "B_SPLINE_SURFACE",
    "SURFACE_OF_LINEAR_EXTRUSION",
    "SURFACE_OF_REVOLUTION",
    "OFFSET_SURFACE",
}


# --------------------------------------------------------------------------- the re-reader
class Ref(int):
    """An instance name, ``#n``."""


class Enum(str):
    """An enumeration value, ``.NAME.`` (logicals too: T, F, U)."""


class Typed:
    """A typed parameter such as ``LENGTH_MEASURE(1.E-05)``."""

    def __init__(self, name: str, value) -> None:
        self.name, self.value = name, value

    def __repr__(self) -> str:
        return f"{self.name}({self.value!r})"


DERIVED = object()  # *


class Entity:
    """One instance: ``records`` is ``[(name, params)]``, one record for a simple
    instance; ``name`` and ``params`` are the first (or only) record's."""

    def __init__(self, ident: int, records, complex_: bool) -> None:
        self.id, self.records, self.complex = ident, records, complex_
        self.name, self.params = records[0]

    def record(self, name: str):
        for n, p in self.records:
            if n == name:
                return p
        return None

    def has(self, name: str) -> bool:
        return any(n == name for n, _p in self.records)


class Part21Error(ValueError):
    pass


_TOKEN = re.compile(
    r"""\s+|/\*.*?\*/
    |(?P<ref>\#\d+)
    |(?P<string>'(?:[^']|'')*')
    |(?P<binary>"[0-9A-F]*")
    |(?P<enum>\.[A-Z_][A-Z0-9_]*\.)
    |(?P<real>[+-]?\d+\.\d*(?:E[+-]?\d+)?)
    |(?P<int>[+-]?\d+)
    |(?P<keyword>!?[A-Z_][A-Z0-9_]*)
    |(?P<punct>[(),;=$*])
    """,
    re.S | re.X,
)


def _tokens(text: str):
    pos = 0
    n = len(text)
    while pos < n:
        m = _TOKEN.match(text, pos)
        if m is None:
            raise Part21Error(f"cannot read the text at character {pos}: {text[pos : pos + 20]!r}")
        pos = m.end()
        kind = m.lastgroup
        if kind is None:
            continue
        yield kind, m.group(kind)


def decode_string(raw: str) -> str:
    """A Part 21 string literal's text (quotes included in ``raw``)."""
    s = raw[1:-1].replace("''", "'")
    out = []
    i = 0
    while i < len(s):
        if s.startswith("\\X2\\", i):
            j = s.index("\\X0\\", i)
            hexs = s[i + 4 : j]
            if len(hexs) % 4:
                raise Part21Error("a \\X2\\ run of the wrong length")
            out.append("".join(chr(int(hexs[k : k + 4], 16)) for k in range(0, len(hexs), 4)))
            i = j + 4
        elif s.startswith("\\X4\\", i):
            j = s.index("\\X0\\", i)
            hexs = s[i + 4 : j]
            if len(hexs) % 8:
                raise Part21Error("a \\X4\\ run of the wrong length")
            out.append("".join(chr(int(hexs[k : k + 8], 16)) for k in range(0, len(hexs), 8)))
            i = j + 4
        elif s.startswith("\\X\\", i):
            out.append(chr(int(s[i + 3 : i + 5], 16)))
            i += 5
        elif s.startswith("\\S\\", i):
            out.append(chr(ord(s[i + 3]) + 128))
            i += 4
        elif s.startswith("\\\\", i):
            out.append("\\")
            i += 2
        elif s[i] == "\\":
            raise Part21Error(f"an unknown control directive in a string at {i}")
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


class _Parser:
    def __init__(self, text: str) -> None:
        self.toks = list(_tokens(text))
        self.i = 0

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def take(self, kind=None, value=None):
        tok = self.peek()
        if tok[0] is None:
            raise Part21Error("the file ends too soon")
        if (kind and tok[0] != kind) or (value is not None and tok[1] != value):
            raise Part21Error(f"expected {value or kind}, found {tok[1]!r} at token {self.i}")
        self.i += 1
        return tok[1]

    def params(self):
        """A parenthesised parameter list."""
        self.take("punct", "(")
        out = []
        if self.peek() == ("punct", ")"):
            self.i += 1
            return out
        while True:
            out.append(self.param())
            v = self.take("punct")
            if v == ")":
                return out
            if v != ",":
                raise Part21Error(f"expected , or ) and found {v!r}")

    def param(self):
        k, v = self.peek()
        if k == "punct" and v == "(":
            return self.params()
        self.i += 1
        if k == "ref":
            return Ref(int(v[1:]))
        if k == "string":
            return decode_string(v)
        if k == "enum":
            return Enum(v[1:-1])
        if k == "real":
            return float(v)
        if k == "int":
            return int(v)
        if k == "binary":
            return v
        if k == "punct" and v == "$":
            return None
        if k == "punct" and v == "*":
            return DERIVED
        if k == "keyword":
            inner = self.params()
            if len(inner) != 1:
                raise Part21Error(f"a typed parameter {v} with {len(inner)} values")
            return Typed(v, inner[0])
        raise Part21Error(f"unexpected {v!r} as a parameter")

    def record(self):
        name = self.take("keyword")
        return name, self.params()


class File:
    """A parsed exchange structure: ``header`` (``[(name, params)]``) and ``entities``
    (id -> :class:`Entity`)."""

    def __init__(self, header, entities) -> None:
        self.header, self.entities = header, entities

    def get(self, ref) -> Entity:
        return self.entities[int(ref)]

    def of(self, name: str) -> list[Entity]:
        return [e for e in self.entities.values() if e.name == name or (e.complex and e.has(name))]

    def header_record(self, name: str):
        for n, p in self.header:
            if n == name:
                return p
        return None


def read(data) -> File:
    """Parse a Part 21 file (bytes, ASCII, or text)."""
    text = data.decode("ascii") if isinstance(data, (bytes, bytearray)) else data
    if not text.startswith("ISO-10303-21;"):
        raise Part21Error("the file does not start with ISO-10303-21;")
    body = text[len("ISO-10303-21;") :]
    end = body.rfind("END-ISO-10303-21;")
    if end < 0 or body[end + len("END-ISO-10303-21;") :].strip():
        raise Part21Error("the file does not end with END-ISO-10303-21;")
    p = _Parser(body[:end])
    p.take("keyword", "HEADER")
    p.take("punct", ";")
    header = []
    while p.peek() != ("keyword", "ENDSEC"):
        header.append(p.record())
        p.take("punct", ";")
    p.take("keyword", "ENDSEC")
    p.take("punct", ";")
    entities: dict[int, Entity] = {}
    while p.peek()[0] is not None:
        p.take("keyword", "DATA")
        if p.peek() == ("punct", "("):
            p.params()
        p.take("punct", ";")
        while p.peek() != ("keyword", "ENDSEC"):
            ident = int(p.take("ref")[1:])
            p.take("punct", "=")
            if p.peek() == ("punct", "("):
                p.i += 1
                records = []
                while p.peek() != ("punct", ")"):
                    records.append(p.record())
                p.take("punct", ")")
                ent = Entity(ident, records, True)
            else:
                ent = Entity(ident, [p.record()], False)
            p.take("punct", ";")
            if ident in entities:
                raise Part21Error(f"#{ident} is defined twice")
            entities[ident] = ent
        p.take("keyword", "ENDSEC")
        p.take("punct", ";")
    return File(header, entities)


def _refs(value):
    if isinstance(value, Ref):
        yield value
    elif isinstance(value, list):
        for v in value:
            yield from _refs(v)
    elif isinstance(value, Typed):
        yield from _refs(value.value)


def syntax_problems(f: File) -> list[str]:
    """What is wrong with the file as Part 21 of the schema subset: unknown entity
    names, wrong attribute counts, references to no instance, complex instances out of
    order, and the header's three records."""
    out = []
    names = [n for n, _p in f.header]
    if names != ["FILE_DESCRIPTION", "FILE_NAME", "FILE_SCHEMA"]:
        out.append(f"header records {names}")
    for e in f.entities.values():
        if e.complex:
            rec_names = [n for n, _p in e.records]
            if rec_names != sorted(rec_names):
                out.append(f"#{e.id}: complex records not in alphabetical order")
            for n, params in e.records:
                if n not in PARTIAL:
                    out.append(f"#{e.id}: {n} is not a partial record the schema subset knows")
                elif len(params) != PARTIAL[n]:
                    out.append(f"#{e.id}: {n} has {len(params)} attributes, not {PARTIAL[n]}")
        else:
            if e.name not in SCHEMA:
                out.append(f"#{e.id}: {e.name} is not in the schema subset")
            elif len(e.params) != SCHEMA[e.name]:
                out.append(f"#{e.id}: {e.name} has {len(e.params)} attributes, not {SCHEMA[e.name]}")
        for _n, params in e.records:
            for r in _refs(params):
                if int(r) not in f.entities:
                    out.append(f"#{e.id} refers to #{int(r)}, which is not there")
    return out


# --------------------------------------------------------------------------- vectors
def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a):
    return math.sqrt(_dot(a, a))


def _unit(a):
    n = _norm(a)
    return (a[0] / n, a[1] / n, a[2] / n)


def _dist(a, b):
    return _norm(_sub(a, b))


def _golden(f, a, b, iters=80):
    """The minimum of ``f`` on ``[a, b]``, taken to have one there, by golden-section
    search (Kiefer, 1953), written for these tests: ``x`` holds the bracket's ends and its
    two inner points, ``y`` the values at the inner points; each round keeps the side of
    the lower value and reuses the inner point that falls in it."""
    r = (3.0 - math.sqrt(5.0)) / 2.0  # the shorter golden section of a unit length
    x = [a, a + r * (b - a), b - r * (b - a), b]
    y = [f(x[1]), f(x[2])]
    for _ in range(iters):
        if y[0] <= y[1]:  # the minimum lies in [x0, x2]
            x = [x[0], x[0] + r * (x[2] - x[0]), x[1], x[2]]
            y = [f(x[1]), y[0]]
        else:  # in [x1, x3]
            x = [x[1], x[2], x[3] - r * (x[3] - x[1]), x[3]]
            y = [y[1], f(x[2])]
    return (x[0] + x[3]) / 2.0


# --------------------------------------------------------------------------- ISO 10303-42 evaluators
class Frame:
    """An AXIS2_PLACEMENT_3D: origin, x, y and z (ISO 10303-42 4.4.4)."""

    def __init__(self, f: File, ref) -> None:
        e = f.get(ref)
        assert e.name == "AXIS2_PLACEMENT_3D", e.name
        self.o = tuple(f.get(e.params[1]).params[1])
        z = _unit(tuple(f.get(e.params[2]).params[1])) if e.params[2] is not None else (0.0, 0.0, 1.0)
        a = tuple(f.get(e.params[3]).params[1]) if e.params[3] is not None else (1.0, 0.0, 0.0)
        x = _sub(a, _mul(z, _dot(a, z)))
        self.x = _unit(x)
        self.z = z
        self.y = _cross(z, self.x)


def _basis(knots, degree, t, i):
    """N_{i,degree}(t) by the Cox-de Boor recursion over a full knot vector."""
    n = len(knots) - degree - 1
    if degree == 0:
        if knots[i] <= t < knots[i + 1]:
            return 1.0
        # the end of the range belongs to the last non-empty span
        if (
            t == knots[-1]
            and knots[i] < knots[i + 1] == knots[-1]
            and i == max(j for j in range(n) if knots[j] < knots[j + 1])
        ):
            return 1.0
        return 0.0
    out = 0.0
    d1 = knots[i + degree] - knots[i]
    if d1 > 0:
        out += (t - knots[i]) / d1 * _basis(knots, degree - 1, t, i)
    d2 = knots[i + degree + 1] - knots[i + 1]
    if d2 > 0:
        out += (knots[i + degree + 1] - t) / d2 * _basis(knots, degree - 1, t, i + 1)
    return out


def _full(mults, knots):
    return [k for k, m in zip(knots, mults, strict=True) for _ in range(m)]


def _span(knots, degree, n, t):
    """The index i of the knot span [knots[i], knots[i + 1]) holding t, between degree
    and n - 1 (n control points); the end of the range belongs to the last span. Only
    N_{i - degree} to N_i are non-zero there."""
    if t >= knots[n]:
        i = n - 1
        while i > degree and knots[i] == knots[i + 1]:
            i -= 1
        return i
    return min(max(bisect.bisect_right(knots, t) - 1, degree), n - 1)


def _samples(knots, degree, n, limit=None):
    """Parameters spread over every non-empty knot span (two to eight a span), thinned
    to at most ``limit`` with both ends kept."""
    ks = sorted(set(knots[degree : n + 1]))
    spans = max(1, len(ks) - 1)
    each = max(2, min(8, 64 // spans))
    out = []
    for a, b in zip(ks, ks[1:], strict=False):
        out.extend(a + (b - a) * j / each for j in range(each))
    out.append(ks[-1])
    if limit is not None and len(out) > limit:
        k = len(out) // limit + 1
        out = out[::k] + ([out[-1]] if (len(out) - 1) % k else [])
    return out


def _grid_params(b, budget=20000):
    """The (u, v) samples of a B-spline surface's search grid: every span sampled in
    both directions while the grid stays within ``budget`` points, else the longer
    direction thinned."""
    us = _samples(b.U, b.pu, len(b.P))
    vs = _samples(b.V, b.pv, len(b.P[0]))
    if len(us) * len(vs) > budget:
        if len(us) >= len(vs):
            us = _samples(b.U, b.pu, len(b.P), max(64, budget // len(vs)))
        else:
            vs = _samples(b.V, b.pv, len(b.P[0]), max(64, budget // len(us)))
    return us, vs


class BSplineCurve:
    def __init__(self, degree, points, mults, knots, weights=None) -> None:
        self.p, self.P, self.w = degree, points, weights
        self.U = _full(mults, knots)
        self.lo, self.hi = self.U[degree], self.U[len(points)]

    def point(self, t):
        t = min(max(t, self.lo), self.hi)
        acc = [0.0, 0.0, 0.0]
        wsum = 0.0
        sp = _span(self.U, self.p, len(self.P), t)
        for i in range(sp - self.p, sp + 1):
            c = self.P[i]
            b = _basis(self.U, self.p, t, i)
            if b == 0.0:
                continue
            w = self.w[i] if self.w else 1.0
            for k in range(3):
                acc[k] += b * w * c[k]
            wsum += b * w
        return (acc[0] / wsum, acc[1] / wsum, acc[2] / wsum)


class Curve:
    """A curve entity: ``point(t)``, ``closest(p) -> (t, distance)`` and ``period``."""

    def __init__(self, f: File, ref) -> None:
        e = f.get(ref)
        self.kind = e.name if not e.complex else "B_SPLINE_CURVE"
        self.period = None
        if e.name == "LINE":
            self.o = tuple(f.get(e.params[1]).params[1])
            v = f.get(e.params[2])
            self.d = _mul(_unit(tuple(f.get(v.params[1]).params[1])), v.params[2])
        elif e.name in ("CIRCLE", "ELLIPSE"):
            self.fr = Frame(f, e.params[1])
            self.a = e.params[2]
            self.b = e.params[3] if e.name == "ELLIPSE" else e.params[2]
            self.period = 2.0 * math.pi
        elif e.name == "B_SPLINE_CURVE_WITH_KNOTS" and not e.complex:
            pts = [tuple(f.get(r).params[1]) for r in e.params[2]]
            self.s = BSplineCurve(e.params[1], pts, e.params[6], e.params[7])
        elif e.complex and e.has("B_SPLINE_CURVE"):
            bc = e.record("B_SPLINE_CURVE")
            kn = e.record("B_SPLINE_CURVE_WITH_KNOTS")
            ws = e.record("RATIONAL_B_SPLINE_CURVE")
            pts = [tuple(f.get(r).params[1]) for r in bc[1]]
            self.s = BSplineCurve(bc[0], pts, kn[0], kn[1], ws[0] if ws else None)
        else:
            raise AssertionError(f"#{e.id}: {e.name} is not a curve the checker knows")

    def point(self, t):
        if self.kind == "LINE":
            return _add(self.o, _mul(self.d, t))
        if self.kind in ("CIRCLE", "ELLIPSE"):
            fr = self.fr
            return _add(fr.o, _add(_mul(fr.x, self.a * math.cos(t)), _mul(fr.y, self.b * math.sin(t))))
        return self.s.point(t)

    def tangent(self, t):
        h = 1e-6 * (1.0 + abs(t))
        return _mul(_sub(self.point(t + h), self.point(t - h)), 0.5 / h)

    def closest(self, p):
        if self.kind == "LINE":
            t = _dot(_sub(p, self.o), self.d) / _dot(self.d, self.d)
            return t, _dist(self.point(t), p)
        if self.kind in ("CIRCLE", "ELLIPSE"):
            q = _sub(p, self.fr.o)
            t0 = math.atan2(_dot(q, self.fr.y) / self.b, _dot(q, self.fr.x) / self.a)
            if self.kind == "ELLIPSE":
                t0 = _golden(lambda t: _dist(self.point(t), p), t0 - 0.5, t0 + 0.5)
            return t0, _dist(self.point(t0), p)
        s = self.s
        n = 64 * max(1, len(s.P))
        n = min(n, 4096)
        best = min(range(n + 1), key=lambda i: _dist(s.point(s.lo + (s.hi - s.lo) * i / n), p))
        h = (s.hi - s.lo) / n
        t = _golden(
            lambda t: _dist(s.point(t), p), max(s.lo, s.lo + (best - 1) * h), min(s.hi, s.lo + (best + 1) * h)
        )
        return t, _dist(s.point(t), p)

    def bounds(self):
        return (self.s.lo, self.s.hi) if self.kind.startswith("B_SPLINE") else None


class BSplineSurface:
    def __init__(self, pu, pv, grid, um, vm, uk, vk, weights=None) -> None:
        self.pu, self.pv, self.P, self.w = pu, pv, grid, weights
        self.U, self.V = _full(um, uk), _full(vm, vk)
        self.ulo, self.uhi = self.U[pu], self.U[len(grid)]
        self.vlo, self.vhi = self.V[pv], self.V[len(grid[0])]

    def point(self, u, v):
        u = min(max(u, self.ulo), self.uhi)
        v = min(max(v, self.vlo), self.vhi)
        su = _span(self.U, self.pu, len(self.P), u)
        sv = _span(self.V, self.pv, len(self.P[0]), v)
        nu = [(i, _basis(self.U, self.pu, u, i)) for i in range(su - self.pu, su + 1)]
        nv = [(j, _basis(self.V, self.pv, v, j)) for j in range(sv - self.pv, sv + 1)]
        acc = [0.0, 0.0, 0.0]
        wsum = 0.0
        for i, bi in nu:
            if bi == 0.0:
                continue
            for j, bj in nv:
                if bj == 0.0:
                    continue
                w = self.w[i][j] if self.w else 1.0
                c = self.P[i][j]
                for k in range(3):
                    acc[k] += bi * bj * w * c[k]
                wsum += bi * bj * w
        return (acc[0] / wsum, acc[1] / wsum, acc[2] / wsum)


class Surface:
    """A surface entity: ``closest(p) -> (distance, unit natural normal at the nearest
    point or None)``."""

    def __init__(self, f: File, ref) -> None:
        e = f.get(ref)
        self.kind = e.name if not e.complex else "B_SPLINE_SURFACE"
        if e.name in ("PLANE", "CYLINDRICAL_SURFACE", "CONICAL_SURFACE", "SPHERICAL_SURFACE"):
            self.fr = Frame(f, e.params[1])
            self.r = e.params[2] if len(e.params) > 2 else None
            self.angle = e.params[3] if e.name == "CONICAL_SURFACE" else None
        elif e.name in ("TOROIDAL_SURFACE", "DEGENERATE_TOROIDAL_SURFACE"):
            self.fr = Frame(f, e.params[1])
            self.R, self.r = e.params[2], e.params[3]
            self.outer = e.params[4] == "T" if e.name == "DEGENERATE_TOROIDAL_SURFACE" else None
        elif e.name == "B_SPLINE_SURFACE_WITH_KNOTS" and not e.complex:
            grid = [[tuple(f.get(r).params[1]) for r in row] for row in e.params[3]]
            self.s = BSplineSurface(
                e.params[1], e.params[2], grid, e.params[8], e.params[9], e.params[10], e.params[11]
            )
        elif e.complex and e.has("B_SPLINE_SURFACE"):
            bs = e.record("B_SPLINE_SURFACE")
            kn = e.record("B_SPLINE_SURFACE_WITH_KNOTS")
            ws = e.record("RATIONAL_B_SPLINE_SURFACE")
            grid = [[tuple(f.get(r).params[1]) for r in row] for row in bs[2]]
            self.s = BSplineSurface(bs[0], bs[1], grid, kn[0], kn[1], kn[2], kn[3], ws[0] if ws else None)
        elif e.name == "SURFACE_OF_LINEAR_EXTRUSION":
            self.c = Curve(f, e.params[1])
            v = f.get(e.params[2])
            self.V = _mul(_unit(tuple(f.get(v.params[1]).params[1])), v.params[2])
        elif e.name == "SURFACE_OF_REVOLUTION":
            self.c = Curve(f, e.params[1])
            ax = f.get(e.params[2])
            self.A = tuple(f.get(ax.params[1]).params[1])
            self.a = _unit(tuple(f.get(ax.params[2]).params[1]))
        elif e.name == "OFFSET_SURFACE":
            self.base = Surface(f, e.params[1])
            self.d = e.params[2]
        else:
            raise AssertionError(f"#{e.id}: {e.name} is not a surface the checker knows")

    # each surface's own closest point and natural normal
    def closest(self, p):
        k = self.kind
        if k == "PLANE":
            fr = self.fr
            return abs(_dot(_sub(p, fr.o), fr.z)), fr.z
        if k in (
            "CYLINDRICAL_SURFACE",
            "CONICAL_SURFACE",
            "SPHERICAL_SURFACE",
            "TOROIDAL_SURFACE",
            "DEGENERATE_TOROIDAL_SURFACE",
        ):
            fr = self.fr
            q = _sub(p, fr.o)
            h = _dot(q, fr.z)
            radial = _sub(q, _mul(fr.z, h))
            rho = _norm(radial)
            e = _mul(radial, 1.0 / rho) if rho > 0 else fr.x
            if k == "CYLINDRICAL_SURFACE":
                return abs(rho - self.r), e
            if k == "SPHERICAL_SURFACE":
                return abs(_norm(q) - self.r), _unit(q)
            if k == "CONICAL_SURFACE":
                ta = math.tan(self.angle)
                # sigma = C + v z + (R + v tan a) e(u), both nappes: in the plane through
                # the axis and p, the line rho = R + v tan a with rho signed, so p is
                # (rho_p, h) at u = u_p or (-rho_p, h) at u = u_p + pi; the natural normal
                # is (R + v tan a)(e(u) - tan a z).
                ca = 1.0 / math.sqrt(1.0 + ta * ta)
                best = None
                for side in (1.0, -1.0):
                    q = side * rho
                    d = abs((q - self.r) * ca - h * ta * ca)
                    if best is None or d < best[0]:
                        best = (d, side, ((q - self.r) * ta * ca + h * ca) * ca)
                d, side, v = best
                n = _unit(_sub(_mul(e, side), _mul(fr.z, ta)))
                if self.r + v * ta < 0:
                    n = _mul(n, -1.0)
                return d, n
            R, r = self.R, self.r
            # the generating circle on p's side (u = u_p) and on the far side (u_p + pi)
            near = abs(math.hypot(rho - R, h) - r)
            far = abs(math.hypot(-rho - R, h) - r)
            if self.outer is None:  # the whole torus: whichever side is nearer
                use_far = far < near
            else:  # the apple (outer) is on p's side, the lemon (inner) on the far one
                use_far = not self.outer
            if not use_far:
                v = math.atan2(h, rho - R)
                n = _add(_mul(e, math.cos(v)), _mul(fr.z, math.sin(v)))
                if R + r * math.cos(v) < 0:
                    n = _mul(n, -1.0)
                return near, n
            # u = u_p + pi: e(u) = -e; the point -(R + r cos v) e + r sin v z
            v = math.atan2(h, -rho - R)
            eu = _mul(e, -1.0)
            n = _add(_mul(eu, math.cos(v)), _mul(fr.z, math.sin(v)))
            if R + r * math.cos(v) < 0:
                n = _mul(n, -1.0)
            return far, n
        if k == "B_SPLINE_SURFACE_WITH_KNOTS" or k == "B_SPLINE_SURFACE":
            b = self.s
            if getattr(self, "_grid", None) is None:
                us, vs = _grid_params(b)
                self._grid = (us, vs, [[b.point(u, v) for v in vs] for u in us])
            return self._param_closest(p, b.point, (b.ulo, b.uhi, b.vlo, b.vhi), self._grid)
        if k == "SURFACE_OF_LINEAR_EXTRUSION":
            c = self.c
            V = self.V
            vv = _dot(V, V)

            def line_dist(u):
                q = _sub(p, c.point(u))
                return _norm(_sub(q, _mul(V, _dot(q, V) / vv)))

            lo, hi = c.bounds() or (-1e3, 1e3)
            if c.period:
                lo, hi = 0.0, c.period
            u = _scan(line_dist, lo, hi)
            v = _dot(_sub(p, c.point(u)), V) / vv
            n = _cross(c.tangent(u), V)
            return line_dist(u), _unit(n) if _norm(n) > 0 else None
        if k == "SURFACE_OF_REVOLUTION":
            c, A, a = self.c, self.A, self.a

            def polar(q):
                d = _sub(q, A)
                h = _dot(d, a)
                return math.hypot(*_sub(d, _mul(a, h))[:2], _sub(d, _mul(a, h))[2]), h

            rp, hp = polar(p)

            def d2(v):
                rc, hc = polar(c.point(v))
                return math.hypot(rc - rp, hc - hp)

            lo, hi = c.bounds() or (0.0, 2.0 * math.pi)
            v = _scan(d2, lo, hi)
            q = c.point(v)
            # turn q about the axis onto p's side, and the tangent with it
            dq = _sub(q, A)
            rq = _sub(dq, _mul(a, _dot(dq, a)))
            dp = _sub(p, A)
            rpv = _sub(dp, _mul(a, _dot(dp, a)))
            if _norm(rq) == 0 or _norm(rpv) == 0:
                return d2(v), None
            ang = math.atan2(_dot(a, _cross(rq, rpv)), _dot(rq, rpv))
            qq = _rotate(dq, a, ang)
            su = _cross(a, qq)
            sv = _rotate(c.tangent(v), a, ang)
            n = _cross(su, sv)
            return d2(v), _unit(n) if _norm(n) > 0 else None
        if k == "OFFSET_SURFACE":
            d, n = self.base.closest(p)
            if n is None:
                return math.inf, None
            # p on the offset lies at self.d along the basis normal from its foot
            return abs(d - abs(self.d)), n
        raise AssertionError(k)

    def near(self, p, uv=None):
        """(distance, (u, v) or None): on a B-spline surface from ``uv`` (the foot of the
        point before, along an edge) by Gauss-Newton steps alone, which gives a point of the
        surface and so a distance at least the true one; the full search without ``uv``,
        and on every other surface."""
        if self.kind not in ("B_SPLINE_SURFACE_WITH_KNOTS", "B_SPLINE_SURFACE"):
            return self.closest(p)[0], None
        b = self.s
        box = (b.ulo, b.uhi, b.vlo, b.vhi)
        if uv == "grid":  # from the search grid's nearest sample
            if getattr(self, "_grid", None) is None:
                us, vs = _grid_params(b)
                self._grid = (us, vs, [[b.point(u, v) for v in vs] for u in us])
            us, vs, pts = self._grid
            _d, i, j = min((_dist(pts[i][j], p), i, j) for i in range(len(us)) for j in range(len(vs)))
            uv = (us[i], vs[j])
        if uv is not None:
            u, v = _gauss_newton(b.point, p, uv[0], uv[1], box)
            return _dist(b.point(u, v), p), (u, v)
        d, _n = self.closest(p)
        return d, self._last_uv

    def _param_closest(self, p, S, box, grid):
        """The nearest point of S over ``box`` to p: the grid's nearest few samples (the
        grid spread over every knot span), each refined by golden-section searches in u
        and in v within its neighbouring samples, shrinking; the best of them."""
        u0, u1, v0, v1 = box
        us, vs, pts = grid
        cands = sorted((_dist(pts[i][j], p), i, j) for i in range(len(us)) for j in range(len(vs)))[:6]
        best = None
        for _d, i, j in cands:
            u, v = us[i], vs[j]
            ulo, uhi = us[max(i - 1, 0)], us[min(i + 1, len(us) - 1)]
            vlo, vhi = vs[max(j - 1, 0)], vs[min(j + 1, len(vs) - 1)]
            hu, hv = max(u - ulo, uhi - u), max(v - vlo, vhi - v)
            for _ in range(60):  # coordinate-wise golden search, shrinking
                u = _golden(lambda x, v=v: _dist(S(x, v), p), max(u0, u - hu), min(u1, u + hu), 40)
                v = _golden(lambda y, u=u: _dist(S(u, y), p), max(v0, v - hv), min(v1, v + hv), 40)
                hu, hv = hu * 0.5, hv * 0.5
                if hu < 1e-14 * (u1 - u0) and hv < 1e-14 * (v1 - v0):
                    break
            u, v = _gauss_newton(S, p, u, v, box)
            d = _dist(S(u, v), p)
            if best is None or d < best[0]:
                best = (d, u, v)
        d, u, v = best
        self._last_uv = (u, v)
        eu = 1e-6 * (u1 - u0)
        ev = 1e-6 * (v1 - v0)
        su = _sub(S(min(u + eu, u1), v), S(max(u - eu, u0), v))
        sv = _sub(S(u, min(v + ev, v1)), S(u, max(v - ev, v0)))
        n = _cross(su, sv)
        return d, _unit(n) if _norm(n) > 0 else None


def _gauss_newton(S, p, u, v, box, rounds=20):
    """Gauss-Newton steps towards the foot of p on S from (u, v), derivatives by central
    differences, kept in ``box``; each step taken only when it brings the point nearer
    (coordinate-wise searches crawl along a diagonal valley)."""
    u0, u1, v0, v1 = box
    eu, ev = 1e-7 * (u1 - u0), 1e-7 * (v1 - v0)
    d = _dist(S(u, v), p)
    for _ in range(rounds):
        q = S(u, v)
        ua, ub = max(u - eu, u0), min(u + eu, u1)
        va, vb = max(v - ev, v0), min(v + ev, v1)
        su = _mul(_sub(S(ub, v), S(ua, v)), 1.0 / (ub - ua))
        sv = _mul(_sub(S(u, vb), S(u, va)), 1.0 / (vb - va))
        r = _sub(p, q)
        a, b, c = _dot(su, su), _dot(su, sv), _dot(sv, sv)
        det = a * c - b * b
        if not det > 0.0:
            break
        g1, g2 = _dot(su, r), _dot(sv, r)
        du, dv = (c * g1 - b * g2) / det, (a * g2 - b * g1) / det
        nu, nv = min(max(u + du, u0), u1), min(max(v + dv, v0), v1)
        nd = _dist(S(nu, nv), p)
        if not nd < d:
            break
        u, v, d = nu, nv, nd
    return u, v


def _rotate(q, a, ang):
    c, s = math.cos(ang), math.sin(ang)
    return _add(_add(_mul(q, c), _mul(_cross(a, q), s)), _mul(a, _dot(a, q) * (1.0 - c)))


def _scan(f, lo, hi, n=256):
    best = min(range(n + 1), key=lambda i: f(lo + (hi - lo) * i / n))
    h = (hi - lo) / n
    return _golden(f, max(lo, lo + (best - 1) * h), min(hi, lo + (best + 1) * h))


# --------------------------------------------------------------------------- topology
class Solid:
    """One solid's (or surface model's) counts and its shells' edge uses."""

    def __init__(self, entity: Entity) -> None:
        self.entity = entity
        self.name = entity.params[0]
        self.shells: list[tuple[int, bool]] = []  # (shell id, closed)
        self.V = self.E = self.F = self.L = 0

    def euler(self) -> int:
        """V - E + F - (L - F) - 2 S: zero less twice the genus (summed over shells)."""
        return self.V - self.E + self.F - (self.L - self.F) - 2 * len(self.shells)

    @property
    def genus(self) -> float:
        return -self.euler() / 2.0


def _oriented_ends(f: File, oe: Entity):
    ec = f.get(oe.params[3])
    s, e = int(ec.params[1]), int(ec.params[2])
    return (s, e) if oe.params[4] == "T" else (e, s)


def shell_faces(f: File, shell: Entity) -> list[Entity]:
    return [f.get(r) for r in shell.params[1]]


def topology(f: File) -> tuple[list[Solid], list[str]]:
    """Each solid and surface model, with what is wrong with its topology."""
    problems: list[str] = []
    solids = []
    for e in f.entities.values():
        if e.name not in ("MANIFOLD_SOLID_BREP", "BREP_WITH_VOIDS", "SHELL_BASED_SURFACE_MODEL"):
            continue
        s = Solid(e)
        if e.name == "SHELL_BASED_SURFACE_MODEL":
            shells = [(int(r), f.get(r).name == "CLOSED_SHELL") for r in e.params[1]]
        else:
            shells = [(int(e.params[1]), True)]
            for r in e.params[2] if e.name == "BREP_WITH_VOIDS" else []:
                ocs = f.get(r)
                if ocs.name != "ORIENTED_CLOSED_SHELL":
                    problems.append(f"#{e.id}: a void that is not an ORIENTED_CLOSED_SHELL")
                    continue
                shells.append((int(ocs.params[2]), True))
        s.shells = shells
        vertices, edges = set(), set()
        for sid, closed in shells:
            sh = f.get(sid)
            if sh.name != ("CLOSED_SHELL" if closed else "OPEN_SHELL"):
                problems.append(f"#{sid}: a {sh.name} where a {'closed' if closed else 'open'} shell belongs")
            uses = Counter()
            for face in shell_faces(f, sh):
                if face.name != "ADVANCED_FACE":
                    problems.append(f"#{face.id}: {face.name} in a shell")
                    continue
                s.F += 1
                bounds = [f.get(b) for b in face.params[1]]
                if sum(1 for b in bounds if b.name == "FACE_OUTER_BOUND") > 1:
                    problems.append(f"#{face.id}: more than one outer bound")
                for b in bounds:
                    s.L += 1
                    loop = f.get(b.params[1])
                    bor = b.params[2] == "T"
                    if loop.name == "VERTEX_LOOP":
                        vertices.add(int(loop.params[1]))
                        continue
                    if loop.name != "EDGE_LOOP":
                        problems.append(f"#{loop.id}: {loop.name} as a loop")
                        continue
                    oes = [f.get(r) for r in loop.params[1]]
                    ends = [_oriented_ends(f, oe) for oe in oes]
                    if not bor:
                        ends = [(b_, a_) for a_, b_ in reversed(ends)]
                    for k in range(len(ends)):
                        if ends[k][1] != ends[(k + 1) % len(ends)][0]:
                            problems.append(f"#{loop.id}: the loop does not close after its edge {k}")
                    for oe in oes:
                        ec = int(oe.params[3])
                        edges.add(ec)
                        ece = f.get(ec)
                        vertices.add(int(ece.params[1]))
                        vertices.add(int(ece.params[2]))
                        forward = (oe.params[4] == "T") == bor
                        uses[(ec, forward)] += 1
            for ec in {k[0] for k in uses}:
                a, b = uses[(ec, True)], uses[(ec, False)]
                if closed and (a, b) != (1, 1):
                    problems.append(f"#{ec}: used {a} forward and {b} backward in closed shell #{sid}")
                if not closed and (a > 1 or b > 1):
                    problems.append(f"#{ec}: used twice one way in open shell #{sid}")
        s.V, s.E = len(vertices), len(edges)
        solids.append(s)
    return solids, problems


# --------------------------------------------------------------------------- geometry
def uncertainty_mm(f: File) -> float:
    (u,) = [e for e in f.entities.values() if e.name == "UNCERTAINTY_MEASURE_WITH_UNIT"][:1]
    v = u.params[0]
    return v.value if isinstance(v, Typed) else v


def point_of_vertex(f: File, ref):
    v = f.get(ref)
    return tuple(f.get(v.params[1]).params[1])


def geometry(f: File, allowance_mm: float) -> dict:
    """Vertices on their edges' curves and on their faces' surfaces: the largest
    distances (mm) and the cases beyond ``allowance_mm``."""
    out = {"vertex_curve_max": 0.0, "vertex_surface_max": 0.0, "beyond": []}
    curves: dict[int, Curve] = {}
    for e in f.entities.values():
        if e.name != "EDGE_CURVE":
            continue
        c = curves.setdefault(int(e.params[3]), Curve(f, e.params[3]))
        for vr in (e.params[1], e.params[2]):
            _t, d = c.closest(point_of_vertex(f, vr))
            out["vertex_curve_max"] = max(out["vertex_curve_max"], d)
            if d > allowance_mm:
                out["beyond"].append(("vertex_curve", e.id, d))
    for face in f.entities.values():
        if face.name != "ADVANCED_FACE":
            continue
        s = Surface(f, face.params[2])
        seen = set()
        for b in face.params[1]:
            loop = f.get(f.get(b).params[1])
            if loop.name == "VERTEX_LOOP":
                vs = [loop.params[1]]
            else:
                vs = []
                for r in loop.params[1]:
                    ec = f.get(f.get(r).params[3])
                    vs.extend([ec.params[1], ec.params[2]])
            for vr in vs:
                if int(vr) in seen:
                    continue
                seen.add(int(vr))
                d, _n = s.closest(point_of_vertex(f, vr))
                out["vertex_surface_max"] = max(out["vertex_surface_max"], d)
                if d > allowance_mm:
                    out["beyond"].append(("vertex_surface", face.id, d))
    return out


def _edge_params(f: File, ec: Entity, c: "Curve", n: int) -> list[float]:
    """``n`` parameters of the curve strictly between an EDGE_CURVE's two vertices, the
    way the edge runs."""
    ps, pe = point_of_vertex(f, ec.params[1]), point_of_vertex(f, ec.params[2])
    ts, _ = c.closest(ps)
    te, _ = c.closest(pe)
    sign = 1.0 if ec.params[4] == "T" else -1.0
    ring = ec.params[1] == ec.params[2]
    if c.period:
        step = ((te - ts) * sign) % c.period
        if ring or step < 1e-12:
            step = c.period
        span = sign * step
    else:
        if ring:
            lo, hi = c.bounds()
            ts, te = (lo, hi) if sign > 0 else (hi, lo)
        span = te - ts
    return [ts + span * (k / (n + 1)) for k in range(1, n + 1)]


def edges_on_faces(f: File, allowance_mm: float, per_edge: int = 12) -> dict:
    """Points along every edge between its vertices on the surface of each face it
    bounds: the largest distance (mm) and the (edge, face, distance) beyond
    ``allowance_mm``. A surface that stops short of its face's boundary, or an edge that
    leaves its face between its vertices, shows here and not in :func:`geometry`."""
    out = {"edge_surface_max": 0.0, "beyond": []}
    curves: dict[int, Curve] = {}
    surfaces: dict[int, Surface] = {}
    params: dict[int, list] = {}
    for face in f.entities.values():
        if face.name != "ADVANCED_FACE":
            continue
        s = surfaces.get(int(face.params[2]))
        if s is None:
            s = surfaces[int(face.params[2])] = Surface(f, face.params[2])
        for b in face.params[1]:
            loop = f.get(f.get(b).params[1])
            if loop.name != "EDGE_LOOP":
                continue
            for r in loop.params[1]:
                ec = f.get(f.get(r).params[3])
                c = curves.setdefault(int(ec.params[3]), Curve(f, ec.params[3]))
                if ec.id not in params:
                    params[ec.id] = [c.point(t) for t in _edge_params(f, ec, c, per_edge)]
                uv = "grid"
                for p in params[ec.id]:
                    d, uv = s.near(p, uv)
                    if d > allowance_mm and uv is not None:  # the quick steps missed: search
                        d, uv = s.near(p)
                    out["edge_surface_max"] = max(out["edge_surface_max"], d)
                    if d > allowance_mm:
                        out["beyond"].append((ec.id, face.id, d))
    return out


def face_normal(f: File, face: Entity, p):
    """The STEP face's normal at the surface point nearest ``p`` (mm): the natural
    normal times the face's same_sense; with the distance to the surface."""
    s = Surface(f, face.params[2])
    d, n = s.closest(p)
    if n is None:
        return d, None
    return d, n if face.params[3] == "T" else _mul(n, -1.0)


def orientation(f: File, face_map: dict, index: dict, samples: int = 48) -> dict:
    """For each STEP face paired with a source face (``face_map``: STEP id -> (body,
    FACE node id)) that SolidSeas tessellated (``index``, from
    :func:`tessellation_index`): whether its normal agrees with the tessellation's
    outward normal, by area at the centres of about ``samples`` triangles spread over
    the face (single triangles can be turned round where the tessellator follows the
    ring of a face thinner than its tolerance). Returns counts and the disagreeing
    faces."""
    out = {"faces": 0, "agree": 0, "disagree": [], "not_tessellated": 0, "far": 0}
    for sid, (body, node_id) in face_map.items():
        got = index.get((body, node_id))
        if got is None:
            out["not_tessellated"] += 1
            continue
        t, ft = got
        m = t.mesh
        tris = []
        for k in range(ft.first_triangle, ft.first_triangle + ft.n_triangles):
            a, b, c = (m.vertex(m.triangles[3 * k + j]) for j in range(3))
            n = _cross(_sub(b, a), _sub(c, a))
            area = _norm(n)
            if area > 0.0:
                tris.append((area, a, b, c, n))
        if not tris:
            out["not_tessellated"] += 1
            continue
        tris = tris[:: max(1, len(tris) // samples)]
        face = f.get(sid)
        surface = Surface(f, face.params[2])
        sense = 1.0 if face.params[3] == "T" else -1.0
        agree = against = 0.0
        for area, a, b, c, n in tris:
            centre = tuple((a[i] + b[i] + c[i]) / 3.0 * 1000.0 for i in range(3))
            _d, sn = surface.closest(centre)
            if sn is None:
                continue
            if _dot(sn, n) * sense > 0:
                agree += area
            else:
                against += area
        out["faces"] += 1
        if agree == 0.0 and against == 0.0:
            out["far"] += 1
        elif agree > against:
            out["agree"] += 1
        else:
            out["disagree"].append(sid)
    return out


def arcs(f: File, edge_map: dict, samplers: dict) -> dict:
    """Each STEP edge paired with a source edge (``edge_map``: STEP id -> (body, EDGE node
    index)) against the source edge's middle sample (``samplers``: body -> callable
    giving an edge's sample points from its start to its end, in metres): the sample
    lies on the curve, between the vertices, the way same_sense says."""
    out = {"edges": 0, "right": 0, "wrong": [], "far": []}
    for eid, (body, node) in edge_map.items():
        pts = samplers[body](node)
        if pts is None or len(pts) < 3:
            continue
        mid = tuple(x * 1000.0 for x in pts[len(pts) // 2])
        ec = f.get(eid)
        c = Curve(f, ec.params[3])
        ps, pe = point_of_vertex(f, ec.params[1]), point_of_vertex(f, ec.params[2])
        ts, _ = c.closest(ps)
        te, _ = c.closest(pe)
        tm, dm = c.closest(mid)
        out["edges"] += 1
        sign = 1.0 if ec.params[4] == "T" else -1.0
        if c.period:
            P = c.period
            want = ((te - ts) * sign) % P
            if ec.params[1] == ec.params[2] or want < 1e-12:
                want = P
            at = ((tm - ts) * sign) % P
            ok = 0.0 < at < want
        else:
            if ec.params[1] == ec.params[2]:  # closes on one vertex: from one end of the curve to the other
                lo, hi = c.bounds()
                ts, te = (lo, hi) if sign > 0 else (hi, lo)
            ok = (tm - ts) * sign > 0 and (te - tm) * sign > 0
        if dm > 1e-3:
            out["far"].append((eid, dm))
        if ok:
            out["right"] += 1
        else:
            out["wrong"].append(eid)
    return out


def _edge_span(f: File, ec: Entity, c: "Curve"):
    """``(ts, span, sign)``: an EDGE_CURVE's start parameter on its curve, the length of
    its arc in that parameter (a whole period for a ring) and the way it runs."""
    ps, pe = point_of_vertex(f, ec.params[1]), point_of_vertex(f, ec.params[2])
    ts, _ = c.closest(ps)
    te, _ = c.closest(pe)
    sign = 1.0 if ec.params[4] == "T" else -1.0
    ring = ec.params[1] == ec.params[2]
    if c.period:
        span = ((te - ts) * sign) % c.period
        if ring or span < 1e-12:
            span = c.period
        return ts, span, sign
    if ring:
        lo, hi = c.bounds()
        ts, te = (lo, hi) if sign > 0 else (hi, lo)
    return ts, (te - ts) * sign, sign


def pieces(f: File, edge_pieces: dict, samplers: dict) -> dict:
    """Each source edge written as pieces (cut where a face round a closed surface was cut
    at its seams; ``edge_pieces``: STEP id -> (body, EDGE node index)) against the source
    edge's samples: every sample between its ends lies on exactly one piece, between
    that piece's vertices the way its same_sense says, or at a vertex two pieces share."""
    groups: dict = {}
    for eid, key in edge_pieces.items():
        groups.setdefault(key, []).append(eid)
    out = {"sources": 0, "pieces": 0, "right": 0, "wrong": []}
    for (body, node), eids in groups.items():
        pts = samplers[body](node)
        if pts is None or len(pts) < 3:
            continue
        out["sources"] += 1
        out["pieces"] += len(eids)
        arcs = []
        for eid in eids:
            ec = f.get(eid)
            c = Curve(f, ec.params[3])
            ts, span, sign = _edge_span(f, ec, c)
            ends = (point_of_vertex(f, ec.params[1]), point_of_vertex(f, ec.params[2]))
            arcs.append((c, ts, span, sign, ends))
        ok = True
        for p in pts[1:-1]:
            q = tuple(x * 1000.0 for x in p)
            inside = 0
            at_end = False
            for c, ts, span, sign, ends in arcs:
                if min(_dist(q, e) for e in ends) <= 1e-6:
                    at_end = True
                    continue
                t, d = c.closest(q)
                if d > 1e-3:
                    continue
                pos = ((t - ts) * sign) % c.period if c.period else (t - ts) * sign
                if 0.0 < pos < span:
                    inside += 1
            if not (inside == 1 or (inside == 0 and at_end)):
                ok = False
                break
        if ok:
            out["right"] += 1
        else:
            out["wrong"].append(sorted(eids))
    return out


# --------------------------------------------------------------------------- the box of SOLIDWORKS' o02
def box_model(f: File) -> dict:
    """The geometry and topology of a planar solid as sets that do not depend on
    numbering: vertices, directed edges (start, end, the line's direction times
    same_sense and its magnitude), faces (plane location, axis and x direction, the
    face's outward normal, the bound kinds and the oriented loops as cyclic
    sequences)."""

    def r(x):
        return tuple(round(c, 9) + 0.0 for c in x)

    counts = Counter()
    for e in f.entities.values():
        for n, _p in e.records:
            counts[n] += 1
    vertices = {int(e.id): r(point_of_vertex(f, e.id)) for e in f.of("VERTEX_POINT")}
    edges = {}
    for e in f.of("EDGE_CURVE"):
        line = f.get(e.params[3])
        assert line.name == "LINE"
        vec = f.get(line.params[2])
        d = tuple(f.get(vec.params[1]).params[1])
        if e.params[4] != "T":
            d = _mul(d, -1.0)
        edges[e.id] = (
            vertices[int(e.params[1])],
            vertices[int(e.params[2])],
            r(d),
            vec.params[2],
            r(f.get(line.params[1]).params[1]),
        )
    faces = set()
    for face in f.of("ADVANCED_FACE"):
        plane = f.get(face.params[2])
        assert plane.name == "PLANE"
        fr = Frame(f, plane.params[1])
        out_n = fr.z if face.params[3] == "T" else _mul(fr.z, -1.0)
        loops = []
        for b in face.params[1]:
            be = f.get(b)
            loop = f.get(be.params[1])
            seq = []
            for oe in (f.get(x) for x in loop.params[1]):
                s, t = _oriented_ends(f, oe)
                seq.append((vertices[s], vertices[t]))
            k = seq.index(min(seq))
            loops.append((be.name, tuple(seq[k:] + seq[:k])))
        faces.add((r(fr.o), r(fr.z), r(fr.x), r(out_n), face.params[3], tuple(sorted(loops))))
    return {
        "counts": counts,
        "vertices": set(vertices.values()),
        "edges": set(edges.values()),
        "faces": faces,
    }


# --------------------------------------------------------------------------- oracles from the source bodies
def tessellation_index(transmits, *, shared: bool = False) -> dict:
    """``(body, FACE node id) -> (Tessellation, FaceTess)`` from SolidSeas' tessellation of
    the source bodies: ``transmits`` one a body in the export's order, or with
    ``shared`` one transmit whose bodies are the export's bodies in order."""
    from solidseas.tessellate import tessellate_transmit

    out = {}
    for k, xt in enumerate(transmits):
        t = tessellate_transmit(xt, body_types=("solid", "sheet"), chord_m=1e-5)
        for i, (b, node_id) in enumerate(t.face_ids):
            out[(b if shared else k, node_id)] = (t, t.mesh.faces[i])
    return out


def edge_samplers(transmits, *, shared: bool = False, count: int = 0) -> dict:
    """``body -> callable(EDGE node index) -> points from the edge's start to its end
    (metres), or None``, from SolidSeas' edge sampler over the source bodies."""
    from types import SimpleNamespace

    from solidseas.tessellate.edges import EdgeSampler
    from solidseas.tessellate.surfaces import Geometry
    from solidseas.tessellate.topology import Clock, FaceFailed, Topology

    def make(xt):
        topo = Topology(xt)
        pts = []

        class Store:
            def add(self, p, tol=0.0):
                pts.append(p)
                return len(pts) - 1

        s = EdgeSampler(
            topo,
            Geometry(topo, 1e-7),
            Store(),
            SimpleNamespace(chord=1e-5, angle=math.pi / 12, max_edge_points=20_000),
            Clock(600.0),
        )

        def sample(index):
            try:
                got = s.samples(topo.nodes[index])
            except FaceFailed:
                return None
            if got.degenerate:
                return None
            return [pts[i] for i in got.ids]

        return sample

    if shared:
        one = make(transmits[0])
        return {k: one for k in range(count)}
    return {k: make(xt) for k, xt in enumerate(transmits)}


def planar_volume(f: File) -> float:
    """The volume (mm^3) of every solid whose faces are planes bounded by lines, by the
    divergence theorem: each face's loops' area vectors (Newell's), oriented by the
    loops' and the face's senses, dotted with a point of the face."""
    total = 0.0
    for face in f.of("ADVANCED_FACE"):
        plane = f.get(face.params[2])
        assert plane.name == "PLANE"
        fr = Frame(f, plane.params[1])
        normal = fr.z if face.params[3] == "T" else _mul(fr.z, -1.0)
        for b in face.params[1]:
            be = f.get(b)
            loop = f.get(be.params[1])
            pts = []
            for oe in (f.get(x) for x in loop.params[1]):
                s, _t = _oriented_ends(f, oe)
                pts.append(point_of_vertex(f, s))
            if be.params[2] != "T":
                pts.reverse()
            area = (0.0, 0.0, 0.0)
            for i in range(len(pts)):
                area = _add(area, _cross(pts[i], pts[(i + 1) % len(pts)]))
            area = _mul(area, 0.5)
            # an outer loop runs counter-clockwise about the outward normal, a hole the
            # other way: the area vector's sign carries it
            total += _dot(area, normal) * _dot(normal, pts[0]) / 3.0
    return total


def extent(f: File) -> tuple[tuple, tuple]:
    """The box (mm) of the vertices and of the circles of ring edges."""
    pts = [point_of_vertex(f, e.id) for e in f.of("VERTEX_POINT")]
    for e in f.of("EDGE_CURVE"):
        if e.params[1] != e.params[2]:
            continue
        c = f.get(e.params[3])
        if c.name == "CIRCLE":
            fr = Frame(f, c.params[1])
            r = c.params[2]
            ext = tuple(r * math.sqrt(max(0.0, 1.0 - fr.z[i] ** 2)) for i in range(3))
            pts.append(_add(fr.o, ext))
            pts.append(_sub(fr.o, ext))
    lo = tuple(min(p[i] for p in pts) for i in range(3))
    hi = tuple(max(p[i] for p in pts) for i in range(3))
    return lo, hi


def full_check(data, model, transmits, *, shared: bool = False, edges: bool = True) -> dict:
    """Every independent check of a written file against its source bodies; the problems
    and the counts, for the tests and the corpus measurement. ``edges``: also points along
    every edge on its faces (:func:`edges_on_faces`; slow on B-spline surfaces)."""
    f = read(data)
    syntax = syntax_problems(f)
    solids, topo = topology(f)
    unc = uncertainty_mm(f)
    tol_mm = (model.max_tolerance_m or 0.0) * 1000.0
    dev_mm = 2.0 * (model.max_deviation_m or 0.0) * 1000.0
    allowance = max(2.0 * unc, tol_mm, dev_mm) * (1.0 + 1e-9) + 1e-12
    geo = geometry(f, allowance)
    if edges:
        on = edges_on_faces(f, allowance)
        geo["edge_surface_max"] = on["edge_surface_max"]
        geo["beyond"] = geo["beyond"] + [("edge_surface", e, d) for e, _face, d in on["beyond"]]
    index = tessellation_index(transmits, shared=shared)
    ori = orientation(f, model.face_map, index)
    samplers = edge_samplers(transmits, shared=shared, count=len(model.bodies))
    arc = arcs(f, model.edge_map, samplers)
    cut = pieces(f, getattr(model, "edge_pieces", {}), samplers)
    return {
        "file": f,
        "solids": solids,
        "syntax": syntax,
        "topology": topo,
        "geometry": geo,
        "orientation": ori,
        "arcs": arc,
        "pieces": cut,
    }


def file_check(
    data, *, deviation_mm: float | None = None, tolerance_mm: float | None = None, edges: bool = True
) -> dict:
    """The checks that need nothing but the file and the numbers its export reported: the
    syntax, the topology, and vertices and points along edges on their curves and
    surfaces, within twice the file's uncertainty, the largest tolerance and twice the
    largest deviation (as :func:`full_check` allows). For the viewer's self-test, which
    has the file it wrote and not its source bodies; ``problems`` is empty when the file
    passes, and a file with no solid or surface model fails."""
    try:
        f = read(data)
    except (Part21Error, UnicodeDecodeError) as exc:
        return {"solids": 0, "problems": [f"not a Part 21 file: {exc}"]}
    problems = list(syntax_problems(f))
    solids, topo = topology(f)
    problems += topo
    if not solids:
        problems.append("no solid or surface model")
    unc = uncertainty_mm(f)
    allowance = max(2.0 * unc, tolerance_mm or 0.0, 2.0 * (deviation_mm or 0.0)) * (1.0 + 1e-9) + 1e-12
    geo = geometry(f, allowance)
    beyond = list(geo["beyond"])
    name = f.header_record("FILE_NAME")
    out = {
        "file_name": name[0] if name else None,
        "solids": len(solids),
        "faces": sum(s.F for s in solids),
        "uncertainty_mm": unc,
        "allowance_mm": allowance,
        "vertex_curve_max_mm": geo["vertex_curve_max"],
        "vertex_surface_max_mm": geo["vertex_surface_max"],
    }
    if edges:
        on = edges_on_faces(f, allowance)
        out["edge_surface_max_mm"] = on["edge_surface_max"]
        beyond += [("edge_surface", e, d) for e, _face, d in on["beyond"]]
    problems += [f"{kind} #{ref} off by {d:.3g} mm" for kind, ref, d in beyond[:20]]
    out["problems"] = problems[:50]
    return out


def corpus_report(data, doc, model, *, edges: bool = True) -> dict:
    """Numbers only, for the corpus measurement (``tests/test_corpus.py``,
    ``test_corpus_step``)."""
    from solidseas.tessellate import bodies_of

    _n, bodies, _w, _ = bodies_of(doc, model.configuration)
    got = full_check(data, model, [b.transmit for b in bodies], edges=edges)
    ori, arc, geo = got["orientation"], got["arcs"], got["geometry"]
    return {
        "edge_surface_max_nm": int(geo.get("edge_surface_max", 0.0) * 1e6),
        "syntax_problems": len(got["syntax"]),
        "topology_problems": len(got["topology"]),
        "beyond_allowance": len(geo["beyond"]),
        "vertex_curve_max_nm": int(geo["vertex_curve_max"] * 1e6),
        "vertex_surface_max_nm": int(geo["vertex_surface_max"] * 1e6),
        "faces_oracle": ori["faces"],
        "faces_agree": ori["agree"],
        "faces_disagree": len(ori["disagree"]),
        "faces_not_tessellated": ori["not_tessellated"],
        "edges_checked": arc["edges"],
        "edges_right": arc["right"],
        "edges_wrong": len(arc["wrong"]),
        "edges_far": len(arc["far"]),
        "edges_cut": got["pieces"]["sources"],
        "edges_cut_wrong": len(got["pieces"]["wrong"]),
    }
