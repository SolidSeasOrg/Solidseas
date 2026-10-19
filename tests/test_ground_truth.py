"""The library against what SOLIDWORKS itself reported about every fixture.

The fixture kit reopened each document it made, read-only, and recorded what the
SOLIDWORKS API reported about it in ``tests/fixtures/ground_truth.json``
(``tests/fixtures/README.md``). These tests compare the library's reading of all
19 native fixtures with that record: document type and version history, unit
system, configurations and the active one, file and configuration properties,
materials, solid bodies per stored partition, every component instance of the
assemblies with its flags and placement, virtual parts as nested documents, and
the models a drawing's views show.

Where the library and SOLIDWORKS disagree, the case goes into ``KNOWN`` and
becomes a strict xfail, so a fix is noticed: the case then passes, which fails
the run until its entry is removed. A strict xfail does not notice a change that
makes the disagreement worse, since the case still fails. ``KNOWN`` is empty:
o14's date and double properties, which used to read as linked, now agree.
The deprecated ``Reference.quantity`` keeps its 0.1 meaning on purpose, every
stored instance of every configuration together, and is checked for that
meaning; ``Document.reference_set`` gives the count SOLIDWORKS reports.
``test_components_ground_truth.py`` checks the component trees, the drawings'
sheets and views, reference resolution and the path report against the same
record.
"""

import datetime
import json
import re
from collections import Counter

import pytest

from builders import fixture_streams, rebuild
from solidseas import open_document
from solidseas.errors import SolidSeasDeprecationWarning
from support import FIXTURES

GROUND_TRUTH = json.loads((FIXTURES / "ground_truth.json").read_text(encoding="utf-8"))
CULTURE = GROUND_TRUTH["_generation"]["culture"]
DOCUMENTS = sorted(k for k, v in GROUND_TRUTH.items() if v.get("type") in ("part", "assembly", "drawing"))
PARTS = [d for d in DOCUMENTS if GROUND_TRUTH[d]["type"] == "part"]
ASSEMBLIES = [d for d in DOCUMENTS if GROUND_TRUTH[d]["type"] == "assembly"]
DRAWINGS = [d for d in DOCUMENTS if GROUND_TRUTH[d]["type"] == "drawing"]
MODELS = PARTS + ASSEMBLIES

# swDocumentTypes_e and swUnitSystem_e from the SOLIDWORKS API, with the length and mass
# units each system other than Custom implies.
DOC_TYPES = {1: "part", 2: "assembly", 3: "drawing"}
UNIT_SYSTEMS = {1: ("CGS", "cm", "g"), 2: ("MKS", "m", "kg"), 3: ("IPS", "in", "lb"), 5: ("MMGS", "mm", "g")}
PROPERTY_TYPES = {"Text": "text", "Number": "number", "Yes or no": "boolean", "Date": "date"}

# Where the library disagrees with SOLIDWORKS today: {(document, property or None): reason}.
KNOWN: dict[tuple[str, str | None], str] = {}


def _param(name: str, *rest, key: str | None = None):
    reason = KNOWN.get((name, key))
    marks = [pytest.mark.xfail(strict=True, reason=reason)] if reason else []
    return pytest.param(name, *rest, marks=marks, id="-".join([name, *(str(r) for r in rest)]))


def _api(name: str) -> dict:
    return GROUND_TRUTH[name]["api"]


def _active(name: str) -> dict:
    api = _api(name)
    return api["configurations"][api["active_configuration"]]


# --------------------------------------------------------------------------- type, version, units
@pytest.mark.parametrize("name", DOCUMENTS)
def test_document_type_and_version_history(name):
    api = _api(name)
    with open_document(FIXTURES / name) as doc:
        assert doc.doc_type == DOC_TYPES[api["document_type"]]
        versions = [e.version for e in doc.saved_version.history]
    assert versions == [int(v.split("[", 1)[0]) for v in api["version_history"]]


@pytest.mark.parametrize("name", DOCUMENTS)
def test_unit_system(name):
    system, length, mass = UNIT_SYSTEMS[_api(name)["unit_system"]]
    with open_document(FIXTURES / name) as doc:
        assert (doc.units["system"], doc.units["length"], doc.units["mass"]) == (system, length, mass)


# --------------------------------------------------------------------------- configurations
@pytest.mark.parametrize("name", MODELS)
def test_configurations_and_the_active_one(name):
    api = _api(name)
    with open_document(FIXTURES / name) as doc:
        assert [c.name for c in doc.configurations] == api["configuration_names"]
        assert doc.active_configuration == api["active_configuration"]
        assert [(c.comment or "") for c in doc.configurations] == [
            api["configurations"][c]["comment"] for c in api["configuration_names"]
        ]


@pytest.mark.parametrize("name", DRAWINGS)
def test_a_drawing_has_no_configuration(name):
    with open_document(FIXTURES / name) as doc:
        assert doc.configurations == []


@pytest.mark.parametrize("name", DRAWINGS)
def test_a_drawing_has_no_active_configuration(name):
    with open_document(FIXTURES / name) as doc:
        assert doc.active_configuration is None


# --------------------------------------------------------------------------- properties
def _matches(prop, reported: dict, *, linked: bool = True) -> None:
    """The library's ``prop`` against one property as SOLIDWORKS reported it: type and
    value, and unless ``linked`` is False, whether it is linked and to what."""
    assert prop.type == PROPERTY_TYPES[reported["type"]], prop.name
    shown = reported["evaluated"]
    if prop.type == "text":
        assert prop.value == shown
    elif prop.type == "number":
        assert prop.value == float(shown)
    elif prop.type == "boolean":
        assert prop.value is (shown == "Yes")
    else:
        # SOLIDWORKS shows the date in the generating account's short date format; the file
        # stores noon local time of that date.
        assert CULTURE["short_date_pattern"] == "M/d/yyyy"
        month, day, year = (int(x) for x in shown.split("/"))
        offset = datetime.timezone(datetime.timedelta(minutes=CULTURE["utc_offset_minutes_2024_03_15_noon"]))
        assert (year, month, day) == (2024, 3, 15)  # the date the offset was recorded for
        assert prop.value.astimezone(offset).replace(tzinfo=None) == datetime.datetime(year, month, day, 12)
    if linked:
        # A property is linked when its stored expression is not the value it shows.
        expected = reported["expression"] != shown
        assert prop.linked is expected
        if expected:
            assert prop.expression == reported["expression"]


FILE_PROPERTIES = [(d, p["name"]) for d in MODELS for p in _active(d)["file_properties"]]


def _file_property(name: str, prop: str):
    reported = next(p for p in _active(name)["file_properties"] if p["name"] == prop)
    with open_document(FIXTURES / name) as doc:
        return next(p for p in doc.properties if p.name == prop), reported


@pytest.mark.parametrize("name", MODELS)
def test_file_property_names(name):
    with open_document(FIXTURES / name) as doc:
        names = [p.name for p in doc.properties]
    assert names == [p["name"] for p in _active(name)["file_properties"]]


@pytest.mark.parametrize(("name", "prop"), [_param(d, p) for d, p in FILE_PROPERTIES])
def test_file_property_type_and_value(name, prop):
    _matches(*_file_property(name, prop), linked=False)


@pytest.mark.parametrize(("name", "prop"), [_param(d, p, key=p) for d, p in FILE_PROPERTIES])
def test_file_property_link(name, prop):
    _matches(*_file_property(name, prop))


# --------------------------------------------------------------------------- what linked means
O14 = "o14_property_types.SLDPRT"
O14_END = b"</propertySection></Properties>"


def _o14_properties(custom_xml: bytes | None = None) -> dict:
    source = rebuild(FIXTURES / O14, {"docProps/custom.xml": custom_xml}) if custom_xml else FIXTURES / O14
    with open_document(source) as doc:
        return {p.name: p for p in doc.properties}


def test_a_value_as_typed_is_not_a_link():
    """``Contents/CusProps`` keeps a date and a number as they were typed, the XML in its
    stored form. That difference links nothing (SOLIDWORKS reports both unlinked), and
    ``expression`` keeps the typed text; the two real links come from hidden properties."""
    props = _o14_properties()
    date, double = props["DateProp"], props["DoubleProp"]
    assert (date.text, date.expression, date.linked) == ("2024-03-15T16:00:00Z", "3/15/2024", False)
    assert (double.text, double.expression, double.linked) == ("3.250000", "3.25", False)
    assert [n for n, p in props.items() if p.linked] == ["Mass", "Material"]
    assert {props[n].expression_source for n in ("Mass", "Material")} == {"pid|0x01000000"}


def test_a_link_only_cusprops_holds_is_still_a_link():
    """Without the hidden properties, the expression comes from CusProps, which stores the
    link with its evaluated value beside it: still linked."""
    xml = fixture_streams(FIXTURES / O14)["docProps/custom.xml"]
    stripped, n = re.subn(rb'<property name="" pid="1677722[45]"[^>]*>.*?</property>', b"", xml)
    assert n == 2
    props = _o14_properties(stripped)
    for name in ("Mass", "Material"):
        assert props[name].linked, name
        assert props[name].expression_source == "Contents/CusProps"
        assert props[name].expression == f'"SW-{name}@{O14}"'
    assert not props["DateProp"].linked and not props["DoubleProp"].linked


def test_a_hidden_expression_links_only_when_it_is_not_a_literal_of_the_type():
    xml = fixture_streams(FIXTURES / O14)["docProps/custom.xml"]
    hidden = {
        3: "Plain text value",  # TextProp: the same text
        # DateProp, stored as 2024-03-15T16:00:00Z: a date as typed is not taken for a
        # literal (its form follows the saving machine's locale), so it reads as linked
        4: "3/15/2024",
        5: "&quot;D1@Sketch1@o14_property_types.SLDPRT&quot;",  # NumberProp: a dimension link
        6: "3.25",  # DoubleProp, stored as 3.250000: the same number
        7: "yes",  # YesNoProp, stored as Yes: the same answer
    }
    extra = "".join(
        f'<property name="" pid="{0x01000000 | pid}" IsEquation="False" TypeID="30">'
        f"<vt:lpstr>{text}</vt:lpstr></property>"
        for pid, text in hidden.items()
    )
    props = _o14_properties(xml.replace(O14_END, extra.encode() + O14_END))
    assert {n: p.linked for n, p in props.items()} == {
        "TextProp": False,
        "DateProp": True,
        "NumberProp": True,
        "DoubleProp": False,
        "YesNoProp": False,
        "Mass": True,
        "Material": True,
    }
    assert props["NumberProp"].expression == f'"D1@Sketch1@{O14}"'
    assert props["DoubleProp"].expression == "3.25"
    date = props["DateProp"]
    assert (date.expression, date.expression_source, date.text) == (
        "3/15/2024",
        "pid|0x01000000",
        "2024-03-15T16:00:00Z",
    )


@pytest.mark.parametrize("name", MODELS)
def test_configuration_properties_and_materials(name):
    api = _api(name)
    with open_document(FIXTURES / name) as doc:
        for cfg in doc.configurations:
            reported = api["configurations"][cfg.name]
            assert [p.name for p in cfg.properties] == [
                p["name"] for p in reported["configuration_properties"]
            ]
            for prop, rep in zip(cfg.properties, reported["configuration_properties"], strict=True):
                _matches(prop, rep)
            if GROUND_TRUTH[name]["type"] == "part":
                assert (cfg.material, cfg.material_database) == (
                    reported["material"],
                    reported["material_database"],
                )


# --------------------------------------------------------------------------- bodies
@pytest.mark.parametrize("name", PARTS)
def test_solid_bodies_of_every_stored_partition(name):
    """Each configuration whose partition the file stores yields as many solid bodies as
    SOLIDWORKS reported for it; a configuration without one yields none."""
    stored = set(GROUND_TRUTH[name]["kit_container_scan"]["partition_streams"])
    api = _api(name)
    with open_document(FIXTURES / name) as doc:
        ids = {c.name: c.id for c in doc.configurations}
        result = doc.parasolid()
    assert result.problems == []
    for cfg, reported in api["configurations"].items():
        bodies = [b for b in result.bodies if b.configuration_name == cfg]
        if f"Contents/Config-{ids[cfg]}-Partition" in stored:
            assert sorted(b.body_type for b in bodies) == ["solid"] * reported["solid_bodies"], cfg
        else:
            assert bodies == [], cfg
    assert len(result.bodies) == sum(
        api["configurations"][c]["solid_bodies"]
        for c in api["configurations"]
        if f"Contents/Config-{ids[c]}-Partition" in stored
    )


# --------------------------------------------------------------------------- assembly components
def _matrix(ad: list[float]) -> tuple[list[list[float]], list[float]]:
    """``IMathTransform.ArrayData``: elements 0 to 8 are the images of the X, Y and Z axes
    (the columns of R in p' = R p + t), 9 to 11 are t."""
    return [[ad[3 * j + i] for j in range(3)] for i in range(3)], list(ad[9:12])


def _relative(parent: list[float], child: list[float]) -> list[float]:
    """The child's placement in its parent's frame, from both placements in the top
    assembly's frame: R = Rp^T Rc, t = Rp^T (tc - tp)."""
    rp, tp = _matrix(parent)
    rc, tc = _matrix(child)
    r = [[sum(rp[k][i] * rc[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    t = [sum(rp[k][i] * (tc[k] - tp[k]) for k in range(3)) for i in range(3)]
    return [r[i][j] for j in range(3) for i in range(3)] + t


def _stored_as_array_data(stored: tuple[float, ...]) -> list[float]:
    """The 16 numbers of ``swTransform`` in ArrayData order (``docs/FORMAT.md`` 12.1)."""
    return [*stored[0:3], *stored[4:7], *stored[8:11], *stored[12:15]]


def _rounded(values) -> tuple[float, ...]:
    return tuple(round(v, 9) + 0.0 for v in values)


def _reported_instances(name: str, *, hidden: bool = False) -> list[tuple]:
    """Every component instance SOLIDWORKS reported, in each configuration of the
    assembly, with its placement relative to its parent. An instance inside a
    sub-assembly is listed once per sub-assembly configuration, as the file stores it."""
    rows, seen = [], set()
    for cfg in _api(name)["configurations"].values():
        by_name = {c["name"]: c for c in cfg["components"]}
        for c in cfg["components"]:
            ad = c["transform_array_data"][:12]
            if c["parent"] is not None:
                parent = by_name[c["parent"]]
                key = (parent["file_name"], parent["referenced_configuration"], c["name"].rsplit("/", 1)[-1])
                if key in seen:
                    continue
                seen.add(key)
                ad = _relative(parent["transform_array_data"], ad)
            flags = (c["suppressed"], c["exclude_from_bom"], c["virtual"]) + (
                (c["hidden"],) if hidden else ()
            )
            rows.append(
                (
                    c["file_name"],
                    c["name"].rsplit("/", 1)[-1],
                    c["referenced_configuration"],
                    *flags,
                    _rounded(ad),
                )
            )
    return sorted(rows)


def _library_instances(name: str, *, hidden: bool = False) -> list[tuple]:
    rows = []
    with open_document(FIXTURES / name) as doc:
        for ref in doc.references():
            for i in ref.instances:
                flags = (i.suppressed, i.exclude_from_bom, ref.virtual) + ((i.hidden,) if hidden else ())
                ad = _stored_as_array_data(i.transform)
                rows.append((ref.file_name, i.name, i.configuration, *flags, _rounded(ad)))
    return sorted(rows)


@pytest.mark.parametrize("name", ASSEMBLIES)
def test_component_instances_flags_and_placements(name):
    """File, instance name, referenced configuration, suppressed, excluded from the BOM,
    virtual, and the placement to 1e-9, for every instance in every configuration."""
    assert _library_instances(name) == _reported_instances(name)


@pytest.mark.parametrize("name", ASSEMBLIES)
def test_component_hidden_flags(name):
    assert _library_instances(name, hidden=True) == _reported_instances(name, hidden=True)


def _active_counts(name: str) -> dict[str, int]:
    """The instances of each file SOLIDWORKS reported in the active configuration,
    sub-assemblies expanded."""
    expected: dict[str, int] = {}
    for c in _active(name)["components"]:
        expected[c["file_name"]] = expected.get(c["file_name"], 0) + 1
    return expected


@pytest.mark.parametrize("name", ASSEMBLIES)
def test_reference_quantity_keeps_its_0_1_meaning(name):
    """``Reference.quantity`` (deprecated, API C9) keeps its 0.1 meaning: every instance the
    file stores of the referenced file, in every configuration and every sub-assembly
    configuration, suppressed ones included. That is SOLIDWORKS' count only for an assembly
    with one configuration whose sub-assemblies have one each (o08, o15); o16's two
    configurations differ, and ``test_reference_set_counts_the_active_configuration`` checks
    the replacement, which counts one."""
    stored = Counter(row[0] for row in _reported_instances(name))
    with open_document(FIXTURES / name) as doc:
        refs = doc.references()
        with pytest.warns(SolidSeasDeprecationWarning):
            quantities = {r.file_name: r.quantity for r in refs}
    assert quantities == dict(stored)


@pytest.mark.parametrize("name", ASSEMBLIES)
def test_reference_set_counts_the_active_configuration(name):
    """``Document.reference_set``, which the ``Reference.quantity`` warning points to, gives
    the count SOLIDWORKS reports for the active configuration."""
    with open_document(FIXTURES / name) as doc:
        files = doc.reference_set().files.values()
        counts = {f.file_name: f.instances for f in files if f.instances}
    assert counts == _active_counts(name)


@pytest.mark.parametrize("name", ASSEMBLIES)
def test_virtual_parts_are_nested_documents(name):
    virtual = {
        c["file_name"]
        for cfg in _api(name)["configurations"].values()
        for c in cfg["components"]
        if c["virtual"]
    }
    with open_document(FIXTURES / name) as doc:
        nested = doc.nested_documents()
        assert len(nested) == len(virtual)
        for stream in nested:
            with doc.open_nested(stream) as inner:
                assert inner.doc_type == "part"


# --------------------------------------------------------------------------- drawings
@pytest.mark.parametrize("name", DRAWINGS)
def test_a_drawing_references_the_models_its_views_show(name):
    shown = {v["referenced_document"] for sheet in _api(name)["sheets"] for v in sheet["views"]}
    with open_document(FIXTURES / name) as doc:
        assert sorted(r.file_name for r in doc.references()) == sorted(shown)
