"""The single serialisable model: the strict encoder, the kind registry and its
schemas, the error object, and the builders behind ``Document.summary()``.

Exact expected values come from the synthetic fixtures (``tests/fixtures``).
Values that depend on the checkout (modification times) are checked against
``os.stat`` instead, and the fixture's saving account is never written here.
"""

import datetime
import decimal
import enum
import json
import math
import os
import re
from pathlib import Path

import pytest

from builders import build_cfb, build_propset, fixture_streams, o06_with_active_alt, rebuild
from jsonschema_subset import validate
from solidseas import model, open_document
from solidseas.errors import (
    WARNING_CODES,
    ConfigurationNotFoundError,
    FileTooLargeError,
    InvalidArgumentError,
    LockedFileError,
    PathRefusedError,
    ReaderWarning,
    SldFormatError,
    SolidSeasDeprecationWarning,
    StreamNotFoundError,
    UnknownFormatError,
)
from solidseas.formats.solidworks import container as container_mod
from solidseas.formats.solidworks.propset import FMTID_USERDEFINED
from support import ASSEMBLY, NATIVE, fixture_path

O04 = fixture_path("o04_boxA_props.SLDPRT")
O06 = fixture_path("o06_boxA_props_mat_cfg.SLDPRT")
API_MD = Path(__file__).resolve().parents[1] / "docs" / "API.md"
SAFE = 2**53 - 1


def strict_loads(text: str):
    def refuse(token):
        raise AssertionError(f"non-standard JSON token {token}")

    return json.loads(text, parse_constant=refuse)


# --------------------------------------------------------------------------- encoder rules
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_dumps_refuses_nan_and_infinity(value):
    for doc in (value, {"x": value}, [1, [value]]):
        with pytest.raises(ValueError):
            model.dumps(doc)
        with pytest.raises(ValueError):  # the builders' own pass refuses it too, not only json.dumps
            model.to_json_data(doc)


def test_dumps_integers_stop_at_2_to_the_53():
    assert model.dumps([SAFE, -SAFE, 0]) == "[9007199254740991,-9007199254740991,0]"
    for big in (SAFE + 1, -(SAFE + 1), 10**30):
        with pytest.raises(ValueError):
            model.dumps({"n": big})


def test_dumps_keeps_booleans_and_null():
    assert model.dumps([True, False, None, 1.5]) == "[true,false,null,1.5]"


def test_lone_surrogates_are_replaced():
    assert model.dumps("a\udc80b") == '"a\\ufffdb"'
    assert model.dumps({"k\ud800": 1}) == '{"k\\ufffd":1}'
    assert model.to_json_data(["x\udfff"]) == ["x\ufffd"]
    # a valid pair held as two code points is joined, so parsing gives the same text back
    pair = "\ud83d\ude00"
    assert strict_loads(model.dumps(pair)) == model.to_json_data(pair) == "\U0001f600"
    with pytest.raises(ValueError):  # two different keys that become equal
        model.dumps({chr(0xD800): 1, chr(0xDBFF): 2})


class _Colour(enum.IntEnum):
    RED = 1


@pytest.mark.parametrize(
    "value",
    [
        b"bytes",
        bytearray(b"x"),
        object(),
        decimal.Decimal("1.5"),
        datetime.date(2026, 1, 1),
        1j,
        _Colour.RED,  # an int subclass: exact types only
        ReaderWarning("xml_parse_error", "boom"),  # a str subclass: the builder converts it
    ],
)
def test_unknown_types_raise_type_error(value):
    with pytest.raises(TypeError):
        model.dumps({"x": value})


def test_object_keys_must_be_strings():
    with pytest.raises(TypeError):
        model.dumps({1: "x"})


def test_tuples_and_sets_become_lists():
    assert (
        model.dumps({"t": (1, 2), "s": {"b", "a"}, "f": frozenset({3})})
        == '{"t":[1,2],"s":["a","b"],"f":[3]}'
    )


def test_datetimes_are_iso_8601():
    utc = datetime.UTC
    plus2 = datetime.timezone(datetime.timedelta(hours=2))
    cases = {
        datetime.datetime(2026, 9, 30, 14, 2, 11, tzinfo=utc): "2026-09-30T14:02:11Z",
        datetime.datetime(2026, 9, 30, 14, 2, 11, 123000, tzinfo=utc): "2026-09-30T14:02:11.123Z",
        datetime.datetime(2026, 9, 30, 14, 2, 11, 123456, tzinfo=utc): "2026-09-30T14:02:11.123456Z",
        datetime.datetime(2026, 9, 30, 16, 2, 11, tzinfo=plus2): "2026-09-30T14:02:11Z",
        datetime.datetime(2026, 9, 30, 14, 2, 11): "2026-09-30T14:02:11",  # zone unknown: no suffix
    }
    for dt, text in cases.items():
        assert model.dumps(dt) == f'"{text}"'
    edge = datetime.datetime(1, 1, 1, tzinfo=plus2)  # converting to UTC would leave the calendar
    assert model.iso8601(edge) == "0001-01-01T00:00:00+02:00"


def test_output_is_ascii_compact_or_indented_and_keeps_builder_order():
    data = {"b": 1, "a": "\u00e9"}
    assert model.dumps(data) == '{"b":1,"a":"\\u00e9"}'
    assert model.dumps(data, pretty=True) == '{\n  "b": 1,\n  "a": "\\u00e9"\n}'


def test_runaway_nesting_is_refused():
    deep: list = []
    for _ in range(300):
        deep = [deep]
    with pytest.raises(ValueError):
        model.dumps(deep)


# --------------------------------------------------------------------------- registry and schemas
EXPECTED_KINDS = {
    "document_summary",
    "properties",
    "configurations",
    "listing",
    "streams",
    "file_written",
    "parasolid_result",
    "batch_summary",
    "version",
    "error",
    "components",
    "references",
    "path_report",
    "health",
    "identity",
    "roots",
    "serve_started",
}


def _refs(schema) -> list[str]:
    out = []
    if isinstance(schema, dict):
        if "$ref" in schema:
            out.append(schema["$ref"])
        for v in schema.values():
            out.extend(_refs(v))
    elif isinstance(schema, list):
        for v in schema:
            out.extend(_refs(v))
    return out


def test_registry_size_and_entries():
    assert len(model.KINDS) >= len(EXPECTED_KINDS) == 17
    assert set(model.KINDS) >= EXPECTED_KINDS
    for name, spec in model.KINDS.items():
        assert spec.name == name and spec.schema_version >= 1 and callable(spec.build)
        assert spec.schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert spec.schema["$id"] == f"urn:solidseas:schema:{name}:v{spec.schema_version}"
        for ref in _refs(spec.schema):  # every reference resolves inside the kind's own schema
            assert ref.removeprefix("#/$defs/") in spec.schema.get("$defs", {}), (name, ref)
        # every kind but the error object is printed by a command or served by a route
        assert bool(spec.cli_commands or spec.rest_route) == (name != "error"), name
    # A kind that stands in for another on the same command and route (model_summary for
    # document_summary, when the file is not a SOLIDWORKS document) shares them.
    primary = {n: s for n, s in model.KINDS.items() if s.alternate_of is None}
    for name, spec in model.KINDS.items():
        if spec.alternate_of is not None:
            other = primary[spec.alternate_of]
            assert set(spec.cli_commands) <= set(other.cli_commands), name
            assert spec.rest_route in (None, other.rest_route), name
    commands = [c for s in primary.values() for c in s.cli_commands]
    routes = [s.rest_route for s in primary.values() if s.rest_route]
    assert len(commands) == len(set(commands)) >= 10  # one kind per command
    assert len(routes) == len(set(routes)) >= 10  # every route but the preview image answers with a kind
    assert all(r.startswith("/v1/") for r in routes)
    assert len(_refs(model.KINDS["document_summary"].schema)) >= 10
    assert len(_refs(model.KINDS["listing"].schema)) >= 10


def test_version_kind_lists_every_schema():
    data = model.build_version()
    assert data["api"] == model.API_VERSION == 1
    assert data["schemas"] == {name: spec.schema_version for name, spec in model.KINDS.items()}
    assert not validate(data, model.KINDS["version"].schema, strict=True)


def test_the_validator_fails_on_wrong_documents():
    schema = model.KINDS["properties"].schema
    good = {"view": "file", "configuration": None, "properties": [], "warnings": []}
    assert validate(good, schema, strict=True) == []
    prop = {
        "name": "Qty",
        "scope": "file",
        "configuration": None,
        "type": "number",
        "value": 42,
        "date": None,
        "text": "42",
        "expression": "42",
        "linked": False,
    }
    wrong = [
        ({**good, "view": "everything"}, "is not one of"),
        ({k: v for k, v in good.items() if k != "warnings"}, "missing required 'warnings'"),
        ({**good, "configuration": 3}, "is not string/null"),
        ({**good, "extra": 1}, "undeclared property 'extra'"),
        ({**good, "properties": [{**prop, "linked": 1}]}, "properties[0].linked"),  # 1 is not a boolean
        ({**good, "properties": [{**prop, "scope": "everywhere"}]}, "is not one of"),
        ({**good, "properties": [{**prop, "value": [1]}]}, "properties[0].value"),
        ({**good, "properties": [{k: v for k, v in prop.items() if k != "text"}]}, "missing required 'text'"),
    ]
    for doc, message in wrong:
        errors = validate(doc, schema, strict=True)
        assert errors and any(message in e for e in errors), (doc, errors)
    assert validate({**good, "extra": 1}, schema) == []  # published schemas leave objects open
    with pytest.raises(ValueError):  # a keyword it does not implement is never silently ignored
        validate(1, {"type": "integer", "multipleOf": 2})
    sha = model.KINDS["document_summary"].schema["$defs"]["preview"]["properties"]["sha256"]
    assert validate("ABC", sha) and not validate("a" * 64, sha)


def _legacy_bytes() -> bytes:
    streams = fixture_streams(O06)
    keep = ("Contents/Definition", "Header2", "_MO_VERSION_17000/History", "PreviewPNG")
    plain = {n: streams[n] for n in keep}
    plain["\x05DocumentSummaryInformation"] = build_propset(
        [
            (
                FMTID_USERDEFINED,
                [(2, 0x1E, "ORACLE-PN-123"), (3, 3, 42), (4, 0x40, 0)],
                {2: "PartNo", 3: "Qty", 4: "When"},
            )
        ]
    )
    return build_cfb(plain)


def _documents():
    for name in NATIVE:
        yield name, fixture_path(name)
    yield "legacy", _legacy_bytes()


@pytest.mark.parametrize(("label", "src"), list(_documents()), ids=lambda v: v if isinstance(v, str) else "")
def test_every_builder_matches_its_schema(label, src):
    with open_document(src) as doc:
        outputs = [
            ("document_summary", doc.summary()),
            ("document_summary", model.build_document_summary(doc, include=())),
            ("configurations", model.build_configurations(doc)),
            ("properties", model.build_properties(doc, view="file")),
            ("properties", model.build_properties(doc, view="configuration")),
            ("properties", model.build_properties(doc)),
            ("components", model.build_components(doc)),
            ("components", model.build_components(doc, flat=True)),
            ("references", model.build_references(doc)),
            ("path_report", model.build_path_report(doc)),
        ]
    for kind, data in outputs:
        assert validate(data, model.KINDS[kind].schema, strict=True) == [], (label, kind)
        env = strict_loads(model.dumps(model.envelope(kind, data, source={"file": "x"}), pretty=True))
        assert env["data"] == data  # the builder already returns exactly what a client parses
        assert validate(env, model.envelope_schema(kind), strict=True) == [], (label, kind)


# --------------------------------------------------------------------------- error codes and the error object
def test_error_codes_table_is_consistent():
    assert len(model.ERROR_CODES) >= 30
    for code, spec in model.ERROR_CODES.items():
        assert spec.code == code and re.fullmatch(r"[a-z_]+", code)
        assert spec.http_status is not None or spec.cli_exit is not None, code
        assert spec.message.endswith(".") and len(spec.message) <= 100
        if spec.http_status == 503:
            assert spec.retryable, code
    assert model.ERROR_CODES["locked"].retryable


def _api_md() -> str:
    return API_MD.read_text(encoding="utf-8")


def test_api_md_error_table_is_derived_from_error_codes():
    text = _api_md()
    section = text[text.index("### 5.6 `error` (v1)") : text.index("### 5.7")]
    rows = [line for line in section.splitlines() if line.startswith("| `")]
    seen: dict[str, tuple] = {}
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        http = re.match(r"\d+", cells[1])
        exit_code = re.match(r"\d+", cells[2])
        for code in re.findall(r"`([a-z_]+)`", cells[0]):
            assert code not in seen, f"{code} appears twice"
            seen[code] = (
                int(http.group()) if http else None,
                int(exit_code.group()) if exit_code else None,
                cells[3] == "yes",
            )
    assert len(seen) == len(model.ERROR_CODES) >= 30
    for code, spec in model.ERROR_CODES.items():
        assert seen[code] == (spec.http_status, spec.cli_exit, spec.retryable), code


def test_api_md_names_every_warning_code_and_kind():
    text = _api_md()
    for code in WARNING_CODES:
        assert f"`{code}`" in text, code
    for kind in model.KINDS:
        assert f"`{kind}`" in text, kind
    assert text.lstrip().startswith("# SolidSeas integration API")
    assert "## Status" in text.split("## 1.")[0]
    for c in range(1, 11):  # the review decisions are written down as rules
        assert f"### C{c}." in text


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (UnknownFormatError("not CAD"), "unknown_format"),
        (SldFormatError("bad"), "damaged_file"),
        (LockedFileError(32, "locked", "x.SLDPRT"), "locked"),
        (FileTooLargeError("big", detail={"limit": 10, "value": 11}), "file_too_large"),
        (StreamNotFoundError("no stream"), "stream_not_found"),
        (ConfigurationNotFoundError("no configuration"), "configuration_not_found"),
        (InvalidArgumentError("bad view", detail={"parameter": "view"}), "invalid_argument"),
        (FileNotFoundError(2, "missing", "x.SLDPRT"), "not_found"),
        (NotADirectoryError(), "not_found"),
        (PermissionError(13, "denied"), "permission_denied"),
        (TimeoutError(), "timeout"),
        (NotImplementedError(), "not_implemented"),
        (ValueError("anything else"), "internal"),
        (RuntimeError(), "internal"),
    ],
)
def test_error_info_maps_every_exception(exc, code):
    info = model.error_info(exc)
    spec = model.ERROR_CODES[code]
    assert info == {
        "code": code,
        "message": spec.message,
        "exception": type(exc).__name__,
        "retryable": spec.retryable,
        "detail": info["detail"],
        "reader_message": str(exc),
    }
    assert validate(info, model.KINDS["error"].schema, strict=True) == []
    assert model.error_info(exc, reader_message=False)["reader_message"] is None


def test_error_detail_keeps_only_safe_keys():
    exc = PathRefusedError(
        "refused",
        detail={"rule": "dot_component", "component_index": 2, "path": "/srv/jobs/x.SLDPRT", "limit": 2**60},
    )
    assert model.error_info(exc)["detail"] == {
        "rule": "dot_component",
        "component_index": 2,
        "limit": str(2**60),
    }


def test_error_envelope():
    env = model.error_envelope(
        LockedFileError(32, "locked", "x.SLDPRT"), source={"file": "x.SLDPRT"}, reader_message=False
    )
    assert (env["ok"], env["kind"], env["error"]["code"], env["error"]["retryable"]) == (
        False,
        "error",
        "locked",
        True,
    )
    assert validate(strict_loads(model.dumps(env)), model.envelope_schema("error"), strict=True) == []


# --------------------------------------------------------------------------- exact values: o04 and o06
def _stat_file(path: Path) -> dict:
    st = os.stat(path)
    modified = datetime.datetime(1970, 1, 1, tzinfo=datetime.UTC) + datetime.timedelta(
        microseconds=st.st_mtime_ns // 1000
    )
    return {
        "name": path.name,
        "size": st.st_size,
        "modified_utc": model.iso8601(modified),
        "mtime_ns": str(st.st_mtime_ns),
    }


SAVED_2024 = {
    "format_version": 17000,
    "release": "SOLIDWORKS 2024",
    "release_verified": True,
    "last_build": 2024016,
    "last_build_date": "2024-01-16",
    "save_as_previous": False,
}
MMGS = {"system": "MMGS", "length": "mm", "mass": "g", "angle": "deg", "length_decimal_places": 2}
ALLOY = {"name": "1060 Alloy", "database": "SOLIDWORKS Materials"}


def _prop(name, ptype, value, text, scope="file", configuration=None, date=None):
    return {
        "name": name,
        "scope": scope,
        "configuration": configuration,
        "type": ptype,
        "value": value,
        "date": date,
        "text": text,
        "expression": text,
        "linked": False,
    }


ORACLE = [
    _prop("PartNo", "text", "ORACLE-PN-123", "ORACLE-PN-123"),
    _prop("Description", "text", "Oracle test box", "Oracle test box"),
    _prop("Qty", "number", 42, "42"),
]
CFG_ONLY = _prop("CfgOnly", "text", "ALT-VALUE", "ALT-VALUE", "configuration", "OracleAlt")


def _png(nbytes: int, sha256: str) -> dict:
    return {
        "available": True,
        "reason": None,
        "mime": "image/png",
        "width": 640,
        "height": 480,
        "bytes": nbytes,
        "stream": "PreviewPNG",
        "sha256": sha256,
    }


def _expected_summary(path: Path, *, created, saved, configurations, material, preview, streams) -> dict:
    return {
        "file": _stat_file(path),
        "format": "modern",
        "doc_type": "part",
        "doc_type_source": "definition",
        "saved_version": SAVED_2024,
        "active_configuration": "Default",
        "configurations": configurations,
        "properties": ORACLE,
        "material": material,
        "units": MMGS,
        "fields": {
            "title": None,
            "subject": None,
            "author": None,
            "keywords": None,
            "comments": None,
            "last_saved_by": "<checked separately>",
            "created_utc": created,
            "last_saved_utc": saved,
        },
        "preview": preview,
        "counts": {
            "streams": streams,
            "configurations": len(configurations),
            "custom_properties": 3,
            "references": None,
            "nested_documents": 0,
            "parasolid_partitions": 1,
        },
        "warnings": [],
    }


def _check_saver(summary: dict, doc) -> None:
    # The fixtures carry the generating account's name; it is compared, never written down.
    saver = summary["fields"]["last_saved_by"]
    assert isinstance(saver, str) and saver and saver == doc.metadata.summary["last_saved_by"]
    summary["fields"]["last_saved_by"] = "<checked separately>"


def test_o04_summary_exact():
    default = {
        "name": "Default",
        "id": 0,
        "active": True,
        "most_recent": True,
        "comment": None,
        "material": None,
        "material_assigned": False,
        "properties": [],
    }
    expected = _expected_summary(
        O04,
        created="2026-10-02T00:26:04Z",
        saved="2026-10-02T00:26:05Z",
        configurations=[default],
        material=None,
        preview=_png(7351, "3d5198792d338e722897add7e85a060f003f46ecac90cb371e3494d5b27dcbbe"),
        streams=41,
    )
    with open_document(O04) as doc:
        summary = doc.summary()
        _check_saver(summary, doc)
    assert expected["file"]["size"] == 46265
    assert summary == expected


def test_o06_summary_exact():
    configurations = [
        {
            "name": "Default",
            "id": 0,
            "active": True,
            "most_recent": True,
            "comment": None,
            "material": ALLOY,
            "material_assigned": True,
            "properties": [],
        },
        {
            "name": "OracleAlt",
            "id": 1,
            "active": False,
            "most_recent": False,
            "comment": "oracle alt config",
            "material": ALLOY,
            "material_assigned": True,
            "properties": [CFG_ONLY],
        },
    ]
    expected = _expected_summary(
        O06,
        created="2026-10-02T00:26:04Z",
        saved="2026-10-02T00:26:07Z",
        configurations=configurations,
        material=ALLOY,
        preview=_png(7395, "0dc9ee4359ccbc6f527f4e4742fcd013ff724fd9a5451e4925bb5d0c7c9534ae"),
        streams=43,
    )
    with open_document(O06) as doc:
        summary = doc.summary()
        _check_saver(summary, doc)
        assert model.build_configurations(doc) == {
            "active_configuration": "Default",
            "configurations": configurations,
            "warnings": [],
        }
    assert expected["file"]["size"] == 49134
    assert summary == expected


def test_o06_property_views_exact():
    with open_document(O06) as doc:
        assert model.build_properties(doc, view="file") == {
            "view": "file",
            "configuration": None,
            "properties": ORACLE,
            "warnings": [],
        }
        assert model.build_properties(doc) == {
            "view": "effective",
            "configuration": "Default",
            "properties": ORACLE,
            "warnings": [],
        }
        assert model.build_properties(doc, configuration="OracleAlt") == {
            "view": "effective",
            "configuration": "OracleAlt",
            "properties": [*ORACLE, CFG_ONLY],
            "warnings": [],
        }
        assert model.build_properties(doc, view="configuration", configuration="oraclealt") == {
            "view": "configuration",
            "configuration": "OracleAlt",
            "properties": [CFG_ONLY],
            "warnings": [],
        }
        assert model.build_properties(doc, view="configuration") == {
            "view": "configuration",
            "configuration": "Default",
            "properties": [],
            "warnings": [],
        }
        with pytest.raises(ConfigurationNotFoundError):
            model.build_properties(doc, configuration="Nope")
        with pytest.raises(InvalidArgumentError) as info:
            model.build_properties(doc, view="everything")
        assert info.value.detail == {"parameter": "view"}
        with pytest.raises(InvalidArgumentError):
            model.build_properties(doc, view="file", configuration="Default")


def test_info_is_deprecated_and_still_answers_in_its_0_1_shape():
    with open_document(fixture_path("o04_boxA_props.SLDPRT")) as doc:
        with pytest.warns(SolidSeasDeprecationWarning, match="summary") as caught:
            info = doc.info()
        summary = doc.summary()
    assert issubclass(SolidSeasDeprecationWarning, DeprecationWarning)
    assert len(caught) == 1 and caught[0].filename == __file__  # it points at the caller
    assert info["file"] == "o04_boxA_props.SLDPRT" and info["doc_type"] == summary["doc_type"] == "part"
    assert info["saved_version"] == summary["saved_version"]
    assert info["custom_property_count"] == len(summary["properties"]) == 3


def test_summary_include_and_python_identity():
    with open_document(O06) as doc:
        assert doc.summary() == model.build_document_summary(doc)
        bare = doc.summary(include=())
        assert bare["properties"] is None and bare["configurations"] is None
        assert doc.summary(include="properties")["configurations"] is None
        with pytest.raises(InvalidArgumentError):
            doc.summary(include=("thumbnail",))


def test_summary_properties_stay_file_level_when_the_active_configuration_has_its_own():
    """API 5.1: the summary's properties are the file-level ones. Of the fixtures, only
    o14's active configuration has a property of its own; a crafted o06 with OracleAlt
    active adds a second case."""
    with open_document(fixture_path("o14_property_types.SLDPRT")) as doc:
        summary = doc.summary()
        effective = [p.name for p in doc.effective_properties()]
    assert effective == [p["name"] for p in summary["properties"]] + ["CfgProp"]
    with open_document(o06_with_active_alt()) as doc:
        summary = doc.summary()
        effective = [p.name for p in doc.effective_properties()]
    assert effective == ["PartNo", "Description", "Qty", "CfgOnly"]  # control: the views differ here
    assert summary["active_configuration"] == "OracleAlt"
    assert summary["properties"] == ORACLE
    alt = next(c for c in summary["configurations"] if c["name"] == "OracleAlt")
    assert alt["active"] and alt["properties"] == [CFG_ONLY]


@pytest.mark.parametrize(
    ("name", "shown"),
    [("o18_drw_boxA.SLDDRW", "o02_boxA.SLDPRT"), ("o19_drw_asm.SLDDRW", "o16_asm_features.SLDASM")],
)
def test_the_drawing_fixtures_count_their_models_as_references(name, shown):
    """o18 and o19 each have one view; the model it shows is their one reference."""
    with open_document(fixture_path(name)) as doc:
        refs = doc.references()
        counts = doc.summary()["counts"]
        assert (doc.doc_type, doc.doc_type_source) == ("drawing", "definition")
    assert [(r.file_name, r.sources, r.direct) for r in refs] == [(shown, ["Header2"], None)]
    assert counts["references"] == len(refs) == 1


def test_a_drawing_counts_its_models_as_references():
    # o08 without its type GUID and component tree, named as a drawing, keeps only the Header2
    # list of referenced models, as a drawing does, and takes its type from the extension.
    data = rebuild(fixture_path(ASSEMBLY), drop=("Contents/Definition", "swXmlContents/COMPINSTANCETREE"))
    with open_document(data, name="sheet.SLDDRW") as doc:
        refs = doc.references()
        counts = doc.summary()["counts"]
        assert (doc.doc_type, doc.doc_type_source) == ("drawing", "extension")
        assert doc.active_configuration is None  # a drawing has no configurations
    assert [(r.file_name, r.sources, r.direct) for r in refs] == [("o02_boxA.SLDPRT", ["Header2"], None)]
    assert counts["references"] == len(refs) == 1
    with open_document(data, name="sheet.SLDPRT") as doc:  # control: a part has no reference count
        assert doc.summary()["counts"]["references"] is None


def test_a_name_matching_two_configurations_case_insensitively_is_not_found():
    streams = fixture_streams(O06)
    xml = ("swXmlContents/Features", "swXmlContents/KeyWords")
    changes = {n: streams[n].replace(b"OracleAlt", b"DEFAULT") for n in xml}
    mt = streams["swXmlContents/MATERIALTREE"].decode("utf-16").replace("OracleAlt", "DEFAULT")
    changes["swXmlContents/MATERIALTREE"] = mt.encode("utf-16")
    with open_document(rebuild(O06, changes)) as doc:
        assert [c.name for c in doc.configurations] == ["Default", "DEFAULT"]
        assert (doc.configuration("Default").id, doc.configuration("DEFAULT").id) == (0, 1)  # exact names
        with pytest.raises(ConfigurationNotFoundError):
            doc.configuration("default")  # matches both when case is ignored: not a unique match
        with pytest.raises(ConfigurationNotFoundError):
            model.build_properties(doc, configuration="default")


def test_material_assigned_is_null_when_no_carrier_says():
    # KeyWords names the material; MATERIALTREE, which says it is assigned, is missing.
    with open_document(rebuild(O06, drop=("swXmlContents/MATERIALTREE",))) as doc:
        configurations = doc.summary()["configurations"]
    assert [(c["name"], c["material"]["name"], c["material_assigned"]) for c in configurations] == [
        ("Default", "1060 Alloy", None),
        ("OracleAlt", "1060 Alloy", None),
    ]


# --------------------------------------------------------------------------- Document options
def test_file_info_from_the_open_handle(tmp_path):
    with open_document(O06) as doc:
        st = os.stat(O06)
        fi = doc.file_info
        assert (fi.size, fi.mtime_ns) == (st.st_size, st.st_mtime_ns)
        assert fi.modified_utc.tzinfo is not None and fi.modified_utc.utcoffset() == datetime.timedelta(0)
        assert doc.name == O06.name
    with open_document(O06.read_bytes()) as doc:
        assert doc.file_info is None and doc.name is None
        assert doc.summary()["file"] == {"name": None, "size": None, "modified_utc": None, "mtime_ns": None}
    with open_document(O06.read_bytes(), name="renamed.SLDPRT") as doc:
        assert doc.summary()["file"]["name"] == "renamed.SLDPRT"


def test_name_is_the_extension_hint_for_bytes():
    data = rebuild(fixture_path(ASSEMBLY), drop=("Contents/Definition",))
    with open_document(data) as doc:
        assert (doc.doc_type, doc.doc_type_source) == (None, "none")
    with open_document(data, name="frame.SLDASM") as doc:
        assert (doc.doc_type, doc.doc_type_source, doc.name) == ("assembly", "extension", "frame.SLDASM")
        assert doc.summary()["counts"]["references"] == 1


def test_max_file_bytes_refuses_before_any_read(monkeypatch):
    size = O06.stat().st_size

    def no_read(*args, **kwargs):
        raise AssertionError("the file was read")

    monkeypatch.setattr(container_mod, "pread", no_read)
    with pytest.raises(FileTooLargeError) as info:
        open_document(O06, max_file_bytes=size - 1)
    assert info.value.detail == {"limit": size - 1, "value": size}
    assert model.error_info(info.value)["code"] == "file_too_large"
    with pytest.raises(FileTooLargeError):
        open_document(O06.read_bytes(), max_file_bytes=size - 1)
    monkeypatch.undo()
    with open_document(O06, max_file_bytes=size) as doc:
        assert doc.file_info.size == size


@pytest.mark.parametrize("bad", [-1, True, "10", 1.5])
def test_max_file_bytes_must_be_a_count(bad):
    with pytest.raises(InvalidArgumentError):
        open_document(O06, max_file_bytes=bad)


def test_name_must_be_text():
    with pytest.raises(InvalidArgumentError):
        open_document(O06, name=b"x.SLDPRT")


def test_none_means_the_active_configuration_everywhere():
    with open_document(O06) as doc:
        assert doc.configuration().name == "Default"
        assert [p.name for p in doc.effective_properties()] == ["PartNo", "Description", "Qty"]
        assert (
            doc.property_values()
            == doc.property_values("Default")
            == {"PartNo": "ORACLE-PN-123", "Description": "Oracle test box", "Qty": 42}
        )
        assert doc.property_values("OracleAlt")["CfgOnly"] == "ALT-VALUE"
        with pytest.raises(KeyError):  # ConfigurationNotFoundError is a KeyError
            doc.property_values("Nope")


def test_none_follows_the_active_configuration_when_it_has_properties():
    # 0.1's property_values(None) meant "file-level only"; it now means the active configuration.
    with open_document(o06_with_active_alt()) as doc:
        assert doc.active_configuration == "OracleAlt"
        assert doc.property_values()["CfgOnly"] == "ALT-VALUE"
        assert [p.scope for p in doc.effective_properties()] == ["file", "file", "file", "configuration"]
        data = model.build_properties(doc)
        assert (data["configuration"], len(data["properties"])) == ("OracleAlt", 4)
        assert model.build_properties(doc, view="file")["properties"] == ORACLE


def test_configuration_property_replaces_a_file_property_in_place():
    streams = fixture_streams(O06)
    cfg = streams["docProps/Config-1-Properties.xml"].replace(b'"CfgOnly"', b'"qty"')
    with open_document(rebuild(O06, {"docProps/Config-1-Properties.xml": cfg})) as doc:
        props = doc.effective_properties("OracleAlt")
        names = [(p.name, p.scope) for p in props]
        assert names == [("PartNo", "file"), ("Description", "file"), ("qty", "configuration")]
        assert doc.property_values("OracleAlt") == {
            "PartNo": "ORACLE-PN-123",
            "Description": "Oracle test box",
            "qty": "ALT-VALUE",
        }


def test_no_active_configuration_gives_the_file_properties():
    streams = fixture_streams(O04)
    isw = streams["docProps/ISolidWorksInformation.xml"].replace(
        b"<vt:lpstr>Default</vt:lpstr>", b"<vt:lpstr></vt:lpstr>"
    )
    tree = streams["swXmlContents/Features"].replace(
        b'swMostRecentConfiguration="YES"', b'swMostRecentConfiguration="NO"'
    )
    changes = {"docProps/ISolidWorksInformation.xml": isw, "swXmlContents/Features": tree}
    with open_document(rebuild(O04, changes)) as doc:
        assert doc.active_configuration is None and doc.configuration() is None
        assert [p.name for p in doc.effective_properties()] == ["PartNo", "Description", "Qty"]
        data = model.build_properties(doc)
    assert data["configuration"] is None and len(data["properties"]) == 3


# --------------------------------------------------------------------------- typed property values
def _custom_xml(*props: tuple[str, str, str]) -> bytes:
    body = "".join(
        f'<property name="{name}" pid="{pid}"><vt:{vt}>{text}</vt:{vt}></property>'
        for pid, (name, vt, text) in enumerate(props, start=2)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><Properties '
        'xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        f'<propertySection name="UserDefinedProperties">{body}</propertySection></Properties>'
    ).encode()


def test_property_values_are_typed_and_json_safe():
    custom = _custom_xml(
        ("Big", "i8", str(2**60)),
        ("NotANumber", "r8", "NaN"),
        ("Huge", "r8", "1e999"),
        ("Bad", "i4", "abc"),
        ("When", "filetime", "2026-09-30T12:00:00Z"),
        ("Local", "date", "2026-09-30T12:00:00"),
        ("Unset", "filetime", "1601-01-01T00:00:00Z"),
        ("Flag", "bool", "true"),
        ("Odd", "bool", "maybe"),
        ("Blob", "blob", "AAEC"),
        ("Half", "r4", "0.5"),
    )
    with open_document(rebuild(O04, {"docProps/custom.xml": custom})) as doc:
        props = {p.name: p for p in doc.properties}
        data = model.build_properties(doc, view="file")
    assert props["Big"].value == 2**60 and props["Big"].type == "number"
    assert math.isnan(props["NotANumber"].value) and props["Huge"].value == math.inf
    assert props["Bad"].value is None and props["Bad"].text == "abc"
    assert props["When"].value == datetime.datetime(2026, 9, 30, 12, tzinfo=datetime.UTC)
    assert props["Local"].value == datetime.datetime(2026, 9, 30, 12) and props["Local"].value.tzinfo is None
    assert props["Unset"].value is None
    assert props["Flag"].value is True and props["Odd"].value is None
    assert (props["Blob"].type, props["Blob"].value, props["Blob"].text) == ("other", None, "AAEC")
    values = {p["name"]: (p["type"], p["value"]) for p in data["properties"]}
    assert values == {
        "Big": ("number", None),
        "NotANumber": ("number", None),
        "Huge": ("number", None),
        "Bad": ("number", None),
        "When": ("date", "2026-09-30T12:00:00Z"),
        "Local": ("date", "2026-09-30T12:00:00"),
        "Unset": ("date", None),
        "Flag": ("boolean", True),
        "Odd": ("boolean", None),
        "Blob": ("other", None),
        "Half": ("number", 0.5),
    }
    big = next(p for p in data["properties"] if p["name"] == "Big")
    assert big["text"] == str(2**60)  # the digits survive in text
    assert [w["code"] for w in data["warnings"]] == [
        "value_not_representable",
        "non_finite_number",
        "non_finite_number",
    ]
    assert validate(data, model.KINDS["properties"].schema, strict=True) == []
    assert strict_loads(model.dumps(data)) == data
    with open_document(rebuild(O04, {"docProps/custom.xml": custom})) as doc:
        reader = [w.code for w in doc.warnings]
    assert reader == ["property_value_unreadable", "property_value_unreadable"]  # Bad and Odd


def test_legacy_property_types():
    with open_document(_legacy_bytes()) as doc:
        props = {p.name: (p.type, p.value) for p in doc.properties}
    assert props == {"PartNo": ("text", "ORACLE-PN-123"), "Qty": ("number", 42), "When": ("date", None)}


def test_a_date_property_carries_its_calendar_day():
    """SOLIDWORKS stores the day typed as noon, local time, in UTC: o14's 3/15/2024, saved
    at UTC-4, is 2024-03-15T16:00:00Z, and its day is 2024-03-15 whatever the reader's own
    zone, so a JavaScript client need not shift it (section 6 of docs/API.md)."""
    import datetime

    from solidseas.formats.solidworks.metadata import Property, calendar_day

    with open_document(fixture_path("o14_property_types.SLDPRT")) as doc:
        props = {p["name"]: p for p in model.build_properties(doc, view="file")["properties"]}
    assert (props["DateProp"]["value"], props["DateProp"]["date"]) == ("2024-03-15T16:00:00Z", "2024-03-15")
    assert all(p["date"] is None for p in props.values() if p["type"] != "date")
    utc = datetime.UTC

    def noon(hours: int) -> datetime.datetime:  # 3/15/2024 as saved at UTC+hours
        return datetime.datetime(2024, 3, 15, 12, tzinfo=datetime.timezone(datetime.timedelta(hours=hours)))

    assert calendar_day(noon(12)) == calendar_day(noon(-11)) == datetime.date(2024, 3, 15)
    assert calendar_day(noon(13)) == datetime.date(2024, 3, 14)  # past UTC+12: the limit 5.3 names
    late = datetime.datetime(2024, 3, 15, 23, 30)
    assert calendar_day(late) == datetime.date(2024, 3, 15)  # no zone: its own day
    assert calendar_day("2024-03-15") is None
    typed = datetime.datetime(2024, 3, 15, 16, tzinfo=utc)
    p = Property("D", typed, None, "date", "3/15/2024", False, None, 0, None)
    assert p.date == datetime.date(2024, 3, 15)
    assert Property("N", 3, "3", "number", "3", False, None, 0, None).date is None
