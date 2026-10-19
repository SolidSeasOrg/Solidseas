"""Synthetic model files for the format tests, written by code (no real file is used).

A :class:`Mesh` is one object in millimetres (vertices and outward, counter-clockwise
triangles over them, an optional RGBA colour); a :class:`Scene` places meshes with a
rotation (rows) and a translation in millimetres. Three shapes cover what the format
tests need: :func:`box`, :func:`holed_block` (a block with a square hole through it,
closed, of genus one) and :func:`two_object_assembly` (two boxes and a holed block,
one box turned a quarter about Z, in colours). Writers turn them into the bytes of a
file: :func:`stl_binary` and :func:`stl_ascii` here; the reader branches add theirs.

:func:`scene_document` wraps a :class:`Scene` in a small
:class:`~solidseas.formats.ModelDocument` subclass, so the export, the renderer and
the surfaces can be tested on placed, coloured objects before any reader that
produces them exists.
"""

import struct
from dataclasses import dataclass, field

Vec = tuple[float, float, float]
Rot = tuple[Vec, Vec, Vec]
IDENTITY: Rot = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
QUARTER_Z: Rot = ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))  # 90 degrees about Z


@dataclass
class Mesh:
    name: str
    vertices: list[Vec]
    triangles: list[tuple[int, int, int]]
    color: tuple[float, float, float, float] | None = None

    def volume_mm3(self) -> float:
        v = 0.0
        p = self.vertices
        for a, b, c in self.triangles:
            (ax, ay, az), (bx, by, bz), (cx, cy, cz) = p[a], p[b], p[c]
            v += ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by * cx)
        return v / 6.0


@dataclass
class Item:
    mesh: int
    rotation: Rot = IDENTITY
    translation_mm: Vec = (0.0, 0.0, 0.0)
    name: str | None = None


@dataclass
class Scene:
    meshes: list[Mesh]
    items: list[Item] = field(default_factory=list)

    def placed(self) -> list[tuple[str, list[Vec], list[tuple[int, int, int]]]]:
        """Every item's mesh moved to where the item places it."""
        out = []
        for it in self.items:
            m = self.meshes[it.mesh]
            r, t = it.rotation, it.translation_mm
            pts = [
                (
                    r[0][0] * x + r[0][1] * y + r[0][2] * z + t[0],
                    r[1][0] * x + r[1][1] * y + r[1][2] * z + t[1],
                    r[2][0] * x + r[2][1] * y + r[2][2] * z + t[2],
                )
                for x, y, z in m.vertices
            ]
            out.append((it.name or m.name, pts, m.triangles))
        return out

    def volume_mm3(self) -> float:
        return sum(self.meshes[it.mesh].volume_mm3() for it in self.items)


# --------------------------------------------------------------------------- shapes
def box(
    lx: float, ly: float, lz: float, origin: Vec = (0.0, 0.0, 0.0), name: str = "box", color=None
) -> Mesh:
    """A closed box from ``origin`` to ``origin + (lx, ly, lz)``, 12 outward triangles."""
    x0, y0, z0 = origin
    x1, y1, z1 = x0 + lx, y0 + ly, z0 + lz
    v = [
        (x0, y0, z0),
        (x1, y0, z0),
        (x1, y1, z0),
        (x0, y1, z0),
        (x0, y0, z1),
        (x1, y0, z1),
        (x1, y1, z1),
        (x0, y1, z1),
    ]
    t = [
        (0, 2, 1), (0, 3, 2),  # bottom, -z
        (4, 5, 6), (4, 6, 7),  # top, +z
        (0, 1, 5), (0, 5, 4),  # front, -y
        (1, 2, 6), (1, 6, 5),  # right, +x
        (2, 3, 7), (2, 7, 6),  # back, +y
        (3, 0, 4), (3, 4, 7),  # left, -x
    ]  # fmt: skip
    return Mesh(name, v, t, color)


def holed_block(
    size: float = 30.0, hole: float = 10.0, height: float = 10.0, name: str = "holed block", color=None
) -> Mesh:
    """A ``size`` x ``size`` x ``height`` block with a centred square hole of side ``hole``
    through it: 16 vertices, 32 outward triangles, closed, of genus one."""
    a, b = (size - hole) / 2.0, (size + hole) / 2.0
    outer = [(0.0, 0.0), (size, 0.0), (size, size), (0.0, size)]
    inner = [(a, a), (b, a), (b, b), (a, b)]
    v = [(x, y, 0.0) for x, y in outer] + [(x, y, 0.0) for x, y in inner]
    v += [(x, y, height) for x, y in outer] + [(x, y, height) for x, y in inner]
    ob, ib, ot, it = 0, 4, 8, 12
    t = []
    for i in range(4):
        j = (i + 1) % 4
        t += [(ot + i, ot + j, it + j), (ot + i, it + j, it + i)]  # top, +z
        t += [(ob + i, ib + j, ob + j), (ob + i, ib + i, ib + j)]  # bottom, -z
        t += [(ob + i, ob + j, ot + j), (ob + i, ot + j, ot + i)]  # outer sides, outwards
        t += [(ib + i, it + j, ib + j), (ib + i, it + i, it + j)]  # the hole's sides, into the hole
    return Mesh(name, v, t, color)


RED = (0.8, 0.1, 0.1, 1.0)
BLUE = (0.1, 0.2, 0.8, 1.0)


def two_object_assembly() -> Scene:
    """A red 10 x 20 x 30 mm box placed twice (once turned a quarter about Z and moved
    50 mm along X) and a blue holed block moved 50 mm along Y: 20,000 mm3 in all."""
    return Scene(
        [box(10, 20, 30, name="box", color=RED), holed_block(color=BLUE)],
        [
            Item(0, name="box 1"),
            Item(0, QUARTER_Z, (50.0, 0.0, 0.0), name="box 2"),
            Item(1, IDENTITY, (0.0, 50.0, 0.0), name="block 1"),
        ],
    )


# --------------------------------------------------------------------------- STL
def _normal(a: Vec, b: Vec, c: Vec) -> Vec:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    n = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
    ln = (n[0] ** 2 + n[1] ** 2 + n[2] ** 2) ** 0.5 or 1.0
    return (n[0] / ln, n[1] / ln, n[2] / ln)


def stl_binary(scene: Scene | Mesh, *, header: bytes = b"synthetic binary STL", attribute: int = 0) -> bytes:
    """A binary STL of every placed triangle (or one mesh's), in millimetres."""
    if isinstance(scene, Mesh):
        scene = Scene([scene], [Item(0)])
    rec = struct.Struct("<12fH")
    body = bytearray()
    n = 0
    for _name, pts, tris in scene.placed():
        for a, b, c in tris:
            body += rec.pack(*_normal(pts[a], pts[b], pts[c]), *pts[a], *pts[b], *pts[c], attribute)
            n += 1
    return header[:80].ljust(80, b" ") + struct.pack("<I", n) + bytes(body)


def stl_ascii(scene: Scene | Mesh, *, newline: str = "\n", upper: bool = False) -> bytes:
    """An ASCII STL with one solid per placed item (or one for a mesh), named as it is."""
    if isinstance(scene, Mesh):
        scene = Scene([scene], [Item(0)])
    lines = []
    for name, pts, tris in scene.placed():
        lines.append(f"solid {name}")
        for a, b, c in tris:
            nx, ny, nz = _normal(pts[a], pts[b], pts[c])
            lines.append(f"  facet normal {nx:e} {ny:e} {nz:e}")
            lines.append("    outer loop")
            for p in (pts[a], pts[b], pts[c]):
                lines.append(f"      vertex {p[0]!r} {p[1]!r} {p[2]!r}")
            lines.append("    endloop")
            lines.append("  endfacet")
        lines.append(f"endsolid {name}")
    text = newline.join(lines) + newline
    return (text.upper() if upper else text).encode("ascii")


# --------------------------------------------------------------------------- a scene as a document
def scene_document(scene: Scene, *, name: str = "scene.stl", doc_type: str = "assembly", kind: str = "mesh"):
    """A :class:`~solidseas.formats.ModelDocument` whose scene is ``scene`` (format id
    ``stl``, for the registry), for tests of what consumes scenes."""
    from solidseas.formats._source import Source
    from solidseas.formats.base import ModelDocument, ModelNode
    from solidseas.formats.limits import Limits
    from solidseas.formats.solidworks.components import Placement

    class SceneDocument(ModelDocument):
        format = "stl"

        def _tree(self, clock):
            nodes = [ModelNode("0", None, "scene", "assembly")]
            for i, it in enumerate(scene.items):
                nodes.append(ModelNode(str(i + 1), "0", it.name, "component", it.mesh))
            return nodes

        def _scene(self, sb):
            for m in scene.meshes:
                mb = sb.mesh(name=m.name, scale_m=0.001, color=m.color)
                mb.add_vertices(c for p in m.vertices for c in p)
                mb.add_triangles(i for t in m.triangles for i in t)
                mb.finish()
            for i, it in enumerate(scene.items):
                t = tuple(c / 1000.0 for c in it.translation_mm)
                sb.add_item(it.mesh, str(i + 1), Placement(it.rotation, t))

    doc = SceneDocument(Source(b"synthetic"), name=name, path=None, file_info=None, limits=Limits())
    doc.doc_type = doc_type
    doc.kind = kind
    doc.set_units("mm", "file")
    return doc
