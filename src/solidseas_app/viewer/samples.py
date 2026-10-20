"""Synthetic 3D files of every format the viewer reads, for its self-test of formats.

:func:`write_samples` writes, into a folder of the caller's (the self-test's own
temporary folder), one small file of each format SolidSeas reads, each written
here by code from the published structure of its format: boxes and blocks whose
sizes are known, two assemblies, a stored preview in the 3MF and Alibre Design
files, and one IGES file that is listed but not read. Every name, number and
string in them is invented here; nothing is copied from another file.

* ``box.stl`` (STL): a 10 x 20 x 30 mm box, binary;
* ``block.obj`` with ``block.mtl`` (OBJ), ``block.ply`` (PLY, binary little-endian)
  and ``block.off`` (OFF): a 20 x 20 x 10 mm block, the OBJ in quads with a material;
* ``box.gltf`` (its buffer in a ``data:`` URI) and ``box.glb`` (glTF): the box, Y-up
  in metres, which the reader turns Z-up;
* ``box.amf`` (AMF): the box;
* ``pair.3mf`` (3MF): an assembly, the box placed twice and the block once, with a
  thumbnail;
* ``bracket.step`` (STEP AP214): the box as a B-rep solid, and ``pair.step`` an
  assembly placing it twice;
* ``bracket.x_t`` and ``bracket.x_b`` (Parasolid): the STEP box's body, written by
  the library's own transmit writers;
* ``cube.sab`` (ACIS, SAB version 2100): a 10 mm cube;
* ``cube.AD_PRT`` (Alibre Design): the cube with its ACIS body, its display mesh, a
  bitmap thumbnail and properties, and ``pair.AD_ASM`` an assembly placing it twice,
  found by its document GUID;
* ``sheet.igs`` (IGES): listed only, as SolidSeas reads IGES only through the OCCT
  backend extension, which the samples' folder never has.

Nothing here imports Qt.
"""

import base64
import json
import math
import os
import struct
import uuid
import zipfile
from io import BytesIO
from typing import Any

Vec = tuple[float, float, float]
BOX = (10.0, 20.0, 30.0)  # millimetres
BLOCK = (20.0, 20.0, 10.0)
CUBE_CM = 1.0  # the Alibre cube's side, in its centimetres
CUBE_GUID = "5a3c1e7b-2d4f-4b6a-9c8e-0f1a2b3c4d5e"
ASSEMBLY_GUID = "7e6d5c4b-3a29-4817-a6f5-e4d3c2b1a090"
UNREADABLE = ("sheet.igs",)
# The corners of a box, counter-clockwise seen from outside each face, with its normal.
_FACES = (
    (((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)), (0, 0, -1)),
    (((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)), (0, 0, 1)),
    (((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)), (0, -1, 0)),
    (((0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)), (0, 1, 0)),
    (((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)), (-1, 0, 0)),
    (((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)), (1, 0, 0)),
)


def _corner(size: Vec, k) -> Vec:
    return (size[0] * k[0], size[1] * k[1], size[2] * k[2])


def box_mesh(size: Vec) -> tuple[list[Vec], list[tuple[int, int, int]]]:
    """A closed box over 8 shared vertices, 12 triangles wound outward."""
    keys = sorted({k for face, _n in _FACES for k in face})
    index = {k: i for i, k in enumerate(keys)}
    verts = [_corner(size, k) for k in keys]
    tris = []
    for face, _n in _FACES:
        a, b, c, d = (index[k] for k in face)
        tris += [(a, b, c), (a, c, d)]
    return verts, tris


def box_quads(size: Vec) -> tuple[list[Vec], list[tuple[int, int, int, int]]]:
    keys = sorted({k for face, _n in _FACES for k in face})
    index = {k: i for i, k in enumerate(keys)}
    return [_corner(size, k) for k in keys], [tuple(index[k] for k in face) for face, _n in _FACES]


# --------------------------------------------------------------------------- images
def _png(width: int, height: int, rgb_at) -> bytes:
    from solidseas.formats._source import encode_png

    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            pixels += bytes(rgb_at(x, y))
    return encode_png(width, height, bytes(pixels), 3)


def _bmp(width: int, height: int, rgb_at) -> bytes:
    """A 24-bit bottom-up Windows bitmap."""
    stride = (width * 3 + 3) // 4 * 4
    rows = bytearray()
    for y in range(height - 1, -1, -1):  # bottom-up
        row = bytearray()
        for x in range(width):
            r, g, b = rgb_at(x, y)
            row += bytes((b, g, r))
        rows += row + b"\0" * (stride - len(row))
    info = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(rows), 2835, 2835, 0, 0)
    return b"BM" + struct.pack("<IHHI", 14 + len(info) + len(rows), 0, 0, 54) + info + bytes(rows)


def _badge(x: int, y: int, w: int, h: int, color) -> tuple[int, int, int]:
    """A light picture with a coloured square in its middle, as a stored thumbnail."""
    inside = w // 4 <= x < 3 * w // 4 and h // 4 <= y < 3 * h // 4
    return color if inside else (235, 238, 242)


# --------------------------------------------------------------------------- meshes
def stl_binary(size: Vec = BOX) -> bytes:
    verts, tris = box_mesh(size)
    out = bytearray(b"SolidSeas self-test box".ljust(80, b" ")) + struct.pack("<I", len(tris))
    for a, b, c in tris:
        p, q, r = verts[a], verts[b], verts[c]
        u = tuple(q[i] - p[i] for i in range(3))
        v = tuple(r[i] - p[i] for i in range(3))
        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        m = math.sqrt(sum(x * x for x in n)) or 1.0
        out += struct.pack("<12fH", *(x / m for x in n), *p, *q, *r, 0)
    return bytes(out)


def obj_files(size: Vec = BLOCK) -> dict[str, bytes]:
    verts, quads = box_quads(size)
    lines = ["# SolidSeas self-test block", "mtllib block.mtl", "o block", "usemtl teal"]
    lines += [f"v {x!r} {y!r} {z!r}" for x, y, z in verts]
    lines += ["f " + " ".join(str(i + 1) for i in q) for q in quads]
    mtl = "newmtl teal\nKd 0.2 0.6 0.6\n"
    return {"block.obj": ("\n".join(lines) + "\n").encode(), "block.mtl": mtl.encode()}


def ply_binary(size: Vec = BLOCK) -> bytes:
    verts, tris = box_mesh(size)
    head = (
        "ply\nformat binary_little_endian 1.0\ncomment SolidSeas self-test block\n"
        f"element vertex {len(verts)}\nproperty float x\nproperty float y\nproperty float z\n"
        f"element face {len(tris)}\nproperty list uchar int vertex_indices\nend_header\n"
    ).encode("ascii")
    body = b"".join(struct.pack("<3f", *v) for v in verts)
    body += b"".join(struct.pack("<B3i", 3, *t) for t in tris)
    return head + body


def off_text(size: Vec = BLOCK) -> bytes:
    verts, quads = box_quads(size)
    lines = ["OFF", "# SolidSeas self-test block", f"{len(verts)} {len(quads)} 0"]
    lines += [f"{x!r} {y!r} {z!r}" for x, y, z in verts]
    lines += [f"4 {a} {b} {c} {d}" for a, b, c, d in quads]
    return ("\n".join(lines) + "\n").encode()


def _gltf_json(size: Vec, uri: str | None) -> tuple[dict[str, Any], bytes]:
    """glTF is Y-up in metres: the box's Z (its 30 mm) becomes Y."""
    verts, tris = box_mesh(size)
    positions = [(x / 1000.0, z / 1000.0, -y / 1000.0) for x, y, z in verts]
    pos = b"".join(struct.pack("<3f", *p) for p in positions)
    idx = b"".join(struct.pack("<3H", *t) for t in tris)
    idx += b"\0" * (-len(idx) % 4)
    data = pos + idx
    lo = [min(p[i] for p in positions) for i in range(3)]
    hi = [max(p[i] for p in positions) for i in range(3)]
    buffer: dict[str, Any] = {"byteLength": len(data)}
    if uri is not None:
        buffer["uri"] = uri
    doc = {
        "asset": {"version": "2.0", "generator": "SolidSeas self-test"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "box"}],
        "meshes": [{"name": "box", "primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "mode": 4}]}],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(positions),
                "type": "VEC3",
                "min": lo,
                "max": hi,
            },
            {"bufferView": 1, "componentType": 5123, "count": 3 * len(tris), "type": "SCALAR"},
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(pos)},
            {"buffer": 0, "byteOffset": len(pos), "byteLength": 6 * len(tris)},
        ],
        "buffers": [buffer],
    }
    return doc, data


def gltf_embedded(size: Vec = BOX) -> bytes:
    doc, data = _gltf_json(size, None)
    doc["buffers"][0]["uri"] = "data:application/octet-stream;base64," + base64.b64encode(data).decode()
    return json.dumps(doc, indent=1).encode()


def glb(size: Vec = BOX) -> bytes:
    doc, data = _gltf_json(size, None)
    text = json.dumps(doc).encode()
    text += b" " * (-len(text) % 4)
    data += b"\0" * (-len(data) % 4)
    body = struct.pack("<I4s", len(text), b"JSON") + text + struct.pack("<I4s", len(data), b"BIN\0") + data
    return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body


def amf(size: Vec = BOX) -> bytes:
    verts, tris = box_mesh(size)
    vx = "".join(
        f"<vertex><coordinates><x>{x!r}</x><y>{y!r}</y><z>{z!r}</z></coordinates></vertex>"
        for x, y, z in verts
    )
    tr = "".join(f"<triangle><v1>{a}</v1><v2>{b}</v2><v3>{c}</v3></triangle>" for a, b, c in tris)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<amf unit="millimeter" version="1.1">'
        '<metadata type="name">SolidSeas self-test box</metadata>'
        f'<object id="1"><mesh><vertices>{vx}</vertices><volume>{tr}</volume></mesh></object></amf>\n'
    ).encode()


def threemf_assembly() -> bytes:
    """A 3MF package: a box and a block, the box placed twice, with a thumbnail."""
    box, block = box_mesh(BOX), box_mesh(BLOCK)

    def mesh_xml(oid: int, name: str, mesh) -> str:
        verts, tris = mesh
        vx = "".join(f'<vertex x="{x!r}" y="{y!r}" z="{z!r}"/>' for x, y, z in verts)
        tr = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in tris)
        return (
            f'<object id="{oid}" type="model" name="{name}">'
            f"<mesh><vertices>{vx}</vertices><triangles>{tr}</triangles></mesh></object>"
        )

    model = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" unit="millimeter">'
        '<metadata name="Title">SolidSeas self-test pair</metadata>'
        '<metadata name="Application">SolidSeas self-test</metadata>'
        f"<resources>{mesh_xml(1, 'box', box)}{mesh_xml(2, 'block', block)}</resources>"
        '<build><item objectid="1"/><item objectid="1" transform="1 0 0 0 1 0 0 0 1 40 0 0"/>'
        '<item objectid="2" transform="1 0 0 0 1 0 0 0 1 0 40 0"/></build></model>\n'
    )
    types = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
        '<Default Extension="png" ContentType="image/png"/></Types>\n'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
        '<Relationship Target="/Metadata/thumbnail.png" Id="rel1" '
        'Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail"/>'
        "</Relationships>\n"
    )
    thumb = _png(64, 48, lambda x, y: _badge(x, y, 64, 48, (42, 143, 143)))
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)
        z.writestr("Metadata/thumbnail.png", thumb)
    return buf.getvalue()


# --------------------------------------------------------------------------- STEP
def _f(x: float) -> str:
    r = repr(float(x))
    return r if "." in r or "e" in r else r + "."


class _P21:
    """A Part 21 exchange structure written instance by instance."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def add(self, text: str) -> int:
        self.lines.append(text)
        return len(self.lines)

    def point(self, p) -> int:
        return self.add(f"CARTESIAN_POINT('',({','.join(_f(x) for x in p)}))")

    def direction(self, d) -> int:
        return self.add(f"DIRECTION('',({','.join(_f(x) for x in d)}))")

    def axis2(self, origin=(0, 0, 0), z=(0, 0, 1), x=(1, 0, 0)) -> int:
        return self.add(
            f"AXIS2_PLACEMENT_3D('',#{self.point(origin)},#{self.direction(z)},#{self.direction(x)})"
        )

    def context(self) -> int:
        mm = self.add("(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.))")
        rad = self.add("(NAMED_UNIT(*)PLANE_ANGLE_UNIT()SI_UNIT($,.RADIAN.))")
        sr = self.add("(NAMED_UNIT(*)SI_UNIT($,.STERADIAN.)SOLID_ANGLE_UNIT())")
        unc = self.add(
            f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-05),#{mm},'distance_accuracy_value','')"
        )
        return self.add(
            f"(GEOMETRIC_REPRESENTATION_CONTEXT(3)GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#{unc}))"
            f"GLOBAL_UNIT_ASSIGNED_CONTEXT((#{mm},#{rad},#{sr}))REPRESENTATION_CONTEXT('',''))"
        )

    def product(self, name: str) -> int:
        if not hasattr(self, "_app"):
            self._app = self.add("APPLICATION_CONTEXT('automotive design')")
            self.add(
                "APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,"
                f"#{self._app})"
            )
        pc = self.add(f"PRODUCT_CONTEXT('',#{self._app},'mechanical')")
        prod = self.add(f"PRODUCT('{name}','{name}','',(#{pc}))")
        pdf = self.add(f"PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE('','',#{prod},.NOT_KNOWN.)")
        pdc = self.add(f"PRODUCT_DEFINITION_CONTEXT('part definition',#{self._app},'design')")
        return self.add(f"PRODUCT_DEFINITION('design','',#{pdf},#{pdc})")

    def box(self, size: Vec) -> int:
        """A box as a MANIFOLD_SOLID_BREP of six planar faces on twelve lines."""
        vertices: dict = {}
        edges: dict = {}

        def vertex(k) -> int:
            if k not in vertices:
                vertices[k] = self.add(f"VERTEX_POINT('',#{self.point(_corner(size, k))})")
            return vertices[k]

        def edge(a, b) -> tuple[int, bool]:
            lo, hi = (a, b) if a < b else (b, a)
            if (lo, hi) not in edges:
                p, q = _corner(size, lo), _corner(size, hi)
                d = tuple(q[i] - p[i] for i in range(3))
                n = math.sqrt(sum(x * x for x in d))
                vec = self.add(f"VECTOR('',#{self.direction(tuple(x / n for x in d))},{_f(n)})")
                line = self.add(f"LINE('',#{self.point(p)},#{vec})")
                edges[(lo, hi)] = self.add(f"EDGE_CURVE('',#{vertex(lo)},#{vertex(hi)},#{line},.T.)")
            return edges[(lo, hi)], (a, b) == (lo, hi)

        faces = []
        for keys, normal in _FACES:
            oes = []
            for k in range(4):
                e, along = edge(keys[k], keys[(k + 1) % 4])
                oes.append(self.add(f"ORIENTED_EDGE('',*,*,#{e},{'.T.' if along else '.F.'})"))
            loop = self.add(f"EDGE_LOOP('',({','.join(f'#{o}' for o in oes)}))")
            bound = self.add(f"FACE_OUTER_BOUND('',#{loop},.T.)")
            x = (1, 0, 0) if normal[0] == 0 else (0, 1, 0)
            plane = self.add(f"PLANE('',#{self.axis2(_corner(size, keys[0]), normal, x)})")
            faces.append(self.add(f"ADVANCED_FACE('',(#{bound}),#{plane},.T.)"))
        shell = self.add(f"CLOSED_SHELL('',({','.join(f'#{f}' for f in faces)}))")
        return self.add(f"MANIFOLD_SOLID_BREP('box',#{shell})")

    def shape(self, pd: int, items: list[int], ctx: int) -> int:
        pds = self.add(f"PRODUCT_DEFINITION_SHAPE('','',#{pd})")
        refs = ",".join(f"#{i}" for i in [self.axis2(), *items])
        rep = self.add(f"ADVANCED_BREP_SHAPE_REPRESENTATION('',({refs}),#{ctx})")
        self.add(f"SHAPE_DEFINITION_REPRESENTATION(#{pds},#{rep})")
        return rep

    def place(self, parent_pd, child_pd, parent_rep, child_rep, at: Vec, name: str) -> None:
        nauo = self.add(f"NEXT_ASSEMBLY_USAGE_OCCURRENCE('{name}','{name}','',#{parent_pd},#{child_pd},$)")
        pds = self.add(f"PRODUCT_DEFINITION_SHAPE('','',#{nauo})")
        idt = self.add(f"ITEM_DEFINED_TRANSFORMATION('','',#{self.axis2()},#{self.axis2(at)})")
        rr = self.add(
            f"(REPRESENTATION_RELATIONSHIP('','',#{child_rep},#{parent_rep})"
            f"REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION(#{idt})SHAPE_REPRESENTATION_RELATIONSHIP())"
        )
        self.add(f"CONTEXT_DEPENDENT_SHAPE_REPRESENTATION(#{rr},#{pds})")

    def bytes(self, name: str) -> bytes:
        head = [
            "ISO-10303-21;",
            "HEADER;",
            "FILE_DESCRIPTION(('SolidSeas self-test'),'2;1');",
            f"FILE_NAME('{name}','2026-01-01T00:00:00',('SolidSeas'),(''),'SolidSeas samples',"
            "'SolidSeas self-test','');",
            "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));",
            "ENDSEC;",
            "DATA;",
        ]
        body = [f"#{i}={t};" for i, t in enumerate(self.lines, 1)]
        return ("\n".join([*head, *body, "ENDSEC;", "END-ISO-10303-21;"]) + "\n").encode("ascii")


def step_part(size: Vec = BOX) -> bytes:
    f = _P21()
    ctx = f.context()
    pd = f.product("bracket")
    f.shape(pd, [f.box(size)], ctx)
    return f.bytes("bracket.step")


def step_assembly(size: Vec = BOX) -> bytes:
    """The box placed twice, 40 mm apart along X."""
    f = _P21()
    ctx = f.context()
    box_pd = f.product("box")
    box_rep = f.shape(box_pd, [f.box(size)], ctx)
    top_pd = f.product("pair")
    top_rep = f.shape(top_pd, [], ctx)
    f.place(top_pd, box_pd, top_rep, box_rep, (0.0, 0.0, 0.0), "box 1")
    f.place(top_pd, box_pd, top_rep, box_rep, (40.0, 0.0, 0.0), "box 2")
    return f.bytes("pair.step")


def parasolid_files(step: bytes) -> dict[str, bytes]:
    """The STEP box's body as Parasolid text and binary transmit files, with the common
    header, through the library's own writers."""
    from solidseas.formats import open_model
    from solidseas.formats.solidworks import parasolid

    with open_model(step, name="bracket.step") as doc:
        xt = doc.bodies()[0].transmit
    text = parasolid.text_header(xt, fmt="text", key="bracket", file="bracket.x_t") + parasolid.write_text(xt)
    binary = parasolid.text_header(xt, fmt="binary", key="bracket", file="bracket.x_b").encode("latin-1")
    return {"bracket.x_t": text.encode("latin-1"), "bracket.x_b": binary + parasolid.write_binary(xt)}


# --------------------------------------------------------------------------- ACIS SAB
_INT, _DBL, _STR, _TRUE, _FALSE, _PTR, _ID, _IDX, _END, _POS, _VEC, _ENUM = (
    0x04, 0x06, 0x07, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x11, 0x13, 0x14, 0x15,
)  # fmt: skip
_NULL = (_PTR, -1)


def _record(name: str, values) -> bytes:
    out = bytearray()
    parts = name.split("-")
    for k, p in enumerate(parts):
        raw = p.encode("latin-1")
        out += bytes((_ID if k == len(parts) - 1 else _IDX, len(raw))) + raw
    for tag, v in values:
        out.append(tag)
        if tag in (_INT, _PTR, _ENUM):
            out += struct.pack("<i", v)
        elif tag == _DBL:
            out += struct.pack("<d", v)
        elif tag in (_POS, _VEC):
            out += struct.pack("<3d", *v)
        elif tag == _STR:
            raw = v.encode("latin-1")
            out += bytes((len(raw),)) + raw
    out.append(_END)
    return bytes(out)


def sab_cube(side: float = CUBE_CM, mm_per_unit: float = 10.0) -> bytes:
    """A cube of ``side`` model units as an ACIS SAB stream (version 2100): body, lump,
    shell, six planar faces with a loop each, coedges with their partners, twelve
    straight edges, eight vertices, with each face's and edge's PersistentID."""
    size = (side, side, side)
    keys = sorted({k for face, _n in _FACES for k in face})
    edge_keys: list[tuple] = []
    for face, _n in _FACES:
        for k in range(4):
            a, b = face[k], face[(k + 1) % 4]
            pair = (a, b) if a < b else (b, a)
            if pair not in edge_keys:
                edge_keys.append(pair)
    n_faces, n_edges, n_vertices = len(_FACES), len(edge_keys), len(keys)
    # Record numbers, in the order written.
    body, lump, shell = 0, 1, 2
    face0 = 3
    loop0 = face0 + n_faces
    coedge0 = loop0 + n_faces
    edge0 = coedge0 + 4 * n_faces
    vertex0 = edge0 + n_edges
    point0 = vertex0 + n_vertices
    plane0 = point0 + n_vertices
    curve0 = plane0 + n_faces
    attrib0 = curve0 + n_edges

    def pre(attrib=_NULL):
        return [attrib, (_INT, -1), (_INT, -1), _NULL]

    def b(v: bool):
        return (_TRUE if v else _FALSE, None)

    zero = (0.0, 0.0, 0.0)
    recs: list[tuple[str, list]] = [
        ("body", pre() + [(_PTR, lump), _NULL, _NULL, b(False)]),
        ("lump", pre() + [_NULL, (_PTR, shell), (_PTR, body), b(False)]),
        ("shell", pre() + [_NULL, _NULL, (_PTR, face0), _NULL, (_PTR, lump), b(False)]),
    ]
    coedge_of: dict[tuple, list[int]] = {}
    coedges: list[tuple[int, int, bool, int]] = []  # (record, edge index, reversed, loop)
    for fi in range(n_faces):
        nxt = (_PTR, face0 + fi + 1) if fi + 1 < n_faces else _NULL
        recs.append(
            (
                "face",
                pre((_PTR, attrib0 + fi))
                + [nxt, (_PTR, loop0 + fi), (_PTR, shell), _NULL, (_PTR, plane0 + fi)]
                + [b(False), b(False), b(True), (_POS, zero), (_POS, zero), b(False)],
            )
        )
    for fi, (face, _normal) in enumerate(_FACES):
        recs.append(
            (
                "loop",
                pre()
                + [_NULL, (_PTR, coedge0 + 4 * fi), (_PTR, face0 + fi), b(True), (_POS, zero), (_POS, zero)]
                + [(_ENUM, 0)],
            )
        )
        for k in range(4):
            a, z = face[k], face[(k + 1) % 4]
            pair = (a, z) if a < z else (z, a)
            rec = coedge0 + 4 * fi + k
            coedge_of.setdefault(pair, []).append(rec)
            coedges.append((rec, edge_keys.index(pair), (a, z) != pair, loop0 + fi))
    for rec, ei, rev, lp in coedges:
        fi, k = divmod(rec - coedge0, 4)
        pair = edge_keys[ei]
        partner = next(c for c in coedge_of[pair] if c != rec)
        ring = [coedge0 + 4 * fi + j for j in range(4)]
        recs.append(
            (
                "coedge",
                pre()
                + [(_PTR, ring[(k + 1) % 4]), (_PTR, ring[k - 1]), (_PTR, partner), (_PTR, edge0 + ei)]
                + [b(rev), (_PTR, lp), _NULL],
            )
        )
    for ei, (a, z) in enumerate(edge_keys):
        p, q = _corner(size, a), _corner(size, z)
        length = math.sqrt(sum((q[i] - p[i]) ** 2 for i in range(3)))
        recs.append(
            (
                "edge",
                pre((_PTR, attrib0 + n_faces + ei))
                + [
                    (_PTR, vertex0 + keys.index(a)),
                    (_DBL, 0.0),
                    (_PTR, vertex0 + keys.index(z)),
                    (_DBL, length),
                ]
                + [(_PTR, coedge_of[(a, z)][0]), (_PTR, curve0 + ei), b(False), (_STR, "unknown")]
                + [b(True), (_POS, zero), (_POS, zero)],
            )
        )
    for vi, k in enumerate(keys):
        first = next(edge0 + ei for ei, pair in enumerate(edge_keys) if k in pair)
        recs.append(("vertex", pre() + [(_PTR, first), (_PTR, point0 + vi)]))
    for k in keys:
        recs.append(("point", pre() + [(_POS, _corner(size, k))]))
    for face, normal in _FACES:
        p0, p1 = _corner(size, face[0]), _corner(size, face[1])
        u = tuple(p1[i] - p0[i] for i in range(3))
        recs.append(("plane-surface", pre() + [(_POS, p0), (_VEC, normal), (_VEC, u)] + [b(False)] * 5))
    for a, z in edge_keys:
        p, q = _corner(size, a), _corner(size, z)
        length = math.sqrt(sum((q[i] - p[i]) ** 2 for i in range(3)))
        d = tuple((q[i] - p[i]) / length for i in range(3))
        recs.append(("straight-curve", pre() + [(_POS, p), (_VEC, d), b(False), b(False)]))
    owners = [face0 + fi for fi in range(n_faces)] + [edge0 + ei for ei in range(n_edges)]
    for pid, owner in enumerate(owners, 1):
        recs.append(
            (
                "PersistentID-Alibre-attrib",
                [_NULL, (_INT, -1), _NULL, _NULL, (_PTR, owner), (_INT, 0), (_INT, pid)],
            )
        )
    head = bytearray(b"ACIS BinaryFile") + struct.pack("<4i", 2100, 0, 1, 0)
    for text in ("SolidSeas samples", "SolidSeas self-test", "Thu Jan 01 00:00:00 2026"):
        raw = text.encode()
        head += bytes((_STR, len(raw))) + raw
    for x in (mm_per_unit, 1e-6, 1e-10):
        head += bytes((_DBL,)) + struct.pack("<d", x)
    end = bytes((_ID, 16)) + b"End-of-ACIS-data"
    return bytes(head) + b"".join(_record(n, v) for n, v in recs) + end


# --------------------------------------------------------------------------- compound files
_SECTOR, _MINI, _CUTOFF = 512, 64, 4096
_FREE, _END_CHAIN, _FAT, _NONE = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFF


def compound_file(streams: dict[str, bytes]) -> bytes:
    """A version 3 compound file (MS-CFB) holding ``streams`` at its root."""
    names = sorted(streams, key=lambda n: (len(n), n.upper()))
    entries = [{"name": "Root Entry", "type": 5, "data": b""}] + [
        {"name": n, "type": 2, "data": streams[n]} for n in names
    ]
    mini, minifat = bytearray(), []
    for e in entries[1:]:
        if len(e["data"]) < _CUTOFF:
            n = max(1, -(-len(e["data"]) // _MINI))
            start = len(minifat)
            minifat += [start + k + 1 for k in range(n - 1)] + [_END_CHAIN]
            e["start"] = start
            mini += e["data"] + b"\0" * (n * _MINI - len(e["data"]))
    sectors: list[bytes] = []
    fat: list[int] = []

    def place(data: bytes) -> int:
        n = max(1, -(-len(data) // _SECTOR))
        start = len(sectors)
        for k in range(n):
            sectors.append(data[k * _SECTOR : (k + 1) * _SECTOR].ljust(_SECTOR, b"\0"))
            fat.append(start + k + 1 if k < n - 1 else _END_CHAIN)
        return start

    for e in entries[1:]:
        if len(e["data"]) >= _CUTOFF:
            e["start"] = place(e["data"])
    entries[0]["start"] = place(bytes(mini)) if mini else _END_CHAIN
    entries[0]["data"] = bytes(mini)
    minifat_bytes = b"".join(struct.pack("<I", x) for x in minifat)
    minifat_bytes += struct.pack("<I", _FREE) * (-(len(minifat_bytes) // 4) % (_SECTOR // 4))
    first_minifat = place(minifat_bytes) if minifat else _END_CHAIN
    n_minifat = -(-len(minifat_bytes) // _SECTOR) if minifat else 0
    directory = bytearray()
    for i, e in enumerate(entries):
        name = e["name"].encode("utf-16-le") + b"\0\0"
        child = 1 if i == 0 and len(entries) > 1 else _NONE
        right = i + 1 if 0 < i < len(entries) - 1 else _NONE  # a right-sibling chain in CFB order
        directory += struct.pack(
            "<64sHBBIII16sIQQIQ", name, len(name), e["type"], 1, _NONE, right, child, b"\0" * 16, 0, 0, 0,
            e.get("start", 0), len(e["data"]),
        )  # fmt: skip
    directory += b"\0" * (-len(directory) % _SECTOR)
    first_dir = place(bytes(directory))
    n_fat = 1
    while len(sectors) + n_fat > n_fat * (_SECTOR // 4):
        n_fat += 1
    fat_ids = list(range(len(sectors), len(sectors) + n_fat))
    fat += [_FAT] * n_fat
    fat += [_FREE] * (n_fat * (_SECTOR // 4) - len(fat))
    fat_bytes = b"".join(struct.pack("<I", x) for x in fat)
    for k in range(n_fat):
        sectors.append(fat_bytes[k * _SECTOR : (k + 1) * _SECTOR])
    header = struct.pack(
        "<8s16sHHHHH6sIIIIIIIII", bytes.fromhex("d0cf11e0a1b11ae1"), b"\0" * 16, 0x3E, 3, 0xFFFE, 9, 6,
        b"\0" * 6, 0, n_fat, first_dir, 0, _CUTOFF, first_minifat, n_minifat, _END_CHAIN, 0,
    )  # fmt: skip
    header += b"".join(struct.pack("<I", x) for x in fat_ids + [_FREE] * (109 - len(fat_ids)))
    return header + b"".join(sectors)


# --------------------------------------------------------------------------- Alibre Design
def _u16(text: str) -> bytes:
    raw = text.encode("utf-8")
    return struct.pack(">H", len(raw)) + raw


def _identity(guid: str, path: str) -> str:
    element = f'<Repository Guid="{{{guid.upper()}}}" Name="Samples" V3Name="" Type="Self-test"/>'
    return f"{element}:{path}|{guid}||1|1"


def _entry(key: str, typ: int, values, flags: int = 1) -> bytes:
    out = _u16(key) + struct.pack("<iii", flags, typ, len(values))
    for v in values:
        if typ == 0x14:
            out += _u16(v)
        elif typ == 0x0A:
            out += struct.pack("<i", v)
        elif typ == 0x1E:
            out += struct.pack("<d", v)
        elif typ == 0x28:
            out += struct.pack("<i", len(v)) + v
    return out


def _prop_data(name: str, color) -> bytes:
    thumb = _bmp(48, 48, lambda x, y: _badge(x, y, 48, 48, color))
    return (
        _entry("name", 0x14, [name])
        + _entry("description", 0x14, ["A SolidSeas self-test file"])
        + _entry("Creation_Author", 0x14, ["SolidSeas"], 0)
        + _entry("stepFileVersion", 0x14, ["SolidSeas samples 1,0,0"])
        + _entry("Weight", 0x0A, [1])
        + _entry("snapshot", 0x28, [thumb])
    )


def _light(rgba) -> bytes:
    return (
        b"\0\0\0\0"
        + _u16("Config<0>")
        + b"\0\0\0\0\x01"
        + bytes(rgba)
        + bytes((55, 55, 55, 255))
        + b"\0" * 12
    )


def _design(records: list[str]) -> bytes:
    head = (
        "ISO-10303-21;\r\nHEADER;\r\nFILE_DESCRIPTION(('SolidSeas self-test'),'2;1');\r\n"
        "FILE_NAME('sample','2026-01-01T00:00:00',(''),(''),'SolidSeas','SolidSeas','');\r\n"
        "FILE_SCHEMA (('ALIBRE_SCHEMA','CONFIG_CONTROL_DESIGN'));\r\nENDSEC;\r\nDATA;\r\n"
    )
    return (head + "\r\n".join(records) + "\r\nENDSEC;\r\nEND-ISO-10303-21;\r\n").encode("latin-1")


def _dictionary(entries: list[tuple[str, bytes, int]]) -> bytes:
    out = struct.pack("<i", len(entries))
    for key, payload, count in entries:
        raw = key.encode("latin-1")
        out += struct.pack("<i", len(raw)) + raw + struct.pack("<i", count) + payload
    return out


def _mesh_data(side: float, rgba) -> bytes:
    """The display mesh of the cube: one block per face (two triangles), then the edges."""
    ints = _dictionary(
        [
            ("SCHEMA_VERSION_KEY", struct.pack("<i", 3), 1),
            ("color", bytes(rgba), 1),
            ("configId", struct.pack("<i", 0), 1),
        ]
    )
    dbls = _dictionary([("extent", struct.pack("<6d", 0, 0, 0, side, side, side), 6)])
    units = b"cm"
    strs = _dictionary([("units", struct.pack("<i", len(units)) + units, 1)])
    edges: list[tuple] = []
    for face, _n in _FACES:
        for k in range(4):
            a, z = face[k], face[(k + 1) % 4]
            pair = (a, z) if a < z else (z, a)
            if pair not in edges:
                edges.append(pair)
    out = ints + dbls + strs + struct.pack("<3i", len(_FACES), len(edges), 8)
    size = (side, side, side)
    for fi, (face, normal) in enumerate(_FACES, 1):
        recs = [(*_corner(size, k), *normal, 0.0, 0.0) for k in face]
        idx = [3, 0, 1, 2, 3, 0, 2, 3, 0]
        out += struct.pack("<4iBf", fi, len(idx), len(recs), 0, 0, -1.0)
        out += b"".join(struct.pack("<8f", *r) for r in recs)
        out += struct.pack(f"<{len(idx)}i", *idx)
    for ei, (a, z) in enumerate(edges, len(_FACES) + 1):
        pts = [_corner(size, a), _corner(size, z)]
        recs = [(*p, 0, 0, 0, 0, 0) for p in pts] + [(0.0,) * 8] * 4
        idx = [2, 0, 1, 0]
        out += struct.pack("<4iBf", ei, len(idx), len(recs), 0, 0, -1.0)
        out += b"".join(struct.pack("<8f", *r) for r in recs)
        out += struct.pack(f"<{len(idx)}i", *idx)
    return out


def alibre_part() -> bytes:
    rgba = (160, 82, 45, 255)
    return compound_file(
        {
            "VERSION": _u16(_identity(CUBE_GUID, "/samples/cube")),
            "PROP_DATA": _prop_data("SolidSeas self-test cube", rgba[:3]),
            "STEP_DATA": _design(
                [
                    "#1=SCHEMAVERSION('SolidSeas samples 1,0,0','self-test schema');",
                    "#2=DESIGNPART($,(),(),$,$,$,$,(),0,$,1,1,1,1,(),(),(),$,$,$,$,0,0,0,.F.,(),$,3);",
                ]
            ),
            "LIGHT_CONFIGURATION_DATA": _light(rgba),
            "SAB_DATA": sab_cube(),
            "MESH_DATA": _mesh_data(CUBE_CM, rgba),
        }
    )


def alibre_assembly() -> bytes:
    """Two inclusions of the cube, the second 2 cm along X, found by its document GUID."""
    recs = ["#1=SCHEMAVERSION('SolidSeas samples 1,0,0','self-test schema');"]
    incs = []
    n = 10
    for k, x in enumerate((0.0, 2.0)):
        a1, a2, a3, origin, cto, rv, member, inc = range(n + 1, n + 9)
        n += 8
        recs += [
            f"#{a1}=DIRECTION($,(1.,0.,0.));",
            f"#{a2}=DIRECTION($,(0.,1.,0.));",
            f"#{a3}=DIRECTION($,(0.,0.,1.));",
            f"#{origin}=CARTESIAN_POINT($,({_f(x)},0.,0.));",
            f"#{cto}=CARTESIAN_TRANSFORMATION_OPERATOR_3D($,$,$,#{a1},#{a2},#{origin},1.,#{a3});",
            f"#{rv}=REPOSITORYVERSIONREFERENCE(1,'C','/samples/cube','{CUBE_GUID}','','',1,1,$);",
            f"#{member}=DESIGNMEMBER($,$,0,.F.,0,'{uuid.UUID(int=k + 1)}',$,$,0);",
            f"#{inc}=DESIGNINCLUSION((),(#{member}),'/samples/cube',#{rv},$,#{cto},$,.F.,$,"
            f"'{uuid.UUID(int=k + 101)}',.F.,$,0,$,'Config\\X\\3C0\\X\\3E');",
        ]
        incs.append(f"#{inc}")
    recs.append(
        f"#2=DESIGNASSEMBLY($,(),(),$,$,$,$,(),0,$,1,1,1,1,(),(),(),$,$,({','.join(incs)}),(),(),(),(),$,3);"
    )
    return compound_file(
        {
            "VERSION": _u16(_identity(ASSEMBLY_GUID, "/samples/pair")),
            "PROP_DATA": _prop_data("SolidSeas self-test pair", (90, 90, 160)),
            "STEP_DATA": _design(recs),
            "LIGHT_CONFIGURATION_DATA": _light((0, 0, 0, 0)),
            "CONSTITUENTS": _u16(_identity(CUBE_GUID, "/samples/cube")),
        }
    )


# --------------------------------------------------------------------------- the folder
def iges_stub() -> bytes:
    """An IGES start section: enough to be recognised, and listed as a file SolidSeas does
    not read without the OCCT backend extension."""
    line = "SolidSeas self-test: an IGES file is listed, not read".ljust(72) + "S      1"
    return (line + "\n").encode("ascii")


def samples() -> dict[str, bytes]:
    """Every sample file by name (see the module notes)."""
    step = step_part()
    files = {
        "box.stl": stl_binary(),
        **obj_files(),
        "block.ply": ply_binary(),
        "block.off": off_text(),
        "box.gltf": gltf_embedded(),
        "box.glb": glb(),
        "box.amf": amf(),
        "pair.3mf": threemf_assembly(),
        "bracket.step": step,
        "pair.step": step_assembly(),
        **parasolid_files(step),
        "cube.sab": sab_cube(),
        "cube.AD_PRT": alibre_part(),
        "pair.AD_ASM": alibre_assembly(),
        "sheet.igs": iges_stub(),
    }
    return files


# What each sample is read as, and the shape the self-test checks: (format id, doc_type,
# placed items, the box's size in millimetres in the file's own axes).
EXPECTED: dict[str, tuple[str, str, int, Vec]] = {
    "box.stl": ("stl", "part", 1, BOX),
    "block.obj": ("obj", "part", 1, BLOCK),
    "block.ply": ("ply", "part", 1, BLOCK),
    "block.off": ("off", "part", 1, BLOCK),
    "box.gltf": ("gltf", "part", 1, BOX),
    "box.glb": ("gltf", "part", 1, BOX),
    "box.amf": ("amf", "part", 1, BOX),
    "pair.3mf": ("3mf", "assembly", 3, (50.0, 60.0, 30.0)),
    "bracket.step": ("step", "part", 1, BOX),
    "pair.step": ("step", "assembly", 2, (50.0, 20.0, 30.0)),
    "bracket.x_t": ("parasolid", "part", 1, BOX),
    "bracket.x_b": ("parasolid", "part", 1, BOX),
    "cube.sab": ("acis", "part", 1, (10.0, 10.0, 10.0)),
    "cube.AD_PRT": ("alibre", "part", 1, (10.0, 10.0, 10.0)),
    "pair.AD_ASM": ("alibre", "assembly", 2, (30.0, 10.0, 10.0)),
}


def write_samples(folder: str) -> list[str]:
    """Write every sample into ``folder`` (made when missing; a file there is never
    replaced): the names written."""
    os.makedirs(folder, exist_ok=True)
    out = []
    for name, data in samples().items():
        path = os.path.join(folder, name)
        with open(path, "xb") as fh:
            fh.write(data)
        out.append(name)
    return out


__all__ = ["EXPECTED", "UNREADABLE", "compound_file", "sab_cube", "samples", "write_samples"]
