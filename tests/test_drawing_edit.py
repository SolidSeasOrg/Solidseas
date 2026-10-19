"""Editing a drawing (docs/DRAWINGS.md 10.12, 13.2, 13.5): each operation changes the
drawing's records and lays the sheet out again from the model, the user's edits
survive regeneration, a drawing without its model is view-only, a released one
refuses edits, and an edit stays quick."""

import time

import pytest

import drawing_parts as P
from drawing_support import fixture
from solidseas import drawing
from solidseas.drawing import display as D
from solidseas.drawing import edit, facegraph, pipeline, release
from solidseas.drawing import settings as S
from solidseas.drawing import types as T
from solidseas.drawing.types import DrawingOptions, FrameCell
from solidseas.errors import InvalidArgumentError, UnsupportedOperationError

TODAY = "2026-10-04"


def people():
    s = S.with_value(S.DrawingSettings(), "company", "name", "Example Engineering Co.")
    return S.with_value(
        s, "people", "people", [{"name": "Ann Bee", "initials": "AB"}, {"name": "Carl Dee", "initials": "CD"}]
    )


def made(name="o02_boxA.SLDPRT", **kw):
    kw.setdefault(
        "fields", {"number": "SS-1", "drawn_by": "Ann Bee", "material": "6061-T6", "finish": "None"}
    )
    return drawing.make_drawing(fixture(name), settings=people(), **kw)


class _Source:
    configuration = None
    format = "sldprt"
    material = None
    sha256 = "ab" * 32
    geometry_digest = "cd" * 32
    properties_digest = None
    units = None
    warnings = ()
    hints = ()
    properties = ()

    def __init__(self, name):
        self.name = name

    def property(self, *names):
        return None

    def selected_bodies(self):
        return []


def synthetic(builder, name="PART.SLDPRT", **kw):
    """A drawing of a synthetic part through every real stage but the source and model."""
    m = facegraph.from_transmit(builder()[0])
    stages = {"source": lambda part, **_k: _Source(name), "model": lambda bodies, **_k: m}
    kw.setdefault("options", DrawingOptions(units="mm"))
    return pipeline.run(name, stages=stages, settings=people(), **kw).drawing


def dim(d, key):
    return next(x for x in d.dimensions if x.key == key)


def annotation(d, ident):
    return next((a for a in d.sheet.annotations if isinstance(a, D.Dimension) and a.id == ident), None)


def texts(d, owner=None):
    return [
        i.text for i in d.sheet.painted if isinstance(i, D.TextRun) and (owner is None or i.owner == owner)
    ]


# ---------------------------------------------------------------------- the model kept beside a drawing


def test_a_new_drawing_is_laid_out_from_its_records():
    d = made()
    drawn = next(s for s in d.signatures if s.row == "DRAWN")
    assert "INITIAL RELEASE" in texts(d) and drawn.date in texts(d)  # the revision row and DRAWN's date
    again, checks = edit.relayout(d)
    assert again.sheet == d.sheet and again.dimensions == d.dimensions
    assert checks == again.checks and edit.live_for(d) is not None


def test_an_edit_needs_the_model(tmp_path):
    d = made()
    path = tmp_path / "box.ssdrw"
    drawing.save(d, str(path))
    back = drawing.load(str(path))
    edit.forget(back)
    with pytest.raises(InvalidArgumentError) as info:
        edit.remove(back, "d-1")
    assert info.value.detail["rule"] == "model_not_found"
    edit.attach(back, fixture("o02_boxA.SLDPRT"))
    again, _checks = edit.relayout(back)
    assert again.sheet == d.sheet
    edit.forget(back)
    edit.attach(back, fixture("o03_boxA_again.SLDPRT"))  # saved again, its geometry unchanged
    resaved, _checks = edit.remove(back, "d-1")
    assert dim(resaved, "size/f-1").state == "removed"
    edit.forget(back)
    with pytest.raises(InvalidArgumentError) as info:
        edit.attach(back, fixture("o07_boxB_h31.SLDPRT"))
    assert info.value.detail["rule"] == "model_changed"
    with pytest.raises(InvalidArgumentError) as info:
        edit.attach(back)
    assert info.value.detail["rule"] == "model_not_found"


def test_the_kept_runs_are_bounded():
    before = dict(edit._LIVE)
    try:
        for k in range(edit.MAX_LIVE + 3):
            edit._keep(f"probe-{k}", edit.Live(None, None, None, ()))
        assert len(edit._LIVE) == edit.MAX_LIVE and "probe-0" not in edit._LIVE
    finally:
        edit._LIVE.clear()
        edit._LIVE.update(before)


# ---------------------------------------------------------------------- dimensions


def test_remove_restore_and_delete():
    d = made()
    first = dim(d, "size/f-1")
    removed, _c = edit.remove(d, first.id)
    assert dim(removed, "size/f-1").state == "removed" and annotation(removed, first.id) is None
    back, _c = edit.restore(removed, first.id)
    assert back.sheet == d.sheet and back.dimensions == d.dimensions
    with pytest.raises(InvalidArgumentError):
        edit.restore(d, first.id)  # not removed
    with pytest.raises(InvalidArgumentError):
        edit.delete(d, first.id)  # generated: remove it instead
    with pytest.raises(InvalidArgumentError):
        edit.remove(d, "d-999")


def test_link_origin_and_scheme_replan_the_locations():
    d = synthetic(P.four_holes_plate, "FOUR-HOLES.SLDPRT")
    assert dim(d, "loc/f-2/x").value == pytest.approx(0.037)
    linked, _c = edit.link(d, "f-1", "f-2", "x")
    loc = dim(linked, "loc/f-2/x")
    assert loc.id == dim(d, "loc/f-2/x").id and loc.value == pytest.approx(0.025)  # from f-1 at X 12
    assert ("link_x", "f-1") in dict((f.id, f.decisions) for f in linked.features)["f-2"]
    with pytest.raises(InvalidArgumentError) as info:
        edit.link(linked, "f-2", "f-1", "x")
    assert info.value.detail["rule"] == "loop"
    unlinked, _c = edit.unlink(linked, "f-2", "x")
    assert dim(unlinked, "loc/f-2/x").value == pytest.approx(0.037)

    moved, _c = edit.set_origin(d, "x", "f-1")
    xs = {x.key: x.value for x in moved.dimensions if x.axis == "x" and x.role == "feature_location"}
    assert "loc/f-1/x" not in xs and xs["loc/f-3/x"] == pytest.approx(0.059)
    back, _c = edit.set_origin(moved, "x", None)
    assert {x.key for x in back.dimensions} == {x.key for x in d.dimensions}

    assert {x.kind for x in d.dimensions if x.role == "feature_location"} == {"ordinate"}
    based, _c = edit.set_scheme(d, "v-1", "x", "baseline")
    kinds = {x.axis: x.kind for x in based.dimensions if x.role == "feature_location"}
    assert kinds == {"x": "linear", "y": "ordinate"}
    with pytest.raises(InvalidArgumentError):
        edit.set_scheme(d, "v-1", "x", "chain")


def test_add_dimension_from_the_candidates():
    d = synthetic(P.four_holes_plate, "FOUR-HOLES.SLDPRT")
    offered = edit.candidates(d, ["f-1", "f-2"])
    assert [(c.kind, c.axis) for c in offered] == [("distance", "x"), ("distance", "y")]
    assert offered[0].value == pytest.approx(0.025) and "25.00" in offered[0].words
    added, _c = edit.add(d, offered[0])
    user = [x for x in added.dimensions if x.origin == "user"]
    assert len(user) == 1 and user[0].key == "user/distance/f-1/f-2/x" and annotation(added, user[0].id)
    assert dict(added.next_id)["d"] == dict(d.next_id)["d"] + 1
    assert all(c.key != user[0].key for c in edit.candidates(added, ["f-1", "f-2"]))
    with pytest.raises(InvalidArgumentError):
        edit.remove(added, user[0].id)  # a user dimension is deleted
    gone, _c = edit.delete(added, user[0].id)
    assert gone.sheet == d.sheet
    removed, _c = edit.remove(d, dim(d, "loc/f-1/x").id)
    restore = [c for c in edit.candidates(removed, ["f-1"]) if c.kind == "restore"]
    assert restore and restore[0].dimension == dim(d, "loc/f-1/x").id
    back, _c = edit.add(removed, restore[0])
    assert back.sheet == d.sheet
    with pytest.raises(InvalidArgumentError):
        edit.candidates(d, ["f-1", "f-2", "f-3"])


def test_a_depth_from_the_floor():
    d = synthetic(P.pocket_tab_block, "BLOCK.SLDPRT")
    depth = dim(d, "depth/f-1")
    floor, _c = edit.set_depth_reference(d, "f-1", "floor")
    under = dim(floor, "depth/f-1")
    lo, hi = d.model["extents"]["xyz".index(depth.axis)]
    assert under.id == depth.id and depth.value + under.value == pytest.approx(hi - lo)
    back, _c = edit.set_depth_reference(floor, "f-1", "open")
    assert dim(back, "depth/f-1").value == pytest.approx(depth.value)


def test_tolerance_precision_text_and_override():
    d = made()
    size = dim(d, "size/f-1")
    tol, _c = edit.set_tolerance(d, size.id, "symmetric", 0.1)
    assert dim(tol, "size/f-1").tolerance == "symmetric" and "user_tolerance" in dim(tol, "size/f-1").flags
    assert any("±" in t for t in texts(tol, size.id))
    back, _c = edit.set_tolerance(tol, size.id, "block")
    assert back.sheet == d.sheet
    with pytest.raises(InvalidArgumentError):
        edit.set_tolerance(d, size.id, "symmetric", 0.0)
    fine, _c = edit.set_precision(d, size.id, 3)
    assert dim(fine, "size/f-1").places == 3 and any("10.000" in t for t in texts(fine, size.id))
    again, _c = edit.set_precision(fine, size.id, None)
    assert again.sheet == d.sheet
    two, _c = edit.set_prefix(d, size.id, "2X ")
    two, _c = edit.set_suffix(two, size.id, ["REF"])
    assert any(t.startswith("2X") for t in texts(two, size.id)) and "REF" in texts(two, size.id)
    plain, _c = edit.reset_text(two, size.id)
    assert plain.sheet == d.sheet
    shown, _c = edit.override_value(d, size.id, "10.5")
    assert dim(shown, "size/f-1").override == "10.5" and any("10.5" in t for t in texts(shown, size.id))
    off, _c = edit.override_value(shown, size.id, None)
    assert off.sheet == d.sheet
    with pytest.raises(InvalidArgumentError):
        edit.set_prefix(d, size.id, "a\nb")


def test_frames_and_datums():
    d = made("o11_curved.SLDPRT")
    callout = next(x for x in d.dimensions if x.kind == "hole_callout")
    frame = FrameCell("position", 0.0002, True, "mmc", ("A", "B"))
    framed, _c = edit.set_frame(d, callout.id, frame)
    assert dim(framed, callout.key).frame == frame and "user_frame" in dim(framed, callout.key).flags
    planner, _c = edit.reset_frame(framed, callout.id)
    assert planner.sheet == d.sheet
    with pytest.raises(InvalidArgumentError):
        edit.set_frame(d, callout.id, FrameCell("position", 0.0002, True, None, ("Q",)))
    c_face = next(x.face for x in d.datums if x.letter == "C")
    off, _c = edit.set_datum(d, "C", None)
    assert [x.letter for x in off.datums] == ["A", "B"]
    on, _c = edit.set_datum(off, "C", c_face)
    assert {x.letter: x.face for x in on.datums}["C"] == c_face
    with pytest.raises(InvalidArgumentError):
        edit.set_datum(d, "I", c_face)


def test_move_flip_and_reset():
    d = made()
    size = dim(d, "size/f-1")
    at = annotation(d, size.id)
    moved, _c = edit.move(d, size.id, 5.0, 4.0)
    m = annotation(moved, size.id)
    assert dim(moved, "size/f-1").placement.moved and m.text_at != at.text_at
    assert edit.reset_position(moved, size.id)[0].sheet == d.sheet
    flipped, _c = edit.flip(d, size.id)
    f = annotation(flipped, size.id)
    side = dim(flipped, "size/f-1").side
    assert side in ("above", "below", "left", "right") and f.points[2] != at.points[2]
    assert edit.reset_position(flipped, size.id)[0].sheet == d.sheet


def test_sheet_scale_units_and_views():
    d = made()
    big, _c = edit.set_sheet(d, "C")
    assert big.sheet.name == "C" and big.options.sheet == "C"
    half, _c = edit.set_scale(d, (1, 2))
    assert half.sheet.scale == (1, 2)
    inch, _c = edit.set_units(d, "in")
    assert inch.options.units == "in" and any(t.startswith(".") for t in texts(inch, dim(d, "size/f-1").id))
    with pytest.raises(InvalidArgumentError):
        edit.set_sheet(d, "F")
    more, _c = edit.add_view(d, "left")
    assert "left" in more.options.views and len(more.sheet.views) >= len(d.sheet.views)
    fewer, _c = edit.remove_view(more, "left")
    assert "left" not in fewer.options.views
    with pytest.raises(UnsupportedOperationError) as info:
        edit.add_view(d, "section")
    assert info.value.detail["rule"] == "later_release"
    with pytest.raises(InvalidArgumentError):
        edit.remove_view(d, "front")


def test_notes_title_and_the_tolerance_block():
    d = made()
    notes = [n.text for _i, n in d.notes]
    edited, _c = edit.edit_notes(d, [*notes, "DEBURR ALL EDGES"])
    assert [i for i, _n in edited.notes][: len(notes)] == [i for i, _n in d.notes]
    assert edited.notes[-1][1].origin == "user" and "DEBURR ALL EDGES" in " ".join(texts(edited))
    titled, _c = edit.set_title(d, "title", "BOX, TEST")
    assert dict(titled.title)["title"].text == "BOX, TEST" and "BOX, TEST" in texts(titled)
    with pytest.raises(InvalidArgumentError):
        edit.set_title(d, "colour", "RED")
    block, _c = edit.set_tolerance_block(d, [(1, 0.5), (2, 0.1)])
    assert block.settings.tolerances.mm_block == ((1, 0.5), (2, 0.1))
    with pytest.raises(UnsupportedOperationError):
        edit.add_flag_note(d, "NOTE", ["d-1"])


def test_the_title_block_is_lettered_in_capitals_and_a_finish_of_the_list_by_its_callout():
    d = made()  # its finish typed as None
    assert dict(d.title)["finish"] == T.TitleField("NONE", "list")
    clear, _c = edit.set_title(d, "finish", "clear  ANODIZE")
    anodize = "ANODIZE PER MIL-A-8625, TYPE II, CLASS 1, CLEAR"
    assert dict(clear.title)["finish"] == T.TitleField(anodize, "list")
    typed, _c = edit.set_title(d, "title", "Box, test")
    assert dict(typed.title)["title"] == T.TitleField("Box, test", "typed")  # kept as typed
    assert "BOX, TEST" in texts(typed, "title") and "Box, test" not in texts(typed)
    named = made(fields={"drawn_by": "Ann Bee", "material": "6061-T6", "finish": "None"})
    (tb,) = [a for a in named.sheet.annotations if isinstance(a, D.TitleBlock)]
    fields = dict(tb.fields)
    assert fields["number"] == "O02_BOXA"  # the part's file name, in capitals
    model = fields["model"]
    assert model.startswith("o02_boxA ") and model in texts(named, "title")  # as the file is


def test_a_confirmed_thread_is_called_out():
    d = made("o11_curved.SLDPRT")
    hole = next(f.id for f in d.features if f.descriptor.type == "Hole")
    tapped, _c = edit.confirm_thread(d, hole, "m12x1.75-6h")
    callout = next(x for x in tapped.dimensions if x.kind == "hole_callout")
    assert "M12X1.75-6H THRU" in callout.suffix
    plain, _c = edit.confirm_thread(tapped, hole, None)
    assert plain.sheet == d.sheet  # answered plain: no thread, and the answer kept
    assert ("thread", None) in dict((f.id, f.decisions) for f in plain.features)[hole]
    open_again, _c = edit.clear_thread(plain, hole)
    assert "thread" not in dict(dict((f.id, f.decisions) for f in open_again.features)[hole])
    with pytest.raises(InvalidArgumentError):
        edit.confirm_thread(d, hole, "M12;rm")


# ---------------------------------------------------------------------- status


def test_signing_release_and_a_new_revision():
    d = made()
    checked, _c = edit.sign(d, "CHECKED", "Carl Dee", TODAY)
    assert checked.status == "CHECKED" and "Carl Dee" in texts(checked)
    edited, _c = edit.set_precision(checked, dim(d, "size/f-1").id, 3)
    assert edited.status == "PRELIMINARY" and all(s.row != "CHECKED" for s in edited.signatures)
    signed, _c = edit.sign(checked, "APPROVED", "Ann Bee", TODAY)
    with pytest.raises(release.ReleaseRefusedError):
        edit.release_drawing(d, TODAY)  # nobody checked or approved it
    released, _c = edit.release_drawing(signed, TODAY)
    assert released.status == "RELEASED" and not any(
        isinstance(a, D.Stamp) for a in released.sheet.annotations
    )
    with pytest.raises(InvalidArgumentError) as info:
        edit.remove(released, "d-1")
    assert info.value.detail["rule"] == "drawing_released"
    opened, _c = edit.start_revision(released, "HEIGHT CHANGED", drawn_by="Ann Bee", today=TODAY)
    assert opened.status == "PRELIMINARY" and [r.rev for r in opened.revisions] == ["A", "B"]
    assert any(isinstance(a, D.Stamp) for a in opened.sheet.annotations)


# ---------------------------------------------------------------------- regeneration (13.5)


def test_edits_survive_update_from_model():
    d = made()
    a, b = dim(d, "size/f-1"), dim(d, "size/f-2")
    d, _c = edit.remove(d, a.id)
    d, _c = edit.move(d, b.id, 3.0, 6.0)
    merged, report = drawing.regenerate(d, fixture("o07_boxB_h31.SLDPRT"))
    assert report.changed >= 1 and dim(merged, a.key).state == "removed" and annotation(merged, a.id) is None
    kept = dim(merged, b.key)
    assert kept.id == b.id and kept.placement.moved and annotation(merged, b.id) is not None
    again, _c = edit.restore(merged, a.id)  # the merged drawing is editable at once
    assert annotation(again, a.id) is not None


def test_edits_are_deterministic():
    one = made()
    two = made()
    assert one.id != two.id and one.sheet == two.sheet
    a, _c = edit.move(one, "d-2", 2.0, 1.0)
    b, _c = edit.move(two, "d-2", 2.0, 1.0)
    assert a.sheet == b.sheet and a.dimensions == b.dimensions


def test_an_edit_lays_out_quickly():
    xt, _truth = P.random_plate(3, n=100)
    m = facegraph.from_transmit(xt)
    stages = {"source": lambda part, **_k: _Source("PLATE.SLDPRT"), "model": lambda bodies, **_k: m}
    d = pipeline.run("PLATE.SLDPRT", stages=stages, options=DrawingOptions(units="mm")).drawing
    loc = next(x for x in d.dimensions if x.role == "feature_location")
    t0 = time.perf_counter()
    removed, _c = edit.remove(d, loc.id)
    took = time.perf_counter() - t0
    assert len(d.dimensions) >= 190 and dim(removed, loc.key).state == "removed"
    assert took < 0.9  # the target is 0.3 s (21 item 6); measured about 0.25 s here


def test_a_released_drawing_refuses_every_edit():
    d = made()
    d, _c = edit.sign(d, "CHECKED", "Carl Dee", TODAY)
    d, _c = edit.sign(d, "APPROVED", "Ann Bee", TODAY)
    released, _c = edit.release_drawing(d, TODAY)
    size = dim(released, "size/f-1").id
    for op, args in (
        (edit.set_precision, (size, 3)),
        (edit.move, (size, 1.0, 1.0)),
        (edit.set_units, ("in",)),
        (edit.edit_notes, ([],)),
        (edit.confirm_thread, ("f-1", "M6")),
    ):
        with pytest.raises(InvalidArgumentError) as info:
            op(released, *args)
        assert info.value.detail["rule"] == "drawing_released"
    assert edit.relayout(released)[0].sheet == released.sheet  # laying it out again changes nothing


# ---------------------------------------------------------------------- the file and the title block


def test_a_full_round_end_keeps_its_r_through_the_file(tmp_path):
    d = synthetic(P.link_plate, "LINK.SLDPRT")
    derived = [x for x in d.dimensions if x.tolerance == "derived"]
    assert derived  # 2X R on the full-round ends, without a value (convention 5)
    path = tmp_path / "link.ssdrw"
    drawing.save(d, str(path))
    back = drawing.load(str(path))
    assert [x.tolerance for x in back.dimensions] == [x.tolerance for x in d.dimensions]
    assert [f.descriptor for f in back.features] == [f.descriptor for f in d.features]


def test_a_new_reference_keeps_the_title_taken_from_the_name():
    d = made(fields={"drawn_by": "Ann Bee", "material": "6061-T6", "finish": "None"})
    title = dict(d.title)
    assert title["number"].text == "O02_BOXA" and title["number"].source == "part"
    same, report = drawing.regenerate(d, fixture("o03_boxA_again.SLDPRT"))
    assert report.geometry_unchanged
    after = dict(same.title)
    assert after["number"].text == "O03_BOXA_AGAIN" and after["title"].text == "O03_BOXA_AGAIN"


def test_the_proprietary_statement_names_the_company_and_is_whole():
    d = made()
    words = " ".join(texts(d, "title"))
    assert "{company}" not in words and "EXAMPLE ENGINEERING CO." in words
    small, _c = edit.set_sheet(d, "A")
    assert "PERMISSION." in " ".join(texts(small, "title"))


def test_a_released_drawing_is_revised_from_its_changed_model():
    d = made()
    d, _c = edit.sign(d, "CHECKED", "Carl Dee", TODAY)
    d, _c = edit.sign(d, "APPROVED", "Ann Bee", TODAY)
    released, _c = edit.release_drawing(d, TODAY)
    edit.forget(released)  # the model has changed: its run is gone
    with pytest.raises(InvalidArgumentError) as info:
        edit.start_revision(released, "HEIGHT CHANGED")
    assert info.value.detail["rule"] == "model_not_found"
    with pytest.raises(InvalidArgumentError) as info:
        drawing.regenerate(released, fixture("o07_boxB_h31.SLDPRT"))
    assert info.value.detail["rule"] == "drawing_released"
    revised, report = drawing.regenerate(
        released, fixture("o07_boxB_h31.SLDPRT"), revision="HEIGHT CHANGED", drawn_by="Ann Bee", today=TODAY
    )
    assert revised.status == "PRELIMINARY" and [r.rev for r in revised.revisions] == ["A", "B"]
    assert report.changed >= 1 and any(isinstance(a, D.Stamp) for a in revised.sheet.annotations)
    moved, _c = edit.move(revised, dim(revised, "size/f-1").id, 1.0, 1.0)  # editable at once
    assert moved.status == "PRELIMINARY"
    same, report = drawing.regenerate(
        released, fixture("o02_boxA.SLDPRT"), revision="NOTES CHANGED", today=TODAY
    )
    assert report.model_unchanged and same.status == "PRELIMINARY"
    assert any(isinstance(a, D.Stamp) for a in same.sheet.annotations)  # laid out again, stamped
