"""Crafted STEP text that used to cost time quadratic in its size, and the write guard
that keeps the library from writing a SOLIDWORKS file. The time bounds are loose on
purpose: the quadratic versions took minutes on these inputs, the linear ones well under
a second. Where the work can be counted, the tests count it instead of timing it."""

import time
from collections import Counter

import pytest

import p21_writers as W
from solidseas.errors import OutputRefusedError
from solidseas.export import write_new
from solidseas.formats import Limits, open_model
from solidseas.formats._source import Source
from solidseas.formats.step import product
from solidseas.formats.step.part21 import decode_string
from solidseas.formats.step.schema import census


def test_escapes_still_decode():
    assert decode_string(b"caf\\X2\\00E9\\X0\\") == "café"
    assert decode_string(b"\\X4\\0001F600\\X0\\") == "\U0001f600"
    assert decode_string(b"\\X2\\00e9\\X0\\") == "é"  # lower-case hex is accepted


@pytest.mark.parametrize(
    ("raw", "kept"),
    [
        (b"a\\X2\\00E9", "a\\X2\\00E9"),  # never closed
        (b"\\X2\\00E\\X0\\", "\\X2\\00E\\X0\\"),  # not a whole code unit
        (b"\\X2\\00G9\\X0\\", "\\X2\\00G9\\X0\\"),  # not hex
    ],
)
def test_an_invalid_escape_is_kept_as_stored(raw, kept):
    assert decode_string(raw) == kept


def test_many_unclosed_escapes_decode_in_linear_time():
    raw = b"\\X2\\A" * 200_000  # 1 MB of escapes, none closed
    started = time.monotonic()
    assert decode_string(raw) == "\\X2\\A" * 200_000
    assert time.monotonic() - started < 10


def test_a_record_full_of_unit_words_is_read_once():
    record = b"#1=FOO(" + b"SI_UNIT " * 500_000 + b");\n"  # 4 MB, one record
    text = b"#2=SI_UNIT(.MILLI.,.METRE.);\n" + record
    started = time.monotonic()
    out = census(Source(text), 0, Limits())
    assert time.monotonic() - started < 10
    assert out.complete


def _grid(k: int) -> tuple[float, float, float]:
    return (20.0 * (k % 25), 20.0 * (k // 25), 0.0)


def _mm(placement) -> tuple[float, ...]:
    return tuple(round(c * 1000.0, 6) for c in placement.translation_m)


def _box_and_top(f):
    ctx = f.units()
    part = f.product("box part")
    rep, _geo = f.shape(part, [W.box_brep(f, (10, 10, 10))], ctx)
    top = f.product("top")
    pds = f.add(f"PRODUCT_DEFINITION_SHAPE('','',#{top})")
    rmap = f.add(f"REPRESENTATION_MAP(#{f.axis2()},#{rep})")
    return ctx, part, rep, top, pds, rmap


def _placed_both_ways(n: int, elsewhere: int = 0) -> bytes:
    """A box placed n times by NAUOs whose relationships carry the transformation, and
    again by a MAPPED_ITEM in the assembly's shape at each place, the mapped items stored in
    the reverse order; ``elsewhere`` more mapped items place it where no occurrence is."""
    f = W.P21()
    ctx, part, rep, top, pds, rmap = _box_and_top(f)
    places = [_grid(k) for k in range(n)]
    extra = [(-50.0 - 20.0 * k, 0.0, 0.0) for k in range(elsewhere)]
    items = [f.add(f"MAPPED_ITEM('m',#{rmap},#{f.axis2(at)})") for at in places[::-1] + extra]
    top_rep = f.add(f"SHAPE_REPRESENTATION('',({','.join(f'#{m}' for m in items)}),#{ctx})")
    f.add(f"SHAPE_DEFINITION_REPRESENTATION(#{pds},#{top_rep})")
    for k, at in enumerate(places):
        f.occurrence(top, part, top_rep, rep, at=at, name=f"box {k}")
    return f.bytes()


def _placed_beside(n: int) -> bytes:
    """A box placed n times by MAPPED_ITEMs held in one representation beside the
    assembly's, each NAUO's context-dependent shape representation over a relationship with
    no transformation between the two."""
    f = W.P21()
    ctx, part, _rep, top, pds, rmap = _box_and_top(f)
    top_rep = f.add(f"SHAPE_REPRESENTATION('',(#{f.axis2()}),#{ctx})")
    f.add(f"SHAPE_DEFINITION_REPRESENTATION(#{pds},#{top_rep})")
    items = [f.add(f"MAPPED_ITEM('m{k}',#{rmap},#{f.axis2(_grid(k))})") for k in range(n)]
    shared = f.add(f"SHAPE_REPRESENTATION('',({','.join(f'#{m}' for m in items)}),#{ctx})")
    for k in range(n):
        nauo = f.add(f"NEXT_ASSEMBLY_USAGE_OCCURRENCE('{k}','box {k}','',#{top},#{part},$)")
        npds = f.add(f"PRODUCT_DEFINITION_SHAPE('','',#{nauo})")
        rr = f.add(f"SHAPE_REPRESENTATION_RELATIONSHIP('','',#{shared},#{top_rep})")
        f.add(f"CONTEXT_DEPENDENT_SHAPE_REPRESENTATION(#{rr},#{npds})")
    return f.bytes()


def test_mapped_items_that_repeat_placed_occurrences_are_matched_without_a_scan(monkeypatch):
    """Each mapped item that repeats an occurrence its relationship already places is found
    through an index of the placements, not by comparing it with every one of them (n * n / 4
    comparisons on this file, 40,000); the mapped items that place the box elsewhere are kept
    as further occurrences and warned, as before."""
    calls: Counter = Counter()
    same = product._same

    def counted(a, b):
        calls["same"] += 1
        return same(a, b)

    monkeypatch.setattr(product, "_same", counted)
    n = 400
    with open_model(_placed_both_ways(n, elsewhere=3), name="t.step") as doc:
        s = doc.scene()
        assert doc._model.structure.ambiguous == 3
        assert "placement_ambiguous" in {w.code for w in doc.warnings}
    expected = [_grid(k) for k in range(n)] + [(-50.0 - 20.0 * k, 0.0, 0.0) for k in range(3)]
    assert sorted(_mm(it.placement) for it in s.items) == sorted(expected)
    assert calls["same"] <= 2 * n


def test_placements_of_round_values_are_looked_for_in_one_cell():
    quarter = ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    for at in ((0.0, 0.0, 0.0), (0.02, 0.5, -1.25), (1e3, 0.0, 0.0)):
        for rot in (product.IDENTITY.rotation, quarter):
            assert len(product._PlacementIndex.near(product._values(product.Placement(rot, at)))) == 1


def test_a_placement_on_a_cell_edge_is_matched_from_the_cell_beside(monkeypatch):
    """The index files placements on a grid much coarser than the 1e-12 a match allows: two
    placements that straddle a cell's edge still match, and one past the tolerance does not."""
    monkeypatch.setattr(product, "PLACEMENT_CELL", 1e-3)
    edge = 2.5e-3  # metres, on the edge between the cells about 2 mm and 3 mm
    rot = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    index = product._PlacementIndex(
        [product.Placement(rot, (edge - 4e-13, 0.0, 0.0)), product.Placement(rot, (edge + 4e-13, 0.0, 0.0))]
    )
    assert index.take(product.Placement(rot, (edge + 4e-13, 0.0, 0.0)))
    assert index.take(product.Placement(rot, (edge + 4e-13, 0.0, 0.0)))  # the other, beside it
    assert not index.take(product.Placement(rot, (edge, 0.0, 0.0)))  # both taken
    index = product._PlacementIndex([product.Placement(rot, (edge, 0.0, 0.0))])
    assert not index.take(product.Placement(rot, (edge + 3e-12, 0.0, 0.0)))
    assert not index.take(product.Placement(rot, (float("nan"), 0.0, 0.0)))
    assert index.take(product.Placement(rot, (edge, 0.0, 0.0)))


def test_the_first_placement_that_matches_is_taken_first():
    rot = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    a = product.Placement(rot, (0.0, 0.0, 0.0))
    b = product.Placement(rot, (5e-13, 0.0, 0.0))
    index = product._PlacementIndex([b, a, b])
    assert index.take(a) and index.placements == [b, a, b]
    assert list(index.cells[next(iter(index.cells))]) == [1, 2]  # the first, b, went first


def test_mapped_items_beside_their_relationships_are_read_once(monkeypatch):
    """Every occurrence takes the next mapped item of the one representation that holds
    them all, as before; that representation is read once, not once for each occurrence,
    so twice the occurrences cost twice the reads (four times when it was read for each)."""
    reads: Counter = Counter()
    rec = product.Reader.rec

    def counted(self, ref):
        reads["rec"] += 1
        return rec(self, ref)

    monkeypatch.setattr(product.Reader, "rec", counted)
    cost = {}
    for n in (200, 400):
        reads.clear()
        with open_model(_placed_beside(n), name="t.step") as doc:
            nodes = [nd for nd in doc.tree().nodes if nd.kind == "component"]
            assert [nd.name for nd in nodes] == [f"box {k}" for k in range(n)]
            assert [_mm(nd.placement) for nd in nodes] == [_grid(k) for k in range(n)]
            assert not {w.code for w in doc.warnings} & {"placement_unresolved", "placement_ambiguous"}
        cost[n] = reads["rec"]
    assert cost[400] < 2.5 * cost[200]


def test_the_library_never_writes_a_solidworks_file(tmp_path):
    source = tmp_path / "part.SLDPRT"
    source.write_bytes(b"original")
    for name in ("part.SLDPRT", "new.sldasm", "tmpl.prtdot"):
        with pytest.raises(OutputRefusedError) as caught:
            write_new(tmp_path / name, lambda fh: fh.write(b"x"), overwrite=True)
        assert caught.value.detail == {"rule": "solidworks_file"}
    assert source.read_bytes() == b"original"
    assert not (tmp_path / "new.sldasm").exists()
