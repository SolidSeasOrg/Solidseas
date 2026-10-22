"""``/v1/identity`` (``docs/API.md`` 8.16, security review finding 15): a client checks that it
is talking to the service that holds its token before it sends the token.

The route is checked from outside: the proof is the documented HMAC, each client's own,
fresh for every nonce, bound to the address and port the connection reached, the same
shape for a name that does not exist, and free of the token. Then the documented Python
client, and the TypeScript client when Node is installed, run as API.md prints them
against the real service and against impostors: one that guesses, one that replays a
proof it collected from the real service, one that forwards each question to the real
service from another port or address, and one that takes the service's own port once
the service has stopped. No impostor ever receives the token. Each client sends its
token only on the connection it checked: the TypeScript one, in a process that lives
on while a stand-in gives up the port and the service starts there, never reuses a
connection from before, and fails rather than open a connection it did not check.
"""

import hashlib
import hmac
import http.client
import http.server
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

from jsonschema_subset import validate
from serve_support import OTHER_TOKEN, TOKEN, Running
from solidseas import model
from solidseas.errors import IdentityKeyError
from solidseas.serve import IDENTITY_SCHEME, identity_proof, proof_address
from solidseas.serve.tokens import TokenChecker
from support import ASSEMBLY, fixture_path

pytestmark = pytest.mark.usefixtures("outbound_guard")
API_MD = Path(__file__).resolve().parents[1] / "docs" / "API.md"
O02 = fixture_path("o02_boxA.SLDPRT")
TOKENS = {"erp": TOKEN, "store": OTHER_TOKEN}


def _expected(token: str, client: str, nonce: str, address: str, port: int) -> str:
    """The proof as API.md 8.16 defines it, computed here without SolidSeas."""
    message = "\n".join(["solidseas-identity-v1", client, nonce, address, str(port)]).encode("ascii")
    return hmac.new(token.encode("ascii"), message, hashlib.sha256).hexdigest()


def _root(tmp: Path) -> Path:
    tmp.mkdir(parents=True, exist_ok=True)
    shutil.copy2(O02, tmp / "a.SLDPRT")
    return tmp


@pytest.fixture(scope="module")
def srv(tmp_path_factory):
    running = Running({"jobs": _root(tmp_path_factory.mktemp("identity"))}, tokens=TOKENS, workers=1)
    yield running
    running.close()


def _identity(srv, **params):
    return srv.get("identity", token=None, **params)


# --------------------------------------------------------------------------- the route
def test_the_service_proves_it_holds_each_clients_token(srv):
    nonce = secrets.token_urlsafe(32)
    r = _identity(srv, client="erp", nonce=nonce)
    env = r.json()
    assert r.status == 200 and validate(env, model.envelope_schema("identity"), strict=True) == []
    assert env["data"] == {
        "scheme": IDENTITY_SCHEME,
        "client": "erp",
        "nonce": nonce,
        "address": "127.0.0.1",
        "port": srv.port,
        "proof": _expected(TOKEN, "erp", nonce, "127.0.0.1", srv.port),
    }
    proof = env["data"]["proof"]
    assert proof == identity_proof(TOKEN, client="erp", nonce=nonce, address="127.0.0.1", port=srv.port)
    store = _identity(srv, client="store", nonce=nonce).json()["data"]["proof"]
    assert store == _expected(OTHER_TOKEN, "store", nonce, "127.0.0.1", srv.port) != proof  # its own token
    again = _identity(srv, client="erp", nonce=secrets.token_urlsafe(32)).json()["data"]["proof"]
    assert again != proof  # a fresh nonce, a fresh proof
    assert TOKEN.encode() not in r.body and OTHER_TOKEN.encode() not in r.body
    assert "etag" not in r.headers and r.headers["cache-control"] == "private, no-cache"
    assert nonce not in srv.log.text and "client=- " in srv.log.lines[-1]  # no query in the log


def test_an_unknown_name_gets_a_proof_that_looks_like_any_other(srv):
    nonce = secrets.token_urlsafe(32)
    r = _identity(srv, client="nobody", nonce=nonce)
    data = r.json()["data"]
    assert r.status == 200 and re.fullmatch(r"[0-9a-f]{64}", data["proof"])
    matching = {_expected(t, "nobody", nonce, "127.0.0.1", srv.port) for t in TOKENS.values()}
    assert data["proof"] not in matching
    assert _identity(srv, client="nobody", nonce=nonce).json()["data"]["proof"] == data["proof"]  # stable


def test_an_unknown_names_proof_survives_a_restart_as_a_real_names_does():
    """Two checkers over the same tokens stand for the service before and after a restart:
    a real name's proof is the same on both, so an unknown name's must be too, or asking
    before and after would tell which names exist. Without an identity key the stand-in
    comes from the tokens, so it changes with them, and it is not anything computable
    without them."""
    nonce, where = "n" * 43, ("127.0.0.1", 8765)
    before, after = TokenChecker(TOKENS), TokenChecker(dict(reversed(TOKENS.items())))
    assert before.identity("erp", nonce, *where) == after.identity("erp", nonce, *where)  # control
    unknown = before.identity("nobody", nonce, *where)
    assert unknown == after.identity("nobody", nonce, *where)
    assert unknown != before.identity("someone", nonce, *where)  # each name its own
    changed = TokenChecker({**TOKENS, "store": OTHER_TOKEN[::-1]})
    assert changed.identity("nobody", nonce, *where) != unknown
    public = [hashlib.sha256(b"nobody").hexdigest(), "nobody", "", IDENTITY_SCHEME]
    assert unknown not in {_expected(key, "nobody", nonce, *where) for key in public}
    assert unknown not in {_expected(t, "nobody", nonce, *where) for t in TOKENS.values()}


# --------------------------------------------------------------------------- the identity key (26a)
IDENTITY_KEY = ("identity-key-" + "Kk7_" * 8).encode("ascii")


def test_an_unknown_names_proof_survives_an_edit_of_the_token_file():
    """With the service's identity key, a line added to the token file or deleted from it
    changes no other name's proof, known or not: asking before and after an edit tells
    nothing but what the edit itself added or removed. The control is the stand-in made
    from the tokens, which changed for every unknown name while kept names kept theirs."""
    nonce, where = "n" * 43, ("127.0.0.1", 8765)
    before = TokenChecker(TOKENS, identity_key=IDENTITY_KEY)
    edits = {
        "added": TokenChecker({**TOKENS, "newcomer": "N" * 43}, identity_key=IDENTITY_KEY),
        "deleted": TokenChecker({"erp": TOKEN}, identity_key=IDENTITY_KEY),
        "reordered": TokenChecker(dict(reversed(TOKENS.items())), identity_key=IDENTITY_KEY),
    }
    unknown = before.identity("nobody", nonce, *where)
    for label, after in edits.items():
        assert after.identity("nobody", nonce, *where) == unknown, label
        assert after.identity("erp", nonce, *where) == before.identity("erp", nonce, *where), label
    # what the edit itself did does show: a deleted name gets a stand-in, an added one its token's proof
    assert edits["deleted"].identity("store", nonce, *where) != before.identity("store", nonce, *where)
    added = edits["added"].identity("newcomer", nonce, *where)
    assert added == _expected("N" * 43, "newcomer", nonce, *where)
    # control: keyed by the tokens alone, the same edit changes every unknown name's proof
    plain_before, plain_after = TokenChecker(TOKENS), TokenChecker({**TOKENS, "newcomer": "N" * 43})
    assert plain_after.identity("nobody", nonce, *where) != plain_before.identity("nobody", nonce, *where)
    assert plain_after.identity("erp", nonce, *where) == plain_before.identity("erp", nonce, *where)
    # the stand-in is the key's: another key gives another, and nothing public or a token computes it
    other = TokenChecker(TOKENS, identity_key=IDENTITY_KEY[::-1]).identity("nobody", nonce, *where)
    assert other != unknown and re.fullmatch(r"[0-9a-f]{64}", unknown)
    public = [IDENTITY_KEY.decode(), "nobody", "", IDENTITY_SCHEME, *TOKENS.values()]
    assert unknown not in {_expected(key, "nobody", nonce, *where) for key in public}


def test_an_identity_key_too_short_to_be_one_is_refused():
    with pytest.raises(IdentityKeyError) as caught:
        TokenChecker(TOKENS, identity_key=b"short")
    assert caught.value.code == "identity_key_refused" and caught.value.detail == {"rule": "malformed"}
    with pytest.raises(IdentityKeyError):
        TokenChecker(TOKENS, identity_key=IDENTITY_KEY.decode())  # text, not bytes
    assert TokenChecker(TOKENS, identity_key=IDENTITY_KEY)  # control


def test_the_service_keeps_an_unknown_names_proof_across_an_edit_of_its_tokens(tmp_path):
    """The same through the service, restarted on the same port as an administrator would
    after editing the token file: the unknown name's answer is the same before and after."""
    root = _root(tmp_path / "jobs")
    nonce = secrets.token_urlsafe(32)
    proofs = []
    port = 0
    for tokens in (TOKENS, {**TOKENS, "newcomer": "N" * 43}, {"erp": TOKEN}):
        running = None
        deadline = time.monotonic() + 10
        while running is None:
            try:
                running = Running(
                    {"jobs": root}, tokens=tokens, workers=1, port=port, identity_key=IDENTITY_KEY
                )
            except OSError:
                if time.monotonic() > deadline:
                    pytest.skip("the service's port could not be taken again here")
                time.sleep(0.2)
        try:
            port = running.port
            proofs.append(_identity(running, client="nobody", nonce=nonce).json()["data"]["proof"])
            assert _identity(running, client="erp", nonce=nonce).json()["data"]["proof"] == _expected(
                TOKEN, "erp", nonce, "127.0.0.1", port
            )
        finally:
            running.close()
    assert len(proofs) == 3 and len(set(proofs)) == 1


def test_the_cli_keeps_its_identity_key_beside_the_token_file(tmp_path, capsys, monkeypatch):
    """``solidseas serve`` makes the identity key file on its first start and reads it on
    every later one: an unknown name's proof is the same after the token file gains a
    line, and changes only when the key file is replaced (the control)."""
    import logging

    from solidseas import cli

    root = _root(tmp_path / "jobs")
    folder = tmp_path / "state"
    folder.mkdir(mode=0o700)
    token_file = folder / "tokens"
    nonce = secrets.token_urlsafe(32)
    proofs: list[str] = []

    def serve_once(server) -> None:  # in place of run_until_signalled: one question, then stop
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=30)
            conn.request("GET", f"/v1/identity?client=nobody&nonce={nonce}")
            proofs.append(json.loads(conn.getresponse().read())["data"]["proof"])
            conn.close()
        finally:
            server.shutdown(close_pool=True)

    monkeypatch.setattr("solidseas.serve.run_until_signalled", serve_once)
    log = logging.getLogger("solidseas.serve")  # leave the service's logger as it was
    monkeypatch.setattr(log, "handlers", list(log.handlers))
    monkeypatch.setattr(log, "propagate", log.propagate)
    with socket.socket() as probe:  # one port for every start: the proof covers the port
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    argv = ["serve", "--root", f"jobs={root}", "--port", str(port), "--workers", "1"]
    argv += ["--token-file", str(token_file)]

    def start():
        deadline = time.monotonic() + 10
        while (code := cli.main(argv)) == 1 and time.monotonic() < deadline:
            capsys.readouterr()  # address_unavailable: the last start's socket is still going
            time.sleep(0.2)
        assert code == 0
        return capsys.readouterr()

    first = start()
    assert "created the identity key file" in first.out
    key_file = folder / "tokens.identity"
    key = key_file.read_bytes()
    with open(token_file, "a", encoding="ascii") as fh:  # an administrator adds a client
        fh.write("newcomer:" + "N" * 43 + "\n")
    second = start()
    assert "created the identity key file" not in second.out and key_file.read_bytes() == key
    assert len(proofs) == 2 and proofs[0] == proofs[1]
    key_file.unlink()  # control: a new key, a new stand-in
    third = start()
    assert "created the identity key file" in third.out and key_file.read_bytes() != key
    assert len(proofs) == 3 and proofs[2] != proofs[0]
    assert key.decode("ascii").splitlines()[-1] not in first.out + second.out + third.out  # never printed


def test_the_route_needs_no_token_and_counts_no_failure(tmp_path):
    running = Running({"jobs": _root(tmp_path / "jobs")}, tokens=TOKENS, workers=1, max_auth_failures=3)
    try:
        nonce = secrets.token_urlsafe(32)
        for _ in range(6):
            r = running.request(f"/v1/identity?client=erp&nonce={nonce}", token=OTHER_TOKEN + "x")
            assert r.status == 200 and r.json()["data"]["proof"] == _expected(
                TOKEN, "erp", nonce, "127.0.0.1", running.port
            )
        assert running.request("/v1/version").status == 200  # not 429: no failure was counted
        for _ in range(4):
            assert running.request("/v1/version", token=OTHER_TOKEN + "x").status == 401
        assert running.request("/v1/version").status == 429  # control: the limit is in force
    finally:
        running.close()


@pytest.mark.parametrize(
    ("query", "code", "parameter"),
    [
        ("client=erp", "invalid_argument", "nonce"),
        ("nonce=" + "n" * 32, "invalid_argument", "client"),
        ("client=erp&nonce=" + "n" * 31, "invalid_argument", "nonce"),
        ("client=erp&nonce=" + "n" * 129, "invalid_argument", "nonce"),
        ("client=erp&nonce=" + "n" * 31 + "%2B", "invalid_argument", "nonce"),
        ("client=ERP&nonce=" + "n" * 32, "invalid_argument", "client"),
        ("client=erp&nonce=" + "n" * 32 + "&token=" + TOKEN, "unknown_parameter", "token"),
        ("client=erp&client=erp&nonce=" + "n" * 32, "duplicate_parameter", "client"),
    ],
)
def test_the_identity_query_is_checked(srv, query, code, parameter):
    r = srv.request(f"/v1/identity?{query}", token=None)
    assert r.status == 400 and r.json()["error"]["code"] == code
    assert r.json()["error"]["detail"] == {"parameter": parameter}


@pytest.mark.parametrize(
    ("host", "address"),
    [
        ("127.0.0.1", "127.0.0.1"),
        ("::1", "::1"),
        ("0:0:0:0:0:0:0:1", "::1"),
        ("::ffff:127.0.0.1", "127.0.0.1"),
        ("fe80::1%eth0", "fe80::1"),
        ("198.51.100.7", "198.51.100.7"),
    ],
)
def test_the_proof_names_an_address_one_way(host, address):
    assert proof_address(host) == address


# --------------------------------------------------------------------------- impostors
class Impostor:
    """A program that answers HTTP on a loopback port, as anything may while the service is
    stopped, recording every request it receives with its headers. ``answer(path)`` gives
    the body of the answer to each request."""

    def __init__(self, answer, *, host: str = "127.0.0.1", port: int = 0) -> None:
        seen = self.seen = []

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args) -> None:
                pass

            def do_GET(self) -> None:
                seen.append((self.path, {k.lower(): v for k, v in self.headers.items()}))
                body = answer(self.path)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        class Server(http.server.ThreadingHTTPServer):
            address_family = socket.AF_INET6 if ":" in host else socket.AF_INET
            daemon_threads = True

        self.httpd = Server((host, port), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def tokens_received(self) -> list[str]:
        return [h["authorization"] for _, h in self.seen if "authorization" in h]

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def _query(path: str) -> dict[str, str]:
    from urllib.parse import parse_qsl, urlsplit

    return dict(parse_qsl(urlsplit(path).query))


def _forged(path: str, proof: str, port: int) -> bytes:
    q = _query(path)
    data = model.build_identity(
        scheme=IDENTITY_SCHEME,
        client=q.get("client", ""),
        nonce=q.get("nonce", ""),
        address="127.0.0.1",
        port=port,
        proof=proof,
    )
    return model.dumps(model.envelope("identity", data)).encode("ascii")


def _forward(real_port: int):
    """Ask the real service each question this impostor is asked, and answer with its answer."""

    def answer(path: str) -> bytes:
        conn = http.client.HTTPConnection("127.0.0.1", real_port, timeout=10)
        try:
            conn.request("GET", path)
            return conn.getresponse().read()
        finally:
            conn.close()

    return answer


def _documented_python() -> dict:
    """The Python client of API.md 8.16, as printed."""
    text = API_MD.read_text(encoding="utf-8")
    section = text[text.index("### 8.16") : text.index("## 9. Stability")]
    block = re.search(r"```python\n(.*?)```", section, re.S).group(1)
    namespace: dict = {"__name__": "documented_client"}
    exec(compile(block, "API.md 8.16", "exec"), namespace)
    return namespace


def _fetch_document(client: dict, host: str, port: int, name: str = "erp", token: str = TOKEN):
    """What an integration does: check the connection, then send the token on it."""
    conn = client["checked_connection"](host, port, name, token)
    try:
        headers = {"Authorization": f"Bearer {token}"}
        conn.request("GET", "/v1/document?root=jobs&path=a.SLDPRT", headers=headers)
        return json.loads(conn.getresponse().read())
    finally:
        conn.close()


def test_the_documented_python_client_sends_its_token_only_to_the_service(srv):
    client = _documented_python()
    assert _fetch_document(client, "127.0.0.1", srv.port)["data"]["doc_type"] == "part"  # control
    collected = _identity(srv, client="erp", nonce=secrets.token_urlsafe(32)).json()["data"]["proof"]
    impostors = {
        "guesses": Impostor(lambda path: _forged(path, secrets.token_hex(32), 0)),
        "replays": Impostor(lambda path: _forged(path, collected, srv.port)),
        "forwards": Impostor(_forward(srv.port)),
        "answers_html": Impostor(lambda path: b"<html>not json</html>"),
    }
    try:
        for label, impostor in impostors.items():
            with pytest.raises(client["NotTheService"]):
                _fetch_document(client, "127.0.0.1", impostor.port)
            assert len(impostor.seen) == 1 and impostor.seen[0][0].startswith("/v1/identity?"), label
            assert impostor.tokens_received == [], label
        # the forwarder did reach the real service, and got a true proof, for the service's own port
        forwarded = impostors["forwards"].seen[0][0]
        nonce = _query(forwarded)["nonce"]
        real = _identity(srv, client="erp", nonce=nonce).json()["data"]
        assert real["proof"] == _expected(TOKEN, "erp", nonce, "127.0.0.1", srv.port)
        assert real["proof"] != _expected(TOKEN, "erp", nonce, "127.0.0.1", impostors["forwards"].port)
    finally:
        for impostor in impostors.values():
            impostor.close()


def test_a_checked_connection_never_reconnects_by_itself(srv):
    client = _documented_python()
    conn = client["checked_connection"]("127.0.0.1", srv.port, "erp", TOKEN)
    conn.close()  # as when the service closes it, or stops
    with pytest.raises(http.client.NotConnected):
        conn.request("GET", "/v1/version", headers={"Authorization": f"Bearer {TOKEN}"})


def test_a_forwarder_on_another_address_of_the_same_port_is_refused(srv):
    """A client that called localhost may reach [::1] while the service holds 127.0.0.1:
    a program there that forwards gets a proof for 127.0.0.1, which the client rejects."""
    try:
        impostor = Impostor(_forward(srv.port), host="::1", port=srv.port)
    except OSError:
        pytest.skip("IPv6 loopback is not available, or the port is held for both families")
    client = _documented_python()
    try:
        with pytest.raises(client["NotTheService"]):
            _fetch_document(client, "::1", impostor.port)
        assert len(impostor.seen) == 1 and impostor.tokens_received == []
    finally:
        impostor.close()


def test_a_program_that_takes_the_port_of_a_stopped_service_gets_no_token(tmp_path):
    """Finding 15 itself: the service stops, another program takes its port and answers
    with a proof it collected while the service ran. A client that checks sends nothing."""
    client = _documented_python()
    running = Running({"jobs": _root(tmp_path / "jobs")}, tokens=TOKENS, workers=1)
    port = running.port
    try:
        assert _fetch_document(client, "127.0.0.1", port)["data"]["doc_type"] == "part"  # control
        collected = running.get("identity", token=None, client="erp", nonce="c" * 43).json()["data"]["proof"]
    finally:
        running.close()
    impostor = None
    deadline = time.monotonic() + 10
    while impostor is None:
        try:
            impostor = Impostor(lambda path: _forged(path, collected, port), port=port)
        except OSError:
            if time.monotonic() > deadline:
                pytest.skip("the stopped service's port could not be taken again here")
            time.sleep(0.2)
    try:
        with pytest.raises(client["NotTheService"]):
            _fetch_document(client, "127.0.0.1", port)
        assert len(impostor.seen) == 1 and impostor.tokens_received == []
    finally:
        impostor.close()


# --------------------------------------------------------------------------- the TypeScript client
FETCH_ONE = """
async function fetchOne(): Promise<string> {
  try {
    const r = await get<{ doc_type: string }>("document", { root: "jobs", path: "a.SLDPRT" });
    return JSON.stringify({ doc_type: r.notModified ? null : r.data.doc_type });
  } catch (e) {
    return JSON.stringify({ error: String((e as Error).message) });
  }
}
"""
# Fetch one document and end.
ONCE = "console.log(await fetchOne());\n"
# Fetch one document for each line read, in one long-lived process, as a store's server does.
EACH_LINE = """
import { createInterface } from "node:readline";
for await (const _line of createInterface({ input: process.stdin })) console.log(await fetchOne());
"""
# Check a connection, then lose it, as when the service closes it, and send on it again.
RECONNECT = """
const conn = new CheckedConnection();
await checkService(conn);
await new Promise((done) => setImmediate(done));
for (const sockets of Object.values(conn.freeSockets)) for (const s of sockets ?? []) s.destroy();
try {
  const res = await send(conn, "/v1/version", { Authorization: `Bearer ${TOKEN}` }, 10_000);
  console.log(JSON.stringify({ status: res.status }));
} catch (e) {
  console.log(JSON.stringify({ error: String((e as Error).message) }));
} finally {
  conn.destroy();
}
"""


def _ts_block(text: str, start: str, end: str) -> str:
    return re.search(r"```ts\n(.*?)```", text[text.index(start) : text.index(end)], re.S).group(1)


def _documented_typescript(tmp_path: Path, driver: str = ONCE, *, recipe: str = "") -> Path:
    """The TypeScript client of API.md 10.1 with the check of 8.16, as printed, with the
    port read from the environment, then ``recipe``; and a driver that uses them."""
    text = API_MD.read_text(encoding="utf-8")
    code = _ts_block(text, "### 10.1", "### 10.2")
    assert code.count("const PORT = 8765;") == 1
    code = code.replace("const PORT = 8765;", "const PORT = Number(process.env.SOLIDSEAS_PORT);")
    module = tmp_path / "client.mts"
    check = _ts_block(text, "### 8.16", "## 9. Stability")
    module.write_text("\n".join([check, code, recipe, FETCH_ONE, driver]), encoding="utf-8")
    return module


def _node(module: Path, port: int, token: str) -> dict:
    env = {**os.environ, "SOLIDSEAS_PORT": str(port), "SOLIDSEAS_TOKEN": token}
    done = subprocess.run(["node", str(module)], capture_output=True, text=True, timeout=60, env=env)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not on PATH")
def test_the_documented_typescript_client_sends_its_token_only_to_the_service(srv, tmp_path):
    module = _documented_typescript(tmp_path)
    assert _node(module, srv.port, OTHER_TOKEN) == {"doc_type": "part"}  # the store's token: control
    collected = _identity(srv, client="store", nonce=secrets.token_urlsafe(32)).json()["data"]["proof"]
    for answer in (
        lambda path: _forged(path, secrets.token_hex(32), 0),
        lambda path: _forged(path, collected, srv.port),
        _forward(srv.port),
    ):
        impostor = Impostor(answer)
        try:
            result = _node(module, impostor.port, OTHER_TOKEN)
            assert "could not prove it holds the token" in result["error"]
            assert len(impostor.seen) == 1 and impostor.tokens_received == []
        finally:
            impostor.close()


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not on PATH")
def test_the_typescript_client_never_opens_a_connection_it_did_not_check(srv, tmp_path):
    """The TypeScript counterpart of the Python client's test above: once the checked
    connection is gone, a request on it fails rather than go out on a new one."""
    result = _node(_documented_typescript(tmp_path, RECONNECT), srv.port, OTHER_TOKEN)
    assert result == {"error": "the checked connection closed; the token was not sent"}


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not on PATH")
def test_the_documented_store_page_sends_its_token_only_to_the_service(tmp_path):
    """API.md 10.4 fetches a preview and a component tree through the client of 10.1, so
    both requests are checked first, each on the connection that carries it: the service
    accepts one connection per request, not one for the check and one for the token."""
    root = _root(tmp_path / "jobs")
    shutil.copy2(fixture_path(ASSEMBLY), root / "asm.SLDASM")
    text = API_MD.read_text(encoding="utf-8")
    page = """
try {
  const p = await productPage("asm.SLDASM");
  const thumbnail = p.thumbnail?.subarray(1, 4).toString(); // "PNG" from the signature
  console.log(JSON.stringify({ thumbnail, components: p.components }));
} catch (e) {
  console.log(JSON.stringify({ error: String((e as Error).message) }));
}
"""
    module = _documented_typescript(tmp_path, page, recipe=_ts_block(text, "### 10.4", "### 10.5"))
    running = Running({"jobs": root}, tokens=TOKENS, workers=1)
    accepted = []
    accept = running.server.httpd.process_request

    def counted(request, client_address):
        accepted.append(client_address)
        accept(request, client_address)

    running.server.httpd.process_request = counted
    try:
        result = _node(module, running.port, OTHER_TOKEN)
    finally:
        running.close()
    assert result == {"thumbnail": "PNG", "components": [{"name": "o02_boxA", "quantity": 2}]}
    routes = [line.split(" route=")[1].split()[0] for line in running.log.lines if " route=" in line]
    assert routes == ["/v1/identity", "/v1/preview", "/v1/identity", "/v1/components"]
    assert len(accepted) == 2  # a check and its request share one connection
    impostor = Impostor(lambda path: _forged(path, secrets.token_hex(32), 0))
    try:
        assert "could not prove it holds the token" in _node(module, impostor.port, OTHER_TOKEN)["error"]
        assert len(impostor.seen) == 1 and impostor.tokens_received == []
    finally:
        impostor.close()


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not on PATH")
def test_the_typescript_client_never_reuses_a_connection_from_before_the_service_ran(tmp_path):
    """A client that keeps connections open can hold one that another program accepted
    while the service was stopped. Once the service runs, that program can forward a check
    to it, which answers for the same address and port, and then take the token on the
    same connection. One Node process lives through it all, as a store's server does: it
    is refused by a stand-in on the port, the stand-in lets go of the port but keeps its
    connections, and the service starts there. The documented client checks and sends on
    a new connection each time, so the stand-in hears one question and never a token."""
    asked: list[str] = []

    def answer(path: str) -> bytes:
        asked.append(path)
        if len(asked) == 1:
            return _forged(path, secrets.token_hex(32), 0)  # refused: the service is not running yet
        return _forward(port)(path)  # later questions go to the service, which holds the port by then

    stand_in = Impostor(answer)
    port = stand_in.port
    module = _documented_typescript(tmp_path, EACH_LINE)
    env = {**os.environ, "SOLIDSEAS_PORT": str(port), "SOLIDSEAS_TOKEN": OTHER_TOKEN}
    node = subprocess.Popen(
        ["node", str(module)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env
    )

    def fetch() -> dict:
        node.stdin.write("fetch\n")
        node.stdin.flush()
        return json.loads(node.stdout.readline())

    running = None
    try:
        assert "could not prove it holds the token" in fetch()["error"]
        stand_in.httpd.shutdown()
        stand_in.httpd.server_close()  # the port is free; the connections it accepted stay open
        deadline = time.monotonic() + 10
        while running is None:
            try:
                running = Running({"jobs": _root(tmp_path / "jobs")}, tokens=TOKENS, workers=1, port=port)
            except OSError:
                if time.monotonic() > deadline:
                    pytest.skip("the stand-in's port could not be taken again here")
                time.sleep(0.2)
        assert fetch() == {"doc_type": "part"}
        assert len(stand_in.seen) == 1 and stand_in.tokens_received == []
        assert fetch() == {"doc_type": "part"}  # and again, on another new connection
        assert len(stand_in.seen) == 1
    finally:
        node.stdin.close()
        try:
            node.wait(timeout=30)
        finally:
            node.kill()
            node.stdout.close()
        if running is not None:
            running.close()
        stand_in.close()
