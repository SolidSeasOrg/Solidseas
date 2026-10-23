"""The clean-room generator (``solidseas.nativewrite.generate``) against its specification.

Implementation-side tests: they use only IR documents built here and SolidSeas'
own SolidCraft sample, never a SOLIDWORKS-made file. The listing language is
checked on small listings written here, line kind by line kind and directive
by directive (README 15.0.3, 15.0.4); the container rule against the MSVC
``rand()`` sequence as docs/FORMAT.md 2.7 states it; ``plan`` against 15.6.
"""

import dataclasses
import importlib.util
import math
import struct
import zlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from solidseas.nativewrite import container, ir, solidcraft
from solidseas.nativewrite import generate as gen
from solidseas.nativewrite.generate import listing
from solidseas.nativewrite.generate.listing import ListingError, parse_text, run

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests" / "fixtures" / "solidcraft" / "rect-extrude-40x30x10.solidcraft"
IDENT = gen.Identity(
    when=datetime(2026, 3, 7, 9, 5, 1, tzinfo=UTC),
    key_index=7,
    anim_guid="{0F1E2D3C-4B5A-4978-8695-A4B3C2D1E0F9}",
    exch_front="11111111-2222-4333-8444-555555555555",
    exch_top="21111111-2222-4333-8444-555555555555",
    exch_right="31111111-2222-4333-8444-555555555555",
    exch_doc="41111111-2222-4333-8444-555555555555",
    exch_config="51111111-2222-4333-8444-555555555555",
)


def assemble_text(text: str, slots=None, *, files=None, xml=False, archive=None):
    return run(parse_text(text, files=files).ops, slots or {}, archive=archive, xml=xml)


def bytes_of(text: str, slots=None, **kw) -> bytes:
    return assemble_text(text, slots, **kw).data


# ------------------------------------------------------------------ line kinds (15.0.3)
def test_integer_and_float_lines():
    assert bytes_of("u8 7 0x1F\nu16 258\nu32 1\nu64 2") == bytes([7, 31, 2, 1]) + (1).to_bytes(
        4, "little"
    ) + (2).to_bytes(8, "little")
    assert bytes_of("i8 -2\ni16 -1\ni32 -1\ni64 -3") == b"\xfe" + b"\xff" * 2 + b"\xff" * 4 + (-3).to_bytes(
        8, "little", signed=True
    )
    assert bytes_of("u16be 0x0102\nu32be 1\nu64be 1") == b"\x01\x02" + b"\0\0\0\x01" + b"\0" * 7 + b"\x01"
    assert bytes_of("f32 1.5 -1\nf64 0.03\nf64be 2.0") == struct.pack("<ff", 1.5, -1) + struct.pack(
        "<d", 0.03
    ) + struct.pack(">d", 2.0)
    assert bytes_of("f64 -0.0") == struct.pack("<d", -0.0)
    nan = 0x7FF8000000000001
    assert bytes_of(f"f64bits {nan}") == nan.to_bytes(8, "little")
    with pytest.raises(ListingError):
        bytes_of("u8 256")
    with pytest.raises(ListingError):
        bytes_of("u32 -1")


def test_hex_rep_text_and_bytes_lines():
    assert bytes_of("hex 02 FA 8c\nrep 3 AB") == b"\x02\xfa\x8c\xab\xab\xab"
    assert bytes_of('utf8 "a\\u00e9"\nutf16 "ab"\nlatin1 "\\u00e9"') == "aé".encode() + b"a\0b\0" + b"\xe9"
    assert bytes_of("bytes $blob", {"blob": b"\x01\x02"}) == b"\x01\x02"
    # A comment starts at # outside a quoted string only.
    assert bytes_of('utf8 "a#b"   # a comment') == b"a#b"


@pytest.mark.parametrize("n", [0, 1, 254, 255, 65534, 65535, 70000])
def test_cstring_lengths(n):
    text = "x" * n
    data = bytes_of("cstr $t", {"t": text})
    assert data[:3] == b"\xff\xfe\xff"
    if n <= 254:
        head = bytes([n])
    elif n <= 65534:
        head = b"\xff" + n.to_bytes(2, "little")
    else:
        head = b"\xff\xff\xff" + n.to_bytes(4, "little")
    assert data[3:] == head + text.encode("utf-16-le")
    narrow = bytes_of("astr $t", {"t": text})
    assert narrow == head + text.encode("latin-1")


def test_cstring_counts_utf16_units():
    data = bytes_of('cstr "\\ud83d\\ude00"')  # one character outside the BMP: two units
    assert data[3] == 2 and len(data) == 8


# ------------------------------------------------------------------ values and expressions
def test_slots_fields_items_and_expressions():
    slots = {"doc.name": "Part1", "model.max": [0.1, 0.2, 0.3], "planes.front": {"hu": 0.5}, "n": [1, 2, 3]}
    assert bytes_of("f64 $model.max.2 $planes.front.hu", slots) == struct.pack("<dd", 0.3, 0.5)
    assert bytes_of("u32 =17+2*len($n)", slots) == (23).to_bytes(4, "little")
    assert bytes_of("u32 =0x10//3 =7%4 =int(2.0)+max(1,4)", slots) == b"".join(
        x.to_bytes(4, "little") for x in (5, 3, 6)
    )
    assert bytes_of("f64 =-$model.max.0", slots) == struct.pack("<d", -0.1)
    assert bytes_of("u8 =len($n)>2 =not(1==1) =1<2 =1 =round(2.6)", slots) == b"\x01\x00\x01\x01\x03"
    # A nested dict and a flat one give the same value.
    assert bytes_of("cstr $doc.name", {"doc": {"name": "Part1"}}) == bytes_of("cstr $doc.name", slots)
    with pytest.raises(ListingError):
        bytes_of("u8 $missing")
    with pytest.raises(ListingError):
        parse_text("u8 =__import__('os')")
    with pytest.raises(ListingError):
        bytes_of("u8 =1//0")


# ------------------------------------------------------------------ directives
def test_member_section_and_let():
    p = parse_text("@member A/B\n@section 15.9\n@let x =3*4\nu8 $x\n", section="15.0")
    assert p.member == "A/B"
    assert p.ops[-1][-1] == "15.9 <text>:4"
    assert run(p.ops, {}).data == b"\x0c"


def test_if_else():
    text = "@if $c\nu8 1\n@else\nu8 2\n@endif\n@if =len($l)==0\nu8 3\n@endif"
    assert bytes_of(text, {"c": True, "l": [1]}) == b"\x01"
    assert bytes_of(text, {"c": False, "l": []}) == b"\x02\x03"


def test_for_and_for_reversed():
    text = "@for x in $l\nu8 $x.v =$x_index\n@endfor\n@for x in $l reversed\nu8 $x.v =$x_index\n@endfor"
    items = [{"v": 10}, {"v": 20}, {"v": 30}]
    assert bytes_of(text, {"l": items}) == bytes([10, 0, 20, 1, 30, 2, 30, 0, 20, 1, 10, 2])
    # A list item that is itself a value
    assert bytes_of("@for g in $t\nutf8 $g\n@endfor", {"t": ["a", "b"]}) == b"ab"


def test_bare_loop_items_and_list_index_paths():
    # README 15.0.2: a list of numbers gives $i the item itself, here inside another loop.
    bodies = [{"id": 101, "from": []}, {"id": 102, "from": [101, 7]}]
    text = "@for b in $bodies\nu8 =len($b.from)\n@for i in $b.from\nu32 $i\nu8 $i_index\n@endfor\n@endfor"
    want = b"\x00" + b"\x02" + (101).to_bytes(4, "little") + b"\x00" + (7).to_bytes(4, "little") + b"\x01"
    assert bytes_of(text, {"bodies": bodies}) == want
    # A path may index a list by position, in a slot and in a loop variable alike.
    f = {"ring": [{"face": 4}, {"face": 1}, {"face": 3}, {"face": 0}, {"face": 9}], "corners": [0.5, 1.5]}
    assert bytes_of("u8 $f.ring.4.face $f.ring.0.face", {"f": f}) == b"\x09\x04"
    assert (
        bytes_of("@for f in $fs\nf64 $f.corners.1\nu8 $f.ring.2.face\n@endfor", {"fs": [f]})
        == struct.pack("<d", 1.5) + b"\x03"
    )
    with pytest.raises(ListingError):
        bytes_of("u8 $f.ring.5.face", {"f": f})


def test_use_arguments_that_name_list_items():
    # README 15.0.3: an argument is text put in place of its parameter, so E=f.ring.0 makes
    # $%E.end read $f.ring.0.end, in an @if as in a line.
    text = """@define face E
@if $%E.end
u8 1 $%E.face
@else
u8 0 $%E.face
@endif
@end
@for f in $features
@use face E=f.ring.0
@use face E=f.ring.1
@endfor
"""
    ring = [{"end": False, "face": 4}, {"end": True, "face": 1}]
    assert bytes_of(text, {"features": [{"ring": ring}]}) == b"\x00\x04\x01\x01"
    loop = parse_text(text).ops[0]
    assert loop[0] == "for" and loop[4][0][:2] == ("if", ("$", "f.ring.0.end"))


def test_a_nested_loop_traces_its_items_to_the_slot():
    # The tracker sees $i of "@for i in $b.from" as a value of the slot bodies.from.
    ops = parse_text("@for b in $bodies\nu32 $b.id\n@for i in $b.from\nu32 $i\n@endfor\n@endfor").ops
    seen: list[str] = []

    def tracker(path):
        seen.append(path)
        return path == "bodies.from"

    r = run(ops, {"bodies": [{"id": 102, "from": [101]}]}, tracker=tracker)
    # The two lists, then the id, and the item of the inner loop under its slot's name.
    assert seen == ["bodies", "bodies.id", "bodies.from", "bodies.from"]
    assert r.mask == bytes(4) + b"\x01" * 4


def test_sized_blocks_in_a_row():
    text = "@sized u32 first\nu16 1 2\n@endsized\n@sized u16 second\nu8 9\n@endsized\nu8 $first $second"
    assert bytes_of(text) == (4).to_bytes(4, "little") + b"\x01\0\x02\0" + b"\x01\0\x09" + b"\x04\x01"
    # Nested: the outer length counts the inner length field and block.
    nested = "@sized u8 a\nu8 1\n@sized u8 b\nu8 2 3\n@endsized\n@endsized"
    assert bytes_of(nested) == bytes([4, 1, 2, 2, 3])


def test_define_and_use_with_quoted_values():
    text = """@define item NAME ID X
cstr %NAME
u16 %ID
u8 =%X+1
@end
@use item NAME="Front Plane" ID=2 X=$k
@use item NAME=$n ID==0x8+8 X=6
"""
    out = bytes_of(text, {"k": 4, "n": "Top"})
    assert out == (listing.cstring("Front Plane") + b"\x02\0\x05" + listing.cstring("Top") + b"\x10\0\x07")
    # A quoted value keeps its quotes, so JSON escapes inside it are read by the line.
    esc = '@define t P\ncstr %P\n@end\n@use t P="a\\\\b # not a comment"'
    assert bytes_of(esc) == listing.cstring("a\\b # not a comment")
    # Nested macros take the outer parameter's text.
    inner = "@define in A\nu8 %A\n@end\n@define out B\n@use in A==%B+1\n@end\n@use out B=4"
    assert bytes_of(inner) == b"\x05"
    with pytest.raises(ListingError):
        parse_text("@define m A\nu8 %A\n@end\n@use m B=1")


def test_include():
    files = {"part.srl": "@section 15.7\n@define two\nu8 2\n@end\nu8 1"}
    p = parse_text("@include part.srl\n@use two\nu8 3", files=files, section="15.0")
    assert run(p.ops, {}).data == b"\x01\x02\x03"
    # The included file's section is cited for its lines; the includer's resumes after it.
    assert p.ops[0][-1] == "15.7 part.srl:5"
    assert p.ops[2][-1] == "15.0 <text>:3"


def test_text_options():
    slots = {"name": 'a<b&"c">', "n": 4}
    body = "line ${name}\nn=${=$n*2}"
    lf = bytes_of(f"@text utf8\n{body}\n@endtext", slots)
    assert lf == b'line a<b&"c">\nn=8\n'
    crlf = bytes_of(f"@text utf8 eol=crlf final=no\n{body}\n@endtext", slots, xml=True)
    assert crlf == b"line a&lt;b&amp;&quot;c&quot;&gt;\r\nn=8"
    bom = bytes_of("@text utf16 bom=yes final=no\nhi\n@endtext")
    assert bom == b"\xff\xfeh\0i\0"
    assert bytes_of("@text utf8 bom=yes final=no\nx\n@endtext") == b"\xef\xbb\xbfx"
    assert bytes_of("@text latin1 eol=crlf\n\\u00e9 # kept\n@endtext") == b"\\u00e9 # kept\r\n"
    with pytest.raises(ListingError):
        parse_text("@text latin1 bom=yes\nx\n@endtext")


def test_zlb():
    data = bytes_of("@zlb level=1\nrep 100 41\nu8 1\n@endzlb")
    assert data[:16] == bytes.fromhex("231DD571DA8148A2A85898B21B89EF99")
    size, packed = struct.unpack_from("<II", data, 16)
    assert size == 101
    chunk = data[24 : 24 + packed]
    assert chunk[:2] == b"\x78\x01"
    assert zlib.decompress(chunk) == b"A" * 100 + b"\x01"
    assert data[24 + packed :] == bytes(8)


# ------------------------------------------------------------------ MFC objects (15.0.4)
def test_class_records_and_references():
    text = """@archive start 1
class moA_c 1 as first
class moB_c 0
class moA_c 1 as second
objref first
objref second
@archive set here
u32 $_archive.here
"""
    data = bytes_of(text)
    head_a = b"\xff\xff\x01\x00\x05\x00moA_c"
    head_b = b"\xff\xff\x00\x00\x05\x00moB_c"
    # moA_c is index 1 and its object 2; moB_c 3 and its object 4; the second moA_c object 5.
    assert data == head_a + head_b + (0x8001).to_bytes(2, "little") + b"\x02\0\x05\0" + (6).to_bytes(
        4, "little"
    )


def test_archive_start_continue_and_labels_from_slots():
    first = assemble_text("@archive start 2\nclass moX_c 1 as $f.name", {"f": {"name": "Sketch1"}})
    assert first.archive.next_index == 4 and first.archive.labels == {"Sketch1": 3}
    second = assemble_text("@archive continue\nclass moX_c 1\nobjref Sketch1", archive=first.archive)
    assert second.data == (0x8002).to_bytes(2, "little") + b"\x03\0"
    with pytest.raises(ListingError):
        assemble_text("@archive continue")
    with pytest.raises(ListingError):
        bytes_of("objref nothing")


# ------------------------------------------------------------------ the container (15.1.1)
def _msvc_rand_low_bytes(count: int) -> list[int]:
    state, out = 1, []
    for _ in range(count):
        state = (state * 214013 + 2531011) % 2**32
        out.append(((state >> 16) & 0x7FFF) & 0xFF)
    return out


@pytest.mark.parametrize("k", [1, 2, 7, 500, 990, 999])
def test_key_and_signatures_follow_rand(k):
    r = _msvc_rand_low_bytes(16 * k + 16)
    key, (lfh, cd, eocd) = gen.container_key(k)
    assert key == bytes(r[16 * k : 16 * k + 4])
    assert lfh == bytes([r[16 * k + 7], r[16 * k + 6], r[16 * k + 5], r[16 * k + 4]])
    assert cd == bytes(r[16 * k + 8 : 16 * k + 12][::-1])
    assert eocd == bytes(r[16 * k + 12 : 16 * k + 16][::-1])
    with pytest.raises(ValueError):
        gen.container_key(0)


def test_internal_attributes_rule():
    assert gen.internal_attr(b"") == 0
    assert gen.internal_attr(b"<?xml?>\r\n") == 1
    assert gen.internal_attr(b"\x86<a/>") == 1
    assert gen.internal_attr(b"a\x00b") == 0
    assert gen.internal_attr(b"\x07\x08\x0b") == 0


# ------------------------------------------------------------------ designs
def rect_sketch(sid, name, x0, y0, x1, y1, *, plane=None, extra=None, tie_origin=True):
    pts = [
        ir.Point(f"{sid}a", x0, y0),
        ir.Point(f"{sid}b", x1, y0),
        ir.Point(f"{sid}c", x1, y1),
        ir.Point(f"{sid}d", x0, y1),
    ]
    lines = [ir.Curve(f"{sid}l{i}", "line", [pts[i].id, pts[(i + 1) % 4].id]) for i in range(4)]
    cons = [
        ir.Constraint(f"{sid}h0", "horizontal", curves=[lines[0].id]),
        ir.Constraint(f"{sid}v1", "vertical", curves=[lines[1].id]),
    ]
    if tie_origin and x0 == 0.0 and y0 == 0.0:
        cons.append(ir.Constraint(f"{sid}o", "coincident", points=["origin", pts[0].id]))
    sk = ir.Sketch(sid, name, plane or ir.Plane.named("xy"), pts, lines, cons)
    if extra:
        extra(sk)
    return sk


def box(n, x0, y0, x1, y1, depth, **kw):
    sk = rect_sketch(f"s{n}", f"MySketch{n}", x0, y0, x1, y1)
    ext_kw = {k: v for k, v in kw.items() if k in ("operation", "direction", "end", "profile", "suppressed")}
    return [sk, ir.Extrude(f"e{n}", f"MyExtrude{n}", sk.id, depth, **ext_kw)]


def example_two_boxes():
    """Section 15.6.8's example design."""
    return ir.Document("example", box(1, 0.0, 0.0, 0.01, 0.02, 0.03) + box(2, 0.03, 0.0, 0.04, 0.02, 0.01))


def test_the_example_of_15_6_8():
    p = gen.plan(example_two_boxes(), identity=IDENT)
    s = p.slots
    f = s["features"]
    assert [(x["name"], x["id"]) for x in f] == [
        ("Sketch1", 26),
        ("Boss-Extrude1", 32),
        ("Sketch2", 33),
        ("Boss-Extrude2", 40),
    ]
    assert f[0]["at_origin"] and not f[2]["at_origin"]
    e1, e2 = f[1], f[3]
    assert (e1["sketch_id"], e1["depth_text"], e1["first"], e1["merge"], e1["body_label"]) == (
        26,
        "30",
        True,
        True,
        "body1",
    )
    assert (e2["sketch_id"], e2["depth_text"], e2["first"], e2["merge"], e2["body_id"]) == (
        33,
        "10",
        False,
        False,
        102,
    )
    assert e1["centre"] == [0.005, 0.01, 0.015] and e1["diagonal"] == math.sqrt(
        0.01 * 0.01 + 0.02 * 0.02 + 0.03 * 0.03
    )
    assert [(b["id"], b["name"], b["label"], b["feature"], b["regen"]) for b in s["bodies"]] == [
        (101, "Boss-Extrude1", "body1", 32, 1151),
        (102, "Boss-Extrude2", "body2", 40, 1153),
    ]
    assert s["model.min"] == [0.0, 0.0, 0.0] and s["model.max"] == [0.04, 0.02, 0.03]
    assert s["model.origin_refs"] == 1 and s["hdr.next_id"] == 41
    assert (s["doc.stamp"], s["doc.stamp2"], s["fixed.id_base"]) == (140, 111, 125)
    assert [x["id"] for x in s["meta.kw_extrusions"]] == [32, 40]
    assert [x["id"] for x in s["meta.kw_sketches"]] == [26, 33, 5]
    assert p.names == {
        "s1": "Sketch1",
        "MySketch1": "Sketch1",
        "e1": "Boss-Extrude1",
        "MyExtrude1": "Boss-Extrude1",
        "s2": "Sketch2",
        "MySketch2": "Sketch2",
        "e2": "Boss-Extrude2",
        "MyExtrude2": "Boss-Extrude2",
    }
    assert p.left_out == []


def test_identity_and_derived_slots():
    s = gen.plan(ir.Document("empty"), identity=IDENT).slots
    unix = int(IDENT.when.timestamp())
    assert s["doc.unix"] == s["doc.created"] == s["tpl.unix"] == unix
    assert s["doc.filetime"] == (unix + 11644473600) * 10**7
    assert s["doc.iso"] == s["meta.created_iso"] == "2026-03-07T09:05:01Z"
    assert s["meta.short_date"] == "3/7/2026"
    assert s["meta.long_date"] == "Saturday, March 7, 2026"
    assert s["meta.created_text"] == "Saturday, March 7, 2026 9:05:01 AM"
    assert s["exch.time"] == {"year": 2026, "month": 3, "day": 7, "hour": 9, "minute": 5, "second": 1}
    h = 5381
    for b in IDENT.exch_doc.encode():
        h = (h * 33 + b) % 2**32
    assert s["exch.hash.doc"] == h
    assert (s["doc.stamp"], s["doc.stamp2"], s["hdr.next_id"], s["model.solid"]) == (102, 101, 26, False)
    assert s["planes.front"]["hu"] == 0.08899 and s["planes.top"]["hv"] == 0.05500000000000001
    assert s["meta.file_stem"] == "empty" and s["doc.name"] == "Part1" and s["doc.author"] == "SolidSeas"
    made = gen.Identity.new()
    assert made.when.microsecond == 0 and 1 <= made.key_index <= 999
    assert (
        len(made.anim_guid) == 38 and made.anim_guid == made.anim_guid.upper() and made.anim_guid[15] == "4"
    )
    assert len(made.exch_doc) == 36 and made.exch_doc == made.exch_doc.lower()


def test_three_bodies_merge_spheres():
    doc = ir.Document(
        "three",
        box(1, 0.0, 0.0, 0.01, 0.01, 0.01)
        + box(2, 0.02, 0.0, 0.03, 0.01, 0.01)
        + box(3, 0.0, 0.02, 0.01, 0.03, 0.02),
    )
    s = gen.plan(doc, identity=IDENT).slots
    assert (s["doc.stamp"], s["doc.stamp2"], s["fixed.id_base"]) == (160, 119, 143)
    c, r = s["model.sphere"][:3], s["model.sphere"][3]
    for b in s["bodies"]:
        f = next(x for x in s["features"] if x["id"] == b["feature"])
        for corner in (
            (f["corners"][0], f["corners"][1], 0.0),
            (f["corners"][2], f["corners"][3], f["depth"]),
        ):
            assert math.dist(c, corner) <= r * (1 + 1e-12)


# ------------------------------------------------------------------ refusals and left_out (15.6.2, 15.6.7)
FOUR = "a fillet right after the box is written only on all four of its edges along its depth"


def _refusal(features) -> list[str]:
    with pytest.raises(gen.NativeWriteUnsupported) as e:
        gen.plan(ir.Document("d", features), identity=IDENT)
    assert isinstance(e.value, ValueError)
    return e.value.items


def test_refused_sketches():
    off = ir.Plane((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, -1.0), "xz")
    sk = rect_sketch("s", "S", 0.0, 0.0, 0.01, 0.01, plane=off)
    assert (
        _refusal([sk, ir.Extrude("e", "E", "s", 0.01)])[0]
        == "S: sketch on a plane other than the Front Plane"
    )
    sk = rect_sketch("s", "S", 0.0, 0.0, 0.01, 0.01)
    sk.suppressed = True
    assert _refusal([sk, ir.Extrude("e", "E", "s", 0.01)])[0] == "S: suppressed sketch"
    tri = ir.Sketch(
        "s",
        "S",
        ir.Plane.named("xy"),
        [ir.Point("a", 0, 0), ir.Point("b", 1, 0), ir.Point("c", 0, 1)],
        [
            ir.Curve("1", "line", ["a", "b"]),
            ir.Curve("2", "line", ["b", "c"]),
            ir.Curve("3", "line", ["c", "a"]),
        ],
    )
    assert _refusal([tri, ir.Extrude("e", "E", "s", 0.01)])[0] == "S: sketch is not a single corner rectangle"
    sk = rect_sketch("s", "S", 0.0, 0.0, 0.01, 0.01)
    sk.curves[0].construction = True
    assert _refusal([sk, ir.Extrude("e", "E", "s", 0.01)])[0] == "S: sketch is not a single corner rectangle"
    tilted = rect_sketch("s", "S", 0.0, 0.0, 0.01, 0.01)
    tilted.points[1].y = 0.001
    assert (
        _refusal([tilted, ir.Extrude("e", "E", "s", 0.01)])[0]
        == "S: rectangle is not aligned with the sketch axes"
    )
    alone = rect_sketch("s", "S", 0.0, 0.0, 0.01, 0.01)
    items = _refusal([alone])
    assert items == ["S: sketch not followed by its extrusion"]


def test_refused_extrusions_and_other_features():
    assert _refusal(box(1, 0, 0, 0.01, 0.01, 0.01, direction="reverse"))[0] == (
        "MyExtrude1: only blind extrusions towards the sketch normal are written"
    )
    assert _refusal(box(1, 0, 0, 0.01, 0.01, 0.01, end="through_all"))[0].endswith(
        "towards the sketch normal are written"
    )
    assert _refusal(box(1, 0, 0, 0.01, 0.01, 0.01, profile=[["s1l0", "s1l1", "s1l2"]]))[0] == (
        "MyExtrude1: profile is not the whole rectangle"
    )
    assert (
        _refusal(box(1, 0, 0, 0.01, 0.01, 0.01, operation="cut"))[0]
        == "MyExtrude1: the first extrusion cannot cut"
    )
    later = box(1, 0, 0, 0.01, 0.01, 0.01) + box(2, 0.02, 0, 0.03, 0.01, 0.01, operation="join")
    assert _refusal(later)[0].startswith(
        "MyExtrude2: a later extrusion that joins or cuts is not written yet"
    )
    assert _refusal(box(1, 0, 0, 0.01, 0.01, 0.01, suppressed=True))[0] == "MyExtrude1: suppressed extrusion"
    fillet = ir.Fillet("f", "Round", [ir.EdgeRef((0.0, 0.0, 0.0))], 0.001)
    odd = ir.Unsupported("u", "Loft1", "loft", "lofts are not in the IR")
    items = _refusal(box(1, 0, 0, 0.01, 0.01, 0.01) + [fillet, odd])
    # A point at the box's corner on the sketch plane is a vertex, not a point of an edge (15.6.2).
    assert items == [f"Round: {FOUR}", "Loft1: lofts are not in the IR"]


def test_allow_partial_leaves_out_refused_items_and_their_dependents():
    sk = rect_sketch("s", "Tilted", 0.0, 0.0, 0.01, 0.01)
    sk.points[1].y = 0.001
    features = [sk, ir.Extrude("e", "Pushed", "s", 0.01)] + box(2, 0.02, 0, 0.03, 0.01, 0.01)
    features.append(ir.Fillet("f", "Round", [ir.EdgeRef((0.0, 0.0, 0.0))], 0.001))
    with pytest.raises(gen.NativeWriteUnsupported) as e:
        gen.plan(ir.Document("d", features), identity=IDENT)
    assert e.value.items == [
        "Tilted: rectangle is not aligned with the sketch axes",
        f"Round: {FOUR}",
    ]
    p = gen.plan(ir.Document("d", features), identity=IDENT, allow_partial=True)
    assert p.left_out == [
        "Tilted: rectangle is not aligned with the sketch axes",
        "Pushed: left out because its sketch is not written",
        f"Round: {FOUR}",
    ]
    # The written pair is the first of the part: Sketch1 and Boss-Extrude1, off the origin. The
    # gap after a sketch follows its place, not the origin (15.5.4): the first sketch leaves 6.
    assert [f["name"] for f in p.slots["features"]] == ["Sketch1", "Boss-Extrude1"]
    assert p.slots["features"][1]["id"] == 32 and p.names["MyExtrude2"] == "Boss-Extrude1"


def test_left_out_entries_of_15_6_7():
    def extra(sk):
        sk.points.append(ir.Point("loose", 0.5, 0.5))
        sk.constraints.append(ir.Constraint("par", "parallel", curves=["sl0", "sl2"]))
        sk.dimensions.append(ir.Dimension("dw", "length", 0.04, curves=["sl0"], parameter="w"))
        sk.dimensions.append(ir.Dimension("dh", "length", 0.03, curves=["sl1"], parameter="h"))
        sk.dimensions.append(ir.Dimension("dx", "length", 0.03, curves=["sl3"]))

    sk = rect_sketch("s", "Base", 0.0, 0.0, 0.04, 0.03, extra=extra)
    params = [ir.Parameter("w", 0.04, expression="width"), ir.Parameter("h", 0.03, expression="30 mm")]

    def plan_with(depth_expression):
        ext = ir.Extrude("e", "Pad", "s", 0.01, operation="join", depth_parameter="d")
        doc = ir.Document("d", [sk, ext], [*params, ir.Parameter("d", 0.01, expression=depth_expression)])
        return gen.plan(doc, identity=IDENT).left_out

    kept = "is kept as geometry only; the rectangle has no driving dimensions in the part"
    head = [
        f"Base: dimension w (length, 40 mm) {kept}; its expression width is not kept",
        f"Base: dimension h (length, 30 mm) {kept}",
        f"Base: dimension dx (length, 30 mm) {kept}",
        "Base: relation parallel on sl0, sl2 is not written; "
        "the rectangle keeps its horizontal, vertical and corner relations",
        "Base: point loose is not written",
    ]
    join = "Pad: written as a new body (there is nothing to join)"
    assert plan_with("10 mm") == [*head, join]  # a plain number: nothing is lost
    assert plan_with("depth / 2") == [
        *head,
        "Pad: depth 10 mm is written as a number; the expression depth / 2 is not kept",
        join,
    ]


@pytest.mark.parametrize(
    "expression, plain",
    [
        ("10", True),
        ("-2.5", True),
        ("40 mm", True),
        ("90deg", True),
        ("90\u00b0", True),
        ("2 in", True),
        ("+3m", True),
        ("1 cm", True),
        ("width", False),
        ("10 mm + 2", False),
        ("1.2.3", False),
        ("mm", False),
        ("10 mmm", False),
    ],
)
def test_plain_numbers_of_15_6_7(expression, plain):
    from solidseas.nativewrite.generate.slots import _kept_expression

    assert _kept_expression(expression) is not plain


def test_a_corner_other_than_the_minimum_on_the_origin_is_reported():
    sk = rect_sketch("s", "Neg", -0.02, -0.01, 0.0, 0.0)
    sk.constraints.append(ir.Constraint("o", "coincident", points=["origin", "sc"]))
    p = gen.plan(ir.Document("d", [sk, ir.Extrude("e", "E", "s", 0.01)]), identity=IDENT)
    assert p.left_out == ["Neg: the corner on the origin is not tied to it"]
    assert p.slots["features"][0]["at_origin"] is False and p.slots["model.origin_refs"] == 0


def test_invalid_ir_passes_through():
    doc = ir.Document("d", [ir.Extrude("e", "E", "nowhere", 0.01)])
    with pytest.raises(ir.IRError):
        gen.plan(doc)


# ------------------------------------------------------------------ the written part
@pytest.fixture(scope="module")
def sample():
    return solidcraft.read_ir(SAMPLE)


def test_the_sample_is_refused_for_its_fillet_unless_partial(sample):
    with pytest.raises(gen.NativeWriteUnsupported) as e:
        gen.write_part(sample, identity=IDENT)
    # The sample's fillet is not one of o11's (15.6.2): the fillet table refuses it.
    assert e.value.items == [f"Fillet1: {FOUR}"]
    p = gen.plan(sample, identity=IDENT, allow_partial=True)
    assert p.left_out[-1] == f"Fillet1: {FOUR}"
    assert p.slots["meta.file_stem"] == "rect-extrude-40x30x10"


def test_a_written_part_reads_back_with_35_members_in_order(sample):
    blob = gen.write_part(sample, identity=IDENT, allow_partial=True)
    key, (lfh, _cd, _eocd) = gen.container_key(IDENT.key_index)
    assert blob[:8] == key + b"\x00\x00\x00\x04" and blob[8:12] == lfh
    doc = container.read_document(blob)
    names = [m.name for m in doc.members]
    assert names == list(gen.MEMBERS) and len(names) == 35
    assert names == sorted(names, key=lambda n: n.encode())
    members = gen.assemble(gen.plan(sample, identity=IDENT, allow_partial=True).slots)
    for m in doc.members:
        assert m.data == members[m.name]
        assert (m.dos_time, m.dos_date) == ((0xB6C4 if m.name == "Header2" else 0xB719), 0x1A6D)
    text = {m.name for m in doc.members if m.internal_attr == 1}
    assert text == {n for n in names if gen.is_xml(n)} and len(text) == 10
    assert doc.data("Header2") == doc.data("Contents/Config-0-ModelHeader")
    assert (
        doc.data("ThirdPty/CM_MOTION_LOAD_1") == b""
        and len(doc.data("Contents/3DExperienceExchange2")) == 12288
    )


def test_writing_is_deterministic_for_one_identity(sample):
    a = gen.write_part(sample, identity=IDENT, allow_partial=True)
    assert a == gen.write_part(sample, identity=IDENT, allow_partial=True)
    other = gen.write_part(sample, identity=dataclasses.replace(IDENT, key_index=8), allow_partial=True)
    assert other[:4] != a[:4] and len(other) == len(a)
    assert container.read_document(other).members[5].data == container.read_document(a).members[5].data
    assert gen.write_part(sample, allow_partial=True) != a  # a new identity: new GUIDs at least


def test_member_contents_follow_the_slots():
    p = gen.plan(example_two_boxes(), identity=IDENT)
    m = gen.assemble(p.slots)
    s = p.slots
    assert m["ModelStamps"] == struct.pack("<III", s["doc.created"], 140, 111)
    assert m["_DL_VERSION_17000/DLUpdateStamp"] == struct.pack("<IH", 140, 0)
    keywords = m["swXmlContents/KeyWords"]
    assert keywords[0] == 0x86
    text = keywords[1:].decode()
    assert '<Extrusion id="32" Name="Boss-Extrude1" Type="Boss-Extrude">' in text
    assert 'DissectableChildren="33"' in text and text.endswith("</Keywords>\r\n")
    assert text.index('<Sketch id="26"') < text.index('<Sketch id="33"') < text.index('<Sketch id="5"')
    feats = m["swXmlContents/Features"].decode()
    assert 'swPath="example.sldprt"' in feats and 'swLastModifiedStamp="140"' in feats
    # The feature stream's header is the archive's next index after Config-0.
    head = int.from_bytes(m["Contents/Config-0-ResolvedFeatures"][:4], "little")
    assert head > 100 and m["Contents/Config-0-ResolvedFeatures"][4:6] == (21).to_bytes(2, "little")
    # Config-0's two size fields cover the member exactly.
    c0 = m["Contents/Config-0"]
    settings = int.from_bytes(c0[14:18], "little")
    tail = int.from_bytes(c0[18 + settings : 22 + settings], "little")
    assert 22 + settings + tail == len(c0)


def test_assemble_takes_a_nested_slot_dict():
    flat = gen.plan(example_two_boxes(), identity=IDENT).slots
    nested: dict = {}
    for key, value in flat.items():
        *path, last = key.split(".")
        here = nested
        for p in path:
            here = here.setdefault(p, {})
        here[last] = value
    assert gen.assemble(nested) == gen.assemble(flat)


def test_spec_constants_are_long_runs_of_the_listings():
    consts = gen.SPEC_CONSTANTS
    assert consts and all(isinstance(c, bytes) and len(c) >= 32 for c in consts)
    members = gen.assemble(gen.plan(ir.Document("empty"), identity=IDENT).slots)
    rels = members["_rels/.rels"]
    assert rels in consts  # a member with no slot is one constant run
    # No run holds an identity value: the time of IDENT is in no constant.
    t = int(IDENT.when.timestamp()).to_bytes(4, "little")
    assert not any(t in c for c in consts)
    # Values 15.6.6 fixes are in runs: the author and company "SolidSeas".
    core = members["docProps/core.xml"]
    author = core.index(b"SolidSeas")
    assert any(core[author - 20 : author + 20] in c for c in consts)
    app = members["docProps/app.xml"]
    company = app.index(b"<Company>SolidSeas")
    assert any(app[company : company + 32] in c for c in consts)


def test_spec_constants_compare_variants_of_one_shape():
    for (doc_a, id_a), (doc_b, id_b) in gen._shapes():
        assert doc_a.name == doc_b.name and id_a.when != id_b.when
        ma = gen.assemble(gen.plan(doc_a, identity=id_a).slots)
        mb = gen.assemble(gen.plan(doc_b, identity=id_b).slots)
        assert {n: len(v) for n, v in ma.items()} == {n: len(v) for n, v in mb.items()}
    assert gen._agreeing_runs(b"a" * 40 + b"x" + b"b" * 31, b"a" * 40 + b"y" + b"b" * 31) == [b"a" * 40]


def test_generation_reads_no_file(sample):
    import sys

    gen.write_part(sample, identity=IDENT, allow_partial=True)
    opened: list[str] = []

    def hook(event, args):
        if event == "open":
            opened.append(str(args[0]))

    sys.addaudithook(hook)
    before = len(opened)
    gen.write_part(sample, allow_partial=True)
    assert opened[before:] == []


# ------------------------------------------------------------------ the compiled listings
def test_the_compiled_listings_are_up_to_date():
    script = ROOT / "scripts" / "compile-sldprt-spec.py"
    spec = importlib.util.spec_from_file_location("compile_sldprt_spec", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    compiled = ROOT / "src" / "solidseas" / "nativewrite" / "generate" / "_listings.py"
    assert compiled.read_text(encoding="utf-8") == mod.render(ROOT), "run scripts/compile-sldprt-spec.py"
    assert [m for m, _s, _f in mod.member_table(ROOT)] == list(gen.MEMBERS)


# ------------------------------------------------------------------ file custom properties (15.6.9)
def example_properties():
    """Section 15.6.9's example design: one box with five file custom properties."""
    props = [
        ir.Property("PartNo", "BR-100 & <A>"),
        ir.Property("Qty", 12, "number"),
        ir.Property("Mass", 0.25, "number"),
        ir.Property("Due", "2025-01-07", "date"),
        ir.Property("Released", False, "yesno"),
    ]
    return ir.Document("props", box(1, 0.0, 0.0, 0.01, 0.02, 0.03), properties=props)


def test_the_example_of_15_6_9():
    s = gen.plan(example_properties(), identity=IDENT).slots
    assert s["props"] == [
        {
            "name": "PartNo",
            "pid": 3,
            "code": 0,
            "type_id": 30,
            "vt": "lpstr",
            "text": "BR-100 & <A>",
            "xml_text": "BR-100 &amp; &lt;A&gt;",
            "xml_value": "BR-100 &amp; &lt;A&gt;",
        },
        {
            "name": "Qty",
            "pid": 4,
            "code": 2,
            "type_id": 3,
            "vt": "i4",
            "text": "12",
            "xml_text": "12",
            "xml_value": "12",
        },
        {
            "name": "Mass",
            "pid": 5,
            "code": 2,
            "type_id": 3,
            "vt": "r8",
            "text": "0.25",
            "xml_text": "0.25",
            "xml_value": "0.250000",
        },
        {
            "name": "Due",
            "pid": 6,
            "code": 1,
            "type_id": 64,
            "vt": "filetime",
            "text": "1/7/2025",
            "xml_text": "1/7/2025",
            "xml_value": "2025-01-07T12:00:00Z",
        },
        {
            "name": "Released",
            "pid": 7,
            "code": 3,
            "type_id": 11,
            "vt": "bool",
            "text": "No",
            "xml_text": "No",
            "xml_value": "No",
        },
    ]
    assert [p["name"] for p in s["props_by_name"]] == ["Due", "Mass", "PartNo", "Qty", "Released"]
    assert all(any(p is q for q in s["props"]) for p in s["props_by_name"])


def test_no_properties_gives_empty_lists_and_the_constant_members():
    for doc in (ir.Document("empty"), example_two_boxes()):
        s = gen.plan(doc, identity=IDENT).slots
        assert s["props"] == [] and s["props_by_name"] == []
    m = gen.assemble(gen.plan(ir.Document("empty"), identity=IDENT).slots)
    xml = m["docProps/custom.xml"].decode()
    assert xml.count("<propertyNameDictionaryElement") == 2 and xml.count("<property ") == 3
    empty_dictionary = '<propertyNameDictionaryElement name="" pid="0"></propertyNameDictionaryElement>'
    assert xml.endswith(empty_dictionary + "</propertySection></Properties>\r\n")

    # 15.2.4 with no properties: the head's i32 is -1, the file container a null object.
    def cls(name):
        return b"\xff\xff\x01\x00" + len(name).to_bytes(2, "little") + name.encode()

    head = cls("moCusPropMgr_c") + struct.pack("<iIII", -1, 1, 1, 0)
    head += cls("moCusPropContainer_c") + cls("moFilePropContainer_c") + b"\0\0" + b"\0\0"
    assert m["Contents/CusProps"] == head + b"\0\0" + bytes(6)
    one = gen.assemble(gen.plan(ir.Document("one", box(1, 0, 0, 0.01, 0.01, 0.01)), identity=IDENT).slots)
    assert one["Contents/CusProps"] == head + cls("moCutListPropContainer_c") + bytes(8) + bytes(6)


def test_properties_change_only_their_two_members_and_not_the_stamps():
    doc = example_properties()
    bare = dataclasses.replace(doc, properties=[])
    with_props, without = gen.plan(doc, identity=IDENT).slots, gen.plan(bare, identity=IDENT).slots
    for stamp in ("doc.stamp", "doc.stamp2"):
        assert with_props[stamp] == without[stamp]
    a, b = gen.assemble(with_props), gen.assemble(without)
    assert {n for n in a if a[n] != b[n]} == {"Contents/CusProps", "docProps/custom.xml"}


def test_exch_time_is_an_identity_slot():
    p = gen.plan(ir.Document("empty"), identity=IDENT)
    s = dict(p.slots)
    assert s["exch.time"] == {"year": 2026, "month": 3, "day": 7, "hour": 9, "minute": 5, "second": 1}
    later = {"year": 2026, "month": 3, "day": 7, "hour": 9, "minute": 5, "second": 2}
    s["exch.time"] = later
    from solidseas.nativewrite.generate.slots import derive

    assert derive(s)["exch.time"] == later  # not derived again from doc.unix


@pytest.mark.parametrize(
    "value, vt, text, stored",
    [
        (42, "i4", "42", "42"),
        (-7, "i4", "-7", "-7"),
        (0, "i4", "0", "0"),
        (2147483647, "i4", "2147483647", "2147483647"),
        (3.25, "r8", "3.25", "3.250000"),
        (7.0, "r8", "7.0", "7.000000"),
        (0.00001, "r8", "0.00001", "0.000010"),
        (1e16, "r8", "10000000000000000.0", "10000000000000000.000000"),
        (-2.5e-7, "r8", "-0.00000025", "-0.000000"),
        (2.675, "r8", "2.675", "2.675000"),
    ],
)
def test_number_forms_of_15_6_9(value, vt, text, stored):
    doc = ir.Document("n", properties=[ir.Property("N", value, "number")])
    (item,) = gen.plan(doc, identity=IDENT).slots["props"]
    assert (item["vt"], item["text"], item["xml_text"], item["xml_value"]) == (vt, text, text, stored)
    assert (item["code"], item["type_id"]) == (2, 3)


def test_text_date_and_yes_or_no_forms_of_15_6_9():
    doc = ir.Document(
        "t",
        properties=[
            ir.Property('Say "hi"', 'a "quote" & <tag>'),
            ir.Property("Start", "1601-01-01", "date"),
            ir.Property("Done", True, "yesno"),
            ir.Property("Empty", ""),
            ir.Property("Nameé", "Жé \U0001f600"),
        ],
    )
    p = gen.plan(doc, identity=IDENT).slots["props"]
    assert (p[0]["text"], p[0]["xml_text"], p[0]["xml_value"]) == (
        'a "quote" & <tag>',
        'a "quote" &amp; &lt;tag&gt;',
        'a "quote" &amp; &lt;tag&gt;',
    )
    assert (p[1]["text"], p[1]["xml_value"]) == ("1/1/1601", "1601-01-01T12:00:00Z")
    assert (p[2]["text"], p[2]["xml_value"], p[2]["vt"]) == ("Yes", "Yes", "bool")
    assert p[3]["text"] == "" and p[4]["text"] == "Жé \U0001f600"
    assert [x["pid"] for x in p] == [3, 4, 5, 6, 7]


def test_props_by_name_ignores_case_then_compares_code_points():
    names = ["beta", "Alpha", "gamma", "_under", "Zeta", "alpha2"]
    doc = ir.Document("o", properties=[ir.Property(n, "x") for n in names])
    s = gen.plan(doc, identity=IDENT).slots
    # "_" (U+005F) comes before every lower-case letter
    assert [p["name"] for p in s["props_by_name"]] == ["_under", "Alpha", "alpha2", "beta", "gamma", "Zeta"]
    assert [p["name"] for p in s["props"]] == names


def _property_refusal(props) -> list[str]:
    with pytest.raises(gen.NativeWriteUnsupported) as e:
        gen.plan(ir.Document("d", properties=props), identity=IDENT)
    return e.value.items


@pytest.mark.parametrize(
    "prop, reason",
    [
        (ir.Property("Line\nbreak", "x"), "control"),
        (ir.Property("Tab", "a\tb"), "control"),
        (ir.Property("Odd", "a\ud800b"), "control"),
        (ir.Property("Non", "￿"), "control"),
        (ir.Property("Non￾", 3, "number"), "control"),
        (ir.Property("Link", "$PRP:Description"), "link"),
        (ir.Property("Link2", "see $prp:x"), "link"),
        (ir.Property("Dim", '"D1@Sketch1"'), "link"),
        (ir.Property("Big", 2147483648, "number"), "range"),
        (ir.Property("Small", -2147483649, "number"), "range"),
        (ir.Property("Old", "1600-12-31", "date"), "date"),
    ],
)
def test_refused_properties(prop, reason):
    expected = {
        "control": "its name (or text) holds a character a part cannot store "
        "(a control character such as a line break)",
        "link": "SOLIDWORKS would read this text as a link to another value",
        "range": f"the whole number {prop.value} is outside the range a part stores",
        "date": "a date before 1601-01-01 cannot be stored",
    }[reason]
    assert _property_refusal([prop]) == [f"property {prop.name}: {expected}"]


def test_accepted_edge_properties():
    props = [
        ir.Property("Quote", 'a "b"'),
        ir.Property("At", "a@b"),
        ir.Property("Dollar", "$PR P and $PRQ"),
        ir.Property("Min", -2147483648, "number"),
        ir.Property("Real", 1e12, "number"),
        ir.Property("First", "1601-01-01", "date"),
    ]
    s = gen.plan(ir.Document("d", properties=props), identity=IDENT).slots
    assert [p["name"] for p in s["props"]] == ["Quote", "At", "Dollar", "Min", "Real", "First"]


def test_refused_properties_with_allow_partial_count_only_the_accepted():
    props = [
        ir.Property("A", "one"),
        ir.Property("Bad", "x\ny"),
        ir.Property("B", 2, "number"),
        ir.Property("Linked", '"SW-Mass@part.SLDPRT"'),
        ir.Property("C", True, "yesno"),
    ]
    tilted = rect_sketch("s", "Tilted", 0.0, 0.0, 0.01, 0.01)
    tilted.points[1].y = 0.001
    doc = ir.Document("d", [tilted, ir.Extrude("e", "E", "s", 0.01)], properties=props)
    bad = (
        "property Bad: its name (or text) holds a character a part cannot store "
        "(a control character such as a line break)"
    )
    linked = "property Linked: SOLIDWORKS would read this text as a link to another value"
    with pytest.raises(gen.NativeWriteUnsupported) as e:
        gen.plan(doc, identity=IDENT)
    assert e.value.items == ["Tilted: rectangle is not aligned with the sketch axes", bad, linked]
    p = gen.plan(doc, identity=IDENT, allow_partial=True)
    assert p.left_out == [
        "Tilted: rectangle is not aligned with the sketch axes",
        "E: left out because its sketch is not written",
        f"{bad}; the part does not carry this property",
        f"{linked}; the part does not carry this property",
    ]
    assert [(x["name"], x["pid"]) for x in p.slots["props"]] == [("A", 3), ("B", 4), ("C", 5)]
    cus = gen.assemble(p.slots)["Contents/CusProps"]
    assert struct.unpack_from("<i", cus, 6 + len("moCusPropMgr_c"))[0] == 2  # the last of three, from 0


def test_more_than_65534_properties():
    props = [ir.Property(f"P{i}", "v") for i in range(65535)]
    props.insert(10, ir.Property("Bad", "a\x00"))
    assert _property_refusal(props) == [
        "property Bad: its name (or text) holds a character a part cannot store "
        "(a control character such as a line break)",
        "more than 65,534 file custom properties",
    ]
    p = gen.plan(ir.Document("d", properties=props), identity=IDENT, allow_partial=True)
    assert len(p.slots["props"]) == 65534 and p.slots["props"][-1]["name"] == "P65533"
    assert p.slots["props"][-1]["pid"] == 3 + 65533
    assert p.left_out[-1] == "more than 65,534 file custom properties"
    # Without the last one, 65,534 are accepted (Bad does not count): no limit refusal.
    ok = gen.plan(ir.Document("d", properties=props[:-1]), identity=IDENT, allow_partial=True)
    assert len(ok.slots["props"]) == 65534 and len(ok.left_out) == 1


def _cus_record(k: int, name: str, text: str, code: int, first: bool) -> bytes:
    """One property record of 15.2.4, its classes written in full or by reference (15.0.4).

    Counting from 1, the head, the two containers, the list and the property list take
    indices 1 to 10 (a class, then its object), so moAdvCusProp_c is class 11 and
    moCusPropStringElem_c class 13.
    """
    if first:
        head = b"\xff\xff\x01\x00\x0e\x00moAdvCusProp_c" + b"\x01\x00"
        head += b"\xff\xff\x01\x00\x15\x00moCusPropStringElem_c"
    else:
        head = (0x8000 | 11).to_bytes(2, "little") + b"\x01\x00" + (0x8000 | 13).to_bytes(2, "little")
    return (
        head
        + listing.cstring(text)
        + struct.pack("<II", k, 9)
        + listing.cstring(name)
        + struct.pack("<I", code)
        + listing.cstring(text) * 2
        + struct.pack("<iII", -1, 1, 0)
    )


def test_a_written_part_carries_its_properties():
    doc = example_properties()
    doc.properties.insert(0, ir.Property('Note "x"', 'say "a" & b'))
    blob = gen.write_part(doc, identity=IDENT)
    part = container.read_document(blob)
    p = gen.plan(doc, identity=IDENT)
    members = gen.assemble(p.slots)
    assert [m.name for m in part.members] == list(gen.MEMBERS)
    for m in part.members:
        assert m.data == members[m.name]

    # docProps/custom.xml (15.1.4): the dictionary by name, then the elements in the design's order.
    import xml.etree.ElementTree as ET

    raw = part.data("docProps/custom.xml")
    assert raw.endswith(b"</propertySection></Properties>\r\n")
    assert raw.count(b"\n") == raw.count(b"\r\n") == 2
    root = ET.fromstring(raw)
    user = root.findall("propertySection")[1]
    assert user.get("name") == "UserDefinedProperties"
    dictionary = [(e.get("name"), e.get("pid")) for e in user.findall("propertyNameDictionaryElement")]
    assert dictionary == [
        ("", "0"),
        ("Due", "7"),
        ("Mass", "6"),
        ('Note "x"', "3"),
        ("PartNo", "4"),
        ("Qty", "5"),
        ("Released", "8"),
    ]
    vt = "{http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes}"
    elements = user.findall("property")[1:]
    got = []
    for e in elements:
        value, fp = e[0], e.find("FPVals")[0]
        attrs = (e.get("name"), e.get("pid"), e.get("TypeID"), e.get("IsEquation"))
        got.append((*attrs, value.tag, value.text, fp.text))
    assert got == [
        ('Note "x"', "3", "30", "False", vt + "lpstr", 'say "a" & b', 'say "a" & b'),
        ("PartNo", "4", "30", "False", vt + "lpstr", "BR-100 & <A>", "BR-100 & <A>"),
        ("Qty", "5", "3", None, vt + "i4", "12", "12"),
        ("Mass", "6", "3", None, vt + "r8", "0.250000", "0.25"),
        ("Due", "7", "64", None, vt + "filetime", "2025-01-07T12:00:00Z", "1/7/2025"),
        ("Released", "8", "11", None, vt + "bool", "No", "No"),
    ]
    text = raw.decode()
    assert 'name="Note &quot;x&quot;"' in text and '<vt:lpstr>say "a" &amp; b</vt:lpstr>' in text
    children = list(user)
    assert children.index(user.findall("propertyNameDictionaryElement")[-1]) < children.index(elements[0])

    # Contents/CusProps (15.2.4): the head, the list, one record per property, then the rest.
    def cls(name):
        return b"\xff\xff\x01\x00" + len(name).to_bytes(2, "little") + name.encode()

    want = cls("moCusPropMgr_c") + struct.pack("<iIII", 5, 1, 1, 0)
    want += cls("moCusPropContainer_c") + cls("moFilePropContainer_c")
    want += cls("suObList") + b"\x01\x00" + cls("moAdvCusPropList_c") + b"\x06\x00"
    records = [
        ('Note "x"', 'say "a" & b', 0),
        ("PartNo", "BR-100 & <A>", 0),
        ("Qty", "12", 2),
        ("Mass", "0.25", 2),
        ("Due", "1/7/2025", 1),
        ("Released", "No", 3),
    ]
    for k, (name, value, code) in enumerate(records):
        want += _cus_record(k, name, value, code, k == 0)
    want += b"\0\0" + cls("moCutListPropContainer_c") + bytes(8) + bytes(6)
    assert part.data("Contents/CusProps") == want


def test_the_property_shape_of_spec_constants():
    (doc_a, id_a), (doc_b, _id_b) = gen._shapes()[-1]
    for doc in (doc_a, doc_b):
        assert [p.type for p in doc.properties] == ["text", "number", "number", "date", "yesno"]
        assert isinstance(doc.properties[1].value, int) and isinstance(doc.properties[2].value, float)
        s = gen.plan(doc, identity=id_a).slots
        assert [p["name"] for p in s["props_by_name"]] == [p["name"] for p in s["props"]]
    for pa, pb in zip(doc_a.properties, doc_b.properties, strict=True):
        assert len(pa.name) == len(pb.name) and pa.name[0] != pb.name[0] and pa.name[0].isascii()
    a = gen.assemble(gen.plan(doc_a, identity=id_a).slots)
    consts = gen.SPEC_CONSTANTS
    # The property elements' fixed text lines up in the two variants and is kept as constant runs.
    xml = a["docProps/custom.xml"]
    tail = xml[xml.rindex(b"</vt:bool>") :]
    assert any(tail in c for c in consts)


# ------------------------------------------------------------------ a box with a hole (15.6.2, 15.5.13)
def circle_sketch(sid, name, cx, cy, r, *, plane=None, extra=None):
    centre = ir.Point(f"{sid}c", cx, cy)
    sk = ir.Sketch(
        sid, name, plane or ir.Plane.named("xy"), [centre], [ir.Curve(f"{sid}k", "circle", [centre.id], r)]
    )
    if extra:
        extra(sk)
    return sk


def hole(n, cx, cy, r, *, sketch=None, **kw):
    sk = sketch or circle_sketch(f"s{n}", f"MyCircle{n}", cx, cy, r)
    cut_kw = {"operation": "cut", "end": "through_all", "direction": "midplane"}
    cut_kw.update(
        {k: v for k, v in kw.items() if k in ("operation", "direction", "end", "profile", "suppressed")}
    )
    return [sk, ir.Extrude(f"e{n}", f"MyCut{n}", sk.id, kw.get("depth", 0.0), **cut_kw)]


def example_hole():
    """Section 15.6.8's second example: the box of o12's first pair with a hole through it."""
    return ir.Document("hole", box(1, 0.0, 0.0, 0.01, 0.02, 0.03) + hole(2, 0.005, 0.01, 0.0025))


def test_the_box_with_a_hole_of_15_6_8():
    p = gen.plan(example_hole(), identity=IDENT)
    s = p.slots
    unix, filetime = s["doc.unix"], s["doc.filetime"]
    sk1, box1, circle, cut = s["features"]
    assert (sk1["name"], sk1["id"], sk1["circle"], sk1["log_modified"], sk1["at_origin"]) == (
        "Sketch1",
        26,
        False,
        True,
        True,
    )
    assert (box1["name"], box1["id"], box1["cut"], box1["log_modified"]) == (
        "Boss-Extrude1",
        32,
        False,
        False,
    )
    assert circle == {
        "name": "Sketch2",
        "sketch": True,
        "circle": True,
        "log_modified": False,
        "id": 33,
        "at_origin": False,
        "centre": [0.005, 0.01],
        "radius": 0.0025,
        "start": [0.005 + 0.0025, 0.01],
        "created": unix,
        "modified": unix,
        "time": filetime,
        "cache_memo": 0.0,
        "regen": 102,
    }
    ring = [(1, 4), (2, 1), (1, 3), (2, 0), (1, 1)]  # (kind, face) of the box's faces (15.6.2)
    assert cut == {
        "name": "Cut-Extrude1",
        "sketch": False,
        "cut": True,
        "fillet": False,
        "log_modified": False,
        "id": 40,
        "sketch_name": "Sketch2",
        "sketch_id": 33,
        "first": False,
        "merge": False,
        "centre": [0.005, 0.01, 0.015],
        "diagonal": math.sqrt(0.01 * 0.01 + 0.02 * 0.02 + 0.03 * 0.03),
        "body_id": 102,
        "body_label": "body2",
        "target_id": 101,
        "target_label": "body1",
        "target_uid": 32,
        "target_created": unix,
        "ring": [{"kind": k, "uid": 32, "created": unix, "face": n} for k, n in ring],
        "created": unix,
        "time": filetime,
        "cache_memo": 0.0,
        "counter_marks": 14,
        "counter_face1": 0,
        "counter_face2": 0,
        "counter_end": 0,
    }
    # The hole's items carry none of a box's own fields (15.6.2).
    assert not {"corners", "depth", "depth_text", "cache_text", "counter_favorite"} & (set(circle) | set(cut))
    fields = ("id", "name", "label", "feature", "last", "changed", "live", "from", "into", "regen", "time")
    assert [tuple(b[k] for k in fields) for b in s["bodies"]] == [
        (101, "Boss-Extrude1", "body1", 32, 32, [], False, [], [102], 1151, filetime),
        (102, "Cut-Extrude1", "body2", 40, 40, [], True, [101], [], 1153, filetime),
    ]
    assert s["live_bodies"] == [s["bodies"][1]] and s["body_links"] == [{"new": 102, "old": 101}]
    assert s["builds"] == [{"feature": 40, "time": filetime}, {"feature": 32, "time": filetime}]
    assert s["model.min"] == [0.0, 0.0, 0.0] and s["model.max"] == [0.01, 0.02, 0.03]
    assert s["model.solid"] and s["model.origin_refs"] == 1 and s["hdr.next_id"] == 41
    assert (s["doc.stamp"], s["doc.stamp2"], s["fixed.id_base"]) == (140, 111, 125)
    # The cut leaves the model box, the sphere and the planes as the box alone has them.
    alone = gen.plan(ir.Document("hole", box(1, 0.0, 0.0, 0.01, 0.02, 0.03)), identity=IDENT).slots
    for key in ("model.centre", "model.sphere", "hdr.centre", "planes.front", "planes.top", "planes.right"):
        assert s[key] == alone[key]
    assert [x["id"] for x in s["meta.kw_extrusions"]] == [32, 40]
    assert [x["id"] for x in s["meta.kw_sketches"]] == [26, 33, 5]
    assert s["sketches"] == [sk1, circle]
    assert p.names == {
        "s1": "Sketch1",
        "MySketch1": "Sketch1",
        "e1": "Boss-Extrude1",
        "MyExtrude1": "Boss-Extrude1",
        "s2": "Sketch2",
        "MyCircle2": "Sketch2",
        "e2": "Cut-Extrude1",
        "MyCut2": "Cut-Extrude1",
    }
    assert p.left_out == []


def test_boxes_carry_the_new_fields_and_their_bodies_are_live():
    s = gen.plan(example_two_boxes(), identity=IDENT).slots
    f = s["features"]
    assert [(x.get("circle"), x.get("cut"), x["log_modified"]) for x in f] == [
        (False, None, True),
        (None, False, False),
        (False, None, True),
        (None, False, False),
    ]
    for b in s["bodies"]:
        assert (b["last"], b["changed"], b["live"], b["from"], b["into"]) == (b["feature"], [], True, [], [])
    assert s["live_bodies"] == s["bodies"] and s["body_links"] == []
    # o12's order: 40 then 32 (remainders 6 and 15 modulo 17).
    assert [b["feature"] for b in s["builds"]] == [40, 32]
    empty = gen.plan(ir.Document("empty"), identity=IDENT).slots
    assert (empty["live_bodies"], empty["body_links"], empty["builds"]) == ([], [], [])


def test_creation_numbers_follow_the_sketch_place():
    # 15.5.4: the first sketch leaves 6, a later one 7, whether or not it starts on the origin.
    doc = ir.Document(
        "d",
        box(1, 0.01, 0.01, 0.02, 0.02, 0.01)
        + box(2, 0.0, 0.0, 0.005, 0.005, 0.01)
        + box(3, 0.03, 0, 0.04, 0.01, 0.01),
    )
    s = gen.plan(doc, identity=IDENT).slots
    assert [x["id"] for x in s["features"]] == [26, 32, 33, 40, 41, 48]
    assert [x["at_origin"] for x in s["sketches"]] == [False, True, False]
    # 15.2.7.5: by node id modulo 17 (32 is 15, 40 is 6, 48 is 14).
    assert [b["feature"] for b in s["builds"]] == [40, 48, 32]


def test_builds_with_the_same_remainder_put_the_later_first():
    from solidseas.nativewrite.generate.slots import body_slots

    bodies = [
        {"id": 101, "feature": 32, "changed": [34], "live": False, "from": [], "time": 1},
        {"id": 102, "feature": 49, "changed": [], "live": True, "from": [101], "time": 2},
    ]
    features = [{"id": 32, "time": 1}, {"id": 34, "time": 5}, {"id": 49, "time": 2}]
    live, links, builds = body_slots(bodies, features)
    assert live == [bodies[1]] and links == [{"new": 102, "old": 101}]
    # 32 and 49 both leave 15; 34 leaves 0. The later of 32 and 49 in the list comes first.
    # A feature that changed a body carries its own time, not the body's (15.6.5).
    assert builds == [{"feature": 34, "time": 5}, {"feature": 49, "time": 2}, {"feature": 32, "time": 1}]


def test_refused_circle_sketches():
    def refuse(sk):
        return _refusal(box(1, 0, 0, 0.02, 0.02, 0.01) + hole(2, 0, 0, 0, sketch=sk))[0]

    off = ir.Plane((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, -1.0), "xz")
    assert refuse(circle_sketch("s2", "C", 0.01, 0.01, 0.002, plane=off)) == (
        "C: sketch on a plane other than the Front Plane"
    )
    sk = circle_sketch("s2", "C", 0.01, 0.01, 0.002)
    sk.suppressed = True
    assert refuse(sk) == "C: suppressed sketch"

    def second_circle(sk):
        sk.curves.append(ir.Curve("k2", "circle", [sk.points[0].id], 0.001))

    several = "C: a sketch with more than one circle is not written yet"
    assert refuse(circle_sketch("s2", "C", 0.01, 0.01, 0.002, extra=second_circle)) == several
    sk = circle_sketch("s2", "C", 0.01, 0.01, 0.002)
    sk.curves[0].construction = True
    assert refuse(sk) == several
    # A circle among lines is no hole's sketch: it is read as a rectangle's.
    mixed = rect_sketch("s2", "C", 0.0, 0.0, 0.01, 0.01)
    mixed.curves.append(ir.Curve("k", "circle", ["s2a"], 0.001))
    assert refuse(mixed) == "C: sketch is not a single corner rectangle"
    alone = box(1, 0, 0, 0.02, 0.02, 0.01) + [circle_sketch("s2", "C", 0.01, 0.01, 0.002)]
    assert _refusal(alone) == ["C: sketch not followed by its extrusion"]


def test_a_degenerate_circle_is_refused():
    # The IR's validation already refuses a radius that is not positive; the rule stands
    # behind it for a circle that comes in another way.
    from solidseas.nativewrite.generate.slots import _circle

    sk = circle_sketch("s", "C", 0.01, 0.01, 0.002)
    sk.curves[0].radius = 0.0
    assert _circle(sk) == (None, "degenerate circle")


def test_refused_cuts():
    one = box(1, 0, 0, 0.02, 0.02, 0.01)
    assert _refusal(
        one + hole(2, 0.01, 0.01, 0.002, operation="new_body", end="blind", depth=0.01, direction="forward")
    ) == ["MyCut2: a circle is written only as the profile of a cut"]
    both = "MyCut2: only a cut through all in both directions is written"
    assert _refusal(one + hole(2, 0.01, 0.01, 0.002, direction="forward")) == [both]
    assert _refusal(one + hole(2, 0.01, 0.01, 0.002, end="blind", depth=0.01)) == [both]
    last = (
        "a cut is written only as the last feature of a part with one box, "
        "or followed only by a fillet on the hole's edge"
    )
    assert _refusal(hole(1, 0.01, 0.01, 0.002)) == [f"MyCut1: {last}"]
    two = one + box(3, 0.03, 0, 0.04, 0.01, 0.01)
    assert _refusal(two + hole(2, 0.01, 0.01, 0.002)) == [f"MyCut2: {last}"]
    after = one + hole(2, 0.01, 0.01, 0.002) + box(3, 0.03, 0, 0.04, 0.01, 0.01)
    assert _refusal(after) == [f"MyCut2: {last}"]
    outside = "MyCut2: the circle is not inside the box's rectangle"
    for cx, cy, r in ((0.019, 0.01, 0.002), (0.01, 0.002, 0.002), (0.03, 0.03, 0.001), (0.01, 0.01, 0.01)):
        assert _refusal(one + hole(2, cx, cy, r)) == [outside]
    assert _refusal(one + hole(2, 0.01, 0.01, 0.002, profile=[["s2k"], ["s2k"]])) == [
        "MyCut2: profile is not the whole circle"
    ]
    assert _refusal(one + hole(2, 0.01, 0.01, 0.002, suppressed=True)) == ["MyCut2: suppressed extrusion"]
    # The whole circle as its profile, and a centre on the origin's corner of the box, are accepted.
    ok = gen.plan(ir.Document("d", one + hole(2, 0.01, 0.01, 0.002, profile=[["s2k"]])), identity=IDENT)
    assert [f["name"] for f in ok.slots["features"]][-1] == "Cut-Extrude1"


def test_a_refused_cut_with_allow_partial_leaves_the_box():
    features = box(1, 0, 0, 0.02, 0.02, 0.01) + hole(2, 0.01, 0.01, 0.002, direction="forward")
    p = gen.plan(ir.Document("d", features), identity=IDENT, allow_partial=True)
    assert p.left_out == [
        "MyCut2: only a cut through all in both directions is written",
        "MyCircle2: left out with MyCut2, which is not written",
    ]
    s = p.slots
    assert [f["name"] for f in s["features"]] == ["Sketch1", "Boss-Extrude1"]
    assert [b["live"] for b in s["bodies"]] == [True] and s["body_links"] == []
    assert (s["doc.stamp"], s["doc.stamp2"]) == (120, 105)


def test_left_out_entries_of_a_circle_sketch():
    def extra(sk):
        sk.points.append(ir.Point("spare", 0.0, 0.0))
        sk.constraints.append(ir.Constraint("fix", "coincident", points=["origin", "spare"]))
        sk.dimensions.append(ir.Dimension("dr", "radius", 0.002, curves=["s2k"], parameter="r"))
        sk.dimensions.append(ir.Dimension("dd", "diameter", 0.004, curves=["s2k"]))

    sk = circle_sketch("s2", "Bore", 0.01, 0.01, 0.002, extra=extra)
    params = [ir.Parameter("r", 0.002, expression="size / 2"), ir.Parameter("d", 0.01, expression="depth")]
    features = box(1, 0, 0, 0.02, 0.02, 0.01) + hole(2, 0, 0, 0, sketch=sk)
    features[-1].depth_parameter = "d"  # a cut through all reads no depth: nothing is reported
    p = gen.plan(ir.Document("d", features, params), identity=IDENT)
    kept = "is kept as geometry only; the circle has no driving dimensions in the part"
    assert p.left_out == [
        f"Bore: dimension r (radius, 2 mm) {kept}; its expression size / 2 is not kept",
        f"Bore: dimension dd (diameter, 4 mm) {kept}",
        "Bore: relation coincident on origin, spare is not written; the circle keeps its centre and radius",
        "Bore: point spare is not written",
    ]


def test_a_box_with_a_hole_writes_and_its_members_have_the_lengths_of_the_spec():
    doc = example_hole()
    blob = gen.write_part(doc, identity=IDENT)
    part = container.read_document(blob)
    s = gen.plan(doc, identity=IDENT).slots
    m = gen.assemble(s)
    assert [x.name for x in part.members] == list(gen.MEMBERS)
    for x in part.members:
        assert x.data == m[x.name]
    one = gen.assemble(
        gen.plan(ir.Document("hole", box(1, 0.0, 0.0, 0.01, 0.02, 0.03)), identity=IDENT).slots
    )
    two = gen.assemble(gen.plan(dataclasses.replace(example_two_boxes(), name="hole"), identity=IDENT).slots)

    # The stamps count the cut as an extrusion (15.6.6).
    assert m["ModelStamps"] == struct.pack("<III", s["doc.created"], 140, 111)
    assert m["_DL_VERSION_17000/DLUpdateStamp"] == struct.pack("<IH", 140, 0)
    # SwDocContentMgrInfo (15.1.6) lists the one body still in the part, named after the cut,
    # one UTF-16 unit shorter than Boss-Extrude1.
    info = m["SwDocContentMgr/SwDocContentMgrInfo"]
    assert len(info) == len(one["SwDocContentMgr/SwDocContentMgrInfo"]) - 2
    assert struct.pack("<II", 1, 102) + listing.cstring("Cut-Extrude1") in info
    assert listing.cstring("Boss-Extrude1") not in info
    # Header2 (15.2.2.2): the circle is logged created only, so one Modified stamp fewer than
    # two boxes (a class reference, u16, u32, u32 and the CString "Modified": 32 bytes), and
    # the last node's name is one unit shorter.
    modified = 2 + 2 + 4 + 4 + len(listing.cstring("Modified"))
    assert len(m["Header2"]) == len(two["Header2"]) - modified - 2
    assert m["Header2"] == m["Contents/Config-0-ModelHeader"]
    # CMgr (15.2.7.4, 15.2.7.5) against one box: a second body in the body list (8), a link in
    # both link lists (8 each), a second linked node (34) with 101 into 102 and 102 from 101,
    # each listed twice at 6 bytes an id (24), a second build (12) and a second id at the end (8).
    assert len(m["Contents/CMgr"]) == len(one["Contents/CMgr"]) + 8 + 8 * 2 + 34 + 24 + 12 + 8
    builds = struct.pack("<I", 2) + b"".join(
        struct.pack("<III", feature, s["doc.filetime"] // 2**32, s["doc.filetime"] % 2**32)
        for feature in (40, 32)
    )
    assert builds in m["Contents/CMgr"]
    # Config-0 (15.4.6) holds two bodies like two boxes, newest first: body 102 live, made and
    # last built by 40, then body 101, used up, by 32.
    c0 = m["Contents/Config-0"]
    assert len(c0) == len(two["Contents/Config-0"])
    assert c0.index(struct.pack("<IIII", 102, 0, 40, 40)) < c0.index(struct.pack("<IIII", 101, 1, 32, 32))
    # KeyWords (15.1.5): the cut's element closes itself, and the circle is listed as a sketch.
    cut_kw = (
        '<Extrusion id="40" Name="Cut-Extrude1" Dissectable="true" '
        'DissectableChildren="33" DissectableRoot="true"/>'
    )
    circle_kw = '<Sketch id="33" Name="Sketch2" Dissectable="true"/>'
    text = m["swXmlContents/KeyWords"][1:].decode()
    assert cut_kw in text and circle_kw in text
    assert len(m["swXmlContents/KeyWords"]) == len(one["swXmlContents/KeyWords"]) + len(cut_kw) + len(
        circle_kw
    )
    # VisualStates (15.2.6.3): a display record per sketch, a circle's like a rectangle's.
    assert len(m["ThirdPtyStore/VisualStates"]) == len(two["ThirdPtyStore/VisualStates"])
    # The feature stream (15.5): 17 + 4 top-level features; the circle's centre and start point
    # (15.5.12); the box twice in the extrusion's records (15.5.8) and twice in the cut's
    # (15.5.13), whose box is the box's own centre and diagonal.
    fs = m["Contents/Config-0-ResolvedFeatures"]
    assert fs[4:6] == (21).to_bytes(2, "little")
    assert struct.pack("<H", 30) + struct.pack("<dd", 0.005, 0.01) in fs
    assert struct.pack("<H", 30) + struct.pack("<dd", 0.005 + 0.0025, 0.01) in fs
    assert fs.count(struct.pack("<I4d", 1, 0.005, 0.01, 0.015, s["features"][1]["diagonal"])) == 4
    for name in ("moICE_c", "sgArcHandle", "moFromSktEnt3IntSurfIdRep_c", "moEndSpec_c", "moFromEndSpec_c"):
        assert name.encode() in fs
    # The members a cut does not touch are those of two boxes, byte for byte or in length.
    for name in ("Contents/CMgrHdr2", "Contents/Config-0-LWDATA", "Contents/Definition", "docProps/core.xml"):
        assert len(m[name]) == len(two[name])


def test_the_hole_shape_of_spec_constants():
    hole_shapes = [pair for pair in gen._shapes() if pair[0][0].name == "hole"]
    assert len(hole_shapes) == 1
    (doc_a, id_a), (doc_b, id_b) = hole_shapes[0]
    for doc, ident in ((doc_a, id_a), (doc_b, id_b)):
        s = gen.plan(doc, identity=ident).slots
        assert [f["name"] for f in s["features"]] == ["Sketch1", "Boss-Extrude1", "Sketch2", "Cut-Extrude1"]
    a, b = gen.plan(doc_a, identity=id_a).slots, gen.plan(doc_b, identity=id_b).slots
    assert a["features"][2]["centre"] != b["features"][2]["centre"]
    assert a["features"][2]["radius"] != b["features"][2]["radius"]
    assert {n: len(v) for n, v in gen.assemble(a).items()} == {n: len(v) for n, v in gen.assemble(b).items()}
    # The cut's end conditions are the same in every part: a constant run (15.5.13).
    fs = gen.assemble(a)["Contents/Config-0-ResolvedFeatures"]
    end = fs[fs.index(b"moEndSpec_c") :]
    assert any(end[:40] in c for c in gen.SPEC_CONSTANTS)


# ------------------------------------------------------------------ fillets (15.6.2, 15.5.14)
O11_CORNERS = ((0.0, 0.0), (0.04, 0.0), (0.04, 0.03), (0.0, 0.03))
POSITION = (
    "a fillet is written only right after the box's extrusion, or right after the hole's cut, "
    "in a part with one box"
)
RIM_EDGE = "a fillet after the hole is written only on the hole's edge on the box's far face"
RIM_CLEAR = (
    "the fillet on the hole's edge must stay on the box's far face, clear of its rounded corners, "
    "with a radius less than the box's depth"
)


def round_edges(fid="f1", name="Round", r=0.003, points=None, **kw):
    """A fillet on the four edges along the depth of o11's 40 x 30 x 10 mm box, by points halfway up."""
    points = points if points is not None else [(x, y, 0.005) for x, y in O11_CORNERS]
    return ir.Fillet(fid, name, [ir.EdgeRef(p) for p in points], r, **kw)


def round_rim(fid="f2", name="Rim", r=0.001, point=(0.025, 0.015, 0.01), **kw):
    """A fillet on the edge of o11's hole on the box's far face, by a point on its +x side."""
    return ir.Fillet(fid, name, [ir.EdgeRef(point)], r, **kw)


def o11_box():
    return box(1, 0.0, 0.0, 0.04, 0.03, 0.01)


def example_o11():
    """Section 15.6.8's third example: o11 as a design."""
    return ir.Document("o11", o11_box() + [round_edges()] + hole(2, 0.02, 0.015, 0.005) + [round_rim()])


def _plan_ok(features) -> list[str]:
    return gen.plan(ir.Document("d", features), identity=IDENT).left_out


def test_o11_as_a_design_of_15_6_8():
    p = gen.plan(example_o11(), identity=IDENT)
    s = p.slots
    unix, filetime = s["doc.unix"], s["doc.filetime"]

    def face(kind, uid, n):
        return {"kind": kind, "uid": uid, "created": unix, "face": n}

    feats = s["features"]
    assert [(f["name"], f["id"]) for f in feats] == [
        ("Sketch1", 26),
        ("Boss-Extrude1", 32),
        ("Fillet1", 34),
        ("Sketch2", 35),
        ("Cut-Extrude1", 42),
        ("Fillet2", 44),
    ]
    assert feats[1]["fillet"] is False and feats[4]["fillet"] is False
    ends = [face(2, 32, 1), face(2, 32, 0)]
    e = [
        {"label": f"Fillet1.e{k + 1}", "counter": 0, "faces": [face(1, 32, a), face(1, 32, b), *ends]}
        for k, (a, b) in enumerate(((4, 3), (3, 2), (2, 1), (1, 4)))
    ]

    def along(k, a, b):
        return {
            "counter": 0,
            "ring": [face(4, 34, k), face(2, 32, 1), face(1, 32, b), face(2, 32, 0), face(1, 32, a)],
            "edge": e[k - 1]["faces"],
        }

    assert feats[2] == {
        "name": "Fillet1",
        "sketch": False,
        "cut": False,
        "fillet": True,
        "hole": False,
        "log_modified": False,
        "id": 34,
        "radius": 0.003,
        "radius_text": "3",
        "anchor": [0.003, 0.003, 0.01],
        "body_id": 101,
        "body_label": "body1",
        "body_regen": 1151,
        "edges": e,
        "faces": [along(1, 4, 3), along(4, 1, 4), along(2, 3, 2), along(3, 2, 1)],
        "closing": [e[2], e[3], e[0], e[1]],
        "dim_edge": "Fillet1.e4",
        "created": unix,
        "time": filetime,
        "cache_memo": 0.0,
        "counter_marks": 22,
    }
    rounded_ring = [face(1, 32, 4), face(2, 32, 1), face(4, 34, 1), face(2, 32, 0), face(4, 34, 4)]
    assert feats[4]["ring"] == rounded_ring
    rim = [face(3, 42, 1), face(2, 32, 1), face(2, 32, 1), face(2, 32, 1)]
    e2 = {"label": "Fillet2.e1", "counter": 0, "faces": rim}
    kind0 = {"kind": 0, "uid": 0, "created": 0, "face": 0}
    rim_face = {"counter": 0, "ring": [face(4, 44, 1), face(2, 32, 1), kind0, face(3, 42, 1)], "edge": rim}
    assert feats[5] == {
        "name": "Fillet2",
        "sketch": False,
        "cut": False,
        "fillet": True,
        "hole": True,
        "log_modified": False,
        "id": 44,
        "radius": 0.001,
        "radius_text": "1",
        "anchor": [0.02 - 0.005 - 0.001, 0.015, 0.01 - 0.001],
        "body_id": 102,
        "body_label": "body2",
        "body_regen": 1153,
        "edges": [e2],
        "faces": [rim_face],
        "closing": [e2],
        "dim_edge": "Fillet2.e1",
        "created": unix,
        "time": filetime,
        "cache_memo": 0.0,
        "counter_marks": 29,
    }
    fields = ("id", "name", "label", "feature", "last", "changed", "live", "from", "into", "regen")
    assert [tuple(b[k] for k in fields) for b in s["bodies"]] == [
        (101, "Fillet1", "body1", 32, 34, [34], False, [], [102], 1151),
        (102, "Fillet2", "body2", 42, 44, [44], True, [101], [], 1153),
    ]
    # 15.6.5: by node id modulo 17 (34 is 0, 42 is 8, 44 is 10, 32 is 15), each its own time.
    assert s["builds"] == [{"feature": n, "time": filetime} for n in (34, 42, 44, 32)]
    assert s["model.back_view"] and s["hdr.next_id"] == 45
    # 15.6.6: the fillets do not count towards the stamps; 15.6.5: the ids follow them.
    assert (s["doc.stamp"], s["doc.stamp2"], s["fixed.id_base"]) == (140, 111, 123)
    assert [x["id"] for x in s["meta.kw_extrusions"]] == [32, 42]
    kw = [x["id"] for x in s["meta.kw_features"]]
    assert kw.index(34) == kw.index(3) + 1 and kw.index(44) == kw.index(4) + 1 and len(kw) == 25
    assert [x for x in s["meta.kw_features"] if x["fillet"]] == [
        {"id": 34, "name": "Fillet1", "fillet": True, "radius_text": "3"},
        {"id": 44, "name": "Fillet2", "fillet": True, "radius_text": "1"},
    ]
    # Rounded edges lie inside the box: the model box and the planes are the box's (15.6.3).
    alone = gen.plan(ir.Document("o11", o11_box()), identity=IDENT).slots
    for key in ("model.min", "model.max", "model.sphere", "hdr.centre", "planes.front", "planes.right"):
        assert s[key] == alone[key]
    assert not alone["model.back_view"]
    assert p.names["f1"] == p.names["Round"] == "Fillet1" and p.names["Rim"] == "Fillet2"
    assert p.left_out == []


def test_a_box_with_a_fillet_and_no_hole():
    s = gen.plan(ir.Document("d", o11_box() + [round_edges()]), identity=IDENT).slots
    ids = [(f["name"], f["id"]) for f in s["features"]]
    assert ids == [("Sketch1", 26), ("Boss-Extrude1", 32), ("Fillet1", 34)]
    assert (s["doc.stamp"], s["doc.stamp2"], s["fixed.id_base"], s["hdr.next_id"]) == (120, 105, 106, 35)
    (body,) = s["bodies"]
    assert (body["name"], body["feature"], body["changed"], body["last"], body["live"]) == (
        "Fillet1",
        32,
        [34],
        34,
        True,
    )
    assert [b["feature"] for b in s["builds"]] == [34, 32] and s["model.back_view"]
    assert [x["id"] for x in s["meta.kw_extrusions"]] == [32]


def test_a_fillet_on_the_hole_of_a_box_without_one():
    features = o11_box() + hole(2, 0.02, 0.015, 0.005) + [round_rim()]
    s = gen.plan(ir.Document("d", features), identity=IDENT).slots
    feats = s["features"]
    assert [(f["name"], f["id"]) for f in feats] == [
        ("Sketch1", 26),
        ("Boss-Extrude1", 32),
        ("Sketch2", 33),
        ("Cut-Extrude1", 40),
        ("Fillet1", 42),
    ]
    rim = feats[4]
    assert rim["hole"] and rim["body_id"] == 102 and rim["counter_marks"] == 29 and not s["model.back_view"]
    assert [(x["kind"], x["face"]) for x in feats[3]["ring"]] == [(1, 4), (2, 1), (1, 3), (2, 0), (1, 1)]
    assert rim["edges"][0]["faces"][0] == {"kind": 3, "uid": 40, "created": s["doc.unix"], "face": 1}
    assert [b["name"] for b in s["bodies"]] == ["Boss-Extrude1", "Fillet1"]
    assert (s["doc.stamp"], s["fixed.id_base"], s["hdr.next_id"]) == (140, 124, 43)


def test_refused_fillets_by_place():
    one = o11_box()
    assert _refusal(one + [round_edges(suppressed=True)]) == ["Round: suppressed fillet"]
    assert _refusal([round_edges()]) == [f"Round: {POSITION}"]
    second = box(2, 0.05, 0.0, 0.06, 0.01, 0.01)
    assert _refusal(one + second + [round_edges()]) == [f"Round: {POSITION}"]
    # A part with two boxes has no fillet, wherever it stands.
    assert _refusal(one + [round_edges()] + second) == [f"Round: {POSITION}"]
    assert _refusal(one + [round_edges(), round_edges("f3", "Again")]) == [f"Again: {POSITION}"]
    after_sketch = one + [circle_sketch("s2", "C", 0.02, 0.015, 0.005), round_edges()]
    assert _refusal(after_sketch) == ["C: sketch not followed by its extrusion", f"Round: {POSITION}"]


def test_refused_fillets_on_the_box():
    one = o11_box()
    corners = [(x, y, 0.005) for x, y in O11_CORNERS]
    assert _refusal(one + [round_edges(points=corners[:3])]) == [f"Round: {FOUR}"]
    assert _refusal(one + [round_edges(points=[*corners[:3], corners[0]])]) == [f"Round: {FOUR}"]
    assert _refusal(one + [round_edges(points=[*corners, (0.02, 0.0, 0.005)])]) == [f"Round: {FOUR}"]
    for bad in ((0.04, 0.03, 0.01), (0.04, 0.03, 0.0), (0.02, 0.03, 0.005), (0.04 + 2e-9, 0.03, 0.005)):
        assert _refusal(one + [round_edges(points=[*corners[:3], bad])]) == [f"Round: {FOUR}"]
    # A point within 1e-9 m names the edge, and the edges may come in any order.
    near = [(5e-10, 0.03 - 5e-10, 0.009), *reversed(corners[:3])]
    assert _plan_ok(one + [round_edges(points=near)]) == []
    half = "Round: the fillet's radius must be less than half the box's shorter side"
    assert _refusal(one + [round_edges(r=0.015)]) == [half]
    assert _plan_ok(one + [round_edges(r=0.0149)]) == []


def test_refused_fillets_on_the_hole():
    one = o11_box()
    bore = hole(2, 0.02, 0.015, 0.005)
    for point in ((0.025, 0.015, 0.0), (0.0251, 0.015, 0.01), (0.02, 0.015, 0.01)):
        assert _refusal(one + bore + [round_rim(point=point)]) == [f"Rim: {RIM_EDGE}"]
    two = ir.Fillet("f2", "Rim", [ir.EdgeRef((0.025, 0.015, 0.01)), ir.EdgeRef((0.015, 0.015, 0.01))], 0.001)
    assert _refusal(one + bore + [two]) == [f"Rim: {RIM_EDGE}"]
    # The rounded rim must stay on the far face, and its radius below the box's depth.
    near_side = hole(2, 0.01, 0.015, 0.005)
    wide = round_rim(r=0.0051, point=(0.015, 0.015, 0.01))
    assert _refusal(one + near_side + [wide]) == [f"Rim: {RIM_CLEAR}"]
    assert _plan_ok(one + near_side + [round_rim(r=0.0049, point=(0.015, 0.015, 0.01))]) == []
    small = hole(2, 0.02, 0.015, 0.002)
    assert _refusal(one + small + [round_rim(r=0.01, point=(0.022, 0.015, 0.01))]) == [f"Rim: {RIM_CLEAR}"]
    # Near a rounded corner: clear of the 3 mm squares with a 2 mm rim, not with a 2.5 mm one.
    corner = hole(2, 0.006, 0.006, 0.002)
    rim = round_rim(r=0.0025, point=(0.008, 0.006, 0.01))
    assert _refusal(one + [round_edges()] + corner + [rim]) == [f"Rim: {RIM_CLEAR}"]
    assert _plan_ok(one + corner + [rim]) == []
    assert _plan_ok(one + [round_edges()] + corner + [round_rim(r=0.002, point=(0.008, 0.006, 0.01))]) == []


def test_a_fillet_on_the_hole_is_the_last_feature():
    # 15.6.2: a cut followed by more than one fillet is refused, so through plan the fillet
    # after an accepted cut is always the last item; the rule stands behind that.
    from solidseas.nativewrite.generate.slots import _Circle, _hole_fillet_problem, _rectangle

    rect, _ = _rectangle(o11_box()[0])
    circle = _Circle("k", "c", (0.02, 0.015), 0.005)
    assert _hole_fillet_problem(round_rim(), rect, 0.01, circle, None, False) == (
        "a fillet on the hole's edge is written only as the last feature"
    )
    assert _hole_fillet_problem(round_rim(), rect, 0.01, circle, None, True) is None


def test_a_cut_into_a_rounded_corner_is_refused():
    one = o11_box()
    corner = hole(2, 0.004, 0.004, 0.0025)
    rounded = "MyCut2: the circle runs into a rounded corner of the box"
    assert _refusal(one + [round_edges()] + corner) == [rounded]
    assert _plan_ok(one + corner) == []
    # A cut followed by a fillet and anything else is not the hole's last step.
    items = _refusal(one + hole(2, 0.02, 0.015, 0.005) + [round_rim(), round_rim("f3", "Again")])
    assert items[0].startswith("MyCut2: a cut is written only as the last feature")
    assert items[1:] == [f"Again: {POSITION}"]


def test_allow_partial_leaves_out_fillets_and_what_they_round():
    # The box's fillet left out: the hole stays, written as on a box without fillets, and a
    # circle in what would be a rounded corner is accepted.
    features = o11_box() + [round_edges(suppressed=True)] + hole(2, 0.004, 0.004, 0.0025)
    features.append(round_rim(r=0.0005, point=(0.0065, 0.004, 0.01)))
    p = gen.plan(ir.Document("d", features), identity=IDENT, allow_partial=True)
    assert p.left_out == ["Round: suppressed fillet"]
    s = p.slots
    names = ["Sketch1", "Boss-Extrude1", "Sketch2", "Cut-Extrude1", "Fillet1"]
    assert [f["name"] for f in s["features"]] == names
    assert s["features"][3]["ring"][2]["kind"] == 1 and not s["model.back_view"]
    # A refused cut takes the fillet on its edge with it; only the cut is refused.
    features = o11_box() + hole(2, 0.02, 0.015, 0.005, direction="forward") + [round_rim()]
    with pytest.raises(gen.NativeWriteUnsupported) as e:
        gen.plan(ir.Document("d", features), identity=IDENT)
    assert e.value.items == ["MyCut2: only a cut through all in both directions is written"]
    p = gen.plan(ir.Document("d", features), identity=IDENT, allow_partial=True)
    assert p.left_out == [
        "MyCut2: only a cut through all in both directions is written",
        "MyCircle2: left out with MyCut2, which is not written",
        "Rim: left out because MyCut2, whose body it rounds, is not written",
    ]
    assert [f["name"] for f in p.slots["features"]] == ["Sketch1", "Boss-Extrude1"]
    # So does a refused box: nothing is left to round.
    features = box(1, 0.0, 0.0, 0.04, 0.03, 0.01, direction="reverse") + [round_edges()]
    p = gen.plan(ir.Document("d", features), identity=IDENT, allow_partial=True)
    assert p.left_out[-2:] == [
        "MySketch1: left out with MyExtrude1, which is not written",
        "Round: left out because MyExtrude1, whose body it rounds, is not written",
    ]
    assert p.slots["features"] == []


def test_a_fillet_radius_expression_is_reported():
    def left_out(expression):
        params = [ir.Parameter("rr", 0.003, expression=expression)]
        doc = ir.Document("d", o11_box() + [round_edges(radius_parameter="rr")], params)
        return gen.plan(doc, identity=IDENT).left_out

    assert left_out("wall / 2") == [
        "Round: radius 3 mm is written as a number; the expression wall / 2 is not kept"
    ]
    assert left_out("3 mm") == []


def test_the_fixed_features_of_keywords():
    s = gen.plan(ir.Document("empty"), identity=IDENT).slots
    fixed = s["meta.kw_features"]
    assert len(fixed) == 23 and not any(x["fillet"] for x in fixed)
    assert {x["id"] for x in fixed} == set(range(1, 26)) - {5, 20}
    assert [x["id"] for x in fixed] == sorted((x["id"] for x in fixed), key=str)
    text = gen.assemble(s)["swXmlContents/KeyWords"][1:].decode()
    assert '<Feature id="11" Name="Material &lt;not specified&gt;" Type="SOLIDWORKS Materials"/>' in text
    assert '<Feature id="19" Name="" Type="Exploded Views"/><Feature id="2" Name="Front Plane"' in text
    assert '<Feature id="24" Name="Folder " Type="History"/>' in text


def test_a_box_with_fillets_writes_and_reads_back():
    doc = example_o11()
    blob = gen.write_part(doc, identity=IDENT)
    part = container.read_document(blob)
    s = gen.plan(doc, identity=IDENT).slots
    m = gen.assemble(s)
    assert [x.name for x in part.members] == list(gen.MEMBERS)
    for x in part.members:
        assert x.data == m[x.name]
    plain = gen.assemble(gen.plan(dataclasses.replace(example_hole(), name="o11"), identity=IDENT).slots)
    # The stamps count the box and the cut, not the fillets (15.6.6).
    assert m["ModelStamps"] == struct.pack("<III", s["doc.created"], 140, 111)
    # KeyWords (15.1.5): each fillet a Feature with its radius, among the fixed features by id
    # as text, and no Extrusion element.
    text = m["swXmlContents/KeyWords"][1:].decode()
    f1 = '<Feature id="34" Name="Fillet1" Type="Fillet"><Dimension Name="D1">R3</Dimension></Feature>'
    f2 = '<Feature id="44" Name="Fillet2" Type="Fillet"><Dimension Name="D1">R1</Dimension></Feature>'
    assert text.index('<Feature id="3" ') < text.index(f1) < text.index('<Feature id="4" ') < text.index(f2)
    assert '<Extrusion id="34"' not in text and '<Extrusion id="42"' in text
    # Config-0 (15.4.9): a second annotation view, *Back, and the last view's number 201.
    c0 = m["Contents/Config-0"]
    back, top = listing.cstring("*Back"), listing.cstring("*Top")
    assert c0.count(back) == plain["Contents/Config-0"].count(back) + 1
    assert c0.count(top) == plain["Contents/Config-0"].count(top)
    assert struct.pack("<IIII", 201, 199, 1, 199) in c0
    assert struct.pack("<IIII", 200, 199, 1, 199) in plain["Contents/Config-0"]
    # The feature stream (15.5.14): 17 + 6 top-level features, each fillet's records and end.
    fs = m["Contents/Config-0-ResolvedFeatures"]
    assert fs[4:6] == (23).to_bytes(2, "little")
    for name in ("Fillet_c", "moFilletSurfIdRep_c", "moEdgeRef_c", "edgeRadiusObject_c", "ThreeDRadiusDim_c"):
        assert name.encode() in fs
    end = struct.pack("<IH5I", 6, 0, 21040, 25, 23341, 22711, 22993) + bytes(16)
    assert fs.count(end) == 2
    assert struct.pack("<3d", 0.003, 0.003, 0.01) * 2 in fs
    # SwDocContentMgrInfo (15.1.6): the one live body, named after the last fillet that built it.
    info = m["SwDocContentMgr/SwDocContentMgrInfo"]
    assert struct.pack("<II", 1, 102) + listing.cstring("Fillet2") in info
    assert listing.cstring("Cut-Extrude1") not in info
    # CMgr (15.2.7.5): four builds, each fillet's with its own time.
    hi, lo = s["doc.filetime"] // 2**32, s["doc.filetime"] % 2**32
    builds = struct.pack("<I", 4) + b"".join(struct.pack("<III", n, hi, lo) for n in (34, 42, 44, 32))
    assert builds in m["Contents/CMgr"]
    # A box with its fillet alone writes too, with the *Back view.
    lone = gen.assemble(gen.plan(ir.Document("d", o11_box() + [round_edges()]), identity=IDENT).slots)
    assert lone["Contents/Config-0"].count(back) == c0.count(back)
    assert lone["Contents/Config-0-ResolvedFeatures"][4:6] == (20).to_bytes(2, "little")


def test_the_fillet_shape_of_spec_constants():
    shapes = [pair for pair in gen._shapes() if pair[0][0].name == "fillets"]
    assert len(shapes) == 1
    (doc_a, id_a), (doc_b, id_b) = shapes[0]
    a, b = gen.plan(doc_a, identity=id_a).slots, gen.plan(doc_b, identity=id_b).slots
    names = ["Sketch1", "Boss-Extrude1", "Fillet1", "Sketch2", "Cut-Extrude1", "Fillet2"]
    assert [f["name"] for f in a["features"]] == [f["name"] for f in b["features"]] == names
    for k in (2, 5):
        ta, tb = a["features"][k]["radius_text"], b["features"][k]["radius_text"]
        assert len(ta) == len(tb) and ta[-1] != tb[-1] and {ta, tb}.isdisjoint({"3", "1"})
        assert a["features"][k]["radius"] != b["features"][k]["radius"]
    assert {n: len(v) for n, v in gen.assemble(a).items()} == {n: len(v) for n, v in gen.assemble(b).items()}
    # A fillet's end is the same in every part: inside a constant run (15.5.14).
    fs = gen.assemble(a)["Contents/Config-0-ResolvedFeatures"]
    end = struct.pack("<IH5I", 6, 0, 21040, 25, 23341, 22711, 22993) + bytes(16)
    assert fs.count(end) == 2 and any(end in c for c in gen.SPEC_CONSTANTS)
