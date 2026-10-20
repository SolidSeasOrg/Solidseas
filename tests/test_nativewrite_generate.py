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
    assert items == ["Round: fillets are not written yet", "Loft1: lofts are not in the IR"]


def test_allow_partial_leaves_out_refused_items_and_their_dependents():
    sk = rect_sketch("s", "Tilted", 0.0, 0.0, 0.01, 0.01)
    sk.points[1].y = 0.001
    features = [sk, ir.Extrude("e", "Pushed", "s", 0.01)] + box(2, 0.02, 0, 0.03, 0.01, 0.01)
    features.append(ir.Fillet("f", "Round", [ir.EdgeRef((0.0, 0.0, 0.0))], 0.001))
    with pytest.raises(gen.NativeWriteUnsupported) as e:
        gen.plan(ir.Document("d", features), identity=IDENT)
    assert e.value.items == [
        "Tilted: rectangle is not aligned with the sketch axes",
        "Round: fillets are not written yet",
    ]
    p = gen.plan(ir.Document("d", features), identity=IDENT, allow_partial=True)
    assert p.left_out == [
        "Tilted: rectangle is not aligned with the sketch axes",
        "Pushed: left out because its sketch is not written",
        "Round: fillets are not written yet",
    ]
    # The written pair is the first of the part: Sketch1 and Boss-Extrude1, off the origin.
    assert [f["name"] for f in p.slots["features"]] == ["Sketch1", "Boss-Extrude1"]
    assert p.slots["features"][1]["id"] == 33 and p.names["MyExtrude2"] == "Boss-Extrude1"


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
    assert e.value.items == ["Fillet1: fillets are not written yet"]
    p = gen.plan(sample, identity=IDENT, allow_partial=True)
    assert p.left_out[-1] == "Fillet1: fillets are not written yet"
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
