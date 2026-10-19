"""Python, the CLI and REST give identical JSON for every fixture document
(``docs/API.md`` section 1: one definition, three surfaces).

For each document in the fixtures folder (``tests/fixtures``, or
``SOLIDSEAS_FIXTURES_DIR``), and each per-document kind, the Python builder's data,
the CLI's ``--json`` data and the REST service's data are equal, and so are the
envelopes apart from ``source``, the one part that names where the document is on
each surface. A request that fails gives equal error objects apart from
``reader_message``, which the REST service never sends. The preview is the same
image, by SHA-256, on all three. With resolution, the REST answer equals Python's
on the same root with lookups outside it switched off, as the service runs it.

All three read the same copies, in one folder that is the service's root. The
number of comparisons is computed from the documents present and asserted.
"""

import hashlib
import json

import pytest

from serve_support import Running, copy_documents, fixture_documents
from solidseas import Root, Roots, cli, model, open_document
from solidseas.resolve import resolve_references

pytestmark = pytest.mark.usefixtures("outbound_guard")
DOCS = fixture_documents()
NEEDS_DOCS = pytest.mark.skipif(
    not DOCS, reason="no SOLIDWORKS documents in tests/fixtures or SOLIDSEAS_FIXTURES_DIR"
)
# kind, CLI command, REST route, Python builder
KINDS = [
    ("document_summary", "info", "document", model.build_document_summary),
    ("properties", "props", "properties", model.build_properties),
    ("configurations", "configurations", "configurations", model.build_configurations),
    ("components", "components", "components", model.build_components),
    ("references", "references", "references", model.build_references),
    ("path_report", "paths", "path-report", model.build_path_report),
]
MISSING_CONFIGURATION = "Zq7 no such configuration"


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    root = tmp_path_factory.mktemp("surfaces") / "fixtures"
    copies = copy_documents(root, DOCS)
    running = Running({"fx": root}, workers=2)
    yield running, copies, root
    running.close()


def _cli(capsys, *argv) -> tuple[int, dict]:
    code = cli.main([*argv, "--json"])
    out, err = capsys.readouterr()
    assert err == ""
    return code, json.loads(out)


def _without(env: dict, *keys: str) -> dict:
    return {k: v for k, v in env.items() if k not in keys}


def _error_without_message(env: dict) -> dict:
    return {**_without(env, "source"), "error": _without(env["error"], "reader_message")}


@NEEDS_DOCS
def test_every_kind_is_identical_on_every_surface(served, capsys):
    running, copies, _root = served
    comparisons = 0
    for path in copies:
        with open_document(path) as doc:
            python = {kind: build(doc) for kind, _cmd, _route, build in KINDS}
        for kind, command, route, _build in KINDS:
            code, cli_env = _cli(capsys, command, str(path))
            assert cli_env["ok"] and cli_env["kind"] == kind, (path.name, kind, cli_env.get("error"))
            r = running.get(route, root="fx", path=path.name)
            assert r.status == 200, (path.name, route, r.body[:300])
            rest_env = r.json()
            assert cli_env["data"] == python[kind], (path.name, kind)
            assert rest_env["data"] == python[kind], (path.name, kind)
            comparisons += 2
            assert (
                _without(cli_env, "source")
                == _without(rest_env, "source")
                == _without(model.envelope(kind, python[kind]), "source")
            )
            assert cli_env["source"] == {"file": str(path)}
            assert rest_env["source"] == {"root": "fx", "path": path.name}
    assert comparisons == 2 * len(KINDS) * len(DOCS) >= 2 * len(KINDS)


@NEEDS_DOCS
def test_errors_are_identical_apart_from_the_reader_message(served, capsys):
    running, copies, _root = served
    comparisons = 0
    for path in copies:
        with open_document(path) as doc:
            try:
                model.build_properties(doc, configuration=MISSING_CONFIGURATION)
            except Exception as exc:  # the same refusal on every surface
                python = model.error_envelope(exc)
        code, cli_env = _cli(capsys, "props", str(path), "--configuration", MISSING_CONFIGURATION)
        r = running.get("properties", root="fx", path=path.name, configuration=MISSING_CONFIGURATION)
        rest_env = r.json()
        assert code == 1 and r.status == 404 and python["error"]["code"] == "configuration_not_found"
        assert (
            _error_without_message(cli_env)
            == _error_without_message(rest_env)
            == _error_without_message(python)
        )
        assert cli_env["error"]["reader_message"] and rest_env["error"]["reader_message"] is None
        comparisons += 2
    assert comparisons == 2 * len(DOCS)


@NEEDS_DOCS
def test_previews_are_the_same_image_on_every_surface(served, capsys, tmp_path):
    running, copies, _root = served
    comparisons = 0
    stored = 0
    for path in copies:
        with open_document(path) as doc:
            pv = doc.preview()
        out = tmp_path / f"{path.stem}.png"
        code, cli_env = _cli(capsys, "preview", str(path), "-o", str(out))
        r = running.get("preview", root="fx", path=path.name)
        if pv is None:
            assert code == 1 and cli_env["error"]["code"] == "no_preview"
            assert r.status == 404 and r.json()["error"]["code"] == "no_preview"
        else:
            stored += 1
            want = hashlib.sha256(pv.data).hexdigest()
            assert hashlib.sha256(out.read_bytes()).hexdigest() == want
            assert r.status == 200 and hashlib.sha256(r.body).hexdigest() == want
            assert r.headers["content-type"] == pv.mime
        comparisons += 2
    assert comparisons == 2 * len(DOCS) and stored >= 1


@NEEDS_DOCS
def test_boms_are_identical_on_every_surface_on_the_same_root(served, capsys):
    """A BOM depends on every file under the roots: the REST answer and the CLI's (given
    the service's root and no lookups outside it) equal Python's on that root."""
    running, copies, root = served
    roots = Roots([Root("fx", str(root))])
    comparisons = 0
    for path in copies:
        for bom_type in ("top", "parts", "indented"):
            with open_document(path) as doc:
                python = model.build_bom(
                    doc,
                    bom_type=bom_type,
                    columns=["Description", "PartNo"],
                    roots=roots,
                    allow_outside_roots=False,
                )
            r = running.get("bom", root="fx", path=path.name, type=bom_type, columns="Description,PartNo")
            assert r.status == 200 and r.json()["data"] == python, (path.name, bom_type)
            code, cli_env = _cli(
                capsys,
                "bom",
                str(path),
                "--type",
                bom_type,
                "--column",
                "Description",
                "--column",
                "PartNo",
                "--root",
                f"fx={root}",
                "--no-outside-roots",
            )
            assert cli_env["data"] == python, (path.name, bom_type)
            assert code == (0 if python["complete"] else 4)
            comparisons += 2
    assert comparisons == 2 * 3 * len(DOCS)
    o16 = running.get("bom", root="fx", path="o16_asm_features.SLDASM", part_number_property="PartNo").json()
    assert [r["part_number"] for r in o16["data"]["rows"]][:2] == ["o02_boxA", "ORACLE-PN-123"]
    assert o16["data"]["rows"][0]["location"] == {"root": "fx", "path": "o02_boxA.SLDPRT"}
    bad = running.get("bom", root="fx", path="o16_asm_features.SLDASM", columns="A,a")
    assert bad.status == 400 and bad.json()["error"]["detail"] == {"parameter": "columns"}
    for value in (" ", "a\tb"):  # named as Python names it
        bad = running.get("bom", root="fx", path="o16_asm_features.SLDASM", part_number_property=value)
        assert bad.status == 400 and bad.json()["error"]["detail"] == {"parameter": "part_number_property"}


@NEEDS_DOCS
def test_resolution_over_rest_equals_python_on_the_same_root(served):
    running, copies, root = served
    referencing = []
    for path in copies:
        with open_document(path) as doc:
            if doc.doc_type in ("assembly", "drawing"):
                referencing.append(path)
    if not referencing:
        pytest.skip("no assembly or drawing among the fixtures")
    comparisons = 0
    for path in referencing:
        with open_document(path) as doc:
            res = resolve_references(doc, Roots([Root("fx", str(root))]), allow_outside_roots=False)
            python = model.build_references(doc, resolution=res)
        r = running.get("references", root="fx", path=path.name, resolve="1")
        assert r.status == 200 and r.json()["data"] == python, path.name
        assert python["resolution"]["outside_roots"] is False
        comparisons += 1
    assert comparisons == len(referencing)
