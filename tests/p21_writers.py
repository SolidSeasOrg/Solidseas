"""Synthetic STEP files for the STEP reader's tests, written by code (no real file is used).

:class:`P21` writes a Part 21 exchange structure instance by instance; its helpers
write the common entities (points, directions, placements, curves, surfaces,
contexts with units, products). :class:`Brep` writes a B-rep solid or shell from
vertices, edges and faces, with the orientations ISO 10303-42 gives them, so each
shape below is a closed solid whose volume is known: :func:`box_file`,
:func:`cylinder_brep`, :func:`cone_brep`, :func:`hemisphere_brep`,
:func:`torus_brep`, :func:`elliptic_prism_brep`, :func:`revolved_brep` and more.
Assemblies, colours, units, properties, faceted and tessellated forms, string
escapes and the malformed variants the hostile tests need are written here too.
Every name and value is invented by the test.
"""

import math
from dataclasses import dataclass, field

TAU = 2.0 * math.pi


def _f(x: float) -> str:
    r = repr(float(x))
    if "e" in r or "E" in r:
        mant, exp = r.lower().split("e")
        if "." not in mant:
            mant += "."
        return f"{mant}E{exp}"
    return r if "." in r else r + "."


def _s(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _list(items) -> str:
    return "(" + ",".join(items) + ")"


class P21:
    """One exchange structure: ``add`` writes an instance and returns its id."""

    def __init__(self, schema="AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }", *, start: int = 1) -> None:
        self.schema = schema
        self.lines: list[tuple[int, str]] = []
        self.next_id = start
        self.header_extra: list[str] = []
        self.name = "synthetic.step"
        self.author = ("A. Tester",)
        self.organization = ("Test Shop",)
        self.time_stamp = "2026-05-04T03:02:01"
        self.originating = "Synthetic Writer 1.0"
        self.description = ("synthetic test file",)

    def add(self, text: str) -> int:
        i = self.next_id
        self.next_id += 1
        self.lines.append((i, text))
        return i

    def ref(self, i: int) -> str:
        return f"#{i}"

    def data(self) -> str:
        return "".join(f"#{i}={t};\n" for i, t in self.lines)

    def bytes(self, *, order: str = "ids", newline: str = "\n") -> bytes:
        lines = list(self.lines)
        schemas = (self.schema,) if isinstance(self.schema, str) else tuple(self.schema)
        if order == "reversed":
            lines.reverse()
        head = [
            "ISO-10303-21;",
            "HEADER;",
            f"FILE_DESCRIPTION(({','.join(_s(d) for d in self.description)}),'2;1');",
            "FILE_NAME("
            + ",".join(
                [
                    _s(self.name),
                    _s(self.time_stamp),
                    _list(_s(a) for a in self.author),
                    _list(_s(o) for o in self.organization),
                    _s("p21_writers"),
                    _s(self.originating),
                    _s(""),
                ]
            )
            + ");",
            f"FILE_SCHEMA(({','.join(_s(x) for x in schemas)}));",
            *self.header_extra,
            "ENDSEC;",
            "DATA;",
        ]
        body = [f"#{i}={t};" for i, t in lines]
        tail = ["ENDSEC;", "END-ISO-10303-21;"]
        return (newline.join(head + body + tail) + newline).encode("ascii")

    # -- values ---------------------------------------------------------------------------
    def point(self, p) -> int:
        return self.add(f"CARTESIAN_POINT('',{_list(_f(x) for x in p)})")

    def direction(self, d) -> int:
        return self.add(f"DIRECTION('',{_list(_f(x) for x in d)})")

    def vector(self, d, magnitude: float = 1.0) -> int:
        return self.add(f"VECTOR('',#{self.direction(d)},{_f(magnitude)})")

    def axis2(self, origin=(0, 0, 0), z=(0, 0, 1), x=(1, 0, 0)) -> int:
        zz = f"#{self.direction(z)}" if z is not None else "$"
        xx = f"#{self.direction(x)}" if x is not None else "$"
        return self.add(f"AXIS2_PLACEMENT_3D('',#{self.point(origin)},{zz},{xx})")

    def axis1(self, origin, axis) -> int:
        return self.add(f"AXIS1_PLACEMENT('',#{self.point(origin)},#{self.direction(axis)})")

    # -- curves --------------------------------------------------------------------------
    def line(self, p, d, magnitude: float = 1.0) -> int:
        return self.add(f"LINE('',#{self.point(p)},#{self.vector(d, magnitude)})")

    def circle(self, centre, normal, x, r) -> int:
        return self.add(f"CIRCLE('',#{self.axis2(centre, normal, x)},{_f(r)})")

    def ellipse(self, centre, normal, x, a, b) -> int:
        return self.add(f"ELLIPSE('',#{self.axis2(centre, normal, x)},{_f(a)},{_f(b)})")

    def bspline_curve(self, degree, points, mults, knots, *, weights=None, closed=False) -> int:
        pts = _list(f"#{self.point(p)}" for p in points)
        closed_flag = ".T." if closed else ".F."
        m = _list(str(k) for k in mults)
        k = _list(_f(v) for v in knots)
        if weights is None:
            return self.add(
                f"B_SPLINE_CURVE_WITH_KNOTS('',{degree},{pts},.UNSPECIFIED.,{closed_flag},.F.,{m},{k},.UNSPECIFIED.)"
            )
        w = _list(_f(v) for v in weights)
        return self.add(
            f"(BOUNDED_CURVE()B_SPLINE_CURVE({degree},{pts},.UNSPECIFIED.,{closed_flag},.F.)"
            f"B_SPLINE_CURVE_WITH_KNOTS({m},{k},.UNSPECIFIED.)CURVE()GEOMETRIC_REPRESENTATION_ITEM()"
            f"RATIONAL_B_SPLINE_CURVE({w})REPRESENTATION_ITEM(''))"
        )

    def polyline(self, points) -> int:
        return self.add(f"POLYLINE('',{_list(f'#{self.point(p)}' for p in points)})")

    # -- surfaces ------------------------------------------------------------------------
    def plane(self, origin, normal, x=None) -> int:
        return self.add(f"PLANE('',#{self.axis2(origin, normal, x)})")

    def cylinder(self, origin, axis, r, x=(1, 0, 0)) -> int:
        return self.add(f"CYLINDRICAL_SURFACE('',#{self.axis2(origin, axis, x)},{_f(r)})")

    def cone(self, origin, axis, r, semi_angle, x=(1, 0, 0)) -> int:
        return self.add(f"CONICAL_SURFACE('',#{self.axis2(origin, axis, x)},{_f(r)},{_f(semi_angle)})")

    def sphere(self, centre, r, axis=(0, 0, 1), x=(1, 0, 0)) -> int:
        return self.add(f"SPHERICAL_SURFACE('',#{self.axis2(centre, axis, x)},{_f(r)})")

    def torus(self, centre, axis, major, minor, x=(1, 0, 0)) -> int:
        return self.add(f"TOROIDAL_SURFACE('',#{self.axis2(centre, axis, x)},{_f(major)},{_f(minor)})")

    def bspline_surface(self, pu, pv, rows, umults, uknots, vmults, vknots, *, weights=None) -> int:
        grid = _list(_list(f"#{self.point(p)}" for p in row) for row in rows)
        um, uk = _list(str(m) for m in umults), _list(_f(k) for k in uknots)
        vm, vk = _list(str(m) for m in vmults), _list(_f(k) for k in vknots)
        if weights is None:
            return self.add(
                f"B_SPLINE_SURFACE_WITH_KNOTS('',{pu},{pv},{grid},.UNSPECIFIED.,.F.,.F.,.F.,{um},{vm},{uk},{vk},"
                ".UNSPECIFIED.)"
            )
        w = _list(_list(_f(x) for x in row) for row in weights)
        return self.add(
            f"(BOUNDED_SURFACE()B_SPLINE_SURFACE({pu},{pv},{grid},.UNSPECIFIED.,.F.,.F.,.F.)"
            f"B_SPLINE_SURFACE_WITH_KNOTS({um},{vm},{uk},{vk},.UNSPECIFIED.)GEOMETRIC_REPRESENTATION_ITEM()"
            f"RATIONAL_B_SPLINE_SURFACE({w})REPRESENTATION_ITEM('')SURFACE())"
        )

    # -- contexts and products -----------------------------------------------------------
    def units(self, length: str = "mm", angle: str = "rad", uncertainty: float = 1e-5) -> int:
        """A geometric representation context with these units."""
        if length == "mm":
            lu = self.add("(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.))")
        elif length == "m":
            lu = self.add("(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT($,.METRE.))")
        elif length == "in":
            mm = self.add("(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.))")
            dims = self.add("DIMENSIONAL_EXPONENTS(1.,0.,0.,0.,0.,0.,0.)")
            conv = self.add(f"LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(25.4),#{mm})")
            lu = self.add(f"(CONVERSION_BASED_UNIT('INCH',#{conv})LENGTH_UNIT()NAMED_UNIT(#{dims}))")
        else:
            raise ValueError(length)
        rad = self.add("(NAMED_UNIT(*)PLANE_ANGLE_UNIT()SI_UNIT($,.RADIAN.))")
        if angle == "deg":
            dims = self.add("DIMENSIONAL_EXPONENTS(0.,0.,0.,0.,0.,0.,0.)")
            conv = self.add(f"PLANE_ANGLE_MEASURE_WITH_UNIT(PLANE_ANGLE_MEASURE({_f(math.pi / 180)}),#{rad})")
            au = self.add(f"(CONVERSION_BASED_UNIT('DEGREE',#{conv})NAMED_UNIT(#{dims})PLANE_ANGLE_UNIT())")
        else:
            au = rad
        sr = self.add("(NAMED_UNIT(*)SI_UNIT($,.STERADIAN.)SOLID_ANGLE_UNIT())")
        unc = self.add(
            f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE({_f(uncertainty)}),#{lu},'distance_accuracy_value','')"
        )
        return self.add(
            f"(GEOMETRIC_REPRESENTATION_CONTEXT(3)GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#{unc}))"
            f"GLOBAL_UNIT_ASSIGNED_CONTEXT((#{lu},#{au},#{sr}))REPRESENTATION_CONTEXT('',''))"
        )

    def product(self, name: str, *, description: str = "") -> int:
        """A product, its formation and its definition; returns the product definition."""
        app = getattr(self, "_app", None)
        if app is None:
            app = self._app = self.add("APPLICATION_CONTEXT('automotive design')")
            self.add(
                f"APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,#{app})"
            )
        pc = self.add(f"PRODUCT_CONTEXT('',#{app},'mechanical')")
        prod = self.add(f"PRODUCT({_s(name)},{_s(name)},{_s(description)},(#{pc}))")
        pdf = self.add(f"PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE('','',#{prod},.NOT_KNOWN.)")
        pdc = self.add(f"PRODUCT_DEFINITION_CONTEXT('part definition',#{app},'design')")
        return self.add(f"PRODUCT_DEFINITION('design','',#{pdf},#{pdc})")

    def shape(
        self, pd: int, items, ctx: int, *, kind: str = "ADVANCED_BREP_SHAPE_REPRESENTATION", via_srr=True
    ):
        """The product's shape: a SHAPE_REPRESENTATION with a placement, related to a
        representation of ``kind`` holding ``items``. Returns (shape rep, geometry rep)."""
        pds = self.add(f"PRODUCT_DEFINITION_SHAPE('','',#{pd})")
        origin = self.axis2()
        geo = self.add(f"{kind}('',{_list(f'#{i}' for i in [origin, *items])},#{ctx})")
        if not via_srr:
            self.add(f"SHAPE_DEFINITION_REPRESENTATION(#{pds},#{geo})")
            return geo, geo
        sr = self.add(f"SHAPE_REPRESENTATION('',(#{self.axis2()}),#{ctx})")
        self.add(f"SHAPE_DEFINITION_REPRESENTATION(#{pds},#{sr})")
        self.add(f"SHAPE_REPRESENTATION_RELATIONSHIP('','',#{sr},#{geo})")
        return sr, geo

    def occurrence(
        self,
        parent_pd,
        child_pd,
        parent_rep,
        child_rep,
        *,
        at,
        z=(0, 0, 1),
        x=(1, 0, 0),
        name="",
        order="child_first",
    ) -> int:
        """A NAUO with its CDSR placing the child at ``at`` (axes ``z`` and ``x``) in the
        parent. ``order`` puts the child's representation first (rep_1) or second."""
        nauo = self.add(
            f"NEXT_ASSEMBLY_USAGE_OCCURRENCE({_s(name or 'NAUO')},{_s(name)},'',#{parent_pd},#{child_pd},$)"
        )
        pds = self.add(f"PRODUCT_DEFINITION_SHAPE('','',#{nauo})")
        child_item = self.axis2()
        parent_item = self.axis2(at, z, x)
        if order == "child_first":
            idt = self.add(f"ITEM_DEFINED_TRANSFORMATION('','',#{child_item},#{parent_item})")
            r1, r2 = child_rep, parent_rep
        else:
            idt = self.add(f"ITEM_DEFINED_TRANSFORMATION('','',#{parent_item},#{child_item})")
            r1, r2 = parent_rep, child_rep
        rr = self.add(
            f"(REPRESENTATION_RELATIONSHIP('','',#{r1},#{r2})REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION(#{idt})"
            "SHAPE_REPRESENTATION_RELATIONSHIP())"
        )
        self.add(f"CONTEXT_DEPENDENT_SHAPE_REPRESENTATION(#{rr},#{pds})")
        return nauo

    def colour(
        self, item: int, rgb, *, overriding: int | None = None, transparency: float | None = None
    ) -> int:
        c = self.add(f"COLOUR_RGB('',{_f(rgb[0])},{_f(rgb[1])},{_f(rgb[2])})")
        fac = self.add(f"FILL_AREA_STYLE_COLOUR('',#{c})")
        fas = self.add(f"FILL_AREA_STYLE('',(#{fac}))")
        ssfa = self.add(f"SURFACE_STYLE_FILL_AREA(#{fas})")
        styles = [f"#{ssfa}"]
        if transparency is not None:
            tr = self.add(f"SURFACE_STYLE_TRANSPARENT({_f(transparency)})")
            styles.append(
                f"#{self.add(f'SURFACE_STYLE_RENDERING_WITH_PROPERTIES(.NORMAL_SHADING.,#{c},(#{tr}))')}"
            )
        sss = self.add(f"SURFACE_SIDE_STYLE('',{_list(styles)})")
        ssu = self.add(f"SURFACE_STYLE_USAGE(.BOTH.,#{sss})")
        curve = self.add(
            f"CURVE_STYLE('',#{self.add('DRAUGHTING_PRE_DEFINED_CURVE_FONT(' + _s('continuous') + ')')},"
            f"POSITIVE_LENGTH_MEASURE(0.1),#{c})"
        )
        psa = self.add(f"PRESENTATION_STYLE_ASSIGNMENT((#{curve},#{ssu}))")
        if overriding is not None:
            return self.add(f"OVER_RIDING_STYLED_ITEM('overriding',(#{psa}),#{item},#{overriding})")
        return self.add(f"STYLED_ITEM('color',(#{psa}),#{item})")

    def named_colour(self, item: int, name: str) -> int:
        c = self.add(f"DRAUGHTING_PRE_DEFINED_COLOUR({_s(name)})")
        fac = self.add(f"FILL_AREA_STYLE_COLOUR('',#{c})")
        fas = self.add(f"FILL_AREA_STYLE('',(#{fac}))")
        ssfa = self.add(f"SURFACE_STYLE_FILL_AREA(#{fas})")
        sss = self.add(f"SURFACE_SIDE_STYLE('',(#{ssfa}))")
        ssu = self.add(f"SURFACE_STYLE_USAGE(.BOTH.,#{sss})")
        psa = self.add(f"PRESENTATION_STYLE_ASSIGNMENT((#{ssu}))")
        return self.add(f"STYLED_ITEM('color',(#{psa}),#{item})")

    def user_property(self, pd: int, name: str, value) -> None:
        pdef = self.add(f"PROPERTY_DEFINITION('user defined attribute','',#{pd})")
        if isinstance(value, str):
            item = self.add(f"DESCRIPTIVE_REPRESENTATION_ITEM({_s(name)},{_s(value)})")
        else:
            item = self.add(f"VALUE_REPRESENTATION_ITEM({_s(name)},COUNT_MEASURE({_f(value)}))")
        ctx = self.add("REPRESENTATION_CONTEXT('','')")
        rep = self.add(f"REPRESENTATION('',(#{item}),#{ctx})")
        self.add(f"PROPERTY_DEFINITION_REPRESENTATION(#{pdef},#{rep})")


# --------------------------------------------------------------------------- B-rep
@dataclass
class Brep:
    """A solid or shell: vertices, edges and faces written with ISO 10303-42's
    orientations. ``edge`` takes a curve instance; ``face`` takes loops of
    ``(edge, along)`` pairs in order round each loop (the face on the left seen from
    its normal), or a vertex for a vertex loop."""

    f: P21
    face_ids: list[int] = field(default_factory=list)
    _vertices: dict = field(default_factory=dict)

    def vertex(self, p) -> int:
        key = tuple(round(float(c), 12) for c in p)
        got = self._vertices.get(key)
        if got is None:
            got = self._vertices[key] = self.f.add(f"VERTEX_POINT('',#{self.f.point(p)})")
        return got

    def edge(self, curve: int, start, end, same_sense: bool = True) -> int:
        v0, v1 = self.vertex(start), self.vertex(end)
        return self.f.add(f"EDGE_CURVE('',#{v0},#{v1},#{curve},{'.T.' if same_sense else '.F.'})")

    def face(
        self, surface: int, loops, *, same_sense: bool = True, outer_first: bool = True, kind="ADVANCED_FACE"
    ):
        bounds = []
        for k, lp in enumerate(loops):
            if isinstance(lp, tuple) and lp and lp[0] == "vertex":
                loop = self.f.add(f"VERTEX_LOOP('',#{self.vertex(lp[1])})")
                orientation = True
            elif isinstance(lp, tuple) and lp and lp[0] == "reversed":
                # the same loop stored the other way round, bound with orientation .F.
                oes = [
                    self.f.add(f"ORIENTED_EDGE('',*,*,#{e},{'.F.' if a else '.T.'})")
                    for e, a in reversed(lp[1])
                ]
                loop = self.f.add(f"EDGE_LOOP('',{_list(f'#{o}' for o in oes)})")
                orientation = False
            else:
                oes = [self.f.add(f"ORIENTED_EDGE('',*,*,#{e},{'.T.' if a else '.F.'})") for e, a in lp]
                loop = self.f.add(f"EDGE_LOOP('',{_list(f'#{o}' for o in oes)})")
                orientation = True
            word = "FACE_OUTER_BOUND" if k == 0 and outer_first else "FACE_BOUND"
            bounds.append(self.f.add(f"{word}('',#{loop},{'.T.' if orientation else '.F.'})"))
        fid = self.f.add(
            f"{kind}('',{_list(f'#{b}' for b in bounds)},#{surface},{'.T.' if same_sense else '.F.'})"
        )
        self.face_ids.append(fid)
        return fid

    def shell(self, kind: str = "CLOSED_SHELL") -> int:
        return self.f.add(f"{kind}('',{_list(f'#{i}' for i in self.face_ids)})")

    def solid(self, name: str = "body") -> int:
        return self.f.add(f"MANIFOLD_SOLID_BREP({_s(name)},#{self.shell()})")


def box_brep(
    f: P21,
    size=(10.0, 20.0, 30.0),
    origin=(0.0, 0.0, 0.0),
    *,
    edges: str = "line",
    name="box",
    top=None,
) -> int:
    """A box as a MANIFOLD_SOLID_BREP; ``edges`` ``line``, ``bspline`` (degree 1),
    ``polyline``, ``trimmed``, ``surface_curve`` or ``pcurve`` (the bottom face's
    edges stored as pcurves only). ``top(f)``, when given, returns the top face's
    surface and its same_sense."""
    b = Brep(f)
    W, D, H = size
    ox, oy, oz = origin

    def P(i, j, k):
        return (ox + W * i, oy + D * j, oz + H * k)

    made: dict = {}
    # the bottom face's plane: (u, v) is (x, -y) there, as its x axis is +x and its normal -z
    bottom = f.plane(P(0, 0, 0), (0, 0, -1), (1, 0, 0))

    def E(c0, c1):
        key = (c0, c1) if c0 < c1 else (c1, c0)
        if key not in made:
            pa, pb = P(*key[0]), P(*key[1])
            d = tuple(pb[i] - pa[i] for i in range(3))
            if edges == "pcurve" and key[0][2] == 0 and key[1][2] == 0:
                uv = [(q[0] - ox, -(q[1] - oy)) for q in (pa, pb)]
                c2 = f.add(
                    f"B_SPLINE_CURVE_WITH_KNOTS('',1,{_list(f'#{f.point(q)}' for q in uv)},"
                    ".POLYLINE_FORM.,.F.,.F.,"
                    "(2,2),(0.,1.),.UNSPECIFIED.)"
                )
                ctx2 = f.add(
                    "(GEOMETRIC_REPRESENTATION_CONTEXT(2)PARAMETRIC_REPRESENTATION_CONTEXT()"
                    "REPRESENTATION_CONTEXT('2D SPACE',''))"
                )
                drep = f.add(f"DEFINITIONAL_REPRESENTATION('',(#{c2}),#{ctx2})")
                curve = f.add(f"PCURVE('',#{bottom},#{drep})")
            elif edges == "composite":
                # two halves: the first along the edge, the second a line from the far end
                # back to the middle, used against its sense
                length = math.sqrt(sum(x * x for x in d))
                u = tuple(x / length for x in d)
                first = f.add(
                    f"TRIMMED_CURVE('',#{f.line(pa, u)},(PARAMETER_VALUE(0.0)),"
                    f"(PARAMETER_VALUE({_f(length / 2.0)})),.T.,.PARAMETER.)"
                )
                back = f.line(pb, tuple(-x for x in u))
                mid = f.point(tuple(pa[i] + d[i] / 2.0 for i in range(3)))
                second = f.add(f"TRIMMED_CURVE('',#{back},(PARAMETER_VALUE(0.0)),(#{mid}),.T.,.CARTESIAN.)")
                s1 = f.add(f"COMPOSITE_CURVE_SEGMENT(.CONTINUOUS.,.T.,#{first})")
                s2 = f.add(f"COMPOSITE_CURVE_SEGMENT(.CONTINUOUS.,.F.,#{second})")
                curve = f.add(f"COMPOSITE_CURVE('',(#{s1},#{s2}),.F.)")
            elif edges == "bspline":
                curve = f.bspline_curve(1, [pa, pb], [2, 2], [0.0, 1.0])
            elif edges == "polyline":
                curve = f.polyline([pa, pb])
            elif edges == "trimmed":
                base = f.line(pa, d, 2.0)
                length = math.sqrt(sum(x * x for x in d))
                curve = f.add(
                    f"TRIMMED_CURVE('',#{base},(PARAMETER_VALUE(0.)),"
                    f"(PARAMETER_VALUE({_f(length / 2.0)})),.T.,"
                    ".PARAMETER.)"
                )
            elif edges == "surface_curve":
                base = f.line(pa, d)
                curve = f.add(f"SURFACE_CURVE('',#{base},(),.CURVE_3D.)")
            else:
                curve = f.line(pa, d)
            made[key] = b.edge(curve, pa, pb)
        return made[key], (c0, c1) == key

    sides = [
        (((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)), (0, 0, -1), (1, 0, 0)),
        (((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)), (0, 0, 1), (1, 0, 0)),
        (((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)), (0, -1, 0), (1, 0, 0)),
        (((0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)), (0, 1, 0), (1, 0, 0)),
        (((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)), (-1, 0, 0), (0, 1, 0)),
        (((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)), (1, 0, 0), (0, 1, 0)),
    ]
    for k, (cs, n, x) in enumerate(sides):
        loop = [E(cs[k], cs[(k + 1) % 4]) for k in range(4)]
        if k == 1 and top is not None:
            surface, same = top(f)
            b.face(surface, [loop], same_sense=same)
            continue
        b.face(bottom if k == 0 else f.plane(P(*cs[0]), n, x), [loop])
    return b.solid(name)


def cylinder_brep(f: P21, r=5.0, h=20.0, *, split: bool = True, name="cylinder", side=None) -> int:
    """A cylinder on the z axis: its side as two half faces (``split``, as SOLIDWORKS
    writes them) or one face with a seam edge, and two planar caps. ``side(f)``, when
    given, returns the side's surface and its same_sense (one face with a seam)."""
    b = Brep(f)
    p0, p1 = (r, 0.0, 0.0), (r, 0.0, h)
    q0, q1 = (-r, 0.0, 0.0), (-r, 0.0, h)
    same = True
    if side is not None:
        side, same = side(f)
        split = False
    else:
        side = f.cylinder((0, 0, 0), (0, 0, 1), r)
    bottom_c = f.circle((0, 0, 0), (0, 0, 1), (1, 0, 0), r)
    top_c = f.circle((0, 0, h), (0, 0, 1), (1, 0, 0), r)
    if split:
        b1 = b.edge(bottom_c, p0, q0)  # counter-clockwise seen from +z: through +y
        b2 = b.edge(bottom_c, q0, p0)
        t1 = b.edge(top_c, p1, q1)
        t2 = b.edge(top_c, q1, p1)
        s0 = b.edge(f.line(p0, (0, 0, 1)), p0, p1)
        s1 = b.edge(f.line(q0, (0, 0, 1)), q0, q1)
        b.face(side, [[(b1, True), (s1, True), (t1, False), (s0, False)]])
        b.face(side, [[(b2, True), (s0, True), (t2, False), (s1, False)]])
        b.face(f.plane((0, 0, 0), (0, 0, -1), (1, 0, 0)), [[(b2, False), (b1, False)]])
        b.face(f.plane((0, 0, h), (0, 0, 1), (1, 0, 0)), [[(t1, True), (t2, True)]])
    else:
        bc = b.edge(bottom_c, p0, p0)
        tc = b.edge(top_c, p1, p1)
        seam_line = f.line(p0, (0, 0, 1))
        seam = b.edge(f.add(f"SEAM_CURVE('',#{seam_line},(),.CURVE_3D.)"), p0, p1)
        b.face(side, [[(bc, True), (seam, True), (tc, False), (seam, False)]], same_sense=same)
        b.face(f.plane((0, 0, 0), (0, 0, -1), (1, 0, 0)), [[(bc, False)]])
        b.face(f.plane((0, 0, h), (0, 0, 1), (1, 0, 0)), [[(tc, True)]])
    return b.solid(name)


def composite_cylinder_brep(f: P21, r=5.0, h=20.0, name="composite cylinder") -> int:
    """The cylinder with a seam, its two rims composite curves of two trimmed arcs each
    (parameters in the file's angle unit, radians here)."""
    b = Brep(f)
    side = f.cylinder((0, 0, 0), (0, 0, 1), r)
    rims = []
    for z in (0.0, h):
        circle = f.circle((0, 0, z), (0, 0, 1), (1, 0, 0), r)
        halves = [
            f.add(
                f"TRIMMED_CURVE('',#{circle},(PARAMETER_VALUE({_f(a0)})),(PARAMETER_VALUE({_f(a1)})),.T.,"
                ".PARAMETER.)"
            )
            for a0, a1 in ((0.0, math.pi), (math.pi, TAU))
        ]
        segs = [f.add(f"COMPOSITE_CURVE_SEGMENT(.CONTINUOUS.,.T.,#{c})") for c in halves]
        comp = f.add(f"COMPOSITE_CURVE('',(#{segs[0]},#{segs[1]}),.F.)")
        rims.append(b.edge(comp, (r, 0.0, z), (r, 0.0, z)))
    bc, tc = rims
    seam = b.edge(f.line((r, 0, 0), (0, 0, 1)), (r, 0, 0), (r, 0, h))
    b.face(side, [[(bc, True), (seam, True), (tc, False), (seam, False)]])
    b.face(f.plane((0, 0, 0), (0, 0, -1), (1, 0, 0)), [[(bc, False)]])
    b.face(f.plane((0, 0, h), (0, 0, 1), (1, 0, 0)), [[(tc, True)]])
    return b.solid(name)


def cone_brep(f: P21, r=5.0, h=10.0, *, angle_unit: float = 1.0, name="cone") -> int:
    """A cone on the z axis with its apex at z = h: a conical face with a vertex loop at
    the apex, on a disc. ``angle_unit`` is the file's radians per angle unit."""
    b = Brep(f)
    semi = math.atan2(r, h)
    # the surface's radius shrinks along its axis: placed at the apex, axis -z, radius 0
    cone = f.cone((0, 0, h), (0, 0, -1), 0.0, semi / angle_unit)
    rim = f.circle((0, 0, 0), (0, 0, 1), (1, 0, 0), r)
    e = b.edge(rim, (r, 0, 0), (r, 0, 0))
    b.face(cone, [[(e, True)], ("vertex", (0.0, 0.0, h))])
    b.face(f.plane((0, 0, 0), (0, 0, -1), (1, 0, 0)), [[(e, False)]])
    return b.solid(name)


def hemisphere_brep(f: P21, r=10.0, name="dome") -> int:
    b = Brep(f)
    rim = f.circle((0, 0, 0), (0, 0, 1), (1, 0, 0), r)
    e = b.edge(rim, (r, 0, 0), (r, 0, 0))
    b.face(f.sphere((0, 0, 0), r), [[(e, True)]])
    b.face(f.plane((0, 0, 0), (0, 0, -1), (1, 0, 0)), [[(e, False)]])
    return b.solid(name)


def torus_band_shell(f: P21, R=10.0, r=3.0) -> int:
    """The outer half of a torus (minor angles from -90 to 90 degrees) as an open shell:
    one face bounded by two circles."""
    b = Brep(f)
    lo = f.circle((0, 0, -r), (0, 0, 1), (1, 0, 0), R)
    hi = f.circle((0, 0, r), (0, 0, 1), (1, 0, 0), R)
    e0 = b.edge(lo, (R, 0, -r), (R, 0, -r))
    e1 = b.edge(hi, (R, 0, r), (R, 0, r))
    b.face(f.torus((0, 0, 0), (0, 0, 1), R, r), [[(e0, True)], [(e1, False)]])
    return b.shell("OPEN_SHELL")


def elliptic_prism_brep(f: P21, a=8.0, b_=4.0, h=10.0, name="elliptic") -> int:
    """An elliptic cylinder as a linear extrusion of an ellipse, with two caps."""
    b = Brep(f)
    base = f.ellipse((0, 0, 0), (0, 0, 1), (1, 0, 0), a, b_)
    top = f.ellipse((0, 0, h), (0, 0, 1), (1, 0, 0), a, b_)
    side = f.add(f"SURFACE_OF_LINEAR_EXTRUSION('',#{base},#{f.vector((0, 0, 1), h)})")
    e0 = b.edge(base, (a, 0, 0), (a, 0, 0))
    e1 = b.edge(top, (a, 0, h), (a, 0, h))
    seam = b.edge(f.line((a, 0, 0), (0, 0, 1)), (a, 0, 0), (a, 0, h))
    b.face(side, [[(e0, True), (seam, True), (e1, False), (seam, False)]])
    b.face(f.plane((0, 0, 0), (0, 0, -1), (1, 0, 0)), [[(e0, False)]])
    b.face(f.plane((0, 0, h), (0, 0, 1), (1, 0, 0)), [[(e1, True)]])
    return b.solid(name)


def revolved_brep(f: P21, r=5.0, h=20.0, name="revolved", *, sense: bool = True) -> int:
    """The cylinder of :func:`cylinder_brep` with its side a SURFACE_OF_REVOLUTION of a
    trimmed line about the z axis; ``sense`` False trims the line from h back to 0,
    against the line (``sense_agreement`` false), and turns the face's same_sense."""
    b = Brep(f)
    profile_line = f.line((r, 0, 0), (0, 0, 1))
    t0, t1 = (0.0, h) if sense else (h, 0.0)
    profile = f.add(
        f"TRIMMED_CURVE('',#{profile_line},(PARAMETER_VALUE({_f(t0)})),(PARAMETER_VALUE({_f(t1)})),"
        f"{'.T.' if sense else '.F.'},.PARAMETER.)"
    )
    side = f.add(f"SURFACE_OF_REVOLUTION('',#{profile},#{f.axis1((0, 0, 0), (0, 0, 1))})")
    bottom_c = f.circle((0, 0, 0), (0, 0, 1), (1, 0, 0), r)
    top_c = f.circle((0, 0, h), (0, 0, 1), (1, 0, 0), r)
    bc = b.edge(bottom_c, (r, 0, 0), (r, 0, 0))
    tc = b.edge(top_c, (r, 0, h), (r, 0, h))
    seam = b.edge(profile_line, (r, 0, 0), (r, 0, h))
    b.face(side, [[(bc, True), (seam, True), (tc, False), (seam, False)]], same_sense=sense)
    b.face(f.plane((0, 0, 0), (0, 0, -1), (1, 0, 0)), [[(bc, False)]])
    b.face(f.plane((0, 0, h), (0, 0, 1), (1, 0, 0)), [[(tc, True)]])
    return b.solid(name)


def half_cylinder_brep(f: P21, r=5.0, h=10.0, *, sense: bool = True, name="half cylinder") -> int:
    """Half a cylinder (y from 0 up) whose curved face is a SURFACE_OF_LINEAR_EXTRUSION
    of a trimmed circle, the trim running with the circle from 0 to pi, or (``sense``
    False) from pi back to 0 against it, the face's same_sense turned to match."""
    b = Brep(f)
    a0, b0, a1, b1 = (r, 0.0, 0.0), (-r, 0.0, 0.0), (r, 0.0, h), (-r, 0.0, h)
    arc0 = b.edge(f.circle((0, 0, 0), (0, 0, 1), (1, 0, 0), r), a0, b0)
    arc1 = b.edge(f.circle((0, 0, h), (0, 0, 1), (1, 0, 0), r), a1, b1)
    low = b.edge(f.line(b0, (1, 0, 0)), b0, a0)
    high = b.edge(f.line(b1, (1, 0, 0)), b1, a1)
    up_a = b.edge(f.line(a0, (0, 0, 1)), a0, a1)
    up_b = b.edge(f.line(b0, (0, 0, 1)), b0, b1)
    b.face(f.plane((0, 0, 0), (0, 0, -1), (1, 0, 0)), [[(low, False), (arc0, False)]])
    b.face(f.plane((0, 0, h), (0, 0, 1), (1, 0, 0)), [[(arc1, True), (high, True)]])
    b.face(
        f.plane((0, 0, 0), (0, -1, 0), (1, 0, 0)), [[(low, True), (up_a, True), (high, False), (up_b, False)]]
    )
    basis = f.circle((0, 0, 0), (0, 0, 1), (1, 0, 0), r)
    t0, t1 = (0.0, math.pi) if sense else (math.pi, 0.0)
    trimmed = f.add(
        f"TRIMMED_CURVE('',#{basis},(PARAMETER_VALUE({_f(t0)})),(PARAMETER_VALUE({_f(t1)})),"
        f"{'.T.' if sense else '.F.'},.PARAMETER.)"
    )
    side = f.add(f"SURFACE_OF_LINEAR_EXTRUSION('',#{trimmed},#{f.vector((0, 0, 1), h)})")
    b.face(side, [[(arc0, True), (up_b, True), (arc1, False), (up_a, False)]], same_sense=sense)
    return b.solid(name)


def sphere_seam_brep(f: P21, r=10.0, name="seam sphere") -> int:
    """A full sphere whose one face is bounded by its seam, a half circle from the south
    pole to the north, used once each way."""
    b = Brep(f)
    seam = b.edge(f.circle((0, 0, 0), (0, -1, 0), (1, 0, 0), r), (0, 0, -r), (0, 0, r))
    b.face(f.sphere((0, 0, 0), r), [[(seam, True), (seam, False)]])
    return b.solid(name)


def holed_plate_brep(
    f: P21, *, holes_reversed: bool = False, s=20.0, h=10.0, r=5.0, name="holed plate"
) -> int:
    """A 20 x 20 x 10 mm plate with a 10 mm hole through its middle. ``holes_reversed``
    writes the hole as some writers do: its bounds on the plate's faces running the same
    way as their outer bounds, and the cylinder that lines it with a same_sense that
    agrees with them, so that the topology is consistent with itself but the hole is
    inside out."""
    b = Brep(f)
    c = s / 2.0

    def P(i, j, k):
        return (s * i, s * j, h * k)

    made: dict = {}

    def E(c0, c1):
        key = (c0, c1) if c0 < c1 else (c1, c0)
        if key not in made:
            pa, pb = P(*key[0]), P(*key[1])
            made[key] = b.edge(f.line(pa, tuple(pb[i] - pa[i] for i in range(3))), pa, pb)
        return made[key], (c0, c1) == key

    hb, ht = (c + r, c, 0.0), (c + r, c, h)
    rim0 = b.edge(f.circle((c, c, 0), (0, 0, 1), (1, 0, 0), r), hb, hb)
    rim1 = b.edge(f.circle((c, c, h), (0, 0, 1), (1, 0, 0), r), ht, ht)
    seam = b.edge(f.line(hb, (0, 0, 1)), hb, ht)
    sides = [
        (((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)), (0, 0, -1), (1, 0, 0)),
        (((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)), (0, 0, 1), (1, 0, 0)),
        (((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)), (0, -1, 0), (1, 0, 0)),
        (((0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)), (0, 1, 0), (1, 0, 0)),
        (((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)), (-1, 0, 0), (0, 1, 0)),
        (((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)), (1, 0, 0), (0, 1, 0)),
    ]
    for k, (cs, n, x) in enumerate(sides):
        loops = [[E(cs[m], cs[(m + 1) % 4]) for m in range(4)]]
        if k == 0:  # the bottom (normal -z): its hole runs clockwise seen from below
            loops.append([(rim0, not holes_reversed)])
        elif k == 1:  # the top (normal +z): clockwise seen from above
            loops.append([(rim1, holes_reversed)])
        b.face(f.plane(P(*cs[0]), n, x), loops)
    wall = f.cylinder((c, c, 0), (0, 0, 1), r)
    if holes_reversed:
        b.face(wall, [[(rim0, True), (seam, True), (rim1, False), (seam, False)]], same_sense=True)
    else:
        b.face(wall, [[(rim0, False), (seam, True), (rim1, True), (seam, False)]], same_sense=False)
    return b.solid(name)


def nurbs_cylinder_brep(f: P21, r=5.0, h=20.0, name="nurbs") -> int:
    """The cylinder with its side one rational B-spline face (a nine-point circle of
    degree 2 in u, straight in v), a seam edge and circular caps."""
    b = Brep(f)
    w = math.sqrt(0.5)
    circle = [
        (1, 0, 1),
        (1, 1, w),
        (0, 1, 1),
        (-1, 1, w),
        (-1, 0, 1),
        (-1, -1, w),
        (0, -1, 1),
        (1, -1, w),
        (1, 0, 1),
    ]
    rows = [[(x * r, y * r, 0.0), (x * r, y * r, h)] for x, y, _w in circle]
    weights = [[wt, wt] for _x, _y, wt in circle]
    side = f.bspline_surface(2, 1, rows, [3, 2, 2, 2, 3], [0, 1, 2, 3, 4], [2, 2], [0, 1], weights=weights)
    bottom_c = f.circle((0, 0, 0), (0, 0, 1), (1, 0, 0), r)
    top_c = f.circle((0, 0, h), (0, 0, 1), (1, 0, 0), r)
    bc = b.edge(bottom_c, (r, 0, 0), (r, 0, 0))
    tc = b.edge(top_c, (r, 0, h), (r, 0, h))
    seam = b.edge(f.line((r, 0, 0), (0, 0, 1)), (r, 0, 0), (r, 0, h))
    b.face(side, [[(bc, True), (seam, True), (tc, False), (seam, False)]])
    b.face(f.plane((0, 0, 0), (0, 0, -1), (1, 0, 0)), [[(bc, False)]])
    b.face(f.plane((0, 0, h), (0, 0, 1), (1, 0, 0)), [[(tc, True)]])
    return b.solid(name)


def bspline_box_brep(f: P21, size=(10.0, 20.0, 30.0), name="bspline box") -> int:
    """A box whose top face is a bicubic B-spline surface lying in its plane (control
    points on a regular grid), bounded by B-spline curve edges of degree 3."""
    b = Brep(f)
    W, D, H = size
    corners = {(i, j, k): (W * i, D * j, H * k) for i in (0, 1) for j in (0, 1) for k in (0, 1)}
    made: dict = {}

    def E(c0, c1, cubic=False):
        key = (c0, c1) if c0 < c1 else (c1, c0)
        if key not in made:
            pa, pb = corners[key[0]], corners[key[1]]
            if cubic:
                pts = [tuple(pa[i] + (pb[i] - pa[i]) * t / 3.0 for i in range(3)) for t in range(4)]
                curve = f.bspline_curve(3, pts, [4, 4], [0.0, 1.0])
            else:
                curve = f.line(pa, tuple(pb[i] - pa[i] for i in range(3)))
            made[key] = b.edge(curve, pa, pb)
        return made[key], (c0, c1) == key

    grid = [[(W * i / 3.0, D * j / 3.0, H) for j in range(4)] for i in range(4)]
    top = f.bspline_surface(3, 3, grid, [4, 4], [0.0, 1.0], [4, 4], [0.0, 1.0])
    sides = [
        (((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)), (0, 0, -1), (1, 0, 0)),
        (((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)), (0, -1, 0), (1, 0, 0)),
        (((0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)), (0, 1, 0), (1, 0, 0)),
        (((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)), (-1, 0, 0), (0, 1, 0)),
        (((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)), (1, 0, 0), (0, 1, 0)),
    ]
    top_loop = ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))
    for k in range(4):
        E(top_loop[k], top_loop[(k + 1) % 4], cubic=True)
    for cs, n, x in sides:
        b.face(f.plane(corners[cs[0]], n, x), [[E(cs[k], cs[(k + 1) % 4]) for k in range(4)]])
    b.face(top, [[E(top_loop[k], top_loop[(k + 1) % 4]) for k in range(4)]])
    return b.solid(name)


def periodic_ring(R: float = 5.0, n: int = 8):
    """The control points and knots of a periodic cubic B-spline near a circle of radius
    ``R``: ``n`` points round it with the first three repeated, uniform knots."""
    pts = [(R * math.cos(TAU * k / n), R * math.sin(TAU * k / n)) for k in range(n)]
    pts = pts + pts[:3]
    knots = [float(k) for k in range(-3, len(pts) + 1)]
    return pts, knots


def periodic_hoop_brep(f: P21, R: float = 5.0, h: float = 10.0, name="hoop") -> int:
    """A hoop whose side is a periodic B-spline surface (cubic round, straight along z;
    uniform knots, its control rows not repeated as a clamped one's would be) and whose
    ends are periodic B-spline curves, each a closed edge of one vertex, with a seam."""
    b = Brep(f)
    ring, knots = periodic_ring(R)
    m = [1] * len(knots)
    start = tuple((ring[0][i] + 4 * ring[1][i] + ring[2][i]) / 6.0 for i in range(2))
    rows = [[(x, y, 0.0), (x, y, h)] for x, y in ring]
    side = f.add(
        "B_SPLINE_SURFACE_WITH_KNOTS('',3,1,"
        + _list(_list(f"#{f.point(q)}" for q in row) for row in rows)
        + ",.UNSPECIFIED.,.T.,.F.,.F.,"
        + _list(str(x) for x in m)
        + ",(2,2),"
        + _list(_f(k) for k in knots)
        + ",(0.0,1.0),.UNSPECIFIED.)"
    )
    bottom = f.bspline_curve(3, [(x, y, 0.0) for x, y in ring], m, knots, closed=True)
    top = f.bspline_curve(3, [(x, y, h) for x, y in ring], m, knots, closed=True)
    p0, p1 = (start[0], start[1], 0.0), (start[0], start[1], h)
    e0 = b.edge(bottom, p0, p0)
    e1 = b.edge(top, p1, p1)
    seam = b.edge(f.line(p0, (0, 0, 1)), p0, p1)
    b.face(side, [[(e0, True), (seam, True), (e1, False), (seam, False)]])
    b.face(f.plane((0, 0, 0), (0, 0, -1), (1, 0, 0)), [[(e0, False)]])
    b.face(f.plane((0, 0, h), (0, 0, 1), (1, 0, 0)), [[(e1, True)]])
    return b.solid(name)


_BOX_SIDES = [
    (((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)), (0, 0, -1), (1, 0, 0)),
    (((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)), (0, 0, 1), (1, 0, 0)),
    (((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)), (0, -1, 0), (1, 0, 0)),
    (((0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)), (0, 1, 0), (1, 0, 0)),
    (((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)), (-1, 0, 0), (0, 1, 0)),
    (((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)), (1, 0, 0), (0, 1, 0)),
]


def plane_box_shell(f: P21, size=(10.0, 20.0, 30.0), origin=(0.0, 0.0, 0.0), *, form: str = "outward") -> int:
    """A box as a CLOSED_SHELL of six planar faces on line edges, written in one of the
    forms writers use, each a valid closed shell read by the letter of ISO 10303-42 except
    where said:

    * ``outward``: each face's normal out of the box, its loop counter-clockwise about it;
    * ``inward``: the shell faces into the box (every face turned round, its loop
      reversed), as some writers store a void's shell before turning it once more;
    * ``against``: each face's ``same_sense`` false over a plane facing out, its loop
      written as if it were true, so every loop runs against its face (not valid);
    * ``against_inward``: the planes facing in, ``same_sense`` false, the loops counter-
      clockwise about the planes' normals: every loop runs against its face, and the
      faces follow their loops only facing into the box (not valid)."""
    b = Brep(f)
    W, D, H = size
    ox, oy, oz = origin

    def P(i, j, k):
        return (ox + W * i, oy + D * j, oz + H * k)

    made: dict = {}

    def E(c0, c1):
        key = (c0, c1) if c0 < c1 else (c1, c0)
        if key not in made:
            pa, pb = P(*key[0]), P(*key[1])
            made[key] = b.edge(f.line(pa, tuple(pb[i] - pa[i] for i in range(3))), pa, pb)
        return made[key], (c0, c1) == key

    for cs, n, x in _BOX_SIDES:
        loop = [E(cs[k], cs[(k + 1) % 4]) for k in range(4)]
        same = True
        if form in ("inward", "against_inward"):
            loop = [(e, not a) for e, a in reversed(loop)]
        if form == "inward":
            same = False
        elif form == "against":
            same = False
        elif form == "against_inward":
            n, same = tuple(-c for c in n), False
        b.face(f.plane(P(*cs[0]), n, x), [loop], same_sense=same)
    return b.shell()


def void_box_brep(f: P21, *, convention: str = "iso") -> int:
    """A 30 mm cube with a 10 mm cubic void in its middle: BREP_WITH_VOIDS whose void is an
    ORIENTED_CLOSED_SHELL. ``convention`` ``iso``: the void's closed shell faces out of the
    void as a solid's would, and the oriented shell (``.F.``) turns it round, as ISO 10303-42
    reads it; ``inward``: the closed shell already faces into the void and is turned round
    once more, as some writers store it (the void then faces out, read by the letter);
    ``inward_true``: the closed shell faces into the void and the oriented shell keeps it."""
    outer = box_brep(f, (30, 30, 30))
    outer_shell = f.lines[[i for i, _t in f.lines].index(outer)][1].split("#")[1].rstrip(")")
    if convention == "iso":
        inner = box_brep(f, (10, 10, 10), (10, 10, 10))
        inner_shell = f.lines[[i for i, _t in f.lines].index(inner)][1].split("#")[1].rstrip(")")
        void = f.add(f"ORIENTED_CLOSED_SHELL('',*,#{inner_shell},.F.)")
    else:
        inner_shell = plane_box_shell(f, (10, 10, 10), (10, 10, 10), form="inward")
        turned = ".F." if convention == "inward" else ".T."
        void = f.add(f"ORIENTED_CLOSED_SHELL('',*,#{inner_shell},{turned})")
    return f.add(f"BREP_WITH_VOIDS('void box',#{outer_shell},(#{void}))")


def against_box_brep(f: P21, *, planes_inward: bool = False) -> int:
    """A 10 x 20 x 30 mm box whose every face's loop runs against the face (see
    :func:`plane_box_shell`, forms ``against`` and ``against_inward``)."""
    shell = plane_box_shell(f, form="against_inward" if planes_inward else "against")
    return f.add(f"MANIFOLD_SOLID_BREP('against',#{shell})")


def free_face_box_brep(f: P21, size=(10.0, 20.0, 30.0)) -> int:
    """A box of six planar faces that share no vertex and no edge, each face with its own:
    the plane's normal into the box and ``same_sense`` false, so the face itself faces out,
    and its loop counter-clockwise about the plane's normal, so the loop runs against the
    face. Every face's loops run against it and no edge joins two faces, so no check of
    neighbours can say which way a face should go."""
    W, D, H = size
    ids = []
    for cs, n, x in _BOX_SIDES:
        b = Brep(f)
        P = [(W * c[0], D * c[1], H * c[2]) for c in cs]
        loop = []
        for k in range(4):
            pa, pb = P[k], P[(k + 1) % 4]
            loop.append((b.edge(f.line(pa, tuple(pb[i] - pa[i] for i in range(3))), pa, pb), True))
        loop = [(e, not a) for e, a in reversed(loop)]
        b.face(f.plane(P[0], tuple(-c for c in n), x), [loop], same_sense=False)
        ids.extend(b.face_ids)
    shell = f.add("CLOSED_SHELL(''," + _list(f"#{i}" for i in ids) + ")")
    return f.add(f"MANIFOLD_SOLID_BREP('free faces',#{shell})")


def sphere_seam_cap_brep(f: P21, r=10.0, zc=5.0, name="seam cap") -> int:
    """The sphere below the plane z = ``zc`` on a disc: its spherical face bounded by the
    rim and by its seam run from the rim down to the south pole and back up, as some
    writers store a cap (the seam once each way, one after the other)."""
    b = Brep(f)
    rho = math.sqrt(r * r - zc * zc)
    top, pole = (rho, 0.0, zc), (0.0, 0.0, -r)
    rim = b.edge(f.circle((0, 0, zc), (0, 0, 1), (1, 0, 0), rho), top, top)
    meridian = f.circle((0, 0, 0), (0, -1, 0), (1, 0, 0), r)
    seam = b.edge(f.add(f"SEAM_CURVE('',#{meridian},(),.CURVE_3D.)"), pole, top)
    b.face(f.sphere((0, 0, 0), r), [[(rim, False), (seam, False), (seam, True)]])
    b.face(f.plane((0, 0, zc), (0, 0, 1), (1, 0, 0)), [[(rim, True)]])
    return b.solid(name)


def cornered_square_sheet(f: P21, s=10.0, *, surface: str = "bspline") -> int:
    """A square sheet bounded by one closed cubic B-spline edge whose control points are
    each corner three times over, so the curve stops dead at every corner (its speed is
    nought at four knots) and turns there. ``surface`` ``bspline`` lays the face on a flat
    bilinear B-spline surface, ``plane`` on a plane."""
    b = Brep(f)
    a, bb, c, d = (0.0, 0.0, 0.0), (s, 0.0, 0.0), (s, s, 0.0), (0.0, s, 0.0)
    pts = [a, a, a, bb, bb, bb, c, c, c, d, d, d, a]
    inner = len(pts) - 4
    curve = f.bspline_curve(3, pts, [4] + [1] * inner + [4], [float(k) for k in range(inner + 2)])
    edge = b.edge(curve, a, a)
    if surface == "bspline":
        top = f.bspline_surface(1, 1, [[a, d], [bb, c]], [2, 2], [0.0, 1.0], [2, 2], [0.0, 1.0])
    else:
        top = f.plane((0, 0, 0), (0, 0, 1), (1, 0, 0))
    b.face(top, [[(edge, True)]])
    return f.add(f"SHELL_BASED_SURFACE_MODEL('',(#{b.shell('OPEN_SHELL')}))")


def overrun_strip_sheet(f: P21, over=0.3, R=20.0, L=10.0, Wd=2.0, n=24) -> int:
    """A strip ``Wd`` mm wide bent round a ``R`` mm radius (a rational quadratic B-spline
    surface along its ``L`` mm length, straight across it) whose face runs ``over`` mm on
    past the surface's end: its far edge stands beyond the end, and its bottom edge, a
    cubic B-spline on the bend, dips below the surface's side there. Those edges lie off
    the surface (its nearest points are on its own edge), by more than a fine chord
    tolerance but within what the tessellator accepts. The face's area is that of the
    region its edges bound on the bend: ``(L + over) * Wd`` and the dip, ``over`` deep
    over its last ``over + 1`` mm, ``over * (over + 1) / 3``."""
    b = Brep(f)

    def P(x, y):
        a = x / R
        return (R * math.sin(a), y, R - R * math.cos(a))

    w = math.cos(L / R / 2)
    row0 = [P(0, 0), (R * math.tan(L / R / 2), 0.0, 0.0), P(L, 0)]
    rows = [[(q[0], 0.0, q[2]), (q[0], Wd, q[2])] for q in row0]
    weights = [[1.0, 1.0], [w, w], [1.0, 1.0]]
    srf = f.bspline_surface(2, 1, rows, [3, 3], [0.0, 1.0], [2, 2], [0.0, 1.0], weights=weights)
    far = L + over
    xs = [far * k / n for k in range(n + 1)]
    bottom = [P(x, -over * max(0.0, (x - L + 1.0) / (far - L + 1.0)) ** 2) for x in xs]
    m = len(bottom)
    curve = f.bspline_curve(3, bottom, [4] + [1] * (m - 4) + [4], [float(k) for k in range(m - 2)])
    c00, c10, c11, c01 = bottom[0], bottom[-1], P(far, Wd), P(0, Wd)
    e0 = b.edge(curve, c00, c10)
    e1 = b.edge(f.line(c10, tuple(c11[i] - c10[i] for i in range(3))), c10, c11)
    e2 = b.edge(f.circle((0, Wd, R), (0, -1, 0), (0, 0, -1), R), c01, c11)
    e3 = b.edge(f.line(c00, (0, 1, 0)), c00, c01)
    b.face(srf, [[(e0, True), (e1, True), (e2, False), (e3, False)]])
    return f.add(f"SHELL_BASED_SURFACE_MODEL('',(#{b.shell('OPEN_SHELL')}))")


def crossed_torus_patch_sheet(f: P21, R=5.0, r=10.0, u1=1.5, v0=2.5, v1=3.8) -> int:
    """A patch of a torus whose major radius is under its minor one, on its part inside
    the axis, where ``R + r cos v`` is below nought throughout: u from 0 to ``u1``, v from
    ``v0`` to ``v1``, bounded by two arcs about the axis and two arcs of its minor circle."""
    b = Brep(f)

    def S(u, v):
        rho = R + r * math.cos(v)
        return (rho * math.cos(u), rho * math.sin(u), r * math.sin(v))

    c00, c10, c11, c01 = S(0, v0), S(u1, v0), S(u1, v1), S(0, v1)
    rims = [
        f.circle((0, 0, r * math.sin(v)), (0, 0, 1), (1, 0, 0), abs(R + r * math.cos(v))) for v in (v0, v1)
    ]
    tubes = []
    for u in (0.0, u1):
        e = (math.cos(u), math.sin(u), 0.0)
        tubes.append(f.circle((R * e[0], R * e[1], 0.0), (e[1], -e[0], 0.0), e, r))
    bottom, top = b.edge(rims[0], c00, c10), b.edge(rims[1], c01, c11)
    left, right = b.edge(tubes[0], c00, c01), b.edge(tubes[1], c10, c11)
    loop = [(bottom, True), (right, True), (top, False), (left, False)]
    b.face(f.torus((0, 0, 0), (0, 0, 1), R, r), [loop])
    return f.add(f"SHELL_BASED_SURFACE_MODEL('',(#{b.shell('OPEN_SHELL')}))")


def ogive_brep(f: P21, rb=10.0, h=30.0, name="ogive") -> int:
    """A tangent ogive nose cone of base radius ``rb`` and height ``h`` on the z axis, as
    OCCT writes a revolved arc: a SURFACE_OF_REVOLUTION of a whole CIRCLE whose centre is
    off the axis, crossing it at the tip, bounded by the base circle and its seam up to the
    tip and back; and a disc."""
    b = Brep(f)
    R = (rb * rb + h * h) / (2.0 * rb)
    profile = f.circle((rb - R, 0, 0), (0, -1, 0), (1, 0, 0), R)
    side = f.add(f"SURFACE_OF_REVOLUTION('',#{profile},#{f.axis1((0, 0, 0), (0, 0, 1))})")
    base, tip = (rb, 0.0, 0.0), (0.0, 0.0, h)
    rim = b.edge(f.circle((0, 0, 0), (0, 0, 1), (1, 0, 0), rb), base, base)
    seam = b.edge(f.add(f"SEAM_CURVE('',#{profile},(),.CURVE_3D.)"), base, tip)
    b.face(side, [[(rim, True), (seam, True), (seam, False)]])
    b.face(f.plane((0, 0, 0), (0, 0, -1), (1, 0, 0)), [[(rim, False)]])
    return b.solid(name)


def ogive_volume(rb=10.0, h=30.0, n=20000) -> float:
    """The volume of :func:`ogive_brep`, by the midpoint rule over its height."""
    R = (rb * rb + h * h) / (2.0 * rb)
    dz = h / n
    return sum(math.pi * (rb - R + math.sqrt(R * R - ((k + 0.5) * dz) ** 2)) ** 2 for k in range(n)) * dz


def open_conic_plate_sheet(f: P21, kind="hyperbola", *, composite=False) -> int:
    """A flat plate in z = 0 between an arc of a hyperbola (semi-axes 4 and 3, t from -1.5
    to 1.5) or a parabola (focal distance 2, t from -1.5 to 1.5) and the chord across its
    ends. ``composite`` makes the whole boundary one closed edge on a COMPOSITE_CURVE of a
    trimmed line and the conic trimmed against its sense by its end points."""
    b = Brep(f)
    T = 1.5
    if kind == "hyperbola":
        a, bb = 4.0, 3.0
        conic = f.add(f"HYPERBOLA('',#{f.axis2((0, 0, 0), (0, 0, 1), (1, 0, 0))},{_f(a)},{_f(bb)})")
        lo, hi = (a * math.cosh(T), -bb * math.sinh(T), 0.0), (a * math.cosh(T), bb * math.sinh(T), 0.0)
    else:
        fd = 2.0
        conic = f.add(f"PARABOLA('',#{f.axis2((0, 0, 0), (0, 0, 1), (1, 0, 0))},{_f(fd)})")
        lo, hi = (fd * T * T, -2 * fd * T, 0.0), (fd * T * T, 2 * fd * T, 0.0)
    span = hi[1] - lo[1]
    chord_line = f.line(lo, (0, 1, 0))
    plane = f.plane((0, 0, 0), (0, 0, 1), (1, 0, 0))
    if composite:
        up = f.add(
            f"TRIMMED_CURVE('',#{chord_line},(PARAMETER_VALUE(0.)),(PARAMETER_VALUE({_f(span)})),.T.,"
            ".PARAMETER.)"
        )
        back = f.add(f"TRIMMED_CURVE('',#{conic},(#{f.point(hi)}),(#{f.point(lo)}),.F.,.CARTESIAN.)")
        segs = [f.add(f"COMPOSITE_CURVE_SEGMENT(.CONTINUOUS.,.T.,#{c})") for c in (up, back)]
        ring = b.edge(f.add(f"COMPOSITE_CURVE('',(#{segs[0]},#{segs[1]}),.F.)"), lo, lo)
        b.face(plane, [[(ring, True)]])
    else:
        chord = b.edge(chord_line, lo, hi)
        arc = b.edge(f.add(f"SURFACE_CURVE('',#{conic},(),.CURVE_3D.)"), lo, hi)
        b.face(plane, [[(chord, True), (arc, False)]])
    return f.add(f"SHELL_BASED_SURFACE_MODEL('',(#{b.shell('OPEN_SHELL')}))")


def open_conic_plate_area(kind="hyperbola") -> float:
    """The area of :func:`open_conic_plate_sheet`."""
    T = 1.5
    if kind == "hyperbola":
        return 4.0 * 3.0 * (math.sinh(T) * math.cosh(T) - T)
    return 8.0 / 3.0 * 2.0**2 * T**3


def torus_seam_band_shell(f: P21, R=10.0, r=3.0, *, against: bool = True) -> int:
    """The outer half of a torus as an open shell of one face bounded by one loop: round
    its lower rim, up its seam, round its upper rim the other way and down the seam again.
    ``against`` stores that loop running against the face, as OCCT writes a fillet's."""
    b = Brep(f)
    p0, p1 = (R, 0.0, -r), (R, 0.0, r)
    lo = b.edge(f.circle((0, 0, -r), (0, 0, 1), (1, 0, 0), R), p0, p0)
    hi = b.edge(f.circle((0, 0, r), (0, 0, 1), (1, 0, 0), R), p1, p1)
    tube = f.circle((R, 0, 0), (0, -1, 0), (1, 0, 0), r)
    seam = b.edge(f.add(f"SEAM_CURVE('',#{tube},(),.CURVE_3D.)"), p0, p1)
    loop = [(lo, True), (seam, True), (hi, False), (seam, False)]
    if against:
        loop = [(e, not a) for e, a in reversed(loop)]
    b.face(f.torus((0, 0, 0), (0, 0, 1), R, r), [loop])
    return f.add(f"SHELL_BASED_SURFACE_MODEL('',(#{b.shell('OPEN_SHELL')}))")


# --------------------------------------------------------------------------- files
def part_file(
    items_fn,
    *,
    name: str = "part",
    length: str = "mm",
    angle: str = "rad",
    schema: str = "AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }",
    kind: str = "ADVANCED_BREP_SHAPE_REPRESENTATION",
    via_srr: bool = True,
) -> tuple[P21, dict]:
    """A one-part file whose shape holds what ``items_fn(f)`` returns (a list of item
    ids). Returns the writer and the ids made (``pd``, ``rep``, ``items``)."""
    f = P21(schema)
    ctx = f.units(length, angle)
    items = items_fn(f)
    pd = f.product(name)
    sr, geo = f.shape(pd, items, ctx, kind=kind, via_srr=via_srr)
    return f, {"pd": pd, "rep": sr, "geo": geo, "items": items, "ctx": ctx}


def box_file(**kw) -> bytes:
    f, _ids = part_file(lambda f: [box_brep(f)], **kw)
    return f.bytes()


def assembly_file(*, order: str = "child_first", nested: bool = False, mapped: bool = False) -> bytes:
    """An assembly of a 10 x 20 x 30 mm box placed twice: at the origin, and turned a
    quarter about z and moved 50 mm along x. ``nested`` puts the second through a
    sub-assembly moved 100 mm along y; ``mapped`` places the parts by MAPPED_ITEMs
    instead of context-dependent shape representations."""
    f = P21()
    ctx = f.units()
    box = box_brep(f)
    box_pd = f.product("box part")
    box_rep, _geo = f.shape(box_pd, [box], ctx)
    top_pd = f.product("top assembly")
    pds = f.add(f"PRODUCT_DEFINITION_SHAPE('','',#{top_pd})")
    if mapped:
        rmap = f.add(f"REPRESENTATION_MAP(#{f.axis2()},#{box_rep})")
        m1 = f.add(f"MAPPED_ITEM('box 1',#{rmap},#{f.axis2()})")
        m2 = f.add(f"MAPPED_ITEM('box 2',#{rmap},#{f.axis2((50, 0, 0), (0, 0, 1), (0, 1, 0))})")
        top_rep = f.add(f"SHAPE_REPRESENTATION('',(#{m1},#{m2}),#{ctx})")
        f.add(f"SHAPE_DEFINITION_REPRESENTATION(#{pds},#{top_rep})")
        f.add(f"NEXT_ASSEMBLY_USAGE_OCCURRENCE('1','box 1','',#{top_pd},#{box_pd},$)")
        f.add(f"NEXT_ASSEMBLY_USAGE_OCCURRENCE('2','box 2','',#{top_pd},#{box_pd},$)")
        return f.bytes()
    top_rep = f.add(f"SHAPE_REPRESENTATION('',(#{f.axis2()}),#{ctx})")
    f.add(f"SHAPE_DEFINITION_REPRESENTATION(#{pds},#{top_rep})")
    f.occurrence(top_pd, box_pd, top_rep, box_rep, at=(0, 0, 0), name="box 1", order=order)
    if nested:
        sub_pd = f.product("sub assembly")
        sub_pds = f.add(f"PRODUCT_DEFINITION_SHAPE('','',#{sub_pd})")
        sub_rep = f.add(f"SHAPE_REPRESENTATION('',(#{f.axis2()}),#{ctx})")
        f.add(f"SHAPE_DEFINITION_REPRESENTATION(#{sub_pds},#{sub_rep})")
        f.occurrence(sub_pd, box_pd, sub_rep, box_rep, at=(50, 0, 0), x=(0, 1, 0), name="box 2", order=order)
        f.occurrence(top_pd, sub_pd, top_rep, sub_rep, at=(0, 100, 0), name="sub 1", order=order)
    else:
        f.occurrence(top_pd, box_pd, top_rep, box_rep, at=(50, 0, 0), x=(0, 1, 0), name="box 2", order=order)
    return f.bytes()


def faceted_box(f: P21, size=(10.0, 20.0, 30.0), *, concave: bool = False) -> int:
    """A FACETED_BREP box of POLY_LOOPs sharing their points, or (``concave``) an L-shaped
    prism whose two L faces are concave hexagons."""
    if concave:
        # an L of side 20 with a 10 x 10 notch, 10 high
        outline = [(0, 0), (20, 0), (20, 10), (10, 10), (10, 20), (0, 20)]
        h = 10.0
        bottom = [f.point((x, y, 0.0)) for x, y in outline]
        top = [f.point((x, y, h)) for x, y in outline]
        faces = [_poly_face(f, list(reversed(bottom))), _poly_face(f, top)]
        n = len(outline)
        for k in range(n):
            j = (k + 1) % n
            faces.append(_poly_face(f, [bottom[k], bottom[j], top[j], top[k]]))
    else:
        W, D, H = size
        P = {(i, j, k): f.point((W * i, D * j, H * k)) for i in (0, 1) for j in (0, 1) for k in (0, 1)}
        quads = [
            ((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)),
            ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)),
            ((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)),
            ((0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)),
            ((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)),
            ((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)),
        ]
        faces = [_poly_face(f, [P[c] for c in q]) for q in quads]
    shell = f.add(f"CLOSED_SHELL('',{_list(f'#{i}' for i in faces)})")
    return f.add(f"FACETED_BREP('faceted',#{shell})")


def _poly_face(f: P21, points) -> int:
    loop = f.add(f"POLY_LOOP('',{_list(f'#{p}' for p in points)})")
    bound = f.add(f"FACE_OUTER_BOUND('',#{loop},.T.)")
    return f.add(f"FACE_SURFACE('',(#{bound}),#{f.plane((0, 0, 0), (0, 0, 1))},.T.)")


def tessellated_box(f: P21, *, complex_form: bool = False) -> int:
    """A 10 x 20 x 30 mm box as AP242 tessellated geometry: a TESSELLATED_SOLID of six
    TRIANGULATED_FACEs over one COORDINATES_LIST (or, ``complex_form``, of
    COMPLEX_TRIANGULATED_FACEs with a strip and a fan, through a pnindex)."""
    W, D, H = 10.0, 20.0, 30.0
    pts = [(W * i, D * j, H * k) for i in (0, 1) for j in (0, 1) for k in (0, 1)]
    index = {(i, j, k): 1 + 4 * i + 2 * j + k for i in (0, 1) for j in (0, 1) for k in (0, 1)}
    coords = f.add(f"COORDINATES_LIST('',8,{_list(_list(_f(c) for c in p) for p in pts)})")
    quads = [
        ((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)),
        ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)),
        ((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)),
        ((0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)),
        ((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)),
        ((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)),
    ]
    faces = []
    for k, q in enumerate(quads):
        a, b, c, d = (index[v] for v in q)
        if not complex_form:
            tris = _list(_list(str(v) for v in t) for t in ((a, b, c), (a, c, d)))
            faces.append(f.add(f"TRIANGULATED_FACE('',#{coords},0,(),$,(),{tris})"))
        else:
            # through a pnindex that lists the four corners: local 1..4
            pn = _list(str(v) for v in (a, b, c, d))
            if k % 2:
                strips, fans = (
                    "((1,2,4,3))",
                    "()",
                )  # a strip a, b, d, c: triangles (a,b,d) and (b,c,d)... reversed
                strips = "((2,3,1,4))"
            else:
                strips, fans = "()", "((1,2,3,4))"
            faces.append(f.add(f"COMPLEX_TRIANGULATED_FACE('',#{coords},0,(),$,{pn},{strips},{fans})"))
    return f.add(f"TESSELLATED_SOLID('tessellated',{_list(f'#{i}' for i in faces)},$)")


def escapes_file() -> bytes:
    """A box whose product name and header use every string escape."""
    bs = "\\"
    name = (
        "caf"
        + bs
        + "X"
        + bs
        + "E9 "
        + bs
        + "X2"
        + bs
        + "00E900E8"
        + bs
        + "X0"
        + bs
        + " "
        + bs
        + "X4"
        + bs
        + "0001F600"
        + bs
        + "X0"
        + bs
        + " "
        + bs
        + "S"
        + bs
        + "i "
        + bs
        + "PB"
        + bs
        + bs
        + "S"
        + bs
        + "1 "
        + "it''s "
        + bs
        + bs
        + " done"
    )
    f = P21()
    ctx = f.units()
    box = box_brep(f)
    app = f.add("APPLICATION_CONTEXT('automotive design')")
    pc = f.add(f"PRODUCT_CONTEXT('',#{app},'mechanical')")
    prod = f.add(f"PRODUCT('id','{name}','',(#{pc}))")
    pdf = f.add(f"PRODUCT_DEFINITION_FORMATION('','',#{prod})")
    pdc = f.add(f"PRODUCT_DEFINITION_CONTEXT('part definition',#{app},'design')")
    pd = f.add(f"PRODUCT_DEFINITION('design','',#{pdf},#{pdc})")
    f.shape(pd, [box], ctx)
    return f.bytes()


def alibre_file() -> bytes:
    """Part 21 in Alibre Design's private schema, as its design database stores it."""
    f = P21(("ALIBRE_SCHEMA", "CONFIG_CONTROL_DESIGN"))
    f.add("SCHEMAVERSION(1)")
    return f.bytes()


__all__ = [
    "P21",
    "Brep",
    "alibre_file",
    "assembly_file",
    "box_brep",
    "box_file",
    "bspline_box_brep",
    "composite_cylinder_brep",
    "cone_brep",
    "cylinder_brep",
    "elliptic_prism_brep",
    "escapes_file",
    "faceted_box",
    "half_cylinder_brep",
    "hemisphere_brep",
    "holed_plate_brep",
    "nurbs_cylinder_brep",
    "part_file",
    "periodic_ring",
    "periodic_hoop_brep",
    "revolved_brep",
    "sphere_seam_brep",
    "tessellated_box",
    "torus_band_shell",
    "void_box_brep",
]
