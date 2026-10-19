# The AP214 product structure around the shapes: contexts, units, products, shapes.
#
# Derived work. The application context, units, uncertainty and representation
# context, and the product, its formation, definition and shape around the
# representation, follow header_entities and write_step in
#   BlinkingSun/sldprt2step, file sldprt2step_lib/step/mapper.py
#   https://github.com/BlinkingSun/sldprt2step, commit fa954124f4f126e0c465c8f96454978ac80b812e
#   Licensed under the Apache License, Version 2.0. sldprt2step is a port of
#   open-sld-to-step 0.1.0 (Apache-2.0). See NOTICE in the SolidSeas repository.
# Modified for SolidSeas (2026-10-03): the values SOLIDWORKS writes in its own STEP
# of fixture o02 ('NONE' labels, the 'UNKNOWN' product definition, the formation with
# specified source, the 'WORKASPACE' context, the uncertainty's description), in the
# AP214 entities where AP203's differ; the representation named after the document;
# a geometric context whose uncertainty covers the product's approximations; sheets in
# a manifold surface representation.
"""The AP214 product structure: a part's product, with its own geometric context, and an
assembly's, whose occurrences place its parts (:class:`AssemblyShape`, :func:`place`).

The values are those SOLIDWORKS writes in its own STEP of fixture o02
(``tests/fixtures/o02_boxA.step``, AP203): ``'NONE'`` labels, PRODUCT_DEFINITION
``'UNKNOWN'``, PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE ``'ANY'`` with
``.NOT_KNOWN.``, units millimetre, radian and steradian, the uncertainty's
description ``'NONE'`` and the representation context ``'NONE'``, ``'WORKASPACE'``
(SOLIDWORKS' spelling). Where AP214 has its own entities the AP214 ones are
written: PRODUCT_CONTEXT and PRODUCT_DEFINITION_CONTEXT for AP203's
MECHANICAL_CONTEXT and DESIGN_CONTEXT, the category ``'part'`` for ``'detail'``,
and none of AP203's approval, person, organisation, date and security entities.
"""

from . import part21 as p21
from .entities import NONE

APPLICATION = "core data for automotive mechanical design processes"


class Contexts:
    """The file's application context and the product and definition contexts, written
    once."""

    def __init__(self, w: p21.Writer) -> None:
        self.app = w.add(f"APPLICATION_CONTEXT({p21.text(APPLICATION)})")
        w.add(
            f"APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2003,#{self.app})"
        )
        self.product = w.add(f"PRODUCT_CONTEXT({NONE},#{self.app},'mechanical')")
        self.definition = w.add(f"PRODUCT_DEFINITION_CONTEXT('detailed design',#{self.app},'design')")
        self._units: tuple[int, int, int] | None = None
        self.w = w

    def units(self) -> tuple[int, int, int]:
        if self._units is None:
            w = self.w
            mm = w.add("(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.))")
            rad = w.add("(NAMED_UNIT(*)PLANE_ANGLE_UNIT()SI_UNIT($,.RADIAN.))")
            sr = w.add("(NAMED_UNIT(*)SI_UNIT($,.STERADIAN.)SOLID_ANGLE_UNIT())")
            self._units = (mm, rad, sr)
        return self._units

    def geometric(self, uncertainty_mm: float) -> int:
        """A GEOMETRIC_REPRESENTATION_CONTEXT in millimetres with this uncertainty."""
        w = self.w
        mm, rad, sr = self.units()
        unc = w.add(
            f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE({p21.real(uncertainty_mm)}),#{mm},"
            f"'distance_accuracy_value',{NONE})"
        )
        return w.add(
            f"(GEOMETRIC_REPRESENTATION_CONTEXT(3)GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#{unc}))"
            f"GLOBAL_UNIT_ASSIGNED_CONTEXT((#{mm},#{rad},#{sr}))REPRESENTATION_CONTEXT({NONE},'WORKASPACE'))"
        )


def origin(w: p21.Writer) -> int:
    p = w.point((0.0, 0.0, 0.0))
    z = w.direction((0.0, 0.0, 1.0))
    x = w.direction((1.0, 0.0, 0.0))
    return w.add(f"AXIS2_PLACEMENT_3D({NONE},#{p},#{z},#{x})")


def product(ctx: Contexts, name: str, category: str) -> int:
    """A PRODUCT with its category, formation and definition; returns the
    PRODUCT_DEFINITION's id."""
    w = ctx.w
    label = p21.text(name)
    prod = w.add(f"PRODUCT({label},{label},'',(#{ctx.product}))")
    w.add(f"PRODUCT_RELATED_PRODUCT_CATEGORY({p21.text(category)},'',(#{prod}))")
    pdf = w.add(f"PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE('ANY','',#{prod},.NOT_KNOWN.)")
    return w.add(f"PRODUCT_DEFINITION('UNKNOWN','',#{pdf},#{ctx.definition})")


def part_shape(ctx: Contexts, pd: int, name: str, solids, sheets, uncertainty_mm: float) -> tuple[int, int]:
    """The shape of a part product: its solids in an ADVANCED_BREP_SHAPE_REPRESENTATION,
    its sheets in a MANIFOLD_SURFACE_SHAPE_REPRESENTATION, or both related to a
    SHAPE_REPRESENTATION holding the origin. ``solids`` and ``sheets`` are the items'
    ids, written already. Returns ``(representation, origin)``: the id of the
    representation the product's shape uses and of its origin, an item of it, which an
    assembly places the part by."""
    w = ctx.w
    geo = ctx.geometric(uncertainty_mm)
    label = p21.text(name)
    pds = w.add(f"PRODUCT_DEFINITION_SHAPE({NONE},{NONE},#{pd})")
    o = origin(w)
    if solids and not sheets:
        rep = w.add(f"ADVANCED_BREP_SHAPE_REPRESENTATION({label},{p21.refs([*solids, o])},#{geo})")
    elif sheets and not solids:
        rep = w.add(f"MANIFOLD_SURFACE_SHAPE_REPRESENTATION({label},{p21.refs([*sheets, o])},#{geo})")
    else:
        rep = w.add(f"SHAPE_REPRESENTATION({label},(#{o}),#{geo})")
        o2 = origin(w)
        absr = w.add(f"ADVANCED_BREP_SHAPE_REPRESENTATION({label},{p21.refs([*solids, o2])},#{geo})")
        o3 = origin(w)
        mssr = w.add(f"MANIFOLD_SURFACE_SHAPE_REPRESENTATION({label},{p21.refs([*sheets, o3])},#{geo})")
        w.add(f"SHAPE_REPRESENTATION_RELATIONSHIP({NONE},{NONE},#{absr},#{rep})")
        w.add(f"SHAPE_REPRESENTATION_RELATIONSHIP({NONE},{NONE},#{mssr},#{rep})")
    w.add(f"SHAPE_DEFINITION_REPRESENTATION(#{pds},#{rep})")
    return rep, o


class AssemblyShape:
    """The shape of an assembly product: a SHAPE_REPRESENTATION holding its origin and the
    axis placement of each occurrence :func:`place` adds; :meth:`close` writes its item
    list once they are all known (the representation's line is written first, so that
    the occurrences can name it)."""

    def __init__(self, ctx: Contexts, pd: int, name: str, uncertainty_mm: float) -> None:
        w = ctx.w
        self.w, self.label = w, p21.text(name)
        self.geo = ctx.geometric(uncertainty_mm)
        pds = w.add(f"PRODUCT_DEFINITION_SHAPE({NONE},{NONE},#{pd})")
        self.items = [origin(w)]
        self.rep = w.add(f"SHAPE_REPRESENTATION({self.label},(#{self.items[0]}),#{self.geo})")
        w.add(f"SHAPE_DEFINITION_REPRESENTATION(#{pds},#{self.rep})")

    def close(self) -> None:
        self.w.lines[self.rep - 1] = f"SHAPE_REPRESENTATION({self.label},{p21.refs(self.items)},#{self.geo})"


def place(
    ctx: Contexts,
    parent_pd: int,
    parent_rep: int,
    child_pd: int,
    child_rep: int,
    child_origin: int,
    placement,
    ident: str,
    name: str,
) -> int:
    """One occurrence of ``child_pd`` in ``parent_pd``, at ``placement`` (a point ``p`` of
    the child at ``rotation @ p + translation_m`` in the parent, metres): a
    NEXT_ASSEMBLY_USAGE_OCCURRENCE and the CONTEXT_DEPENDENT_SHAPE_REPRESENTATION that
    maps the child's origin onto an axis placement in the parent's representation.
    Returns that axis placement's id, which the caller adds to ``parent_rep``'s items
    (:meth:`AssemblyShape.close`), so that it is an item of the representation it is in."""
    w = ctx.w
    r, t = placement.rotation, placement.translation_m
    at = w.point(tuple(v * p21.SCALE for v in t))
    z = w.direction((r[0][2], r[1][2], r[2][2]))
    x = w.direction((r[0][0], r[1][0], r[2][0]))
    axis = w.add(f"AXIS2_PLACEMENT_3D({NONE},#{at},#{z},#{x})")
    nauo = w.add(
        f"NEXT_ASSEMBLY_USAGE_OCCURRENCE({p21.text(ident)},{p21.text(name)},'',#{parent_pd},#{child_pd},$)"
    )
    pds = w.add(f"PRODUCT_DEFINITION_SHAPE({NONE},{NONE},#{nauo})")
    idt = w.add(f"ITEM_DEFINED_TRANSFORMATION({NONE},{NONE},#{child_origin},#{axis})")
    rr = w.add(
        f"(REPRESENTATION_RELATIONSHIP({NONE},{NONE},#{child_rep},#{parent_rep})"
        f"REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION(#{idt})SHAPE_REPRESENTATION_RELATIONSHIP())"
    )
    w.add(f"CONTEXT_DEPENDENT_SHAPE_REPRESENTATION(#{rr},#{pds})")
    return axis
