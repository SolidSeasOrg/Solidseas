"""Damaged and crafted Alibre Design and ACIS files (``docs/formats/alibre.md``): each
ends in a documented exception, a warning or a face left out, within its bounds, and
never in an error a crafted file should not be able to provoke."""

import math
import struct
import time

import pytest

import alibre_writers as A
import sab_writers as W
from solidseas import export
from solidseas.errors import SldFormatError, SldLimitError, SolidSeasError
from solidseas.formats import Limits, open_model
from solidseas.formats._source import Clock, ReadCancelledError
from solidseas.formats.acis import entities as E
from solidseas.formats.acis import sab
from solidseas.formats.acis.entities import AcisError, Model
from solidseas.formats.acis.geometry import bodies, body_faces, build_body
from solidseas.formats.alibre import mesh as meshmod
from solidseas.formats.alibre import props as propsmod

L = Limits()


def _stream(recs: list[list]) -> bytes:
    return W.stream([(n, v) for n, v in recs])


def _build(data: bytes):
    m = Model(sab.read(data, L), L)
    return build_body(m, bodies(m)[0], L)


# --------------------------------------------------------------------------- SAB
def test_a_sab_stream_cut_anywhere_is_damage():
    data = W.cube().sab(persistent_ids=True)
    for n in range(0, len(data), 7):
        with pytest.raises(SldFormatError):
            sab.read(data[:n], L)


def test_an_unknown_tag_is_damage():
    data = bytearray(W.cube().sab())
    at = data.index(bytes((W.PTR,)), len(sab.read_header(bytes(data), L).signature) + 80)
    data[at] = 0x99
    with pytest.raises(SldFormatError, match="unknown ACIS tag"):
        sab.read(bytes(data), L)


def test_a_pointer_out_of_range_costs_its_face():
    recs = W.records_of(W.cube())
    face = W.find(recs, "face", 2)
    recs[face][1][8] = (W.PTR, 99_999)  # the surface pointer
    build = _build(_stream(recs))
    assert [s.reason for s in build.skipped] == ["bad_reference"]
    assert build.faces == 6


def test_a_reference_to_a_missing_subtype_costs_its_face():
    sol = W.split_box()
    sol.faces[6].surface = W.spline_ref(7)
    build = _build(sol.sab())
    assert [s.reason for s in build.skipped] == ["bad_reference"]


@pytest.mark.parametrize("what", ["face", "loop", "coedge"])
def test_chains_that_loop_end(what):
    recs = W.records_of(W.cube())
    if what == "face":
        last = W.find(recs, "face", 5)
        recs[last][1][4] = (W.PTR, W.find(recs, "face", 0))  # the last face's next: the first
        build = _build(_stream(recs))
        assert build.faces == 6  # the walk stops where the chain comes round
        return
    if what == "loop":
        lp = W.find(recs, "loop", 1)
        recs[lp][1][4] = (W.PTR, lp)  # a loop whose next is itself
    else:
        first = W.find(recs, "coedge", 4)
        recs[first][1][4] = (W.PTR, W.find(recs, "coedge", 5))
        recs[W.find(recs, "coedge", 5)][1][4] = (W.PTR, W.find(recs, "coedge", 6))
        recs[W.find(recs, "coedge", 6)][1][4] = (W.PTR, W.find(recs, "coedge", 5))  # round 5 and 6, never 4
    build = _build(_stream(recs))
    assert len(build.skipped) == 1 and build.skipped[0].reason == "bad_reference"


# Every decoder of the model and the classes it may answer.
DECODERS = {
    "body": (E.Body,),
    "lump": (E.Lump,),
    "shell": (E.Shell,),
    "face": (E.Face,),
    "loop": (E.Loop,),
    "coedge": (E.Coedge,),
    "edge": (E.Edge,),
    "vertex": (E.Vertex,),
    "point": (tuple,),
    "transform": (E.Transform,),
    "surface": (E.Plane, E.Cone, E.Sphere, E.Torus, E.Spline),
    "curve": (E.Straight, E.Ellipse, E.IntCurve),
}


def test_every_decoder_checks_a_record_another_decoder_already_read():
    """The decoders share one model: asking any of them for any record, twice round,
    answers its own class or raises AcisError, never what another decoder left."""
    sol = W.rational_cylinder()
    sol.transform = (((0, 1, 0), (-1, 0, 0), (0, 0, 1)), (1.0, 2.0, 3.0), 1.0)
    m = Model(sab.read(sol.sab(), L), L)
    for _round in range(2):
        for i in range(len(m.records)):
            for name, classes in DECODERS.items():
                try:
                    got = getattr(m, name)(i)
                except AcisError as exc:
                    assert exc.reason in ("bad_reference", "unsupported_surface", "unsupported_curve")
                else:
                    assert isinstance(got, classes), (i, m.type_of(i), name)


def _misdirected() -> bytes:
    """The cube with the first coedge's edge pointing at the body, and the first face's
    next at a surface: records of other classes, which other decoders read first."""
    recs = W.records_of(W.cube())
    recs[W.find(recs, "coedge", 0)][1][7] = (W.PTR, W.find(recs, "body"))
    recs[W.find(recs, "face", 0)][1][4] = (W.PTR, W.find(recs, "plane-surface", 3))
    return _stream(recs)


@pytest.mark.parametrize("container", ["sab", "alibre"])
def test_pointers_to_records_decoded_as_another_class_cost_their_face(container):
    data = _misdirected()
    if container == "alibre":
        data, name = A.part(streams={"SAB_DATA": data}), "cube.AD_PRT"
    else:
        name = "cube.sab"
    with open_model(data, name=name) as doc:
        for k in range(2):  # the second walk meets records the first decoded
            scene = doc.scene(prefer="bodies", max_triangles=10_000 + k)
            assert [o.source for o in scene.objects] == ["bodies"]
            assert [s.reason for s in scene.skipped] == ["bad_reference"]
            assert scene.counts["faces_done"] == 5
            (ref,) = doc.bodies()
            assert ref.body_type == "sheet"  # the face it cost leaves the body open
        if container == "alibre":  # printing falls back to the display mesh
            assert export.print_model(doc).objects[0].source == "display_mesh"
        else:
            with pytest.raises(SolidSeasError):
                export.print_model(doc)


def _long_record(n: int) -> bytes:
    """The cube, then one record of ``n`` true flags."""
    cube = W.cube().sab()
    end = cube.rfind(W.END_MARKER)
    return cube[:end] + W.encode("x", [W.b(True)] * n) + W.END_MARKER


def test_the_clock_is_looked_at_inside_a_long_record():
    data = _long_record(50_000)
    assert len(sab.read(data, L).records) == len(sab.read(W.cube().sab(), L).records) + 1
    with pytest.raises(ReadCancelledError):
        sab.read(data, L, Clock(None, lambda: True))
    with pytest.raises(SldLimitError) as err:
        sab.read(data, L, Clock(1e-9))
    assert err.value.detail["limit"] == "seconds"


def test_a_scene_bounds_the_sab_read_by_its_own_clock():
    """The tokenizer runs under the scene's clock (and its cancel), not only
    ``limits.seconds``."""
    with open_model(_long_record(50_000), name="long.sab") as doc:
        with pytest.raises(ReadCancelledError):
            doc.scene(cancelled=lambda: True)
        assert doc.scene().objects  # nothing half-read was kept
    with open_model(A.part(streams={"SAB_DATA": _long_record(50_000)}), name="long.AD_PRT") as doc:
        with pytest.raises(ReadCancelledError):
            doc.scene(prefer="bodies", cancelled=lambda: True)


def test_the_values_bound_is_kept():
    data = _long_record(5_000)
    with pytest.raises(SldLimitError) as err:
        sab.read(data, L.replace(sab_values=4_000))
    assert err.value.detail["limit"] == "sab_values"
    # a position or vector counts three: 400 of them pass 1,000
    many = W.stream([("point", [W.pos((0, 0, 0))] * 400)])
    with pytest.raises(SldLimitError):
        sab.read(many, L.replace(sab_values=1_000))
    assert len(sab.read(many, L.replace(sab_values=1_300)).records) == 1


def _spheres(n: int) -> bytes:
    """``n`` whole spheres, each a body of its own: a standalone .sab."""
    recs = []
    for k in range(n):
        body, lump, shell, face, surf = range(len(recs), len(recs) + 5)
        recs.append(("body", W.prefix() + [W.ptr(lump), W.NULL, W.NULL, W.b(False)]))
        recs.append(("lump", W.prefix() + [W.NULL, W.ptr(shell), W.ptr(body), W.b(False)]))
        recs.append(("shell", W.prefix() + [W.NULL, W.NULL, W.ptr(face), W.NULL, W.ptr(lump), W.b(False)]))
        recs.append(
            ("face", W.prefix() + [W.NULL, W.NULL, W.ptr(shell), W.NULL, W.ptr(surf), W.b(False), W.b(False)])
        )
        name, vals = W.sphere((3 * k, 0, 0), 1.0)
        recs.append((name, W.prefix() + list(vals)))
    return W.stream(recs)


def test_many_bodies_find_their_faces_without_a_pass_over_every_record_each(monkeypatch):
    """The faces outside a shell's chain come from one index of faces by shell, so the
    work grows with the bodies, not with their square."""
    n = 300
    m = Model(sab.read(_spheres(n), L), L)
    calls = 0
    face = Model.face

    def counted(self, i):
        nonlocal calls
        calls += 1
        return face(self, i)

    monkeypatch.setattr(Model, "face", counted)
    found = [body_faces(m, b) for b in bodies(m)]
    assert [len(f) for f in found] == [1] * n
    assert calls < 5 * n  # a pass over every face for every body would be n * n


def test_a_face_cut_off_its_shells_chain_is_still_found():
    recs = W.records_of(W.cube())
    recs[W.find(recs, "face", 2)][1][4] = W.NULL  # the chain ends after the third face
    build = _build(_stream(recs))
    assert build.faces == 6 and not build.skipped and build.body_type == "solid"


def test_a_knot_that_is_not_finite_costs_its_face_not_the_body():
    sol = W.rational_cylinder()
    name, vals = sol.faces[0].surface
    vals = list(vals)
    last_u = 4 + 10 + 2 * (len(W.CIRCLE_KNOTS) - 1)  # sense, {, exactsur, enum; then the block
    assert vals[last_u] == W.d(4.0)
    vals[last_u] = W.d(math.inf)
    sol.faces[0].surface = (name, vals)
    with open_model(sol.sab(), name="k.sab") as doc:
        scene = doc.scene()
    assert [s.reason for s in scene.skipped] == ["bad_geometry"]
    assert scene.counts["faces"] == 3 and scene.counts["faces_done"] == 2
    with open_model(A.part(solid=sol, mesh=A.cylinder_mesh()), name="k.AD_PRT") as doc:
        scene = doc.scene(prefer="bodies")
    assert [o.source for o in scene.objects] == ["bodies"]
    assert [s.reason for s in scene.skipped] == ["bad_geometry"]


def test_a_number_the_node_writer_refuses_costs_its_face():
    """A length that overflows once the body's scale is applied: the node writer refuses
    it, and only the face it belongs to is left out."""
    sol = W.cylinder()
    name, vals = sol.faces[0].surface
    vals = list(vals)
    vals[2] = W.vec((1e150, 0, 0))  # the side's major axis: its radius
    sol.faces[0].surface = (name, vals)
    sol.transform = (((1, 0, 0), (0, 1, 0), (0, 0, 1)), (0.0, 0.0, 0.0), 1e300)
    m = Model(sab.read(sol.sab(), L), L)
    build = build_body(m, bodies(m)[0], L)
    assert [s.reason for s in build.skipped] == ["non_finite"]
    assert build.faces == 3 and build.body_type == "solid"


def test_subtypes_nested_too_deeply_reach_their_bound():
    vals = [W.b(False)] + [W.OPEN, W.kw("exactsur")] * 70 + [W.CLOSE] * 70
    data = W.stream([("spline-surface", W.prefix() + vals)])
    with pytest.raises(SldLimitError) as err:
        sab.read(data, L)
    assert err.value.detail["limit"] == "sab_subtype_depth"


def test_spline_counts_past_the_values_left_cost_the_face():
    sol = W.split_box()
    block = W.bs3_surface(1, 1, [(0.0, 1), (1.0, 1)], [(0.0, 1), (1.0, 1)], [(0, 0, 1)] * 4)
    block[7] = W.i(900)  # the number of u knots
    sol.faces[5].surface = W.spline(block)
    sol.faces[6].surface = W.spline_ref(0)
    build = _build(sol.sab())
    assert len(build.skipped) == 2 and {s.reason for s in build.skipped} == {"bad_geometry"}


def test_the_record_bound_is_kept():
    with pytest.raises(SldLimitError) as err:
        sab.read(W.cube().sab(), L.replace(sab_records=10))
    assert err.value.detail["limit"] == "sab_records"


def test_a_long_string_is_refused():
    data = W.stream([("point", [W.s7("x" * 200)])])
    with pytest.raises(SldLimitError):
        sab.read(data, L.replace(sab_string_bytes=100))


# --------------------------------------------------------------------------- MESH_DATA
def _mesh() -> bytes:
    return A.mesh_data(A.cube_mesh())


def _face_block_at(data: bytes) -> int:
    return meshmod.read_header(data, L).end


@pytest.mark.parametrize(
    "damage",
    ["huge_v", "huge_l", "index", "terminator", "quad", "counts", "trailing", "key"],
)
def test_a_damaged_display_mesh_is_refused_and_the_part_still_reads(damage):
    data = bytearray(_mesh())
    at = _face_block_at(bytes(data))
    if damage == "huge_v":
        struct.pack_into("<i", data, at + 8, 0x7FFFFFF)
    elif damage == "huge_l":
        struct.pack_into("<i", data, at + 4, 0x7FFFFFF)
    elif damage == "index":
        struct.pack_into("<i", data, at + 21 + 4 * 32 + 4, 77)  # the first triangle's first corner
    elif damage == "terminator":
        struct.pack_into("<i", data, at + 21 + 4 * 32 + 8 * 4, 5)
    elif damage == "quad":
        struct.pack_into("<i", data, at + 21 + 4 * 32, 4)
    elif damage == "counts":
        struct.pack_into("<i", data, at - 12, 9)  # nine faces declared, six stored
    elif damage == "trailing":
        data += b"\0" * 4
    elif damage == "key":
        struct.pack_into("<i", data, 4, 100_000)  # the first key's length
    data = bytes(data)
    with pytest.raises(SldFormatError):
        meshmod.read(data, L)
    with open_model(A.part(streams={"MESH_DATA": data}), name="cube.AD_PRT") as doc:
        scene = doc.scene(prefer="display")
    assert [o.source for o in scene.objects] == ["bodies"]
    assert "stream_unreadable" in {w.code for w in [*doc.warnings, *scene.warnings]}


def test_the_clock_is_looked_at_inside_a_long_display_mesh_block():
    n = 10_000  # one face block: a fan of n triangles
    recs = [(0.0, 0.0, 0.0, 0, 0, 1, 0, 0)]
    recs += [(math.cos(k), math.sin(k), 0.0, 0, 0, 1, 0, 0) for k in range(n + 1)]
    tris = [(0, 1 + k, 2 + k) for k in range(n)]
    data = A.mesh_data(A.DisplayMesh([A.MeshFace(1, recs, tris)], [], "cm", vertices=0))
    assert len(meshmod.read(data, L).triangles) == 3 * n
    with pytest.raises(ReadCancelledError):
        meshmod.read(data, L, Clock(None, lambda: True))


def test_too_many_dictionary_entries_reach_their_bound():
    data = bytearray(_mesh())
    struct.pack_into("<i", data, 0, 5000)
    with pytest.raises(SldLimitError):
        meshmod.read_header(bytes(data), L)


# --------------------------------------------------------------------------- PROP_DATA, VERSION, the rest
def test_a_blob_longer_than_its_stream_keeps_what_came_before():
    damaged = A.prop_data() + A.ustr("snapshot") + struct.pack("<iiii", 1, 0x28, 1, 1 << 30) + b"BM"
    entries, error = propsmod.read(damaged, L)
    assert isinstance(error, SldFormatError) and len(entries) == 15
    with open_model(A.part(streams={"PROP_DATA": damaged}), name="cube.AD_PRT") as doc:
        assert doc.preview() is None and doc.fields.title == "Test cube"
        assert [w.code for w in doc.warnings] == ["stream_unreadable"]
        assert doc.warnings[0].stream == "PROP_DATA"


def test_a_bitmap_claiming_a_huge_size_is_refused():
    bmp = bytearray(A.bmp())
    struct.pack_into("<i", bmp, 18, 100_000)
    with open_model(A.part(snapshot=bytes(bmp)), name="cube.AD_PRT") as doc:
        with pytest.raises(SldFormatError):
            doc.preview()
        summary = doc.summary()
    assert summary["preview"]["reason"] == "undecodable"
    assert "preview_undecodable" in {w["code"] for w in summary["warnings"]}


@pytest.mark.parametrize("stream", ["VERSION", "LIGHT_CONFIGURATION_DATA"])
def test_a_string_longer_than_its_stream_is_a_warning(stream):
    damaged = struct.pack(">H", 900) + b"<Repository"
    if stream == "LIGHT_CONFIGURATION_DATA":
        damaged = b"\0\0\0\0" + damaged
    with open_model(A.part(streams={stream: damaged}), name="cube.AD_PRT") as doc:
        assert [(w.code, w.stream) for w in doc.warnings] == [("stream_unreadable", stream)]
        assert doc.scene().objects


def test_an_unterminated_string_in_the_design_database():
    design = A.assembly_design([A.Placed(A.CUBE_GUID)]).replace(b"'C'", b"'C", 1)
    with open_model(A.assembly([A.Placed(A.CUBE_GUID)], design=design), name="x.AD_ASM") as doc:
        with pytest.raises(SldFormatError):
            doc.tree()
        with pytest.raises(SldFormatError):
            doc.scene()


def test_damaged_constituents_are_a_warning(tmp_path):
    (tmp_path / "cube.AD_PRT").write_bytes(A.part())
    data = A.assembly([A.Placed(A.CUBE_GUID)], streams={"CONSTITUENTS": struct.pack(">H", 50) + b"<Rep"})
    (tmp_path / "x.AD_ASM").write_bytes(data)
    with open_model(tmp_path / "x.AD_ASM") as doc:
        assert doc.references()[0].resolution["status"] == "found"
        assert ("stream_unreadable", "CONSTITUENTS") in {(w.code, w.stream) for w in doc.warnings}


@pytest.mark.parametrize(
    ("limits", "name"),
    [
        ({"ole_streams": 3}, "ole_streams"),
        ({"alibre_small_stream_bytes": 16}, "alibre_small_stream_bytes"),
        ({"alibre_text_stream_bytes": 64}, "alibre_text_stream_bytes"),
    ],
)
def test_the_container_bounds_are_kept(limits, name):
    with pytest.raises(SldLimitError) as err:
        open_model(A.part(), name="cube.AD_PRT", limits=limits)
    assert err.value.detail["limit"] == name


def test_too_many_inclusions_reach_their_bound(tmp_path):
    placed = [A.Placed(A.CUBE_GUID) for _ in range(5)]
    with open_model(A.assembly(placed), name="x.AD_ASM", limits={"inclusions": 3}) as doc:
        with pytest.raises(SldLimitError):
            doc.tree()


def test_deeply_nested_lists_in_the_design_database():
    nested = "(" * 40 + ")" * 40
    design = A.p21(["#1=SCHEMAVERSION('a','b');", f"#2=DESIGNASSEMBLY({nested});"])
    with open_model(A.assembly([], design=design), name="x.AD_ASM") as doc:
        with pytest.raises(SldLimitError):
            doc.tree()


def test_a_crafted_file_never_raises_anything_else():
    """Single bytes overwritten all through a part: every outcome is a SolidSeas error, a
    warning or a result, in bounded time."""
    good = A.part()
    t0 = time.perf_counter()
    for at in range(512, len(good), 997):
        data = bytearray(good)
        data[at] ^= 0x5A
        try:
            with open_model(bytes(data), name="cube.AD_PRT") as doc:
                doc.summary()
                doc.scene(prefer="display")
                doc.scene(prefer="bodies")
        except SolidSeasError:
            pass
    assert time.perf_counter() - t0 < 120
