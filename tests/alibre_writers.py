"""Synthetic Alibre Design files for the tests, written by code (no real file is used).

Each file is a compound file built with :func:`builders.build_cfb` (root CLSID all
zero, every stream at the root) holding the streams ``docs/formats/alibre.md``
describes: ``VERSION``, ``PROP_DATA`` (with an 8 by 8 bitmap thumbnail drawn
here), ``STEP_DATA`` (a minimal design database), ``LIGHT_CONFIGURATION_DATA``,
and for a part ``SAB_DATA`` (from :mod:`sab_writers`) and ``MESH_DATA``; an
assembly adds ``CONSTITUENTS`` and its inclusions. GUIDs, names, paths, authors
and times are invented by the test.
"""

import math
import struct
from dataclasses import dataclass, field

import sab_writers as W
from builders import build_cfb

ZERO_CLSID = "{00000000-0000-0000-0000-000000000000}"
CUBE_GUID = "11111111-2222-3333-4444-555555555555"
ASM_GUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SUB_GUID = "99999999-8888-7777-6666-555555555555"


# --------------------------------------------------------------------------- small streams
def ustr(s: str) -> bytes:
    raw = s.encode("utf-8")
    return struct.pack(">H", len(raw)) + raw


def identity_string(guid: str, version: int, path: str) -> str:
    return (
        f'<Repository Guid="{{{guid.upper()}}}" Name="R" V3Name="" Type="Test"/>:{path}|{guid}||1|{version}'
    )


def version_stream(guid: str, version: int = 1, path: str = "/tests/repository/cube") -> bytes:
    return ustr(identity_string(guid, version, path))


def bmp(width: int = 8, height: int = 8) -> bytes:
    """A 24-bit bottom-up bitmap: red left half, blue right half, a green bottom row."""
    stride = ((width * 24 + 31) // 32) * 4
    rows = bytearray()
    for y in range(height):  # bottom-up: the first row stored is the bottom one
        row = bytearray()
        for x in range(width):
            if y == 0:
                row += bytes((0, 255, 0))
            elif x < width // 2:
                row += bytes((0, 0, 255))  # BGR red
            else:
                row += bytes((255, 0, 0))  # BGR blue
        rows += row + b"\0" * (stride - len(row))
    header = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(rows), 2835, 2835, 0, 0)
    return b"BM" + struct.pack("<IHHI", 14 + len(header) + len(rows), 0, 0, 54) + header + bytes(rows)


def entry(key: str, typ: int, values, flags: int = 1) -> bytes:
    out = ustr(key) + struct.pack("<iii", flags, typ, len(values))
    for v in values:
        if typ == 0x14:
            out += ustr(v)
        elif typ == 0x0A:
            out += struct.pack("<i", v)
        elif typ == 0x1E:
            out += struct.pack("<d", v)
        elif typ == 0x28:
            out += struct.pack("<i", len(v)) + v
    return out


def prop_data(*, name: str = "Test cube", snapshot: bytes | None = None, extra: bytes = b"") -> bytes:
    out = entry("TotalSize", 0x14, ["12345"], 0)
    out += entry("number", 0x14, ["TC-1"])
    out += entry("Hatching Angle", 0x1E, [45.0])
    out += ustr("__ConstituentMinorVersions") + struct.pack("<iii", -111, -1, 0)
    out += entry("name", 0x14, [name])
    out += entry("secureObjectType", 0x0A, [2])
    out += entry("Last_Modification_Time", 0x14, ["02 Jan 2026 12:30:00 EST"], 0)
    out += entry("Creation_Time", 0x14, ["01 Jan 2026 09:00:00 UTC"], 0)
    out += entry("Last_Modification_Author", 0x14, ["Test Saver"], 0)
    out += entry("description", 0x14, ["A cube for the tests"])
    out += entry("Creation_Author", 0x14, ["Test Author"], 0)
    out += entry("stepFileVersion", 0x14, ["TestWriter 9,1,22"])
    out += entry("Hatching Scale", 0x1E, [1.0])
    out += entry("Weight", 0x0A, [7])
    if snapshot is not None:
        out += entry("snapshot", 0x28, [snapshot])
    out += entry("subType", 0x0A, [1])
    return out + extra


def light(configuration: str = "Config<0>", rgba=(200, 100, 50, 255)) -> bytes:
    return (
        b"\0\0\0\0"
        + ustr(configuration)
        + b"\0\0\0\0\x01"
        + bytes(rgba)
        + bytes((55, 55, 55, 255))
        + b"\0" * 12
    )


def p21(records: list[str], schema: str = "('ALIBRE_SCHEMA','CONFIG_CONTROL_DESIGN')") -> bytes:
    head = (
        "ISO-10303-21;\r\nHEADER;\r\n/* written by the tests */\r\n"
        "FILE_DESCRIPTION(('test'),'2;1');\r\n"
        "FILE_NAME('test','2026-01-01T00:00:00',(''),(''),'tests','tests','');\r\n"
        f"FILE_SCHEMA ({schema});\r\nENDSEC;\r\nDATA;\r\n"
    )
    return (head + "\r\n".join(records) + "\r\nENDSEC;\r\nEND-ISO-10303-21;\r\n").encode("latin-1")


def part_design() -> bytes:
    return p21(
        [
            "#1=SCHEMAVERSION('TestWriter 9,1,22','test schema');",
            "#2=DESIGNPART($,(),(),$,$,$,$,(),0,$,1,1,1,1,(),(),(),$,$,$,$,0,0,0,.F.,(),$,3);",
        ]
    )


# --------------------------------------------------------------------------- MESH_DATA
@dataclass
class MeshFace:
    id: int
    records: list  # (x, y, z, nx, ny, nz, u, v)
    triangles: list  # (a, b, c)


@dataclass
class DisplayMesh:
    faces: list[MeshFace]
    edges: list[tuple[int, list]] = field(default_factory=list)  # (id, polyline points)
    units: str = "cm"
    color: tuple = (200, 100, 50, 255)
    extent: tuple = (0, 0, 0, 1, 1, 1)
    vertices: int = 0


def _dict(entries: list[tuple[str, bytes, int]]) -> bytes:
    out = struct.pack("<i", len(entries))
    for key, payload, count in entries:
        raw = key.encode("latin-1")
        out += struct.pack("<i", len(raw)) + raw + struct.pack("<i", count) + payload
    return out


def mesh_data(m: DisplayMesh) -> bytes:
    ints = _dict(
        [
            ("SCHEMA_VERSION_KEY", struct.pack("<i", 3), 1),
            ("color", bytes(m.color), 1),
            ("configId", struct.pack("<i", 0), 1),
            ("edgeColor", bytes((55, 55, 55, 255)), 1),
            ("reflectivity", struct.pack("<i", 50), 1),
            ("stateID", struct.pack("<i", 1), 1),
        ]
    )
    dbls = _dict([("density", struct.pack("<d", 1.0), 1), ("extent", struct.pack("<6d", *m.extent), 6)])
    name, units = b"Test cube", m.units.encode()
    strs = _dict(
        [
            ("name", struct.pack("<i", len(name)) + name, 1),
            ("units", struct.pack("<i", len(units)) + units, 1),
        ]
    )
    out = ints + dbls + strs + struct.pack("<3i", len(m.faces), len(m.edges), m.vertices)
    for f in m.faces:
        idx = []
        for t in f.triangles:
            idx += [3, *t]
        idx.append(0)
        out += struct.pack("<4iBf", f.id, len(idx), len(f.records), 0, 0, -1.0)
        out += b"".join(struct.pack("<8f", *r) for r in f.records)
        out += struct.pack(f"<{len(idx)}i", *idx)
    for eid, pts in m.edges:
        n = len(pts)
        recs = [(*p, 0, 0, 0, 0, 0) for p in pts] + [(0.0,) * 8] * (2 * n)
        idx = [n, *range(n), 0]
        out += struct.pack("<4iBf", eid, len(idx), len(recs), 0, 0, -1.0)
        out += b"".join(struct.pack("<8f", *r) for r in recs)
        out += struct.pack(f"<{len(idx)}i", *idx)
    return out


def cube_mesh(size: float = 1.0, units: str = "cm") -> DisplayMesh:
    """The display mesh of :func:`sab_writers.cube`: six faces of two triangles each,
    ids 1 to 6, and its twelve edges after them."""
    faces = []
    for n, (keys, normal) in enumerate(W.BOX_FACES, 1):
        recs = [(*(size * c for c in k), *normal, 0.0, 0.0) for k in keys]
        faces.append(MeshFace(n, recs, [(0, 1, 2), (0, 2, 3)]))
    seen = []
    for keys, _n in W.BOX_FACES:
        for k in range(4):
            a, z = keys[k], keys[(k + 1) % 4]
            pair = (a, z) if a < z else (z, a)
            if pair not in seen:
                seen.append(pair)
    edges = [
        (7 + k, [tuple(size * c for c in a), tuple(size * c for c in z)]) for k, (a, z) in enumerate(seen)
    ]
    return DisplayMesh(faces, edges, units, extent=(0, 0, 0, size, size, size), vertices=8)


def cylinder_mesh(r: float = 1.0, h: float = 2.0, n: int = 24, units: str = "cm") -> DisplayMesh:
    """A display mesh of :func:`sab_writers.cylinder`: the side and the two caps."""
    side, caps = [], [[], []]
    for k in range(n + 1):
        t = 2 * math.pi * k / n
        c, s = math.cos(t), math.sin(t)
        side += [(r * c, r * s, 0.0, c, s, 0.0, t, 0.0), (r * c, r * s, h, c, s, 0.0, t, h)]
    tris = []
    for k in range(n):
        a, b, c2, d2 = 2 * k, 2 * k + 1, 2 * k + 2, 2 * k + 3
        tris += [(a, c2, d2), (a, d2, b)]
    bottom = [(0.0, 0.0, 0.0, 0, 0, -1, 0, 0)] + [
        (r * math.cos(2 * math.pi * k / n), r * math.sin(2 * math.pi * k / n), 0.0, 0, 0, -1, 0, 0)
        for k in range(n)
    ]
    top = [(0.0, 0.0, h, 0, 0, 1, 0, 0)] + [
        (r * math.cos(2 * math.pi * k / n), r * math.sin(2 * math.pi * k / n), h, 0, 0, 1, 0, 0)
        for k in range(n)
    ]
    btris = [(0, 1 + (k + 1) % n, 1 + k) for k in range(n)]
    ttris = [(0, 1 + k, 1 + (k + 1) % n) for k in range(n)]
    caps = [MeshFace(2, bottom, btris), MeshFace(3, top, ttris)]
    return DisplayMesh([MeshFace(1, side, tris), *caps], [], units, extent=(-r, -r, 0, r, r, h), vertices=2)


# --------------------------------------------------------------------------- whole files
def part(
    *,
    guid: str = CUBE_GUID,
    version: int = 1,
    solid=None,
    mesh: DisplayMesh | None = None,
    mm_per_unit: float = 10.0,
    sab_version: int = 2100,
    snapshot: bytes | None = None,
    configuration: str = "Config<0>",
    path: str = "/tests/repository/cube",
    streams: dict | None = None,
    drop: tuple[str, ...] = (),
    with_sab: bool = True,
    with_mesh: bool = True,
) -> bytes:
    """An Alibre Design part (the unit cube in centimetres unless told otherwise)."""
    solid = solid if solid is not None else W.cube(1.0)
    mesh = mesh if mesh is not None else cube_mesh(1.0)
    out = {
        "VERSION": version_stream(guid, version, path),
        "PROP_DATA": prop_data(snapshot=bmp() if snapshot is None else (snapshot or None)),
        "STEP_DATA": part_design(),
        "LIGHT_CONFIGURATION_DATA": light(configuration),
        "AUTOGRAPH_DATA": struct.pack("<i", 0),
        "CUSTOM_ITEM_PROP_DATA": struct.pack("<iii", 1, 0, 0),
    }
    if with_sab:
        out["SAB_DATA"] = solid.sab(persistent_ids=True, mm_per_unit=mm_per_unit, version=sab_version)
        out["IMPORT_DATA"] = b"not read"  # never read: an imported body before features
    if with_mesh:
        out["MESH_DATA"] = mesh_data(mesh)
    out.update(streams or {})
    for name in drop:
        out.pop(name, None)
    return build_cfb(out, ZERO_CLSID)


@dataclass
class Placed:
    """One inclusion: the document it places, where, and how it is stored."""

    guid: str
    version: int = 1
    stored_path: str = "C:/Repository/Parts/cube"
    origin: tuple = (0.0, 0.0, 0.0)
    axis1: tuple | None = (1.0, 0.0, 0.0)
    axis2: tuple | None = (0.0, 1.0, 0.0)
    axis3: tuple | None = (0.0, 0.0, 1.0)
    scale: float = 1.0
    share_placement_with: int | None = None  # the index of an earlier inclusion whose placement it shares


def assembly_design(placed: list[Placed], *, wrap: bool = True) -> bytes:
    """A design database with ``DESIGNASSEMBLY`` and one ``DESIGNINCLUSION`` per entry."""
    recs = ["#1=SCHEMAVERSION('TestWriter 9,1,22','test schema');"]
    n = 10
    inclusions = []
    placements: list[int] = []

    def new() -> int:
        nonlocal n
        n += 1
        return n

    for k, p in enumerate(placed):
        if p.share_placement_with is not None:
            cto = placements[p.share_placement_with]
        else:
            ids = []
            for v in (p.axis1, p.axis2):
                if v is None:
                    ids.append("$")
                else:
                    did = new()
                    recs.append(f"#{did}=DIRECTION($,({v[0]:.17g},{v[1]:.17g},{v[2]:.17g}));")
                    ids.append(f"#{did}")
            pid = new()
            recs.append(
                f"#{pid}=CARTESIAN_POINT($,({p.origin[0]:.17g},{p.origin[1]:.17g},{p.origin[2]:.17g}));"
            )
            if p.axis3 is None:
                a3 = "$"
            else:
                did = new()
                recs.append(f"#{did}=DIRECTION($,({p.axis3[0]:.17g},{p.axis3[1]:.17g},{p.axis3[2]:.17g}));")
                a3 = f"#{did}"
            cto = new()
            recs.append(
                f"#{cto}=CARTESIAN_TRANSFORMATION_OPERATOR_3D($,$,$,{ids[0]},{ids[1]},#{pid},{p.scale:.17g},{a3});"
            )
        placements.append(cto)
        rv = new()
        path = p.stored_path
        if wrap and len(path) > 8:  # Part 21 lets a long string run across lines
            path = path[:8] + "\r\n" + path[8:]
        recs.append(f"#{rv}=REPOSITORYVERSIONREFERENCE({p.version},'C','{path}','{p.guid}','','',1,1,$);")
        member = new()
        recs.append(f"#{member}=DESIGNMEMBER($,$,0,.F.,0,'00000000-0000-0000-0000-00000000000{k}',$,$,0);")
        inc = new()
        recs.append(
            f"#{inc}=DESIGNINCLUSION((),(#{member}),'{p.stored_path}',#{rv},$,#{cto},$,.F.,$,"
            f"'00000000-0000-0000-0000-0000000001{k:02d}',.F.,$,0,$,'Config\\X\\3C0\\X\\3E');"
        )
        inclusions.append(f"#{inc}")
    recs.append(
        f"#2=DESIGNASSEMBLY($,(),(),$,$,$,$,(),0,$,1,1,1,1,(),(),(),$,$,({','.join(inclusions)}),(),(),(),(),$,3);"
    )
    return p21(recs)


def constituents(placed: list[Placed]) -> bytes:
    out = b""
    seen = []
    for p in placed:
        if p.guid in seen:
            continue
        seen.append(p.guid)
        text = (
            identity_string(p.guid, p.version, p.stored_path.split(":", 1)[-1]) + ":C/Repository/x:/more|text"
        )
        out += ustr(text)
    return out


def assembly(
    placed: list[Placed], *, guid: str = ASM_GUID, streams: dict | None = None, design: bytes | None = None
) -> bytes:
    out = {
        "VERSION": version_stream(guid, 1, "/tests/repository/assembly"),
        "PROP_DATA": prop_data(name="Test assembly", snapshot=bmp()),
        "STEP_DATA": design if design is not None else assembly_design(placed),
        "LIGHT_CONFIGURATION_DATA": light("Config<0>", (0, 0, 0, 0)),
        "CONSTITUENTS": constituents(placed),
    }
    out.update(streams or {})
    return build_cfb(out, ZERO_CLSID)


QUARTER_Z = ((0.0, 1.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0))  # axis1, axis2, axis3 of 90 degrees about z
