"""Write ``rocket.step``, a small model rocket, with CadQuery.

Run it from this folder with an interpreter where CadQuery imports, for example
``uv run --with cadquery python make_rocket.py``. The model, in millimetres:

* a body tube, a cylinder of radius 10 from z = 0 to z = 60;
* a nose, an arc from (10, 60) through (7, 78) to the tip at (0, 90) turned
  about Z: the arc's centre is off the axis, so OCCT writes the nose as a
  SURFACE_OF_REVOLUTION of a whole CIRCLE that crosses its axis at the tip;
* a skirt, a cone from radius 10 at z = 0 out to radius 13 at z = -10, closed by a
  flat base whose rim is rounded by a 1 mm fillet (a TOROIDAL_SURFACE);
* three fins, 2 mm thick plates 120 degrees apart, from radius 5 out to 22 and
  from z = -8 to 25, so their flat sides are trimmed by the body cylinder and
  the skirt cone.

The header's name, author and organisation are set to neutral values and the
time stamp is fixed, so the file is the same on every run with the same
CadQuery.
"""

import re
from pathlib import Path

import cadquery as cq

HERE = Path(__file__).resolve().parent
OUT = HERE / "rocket.step"


def rocket() -> cq.Workplane:
    body = cq.Workplane("XY").circle(10).extrude(60)
    nose = (
        cq.Workplane("XZ")
        .moveTo(0, 60)
        .lineTo(10, 60)
        .threePointArc((7, 78), (0, 90))
        .close()
        .revolve(360, (0, 0, 0), (0, 1, 0))
    )
    skirt = (
        cq.Workplane("XY")
        .workplane(offset=-10)
        .circle(13)
        .workplane(offset=10)
        .circle(10)
        .loft()
        .faces("<Z")
        .edges()
        .fillet(1)
    )
    shape = body.union(nose).union(skirt)
    for k in range(3):
        fin = cq.Workplane("XY").box(17, 2, 33, centered=(False, True, False)).translate((5, 0, -8))
        shape = shape.union(fin.rotate((0, 0, 0), (0, 0, 1), 120 * k))
    return shape


def main() -> None:
    cq.exporters.export(rocket(), str(OUT), "STEP")
    text = OUT.read_text(encoding="ascii")
    text = re.sub(
        r"FILE_NAME\([^;]*\);",
        "FILE_NAME('rocket.step','2026-10-17T00:00:00',(''),(''),'CadQuery','CadQuery','');",
        text,
        count=1,
        flags=re.S,
    )
    OUT.write_text(text, encoding="ascii", newline="\n")


if __name__ == "__main__":
    main()
