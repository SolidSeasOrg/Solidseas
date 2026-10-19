"""Regeneration that keeps the user's edits (docs/DRAWINGS.md 13.4, 13.5; dwg-file):
ids inherited through matching, state, placement and overrides kept, new and dropped
requirements, user dimensions needing attention, datums, title fields, signatures,
and the report; then regenerate on the o02, o03 and o07 fixtures."""

import shutil
from dataclasses import replace

import pytest

from drawing_support import fixture
from solidseas.drawing import display as D
from solidseas.drawing import document as doc
from solidseas.drawing import merge as G
from solidseas.drawing import pipeline, release
from solidseas.drawing import types as T
from solidseas.errors import InvalidArgumentError, UnsupportedOperationError
from test_drawing_file import (
    NOW,
    TODAY,
    compact_sheet,
    face_desc,
    feature_set,
    hand_source,
    hole_desc,
    made,
    people_settings,
)

MM = 0.001


def edited():
    """The drawing as a user left it: d-1 moved and its text overridden with its own
    precision, d-2 removed, a user dimension d-3 between the face and the hole, a
    typed note, and signed CHECKED."""
    d = made()
    d1, d2 = d.dimensions
    d1 = replace(
        d1,
        placement=doc.Placement(2.0, 14.0, 2, True),
        override="20.00 BASIC",
        places=4,
        places_source="user",
    )
    d2 = replace(d2, state="removed")
    user = doc.DimensionRecord(
        "dist/f-1/f-2/z", "d-3", "linear", "v-2", 0.01, axis="z", features=("f-1", "f-2"), origin="user"
    )
    notes = (*d.notes, ("n-2", doc.NoteRecord("DEBURR THE BORE", (), "user")))
    d = replace(d, dimensions=(d1, d2, user), notes=notes, next_id=(("f", 3), ("d", 4), ("n", 3), ("v", 3)))
    d, _w = release.sign(d, "CHECKED", "Carl Dee", TODAY)
    return d


def new_run(features, dims, *, sha="9" * 64, geometry="8" * 64, properties=None, datums=None, title=None):
    """A new run's drawing: its own feature numbering, plan and sheet."""
    src = hand_source(sha256=sha, geometry_digest=geometry)
    if properties is not None:
        src = replace(src, properties=properties)
    plan = T.Plan(
        views=(T.ViewSpec("v-1", "base", (0.0, 0.0, 1.0), (0.0, 1.0, 0.0), name="front"),),
        dimensions=dims,
        datums=datums if datums is not None else (T.Datum("A", 0, "largest planar face"),),
        notes=(T.NoteLine("A NEW TEMPLATE NOTE"),),
    )
    annotations = tuple(
        D.Dimension(x.id, x.kind, x.view, ((0.0, 0.0),), (1.0, 1.0), x.value, D.DimText("v")) for x in dims
    )
    painted = tuple(D.Stroke((("M", 0.0, 0.0), ("L", 1.0, 1.0)), 0.3, (), "dimensions", x.id) for x in dims)
    sheet = replace(compact_sheet(), annotations=annotations, painted=painted)
    return doc.new_drawing(
        src,
        (plan, sheet),
        T.DrawingOptions(),
        people_settings(),
        title or {"title": "BRACKET, NEW RUN"},
        features=feature_set(*features),
        seed="new",
        now=NOW,
    )


def dims_for(hole_x=0.02, extra=False):
    """The new run's plan: its f-1 is the hole and f-2 the face (recognised the other way
    round), with a second hole f-3 when ``extra``."""
    out = [
        T.PlannedDimension("loc/f-1/x", "d-1", "linear", "v-1", hole_x, axis="x", features=("f-1",)),
        T.PlannedDimension("size/f-1", "d-2", "diameter", "v-1", 0.005, features=("f-1",)),
    ]
    if extra:
        out.append(T.PlannedDimension("loc/f-3/x", "d-3", "linear", "v-1", 0.06, axis="x", features=("f-3",)))
    return tuple(out)


def moved_hole_run(hole_x=0.021, extra=True):
    features = [(hole_desc(hole_x, 0.025), (5, 6)), (face_desc("z", 0.0, "-"), (0,))]
    if extra:
        features.append((hole_desc(0.06, 0.025), (7, 8)))
    return new_run(features, dims_for(hole_x, extra))


# --------------------------------------------------------------------------- merge


def test_ids_state_placement_and_overrides_are_inherited():
    old = edited()
    merged, report = G.merge(old, moved_hole_run())
    assert [f.id for f in merged.features] == ["f-2", "f-1", "f-3"]  # the new run's order, the old ids
    assert dict(merged.features[1].decisions) == {"datum": "A"}
    by_id = {x.id: x for x in merged.dimensions}
    d1 = by_id["d-1"]
    assert d1.key == "loc/f-2/x" and d1.value == 0.021
    assert d1.placement == doc.Placement(2.0, 14.0, 2, True) and d1.override == "20.00 BASIC"
    assert (d1.places, d1.places_source) == (4, "user") and "changed" in d1.flags
    assert by_id["d-2"].state == "removed" and by_id["d-2"].key == "size/f-2"
    assert by_id["d-4"].key == "loc/f-3/x" and "new" in by_id["d-4"].flags  # the next free id
    assert by_id["d-3"].origin == "user" and by_id["d-3"].flags == ()  # its features are both there
    assert dict(merged.next_id) == {"f": 4, "d": 5, "n": 3, "v": 3}
    assert report.words() == "2 unchanged, 1 changed, 1 new, 0 dropped, 0 needs attention"
    assert report.features_new == ("f-3",) and report.features_gone == ()


def test_the_sheet_takes_the_merged_ids_and_drops_removed_dimensions():
    merged, _r = G.merge(edited(), moved_hole_run())
    ids = {a.id for a in merged.sheet.annotations if isinstance(a, D.Dimension)}
    assert ids == {"d-1", "d-4"}  # d-2 is removed, the user's d-3 waits for layout
    assert {p.owner for p in merged.sheet.painted} == {"d-1", "d-4"}


def test_notes_and_typed_fields_stay_and_part_fields_follow_the_part():
    old = edited()
    props = (("PartNo", "1234-002"), ("Description", "BRACKET"), ("Revision", "A"))
    merged, report = G.merge(
        old,
        new_run(
            [(hole_desc(0.02, 0.025), (5,)), (face_desc("z", 0.0, "-"), (0,))], dims_for(), properties=props
        ),
    )
    assert merged.notes == old.notes
    title = dict(merged.title)
    assert title["title"] == T.TitleField("BRACKET, MOTOR MOUNT", "typed")
    assert title["part_number"] == T.TitleField("1234-002", "part")
    assert any("part_number follows the part: 1234-002" in i for i in report.items)
    assert merged.options == old.options and merged.settings == old.settings
    assert merged.revisions == old.revisions and merged.id == old.id


def test_signatures_the_merge_invalidates_are_cleared():
    old = edited()
    assert old.status == "CHECKED"
    merged, report = G.merge(old, moved_hole_run())
    assert merged.status == "PRELIMINARY" and [s.row for s in merged.signatures] == ["DRAWN"]
    assert "the edit cleared the CHECKED signature of Carl Dee" in report.items


def test_gone_features_drop_their_dimensions_and_flag_the_users():
    old = edited()
    old = replace(
        old,
        dimensions=(
            *old.dimensions,
            doc.DimensionRecord("size/f-9", "d-9", "radius", "v-1", 0.001, state="removed"),
        ),
    )
    # the hole is gone and only the face is left
    merged, report = G.merge(old, new_run([(face_desc("z", 0.0, "-"), (0,))], ()))
    by_id = {x.id: x for x in merged.dimensions}
    assert set(by_id) == {"d-3"}  # d-1 dropped, d-2 and d-9 removed and forgotten
    assert "needs_attention" in by_id["d-3"].flags
    assert report.words() == "0 unchanged, 0 changed, 0 new, 1 dropped, 1 needs attention"
    assert report.forgotten == 2 and report.features_gone == ("f-2",)
    assert any(i.startswith("d-1 (loc/f-2/x) was dropped") for i in report.items)
    assert any(i.startswith("d-3 (dist/f-1/f-2/z) needs attention") for i in report.items)
    assert not [a for a in merged.sheet.annotations if isinstance(a, D.Dimension)]  # left off the sheet
    assert release.release_problems(merged)[-1] == "dimension d-3 needs attention"


def test_a_datum_follows_its_face_and_is_never_re_picked():
    old = edited()
    # the new run would make the side face datum A (it is the largest now)
    side = face_desc("y", 0.0, "-")
    run = new_run(
        [(face_desc("z", 0.0, "-"), (0,)), (side, (1,)), (hole_desc(0.02, 0.025), (5,))],
        (),
        datums=(T.Datum("A", 1, "largest planar face"),),
    )
    assert dict(run.features[1].decisions) == {"datum": "A"}
    merged, report = G.merge(old, run)
    decisions = {f.id: dict(f.decisions) for f in merged.features}
    assert decisions["f-1"] == {"datum": "A"} and "datum" not in decisions["f-3"]
    assert any("would put datum A on f-3; it stays on f-1" in i for i in report.items)
    assert [(x.letter, x.reason) for x in merged.datums] == [("A", "largest planar face")]
    # and when its face is gone, the drawing asks for a new one
    merged, report = G.merge(
        old, new_run([(side, (1,)), (hole_desc(0.02, 0.025), (5,))], (), datums=(T.Datum("A", 1, "x"),))
    )
    assert merged.datums == () and report.attention == 2  # the datum and the user dimension on f-1
    assert "datum A's feature f-1 is gone: choose a new datum A" in report.items
    assert all("datum" not in dict(f.decisions) for f in merged.features)


def test_a_placement_whose_view_changed_is_reset_and_reported():
    old = edited()
    dims = (T.PlannedDimension("loc/f-1/x", "d-1", "linear", "v-2", 0.02, axis="x", features=("f-1",)),)
    merged, report = G.merge(
        old, new_run([(hole_desc(0.02, 0.025), (5,)), (face_desc("z", 0.0, "-"), (0,))], dims)
    )
    d1 = {x.id: x for x in merged.dimensions}["d-1"]
    assert d1.placement is None and "placement_reset" in d1.flags and d1.override == "20.00 BASIC"
    assert "d-1: its view or side changed, so its placement was reset" in report.items


def test_unchanged_geometry_only_takes_the_new_reference():
    old = edited()
    props = (("PartNo", "1234-001-B"),)
    run = new_run([(face_desc("z", 0.0, "-"), (0,))], (), geometry=old.model["geometry"], properties=props)
    merged, report = G.merge(old, run)
    assert report.geometry_unchanged and report.words() == G.GEOMETRY_UNCHANGED
    assert merged.model["sha256"] == "9" * 64 and merged.model["relative"] == old.model["relative"]
    assert merged.dimensions == old.dimensions and merged.features == old.features
    assert dict(merged.title)["part_number"].text == "1234-001-B"
    assert merged.status == "PRELIMINARY"  # the reference is content: CHECKED is cleared
    assert report.description() == "MODEL REFERENCE UPDATED, GEOMETRY UNCHANGED"
    same, report = G.merge(old, run := replace(run, model=dict(run.model, sha256=old.model["sha256"])))
    assert same is old and report.words() == G.MODEL_UNCHANGED


def test_a_released_drawing_must_start_a_revision_first():
    d = edited()
    d, _w = release.sign(d, "APPROVED", "Ann Bee", TODAY)
    d = release.release(d, TODAY)
    with pytest.raises(InvalidArgumentError) as info:
        G.merge(d, moved_hole_run())
    assert info.value.detail["rule"] == "drawing_released"
    with pytest.raises(InvalidArgumentError) as info:
        G.regenerate(d, new=moved_hole_run())
    assert info.value.detail["rule"] == "drawing_released"
    b = release.start_revision(d, "UPDATED FROM MODEL")
    merged, report = G.regenerate(b, new=moved_hole_run())
    assert report.changed == 1 and release.current_revision(merged) == "B"


def test_the_report_reads_the_same_everywhere():
    _m, report = G.merge(edited(), moved_hole_run())
    data = report.to_dict()
    assert data["words"] == report.words()
    assert (data["unchanged"], data["changed"], data["new"], data["dropped"], data["needs_attention"]) == (
        2,
        1,
        1,
        0,
        0,
    )
    assert data["features"] == {"matched": 2, "resized": [], "gone": [], "new": ["f-3"]}
    assert report.description() == "UPDATED FROM MODEL: 1 DIMENSION CHANGED, 1 DIMENSION ADDED"


def test_the_merged_drawing_round_trips():
    merged, _r = G.merge(edited(), moved_hole_run())
    again, problems = doc.loads(doc.dumps(merged))
    assert problems == [] and again.dimensions == merged.dimensions and again.features == merged.features


# --------------------------------------------------------------------------- regenerate on the fixtures


@pytest.fixture(scope="module")
def o02_drawing():
    from solidseas.drawing.source import open_source

    src = open_source(fixture("o02_boxA.SLDPRT"))
    plan = T.Plan(views=(T.ViewSpec("v-1", "base", (0.0, 0.0, 1.0), (0.0, 1.0, 0.0), name="front"),))
    return doc.new_drawing(
        src, (plan, compact_sheet()), T.DrawingOptions(units="mm"), people_settings(), {}, seed="o02", now=NOW
    )


def test_regenerate_needs_a_model():
    with pytest.raises(InvalidArgumentError) as info:
        G.regenerate(made())
    assert info.value.detail["rule"] == "model_not_found"


def test_regenerate_on_a_file_saved_again_takes_only_the_new_reference(o02_drawing):
    d, report = G.regenerate(o02_drawing, fixture("o02_boxA.SLDPRT"))
    assert report.model_unchanged and d is o02_drawing
    d, report = G.regenerate(o02_drawing, fixture("o03_boxA_again.SLDPRT"))
    assert report.words() == "model file changed, geometry unchanged"
    assert (
        d.model["sha256"] != o02_drawing.model["sha256"]
        and d.model["geometry"] == o02_drawing.model["geometry"]
    )


def test_regenerate_on_changed_geometry_runs_the_pipeline(o02_drawing):
    missing = [name for name, _p in pipeline.STAGES if not pipeline.available()[name]]
    if not missing:
        pytest.skip("every stage is built")
    with pytest.raises(UnsupportedOperationError) as info:
        G.regenerate(o02_drawing, fixture("o07_boxB_h31.SLDPRT"))
    assert info.value.detail == {"rule": "stage_missing", "value": missing[0]}


def test_regenerate_finds_the_model_next_to_the_drawing(o02_drawing, tmp_path):
    drawing_path = tmp_path / "1234.ssdrw"
    shutil.copyfile(fixture("o03_boxA_again.SLDPRT"), tmp_path / "o02_boxA.SLDPRT")
    with pytest.raises(InvalidArgumentError) as info:  # a changed file is never taken
        G.regenerate(o02_drawing, drawing_path=drawing_path)
    assert info.value.detail["rule"] == "model_not_found" and "changed" in str(info.value)
    shutil.copyfile(fixture("o02_boxA.SLDPRT"), tmp_path / "o02_boxA.SLDPRT")
    d, report = G.regenerate(o02_drawing, drawing_path=drawing_path)
    assert report.model_unchanged
