"""The drawing file (.ssdrw): round trip, member order, unknown members, hostile input,
and a new drawing's ids and records (docs/DRAWINGS.md 13.1, 13.4, 17.2; dwg-file).

The helpers here build drawings by hand from the core types; the other dwg-file test
modules import them."""

import json
import math
import random
from dataclasses import fields, replace

import pytest

from drawing_support import COMPANY, sample_sheet
from solidseas.drawing import display as D
from solidseas.drawing import document as doc
from solidseas.drawing import keys, release
from solidseas.drawing import settings as S
from solidseas.drawing import types as T
from solidseas.drawing.limits import DrawingLimits
from solidseas.drawing.source import DrawingSource, SourceUnits
from solidseas.errors import InvalidArgumentError, SldLimitError

MM = 0.001
NOW = "2026-10-04T14:05:00-04:00"
TODAY = "2026-10-04"
DRAWING_ID = "8f0c1d2e-3b4a-4c5d-9e6f-708192a3b4c5"


# --------------------------------------------------------------------------- builders (shared)


def people_settings(*, same_person_twice=True, replace_own_files=True, keep=True):
    s = S.DrawingSettings()
    s = S.with_value(s, "company", "name", COMPANY)
    s = S.with_value(
        s,
        "people",
        "people",
        [{"name": "Ann Bee", "initials": "AB"}, {"name": "Carl Dee", "initials": "CD"}],
    )
    s = S.with_value(s, "people", "same_person_twice", same_person_twice)
    s = S.with_value(s, "files", "replace_own_files", replace_own_files)
    return S.with_value(s, "files", "keep_preliminary_current", keep)


def compact_sheet():
    """The core's sample sheet after one trip through the compact form (micrometres)."""
    return D.from_compact(json.loads(json.dumps(D.to_compact(sample_sheet()))))


def hole_desc(x, y, d=5 * MM, z=10 * MM, normal="+z", through=True):
    return keys.descriptor(
        "hole", {"diameter": d, "segments": ("cylinder",), "through": through}, {"normal": normal}, (x, y, z)
    )


def face_desc(axis, offset, sign="+"):
    return keys.descriptor("face", {}, {"normal": sign + axis, "axis": axis}, (offset,))


def hand_drawing(**changes):
    """A drawing built by hand from the types, with every member filled."""
    d = doc.DrawingDocument(
        id=DRAWING_ID,
        options=T.DrawingOptions(
            process="machined",
            units="in",
            scheme="datum",
            views=("front", "top"),
            sheet="A",
            scale=(1, 2),
            front="+z",
            arrangement=(("v-1/x", "baseline"),),
        ),
        settings=people_settings(),
        model={
            "name": "bracket.SLDPRT",
            "relative": "bracket.SLDPRT",
            "stored": None,
            "format": "sldprt",
            "configuration": "Default",
            "sha256": "a" * 64,
            "geometry": "b" * 64,
            "properties": "c" * 64,
            "part_number": "1234-001",
            "model_revision": "A",
            "units": {"unit": "in", "origin": "user"},
            "extents": [[0.0, 0.08], [0.0, 0.05], [0.0, 0.01]],
        },
        title=(
            ("title", T.TitleField("BRACKET, MOTOR MOUNT", "typed")),
            ("number", T.TitleField("1234-001", "part")),
            ("material", T.TitleField("ALUMINUM 6061-T6", "list")),
        ),
        features=(
            T.FeatureRecord("f-1", face_desc("z", 0.0, "-"), (("datum", "A"),)),
            T.FeatureRecord("f-2", hole_desc(0.02, 0.025), (("thread", None),)),
        ),
        datums=(T.Datum("A", 0, "largest planar face"),),
        dimensions=(
            doc.DimensionRecord(
                "loc/f-2/x",
                "d-1",
                "linear",
                "v-1",
                0.02,
                axis="x",
                positions=(T.Position(0.0, features=("f-1",)), T.Position(0.02, True, 0.0025, ("f-2",))),
                features=("f-2",),
                places=3,
                tolerance="basic",
                serves=("loc/f-2/x",),
                role="feature_location",
                placement=doc.Placement(0.0, 12.0, 1, True),
                flags=("user_tolerance",),
            ),
            doc.DimensionRecord(
                "size/f-2",
                "d-2",
                "hole_callout",
                "v-1",
                0.005,
                features=("f-2",),
                anchor=(0.02, 0.025, 0.01),
                radius=0.0025,
                prefix="4X",
                suffix=("THRU",),
                frame=T.FrameCell("position", 0.254, True, "mmc", ("A", "B", "C")),
                override="Ø.201 THRU",
            ),
            doc.DimensionRecord(
                "size/f-9", "d-3", "linear", "v-2", 0.01, state="removed", origin="generated"
            ),
        ),
        notes=(
            ("n-1", doc.NoteRecord("BREAK SHARP EDGES .005-.015")),
            (
                "n-2",
                doc.NoteRecord(
                    "ALL OVER", (T.FrameCell("profile_surface", 0.508, False, None, ("A",)),), "user"
                ),
            ),
        ),
        status="PRELIMINARY",
        signatures=(T.Signature("DRAWN", "Ann Bee", TODAY, "d" * 64),),
        revisions=(T.Revision("A", "INITIAL RELEASE"),),
        outputs=(T.Output("pdf", "1234-001 A PRELIMINARY.pdf", "e" * 64, "A", False),),
        next_id=(("f", 10), ("d", 4), ("n", 3), ("v", 3)),
        sheet=compact_sheet(),
        created=NOW,
        modified="2026-10-04T14:20:12-04:00",
    )
    return replace(d, **changes) if changes else d


def hand_source(**changes):
    s = DrawingSource(
        name="bracket.SLDPRT",
        format="sldprt",
        kind="brep",
        configuration="Default",
        bodies=(),
        units=SourceUnits("in", "user"),
        material="6061-T6 (SS)",
        properties=(("PartNo", "1234-001"), ("Description", "BRACKET"), ("Revision", "A")),
        hints=(),
        sha256="a" * 64,
        geometry_digest="b" * 64,
        properties_digest="c" * 64,
    )
    return replace(s, **changes) if changes else s


def feature_set(*descs_faces, extents=((0.0, 0.08), (0.0, 0.05), (0.0, 0.01))):
    """A FeatureSet of plain features: each item is (descriptor, faces)."""
    features = tuple(T.Feature(faces=faces, descriptor=desc) for desc, faces in descs_faces)
    return T.FeatureSet(features=features, frame=T.Frame(extents=extents))


def plan_and_sheet(dim_ids=("d-1", "d-2"), datum_face=0):
    views = (
        T.ViewSpec("v-1", "base", (0.0, 0.0, 1.0), (0.0, 1.0, 0.0), name="front"),
        T.ViewSpec("v-2", "projected", (0.0, 1.0, 0.0), (0.0, 0.0, -1.0), name="top"),
    )
    dims = (
        T.PlannedDimension("loc/f-2/x", dim_ids[0], "linear", "v-1", 0.02, axis="x", features=("f-2",)),
        T.PlannedDimension("size/f-2", dim_ids[1], "diameter", "v-1", 0.005, features=("f-2",)),
    )
    plan = T.Plan(
        views=views,
        dimensions=dims,
        datums=(T.Datum("A", datum_face, "largest planar face"),),
        notes=(T.NoteLine("BREAK SHARP EDGES .005-.015"),),
        coverage=T.Coverage(features=2, faces=7, faces_claimed=7),
    )
    base = compact_sheet()
    painted = base.painted + (
        D.Stroke((("M", 1.0, 1.0), ("L", 2.0, 2.0)), 0.3, (), "dimensions", dim_ids[1]),
    )
    annotations = base.annotations + (
        D.Dimension(dim_ids[1], "diameter", "v-1", ((70.0, 80.0),), (75.0, 85.0), 0.005, D.DimText("Ø.197")),
    )
    sheet = replace(base, annotations=annotations, painted=painted)
    sheet = doc.remap_sheet(sheet, {"d-1": dim_ids[0]}) if dim_ids[0] != "d-1" else sheet
    return plan, sheet


def made(seed="bracket", fields=None, dim_ids=("d-1", "d-2"), settings=None, **kw):
    fs = feature_set((face_desc("z", 0.0, "-"), (0,)), (hole_desc(0.02, 0.025), (5, 6)))
    plan, sheet = plan_and_sheet(dim_ids)
    return doc.new_drawing(
        hand_source(),
        (plan, sheet),
        T.DrawingOptions(),
        settings or people_settings(),
        {"title": "BRACKET, MOTOR MOUNT", "drawn_by": "Ann Bee"} if fields is None else fields,
        features=fs,
        seed=seed,
        today=TODAY,
        now=NOW,
        **kw,
    )


# --------------------------------------------------------------------------- the file


def test_a_drawing_round_trips_through_the_file():
    d = hand_drawing()
    data = doc.dumps(d)
    again, problems = doc.loads(data)
    assert problems == []
    for f in fields(d):
        assert getattr(again, f.name) == getattr(d, f.name), f.name
    assert again == d
    assert doc.dumps(again) == data  # the same drawing writes the same bytes


def test_the_file_is_utf8_json_in_the_fixed_order():
    data = doc.dumps(hand_drawing())
    assert not data.startswith(doc.BOM) and data.endswith(b"}\n")
    obj = json.loads(data.decode("utf-8"))
    assert list(obj) == list(doc.MEMBERS)
    assert obj["schema"] == "solidseas.drawing/1"
    assert obj["generator"]["name"] == "SolidSeas"
    assert list(obj["model"])[:11] == list(doc.MODEL_KEYS)[:11]
    assert list(obj["dimensions"][0])[:10] == [
        "key",
        "id",
        "origin",
        "state",
        "view",
        "placement",
        "text",
        "precision",
        "tolerance",
        "frame",
    ]
    assert obj["dimensions"][0]["placement"] == {
        "along_mm": 0.0,
        "across_mm": 12.0,
        "track": 1,
        "moved": True,
    }
    assert obj["dimensions"][1]["text"] == {"prefix": "4X", "suffix": ["THRU"], "override": "Ø.201 THRU"}
    assert obj["notes"][0] == {"id": "n-1", "origin": "template", "text": "BREAK SHARP EDGES .005-.015"}
    assert obj["title"]["title"] == {"text": "BRACKET, MOTOR MOUNT", "from": "typed"}
    assert obj["next_id"] == {"f": 10, "d": 4, "n": 3, "v": 3}
    assert obj["sheet"]["schema"] == D.SCHEMA
    text = data.decode("utf-8")
    assert "\u2014" not in text and "\u2013" not in text
    # one record a line, so a change to one dimension is one changed line in git
    assert sum(1 for line in text.splitlines() if line.startswith('    {"key": ')) == 3


def test_numbers_are_written_in_shortest_round_trip_form():
    d = hand_drawing(
        dimensions=(doc.DimensionRecord("size/f-2", "d-1", "diameter", "v-1", 0.1 + 0.2, features=("f-2",)),)
    )
    text = doc.dumps(d).decode("utf-8")
    assert '"value": 0.30000000000000004' in text
    again, _ = doc.loads(text.encode("utf-8"))
    assert again.dimensions[0].value == 0.1 + 0.2


def test_a_plain_drawing_and_planned_dimensions_are_written_too():
    plain = T.Drawing(
        id="d-plain",
        options=T.DrawingOptions(),
        settings=S.DrawingSettings(),
        dimensions=(T.PlannedDimension("size/f-1", "d-1", "diameter", "v-1", 0.005),),
    )
    again, problems = doc.loads(doc.dumps(plain))
    assert problems and all(p.startswith(("next_id.d:", "next_id.v:")) for p in problems)
    assert isinstance(again, doc.DrawingDocument) and again.created is None
    assert again.dimensions[0] == doc.as_record(plain.dimensions[0])
    assert again.next_id == (("f", 1), ("d", 2), ("n", 1), ("v", 2))  # past the ids used


def test_unknown_members_are_kept_and_written_back_unread():
    obj = json.loads(doc.dumps(hand_drawing()))
    obj["later_member"] = {"anything": [1, 2, 3]}
    obj["model"]["thumbnail_hash"] = "f" * 64
    obj["options"]["later_option"] = True
    obj["dimensions"][0]["leader"] = {"bend": [1.5, 2.5]}
    obj["dimensions"][0]["placement"]["angle"] = 15
    obj["features"][1]["descriptor"]["curvature"] = 0.5
    obj["signatures"][0]["method"] = "typed"
    obj["outputs"][0]["pages"] = 1
    obj["title"]["number"]["locked"] = True
    data = json.dumps(obj).encode("utf-8")
    d, problems = doc.loads(data)
    assert problems == []
    assert d.model["thumbnail_hash"] == "f" * 64
    out = json.loads(doc.dumps(d))
    assert out["later_member"] == {"anything": [1, 2, 3]}
    assert list(out)[-1] == "later_member"
    assert out["model"]["thumbnail_hash"] == "f" * 64
    assert out["options"]["later_option"] is True
    assert out["dimensions"][0]["leader"] == {"bend": [1.5, 2.5]}
    assert out["dimensions"][0]["placement"]["angle"] == 15
    assert out["features"][1]["descriptor"]["curvature"] == 0.5
    assert out["signatures"][0]["method"] == "typed"
    assert out["outputs"][0]["pages"] == 1
    assert out["title"]["number"]["locked"] is True
    # an edit that removes the dimension takes its unknown members with it
    gone = replace(d, dimensions=d.dimensions[1:])
    assert "leader" not in doc.dumps(gone).decode("utf-8")


def test_unknown_members_are_bounded():
    obj = json.loads(doc.dumps(hand_drawing()))
    obj["later"] = ["x" * 4000] * 300
    with pytest.raises(SldLimitError) as info:
        doc.loads(json.dumps(obj).encode("utf-8"))
    assert info.value.detail["limit"] == "unknown_bytes"


def test_a_sheet_this_solidseas_cannot_read_is_kept_as_it_came():
    obj = json.loads(doc.dumps(hand_drawing()))
    obj["sheet"] = {"schema": "solidseas.drawing-sheet/2", "sheet": {"k": "sheet", "v": ["A", 1]}}
    d, problems = doc.loads(json.dumps(obj).encode("utf-8"))
    assert d.sheet is None and any(p.startswith("sheet:") for p in problems)
    assert json.loads(doc.dumps(d))["sheet"] == obj["sheet"]


# --------------------------------------------------------------------------- hostile input (17.2)


def refused(data, rule=None, limit=None, **kw):
    with pytest.raises((InvalidArgumentError, SldLimitError)) as info:
        doc.loads(data, **kw)
    detail = info.value.detail or {}
    if rule is not None:
        assert isinstance(info.value, doc.DrawingFileError)
        assert detail["rule"] == "drawing_invalid" and detail["value"] == rule, detail
    if limit is not None:
        assert isinstance(info.value, SldLimitError) and detail["limit"] == limit, detail
    return info.value


def good() -> dict:
    return json.loads(doc.dumps(hand_drawing()))


def as_bytes(obj) -> bytes:
    return json.dumps(obj).encode("utf-8")


def test_a_file_over_the_size_bound_is_refused_before_it_is_parsed():
    refused(b" " * 2048 + b"{}", limit="drawing_bytes", limits=DrawingLimits(drawing_bytes=1024))


@pytest.mark.parametrize(
    "data, rule",
    [
        (doc.BOM + b"{}", "bom"),
        (b'{"schema": "solidseas.drawing/1", "id": "\xff"}', "not_utf8"),
        (b'{"schema": "solidseas.drawing/1", "id": "x", "id": "y"}', "json"),
        (b'{"schema": "solidseas.drawing/1", "id": "x", "radius": NaN}', "json"),
        (b'{"schema": "solidseas.drawing/1", "id": "x", "radius": Infinity}', "json"),
        (b'{"schema": "solidseas.drawing/1", "id": "x", "radius": 1e999}', "json"),
        (b'{"schema": "solidseas.drawing/1", "id": "x", "n": 1' + b"0" * 40 + b"}", "json"),
        (b'{"schema": "solidseas.drawing/1", "id": "x", "radius": 1e300}', "number_range"),
        (b'{"schema": "solidseas.drawing/1", "id": "\\ud800"}', "unicode"),
        (b"[1, 2]", "not_object"),
        (b'{"schema": "solidseas.settings/1", "id": "x"}', "schema"),
        (b'{"id": "x"}', "schema"),
        (b'{"schema": "solidseas.drawing/0", "id": "x"}', "schema"),
        (b'{"schema": "solidseas.drawing/2", "id": "x"}', "schema_newer"),
        (b'{"schema": "solidseas.drawing/1", "id": "Not An Id"}', "id"),
        (b'{"schema": "solidseas.drawing/1"}', "id"),
        (b'{"schema": "solidseas.drawing/1", "id": "x"', "json"),
    ],
)
def test_a_file_outside_the_bounds_is_refused_whole(data, rule):
    refused(data, rule=rule)


def test_a_newer_schema_major_says_so_plainly():
    exc = refused(b'{"schema": "solidseas.drawing/2", "id": "x"}', rule="schema_newer")
    assert "newer SolidSeas" in str(exc)
    d, problems = doc.loads(b'{"schema": "solidseas.drawing/1.3", "id": "x"}')  # a minor is read
    assert d.id == "x"


def test_deep_nesting_is_refused():
    deep = b'{"schema": "solidseas.drawing/1", "id": "x", "later": ' + b"[" * 40 + b"]" * 40 + b"}"
    refused(deep, limit="json_depth")
    very = b'{"schema": "solidseas.drawing/1", "id": "x", "later": ' + b"[" * 100_000 + b"]" * 100_000 + b"}"
    refused(very, limit="json_depth")


@pytest.mark.parametrize(
    "change, rule, limit",
    [
        (lambda o: o["features"][0].update(id="F 1"), "id", None),
        (lambda o: o["features"][1].update(id="f-1"), "id_twice", None),
        (lambda o: o["dimensions"][0].update(view="View 1"), "id", None),
        (lambda o: o["dimensions"][0].update(features=["f-1", "../x"]), "id", None),
        (lambda o: o["notes"][0].update(id="n" * 65), "id", None),
        (lambda o: o["title"]["title"].update(text="x" * 5000), None, "string_chars"),
        (lambda o: o.update(later=list(range(20_000))), "array_bounds", None),
        (lambda o: o.update(revisions=[{"rev": "A"}] * 1001), "array_bounds", None),
    ],
)
def test_bad_ids_and_oversized_members_are_refused_whole(change, rule, limit):
    obj = good()
    change(obj)
    refused(as_bytes(obj), rule=rule, limit=limit)


def test_too_many_dimensions_pass_the_requirements_bound():
    obj = good()
    obj["dimensions"] = [dict(obj["dimensions"][0], id=f"d-{k}") for k in range(1, 12)]
    refused(as_bytes(obj), limit="requirements", limits=DrawingLimits(requirements=10))


def test_a_sheet_over_its_bound_is_refused():
    refused(doc.dumps(hand_drawing()), limit="sheet_bytes", limits=DrawingLimits(sheet_bytes=1000))


def test_a_value_failing_its_own_check_falls_back_and_is_listed():
    obj = good()
    obj["status"] = "SHIPPED"
    obj["options"]["process"] = "cast"
    obj["options"]["scale"] = [0, 2]
    obj["options"]["arrangement"] = ["v-1/x"]
    obj["created"] = "yesterday"
    obj["model"]["sha256"] = "not a hash"
    obj["title"]["number"]["from"] = "guessed"
    obj["dimensions"][0]["placement"] = {"along_mm": "far"}
    obj["dimensions"][0]["precision"]["places"] = 99
    obj["dimensions"][1]["kind"] = "spline"
    obj["signatures"].append({"row": "QA", "name": "Ann Bee", "date": "2026-13-40", "digest": "d" * 64})
    obj["revisions"][0]["zones"] = ["B3", "b3"]
    obj["outputs"][0]["name"] = "../../evil.pdf"
    obj["next_id"]["d"] = 1
    d, problems = doc.loads(as_bytes(obj))
    assert d.status == "PRELIMINARY"
    assert d.options.process == "machined" and d.options.scale == "auto"
    assert d.options.units == "in"  # the good options are kept
    assert d.created is None and d.model["sha256"] is None
    assert [k for k, _f in d.title] == ["title", "material"]
    assert d.dimensions[0].placement is None and d.dimensions[0].places == 2
    assert [x.id for x in d.dimensions] == ["d-1", "d-3"]  # the one with a bad kind is left out
    assert [s.row for s in d.signatures] == ["DRAWN"]
    assert d.revisions == () and d.outputs == ()
    assert dict(d.next_id)["d"] == 4  # never below an id in use
    joined = "\n".join(problems)
    for where in (
        "status:",
        "options.process:",
        "options.scale:",
        "options.arrangement:",
        "file.created:",
        "model.sha256:",
        "title.number:",
        "dimensions[d-1].placement:",
        "dimensions[d-1].precision.places:",
        "dimensions[d-2]:",
        "signatures[1]:",
        "revisions[0]:",
        "outputs[0]:",
        "next_id.d:",
    ):
        assert where in joined, where


def test_a_bad_settings_snapshot_value_falls_back_alone():
    obj = good()
    obj["settings"]["files"]["replace_own_files"] = "yes"
    obj["settings"]["company"]["name"] = 7
    d, problems = doc.loads(as_bytes(obj))
    assert d.settings.files.replace_own_files is True and d.settings.people.people  # the rest is read
    assert sum(p.startswith("settings: ") for p in problems) == 2


def test_truncated_files_never_raise_an_unexpected_exception():
    data = doc.dumps(hand_drawing())
    for cut in list(range(0, 400)) + list(range(400, len(data), 97)):
        try:
            doc.loads(data[:cut])
        except (InvalidArgumentError, SldLimitError):
            pass


def test_random_byte_flips_never_raise_an_unexpected_exception():
    data = bytearray(doc.dumps(hand_drawing()))
    rng = random.Random(1307)
    outcomes = {"read": 0, "refused": 0}
    for _ in range(400):
        mutated = bytearray(data)
        for _k in range(rng.randint(1, 4)):
            mutated[rng.randrange(len(mutated))] = rng.randrange(256)
        try:
            d, problems = doc.loads(bytes(mutated))
        except (InvalidArgumentError, SldLimitError):
            outcomes["refused"] += 1
            continue
        outcomes["read"] += 1
        doc.dumps(d)  # whatever was read writes back
        assert isinstance(problems, list)
    assert outcomes["read"] and outcomes["refused"]


def value_paths(value, prefix=()):
    """Every path into a JSON value but the sheet's, at most three entries of each list."""
    if prefix:
        yield prefix
    if isinstance(value, dict):
        for k, v in value.items():
            if not (prefix == () and k == "sheet"):
                yield from value_paths(v, (*prefix, k))
    elif isinstance(value, list):
        for i, v in enumerate(value[:3]):
            yield from value_paths(v, (*prefix, i))


def test_hostile_values_anywhere_never_raise_an_unexpected_exception():
    rng = random.Random(42)
    junk = [None, True, -1, 0, 1.5, 1e12, "", "x" * 300, [], [None], ["a"], {}, {"k": "v"}, "f-1", "\x01"]
    base = good()
    paths = list(value_paths(base))
    for _ in range(600):
        obj = json.loads(json.dumps(base))
        for path in rng.sample(paths, rng.randint(1, 3)):
            target = obj
            try:
                for p in path[:-1]:
                    target = target[p]
                target[path[-1]] = rng.choice(junk)
            except (KeyError, IndexError, TypeError):
                continue  # an earlier change took the path away
        try:
            d, _problems = doc.loads(as_bytes(obj))
            doc.dumps(d)
            release.content_digest(d)
        except (InvalidArgumentError, SldLimitError):
            pass


def test_dumps_refuses_what_it_cannot_write():
    with pytest.raises(InvalidArgumentError):
        doc.dumps("not a drawing")
    with pytest.raises(InvalidArgumentError):
        doc.dumps(hand_drawing(sheet="a sheet"))
    with pytest.raises(InvalidArgumentError):
        doc.dumps(hand_drawing(features=(T.FeatureRecord("f-1", T.Descriptor("hole"), (("x", math.nan),)),)))
    with pytest.raises(SldLimitError):
        doc.dumps(hand_drawing(), limits=DrawingLimits(drawing_bytes=1024))


# --------------------------------------------------------------------------- a new drawing (13.4)


def test_a_new_drawing_is_preliminary_with_ids_in_order():
    d = made()
    assert isinstance(d, doc.DrawingDocument) and d.status == "PRELIMINARY"
    assert [f.id for f in d.features] == ["f-1", "f-2"]
    assert dict(d.features[0].decisions) == {"datum": "A"}  # the datum's letter on its feature
    assert [x.id for x in d.dimensions] == ["d-1", "d-2"]
    assert all(isinstance(x, doc.DimensionRecord) for x in d.dimensions)
    assert d.notes == (("n-1", doc.NoteRecord("BREAK SHARP EDGES .005-.015", (), "template")),)
    assert dict(d.next_id) == {"f": 3, "d": 3, "n": 2, "v": 3}
    assert d.revisions == (T.Revision("A", "INITIAL RELEASE"),)
    assert d.created == d.modified == NOW
    assert (
        d.model["sha256"] == "a" * 64
        and d.model["relative"] == "bracket.SLDPRT"
        and d.model["stored"] is None
    )
    assert d.model["units"] == {"unit": "in", "origin": "user"}
    assert d.model["extents"] == [[0.0, 0.08], [0.0, 0.05], [0.0, 0.01]]
    assert d.settings == people_settings()
    assert d.coverage.features == 2


def test_dimension_ids_follow_planning_order_and_the_sheet_follows():
    d = made(dim_ids=("d-12", "d-5"))
    assert [x.id for x in d.dimensions] == ["d-1", "d-2"]
    dims = [a for a in d.sheet.annotations if isinstance(a, D.Dimension)]
    assert {a.id for a in dims} == {"d-1", "d-2"}
    owners = {p.owner for p in d.sheet.painted if p.owner.startswith("d-")}
    assert owners == {"d-1", "d-2"}


def test_a_fresh_drawing_of_the_same_model_gets_the_same_ids_and_bytes():
    a, b = made(seed="same"), made(seed="same")
    assert a.id == b.id and doc.dumps(a) == doc.dumps(b)
    assert made(seed="other").id != a.id
    assert T.ID_PATTERN.fullmatch(made(seed=None).id)


def test_title_fields_are_typed_else_from_the_part():
    d = made(fields={"title": "BRACKET, MOTOR MOUNT", "finish": "AS MACHINED"})
    title = dict(d.title)
    assert title["title"] == T.TitleField("BRACKET, MOTOR MOUNT", "typed")
    assert title["finish"] == T.TitleField("AS MACHINED", "typed")
    assert "number" not in title  # the part has no drawing number property
    assert title["part_number"] == T.TitleField("1234-001", "part")
    assert title["revision"] == T.TitleField("A", "part")
    # the part's material maps through the settings' list to its callout and follows the part
    assert title["material"] == T.TitleField("ALUMINUM 6061-T6", "part")
    typed = dict(made(fields={"material": "pla"}).title)["material"]
    assert typed == T.TitleField("PLA", "list")
    assert dict(made(fields={"material": "UNOBTAINIUM"}).title)["material"].source == "typed"


def test_drawn_by_signs_drawn_with_the_content_digest():
    d = made()
    assert d.signatures == (T.Signature("DRAWN", "Ann Bee", TODAY, release.content_digest(d)),)
    assert made(fields={}).signatures == ()


def test_the_options_are_frozen_as_the_run_chose_them():
    d = made()
    o = d.options
    assert o.units == "in" and o.scheme == "datum"
    assert o.views == ("front", "top") and o.sheet == "A" and o.scale == (1, 2) and o.front == "+z"
    kept = doc.new_drawing(
        hand_source(),
        plan_and_sheet(),
        T.DrawingOptions(units="mm", views=("front",), sheet="B", scale=(1, 1)),
        people_settings(),
        {},
        seed="x",
        now=NOW,
    )
    assert kept.options.units == "mm" and kept.options.views == ("front",) and kept.options.sheet == "B"


def test_without_a_feature_set_the_table_is_empty_and_says_so():
    plan, sheet = plan_and_sheet()
    d = doc.new_drawing(hand_source(), (plan, sheet), None, None, None, seed="x", now=NOW)
    assert d.features == () and dict(d.next_id)["f"] == 3  # past f-2, which the plan names
    assert any("feature" in w for w in d.warnings)
    fs = feature_set((face_desc("z", 0.0, "-"), (0,)))
    third = doc.new_drawing(hand_source(), (plan, sheet, fs), None, None, None, seed="x", now=NOW)
    assert [f.id for f in third.features] == ["f-1"]


@pytest.mark.parametrize(
    "call",
    [
        lambda: doc.new_drawing(hand_source(), "plan", seed="x"),
        lambda: doc.new_drawing(hand_source(), plan_and_sheet(), "options", seed="x"),
        lambda: doc.new_drawing(hand_source(), plan_and_sheet(), None, {"not": "settings"}, seed="x"),
        lambda: doc.new_drawing(hand_source(), plan_and_sheet(), None, None, {"Title": "x"}, seed="x"),
        lambda: doc.new_drawing(hand_source(), plan_and_sheet(), None, None, {"title": "a\nb"}, seed="x"),
        lambda: doc.new_drawing(hand_source(), plan_and_sheet(), None, None, {"title": "x" * 300}, seed="x"),
        lambda: doc.new_drawing(hand_source(), plan_and_sheet(), features="fs", seed="x"),
        lambda: doc.new_drawing(hand_source(), plan_and_sheet(), seed=5),
        lambda: doc.new_drawing(hand_source(), plan_and_sheet(), now="later"),
    ],
)
def test_new_drawing_checks_its_arguments(call):
    with pytest.raises(InvalidArgumentError) as info:
        call()
    assert "parameter" in info.value.detail


def test_a_new_drawing_round_trips():
    d = made()
    again, problems = doc.loads(doc.dumps(d))
    assert problems == []
    assert replace(again, warnings=d.warnings, coverage=d.coverage) == d


def test_the_pipeline_finds_the_assemble_stage():
    from solidseas.drawing import pipeline

    assert pipeline.available()["assemble"] and pipeline.available()["load"]
    assert pipeline.available()["save"] and pipeline.available()["regenerate"]


def test_a_plan_naming_one_dimension_twice_is_refused():
    with pytest.raises(InvalidArgumentError) as info:
        doc.new_drawing(hand_source(), plan_and_sheet(("d-4", "d-4")), seed="x", now=NOW)
    assert info.value.detail["parameter"] == "planned"
