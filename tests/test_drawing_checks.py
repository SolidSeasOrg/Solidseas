"""The automated checklist (docs/DRAWINGS.md 20.1, 19.5): every id fires on a case
built to break it and stays quiet on a good drawing, live (with the plan and layout)
and from the file alone; release-time levels; Release reading the checks; the order;
the o11 fixture; and the speed on a 100-hole plate."""

import contextlib
import functools
import math
import re
import time
from dataclasses import replace
from pathlib import Path

import pytest

import drawing_parts as P
from drawing_plan_fixtures import PATTERNS, plate
from drawing_support import COMPANY, fixture
from solidseas.drawing import checks as C
from solidseas.drawing import display as D
from solidseas.drawing import document, facegraph, make_drawing, orchestrate, pipeline, release
from solidseas.drawing import settings as S
from solidseas.drawing import types as T
from solidseas.drawing.layout import layout
from solidseas.drawing.layout import notes as layout_notes
from solidseas.drawing.layout.checks import LayoutCheck
from solidseas.drawing.plan import Planned, make_plan
from solidseas.errors import InvalidArgumentError

TODAY = "2026-10-07"
SCATTERED = (("scattered", (0, 1, 2, 3)),)
FIELDS = {"drawn_by": "Ann Example", "material": "6061-T6 (SS)", "finish": "None"}
PEOPLE = (
    {"name": "Ann Example", "initials": "AE"},
    {"name": "Carl Dee", "initials": "CD"},
    {"name": "Pat Example", "initials": "PE"},
)
DRAWINGS_MD = Path(__file__).resolve().parents[1] / "docs" / "DRAWINGS.md"


class _Source:
    configuration = "Default"
    material = None
    hints = ()
    properties = ()
    sha256 = "ab" * 32

    def __init__(self, name: str) -> None:
        self.name = name.upper() + ".SLDPRT"

    def property(self, *names):
        return None


def _settings() -> S.DrawingSettings:
    s = S.DrawingSettings()
    return replace(s, company=replace(s.company, name=COMPANY), people=replace(s.people, people=PEOPLE))


@contextlib.contextmanager
def notes_lettered_small():
    """The notes lettered at 0.9 of the dimension height (2.7 mm), below the 3 mm
    minimum, as layout once did: the case R10.text is about."""
    block, height = layout_notes.notes_block, layout_notes.height
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            layout_notes,
            "notes_block",
            lambda pen, index, ctx, area, notes, h, frame_w: block(
                pen, index, ctx, area, notes, h * 0.9, frame_w
            ),
        )
        mp.setattr(
            layout_notes, "height", lambda notes, width, h, frame_w: height(notes, width, h * 0.9, frame_w)
        )
        yield


@functools.cache
def made(name="four_holes", patterns=SCATTERED, unclaimed=0, options=None, small_notes=False):
    """(drawing, orchestrated) of a hand-made plate: a live run of the plan stage and
    the drawing the assemble stage makes of it, PRELIMINARY, DRAWN signed."""
    st = _settings()
    pats = [(k, list(m)) for k, m in patterns] if patterns else None
    ctx = plate(name, patterns=pats, unclaimed=unclaimed, options=options, settings=st)
    src = _Source(name)
    with notes_lettered_small() if small_notes else contextlib.nullcontext():
        done = orchestrate.run(src, ctx.model, ctx.features, ctx.views, ctx.options, st, FIELDS)
    d = document.new_drawing(
        src,
        (done.planned.plan, done.result.sheet, ctx.features),
        done.options,
        st,
        FIELDS,
        today=TODAY,
        seed=name,
    )
    return d, done


def relaid(d, done):
    """The sheet laid out again with the drawing's status and signatures, as the editor
    does after signing."""
    signed = {g.row: (g.name, g.date) for g in d.signatures}
    r = layout(
        done.planned,
        options=done.options,
        settings=d.settings,
        source=_Source(d.model["name"][: -len(".SLDPRT")]),
        fields=FIELDS,
        status=d.status,
        signed=signed,
    )
    return replace(d, sheet=r.sheet), replace(done, result=r)


def signed(d, done):
    d, _w = release.sign(d, "CHECKED", "Carl Dee", TODAY)
    d, _w = release.sign(d, "APPROVED", "Pat Example", TODAY)
    return relaid(d, done)


@functools.cache
def good(**kw):
    """A drawing with nothing to say: signed CHECKED and APPROVED, laid out again."""
    return signed(*made(**kw))


def live(d, done, **kw):
    return C.run_checks(d, planned=done.planned, layout=done.result, **kw)


def from_file(d, **kw):
    loaded, _problems = document.loads(document.dumps(d))
    return C.run_checks(loaded, **kw)


def found(checks, code, level=None):
    return [c for c in checks if c.code == code and (level is None or c.level == level)]


def dim(d, did):
    return next(x for x in d.dimensions if x.id == did)


def with_dim(d, did, **kw):
    return replace(d, dimensions=tuple(replace(x, **kw) if x.id == did else x for x in d.dimensions))


def with_sheet(d, *, drop=(), add=()):
    """The drawing with annotations of the classes ``drop`` taken off its sheet and
    ``add`` put on."""
    anns = tuple(a for a in d.sheet.annotations if not isinstance(a, drop)) + tuple(add)
    return replace(d, sheet=replace(d.sheet, annotations=anns))


def with_ann(d, cls, **kw):
    """The drawing with every annotation of ``cls`` on its sheet changed."""
    anns = tuple(replace(a, **kw) if isinstance(a, cls) else a for a in d.sheet.annotations)
    return replace(d, sheet=replace(d.sheet, annotations=anns))


def with_title(d, key, value):
    tb = next(a for a in d.sheet.annotations if isinstance(a, D.TitleBlock))
    return with_ann(d, D.TitleBlock, fields=tuple((k, value if k == key else v) for k, v in tb.fields))


def with_note(d, nid, note=None):
    notes = tuple((i, n) for i, n in d.notes if i != nid)
    if note is not None:
        notes += ((nid, note),)
    return replace(d, notes=notes)


def with_detail(done, **kw):
    detail = replace(done.planned.detail, **kw)
    return replace(done, planned=Planned(done.planned.plan, detail))


# --------------------------------------------------------------------------- the table and the contract


def _table() -> dict[str, str]:
    text = DRAWINGS_MD.read_text(encoding="utf-8")
    section = text.split("### 20.1 The automated checklist", 1)[1].split("### 20.2", 1)[0]
    out = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 3 or cells[0] in ("Id", "---"):
            continue
        for code in re.findall(r"\b(?:R[0-9]+|COV|REL|ASM)\.[a-z_]+\b", cells[0]):
            out[code] = cells[2].split()[0].rstrip(";")
    return out


def test_every_id_of_the_table_is_a_check_with_its_severity():
    table = _table()
    assert len(table) == 38
    assert set(table) == set(C.CODES)
    assert {code: level for code, (level, _reads) in C.CODES.items()} == table
    assert set(C.MODEL_ONLY) <= set(C.CODES) and set(C.LAYOUT_CODES.values()) <= set(C.CODES)


def test_the_pipeline_finds_the_checks():
    assert pipeline.resolve("checks", pipeline.ENTRY_POINTS["checks"]) is C.run_checks
    assert pipeline.available()["checks"]


def test_a_check_is_words_with_a_level():
    c = C.Check("R4.complete", "error", "the Ø6.60 hole is not located along X", "f-1", ("Restore", "Add"))
    assert c.to_dict() == {
        "code": "R4.complete",
        "level": "error",
        "message": "the Ø6.60 hole is not located along X",
        "item": "f-1",
        "fixes": ["Restore", "Add"],
    }
    for bad in (
        {"level": "fatal"},
        {"code": ""},
        {"message": ""},
        {"item": 3},
        {"fixes": ["Add"]},
        {"fixes": (1,)},
    ):
        args = {"code": "R1.scale", "level": "error", "message": "x", "item": "", "fixes": ()} | bad
        with pytest.raises(InvalidArgumentError):
            C.Check(**args)


def test_the_arguments_are_checked():
    d, done = made()
    for kw, name in (
        ({"drawing": "x"}, "drawing"),
        ({"drawing": d, "planned": done}, "planned"),
        ({"drawing": d, "layout": done.planned}, "layout"),
        ({"drawing": d, "release": "yes"}, "release"),
    ):
        drawing = kw.pop("drawing")
        with pytest.raises(InvalidArgumentError) as info:
            C.run_checks(drawing, **kw)
        assert info.value.detail == {"parameter": name}


# --------------------------------------------------------------------------- the good drawing


def test_a_good_drawing_has_nothing_to_say_live_or_from_its_file():
    d, done = good()
    assert live(d, done) == ()
    assert from_file(d) == ()
    assert C.run_checks(d, planned=done.planned) == ()  # the plan without the layout's own checks


def test_a_new_drawing_says_what_is_left_to_do_as_information():
    d, done = made()
    said = live(d, done)
    assert {(c.code, c.level) for c in said} == {
        ("R3.roles", "information"),
        ("R6.signatures", "information"),
    }
    (roles,) = found(said, "R3.roles")
    assert roles.message.startswith(
        "4 dimensions take their precision from their role (3 at ±0.2, 1 at ±0.05)"
    )
    assert {c.item for c in found(said, "R6.signatures")} == {"CHECKED", "APPROVED"}


# --------------------------------------------------------------------------- each id, broken on purpose


def _r1_aligned():
    d, done = good()
    views = tuple(
        replace(p, origin=(p.origin[0] + 0.5, p.origin[1])) if p.view == "v-2" else p for p in d.sheet.views
    )
    return live(replace(d, sheet=replace(d.sheet, views=views)), done)


def _r1_scale():
    return C.run_checks(with_title(good()[0], "scale", "1:2"))


def _r1_symbol():
    d, _done = good()
    return C.run_checks(with_sheet(d, drop=(D.ProjectionSymbol,)))


def _r2_units():
    d, _done = good()
    tb = next(a for a in d.sheet.annotations if isinstance(a, D.ToleranceBlock))
    return C.run_checks(
        with_ann(d, D.ToleranceBlock, lines=tuple(x for x in tb.lines if "DIMENSIONS ARE IN" not in x))
    )


def _r2_format():
    d, _done = good()
    anns = tuple(
        replace(a, text=replace(a.text, value="100.00"))
        if isinstance(a, D.Dimension) and a.id == "d-2"
        else a
        for a in d.sheet.annotations
    )
    return C.run_checks(replace(d, sheet=replace(d.sheet, annotations=anns)))


def _r2_rounding():
    d, _done = good()
    return C.run_checks(with_dim(d, "d-2", value=0.100049))


def _r2_override():
    d, _done = good()
    return C.run_checks(with_dim(d, "d-2", override="105.0"))


def _r3_tolerance():
    d, _done = good()
    return C.run_checks(with_dim(d, "d-2", tolerance="eyeball"))


def _r3_block():
    d, _done = good()
    return C.run_checks(with_dim(d, "d-2", places=3))


def _r3_basic():
    d, _done = good()
    return C.run_checks(with_dim(with_note(d, "n-1"), "d-1", frame=None))


def _r3_roles():
    return C.run_checks(made()[0])


def _r4_complete():
    d, done = good()
    return live(with_dim(d, "d-5", state="removed"), done)


def _r4_redundant():
    d, done = good()
    copy = replace(dim(d, "d-2"), id="d-99")
    return live(replace(d, dimensions=d.dimensions + (copy,)), done)


def _r4_members():
    d, done = good(patterns=tuple((k, tuple(m)) for k, m in PATTERNS), name="patterns")
    callout = next(x for x in d.dimensions if x.key == "callout/f-19")
    assert callout.prefix == "5X Ø"
    return live(with_dim(d, callout.id, prefix="4X Ø"), done)


def _r4_coincident():
    d, done = good()
    detail = done.planned.detail
    a, b = detail.positions["d-2"]
    spec, geom = detail.ctx.view("v-1")
    split = []
    for w in geom.witnesses:
        if w.axis == "x" and abs(w.position - a.value) < 1e-9:
            mid = (w.low + w.high) / 2
            split += [replace(w, high=mid - 0.005), replace(w, low=mid + 0.005)]
        else:
            split.append(w)
    views = tuple(
        (s, replace(g, witnesses=tuple(split)) if s.id == "v-1" else g) for s, g in detail.ctx.views
    )
    ctx = replace(detail.ctx, views=views)
    positions = {**detail.positions, "d-2": (replace(a, faces=(a.faces[0], a.faces[0] + 1000)), b)}
    return live(d, with_detail(done, ctx=ctx, positions=positions))


def _r5_visible():
    d, done = good()
    detail = done.planned.detail
    views = tuple((s, replace(g, witnesses=()) if s.id == "v-1" else g) for s, g in detail.ctx.views)
    return live(d, with_detail(done, ctx=replace(detail.ctx, views=views)))


def _r5_true_shape():
    d, done = good()
    return live(with_dim(d, "d-1", view="v-2"), done)


def _r6_title():
    d, _done = good()
    return C.run_checks(
        replace(d, settings=replace(d.settings, company=replace(d.settings.company, name="")))
    )


def _r6_material():
    return C.run_checks(with_title(good()[0], "material", "STEEL 4140"), release=True)


def _r6_signatures():
    return C.run_checks(made()[0], release=True)


def _r7_callouts():
    d, done = good()
    return live(with_dim(d, "d-1", suffix=("↧ 5.0",)), done)


def _r8_sheet():
    d, _done = good()
    return C.run_checks(with_sheet(d, drop=(D.Border,)))


def _r9_lines():
    d, _done = good()
    painted = list(d.sheet.painted)
    painted[0] = replace(painted[0], width=0.3)
    assert d.sheet.geometry[0].style == "visible"
    return C.run_checks(replace(d, sheet=replace(d.sheet, painted=tuple(painted))))


def _r10_text():
    return live(*made(small_notes=True))


def _r11_collisions():
    d, _done = good()
    runs = [p for p in d.sheet.painted if isinstance(p, D.TextRun)]
    target = next(p for p in runs if p.owner == "d-2")
    painted = tuple(
        replace(p, x=target.x, y=target.y, angle_deg=0.0, anchor=target.anchor)
        if isinstance(p, D.TextRun) and p.owner == "d-3"
        else p
        for p in d.sheet.painted
    )
    return C.run_checks(replace(d, sheet=replace(d.sheet, painted=painted)))


def _r11_spacing():
    d, _done = good()
    anns = []
    for a in d.sheet.annotations:
        if isinstance(a, D.Dimension) and a.id == "d-2":
            (x0, y0), b, (lx, ly) = a.points
            a = replace(a, points=((x0, y0), b, (lx, (ly + y0) / 2)))
        anns.append(a)
    return C.run_checks(replace(d, sheet=replace(d.sheet, annotations=tuple(anns))))


def _r11_leaders():
    d, _done = good()
    (owner, start, elbow), *_rest = C._painted_leaders(d.sheet)
    steep = (elbow[0] - 1.0, elbow[1] - 20.0)
    painted = tuple(
        replace(p, path=(("M", *steep), ("L", *elbow)))
        if isinstance(p, D.Stroke) and p.owner == owner and p.path == (("M", *start), ("L", *elbow))
        else p
        for p in d.sheet.painted
    )
    return C.run_checks(replace(d, sheet=replace(d.sheet, painted=painted)))


def _r12_views():
    d, _done = good()
    return C.run_checks(with_sheet(d, add=(D.ViewLabel("v-1", (20.0, 20.0), "SECTION I-I", "I"),)))


def _r13_scheme():
    d, done = good()
    edges = dict(done.planned.detail.edges)
    ax, _a, b = edges["d-6"]
    edges["d-6"] = (ax, edges["d-5"][2], b)  # f-2 located from f-1: a chain
    return live(d, with_detail(done, edges=edges))


def _r13_plusminus():
    return C.run_checks(good(options=T.DrawingOptions(scheme="plusminus"))[0])


def _r14_notes():
    d, _done = good()
    return C.run_checks(with_note(d, "n-2"))


def _r15_process():
    d, _done = good()
    return C.run_checks(with_note(d, "n-5"))


def _r18_datums():
    d, _done = good()
    frame = dim(d, "d-1").frame
    return C.run_checks(with_dim(d, "d-1", frame=replace(frame, datums=("A", "B", "D"))))


def _r18_frames():
    d, _done = good()
    (nid, note), *_rest = d.notes
    flat = replace(note.frames[0], characteristic="flatness")
    return C.run_checks(with_note(d, nid, replace(note, frames=(flat,))))


def _cov_unclaimed():
    return live(*good(unclaimed=2))


def _rel_stamp():
    d, _done = good()
    return C.run_checks(with_sheet(d, drop=(D.Stamp,)))


@functools.cache
def assembly_drawing():
    """o15's drawing: an assembly of two parts, its parts list of two items and a
    balloon on each."""
    fields = {"drawn_by": "Ann Example"}
    return make_drawing(fixture("o15_sub_asm.SLDASM"), settings=_settings(), fields=fields)


def _asm_parts():
    return C.run_checks(with_sheet(assembly_drawing(), drop=(D.PartsList,)))


def _asm_balloons():
    return C.run_checks(with_sheet(assembly_drawing(), drop=(D.Balloon,)))


CASES = {
    "R1.aligned": (_r1_aligned, "error"),
    "R1.scale": (_r1_scale, "error"),
    "R1.symbol": (_r1_symbol, "error"),
    "R2.units": (_r2_units, "error"),
    "R2.format": (_r2_format, "error"),
    "R2.rounding": (_r2_rounding, "warning"),
    "R2.override": (_r2_override, "error"),
    "R3.tolerance": (_r3_tolerance, "error"),
    "R3.block": (_r3_block, "error"),
    "R3.basic": (_r3_basic, "error"),
    "R3.roles": (_r3_roles, "information"),
    "R4.complete": (_r4_complete, "error"),
    "R4.redundant": (_r4_redundant, "error"),
    "R4.members": (_r4_members, "error"),
    "R4.coincident": (_r4_coincident, "error"),
    "R5.visible": (_r5_visible, "error"),
    "R5.true_shape": (_r5_true_shape, "error"),
    "R6.title": (_r6_title, "error"),
    "R6.material": (_r6_material, "error"),
    "R6.signatures": (_r6_signatures, "error"),
    "R7.callouts": (_r7_callouts, "error"),
    "R8.sheet": (_r8_sheet, "error"),
    "R9.lines": (_r9_lines, "warning"),
    "R10.text": (_r10_text, "error"),
    "R11.collisions": (_r11_collisions, "error"),
    "R11.spacing": (_r11_spacing, "warning"),
    "R11.leaders": (_r11_leaders, "warning"),
    "R12.views": (_r12_views, "warning"),
    "R13.scheme": (_r13_scheme, "warning"),
    "R13.plusminus": (_r13_plusminus, "warning"),
    "R14.notes": (_r14_notes, "warning"),
    "R15.process": (_r15_process, "error"),
    "R18.datums": (_r18_datums, "error"),
    "R18.frames": (_r18_frames, "error"),
    "COV.unclaimed": (_cov_unclaimed, "warning"),
    "REL.stamp": (_rel_stamp, "error"),
    "ASM.parts": (_asm_parts, "error"),
    "ASM.balloons": (_asm_balloons, "warning"),
}


def test_every_id_has_a_case():
    assert set(CASES) == set(C.CODES)


@pytest.mark.parametrize("code", sorted(CASES))
def test_each_id_fires_on_its_case(code):
    case, level = CASES[code]
    said = found(case(), code)
    assert said, f"{code} did not fire"
    assert level in {c.level for c in said}
    for c in said:
        assert c.message and c.item and c.message[0] != " "
        assert "\u2013" not in c.message and "\u2014" not in c.message


# --------------------------------------------------------------------------- what each says


def test_an_assembly_is_checked_as_an_assembly():
    d = assembly_drawing()
    found_codes = {c.code for c in C.run_checks(d)}
    part_only = {"R2.units", "R3.tolerance", "R6.material", "R12.views", "R14.notes", "R15.process"}
    part_only.add("COV.unclaimed")
    assert not found_codes & part_only
    assert [c for c in d.checks if c.level != "information"] == []
    assert [c for c in C.run_checks(d) if c.level != "information"] == []  # from the file alone too
    (parts,) = found(_asm_parts(), "ASM.parts")
    assert (parts.message, parts.item) == ("the sheet has no parts list", "parts")
    assert parts.fixes == ("Lay Out Again",)
    missing = found(_asm_balloons(), "ASM.balloons")
    why = "has no balloon: no view on the sheet shows a visible edge of it"
    assert [(c.item, c.message) for c in missing] == [
        ("balloon-1", f"item 1 (O02_BOXA) {why}"),
        ("balloon-2", f"item 2 (O07_BOXB_H31) {why}"),
    ]
    stray = next(a for a in d.sheet.annotations if isinstance(a, D.Balloon))
    odd = C.run_checks(with_sheet(d, add=(replace(stray, item="9"),)))
    assert [(c.level, c.message) for c in found(odd, "ASM.balloons")] == [
        ("error", "balloon 9 names no item of the parts list")
    ]


def test_a_location_removed_is_named_with_restore_and_add():
    (c,) = found(_r4_complete(), "R4.complete")
    assert c.item == "f-1" and c.fixes == ("Restore", "Add")
    assert c.message == "the Ø6.60 hole is not located along X"
    d, done = good()
    size = found(live(with_dim(d, "d-2", state="removed"), done), "R4.complete")
    assert [(c.item, c.fixes) for c in size] == [("f-6", ("Restore", "Add"))]
    assert size[0].message == "the 100.0 overall size along X is not stated"


def test_a_loop_names_the_dimension_that_closes_it():
    d, done = good()
    copy = replace(dim(d, "d-5"), id="d-98")
    said = found(live(replace(d, dimensions=d.dimensions + (copy,)), done), "R4.redundant")
    (loop,) = said
    assert loop.item == "d-98" and loop.fixes == ("Make Reference", "Remove the Other", "Link Instead")
    assert re.fullmatch(r"d-98 \(\[[0-9.]+\]\) closes a loop with \[[0-9.]+\]", loop.message)
    (twice,) = found(_r4_redundant(), "R4.redundant")
    assert twice.item == "d-99" and "already states" in twice.message


def test_pattern_members_and_counts():
    (c,) = found(_r4_members(), "R4.members")
    assert "says 4X but the pattern has 5 holes" in c.message
    d, done = good(patterns=tuple((k, tuple(m)) for k, m in PATTERNS), name="patterns")
    pitch = next(x for x in d.dimensions if x.key.startswith("pitch/f-19/"))
    said = found(live(with_dim(d, pitch.id, state="removed"), done), "R4.members")
    assert [c.item for c in said] == ["f-19"] and "are not located" in said[0].message
    assert said[0].fixes == ("Restore", "Add")
    assert not found(live(with_dim(d, pitch.id, state="removed"), done), "R4.complete")


def test_rounding_is_an_error_above_half_the_band():
    (warn,) = found(_r2_rounding(), "R2.rounding")
    assert warn.level == "warning" and "lies inside the band" in warn.message
    assert warn.fixes == ("Keep", "Increase the Precision", "Give a Tolerance")
    d, _done = good()
    tight = with_dim(d, "d-2", value=0.100049, tolerance="symmetric", tolerance_values=(0.01, -0.01))
    (err,) = found(C.run_checks(tight), "R2.rounding")
    assert err.level == "error" and "lies outside the band" in err.message


def test_an_override_is_an_error_until_accepted():
    (c,) = found(_r2_override(), "R2.override")
    assert c.level == "error" and c.item == "d-2" and "'105.0'" in c.message and "100.0" in c.message
    d, _done = good()
    assert not found(C.run_checks(with_dim(d, "d-2", override="100.0")), "R2.override")
    worded = found(C.run_checks(with_dim(d, "d-2", override="AS MACHINED")), "R2.override")
    assert worded and worded[0].level == "error" and "states no number" in worded[0].message
    accepted = replace(
        with_dim(d, "d-2", override="105.0"), accepted=(("d-2", "the customer's print governs"),)
    )
    (info,) = found(C.run_checks(accepted), "R2.override")
    assert info.level == "information" and "the customer's print governs" in info.message


def test_release_time_levels():
    d, _done = made()
    before = C.run_checks(d)
    at = C.run_checks(d, release=True)
    assert {c.level for c in found(before, "R6.signatures")} == {"information"}
    assert {c.level for c in found(at, "R6.signatures")} == {"error"}
    material = _r6_material()
    assert [c.level for c in found(material, "R6.material")] == ["error"]
    heat = with_title(d, "material", "STEEL 4140")
    assert [c.level for c in found(C.run_checks(heat), "R6.material")] == ["warning"]
    typed = with_title(d, "material", "UNOBTAINIUM")
    # Release refuses an unmapped material itself until it is accepted as typed (13.2)
    assert [c.level for c in found(C.run_checks(typed, release=True), "R6.material")] == ["warning"]
    reduced, done = good(unclaimed=2)
    assert [c.level for c in found(live(reduced, done), "COV.unclaimed")] == ["warning"]
    assert [c.level for c in found(live(reduced, done, release=True), "COV.unclaimed")] == ["error"]
    plus = good(options=T.DrawingOptions(scheme="plusminus"))[0]
    printed = replace(plus, options=replace(plus.options, process="printed"))
    assert {c.level for c in found(C.run_checks(plus), "R13.plusminus")} == {"warning"}
    assert {c.level for c in found(C.run_checks(printed), "R13.plusminus")} == {"information"}


def test_a_signature_older_than_an_edit_and_one_person_twice():
    d, _done = good()
    edited = with_dim(d, "d-2", places=2)
    said = found(C.run_checks(edited), "R6.signatures")
    assert {(c.item, c.level) for c in said} == {("CHECKED", "warning"), ("APPROVED", "warning")}
    twice, _w = release.sign(made()[0], "CHECKED", "Ann Example", TODAY)
    (same,) = found(C.run_checks(twice), "R6.signatures", "warning")
    assert same.message == "Ann Example signed both DRAWN and CHECKED"


def test_callout_grammar():
    d, done = good()
    (depth,) = found(_r7_callouts(), "R7.callouts")
    assert "gives a depth, but the hole goes through" in depth.message
    order = ("THRU", "⌵ Ø12.00 X 90°", "⌴ Ø11.00 ↧ 6.5")
    (late,) = found(C.run_checks(with_dim(d, "d-1", suffix=order)), "R7.callouts")
    assert "puts its counterbore line after its countersink line" in late.message
    thread = with_dim(d, "d-1", suffix=("THRU", "M6 x 1-6H THRU"))
    (named,) = found(C.run_checks(thread), "R7.callouts")
    assert "no thread is confirmed" in named.message
    confirmed = replace(
        thread,
        features=tuple(
            replace(r, decisions=(("thread", "M6 x 1-6H"),)) if r.id == "f-5" else r for r in thread.features
        ),
    )
    assert not found(C.run_checks(confirmed), "R7.callouts")
    assert (
        found(C.run_checks(with_dim(d, "d-1", prefix="Ø")), "R7.callouts") == []
    )  # the count is R4.members'
    typ = found(C.run_checks(with_dim(d, "d-1", suffix=("THRU", "TYP"))), "R7.callouts")
    assert [c.message.endswith("says TYP; repetition is stated with nX") for c in typ] == [True]


def test_notes_lettered_too_small_are_reported():
    said = found(_r10_text(), "R10.text")
    assert [(c.item, c.level) for c in said] == [("notes", "error")]
    assert said[0].message == "the notes are lettered 2.7 mm high, below the 3.0 mm minimum"


def _made_with(fields, sheet="A"):
    """The four-holes plate drawn on ``sheet`` with title fields ``fields``."""
    st, fields = _settings(), {**FIELDS, **fields}
    ctx = plate(
        "four_holes",
        patterns=[(k, list(m)) for k, m in SCATTERED],
        options=T.DrawingOptions(sheet=sheet),
        settings=st,
    )
    done = orchestrate.run(_Source("four_holes"), ctx.model, ctx.features, ctx.views, ctx.options, st, fields)
    planned = (done.planned.plan, done.result.sheet, ctx.features)
    return document.new_drawing(
        _Source("four_holes"), planned, done.options, st, fields, today=TODAY, seed="four_holes"
    )


def test_a_long_title_or_drawing_number_stays_at_the_lettering_minimum():
    titled = _made_with({"title": "HOUSING, GEARBOX, LOWER, MACHINED FROM BILLET"})  # on two lines
    assert not found(C.run_checks(titled), "R10.text") and not found(from_file(titled), "R10.text")
    numbered = _made_with({"number": "ABCD-123456-78901"})  # in the CAGE cell's width too
    assert not found(C.run_checks(numbered), "R10.text") and not found(from_file(numbered), "R10.text")
    (said,) = found(from_file(_made_with({"number": "ABCDEFGH-123456-7890-AB"})), "R10.text")
    assert said.item == "number" and said.fixes == ("Edit the Title Block", "Set Sheet")
    assert said.message == (
        "the title block's DWG NO is lettered 2.5 mm high to fit its block, below the 3.0 mm minimum: "
        "shorten it, or use a larger sheet"
    )
    assert not found(C.run_checks(_made_with({"number": "ABCDEFGH-123456-7890-AB"}, "B")), "R10.text")


def test_the_model_cell_shows_the_models_short_hash_whatever_the_part_number():
    long = _made_with({"part_number": "BRACKET-MOTOR-MOUNT-LEFT-HAND-SIDE"})
    for checks in (C.run_checks(long), from_file(long)):
        assert not [c for c in found(checks, "R6.title") if c.item == "model"]
    hashed = "AB" * 8
    painted = tuple(
        replace(p, text=p.text.replace(hashed, "AB…")) if isinstance(p, D.TextRun) and hashed in p.text else p
        for p in long.sheet.painted
    )
    cut = replace(long, sheet=replace(long.sheet, painted=painted))
    (said,) = [c for c in found(C.run_checks(cut), "R6.title") if c.item == "model"]
    assert said.message == "the title block's MODEL cell is cut before the model's short hash"
    assert said.level == "error" and said.fixes == ("Lay Out Again",)


def test_the_layouts_own_checks_are_kept_under_their_ids():
    d, done = good()
    own = [
        LayoutCheck("L.overlap", "'40.0' overlaps '30.0'", "d-2"),
        LayoutCheck("L.outside", "'40.0' lies outside the border", "d-2"),
        LayoutCheck("L.reserved", "'40.0' lies in the title, revision or notes block", "d-3"),
        LayoutCheck("L.leader", "a leader stands at 80 degrees, outside 15 to 75", "d-1"),
        LayoutCheck("L.placement", "Ø6.60 could not be placed clear", "d-1"),
        LayoutCheck("L.cramped", "the 2.0 span is cramped at 1:2", ""),
        LayoutCheck("L.characters", "the character U+03A9 is not one the drawing's font has", "", "error"),
        LayoutCheck("L.future", "something new", "d-4", "warning"),
    ]
    said = live(d, replace(done, result=replace(done.result, checks=own)))
    assert [(c.code, c.level, c.item) for c in said] == [
        ("L.future", "warning", "d-4"),
        ("R8.sheet", "error", "d-2"),
        ("R8.sheet", "error", "d-3"),
        ("R10.text", "error", "R10.text"),
        ("R11.collisions", "error", "d-1"),
        ("R11.collisions", "error", "d-2"),
        ("R11.leaders", "warning", "d-1"),
        ("R12.views", "warning", "R12.views"),
    ]
    assert next(c for c in said if c.code == "R12.views").fixes == ("Add Detail View", "Sheet and Scale")


def test_painted_overlaps_spacing_and_leaders_from_the_file():
    (overlap,) = found(_r11_collisions(), "R11.collisions")
    assert overlap.item == "d-2" and "overlaps" in overlap.message
    (spacing,) = found(_r11_spacing(), "R11.spacing")
    assert spacing.item == "d-2" and "the first row stands at least 10 mm off" in spacing.message
    (leader,) = found(_r11_leaders(), "R11.leaders")
    assert leader.item == "d-1" and "outside 15 to 75" in leader.message


def test_the_model_governs_note_is_held_to_its_words():
    d, done = good(unclaimed=2)
    (nid, note) = next((i, n) for i, n in d.notes if n.text.startswith("REDUCED-DIMENSION"))
    assert not found(live(d, done), "R15.process")
    partial = with_note(d, nid, replace(note, frames=()))
    (c,) = found(live(partial, done), "R15.process")
    assert c.item == nid and "the profile tolerance of the undimensioned surfaces" in c.message
    (gone,) = found(live(with_note(d, nid), done), "R15.process")
    assert gone.message == "the drawing has unclaimed geometry and no model-governs note"


# --------------------------------------------------------------------------- the file alone


def test_the_file_alone_answers_what_it_can_and_invents_nothing():
    d, done = good()
    broken = with_dim(with_dim(d, "d-5", state="removed"), "d-1", view="v-2")
    assert {"R4.complete", "R5.true_shape"} <= {c.code for c in live(broken, done)}
    alone = from_file(broken)
    assert not {c.code for c in alone} & set(C.MODEL_ONLY)
    assert C.skipped() == C.MODEL_ONLY and C.skipped(planned=done.planned) == ()
    reduced, _done = good(unclaimed=2)
    (cov,) = found(from_file(reduced), "COV.unclaimed")
    assert cov.level == "warning" and "model-governs note says" in cov.message


def test_a_drawing_without_a_sheet():
    d, _done = good()
    said = C.run_checks(replace(d, sheet=None))
    assert [(c.code, c.item) for c in said] == [("R8.sheet", "sheet")]


# --------------------------------------------------------------------------- release reads the checks


def test_release_blocks_on_unclaimed_geometry_until_a_typed_reason_accepts_it():
    d, done = made()
    profile = d.notes[0][1].frames[0]
    note = document.NoteRecord(
        "REDUCED-DIMENSION DRAWING OF MODEL FOUR_HOLES ABABABABABABABAB. DIMENSIONS SHOWN TAKE PRECEDENCE "
        "OVER THE MODEL. SURFACES NOT DIMENSIONED ARE DEFINED BY THE MODEL WITHIN",
        (profile,),
    )
    reduced = replace(
        d,
        notes=d.notes + (("n-6", note),),
        coverage=T.Coverage(
            features=8, features_unclaimed=1, faces=20, faces_claimed=18, area=1.0, area_claimed=0.9
        ),
    )
    reduced, _done = signed(reduced, done)
    problems = release.release_problems(reduced, checks=C.run_checks(reduced, release=True))
    assert len(problems) == 1 and problems[0].startswith("COV.unclaimed (reduced-dimension drawing: 2 faces")
    reason = {"COV.unclaimed": "the free-form faces are defined by the model"}
    assert release.release_problems(reduced, reason, checks=C.run_checks(reduced, release=True)) == ()
    released = release.release(reduced, TODAY, reason, checks=C.run_checks(reduced, release=True))
    assert released.accepted == (("COV.unclaimed", reason["COV.unclaimed"]),)
    assert [c.level for c in found(C.run_checks(released), "COV.unclaimed")] == ["information"]
    # a missing model-governs note is not something a reason accepts
    bare = signed(with_note(reduced, "n-6"), done)[0]
    assert release.release_problems(bare, reason, checks=C.run_checks(bare, release=True)) == (
        "check R15.process: the drawing has unclaimed geometry and no model-governs note",
    )


def test_release_reads_the_other_release_time_checks():
    d, _done = made()
    problems = release.release_problems(d, checks=C.run_checks(d, release=True))
    assert "check R6.signatures: CHECKED is not signed" in problems
    gd, _done = good()
    assert release.release_problems(gd, checks=C.run_checks(gd, release=True)) == ()


# --------------------------------------------------------------------------- order and speed


def _natural(text):
    return [int(p) if p.isdigit() else p for p in re.split(r"([0-9]+)", text)]


def test_the_order_is_fixed():
    d, done = made(small_notes=True)
    noisy = with_dim(with_dim(d, "d-5", state="removed"), "d-2", override="105.0")
    a = live(noisy, done)
    rebuilt = made.__wrapped__(small_notes=True)
    assert live(noisy, rebuilt[1]) == a
    keys = [(_natural(c.code), _natural(c.item)) for c in a]
    assert keys == sorted(keys)
    assert [c.code for c in a][:2] == ["R2.override", "R3.roles"]


def test_a_hundred_hole_plate_checks_quickly():
    xt, truth = P.random_plate(3, n=100)
    m = facegraph.from_transmit(xt)
    by_size: dict[float, list[int]] = {}
    for k, h in enumerate(truth["holes"]):
        by_size.setdefault(round(h["diameter"], 6), []).append(k)
    groups = [("scattered", ks) for ks in by_size.values() if len(ks) > 1]
    ctx = plate((m, truth), patterns=groups, settings=_settings())
    planned = make_plan(ctx)
    result = layout(planned, options=ctx.options, settings=ctx.settings)
    d = document.new_drawing(
        _Source("plate"),
        (planned.plan, result.sheet, ctx.features),
        ctx.options,
        ctx.settings,
        FIELDS,
        today=TODAY,
    )
    assert len(d.dimensions) >= 190
    t0 = time.perf_counter()
    said = C.run_checks(d, planned=planned, layout=result)
    took = time.perf_counter() - t0
    assert took < 0.3  # measured about 0.006 s on the VM
    t0 = time.perf_counter()
    C.run_checks(d)
    assert time.perf_counter() - t0 < 0.3
    assert not found(said, "R4.complete") and not found(said, "R4.redundant")


# --------------------------------------------------------------------------- the o11 fixture


@functools.cache
def _o11():
    st = _settings()
    path = fixture("o11_curved.SLDPRT")
    d = make_drawing(path, settings=st, fields=FIELDS)
    run = pipeline.run(path, until="views", settings=st, fields=FIELDS)
    signed = {g.row: (g.name, g.date) for g in d.signatures}
    done = orchestrate.run(
        run.source,
        run.model,
        run.features,
        run.views,
        T.DrawingOptions(),
        st,
        FIELDS,
        revisions=d.revisions,
        status=d.status,
        signed=signed,
    )
    return d, done


def test_the_o11_drawing_has_no_error_level_check():
    d, done = _o11()
    said = live(d, done)
    assert not [c for c in said if c.level == "error"], [c.message for c in said if c.level == "error"]
    assert not [c for c in said if c.level == "warning"]
    assert not [c for c in from_file(d) if c.level == "error"]
    assert d.checks == C.run_checks(d, planned=done.planned, layout=done.result)  # the pipeline checks it


def test_a_partial_hole_takes_r():
    d, done = good()
    ctx = done.planned.detail.ctx
    hole = ctx.features.features[0]
    assert isinstance(hole, T.Hole) and hole.cover > math.pi
    features = (replace(hole, cover=math.radians(160)), *ctx.features.features[1:])
    partial = replace(ctx, features=replace(ctx.features, features=features))
    one = with_dim(d, "d-1", features=("f-1",))
    (c,) = found(live(one, with_detail(done, ctx=partial)), "R5.true_shape")
    assert c.item == "d-1" and "an arc of 160 degrees; arcs of 180 degrees or less take R" in c.message
    assert not found(live(one, done), "R5.true_shape")
