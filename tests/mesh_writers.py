"""Synthetic 3MF, OBJ (with MTL), PLY, OFF, glTF, GLB and AMF files for the mesh-format
tests, written by code from the shapes of ``tests/model_writers.py`` (every value is
invented here; no real file is used).

Formats that place objects (3MF, glTF, AMF) write a :class:`~model_writers.Scene`'s
meshes once and its items as placements; the others (OBJ, PLY, OFF) write every
item's triangles where the item puts them. Each writer returns the file's bytes;
the OBJ and glTF writers also return the files they name beside it, as
``{relative name: bytes}``.
"""

import base64
import io
import json
import struct
import zipfile

from model_writers import IDENTITY, Item, Mesh, Scene
from solidseas.formats._source import encode_png

CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
MATERIAL = "http://schemas.microsoft.com/3dmanufacturing/material/2015/02"
PRODUCTION = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
SLICE = "http://schemas.microsoft.com/3dmanufacturing/slice/2015/07"
VENDOR = "http://example.invalid/slicer/2026"


def as_scene(shape) -> Scene:
    return shape if isinstance(shape, Scene) else Scene([shape], [Item(0)])


def png(width: int = 8, height: int = 6, rgb=(200, 40, 40)) -> bytes:
    return encode_png(width, height, bytes(rgb) * (width * height), 3)


def _hex(color) -> str:
    return "#" + "".join(f"{round(c * 255):02X}" for c in color)


def _cells(rotation, translation) -> str:
    """A placement as 3MF's twelve transform numbers (row-vector form)."""
    r, t = rotation, translation
    return " ".join(repr(float(v)) for v in [r[j][i] for i in range(3) for j in range(3)] + list(t))


def _zip(parts: dict[str, bytes], *, method=zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=method) as z:
        for name, data in parts.items():
            z.writestr(name, data)
    return buf.getvalue()


# --------------------------------------------------------------------------- 3MF
def threemf_mesh_xml(m: Mesh, oid: int, *, pid: str | None = None, extra: str = "", tri_props=None) -> str:
    attrs = f' pid="{pid}" pindex="0"' if pid is not None else ""
    out = [f'<object id="{oid}" type="model" name="{m.name}"{attrs}{extra}><mesh><vertices>']
    out += [f'<vertex x="{x!r}" y="{y!r}" z="{z!r}"/>' for x, y, z in m.vertices]
    out.append("</vertices><triangles>")
    for k, (a, b, c) in enumerate(m.triangles):
        props = tri_props(k) if tri_props else ""
        out.append(f'<triangle v1="{a}" v2="{b}" v3="{c}"{props}/>')
    out.append("</triangles></mesh></object>")
    return "".join(out)


def threemf(
    shape,
    *,
    unit: str | None = "millimeter",
    colors: str | None = "base",
    production: bool = False,
    wrap: bool = False,
    thumbnail: bytes | None = None,
    metadata: dict | None = None,
    required: tuple[str, ...] = (),
    recommended: tuple[str, ...] = (),
    vendor: bool = False,
    model_part: str = "3D/3dmodel.model",
    extra_parts: dict | None = None,
    root_extra: str = "",
    resources_extra: str = "",
    build_xml: str | None = None,
) -> bytes:
    """A 3MF package of ``shape``. ``colors``: ``base`` (one basematerials group, each mesh
    its own entry), ``colorgroup`` (the materials extension) or None. ``production``
    puts each mesh in its own model part named with ``p:path``; ``wrap`` puts each
    mesh behind a components object, as SOLIDWORKS writes. ``required`` and
    ``recommended`` are (prefix, namespace) pairs."""
    scene = as_scene(shape)
    ns = {"m": MATERIAL} if colors == "colorgroup" else {}
    if production:
        ns["p"] = PRODUCTION
    if vendor:
        ns["slicer"] = VENDOR
    for prefix, uri in (*required, *recommended):
        ns[prefix] = uri
    decl = "".join(f' xmlns:{k}="{v}"' for k, v in ns.items())
    req = f' requiredextensions="{" ".join(p for p, _ in required)}"' if required else ""
    rec = f' recommendedextensions="{" ".join(p for p, _ in recommended)}"' if recommended else ""
    unit_attr = f' unit="{unit}"' if unit is not None else ""
    head = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<model xmlns="{CORE}"{decl}{unit_attr}{req}{rec}{root_extra}>'
    )
    meta = "".join(f'<metadata name="{k}">{v}</metadata>' for k, v in (metadata or {}).items())
    if vendor:
        meta += '<metadata name="slicer:Version">7</metadata>'
    groups = ""
    pid = None
    if colors == "base":
        entries = "".join(
            f'<base name="{m.name}" displaycolor="{_hex(m.color or (0.5, 0.5, 0.5, 1.0))}"/>'
            for m in scene.meshes
        )
        groups = f'<basematerials id="100">{entries}</basematerials>'
        pid = "100"
    elif colors == "colorgroup":
        entries = "".join(f'<m:color color="{_hex(m.color or (0.5, 0.5, 0.5, 1.0))}"/>' for m in scene.meshes)
        groups = f'<m:colorgroup id="100">{entries}</m:colorgroup>'
        pid = "100"
    parts: dict[str, bytes] = {}
    objects = []
    for i, m in enumerate(scene.meshes):
        oid = i + 1
        extra_attr = ""
        if pid is not None:
            extra_attr = f' pid="{pid}" pindex="{i}"'
        body = threemf_mesh_xml(m, oid, extra=extra_attr)
        if production:
            part = f"3D/Objects/object_{oid}.model"
            parts[part] = (
                f'<?xml version="1.0" encoding="UTF-8"?>\n<model xmlns="{CORE}"{decl}{unit_attr}{req}>'
                f"<resources>{groups}{body}</resources><build/></model>"
            ).encode()
            objects.append(
                f'<object id="{1000 + oid}" type="model" name="{m.name}"><components>'
                f'<component objectid="{oid}" p:path="/{part}"/></components></object>'
            )
        elif wrap:
            objects.append(body)
            objects.append(
                f'<object id="{1000 + oid}" type="model" name="{m.name} wrapper"><components>'
                f'<component objectid="{oid}"/></components></object>'
            )
        else:
            objects.append(body)
    if build_xml is None:
        items = []
        for it in scene.items:
            oid = it.mesh + 1 + (1000 if production or wrap else 0)
            items.append(f'<item objectid="{oid}" transform="{_cells(it.rotation, it.translation_mm)}"/>')
        build_xml = "<build>" + "".join(items) + "</build>"
    model = (
        head
        + meta
        + "<resources>"
        + ("" if production else groups)
        + resources_extra
        + "".join(objects)
        + "</resources>"
        + build_xml
        + "</model>"
    )
    rels = [
        f'<Relationship Target="/{model_part}" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
    ]
    if thumbnail is not None:
        rels.append(
            '<Relationship Target="/Metadata/thumbnail.png" Id="rel1" '
            'Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail"/>'
        )
    out = {
        "[Content_Types].xml": (
            b'<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
            b'content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
            b'relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.'
            b'3dmanufacturing-3dmodel+xml"/><Default Extension="png" ContentType="image/png"/></Types>'
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/'
            'package/2006/relationships">' + "".join(rels) + "</Relationships>"
        ).encode(),
        model_part: model.encode(),
    }
    if production:
        rels3d = "".join(
            f'<Relationship Target="/{p}" Id="r{i}" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
            for i, p in enumerate(parts)
        )
        out["3D/_rels/3dmodel.model.rels"] = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/'
            f'package/2006/relationships">{rels3d}</Relationships>'
        ).encode()
        out.update(parts)
    if thumbnail is not None:
        out["Metadata/thumbnail.png"] = thumbnail
    if vendor:
        out["Metadata/Slicer_settings.config"] = b"; invented slicer settings\nlayer_height = 0.2\n"
    out.update(extra_parts or {})
    return _zip(out)


# --------------------------------------------------------------------------- OBJ
def obj(
    shape,
    *,
    mtl: str | None = "materials.mtl",
    statement: str = "o",
    negative: bool = False,
    corners: str = "plain",
    quads_from_pairs: bool = False,
) -> tuple[bytes, dict[str, bytes]]:
    """An OBJ of every placed item (one group each, named by ``statement``) and its MTL
    library. ``corners``: ``plain`` (``f 1 2 3``), ``slashes`` (``1/1/1``) or
    ``normals`` (``1//1``); ``negative`` numbers corners back from the last vertex."""
    scene = as_scene(shape)
    lines = ["# invented OBJ for the SolidSeas tests"]
    if mtl:
        lines.append(f"mtllib {mtl}")
    mats = []
    base = 0
    for k, (name, pts, tris) in enumerate(scene.placed()):
        it = scene.items[k]
        color = scene.meshes[it.mesh].color
        lines.append(f"{statement} {name}")
        for x, y, z in pts:
            lines.append(f"v {x!r} {y!r} {z!r}")
        lines.append("vt 0 0")
        lines.append("vn 0 0 1")
        if color is not None and mtl:
            mname = f"mat{len(mats)}"
            mats.append((mname, color))
            lines.append(f"usemtl {mname}")
        n = len(pts)
        for a, b, c in tris:
            if negative:
                ids = [v - n for v in (a, b, c)]
            else:
                ids = [base + v + 1 for v in (a, b, c)]
            if corners == "slashes":
                lines.append("f " + " ".join(f"{i}/1/1" for i in ids))
            elif corners == "normals":
                lines.append("f " + " ".join(f"{i}//1" for i in ids))
            else:
                lines.append("f " + " ".join(str(i) for i in ids))
        base += n
    text = "\n".join(lines) + "\n"
    siblings = {}
    if mtl:
        mt = []
        for mname, (r, g, b, a) in mats:
            mt += [f"newmtl {mname}", "Ka 0 0 0", f"Kd {r!r} {g!r} {b!r}", f"d {a!r}", "illum 1"]
        siblings[mtl] = ("\n".join(mt) + "\n").encode()
    return text.encode(), siblings


def obj_quads_box(lx: float = 10.0, ly: float = 20.0, lz: float = 30.0) -> bytes:
    """A box of six quads, and an L-shaped (concave) hexagon prism as a second group."""
    v = [(0, 0, 0), (lx, 0, 0), (lx, ly, 0), (0, ly, 0), (0, 0, lz), (lx, 0, lz), (lx, ly, lz), (0, ly, lz)]
    quads = [(1, 4, 3, 2), (5, 6, 7, 8), (1, 2, 6, 5), (2, 3, 7, 6), (3, 4, 8, 7), (4, 1, 5, 8)]
    lines = ["o box"] + [f"v {x} {y} {z}" for x, y, z in v] + [f"f {a} {b} {c} {d}" for a, b, c, d in quads]
    # an L: (0,0) (20,0) (20,10) (10,10) (10,20) (0,20), extruded 5 mm, at x = 100
    ring = [(0, 0), (20, 0), (20, 10), (10, 10), (10, 20), (0, 20)]
    lines.append("o ell")
    for z in (0, 5):
        for x, y in ring:
            lines.append(f"v {100 + x} {y} {z}")
    bot = [9 + i for i in range(6)]
    top = [15 + i for i in range(6)]
    lines.append("f " + " ".join(str(i) for i in reversed(bot)))
    lines.append("f " + " ".join(str(i) for i in top))
    for i in range(6):
        j = (i + 1) % 6
        lines.append(f"f {bot[i]} {bot[j]} {top[j]} {top[i]}")
    return ("\n".join(lines) + "\n").encode()


# --------------------------------------------------------------------------- PLY
def ply(
    shape,
    *,
    encoding: str = "ascii",
    vertex_colors: bool = False,
    face_colors: bool = False,
    normals: bool = False,
    extra_element: bool = False,
    index_type: str = "int",
    comment: str = "invented PLY for the SolidSeas tests",
) -> bytes:
    """A PLY of every placed item's triangles, in one mesh."""
    scene = as_scene(shape)
    verts, faces, vcol, fcol = [], [], [], []
    for k, (_name, pts, tris) in enumerate(scene.placed()):
        color = scene.meshes[scene.items[k].mesh].color or (0.5, 0.5, 0.5, 1.0)
        rgb = tuple(round(c * 255) for c in color[:3])
        base = len(verts)
        verts += pts
        vcol += [rgb] * len(pts)
        for a, b, c in tris:
            faces.append((base + a, base + b, base + c))
            fcol.append(rgb)
    fmt = {"ascii": "ascii", "binary_le": "binary_little_endian", "binary_be": "binary_big_endian"}[encoding]
    head = ["ply", f"format {fmt} 1.0", f"comment {comment}", "obj_info invented"]
    head.append(f"element vertex {len(verts)}")
    head += ["property float x", "property float y", "property float z"]
    if normals:
        head += ["property float nx", "property float ny", "property float nz"]
    if vertex_colors:
        head += ["property uchar red", "property uchar green", "property uchar blue"]
    if extra_element:
        head += ["element material 2", "property uchar ambient_red", "property list uchar float coefficients"]
    head.append(f"element face {len(faces)}")
    head.append(f"property list uchar {index_type} vertex_indices")
    if face_colors:
        head += ["property uchar red", "property uchar green", "property uchar blue"]
    if extra_element:
        head += ["element edge 1", "property int vertex1", "property int vertex2"]
    head.append("end_header")
    text = ("\n".join(head) + "\n").encode()
    if encoding == "ascii":
        rows = []
        for i, (x, y, z) in enumerate(verts):
            row = [repr(float(x)), repr(float(y)), repr(float(z))]
            if normals:
                row += ["0", "0", "1"]
            if vertex_colors:
                row += [str(c) for c in vcol[i]]
            rows.append(" ".join(row))
        if extra_element:
            rows += ["10 2 0.5 0.25", "20 0"]
        for i, f in enumerate(faces):
            row = ["3", *map(str, f)]
            if face_colors:
                row += [str(c) for c in fcol[i]]
            rows.append(" ".join(row))
        if extra_element:
            rows.append("0 1")
        return text + ("\n".join(rows) + "\n").encode()
    e = "<" if encoding == "binary_le" else ">"
    code = {"int": "i", "uint": "I", "ushort": "H"}[index_type]
    body = bytearray()
    for i, (x, y, z) in enumerate(verts):
        body += struct.pack(e + "3f", x, y, z)
        if normals:
            body += struct.pack(e + "3f", 0.0, 0.0, 1.0)
        if vertex_colors:
            body += struct.pack(e + "3B", *vcol[i])
    if extra_element:
        body += struct.pack(e + "BB2f", 10, 2, 0.5, 0.25) + struct.pack(e + "BB", 20, 0)
    for i, f in enumerate(faces):
        body += struct.pack(e + "B3" + code, 3, *f)
        if face_colors:
            body += struct.pack(e + "3B", *fcol[i])
    if extra_element:
        body += struct.pack(e + "2i", 0, 1)
    return text + bytes(body)


# --------------------------------------------------------------------------- OFF
def off(
    shape, *, keyword: str = "OFF", face_colors: bool = False, counts_on_keyword_line: bool = False
) -> bytes:
    scene = as_scene(shape)
    verts, faces, cols = [], [], []
    for k, (_name, pts, tris) in enumerate(scene.placed()):
        color = scene.meshes[scene.items[k].mesh].color or (0.5, 0.5, 0.5, 1.0)
        base = len(verts)
        verts += pts
        for a, b, c in tris:
            faces.append((base + a, base + b, base + c))
            cols.append(color)
    lines = ["# invented OFF for the SolidSeas tests"]
    counts = f"{len(verts)} {len(faces)} 0"
    lines += [f"{keyword} {counts}"] if counts_on_keyword_line else [keyword, counts]
    for x, y, z in verts:
        row = f"{x!r} {y!r} {z!r}"
        if "N" in keyword:
            row += " 0 0 1"
        if "C" in keyword:
            row += " 0.5 0.5 0.5 1.0"
        lines.append(row)
    for f, c in zip(faces, cols, strict=True):
        row = "3 " + " ".join(map(str, f))
        if face_colors:
            row += " " + " ".join(str(round(v * 255)) for v in c[:3])
        lines.append(row)
    return ("\n".join(lines) + "\n").encode()


# --------------------------------------------------------------------------- glTF
def gltf(
    shape,
    *,
    binary: bool = False,
    buffer: str = "data",
    yup: bool = True,
    extras: dict | None = None,
    hierarchy: bool = False,
    extensions_required: tuple[str, ...] = (),
    short_indices: bool = False,
    strided: bool = False,
) -> tuple[bytes, dict[str, bytes]]:
    """A glTF (or GLB) of ``shape``: one mesh a :class:`Mesh` with one primitive, one node
    an item. ``buffer`` is ``data`` (a base64 data URI), ``file`` (``scene.bin``
    beside it) or ``glb`` (the GLB chunk). ``yup`` writes the coordinates Y up, as glTF
    wants (the reader turns them back), in metres. ``hierarchy`` puts every item's
    node under one parent node."""
    scene = as_scene(shape)
    blob = bytearray()
    views, accessors, meshes, materials = [], [], [], []

    def add(data: bytes, target: int, stride: int | None = None) -> int:
        while len(blob) % 4:
            blob.append(0)
        view = {"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), "target": target}
        if stride:
            view["byteStride"] = stride
        blob.extend(data)
        views.append(view)
        return len(views) - 1

    def turn(p):  # millimetres, Z up -> metres, Y up
        x, y, z = (c / 1000.0 for c in p)
        return (x, z, -y) if yup else (x, y, z)

    for m in scene.meshes:
        pts = [turn(p) for p in m.vertices]
        if strided:
            data = b"".join(struct.pack("<3f", *p) + b"\0" * 4 for p in pts)
            pv = add(data, 34962, 16)
        else:
            pv = add(b"".join(struct.pack("<3f", *p) for p in pts), 34962)
        lo = [min(p[i] for p in pts) for i in range(3)]
        hi = [max(p[i] for p in pts) for i in range(3)]
        accessors.append(
            {"bufferView": pv, "componentType": 5126, "count": len(pts), "type": "VEC3", "min": lo, "max": hi}
        )
        pos = len(accessors) - 1
        flat = [i for t in m.triangles for i in t]
        if short_indices:
            iv = add(struct.pack(f"<{len(flat)}H", *flat), 34963)
            accessors.append({"bufferView": iv, "componentType": 5123, "count": len(flat), "type": "SCALAR"})
        else:
            iv = add(struct.pack(f"<{len(flat)}I", *flat), 34963)
            accessors.append({"bufferView": iv, "componentType": 5125, "count": len(flat), "type": "SCALAR"})
        prim = {"attributes": {"POSITION": pos}, "indices": len(accessors) - 1, "mode": 4}
        if m.color is not None:
            materials.append({"pbrMetallicRoughness": {"baseColorFactor": list(m.color)}})
            prim["material"] = len(materials) - 1
        meshes.append({"name": m.name, "primitives": [prim]})
    nodes = []
    for it in scene.items:
        r, t = it.rotation, it.translation_mm
        # the item's placement in Z-up millimetres, written in glTF's Y-up metres
        if yup:
            c = ((1, 0, 0), (0, 0, 1), (0, -1, 0))  # Z up to Y up
            ci = ((1, 0, 0), (0, 0, -1), (0, 1, 0))
            rr = [
                [
                    sum(c[i][k] * sum(r[k][m2] * ci[m2][j] for m2 in range(3)) for k in range(3))
                    for j in range(3)
                ]
                for i in range(3)
            ]
            tt = turn(t)
        else:
            rr, tt = [list(row) for row in r], tuple(v / 1000.0 for v in t)
        matrix = [rr[i][j] for j in range(3) for i in range(3)]
        matrix = matrix[0:3] + [0.0] + matrix[3:6] + [0.0] + matrix[6:9] + [0.0] + [*tt, 1.0]
        node = {"mesh": it.mesh, "name": it.name or scene.meshes[it.mesh].name}
        if r != IDENTITY or any(t):
            node["matrix"] = matrix
        nodes.append(node)
    roots = list(range(len(nodes)))
    if hierarchy:
        nodes.append({"name": "group", "children": roots, "translation": [0.0, 0.0, 0.0]})
        roots = [len(nodes) - 1]
    doc = {
        "asset": {"version": "2.0", "generator": "Invented Writer 1.2.3", "copyright": "none"},
        "scene": 0,
        "scenes": [{"name": "scene", "nodes": roots}],
        "nodes": nodes,
        "meshes": meshes,
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(blob)}],
    }
    if materials:
        doc["materials"] = materials
    if extras:
        doc["asset"]["extras"] = extras
    if extensions_required:
        doc["extensionsRequired"] = list(extensions_required)
        doc["extensionsUsed"] = list(extensions_required)
    siblings = {}
    if buffer == "data":
        doc["buffers"][0]["uri"] = "data:application/octet-stream;base64," + base64.b64encode(blob).decode()
    elif buffer == "file":
        doc["buffers"][0]["uri"] = "scene.bin"
        siblings["scene.bin"] = bytes(blob)
    if binary or buffer == "glb":
        return glb(json.dumps(doc).encode(), bytes(blob) if buffer == "glb" else None), siblings
    return json.dumps(doc).encode(), siblings


def glb(json_bytes: bytes, bin_bytes: bytes | None) -> bytes:
    j = json_bytes + b" " * (-len(json_bytes) % 4)
    chunks = struct.pack("<II", len(j), 0x4E4F534A) + j
    if bin_bytes is not None:
        b = bin_bytes + b"\0" * (-len(bin_bytes) % 4)
        chunks += struct.pack("<II", len(b), 0x004E4942) + b
    return struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks


# --------------------------------------------------------------------------- AMF
def amf(
    shape,
    *,
    unit: str | None = "millimeter",
    zipped: bool = False,
    constellation: bool = True,
    materials: bool = True,
    curved: bool = False,
    metadata: dict | None = None,
) -> bytes:
    """An AMF of ``shape``: an object a :class:`Mesh` (its colour on a material, or on the
    object), and with ``constellation`` one constellation placing every item."""
    scene = as_scene(shape)
    out = ['<?xml version="1.0" encoding="UTF-8"?>']
    out.append(f'<amf unit="{unit}" version="1.1">' if unit else '<amf version="1.1">')
    for k, v in (metadata or {"name": "invented", "cad": "Invented Writer 4.5"}).items():
        out.append(f'<metadata type="{k}">{v}</metadata>')
    for i, m in enumerate(scene.meshes):
        out.append(f'<object id="{i}"><metadata type="name">{m.name}</metadata>')
        if m.color is not None and not materials:
            r, g, b, a = m.color
            out.append(f"<color><r>{r}</r><g>{g}</g><b>{b}</b><a>{a}</a></color>")
        out.append("<mesh><vertices>")
        for x, y, z in m.vertices:
            normal = "<normal><nx>0</nx><ny>0</ny><nz>1</nz></normal>" if curved else ""
            out.append(
                f"<vertex><coordinates><x>{x!r}</x><y>{y!r}</y><z>{z!r}</z></coordinates>{normal}</vertex>"
            )
        out.append("</vertices>")
        mat = f' materialid="{100 + i}"' if materials and m.color is not None else ""
        out.append(f"<volume{mat}>")
        for a, b, c in m.triangles:
            out.append(f"<triangle><v1>{a}</v1><v2>{b}</v2><v3>{c}</v3></triangle>")
        out.append("</volume></mesh></object>")
    if materials:
        for i, m in enumerate(scene.meshes):
            if m.color is not None:
                r, g, b, a = m.color
                out.append(
                    f'<material id="{100 + i}"><color><r>{r}</r><g>{g}</g><b>{b}</b><a>{a}</a></color>'
                    "</material>"
                )
    if constellation:
        import math

        out.append('<constellation id="500">')
        for it in scene.items:
            r = it.rotation
            # Rz Ry Rx angles of a rotation (only the quarter turns the shapes use)
            ry = math.degrees(math.asin(max(-1.0, min(1.0, -r[2][0]))))
            rx = math.degrees(math.atan2(r[2][1], r[2][2]))
            rz = math.degrees(math.atan2(r[1][0], r[0][0]))
            dx, dy, dz = it.translation_mm
            out.append(
                f'<instance objectid="{it.mesh}">'
                f"<deltax>{dx}</deltax><deltay>{dy}</deltay><deltaz>{dz}</deltaz>"
                f"<rx>{rx}</rx><ry>{ry}</ry><rz>{rz}</rz></instance>"
            )
        out.append("</constellation>")
    out.append("</amf>")
    data = "\n".join(out).encode()
    if zipped:
        return _zip({"model.amf": data})
    return data


# --------------------------------------------------------------------------- shared checks
def scene_volume(doc) -> float:
    """The volume of every placed item of a document's scene, in cubic metres."""
    s = doc.scene()
    return sum(s.objects[it.object].measures()["volume_m3"] for it in s.items)


def codes(warnings) -> set[str]:
    return {w.code for w in warnings}


def same_on_three_surfaces(folder, names, fmt: str, capsys) -> None:
    """Python, the command line and the REST service (with ``fmt`` enabled) give the same
    ``model_summary`` for each file, and it validates against its schema."""
    from jsonschema_subset import validate
    from serve_support import Running
    from solidseas import cli, model
    from solidseas.formats import open_model

    running = Running({"m": folder}, workers=1, formats=("solidworks", fmt))
    try:
        for name in names:
            with open_model(folder / name) as doc:
                python = doc.summary(include=model.MODEL_SUMMARY_PARTS)
            code = cli.main(["info", str(folder / name), "--json"])
            out, err = capsys.readouterr()
            assert code == 0 and err == "", name
            cli_env = json.loads(out)
            rest_env = running.get("document", root="m", path=name).json()
            assert cli_env["data"] == python == rest_env["data"], name
            assert validate(cli_env, model.envelope_schema("model_summary"), strict=True) == []
    finally:
        running.close()
