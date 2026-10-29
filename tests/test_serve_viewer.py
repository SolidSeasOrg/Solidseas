"""``/v1/mesh`` and the reference viewer (``docs/API.md`` 8.6 and 8.18).

The route answers the GLB ``solidseas.gltf.display_glb`` writes, byte for byte, with the
service's headers, its ETag and its refusals; a worker's answer that is not a GLB is never
served. The viewer is off unless asked for; on, its page and files need no token, carry
the page's own policy (its import map by hash, nothing from elsewhere), and its page's own
origin may call the routes. The vendored three.js is the published release, unchanged,
and three.js's own GLTFLoader, run by Node, reads what the route answers.
"""

import base64
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from serve_support import Running
from solidseas import open_document
from solidseas.gltf import display_glb, is_glb
from solidseas.serve import server as server_mod
from solidseas.workers import WorkerPool
from support import fixture_path

pytestmark = pytest.mark.usefixtures("outbound_guard")
ROOT = Path(__file__).resolve().parents[1]
VIEWER = ROOT / "src" / "solidseas" / "serve" / "viewer"
THREE = VIEWER / "three"
O02 = fixture_path("o02_boxA.SLDPRT")
O16 = fixture_path("o16_asm_features.SLDASM")
O18 = fixture_path("o18_drw_boxA.SLDDRW")
# three.js 0.185.1 from the npm registry: the tarball's published integrity is
# sha512-5aojFCXKwnjBRZvUnt3WFfEcvUJgkN5LlijRFN95hMy8WVkG4I0QNcJE+OuWvuJ0bOdStrbfXn0pkd6/QyiAlg==
# and these are the files taken from it, unchanged.
JSM = "examples/jsm/"
THREE_FILES = {
    "LICENSE": "8b378ebe60e2fe500158cb0ac71cb5e8b7d92953c2abcc63a0eb90499653b5bc",
    "build/three.core.min.js": "05b2609338c76cd65daf74f3ac515bc9a5045e1b3b33edc07d8c9bd55250fa90",
    "build/three.module.min.js": "86bcee248b64f44bcfc23c331ae74619061957d59cab040171dcb6fb5900beb6",
    JSM + "controls/OrbitControls.js": "faabb4e8dfd9235ee4a9fd7c9a3d75f90f1689dbd4944bd6fd32117dacec5f93",
    JSM + "loaders/GLTFLoader.js": "97642d720f16cc9a0c9844934198e4d0c023bea8e89576d0f7545d03b2d103d2",
    JSM + "utils/BufferGeometryUtils.js": "5c552223a9309883743b80538d6e9cdb45e3227f30d3ec56fb2c39b46e78d595",
    JSM + "utils/SkeletonUtils.js": "b1632a703206c3d830de9fcbe515696770d04b71a15ee6b50afa6d2c3298c86f",
}


@pytest.fixture(scope="module")
def root(tmp_path_factory) -> Path:
    base = tmp_path_factory.mktemp("viewer") / "jobs"
    base.mkdir()
    for p in (O02, O16, O18):
        shutil.copy2(p, base / p.name)
    return base


@pytest.fixture(scope="module")
def srv(root):
    running = Running({"jobs": root}, viewer=True)
    yield running
    running.close()


@pytest.fixture(scope="module")
def plain(root):
    running = Running({"jobs": root}, workers=1)
    yield running
    running.close()


# --------------------------------------------------------------------------- /v1/mesh
@pytest.mark.parametrize("name", ["o02_boxA.SLDPRT", "o16_asm_features.SLDASM"])
def test_the_mesh_route_answers_the_documents_glb(plain, root, name):
    r = plain.get("mesh", root="jobs", path=name)
    assert r.status == 200 and r.headers["content-type"] == "model/gltf-binary" and is_glb(r.body)
    with open_document(root / name) as doc:
        assert r.body == display_glb(doc)[1]  # what the library writes, byte for byte
    assert r.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'; sandbox"
    assert r.headers["x-content-type-options"] == "nosniff"
    again = plain.request(f"/v1/mesh?root=jobs&path={name}", headers={"If-None-Match": r.headers["etag"]})
    assert again.status == 304 and again.body == b""
    preview = plain.get("preview", root="jobs", path=name)
    assert preview.headers["etag"] != r.headers["etag"]  # each route its own tag


@pytest.mark.parametrize(
    ("query", "status", "code"),
    [
        ("root=jobs&path=o18_drw_boxA.SLDDRW", 404, "nothing_to_export"),
        ("root=jobs&path=missing.SLDPRT", 404, "not_found"),
        ("root=jobs&path=o02_boxA.SLDPRT&configuration=Nope", 404, "configuration_not_found"),
        ("root=jobs&path=notes.txt", 403, "path_refused"),
        ("root=jobs&path=o02_boxA.SLDPRT&nested=x", 400, "unknown_parameter"),
        ("root=jobs", 400, "invalid_argument"),
    ],
)
def test_the_mesh_route_refuses_what_it_cannot_draw(plain, query, status, code):
    r = plain.request(f"/v1/mesh?{query}")
    assert r.status == status and r.json()["error"]["code"] == code
    assert r.headers["content-type"] == "application/json; charset=utf-8"


def test_the_mesh_route_needs_the_token(plain):
    r = plain.request("/v1/mesh?root=jobs&path=o02_boxA.SLDPRT", token=None)
    assert r.status == 401 and r.json()["error"]["code"] == "unauthorized"


def test_a_model_file_has_no_mesh_yet(tmp_path):
    shutil.copy2(fixture_path("o02_boxA.STL"), tmp_path / "box.stl")
    running = Running({"m": tmp_path}, workers=1, formats="all")
    try:
        r = running.get("mesh", root="m", path="box.stl")
        assert r.status == 501 and r.json()["error"]["detail"]["rule"] == "model_file"
    finally:
        running.close()


def test_mesh_answers_past_their_own_limit_answer_busy(plain):
    """Each may hold tens of MiB, so few are read at once, within the requests' own limit."""
    held = plain.server._mesh_slots
    taken = 0
    while held.acquire(blocking=False):
        taken += 1
    try:
        r = plain.get("mesh", root="jobs", path="o02_boxA.SLDPRT")
        assert r.status == 503 and r.json()["error"]["detail"] == {"rule": "mesh_in_flight"}
        assert r.headers["retry-after"] == "2"
        assert plain.get("document", root="jobs", path="o02_boxA.SLDPRT").status == 200  # others go on
    finally:
        for _ in range(taken):
            held.release()
    assert taken == 2 and plain.get("mesh", root="jobs", path="o02_boxA.SLDPRT").status == 200


def test_only_a_checked_glb_is_served(tmp_path):
    shutil.copy2(O02, tmp_path / "a.SLDPRT")
    pool = WorkerPool(1, reader_message=False, jobs={"display_glb": "worker_jobs:html_preview"})
    running = Running({"a": tmp_path}, pool=pool)
    try:
        r = running.get("mesh", root="a", path="a.SLDPRT")
        assert r.status == 500 and r.json()["error"]["code"] == "worker_crashed"
        assert r.headers["content-type"] == "application/json; charset=utf-8" and b"<html" not in r.body
    finally:
        running.close()
        pool.close()


# --------------------------------------------------------------------------- the viewer, off
@pytest.mark.parametrize("path", ["/", "/viewer", "/viewer/", "/viewer/viewer.js"])
def test_the_viewer_is_off_unless_asked_for(plain, path):
    assert plain.request(path, token=None).status == 401  # an unknown route, as before
    r = plain.request(path)
    assert r.status == 404 and r.json()["error"]["detail"] == {"rule": "route"}


def test_without_the_viewer_the_services_own_origin_is_refused(plain):
    r = plain.request("/v1/version", headers={"Origin": f"http://127.0.0.1:{plain.port}"})
    assert r.status == 403 and r.json()["error"]["code"] == "forbidden_origin"


# --------------------------------------------------------------------------- the viewer, on
def _import_map_hash() -> str:
    page = (VIEWER / "index.html").read_bytes()
    (text,) = re.findall(rb'<script type="importmap">(.*?)</script>', page, re.S)
    return "'sha256-" + base64.b64encode(hashlib.sha256(text).digest()).decode() + "'"


def test_the_page_is_served_with_its_own_policy(srv):
    r = srv.request("/viewer/", token=None)
    assert r.status == 200 and r.headers["content-type"] == "text/html; charset=utf-8"
    assert r.body == (VIEWER / "index.html").read_bytes()
    assert r.headers["content-security-policy"] == (
        f"default-src 'none'; script-src 'self' {_import_map_hash()}; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'"
    )
    for name, value in (
        ("x-frame-options", "DENY"),
        ("x-content-type-options", "nosniff"),
        ("referrer-policy", "no-referrer"),
        ("cross-origin-resource-policy", "same-origin"),
    ):
        assert r.headers[name] == value, name
    assert srv.request("/viewer/", token=None, headers={"If-None-Match": r.headers["etag"]}).status == 304
    assert srv.request("/viewer/", token=None, method="HEAD").body == b""


def test_every_file_of_the_viewer_is_served_with_a_fixed_type(srv):
    files = sorted(p for p in VIEWER.rglob("*") if p.is_file())
    assert len(files) == 10
    for p in files:
        rel = p.relative_to(VIEWER).as_posix()
        if rel == "index.html":
            continue
        r = srv.request(f"/viewer/{rel}", token=None)
        assert r.status == 200 and r.body == p.read_bytes(), rel
        want = {".js": "text/javascript", ".css": "text/css", "": "text/plain"}[p.suffix]
        assert r.headers["content-type"] == f"{want}; charset=utf-8", rel
        assert r.headers["content-security-policy"].startswith("default-src 'none'"), rel


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("/viewer/missing.js", 404),
        ("/viewer/index.html", 404),  # the page is at /viewer/ alone
        ("/viewer/../server.py", 404),
        ("/viewer/viewer.js?v=1", 400),
        ("/viewer/?token=x", 400),
    ],
)
def test_the_viewer_serves_nothing_else(srv, path, status):
    r = srv.request(path, token=None)
    assert r.status == status and r.headers["content-type"] == "application/json; charset=utf-8"


@pytest.mark.parametrize("path", ["/", "/viewer"])
def test_the_viewer_is_found_from_the_services_address(srv, path):
    r = srv.request(path, token=None)
    assert r.status == 308 and r.headers["location"] == "/viewer/" and r.body == b""


def test_the_viewer_needs_the_host_check_and_takes_only_get(srv):
    from serve_support import status_of

    raw = srv.raw(b"GET /viewer/ HTTP/1.1\r\nHost: evil.example\r\nConnection: close\r\n\r\n")
    assert status_of(raw) == 403
    assert srv.request("/viewer/", token=None, method="POST").status == 405


def test_the_pages_own_origin_may_call_the_routes(srv):
    own = {"Origin": f"http://127.0.0.1:{srv.port}", "Sec-Fetch-Site": "same-origin"}
    r = srv.request("/v1/version", headers=own)
    assert r.status == 200 and "access-control-allow-origin" not in r.headers  # same origin: no CORS
    assert srv.request("/viewer/viewer.js", token=None, headers=own).status == 200  # a module script
    for other in (
        f"http://localhost:{srv.port}",
        f"http://127.0.0.1:{srv.port + 1}",
        "null",
        "https://evil.example",
    ):
        r = srv.request("/v1/version", headers={"Origin": other})
        assert r.status == 403 and r.json()["error"]["code"] == "forbidden_origin", other


def test_the_viewer_requests_are_logged_without_their_paths(srv):
    srv.request("/viewer/three/build/three.core.min.js", token=None)
    line = srv.log.lines[-1]
    assert "route=/viewer " in line and "three" not in line and "status=200" in line


# --------------------------------------------------------------------------- what the page is made of
def test_the_viewer_loads_nothing_from_anywhere_else():
    own = {p.name: p.read_text(encoding="utf-8") for p in VIEWER.glob("*.*")}
    assert set(own) == {"index.html", "viewer.css", "viewer.js"}
    for name, text in own.items():
        assert not re.search(r"https?://|//[a-z0-9.-]+\.[a-z]{2,}/|url\(", text), name
    imports = re.findall(r'from "([^"]+)"', own["viewer.js"])
    addons = ["three/addons/controls/OrbitControls.js", "three/addons/loaders/GLTFLoader.js"]
    assert imports == ["three", *addons]
    module_import = re.compile(r"""(?:^|[;}\s])(?:import|export)\b[^'"]*?from\s*['"]([^'"]+)['"]""")
    for p in THREE.rglob("*.js"):
        lines = p.read_text("utf-8").splitlines()
        code = [line for line in lines if not line.lstrip().startswith(("*", "//"))]
        for target in module_import.findall("\n".join(code)):
            assert target == "three" or target.startswith(("./", "../")), (p.name, target)
    assert re.findall(r'(?:src|href)="([^"]+)"', own["index.html"]) == ["data:,", "viewer.css", "viewer.js"]


def test_the_viewer_never_builds_markup_from_what_the_service_says():
    script = (VIEWER / "viewer.js").read_text(encoding="utf-8")
    banned_words = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function")
    for banned in (*banned_words, "localStorage", "sessionStorage", "cookie"):
        assert banned not in script, banned
    page = (VIEWER / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"\son[a-z]+=", page) and page.count("<script") == 2  # the map, the module
    assert 'credentials: "omit"' in script and 'redirect: "error"' in script


def test_the_vendored_three_js_is_the_published_release_unchanged():
    found = {p.relative_to(THREE).as_posix(): p for p in THREE.rglob("*") if p.is_file()}
    assert set(found) == set(THREE_FILES)
    for rel, digest in THREE_FILES.items():
        data = found[rel].read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest, rel
        assert b"\r" not in data, rel  # .gitattributes keeps the bytes on every checkout
    assert re.search(r'const \w+="185"', found["build/three.core.min.js"].read_text("utf-8")[:400])
    licence = found["LICENSE"].read_text("utf-8")
    assert licence.startswith("The MIT License") and "three.js authors" in licence
    assert (ROOT / "licenses" / "three.js-LICENSE.txt").read_bytes() == found["LICENSE"].read_bytes()


def test_the_package_carries_the_viewer():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"solidseas.serve" = ["viewer/*.*", "viewer/three/**/*"]' in text
    assert server_mod.load_viewer().keys() >= {"/viewer/", "/viewer/viewer.js", "/viewer/three/LICENSE"}


# --------------------------------------------------------------------------- three.js reads it
CHECK = """
import { readFileSync } from "node:fs";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
const data = readFileSync(process.argv[2]);
const buffer = data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength);
new GLTFLoader().parse(buffer, "", (gltf) => {
  const meshes = [];
  gltf.scene.updateMatrixWorld(true);
  gltf.scene.traverse((o) => {
    if (o.isMesh) meshes.push({ id: o.userData.id ?? null, triangles: o.geometry.index.count / 3,
      normals: !!o.geometry.attributes.normal, world: o.matrixWorld.toArray() });
  });
  console.log(JSON.stringify({ meshes, extras: gltf.scene.userData.solidseas }));
}, (error) => console.log(JSON.stringify({ error: String(error) })));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not on PATH")
def test_three_js_reads_what_the_route_answers(plain, tmp_path):
    package = tmp_path / "node_modules" / "three"
    shutil.copytree(THREE, package)
    (package / "package.json").write_text(
        json.dumps(
            {
                "name": "three",
                "type": "module",
                "exports": {".": "./build/three.module.min.js", "./addons/*": "./examples/jsm/*"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "check.mjs").write_text(CHECK, encoding="utf-8")
    model = tmp_path / "model.glb"
    model.write_bytes(plain.get("mesh", root="jobs", path="o16_asm_features.SLDASM").body)
    done = subprocess.run(
        ["node", str(tmp_path / "check.mjs"), str(model)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    got = json.loads(done.stdout.strip().splitlines()[-1])
    assert "error" not in got, got
    from solidseas import Roots
    from solidseas.geometry import display_geometry

    with open_document(O16) as doc:
        g = display_geometry(doc, roots=Roots([]), allow_outside_roots=False, sources=("assembly", "nested"))
    assert [m["id"] for m in got["meshes"]] == [i.id for i in g.instances]
    for m, inst in zip(got["meshes"], g.instances, strict=True):
        assert all(abs(a - b) < 1e-9 for a, b in zip(m["world"], inst.matrix(), strict=True))
        assert m["normals"] and m["triangles"] == g.meshes[inst.mesh].triangles
    assert got["extras"]["instances"] == 12 and got["extras"]["units"] == "m"


def test_the_viewer_flag_says_it_is_provisional():
    import argparse

    from solidseas import cli

    parser = cli.build_parser()
    (sub,) = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    (flag,) = [a for a in sub.choices["serve"]._actions if "--viewer" in a.option_strings]
    assert "reference web viewer" in flag.help and "(provisional)" in flag.help
