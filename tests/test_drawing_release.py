"""Status, signatures, release and revisions (docs/DRAWINGS.md 13.2, 13.3, 17.2;
dwg-file)."""

from dataclasses import replace

import pytest

from solidseas.drawing import document as doc
from solidseas.drawing import release as R
from solidseas.drawing import settings as S
from solidseas.drawing import standards
from solidseas.drawing import types as T
from solidseas.errors import InvalidArgumentError
from test_drawing_file import TODAY, made, people_settings


def fresh(**people):
    """A new drawing whose settings' people group has ``people`` changed."""
    s = people_settings()
    for key, value in people.items():
        s = S.with_value(s, "people", key, value)
    return made(settings=s)


def signed(d=None):
    d = d or fresh()
    d, _w = R.sign(d, "CHECKED", "Carl Dee", TODAY)
    d, _w = R.sign(d, "APPROVED", "AB", TODAY)  # initials name a person too
    return d


def test_a_new_drawing_is_preliminary_with_drawn_only():
    d = fresh()
    assert R.status(d) == R.PRELIMINARY
    assert [s.row for s in d.signatures] == ["DRAWN"]
    assert R.current_revision(d) == "A"


def test_signing_checked_moves_the_status_and_records_the_digest():
    d, warnings = R.sign(fresh(), "CHECKED", "Carl Dee", "2026-10-05")
    assert warnings == () and d.status == R.CHECKED
    s = dict((x.row, x) for x in d.signatures)["CHECKED"]
    assert s == T.Signature("CHECKED", "Carl Dee", "2026-10-05", R.content_digest(d))
    d2, _w = R.sign(d, "APPROVED", "Carl Dee", "2026-10-05")
    assert d2.status == R.CHECKED and [x.row for x in d2.signatures] == ["DRAWN", "CHECKED", "APPROVED"]


def test_only_rows_the_settings_name_may_be_signed_by_people_they_list():
    d = fresh()
    with pytest.raises(InvalidArgumentError) as info:
        R.sign(d, "QA", "Carl Dee", TODAY)
    assert info.value.detail["rule"] == "row"
    with pytest.raises(InvalidArgumentError) as info:
        R.sign(d, "CHECKED", "Somebody Else", TODAY)
    assert info.value.detail["rule"] == "not_in_people"
    nobody = made(settings=S.DrawingSettings())
    with pytest.raises(InvalidArgumentError) as info:
        R.sign(nobody, "CHECKED", "Carl Dee", TODAY)
    assert info.value.detail["rule"] == "no_people"
    with pytest.raises(InvalidArgumentError):
        R.sign(d, "CHECKED", "Carl Dee", "05/10/2026")
    with_qa = fresh(rows=["DRAWN", "CHECKED", "APPROVED", "QA"])
    d3, _w = R.sign(with_qa, "QA", "Carl Dee", TODAY)
    assert "QA" in [s.row for s in d3.signatures]


def test_one_person_on_two_rows_is_a_warning_or_an_error_as_the_settings_say():
    d, _w = R.sign(fresh(), "CHECKED", "Ann Bee", TODAY)  # Ann Bee drew it
    assert _w == ("Ann Bee also signed DRAWN",)
    strict = fresh(same_person_twice=False)
    with pytest.raises(InvalidArgumentError) as info:
        R.sign(strict, "CHECKED", "ab", TODAY)
    assert info.value.detail["rule"] == "same_person"


def test_a_row_is_signed_once_until_an_edit_clears_it():
    d, _w = R.sign(fresh(), "CHECKED", "Carl Dee", TODAY)
    with pytest.raises(InvalidArgumentError) as info:
        R.sign(d, "CHECKED", "Carl Dee", TODAY)
    assert info.value.detail["rule"] == "signed"


def test_the_content_digest_covers_content_not_records():
    d = signed()
    digest = R.content_digest(d)
    same = [
        replace(d, status=R.PRELIMINARY),
        replace(d, signatures=()),
        replace(d, outputs=(T.Output("pdf", "x.pdf", "0" * 64, "A"),)),
        replace(d, sheet=None),
        replace(d, modified="2027-01-01T00:00:00+00:00"),
        replace(d, model=dict(d.model, relative=None, stored="C:\\elsewhere\\bracket.SLDPRT")),
        replace(d, revisions=(replace(d.revisions[0], date=TODAY, approved="Carl Dee"),)),
    ]
    assert all(R.content_digest(x) == digest for x in same)
    differ = [
        replace(d, notes=()),
        replace(d, title=d.title[1:]),
        replace(d, dimensions=(replace(d.dimensions[0], state="removed"), *d.dimensions[1:])),
        replace(d, features=d.features[:1]),
        replace(d, model=dict(d.model, sha256="9" * 64)),
        replace(d, options=replace(d.options, scheme="plusminus")),
        replace(d, settings=S.with_value(d.settings, "company", "phone", "555 0100")),
        replace(d, revisions=(replace(d.revisions[0], description="FIRST"),)),
    ]
    assert all(R.content_digest(x) != digest for x in differ)


def test_an_edit_clears_the_signatures_it_invalidates_and_says_so():
    d = signed()
    unchanged, said = R.invalidate(d)
    assert unchanged is d and said == ()
    edited = replace(d, notes=())
    after, said = R.invalidate(edited)
    assert [s.row for s in after.signatures] == ["DRAWN"]
    assert after.status == R.PRELIMINARY
    assert said == (
        "the edit cleared the CHECKED signature of Carl Dee",
        "the edit cleared the APPROVED signature of Ann Bee",
    )


def test_release_needs_the_required_rows_signed_and_current():
    with pytest.raises(R.ReleaseRefusedError) as info:
        R.release(fresh(), TODAY)
    assert info.value.reasons == ("CHECKED is not signed", "APPROVED is not signed")
    assert info.value.detail["rule"] == "release_refused"
    stale = replace(signed(), notes=())
    assert R.release_problems(stale) == (
        "the CHECKED signature is older than the drawing's last change; sign it again",
        "the APPROVED signature is older than the drawing's last change; sign it again",
    )
    only_checked = fresh(required=["CHECKED"])
    d, _w = R.sign(only_checked, "CHECKED", "Carl Dee", TODAY)
    assert R.release_problems(d) == ()


def test_release_sets_released_and_fills_the_revision_row():
    d = R.release(signed(), "2026-10-07")
    assert d.status == R.RELEASED
    assert d.revisions[-1] == T.Revision("A", "INITIAL RELEASE", (), "2026-10-07", "Ann Bee")
    assert isinstance(d, doc.DrawingDocument) and d.accepted == ()
    again, problems = doc.loads(doc.dumps(d))
    assert problems == [] and again.status == R.RELEASED and again.revisions == d.revisions
    assert R.release_problems(d) == ("the drawing is already released",)


def test_error_checks_block_release_unless_accepted_with_a_typed_reason():
    d = signed()
    checks = (
        {"level": "error", "code": "COV.unclaimed", "item": "face-12", "message": "2 faces are unclaimed"},
        {"level": "error", "code": "R2.override", "message": "a value was overridden"},
        {"level": "warning", "code": "L.crowded", "message": "crowded"},
    )
    assert R.release_problems(d, checks=checks) == (
        "COV.unclaimed (2 faces are unclaimed) needs a typed reason to be accepted",
        "R2.override (a value was overridden) needs a typed reason to be accepted",
    )
    accepted = {"face-12": "free-form face, defined by the model", "R2.override": "customer drawing value"}
    out = R.release(d, TODAY, accepted, checks=checks)
    assert out.accepted == (
        ("face-12", "free-form face, defined by the model"),
        ("R2.override", "customer drawing value"),
    )
    blocking = ({"level": "error", "code": "G.cycle", "message": "a loop of dimensions"},)
    with pytest.raises(R.ReleaseRefusedError) as info:
        R.release(d, TODAY, {"G.cycle": "please"}, checks=blocking)
    assert info.value.reasons == ("check G.cycle: a loop of dimensions",)
    with pytest.raises(R.ReleaseRefusedError):
        R.release(d, TODAY, {"face-12": "   "}, checks=checks[:1])


def test_an_unmapped_material_must_be_accepted_as_typed():
    d = made(fields={"material": "UNOBTAINIUM", "drawn_by": "Ann Bee"})
    d = signed(d)
    assert R.release_problems(d) == (
        "the material is not in the materials list; map it or accept it as typed",
    )
    out = R.release(d, TODAY, {"material": "customer specification"})
    assert ("material", "customer specification") in out.accepted
    mapped = signed(made(fields={"material": "pla", "drawn_by": "Ann Bee"}))
    assert R.release_problems(mapped) == ()


def test_a_dimension_needing_attention_blocks_release():
    d = signed()
    flagged = replace(d, dimensions=(replace(d.dimensions[0], flags=("needs_attention",)), *d.dimensions[1:]))
    flagged = replace(
        flagged, signatures=tuple(replace(s, digest=R.content_digest(flagged)) for s in d.signatures)
    )
    assert R.release_problems(flagged) == ("dimension d-1 needs attention",)


def test_a_released_drawing_refuses_edits():
    d = R.release(signed(), TODAY)
    for call in (
        lambda: R.sign(d, "CHECKED", "Carl Dee", TODAY),
        lambda: R.invalidate(d),
        lambda: R.require_editable(d),
    ):
        with pytest.raises(InvalidArgumentError) as info:
            call()
        assert info.value.detail == {"parameter": "drawing", "rule": "drawing_released"}
        assert info.value.code == "drawing_released"


def test_start_revision_takes_the_next_letter_and_starts_over():
    d = R.release(signed(), TODAY)
    b = R.start_revision(d, "MOVED HOLE f-2", ["B3", "C4"], drawn_by="Ann Bee", today="2026-11-01")
    assert b.status == R.PRELIMINARY and R.current_revision(b) == "B"
    assert b.revisions[-1] == T.Revision("B", "MOVED HOLE f-2", ("B3", "C4"))
    assert b.revisions[0].date == TODAY  # the released row stays as it was
    assert [s.row for s in b.signatures] == ["DRAWN"] and b.signatures[0].date == "2026-11-01"
    assert doc.export_name(b, "pdf") == "1234-001 B PRELIMINARY.pdf"
    assert R.start_revision(d, "X").signatures == ()
    with pytest.raises(InvalidArgumentError) as info:
        R.start_revision(b, "AGAIN")
    assert info.value.detail["rule"] == "not_released"
    for bad in (("", ()), ("OK", ("b3",)), ("OK", ("B3",) * 201), ("two\nlines", ())):
        with pytest.raises(InvalidArgumentError):
            R.start_revision(d, *bad)


@pytest.mark.parametrize(
    "mark, after", [("A", "B"), ("H", "J"), ("N", "P"), ("R", "T"), ("Y", "AA"), ("AY", "BA")]
)
def test_revision_letters_skip_i_o_q_s_x_and_z(mark, after):
    d = R.release(signed(), TODAY)
    d = replace(d, revisions=(T.Revision(mark, "x"),))
    assert R.current_revision(R.start_revision(d, "NEXT")) == after == standards.next_revision(mark)


def test_the_release_record_must_match_the_files():
    d = R.release(signed(), TODAY)
    d = doc.record_output(d, "pdf", "1234-001 A.pdf", "1" * 64)
    d = doc.record_output(d, "dxf", "1234-001 A.dxf", "2" * 64)
    assert R.check_release_record(d, {"1234-001 A.pdf": "1" * 64, "1234-001 A.dxf": "2" * 64}) == ()
    assert R.check_release_record(d, lambda name: {"1234-001 A.pdf": "1" * 64}.get(name)) == (
        R.RECORD_MISMATCH,
        "1234-001 A.dxf is not there",
    )
    assert (
        R.check_release_record(d, {"1234-001 A.pdf": "9" * 64, "1234-001 A.dxf": "2" * 64})[0]
        == R.RECORD_MISMATCH
    )
    forged = replace(d, notes=())  # someone edited a released file by hand
    assert R.SIGNATURES_MISMATCH in R.check_release_record(
        forged, {"1234-001 A.pdf": "1" * 64, "1234-001 A.dxf": "2" * 64}
    )
    assert R.check_release_record(signed(), {}) == ()  # only a drawing claiming RELEASED is checked


def test_the_status_survives_the_file_and_a_bad_one_falls_back():
    d = signed()
    again, problems = doc.loads(doc.dumps(d))
    assert problems == [] and again.status == R.CHECKED and again.signatures == d.signatures
