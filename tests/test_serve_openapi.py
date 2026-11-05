"""The service's OpenAPI description (``docs/API.md`` 8.19): a valid OpenAPI 3.0.3 document
that describes exactly the routes and query parameters the service enforces, the route that
serves it, the ``openapi`` command and the copy checked in as ``docs/openapi.json``."""

import json
import re
import shutil
from pathlib import Path

import pytest

from serve_support import Running, wait_for
from solidseas import __version__, cli, model
from solidseas.errors import InvalidArgumentError, PathRefusedError
from solidseas.serve import ROUTES
from solidseas.serve.openapi import OPENAPI_ROUTE, build_openapi, route_error_codes, route_kinds
from solidseas.serve.paths import check_path_text
from solidseas.serve.query import ServiceError, parse_query
from support import NATIVE, fixture_path

pytestmark = pytest.mark.usefixtures("outbound_guard")
REPO = Path(__file__).resolve().parents[1]
CHECKED_IN = REPO / "docs" / "openapi.json"
API_MD = REPO / "docs" / "API.md"
REGENERATE = "python -m solidseas openapi -o docs/openapi.json --force"


@pytest.fixture(scope="module")
def doc() -> dict:
    return build_openapi()


@pytest.fixture(scope="module")
def srv(tmp_path_factory):
    base = tmp_path_factory.mktemp("openapi") / "jobs"
    base.mkdir()
    for name in NATIVE:
        shutil.copy2(fixture_path(name), base / name)
    running = Running({"jobs": base}, workers=1, catalog=True)
    yield running
    running.close()


def _refs(node) -> list[str]:
    if isinstance(node, dict):
        return [v for k, v in node.items() if k == "$ref"] + [r for v in node.values() for r in _refs(v)]
    if isinstance(node, list):
        return [r for v in node for r in _refs(v)]
    return []


def _resolve(doc: dict, ref: str):
    assert ref.startswith("#/"), ref
    node = doc
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _query_params(doc: dict, path: str) -> dict[str, dict]:
    return {p["name"]: p for p in doc["paths"][path]["get"].get("parameters", []) if "in" in p}


# --------------------------------------------------------------------------- the document
def test_the_document_is_openapi_3_0_3_and_every_reference_resolves(doc):
    assert doc["openapi"] == "3.0.3"
    assert set(doc) <= {
        "openapi",
        "info",
        "externalDocs",
        "servers",
        "security",
        "tags",
        "paths",
        "components",
    }
    refs = _refs(doc)
    assert len(refs) > 100
    for ref in refs:
        assert _resolve(doc, ref) is not None, ref
    for name in doc["components"]["schemas"]:  # every component is used
        assert f"#/components/schemas/{name}" in refs or name.endswith("Envelope"), name
    # nothing a 3.0 reader does not know: no JSON Schema 2020-12 keywords
    text = json.dumps(doc)
    for keyword in ('"const"', '"$defs"', '"prefixItems"', '"type": ["'):
        assert keyword not in text, keyword
    assert text.isascii()


def test_every_route_is_described_once_with_a_unique_operation_id(doc):
    assert list(doc["paths"]) == list(ROUTES) and OPENAPI_ROUTE in ROUTES
    ids = [item["get"]["operationId"] for item in doc["paths"].values()]
    assert len(ids) == len(set(ids)) == len(ROUTES) >= 21
    assert {"getDocument", "listFolder", "getPreview", "getOpenApi"} <= set(ids)
    tags = {t["name"] for t in doc["tags"]}
    assert tags == {"service", "files", "catalog"}
    for path, item in doc["paths"].items():
        assert list(item) == ["get"], path
        op = item["get"]
        assert op["tags"][0] in tags and op["summary"] and "HEAD is answered too" in op["description"]
        assert re.fullmatch(r"[a-z][A-Za-z]+", op["operationId"])


def test_the_version_is_the_api_line_never_the_package_version(doc):
    assert doc["info"]["version"] == ".".join(__version__.split(".")[:2])
    assert __version__ not in model.dumps(doc)
    assert doc["servers"] == [
        {
            "url": "http://127.0.0.1:{port}",
            "description": doc["servers"][0]["description"],
            "variables": {
                "port": {
                    "default": "8765",
                    "description": doc["servers"][0]["variables"]["port"]["description"],
                }
            },
        }
    ]


def test_the_token_is_needed_but_by_health_and_identity(doc):
    assert doc["security"] == [{"bearerAuth": []}]
    assert doc["components"]["securitySchemes"]["bearerAuth"] == {
        "type": "http",
        "scheme": "bearer",
        "description": doc["components"]["securitySchemes"]["bearerAuth"]["description"],
    }
    open_routes = [p for p, item in doc["paths"].items() if item["get"].get("security") == []]
    assert open_routes == [p for p, r in ROUTES.items() if not r.auth] == ["/v1/health", "/v1/identity"]
    for path, item in doc["paths"].items():
        responses = item["get"]["responses"]
        assert ("401" in responses) == ROUTES[path].auth, path
        assert ("429" in responses) == ROUTES[path].auth, path


def test_every_query_parameter_is_described_as_the_server_enforces_it(doc):
    for path, route in ROUTES.items():
        described = _query_params(doc, path)
        assert list(described) == list(route.params), path  # none missing, none extra
        for name, spec in route.params.items():
            p = described[name]
            schema = p["schema"]
            assert p["in"] == "query" and p["required"] == spec.required, (path, name)
            if spec.kind == "enum":
                assert schema["enum"] == list(spec.choices) and schema["default"] == spec.default
            elif spec.kind == "include":
                assert schema["items"]["enum"] == list(spec.choices) and (p["style"], p["explode"]) == (
                    "form",
                    False,
                )
                assert schema["default"] == list(spec.default)
            elif spec.kind == "int":
                assert (schema["minimum"], schema["maximum"], schema["default"]) == (
                    spec.low,
                    spec.high,
                    spec.default,
                )
            elif spec.kind == "bool":
                assert schema == {"type": "boolean", "default": spec.default}
            else:
                assert schema["type"] == "string" and "default" not in schema, (path, name)


def _base_query(route) -> dict[str, str]:
    """Valid values for a route's required parameters."""
    values = {"root": "jobs", "path": "a.SLDPRT", "client": "tests", "nonce": "n" * 32, "q": "box"}
    return {n: values[n] for n, s in route.params.items() if s.required}


def _query(pairs: dict[str, str]) -> str:
    from urllib.parse import urlencode

    return urlencode(pairs)


def test_the_parser_accepts_every_described_value_and_refuses_beyond_the_bounds(doc):
    """What the description allows, the query parser takes, and one step past each bound it
    refuses: the description is the server's own allowlist, not a copy of it."""
    checked = 0
    for path, route in ROUTES.items():
        base = _base_query(route)
        for name, p in _query_params(doc, path).items():
            schema, spec = p["schema"], route.params[name]

            def accepts(value, name=name, base=base, route=route):
                return parse_query(_query({**base, name: value}), route.params)

            if "enum" in schema:
                for value in schema["enum"]:
                    assert accepts(value)[0][name] == value
                with pytest.raises(InvalidArgumentError):
                    accepts(schema["enum"][0].upper() + "x")
            elif schema["type"] == "array":
                assert accepts(",".join(schema["items"]["enum"]))[0][name] == tuple(schema["items"]["enum"])
                with pytest.raises(InvalidArgumentError):
                    accepts(",".join([schema["items"]["enum"][0]] * 2))
            elif schema["type"] == "integer":
                assert accepts(str(schema["minimum"]))[0][name] == schema["minimum"]
                assert accepts(str(schema["maximum"]))[0][name] == schema["maximum"]
                for beyond in (schema["minimum"] - 1, schema["maximum"] + 1):
                    with pytest.raises(InvalidArgumentError):
                        accepts(str(beyond))
            elif schema["type"] == "boolean":
                assert accepts("true")[0][name] is True and accepts("false")[0][name] is False
            elif "pattern" in schema and "maxLength" not in schema:  # root, client, nonce
                good = {"root": "jobs", "client": "tests", "nonce": "n" * 32}[name]
                assert re.search(schema["pattern"], good) and accepts(good)
                for bad in ("Jobs", "a b", "x" * 129):
                    assert not re.search(schema["pattern"], bad)
                    with pytest.raises(InvalidArgumentError):
                        accepts(bad)
            elif spec.kind == "path":
                most = schema["maxLength"]
                longest = ("d" * 200 + "/") * ((most - 7) // 201) + "a" * ((most - 7) % 201) + ".SLDPRT"
                assert len(longest) == most
                check_path_text(longest, want="file")
                with pytest.raises(PathRefusedError):
                    check_path_text("a" + longest, want="file")
            else:  # text, nested, cursor
                most = schema["maxLength"]
                assert accepts("a" * most)
                with pytest.raises(InvalidArgumentError):
                    accepts("a" * (most + 1))
                assert not re.search(schema["pattern"], "tab\there")
                with pytest.raises(InvalidArgumentError):
                    accepts("tab\there")
            checked += 1
        with pytest.raises(ServiceError) as refused:  # a name the description does not give
            parse_query(_query({**base, "token": "x"}), route.params)
        assert refused.value.code == "unknown_parameter"
    assert checked >= 50


def test_the_error_responses_are_the_codes_statuses(doc):
    error_codes = doc["components"]["schemas"]["Error"]["properties"]["code"]["x-extensible-enum"]
    assert set(error_codes) <= set(model.ERROR_CODES) and len(error_codes) >= 30
    assert "quarantined" not in error_codes  # a catalog state, never an answer
    for path, route in ROUTES.items():
        responses = doc["paths"][path]["get"]["responses"]
        codes = route_error_codes(route)
        statuses = {str(model.ERROR_CODES[c].http_status) for c in codes}
        assert {s for s in responses if s >= "400"} == statuses, path
        for code in codes:
            assert f"`{code}`" in responses[str(model.ERROR_CODES[code].http_status)]["description"]
        for status in ("503", "429"):
            if status in responses:
                assert "Retry-After" in responses[status]["headers"]
        assert {"400", "403", "500", "503"} <= set(responses), path
    assert "413" not in json.dumps([item["get"]["responses"] for item in doc["paths"].values()])


def test_each_kind_points_at_its_section_of_the_api_document(doc):
    text = API_MD.read_text(encoding="utf-8")
    kinds = sorted({k for r in ROUTES.values() for k in route_kinds(r)})
    assert "model_summary" in kinds and len(kinds) >= 19
    for kind in kinds:
        name = "".join(w.capitalize() for w in kind.split("_"))
        description = doc["components"]["schemas"][name]["description"]
        section = re.search(r"section (\d+\.\d+)", description).group(1)
        start = text.index(f"\n### {section} ")
        end = text.index("\n### ", start + 1)
        assert f"`{kind}`" in text[start:end], (kind, section)


def test_the_checked_in_copy_is_what_the_builder_makes_now(doc):
    on_disk = json.loads(CHECKED_IN.read_text(encoding="utf-8"))
    assert on_disk == doc, f"docs/openapi.json is out of date: regenerate it with `{REGENERATE}`"


# --------------------------------------------------------------------------- the route
def test_the_route_serves_the_document_bare_with_the_token(srv, doc):
    assert srv.request(OPENAPI_ROUTE, token=None).status == 401
    r = srv.request(OPENAPI_ROUTE)
    assert r.status == 200 and r.headers["content-type"] == "application/json; charset=utf-8"
    body = r.json()
    assert body == doc and "ok" not in body and "kind" not in body  # no envelope
    assert r.body.isascii() and r.headers["cache-control"] == "private, no-cache"
    again = srv.request(OPENAPI_ROUTE, headers={"If-None-Match": r.headers["etag"]})
    assert again.status == 304 and again.body == b""
    head = srv.request(OPENAPI_ROUTE, method="HEAD")
    assert head.status == 200 and head.body == b"" and head.headers["content-length"] == str(len(r.body))
    refused = srv.request(f"{OPENAPI_ROUTE}?pretty=1")
    assert refused.status == 400 and refused.json()["error"]["code"] == "unknown_parameter"
    origin = srv.request(OPENAPI_ROUTE, headers={"Origin": "https://elsewhere.example"})
    assert origin.status == 403 and origin.json()["error"]["code"] == "forbidden_origin"
    site = srv.request(OPENAPI_ROUTE, headers={"Sec-Fetch-Site": "cross-site"})
    assert site.status == 403 and site.json()["error"]["code"] == "forbidden_origin"
    host = srv.request(OPENAPI_ROUTE, headers={"Host": "rebound.example"})
    assert host.status == 403 and host.json()["error"]["code"] == "forbidden_host"


CALLS = {
    "/v1/health": {},
    "/v1/identity": {"client": "tests", "nonce": "n" * 43},
    "/v1/version": {},
    "/v1/roots": {},
    OPENAPI_ROUTE: {},
    "/v1/list": {"root": "jobs"},
    "/v1/document": {"root": "jobs", "path": "o02_boxA.SLDPRT"},
    "/v1/properties": {"root": "jobs", "path": "o04_boxA_props.SLDPRT"},
    "/v1/configurations": {"root": "jobs", "path": "o02_boxA.SLDPRT"},
    "/v1/components": {"root": "jobs", "path": "o08_asm_2x_boxA.SLDASM"},
    "/v1/references": {"root": "jobs", "path": "o08_asm_2x_boxA.SLDASM"},
    "/v1/bom": {"root": "jobs", "path": "o08_asm_2x_boxA.SLDASM"},
    "/v1/preview": {"root": "jobs", "path": "o02_boxA.SLDPRT"},
    "/v1/path-report": {"root": "jobs", "path": "o02_boxA.SLDPRT"},
    "/v1/mesh": {"root": "jobs", "path": "o08_asm_2x_boxA.SLDASM"},
    "/v1/catalog": {},
    "/v1/where-used": {"root": "jobs", "path": "o02_boxA.SLDPRT"},
    "/v1/search": {"q": "boxA"},
    "/v1/duplicates": {},
    "/v1/missing": {},
    "/v1/changes": {"since": "1d"},
}


def test_every_route_answers_as_described(srv, doc):
    """Each route's answer has the media type, the kind and the ETag (or none) its 200
    response describes."""
    assert set(CALLS) == set(ROUTES)
    assert wait_for(lambda: srv.server._catalog_path is not None, 120)
    for path, params in CALLS.items():
        r = srv.get(path.removeprefix("/v1/"), **params)
        ok = doc["paths"][path]["get"]["responses"]["200"]
        assert r.status == 200, (path, r.body[:300])
        media = r.headers["content-type"].split(";")[0]
        assert media in ok["content"], path
        assert ("ETag" in ok["headers"]) == ("etag" in r.headers), path
        assert ("304" in doc["paths"][path]["get"]["responses"]) == ("etag" in r.headers), path
        if media == "application/json" and path != OPENAPI_ROUTE:
            assert r.json()["kind"] in route_kinds(ROUTES[path]), path


# --------------------------------------------------------------------------- the command
def _cli(capsys, *argv) -> tuple[int, str]:
    code = cli.main(list(argv))
    return code, capsys.readouterr().out


def test_the_command_prints_and_writes_the_document(capsys, tmp_path, doc):
    for argv in (("openapi",), ("openapi", "--json"), ("--json", "openapi")):
        code, out = _cli(capsys, *argv)
        assert code == 0 and json.loads(out) == doc and out.startswith('{\n  "openapi": "3.0.3"')
    target = tmp_path / "openapi.json"
    code, out = _cli(capsys, "openapi", "-o", str(target))
    assert code == 0 and "wrote the OpenAPI description" in out
    assert json.loads(target.read_text(encoding="utf-8")) == doc
    written = target.read_bytes()
    assert written == (model.dumps(doc, pretty=True) + "\n").encode("ascii")
    code, out = _cli(capsys, "openapi", "-o", str(target), "--json")  # never over a file without --force
    env = json.loads(out)
    assert (
        code == 3 and env["error"]["code"] == "output_refused" and env["error"]["detail"]["rule"] == "exists"
    )
    target.write_text("{}", encoding="utf-8")
    code, out = _cli(capsys, "openapi", "-o", str(target), "--force", "--json")
    env = json.loads(out)
    assert code == 0 and env["kind"] == "file_written" and env["source"] is None
    assert env["data"]["bytes"] == len(written) and env["data"]["mime"] == "application/json"
    assert target.read_bytes() == written
    code, out = _cli(capsys, "openapi", "--force", "--json")
    assert code == 2 and json.loads(out)["error"]["detail"] == {"parameter": "force"}
