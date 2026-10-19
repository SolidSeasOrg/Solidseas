"""Bodies hidden in SOLIDWORKS are left out of a 3D print, as SOLIDWORKS leaves them out
of what it exports and as the STEP export already does. A body's hidden state is its
shown attribute (FORMAT.md 10.9); test_step.py's _with_flags sets it."""

import pytest

from solidseas import geometry as geo
from solidseas import open_document
from solidseas.errors import InvalidArgumentError, NothingToExportError
from solidseas.export import print_model
from solidseas.tessellate import tessellate_document
from support import fixture_path
from test_step import _with_flags

O12 = "o12_multibody.SLDPRT"


def _print(name: str, **kw):
    with open_document(fixture_path(name)) as doc:
        return print_model(doc, **kw)


def test_a_hidden_body_is_left_out_of_a_print_and_said(monkeypatch):
    both = _print(O12)
    _with_flags(monkeypatch, (0, 1))
    one = _print(O12)
    assert 0 < one.counts["triangles"] < both.counts["triangles"]
    said = [w.message for w in one.warnings if w.code == "bodies_left_out"]
    assert said == [
        "1 body is hidden in SOLIDWORKS and left out, as SOLIDWORKS leaves hidden bodies out of what it "
        "exports"
    ]
    assert not any(w.code == "bodies_left_out" for w in both.warnings)


def test_a_part_whose_bodies_are_all_hidden_prints_nothing(monkeypatch):
    _with_flags(monkeypatch, (0, 0))
    with pytest.raises(NothingToExportError) as caught:
        _print(O12)
    assert caught.value.detail == {"rule": "hidden"}


def test_a_body_whose_state_is_not_known_is_printed(monkeypatch):
    both = _print(O12)
    _with_flags(monkeypatch, (2, None))  # neither 0 nor 1, and no attribute at all
    assert _print(O12).counts["triangles"] == both.counts["triangles"]


def test_the_tessellator_keeps_hidden_bodies_unless_asked(monkeypatch):
    _with_flags(monkeypatch, (0, 1))
    with open_document(fixture_path(O12)) as doc:
        every = tessellate_document(doc)
        shown = tessellate_document(doc, include_hidden=False)
    assert every.counts["bodies"] == 2 and shown.counts["bodies"] == 1


def test_an_assembly_component_whose_bodies_are_hidden_is_not_tessellated(monkeypatch):
    _with_flags(monkeypatch, (0,))  # the box each instance of o08 places, hidden
    with open_document(fixture_path("o08_asm_2x_boxA.SLDASM")) as doc:
        kept = geo.display_geometry(doc, sources=("brep",))
        left = geo.display_geometry(doc, sources=("brep",), brep_options={"include_hidden": False})
    assert len(kept.instances) == 2 and not kept.skipped
    assert not left.instances and {s.reason for s in left.skipped} == {"bodies_not_asked"}


def test_brep_options_names_include_hidden_among_its_keys():
    with open_document(fixture_path("o08_asm_2x_boxA.SLDASM")) as doc:
        with pytest.raises(InvalidArgumentError) as caught:
            geo.display_geometry(doc, brep_options={"hidden": False})
    assert "include_hidden" in str(caught.value)
