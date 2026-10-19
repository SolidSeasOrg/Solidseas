"""Phase 1's "done when" (``docs/ROADMAP.md``), as an integrating system would do it.

"An integrating system can, without SOLIDWORKS, list a folder's parts and
assemblies with thumbnails and properties, and get an assembly's component list."

The folder holds the fixture documents (``tests/fixtures``, or
``SOLIDSEAS_FIXTURES_DIR``), a part that stores no preview and a damaged file.
The same steps run through the REST service and the CLI, and the library gives
the same answers: every part and assembly is listed with its properties and its
preview, each preview the listing describes is the PNG the service serves, the
part with no stored preview says so, the damaged file is one error entry that
stops nothing, and the assembly's component list names its parts and where they
are. Nothing here starts SOLIDWORKS: a fresh interpreter runs the same steps and
then shows that neither it nor its worker process loaded SOLIDWORKS automation
(``solidseas.swapi``, ``win32com`` or any other COM package). The service in this
process reaches nothing but loopback (``netguard.no_outbound_connections``).
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from builders import rebuild
from serve_support import PNG, Running, copy_documents, fixture_documents
from solidseas import cli, model, open_document, scan

DOCS = fixture_documents()
NAMES = {p.name for p in DOCS}
ASSEMBLY = "o08_asm_2x_boxA.SLDASM"
PART = "o02_boxA.SLDPRT"
WITH_PROPERTIES = "o04_boxA_props.SLDPRT"
pytestmark = [
    pytest.mark.skipif(
        not {ASSEMBLY, PART, WITH_PROPERTIES} <= NAMES,
        reason=f"{ASSEMBLY}, {PART} and {WITH_PROPERTIES} are needed "
        "in tests/fixtures or SOLIDSEAS_FIXTURES_DIR",
    ),
    pytest.mark.usefixtures("outbound_guard"),
]
TESTS = Path(__file__).resolve().parent
SRC = TESTS.parent / "src"
# Packages that drive SOLIDWORKS: none may be loaded to do what Phase 1 promises.
AUTOMATION = ("solidseas.swapi", "win32com", "pythoncom", "pywintypes", "comtypes")


@pytest.fixture(scope="module")
def folder(tmp_path_factory):
    root = tmp_path_factory.mktemp("done") / "jobs"
    copy_documents(root, DOCS)
    by_name = {p.name: p for p in DOCS}
    (root / "bare.SLDPRT").write_bytes(rebuild(by_name[PART], drop=("PreviewPNG", "Preview")))
    (root / "damaged.SLDPRT").write_bytes(b"\x00\x00\x00\x00\x00\x00\x00\x04" + b"\x00" * 40)
    return root


@pytest.fixture(scope="module")
def service(folder):
    running = Running({"jobs": folder}, workers=2)
    yield running
    running.close()


def _cli(capsys, *argv) -> tuple[int, dict]:
    code = cli.main([*argv, "--json"])
    out, err = capsys.readouterr()
    assert err == ""
    return code, json.loads(out)


def _parts_and_assemblies(entries: list[dict]) -> dict[str, dict]:
    return {e["path"]: e for e in entries if e["doc_type"] in ("part", "assembly")}


def _check_listing(entries: list[dict]) -> dict[str, dict]:
    docs = _parts_and_assemblies(entries)
    expected = {p.name for p in DOCS if p.suffix.lower() in (".sldprt", ".sldasm")} | {"bare.SLDPRT"}
    assert set(docs) == expected
    for name, e in docs.items():
        assert e["status"] == "ok" and e["error"] is None, name
        assert isinstance(e["properties"], list), name
        if name == "bare.SLDPRT":
            assert e["preview"] == {**e["preview"], "available": False, "reason": "not_stored"}
        else:
            assert e["preview"]["available"] and e["preview"]["mime"] == "image/png", name
    with open_document(next(p for p in DOCS if p.name == WITH_PROPERTIES)) as doc:
        want = [p.name for p in doc.effective_properties()]
    assert want and [p["name"] for p in docs[WITH_PROPERTIES]["properties"]] == want
    damaged = next(e for e in entries if e["path"] == "damaged.SLDPRT")
    assert damaged["status"] == "error" and damaged["error"]["code"] in ("unknown_format", "damaged_file")
    return docs


def _check_components(data: dict) -> None:
    files = {f["key"]: f for f in data["files"]}
    instances = [n for n in data["children"] if files[n["file"]]["file_name"] == PART]
    assert len(instances) == 2 and all(n["doc_type"] == "part" for n in instances)
    (xa, ya, za), (xb, yb, zb) = (n["placement"]["translation_m"] for n in instances)
    assert abs(abs(xa - xb) - 0.05) < 1e-9 and ya == yb and za == zb


def test_through_rest(service):
    r = service.get("list", root="jobs", include="properties,preview")
    assert r.status == 200
    data = r.json()["data"]
    docs = _check_listing(data["entries"])
    assert data["counts"]["error"] == 1 and data["root"] == "jobs"
    served = 0
    for name, e in docs.items():
        if not e["preview"]["available"]:
            continue
        image = service.get("preview", root="jobs", path=name)
        assert image.status == 200 and image.body.startswith(PNG), name
        assert hashlib.sha256(image.body).hexdigest() == e["preview"]["sha256"], name
        served += 1
    assert served == len(docs) - 1
    r = service.get("components", root="jobs", path=ASSEMBLY)
    assert r.status == 200
    _check_components(r.json()["data"])


def test_through_the_cli_and_python(service, folder, capsys, tmp_path):
    code, env = _cli(capsys, "list", str(folder), "--include", "properties")
    assert code == 4 and env["ok"]  # the damaged file makes the listing partial, not failed
    cli_docs = _check_listing(env["data"]["entries"])
    rest_docs = _parts_and_assemblies(
        service.get("list", root="jobs", include="properties,preview").json()["data"]["entries"]
    )
    assert cli_docs == rest_docs  # the same entries: the root is the listed folder
    python = scan(folder, include=("properties", "preview")).listing()
    assert _parts_and_assemblies(python["entries"]) == cli_docs
    code, env = _cli(capsys, "preview", str(folder / PART), "-o", str(tmp_path / "part.png"))
    assert code == 0 and (tmp_path / "part.png").read_bytes().startswith(PNG)
    code, env = _cli(capsys, "components", str(folder / ASSEMBLY))
    assert code == 0
    _check_components(env["data"])
    with open_document(folder / ASSEMBLY) as doc:
        assert env["data"] == model.build_components(doc)


def _automation(modules: list[str]) -> list[str]:
    return [m for m in modules if any(m == a or m.startswith(a + ".") for a in AUTOMATION)]


def test_nothing_loads_solidworks_automation(folder):
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(SRC), str(TESTS)])}
    done = subprocess.run(
        [sys.executable, str(TESTS / "done_child.py"), str(folder), ASSEMBLY, PART],
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    result = json.loads(done.stdout.strip().splitlines()[-1])
    assert result["codes"] == [4, 0, 0]  # the damaged file makes the listing partial
    assert result["statuses"] == [200, 200, 200]
    for where in ("process", "worker"):
        modules = result[where]
        # the lists are real: both processes read documents
        assert "solidseas.formats.solidworks.components" in modules, where
        assert _automation(modules) == [], where
    # control: the same check finds the automation package once it is loaded
    assert _automation([*result["process"], "solidseas.swapi"]) == ["solidseas.swapi"]
