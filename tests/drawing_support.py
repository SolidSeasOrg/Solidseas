"""Shared helpers for the drawing tests: fixture paths, cached models of the synthetic
parts, and hand-built sheets for the writers (docs/DRAWINGS.md 19)."""

from __future__ import annotations

import functools
import hashlib
import math
import os
import struct
import zlib

import drawing_parts
from solidseas.drawing import display as D
from solidseas.drawing import facegraph
from solidseas.drawing.painter import stroke_geometry, text_run

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
COMPANY = "Example Engineering Co."  # the fictional company every test uses (18)


def fixture(name: str) -> str:
    return os.path.join(FIXTURES, name)


@functools.cache
def part(name: str):
    """``(transmit, truth)`` of a synthetic part, built once."""
    return drawing_parts.PARTS[name]()


@functools.cache
def model(name: str) -> facegraph.BrepModel:
    """The ``BrepModel`` of a synthetic part, built once."""
    xt, _truth = part(name)
    return facegraph.from_transmit(xt, name=name)


def faces(m: facegraph.BrepModel, kind: str, **where):
    """The faces of a kind whose surface has the attributes given."""
    out = []
    for f in m.faces:
        if f.kind != kind:
            continue
        if all(getattr(f.surface, k) == v for k, v in where.items()):
            out.append(f)
    return out


def close(a, b, tol=1e-9) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b, strict=True))


def tiny_png(width: int = 4, height: int = 2) -> bytes:
    """A real 8-bit RGBA PNG, as the viewer would store a logo."""
    raw = b"".join(b"\x00" + b"\x10\x20\x30\xff" * width for _ in range(height))

    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    )


def sample_sheet() -> D.Sheet:
    """An A sheet with one of every geometry primitive in a view at 1:2, a dimension, a
    note with a frame, a title field, the logo, and their painted layer."""
    view = D.ViewPlacement("v-1", (60.0, 80.0), 0.5, "")
    src = D.Src(0, "plane:0,0,1:0", "v-1")
    in_view = [
        D.Segment((0.0, 0.0), (0.1, 0.0), "visible", src),
        D.Segment((0.0, 0.02), (0.1, 0.02), "hidden", src),
        D.Arc((0.05, 0.01), 0.005, 0.0, 360.0, "visible", src),
        D.Arc((0.08, 0.01), 0.004, 90.0, 270.0, "tangent", src),
        D.EllipseArc((0.02, 0.01), (0.006, 0.0), 0.5, 0.0, math.pi, "visible", src),
        D.Spline(
            3,
            (0, 0, 0, 0, 0.5, 1, 1, 1, 1),
            ((0.0, 0.03), (0.02, 0.05), (0.04, 0.03), (0.06, 0.05), (0.08, 0.03)),
            None,
            "phantom",
            src,
        ),
        D.Polyline(((0.0, -0.01), (0.05, -0.012), (0.1, -0.01)), False, "centre", src),
    ]
    geometry = tuple(D.place(g, view) for g in in_view)
    dim = D.Dimension(
        "d-1",
        "linear",
        "v-1",
        ((60.0, 80.0), (110.0, 80.0), (85.0, 70.0)),
        (85.0, 70.0),
        0.1,
        D.DimText("100", prefix="", suffix=()),
        refs=("f-1",),
        precision=0,
    )
    note = D.Note(
        "n-1",
        (20.0, 40.0),
        (
            (
                "UNLESS OTHERWISE SPECIFIED, ALL SURFACES",
                (D.FrameItem("profile_surface", "0.4", False, "", ("A", "B", "C")),),
            ),
        ),
    )
    logo = tiny_png()
    annotations = (
        dim,
        note,
        D.TitleBlock((180.0, 10.0), 90.0, 40.0, (("company", COMPANY), ("title", 'BRACKET <& "TEST">'))),
        D.Image((182.0, 30.0), 20.0, 10.0, logo, hashlib.sha256(logo).hexdigest()),
        D.Stamp("PRELIMINARY - NOT FOR MANUFACTURE", (10.0, 5.0)),
    )
    painted = stroke_geometry(geometry) + (
        D.Stroke((("M", 60.0, 72.0), ("L", 110.0, 72.0)), 0.3, (), "dimensions", "d-1"),
        D.Fill((("M", 60.0, 72.0), ("L", 63.0, 73.0), ("L", 63.0, 71.0), ("Z",)), "dimensions", "d-1"),
        text_run(85.0, 73.0, 3.0, "100", anchor="centre", layer="dimensions", owner="d-1"),
        text_run(182.0, 20.0, 4.5, 'BRACKET <& "TEST">', bold=True, layer="title", owner="title"),
        text_run(10.0, 5.0, 3.0, "PRELIMINARY - NOT FOR MANUFACTURE", angle_deg=90.0, layer="stamp"),
        D.ImageRun(182.0, 30.0, 20.0, 10.0, logo, "title", "logo"),
    )
    return D.Sheet("A", 279.4, 215.9, (1, 2), (view,), geometry, annotations, painted)
