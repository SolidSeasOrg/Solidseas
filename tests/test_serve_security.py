"""The service's security rules (``docs/API.md`` section 8), tested from outside.

Bind and token, Host, Origin and Fetch Metadata, methods, request limits, the
query allowlist, path confinement (encoded traversal, links and junctions,
alternate data streams, device names, hard links), hostile files through the
worker pool with its deadline and crash paths, response caps, headers, logs that
leak nothing, and a shutdown that ends even with a worker stuck. Every check that
looks for an absence is paired with one that proves the thing exists.
"""

import hashlib
import ipaddress
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote

import pytest

from builders import build_modern, fixture_streams, rebuild
from serve_support import (
    OTHER_TOKEN,
    PNG,
    TOKEN,
    OutboundConnection,
    Response,
    Running,
    body_of,
    status_of,
    wait_for,
)
from solidseas import Root, Roots, cli, open_document
from solidseas import walk as walk_mod
from solidseas.errors import (
    BindRefusedError,
    IdentityKeyError,
    LinkRefusedError,
    TokenFileError,
    WorkerJobError,
)
from solidseas.gltf import is_glb
from solidseas.serve import (
    ROUTES,
    ServeConfig,
    check_bind,
    create_identity_key_file,
    default_identity_key_file,
    ensure_identity_key,
    ensure_token_file,
    load_identity_key,
    load_tokens,
)
from solidseas.serve import tokens as token_mod
from solidseas.workers import WorkerPool
from support import NATIVE, PARTS, fixture_path
from test_hardening import LEGACY_LIES, _eocd_flood, _legacy_crafted, _local_bodies, _runaway_strings
from test_model import _custom_xml
from test_pathreport import PLANTED, PLANTED_NAMES, planted_part

pytestmark = pytest.mark.usefixtures("outbound_guard")
WINDOWS = sys.platform == "win32"
O02 = fixture_path("o02_boxA.SLDPRT")
O04 = fixture_path("o04_boxA_props.SLDPRT")
O08 = fixture_path("o08_asm_2x_boxA.SLDASM")
SRC = Path(__file__).resolve().parents[1] / "src"
SERVE_DIR = SRC / "solidseas" / "serve"
PLANTED_VALUE = "ZQ7-PROPERTY-SECRET-4411"
PLANTED_TOKEN = "zq7plantedtoken" + "Q" * 30
SECURITY = {
    "x-content-type-options": "nosniff",
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'; sandbox",
    "cross-origin-resource-policy": "same-origin",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _raw(port: int, lines: list[str], *, body: bytes = b"") -> bytes:
    data = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body
    with socket.create_connection(("127.0.0.1", port), timeout=20) as s:
        s.sendall(data)
        out = []
        while True:
            try:
                chunk = s.recv(65536)
            except (ConnectionResetError, ConnectionAbortedError):
                break
            if not chunk:
                break
            out.append(chunk)
    return b"".join(out)


def _headers_of(raw: bytes) -> dict[str, str]:
    head = raw.split(b"\r\n\r\n", 1)[0].decode("latin-1").split("\r\n")[1:]
    return {k.strip().lower(): v.strip() for k, _, v in (line.partition(":") for line in head)}


def _snapshot(root: Path) -> dict:
    """Every file below ``root`` (links not followed) with its hash and times, and every
    folder's entries: what a read-only service must leave exactly as it found it."""
    out: dict = {}
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(folder, d)) and d != "escape"]
        out[folder] = sorted(os.listdir(folder))
        for name in files:
            p = os.path.join(folder, name)
            st = os.lstat(p)
            if os.path.islink(p):
                continue
            with open(p, "rb") as fh:
                out[p] = (st.st_size, st.st_mtime_ns, hashlib.sha256(fh.read()).hexdigest())
    return out


def _leaky_part(tmp: Path) -> bytes:
    base = tmp / "planted.SLDPRT"
    base.write_bytes(planted_part())
    return rebuild(base, {"docProps/custom.xml": _custom_xml(("Zq7Secret", "lpwstr", PLANTED_VALUE))})


# --------------------------------------------------------------------------- the served tree
@pytest.fixture(scope="module")
def tree(tmp_path_factory) -> Path:
    base = tmp_path_factory.mktemp("security")
    jobs = base / "jobs"
    jobs.mkdir()
    for name in NATIVE:
        shutil.copy2(fixture_path(name), jobs / name)
    (jobs / "sub").mkdir()
    shutil.copy2(fixture_path(PARTS[3]), jobs / "sub" / PARTS[3])
    (jobs / "leaky.SLDPRT").write_bytes(_leaky_part(base))
    shutil.copy2(O02, jobs / "twin_a.SLDPRT")
    try:
        os.link(jobs / "twin_a.SLDPRT", jobs / "twin_b.SLDPRT")
    except OSError:
        pass
    outside = base / "outside"
    outside.mkdir()
    shutil.copy2(O02, outside / "secret.SLDPRT")
    if WINDOWS:
        import _winapi

        _winapi.CreateJunction(str(outside), str(jobs / "escape"))
    else:
        os.symlink(outside, jobs / "escape", target_is_directory=True)
    return base


@pytest.fixture(scope="module")
def srv(tree):
    before = _snapshot(tree / "jobs")
    running = Running({"jobs": tree / "jobs"}, max_auth_failures=10_000)
    yield running
    running.close()
    assert _snapshot(tree / "jobs") == before, "the service changed something in its root"


# --------------------------------------------------------------------------- the catalog
def test_the_catalog_is_never_kept_under_a_root(tmp_path, monkeypatch):
    """The service writes nothing under a root, its catalog included: a cache folder
    inside a root (set there, or a root at the home folder that holds the cache) is
    refused before anything starts."""
    from solidseas.errors import InvalidArgumentError

    home = tmp_path / "home"
    (home / "jobs").mkdir(parents=True)
    roots = Roots([Root("home", str(home))])
    with pytest.raises(InvalidArgumentError) as err:
        ServeConfig(roots=roots, tokens={"t": TOKEN}, catalog=True, catalog_cache_dir=str(home / ".cache"))
    assert err.value.detail == {"parameter": "catalog"} and "root home" in str(err.value)
    monkeypatch.setenv("SOLIDSEAS_CACHE_DIR", str(home / "jobs" / "cache"))
    with pytest.raises(InvalidArgumentError):
        ServeConfig(roots=roots, tokens={"t": TOKEN}, catalog=True)
    outside = str(tmp_path / "cache")
    assert ServeConfig(roots=roots, tokens={"t": TOKEN}, catalog=True, catalog_cache_dir=outside).catalog
    assert not ServeConfig(roots=roots, tokens={"t": TOKEN}).catalog  # no catalog, nothing to keep


# --------------------------------------------------------------------------- bind
def test_the_default_bind_is_loopback(srv):
    assert ServeConfig(roots=Roots([Root("a", str(SRC))]), tokens={"t": TOKEN}).host == "127.0.0.1"
    host = srv.server.httpd.socket.getsockname()[0]
    assert host == "127.0.0.1" and ipaddress.ip_address(host).is_loopback


def test_localhost_means_127_0_0_1_and_loopback_needs_nothing_more():
    assert check_bind("localhost", allow_remote=False, allowed_hosts=()) == "127.0.0.1"
    assert check_bind("127.0.0.1", allow_remote=False, allowed_hosts=()) == "127.0.0.1"
    assert check_bind("::1", allow_remote=False, allowed_hosts=()) == "::1"


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "198.51.100.10", "fileserver"])
def test_any_other_bind_needs_allow_remote_and_an_allowed_host(host):
    with pytest.raises(BindRefusedError) as caught:
        check_bind(host, allow_remote=False, allowed_hosts=())
    assert caught.value.detail == {"rule": "remote_not_allowed"}
    with pytest.raises(BindRefusedError) as caught:
        check_bind(host, allow_remote=True, allowed_hosts=())
    assert caught.value.detail == {"rule": "no_allowed_hosts"}
    assert check_bind(host, allow_remote=True, allowed_hosts=("store",)) == host


def _cli(capsys, *argv) -> tuple[int, dict]:
    code = cli.main([*argv, "--json"])
    out, err = capsys.readouterr()
    assert err == ""
    return code, json.loads(out)


def test_the_cli_refuses_a_remote_bind_before_anything_listens(tmp_path, capsys):
    port = _free_port()
    token_file = tmp_path / "tokens"
    base = ["serve", "--root", f"a={tmp_path}", "--port", str(port), "--token-file", str(token_file)]
    code, env = _cli(capsys, *base, "--bind", "0.0.0.0")
    assert code == 3 and env["error"]["code"] == "bind_refused"
    assert env["error"]["detail"] == {"rule": "remote_not_allowed"}
    code, env = _cli(capsys, *base, "--bind", "0.0.0.0", "--allow-remote")
    assert code == 3 and env["error"]["detail"] == {"rule": "no_allowed_hosts"}
    assert not token_file.exists()  # refused before the token file is touched
    with pytest.raises(OSError):  # and nothing listens on the port
        socket.create_connection(("127.0.0.1", port), timeout=3).close()


# --------------------------------------------------------------------------- the token
def test_every_route_but_health_and_identity_needs_the_token(srv):
    assert len(ROUTES) >= 12
    assert [p for p, r in ROUTES.items() if not r.auth] == ["/v1/health", "/v1/identity"]
    for route in ROUTES:
        for headers in (
            {},
            {"Authorization": f"Bearer {OTHER_TOKEN}"},
            {"Authorization": "Basic dXNlcjpwYXNz"},
        ):
            r = srv.request(route, token=None, headers=headers)
            if route == "/v1/health":
                assert r.status == 200 and r.json()["data"] == {"status": "ok"}
            elif route == "/v1/identity":  # its query is checked, not a token
                assert r.status == 400 and r.json()["error"]["detail"] == {"parameter": "client"}
                r = srv.request(f"{route}?client=tests&nonce={'n' * 32}", token=None, headers=headers)
                assert r.status == 200 and r.json()["kind"] == "identity"  # tests/test_serve_identity.py
            else:
                assert r.status == 401, (route, headers)
                assert r.headers["www-authenticate"] == 'Bearer realm="solidseas"'
                assert r.json()["error"]["code"] == "unauthorized"
    r = srv.request("/v1/roots")
    assert r.status == 200 and r.json()["data"]["roots"][0]["id"] == "jobs"  # control: the token works


def test_two_authorization_headers_are_refused(srv):
    raw = _raw(
        srv.port,
        [
            "GET /v1/version HTTP/1.1",
            f"Host: 127.0.0.1:{srv.port}",
            f"Authorization: Bearer {TOKEN}",
            f"Authorization: Bearer {TOKEN}",
            "Connection: close",
        ],
    )
    assert status_of(raw) == 401


@pytest.mark.parametrize("name", ["token", "access_token"])
def test_a_token_in_the_url_is_refused(srv, name):
    r = srv.request(f"/v1/version?{name}={TOKEN}", token=None)
    assert r.status == 401  # never taken as a credential
    r = srv.request(f"/v1/version?{name}={TOKEN}")  # and refused by name even with a good header
    assert r.status == 400 and r.json()["error"]["code"] == "unknown_parameter"
    assert r.json()["error"]["detail"] == {"parameter": name}


def test_repeated_failures_from_one_address_answer_429(tmp_path):
    shutil.copy2(O02, tmp_path / "a.SLDPRT")
    running = Running({"a": tmp_path}, workers=1, max_auth_failures=3)
    try:
        for _ in range(4):
            assert running.request("/v1/version", token=OTHER_TOKEN).status == 401
        r = running.request("/v1/version")  # the right token, from an address that kept guessing
        assert r.status == 429 and r.json()["error"]["code"] == "too_many_failures"
        assert r.headers["retry-after"] == "60"
    finally:
        running.close()


def test_the_token_file_is_created_for_the_user_alone(tmp_path):
    path = tmp_path / "tokens"
    got_path, tokens, created = ensure_token_file(path)
    assert created and got_path == str(path) and list(tokens) == ["default"]
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", tokens["default"])
    assert ensure_token_file(path) == (str(path), tokens, False)  # never replaced
    if WINDOWS:
        # protected: the user alone (Windows writes the built-in Administrator as LA)
        entry = re.fullmatch(r"D:P\(A;;FA;;;([^)]+)\)", token_mod.access_list(str(path)))
        assert entry and token_mod.canonical_sid(entry.group(1)) == token_mod.current_user_sid()
    else:  # pragma: no cover - POSIX
        assert os.stat(path).st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    ("content", "rule"),
    [
        (b"", "empty"),
        (b"# only a comment\n", "empty"),
        (b"default " + b"A" * 43 + b"\n", "malformed"),
        (b"Default:" + b"A" * 43 + b"\n", "malformed"),
        (b"a:short\n", "malformed"),
        (b"a:" + b"A" * 43 + b"\na:" + b"B" * 43 + b"\n", "malformed"),
        (b"a:" + b"\xff" * 43 + b"\n", "malformed"),
        (b"#" * (70 << 10), "too_large"),
    ],
    ids=["empty", "comment", "no_colon", "upper_name", "short", "twice", "not_utf8", "too_large"],
)
def test_a_bad_token_file_refuses_the_start(tmp_path, content, rule):
    path = tmp_path / "tokens"
    token_mod._create_private(str(path), content)
    with pytest.raises(TokenFileError) as caught:
        load_tokens(path)
    assert caught.value.detail == {"rule": rule}
    with pytest.raises(TokenFileError) as caught:
        load_tokens(tmp_path / "missing")
    assert caught.value.detail == {"rule": "missing"}


@pytest.mark.skipif(not WINDOWS, reason="access lists and their SDDL aliases are Windows")
def test_a_service_account_recognises_its_own_token_file(tmp_path, monkeypatch):
    """Windows writes LOCAL SERVICE as ``LS`` and NETWORK SERVICE as ``NS`` in an access
    list, so a service running as one of them must compare accounts, not text: its own
    entry is accepted, and any other account's still refuses the start."""
    path = tmp_path / "tokens"
    ensure_token_file(path)
    shared = tmp_path / "shared"
    ensure_token_file(shared)
    done = subprocess.run(["icacls", str(shared), "/grant", "*S-1-5-19:(R)"], capture_output=True)
    assert done.returncode == 0
    assert ";;;LS)" in token_mod.access_list(str(shared))  # the premise: an alias, not S-1-5-19
    with pytest.raises(TokenFileError):
        load_tokens(shared)  # control: for this account, LOCAL SERVICE is another account
    for alias, sid in (("LS", "S-1-5-19"), ("NS", "S-1-5-20")):
        monkeypatch.setattr(token_mod, "current_user_sid", lambda sid=sid: sid)
        own = f"O:{alias}D:P(A;;FA;;;{alias})(A;;FA;;;SY)(A;;FA;;;BA)"
        monkeypatch.setattr(token_mod, "security_descriptor", lambda p, own=own: own)
        assert load_tokens(path), alias  # the service's own entry, SYSTEM and Administrators
        for other in ("WD", "AU", "S-1-5-32-545", "XX"):  # Everyone, Authenticated Users, Users, junk
            acl = f"{own}(A;;FR;;;{other})"
            monkeypatch.setattr(token_mod, "security_descriptor", lambda p, acl=acl: acl)
            with pytest.raises(TokenFileError) as caught:
                load_tokens(path)
            assert caught.value.detail == {"rule": "shared_access"}, (alias, other)


def _set_access_list(path: Path, sddl: str) -> None:
    """Replace a file's or folder's access list with ``sddl`` (``D:P(...)``), as its owner may."""
    import ctypes
    from ctypes import wintypes

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    psd = wintypes.LPVOID()
    assert advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(psd), None)
    try:
        dacl_information = 0x4
        assert advapi.SetFileSecurityW(str(path), dacl_information, psd), ctypes.get_last_error()
    finally:
        ctypes.windll.kernel32.LocalFree(psd)


@pytest.mark.skipif(not WINDOWS, reason="owners and access lists are Windows")
def test_a_token_file_owned_by_another_account_refuses_the_start(tmp_path, monkeypatch):
    """An owner can rewrite an access list whenever it likes, and OWNER RIGHTS grants that
    owner whatever it says: a file that grants only OWNER RIGHTS and the service is safe
    only when the service, SYSTEM or Administrators own it. Checked as LOCAL SERVICE, for
    which this test's own account is another account."""
    path = tmp_path / "tokens"
    ensure_token_file(path)
    _set_access_list(path, "D:P(A;;FA;;;OW)(A;;FR;;;LS)")
    real = token_mod.security_descriptor(str(path))
    owner = re.match(r"O:(.+?)(?=D:)", real).group(1)
    # an elevated administrator's new files belong to Administrators, as on CI runners
    assert token_mod.canonical_sid(owner) in (token_mod.current_user_sid(), "S-1-5-32-544")
    assert real.endswith("D:P(A;;FA;;;OW)(A;;FR;;;LS)")
    folder = "O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FR;;;LS)"  # the recipe's folder
    # Owned by an ordinary account, whichever account owns it on disk (Administrators may)
    other = "S-1-5-21-1000-2000-3000-1001"
    real = real.replace(f"O:{owner}", f"O:{other}", 1)
    owner = other
    file_sddl = {"sddl": real}
    monkeypatch.setattr(token_mod, "current_user_sid", lambda: "S-1-5-19")
    monkeypatch.setattr(
        token_mod, "security_descriptor", lambda p: file_sddl["sddl"] if p.endswith("tokens") else folder
    )
    with pytest.raises(TokenFileError) as caught:
        load_tokens(path)
    assert caught.value.detail == {"rule": "not_owner"}
    for trusted in ("BA", "SY", "LS"):  # control: the same entries under an owner that may own it
        file_sddl["sddl"] = real.replace(f"O:{owner}", f"O:{trusted}", 1)
        assert list(load_tokens(path)) == ["default"], trusted


@pytest.mark.skipif(not WINDOWS, reason="owners and access lists are Windows")
def test_a_token_file_in_a_folder_others_control_refuses_the_start(tmp_path, monkeypatch):
    """Whoever owns the folder, or may add to it, delete from it or re-permission it, can put
    a file of their own in the token file's place while the service is stopped."""
    folder = tmp_path / "state"
    folder.mkdir()
    path = folder / "tokens"
    ensure_token_file(path)
    assert load_tokens(path)  # control: a folder only this account controls
    done = subprocess.run(["icacls", str(folder), "/grant", "*S-1-5-32-545:(CI)(AD,WD)"], capture_output=True)
    assert done.returncode == 0  # Users may add files and folders, as C:\ProgramData lets them
    with pytest.raises(TokenFileError) as caught:
        load_tokens(path)
    assert caught.value.detail == {"rule": "folder_writable"}
    real = token_mod.security_descriptor
    cases = {
        "O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FR;;;BU)(A;OICIIO;FA;;;CO)": None,  # read only
        "O:BUD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)": "not_owner",  # Users own the folder
        "O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;;0x10000;;;WD)": "folder_writable",  # delete it
        "O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;;WD;;;AU)": "folder_writable",  # rewrite its list
        "O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;;ZZ;;;AU)": "folder_writable",  # unknown rights
        "O:BAD:NO_ACCESS_CONTROL": "shared_access",
    }
    for sddl, rule in cases.items():
        monkeypatch.setattr(
            token_mod, "security_descriptor", lambda p, sddl=sddl: real(p) if p.endswith("tokens") else sddl
        )
        if rule is None:
            assert load_tokens(path), sddl
            continue
        with pytest.raises(TokenFileError) as caught:
            load_tokens(path)
        assert caught.value.detail == {"rule": rule}, sddl


def test_sddl_rights_are_read_as_masks():
    assert token_mod.sddl_mask("FA") == 0x1F01FF and token_mod.sddl_mask("0x1301bf") == 0x1301BF
    assert token_mod.sddl_mask("DCLC") == 0x6 and token_mod.sddl_mask("FRFX") == 0x1200A9
    assert token_mod.sddl_mask("QQ") is None and token_mod.sddl_mask("F") is None
    assert token_mod.sddl_mask("0xZZ") is None


@pytest.mark.skipif(WINDOWS, reason="modes and owners of folders are POSIX")
def test_a_token_file_in_a_folder_others_may_write_refuses_the_start(tmp_path):  # pragma: no cover
    folder = tmp_path / "state"
    folder.mkdir(mode=0o700)
    path = folder / "tokens"
    ensure_token_file(path)
    assert load_tokens(path)  # control
    os.chmod(folder, 0o777)
    with pytest.raises(TokenFileError) as caught:
        load_tokens(path)
    assert caught.value.detail == {"rule": "folder_writable"}
    os.chmod(folder, 0o1777)  # sticky: each file stays its owner's, as in /tmp
    assert load_tokens(path)


def test_a_token_file_in_a_missing_folder_says_so(tmp_path, capsys):
    path = tmp_path / "absent" / "serve-tokens"
    code, env = _cli(capsys, "serve", "--root", f"a={tmp_path}", "--port", "0", "--token-file", str(path))
    assert code == 3 and env["error"]["code"] == "token_file_refused"
    assert env["error"]["detail"] == {"rule": "folder_missing"} and not (tmp_path / "absent").exists()
    (tmp_path / "absent").mkdir()
    assert ensure_token_file(path)[2] is True  # control: with its folder there, it is created


def test_the_identity_key_file_is_made_beside_the_token_file_for_the_user_alone(tmp_path):
    folder = tmp_path / "state"
    folder.mkdir(mode=0o700)
    token_path, tokens, _created = ensure_token_file(folder / "tokens")
    path = default_identity_key_file(token_path)
    assert path == str(folder / "tokens.identity")
    got, key, created = ensure_identity_key(path)
    assert created and got == path and re.fullmatch(rb"[A-Za-z0-9_-]{43}", key)
    assert ensure_identity_key(path) == (path, key, False)  # never replaced
    assert key.decode() not in tokens.values()  # its own secret, not a client's token
    if WINDOWS:
        entry = re.fullmatch(r"D:P\(A;;FA;;;([^)]+)\)", token_mod.access_list(path))
        assert entry and token_mod.canonical_sid(entry.group(1)) == token_mod.current_user_sid()
    else:  # pragma: no cover - POSIX
        assert os.stat(path).st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    ("content", "rule"),
    [
        (b"", "empty"),
        (b"# only a comment\n", "empty"),
        (b"A" * 43 + b"\n" + b"B" * 43 + b"\n", "malformed"),
        (b"default:" + b"A" * 43 + b"\n", "malformed"),
        (b"short\n", "malformed"),
        (b"\xff" * 43 + b"\n", "malformed"),
        (b"#" * (5 << 10), "too_large"),
    ],
    ids=["empty", "comment", "two_keys", "token_line", "short", "not_utf8", "too_large"],
)
def test_a_bad_identity_key_file_refuses_the_start(tmp_path, content, rule):
    path = tmp_path / "tokens.identity"
    token_mod._create_private(str(path), content)
    with pytest.raises(IdentityKeyError) as caught:
        load_identity_key(path)
    assert caught.value.code == "identity_key_refused" and caught.value.detail == {"rule": rule}
    with pytest.raises(IdentityKeyError) as caught:
        load_identity_key(tmp_path / "missing")
    assert caught.value.detail == {"rule": "missing"}
    good = tmp_path / "good.identity"
    token_mod._create_private(str(good), b"# a comment\n\n" + b"K" * 43 + b"\n")
    assert load_identity_key(good) == b"K" * 43  # control: comments and blank lines are fine


def test_an_identity_key_file_others_can_read_refuses_the_start(tmp_path, capsys):
    folder = tmp_path / "state"
    folder.mkdir(mode=0o700)
    tokens = folder / "tokens"
    ensure_token_file(tokens)
    key = default_identity_key_file(tokens)
    ensure_identity_key(key)
    assert load_identity_key(key)  # control: the file as created is accepted
    if WINDOWS:
        done = subprocess.run(["icacls", key, "/grant", "*S-1-1-0:(R)"], capture_output=True)
        assert done.returncode == 0
    else:  # pragma: no cover - POSIX
        os.chmod(key, 0o644)
    with pytest.raises(IdentityKeyError) as caught:
        load_identity_key(key)
    assert caught.value.detail == {"rule": "shared_access"}
    code, env = _cli(capsys, "serve", "--root", f"a={tmp_path}", "--port", "0", "--token-file", str(tokens))
    assert code == 3 and env["error"]["code"] == "identity_key_refused"
    assert env["error"]["detail"] == {"rule": "shared_access"}


@pytest.mark.skipif(WINDOWS or not hasattr(os, "geteuid") or os.geteuid() == 0, reason="POSIX folder modes")
def test_an_identity_key_the_service_cannot_create_refuses_the_start(tmp_path, capsys):  # pragma: no cover
    """As in a folder only administrators may change (API 8.14): the token file is there, the
    key file is not, and the service may not add it. It refuses the start rather than run
    without one, and runs once an administrator has made it."""
    folder = tmp_path / "state"
    folder.mkdir(mode=0o700)
    tokens = folder / "tokens"
    ensure_token_file(tokens)
    base = ["serve", "--root", f"a={tmp_path}", "--port", "0", "--token-file", str(tokens)]
    os.chmod(folder, 0o500)
    try:
        code, env = _cli(capsys, *base)
    finally:
        os.chmod(folder, 0o700)
    assert code == 3 and env["error"]["code"] == "identity_key_refused"
    assert env["error"]["detail"] == {"rule": "unreadable"} and not (folder / "tokens.identity").exists()
    create_identity_key_file(folder / "tokens.identity")  # as the administrator would
    os.chmod(folder, 0o500)
    try:
        assert ensure_identity_key(folder / "tokens.identity")[2] is False  # control: now it is read
    finally:
        os.chmod(folder, 0o700)


def test_an_identity_key_file_in_a_missing_folder_says_so(tmp_path, capsys):
    folder = tmp_path / "state"
    folder.mkdir(mode=0o700)
    path = tmp_path / "absent" / "key"
    code, env = _cli(
        capsys,
        "serve",
        *("--root", f"a={tmp_path}", "--port", "0", "--token-file", str(folder / "tokens")),
        *("--identity-key-file", str(path)),
    )
    assert code == 3 and env["error"]["code"] == "identity_key_refused"
    assert env["error"]["detail"] == {"rule": "folder_missing"} and not (tmp_path / "absent").exists()


def test_the_serve_help_says_the_log_goes_to_standard_error(capsys):
    assert cli.main(["serve", "--help"]) == 0
    text = " ".join(capsys.readouterr().out.split())
    assert "the log still goes to standard error" in text and "its folder must exist" in text


def test_a_token_file_others_can_read_refuses_the_start(tmp_path, capsys):
    path = tmp_path / "tokens"
    ensure_token_file(path)
    assert load_tokens(path)  # control: the file as created is accepted
    if WINDOWS:
        done = subprocess.run(["icacls", str(path), "/grant", "*S-1-1-0:(R)"], capture_output=True)
        assert done.returncode == 0
    else:  # pragma: no cover - POSIX
        os.chmod(path, 0o644)
    with pytest.raises(TokenFileError) as caught:
        load_tokens(path)
    assert caught.value.detail == {"rule": "shared_access"}
    code, env = _cli(capsys, "serve", "--root", f"a={tmp_path}", "--port", "0", "--token-file", str(path))
    assert code == 3 and env["error"]["code"] == "token_file_refused"


# --------------------------------------------------------------------------- Host, Origin, Fetch Metadata
@pytest.mark.parametrize(
    "host",
    [
        None,
        "",
        "[::1",
        "evil.example:{port}",
        "127.0.0.1:{other}",
        "localhost.evil.example:{port}",
        "127.0.0.1.nip.io:{port}",
        "evil@127.0.0.1:{port}",
        "127.0.0.1:{port}/x",
        "127.0.0.2:{port}",
        "0x7f.0.0.1:{port}",
        "127.0.0.1:{port}:{port}",
    ],
)
def test_a_wrong_host_is_refused(srv, host):
    lines = ["GET /v1/health HTTP/1.1"]
    if host is not None:
        lines.append("Host: " + host.format(port=srv.port, other=srv.port + 1))
    raw = _raw(srv.port, [*lines, "Connection: close"])
    assert status_of(raw) == 403 and body_of(raw)["error"]["code"] == "forbidden_host"


@pytest.mark.parametrize("host", ["127.0.0.1:{port}", "localhost:{port}", "LOCALHOST:{port}"])
def test_the_bound_host_is_served(srv, host):
    raw = _raw(
        srv.port, ["GET /v1/health HTTP/1.1", "Host: " + host.format(port=srv.port), "Connection: close"]
    )
    assert status_of(raw) == 200


def test_two_host_headers_are_refused(srv):
    h = f"Host: 127.0.0.1:{srv.port}"
    assert status_of(_raw(srv.port, ["GET /v1/health HTTP/1.1", h, h, "Connection: close"])) == 403


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Origin": "http://127.0.0.1:{port}"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
    ],
)
def test_cross_site_browser_requests_are_refused(srv, headers):
    h = {k: v.format(port=srv.port) for k, v in headers.items()}
    r = srv.request("/v1/document?root=jobs&path=o02_boxA.SLDPRT", headers=h)
    assert r.status == 403 and r.json()["error"]["code"] == "forbidden_origin"
    assert "access-control-allow-origin" not in r.headers


@pytest.mark.parametrize("site", ["none", "same-origin"])
def test_a_same_origin_or_typed_request_is_served(srv, site):
    r = srv.request("/v1/document?root=jobs&path=o02_boxA.SLDPRT", headers={"Sec-Fetch-Site": site})
    assert r.status == 200


# --------------------------------------------------------------------------- CORS for named origins (xex)
INTRANET = "https://intranet.example"


@pytest.mark.parametrize(
    ("text", "origin"),
    [
        ("https://intranet.example", "https://intranet.example"),
        ("https://Intranet.Example:443/", "https://intranet.example"),
        ("http://intranet.example:80", "http://intranet.example"),
        ("http://127.0.0.1:3000", "http://127.0.0.1:3000"),
        ("http://[0:0:0:0:0:0:0:1]:3000", "http://[::1]:3000"),
        ("https://store.example:8443", "https://store.example:8443"),
    ],
)
def test_an_allowed_origin_is_kept_as_browsers_send_it(text, origin):
    from solidseas.serve import parse_origin

    assert parse_origin(text) == origin


@pytest.mark.parametrize(
    "text",
    [
        "*",
        "null",
        "",
        "intranet.example",
        "ftp://intranet.example",
        "file:///c:/x",
        "https://intranet.example/app",
        "https://intranet.example?x=1",
        "https://user@intranet.example",
        "https://*.example",
        "https://intranet.example:0",
        "https://intränet.example",
        "https://intranet example",
    ],
)
def test_an_origin_that_is_not_one_is_refused(text):
    from solidseas.errors import InvalidArgumentError
    from solidseas.serve import parse_origin

    with pytest.raises(InvalidArgumentError) as caught:
        parse_origin(text)
    assert caught.value.detail == {"parameter": "allow_origin"}


@pytest.fixture(scope="module")
def cors(tree):
    running = Running({"jobs": tree / "jobs"}, workers=1, allow_origins=(INTRANET + ":443/",))
    yield running
    running.close()


def test_an_allowed_origin_may_call_the_service_and_read_its_answers(cors):
    """A page of a named origin calls from its own site (Origin, Sec-Fetch-Site
    cross-site): the answer names that origin, exposes the headers a client reads, and
    says it varies by Origin; its errors do too, so the page can tell them apart. The
    token is still needed."""
    page = {"Origin": INTRANET, "Sec-Fetch-Site": "cross-site"}
    ok = cors.request("/v1/document?root=jobs&path=o02_boxA.SLDPRT", headers=page)
    assert ok.status == 200 and ok.headers["access-control-allow-origin"] == INTRANET
    assert ok.headers["access-control-expose-headers"] == "ETag, Retry-After, WWW-Authenticate, X-Request-Id"
    assert ok.headers["vary"] == "Origin" and ok.headers["etag"]
    assert "access-control-allow-credentials" not in ok.headers  # a token in a header, never a cookie
    for name, value in SECURITY.items():
        assert ok.headers[name] == value, name
    refused = cors.request("/v1/document?root=jobs&path=o02_boxA.SLDPRT", token=None, headers=page)
    assert refused.status == 401 and refused.headers["access-control-allow-origin"] == INTRANET
    same_site = cors.request("/v1/version", headers={"Origin": INTRANET, "Sec-Fetch-Site": "same-site"})
    assert same_site.status == 200 and same_site.headers["access-control-allow-origin"] == INTRANET


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Origin": "https://intranet.example.evil.example"},
        {"Origin": "http://intranet.example"},  # another scheme is another origin
        {"Origin": "https://intranet.example:8443"},
        {"Origin": "null"},
        {"Origin": "HTTPS://INTRANET.EXAMPLE"},  # browsers send it in lower case
        {"Sec-Fetch-Site": "cross-site"},  # a page elsewhere that sent no Origin
        {"Origin": "https://evil.example", "Sec-Fetch-Site": "same-origin"},
    ],
)
def test_every_other_origin_is_still_refused(cors, headers):
    r = cors.request("/v1/document?root=jobs&path=o02_boxA.SLDPRT", headers=headers)
    assert r.status == 403 and r.json()["error"]["code"] == "forbidden_origin"
    assert "access-control-allow-origin" not in r.headers and r.headers["vary"] == "Origin"


def test_two_origin_headers_are_refused(cors):
    raw = _raw(
        cors.port,
        [
            "GET /v1/version HTTP/1.1",
            f"Host: 127.0.0.1:{cors.port}",
            f"Authorization: Bearer {TOKEN}",
            f"Origin: {INTRANET}",
            f"Origin: {INTRANET}",
            "Connection: close",
        ],
    )
    assert status_of(raw) == 403 and body_of(raw)["error"]["code"] == "forbidden_origin"


def _preflight(port: int, *extra: str, origin: str = INTRANET, method: str = "GET", host: str = "") -> bytes:
    lines = [
        "OPTIONS /v1/document?root=jobs&path=o02_boxA.SLDPRT HTTP/1.1",
        f"Host: {host or f'127.0.0.1:{port}'}",
        f"Origin: {origin}",
        f"Access-Control-Request-Method: {method}",
        *extra,
        "Connection: close",
    ]
    return _raw(port, lines)


def test_a_preflight_from_an_allowed_origin_is_answered(cors):
    raw = _preflight(cors.port, "Access-Control-Request-Headers: authorization,if-none-match")
    head = _headers_of(raw)
    assert status_of(raw) == 204 and raw.endswith(b"\r\n\r\n")  # no body
    assert "content-length" not in head and "content-type" not in head
    assert head["access-control-allow-origin"] == INTRANET
    assert head["access-control-allow-methods"] == "GET, HEAD"
    assert head["access-control-allow-headers"] == "Authorization, If-None-Match"
    assert head["access-control-max-age"] == "600"
    for name, value in SECURITY.items():
        assert head[name] == value, name
    assert status_of(_preflight(cors.port)) == 204  # no headers asked for


@pytest.mark.parametrize(
    ("extra", "kwargs", "status"),
    [
        ((), {"method": "POST"}, 405),
        ((), {"method": "DELETE"}, 405),
        (("Access-Control-Request-Headers: authorization, x-custom",), {}, 405),
        (("Access-Control-Request-Headers: cookie",), {}, 405),
        ((), {"origin": "https://evil.example"}, 405),
        ((), {"origin": "null"}, 405),
        ((), {"host": "evil.example"}, 403),
        (("Content-Length: 5",), {}, 400),
    ],
)
def test_any_other_preflight_is_refused(cors, extra, kwargs, status):
    raw = _preflight(cors.port, *extra, **kwargs)
    assert status_of(raw) == status, raw[:300]
    assert "access-control-allow-origin" not in _headers_of(raw)


def test_without_allowed_origins_a_preflight_is_refused(srv):
    raw = _preflight(srv.port)
    assert status_of(raw) == 405 and "access-control-allow-origin" not in _headers_of(raw)
    assert "vary" not in _headers_of(raw)  # nothing varies by Origin without CORS


# --------------------------------------------------------------------------- methods and bodies
@pytest.mark.parametrize(
    "method", ["POST", "PUT", "DELETE", "PATCH", "TRACE", "CONNECT", "OPTIONS", "PROPFIND", "FOO"]
)
def test_only_get_and_head_are_accepted(srv, method):
    raw = _raw(
        srv.port, [f"{method} /v1/health HTTP/1.1", f"Host: 127.0.0.1:{srv.port}", "Connection: close"]
    )
    assert status_of(raw) == 405 and _headers_of(raw)["allow"] == "GET, HEAD"
    assert body_of(raw)["error"]["code"] == "method_not_allowed"


@pytest.mark.parametrize("method", ["PROPFIND", "BREW", "get", "POST"])
def test_the_host_check_comes_before_the_method_check(srv, method):
    """Even for a method the service has never heard of, a wrong Host is refused first (8.4)."""
    raw = _raw(srv.port, [f"{method} /v1/version HTTP/1.1", "Host: evil.example", "Connection: close"])
    assert status_of(raw) == 403 and body_of(raw)["error"]["code"] == "forbidden_host"
    raw = _raw(srv.port, [f"{method} /v1/version HTTP/1.1", f"Host: 127.0.0.1:{srv.port}"])
    assert status_of(raw) == 405 and body_of(raw)["error"]["code"] == "method_not_allowed"  # control


@pytest.mark.parametrize(
    "line",
    ["GET /v1/version", "GET /v1/version HTTP/1.1 extra", "GET", "BREW /v1/version"],
    ids=["http_0_9", "four_words", "one_word", "http_0_9_other_method"],
)
def test_every_answer_has_a_status_line_and_the_security_headers(srv, line):
    """A request line without a version is HTTP/0.9, whose answer would be a bare body with
    no status, no Content-Type and none of the security headers: refused as HTTP/1.1."""
    raw = _raw(srv.port, [line, f"Host: 127.0.0.1:{srv.port}", f"Authorization: Bearer {TOKEN}"])
    assert raw.startswith(b"HTTP/1.1 400 "), raw[:80]
    headers = _headers_of(raw)
    assert all(headers.get(k) == v for k, v in SECURITY.items()) and headers["x-request-id"]
    assert headers["content-type"] == "application/json; charset=utf-8" and headers["connection"] == "close"
    assert body_of(raw)["error"]["code"] == "invalid_argument"


def test_head_answers_the_headers_of_get(srv):
    get = srv.request("/v1/document?root=jobs&path=o02_boxA.SLDPRT")
    head = srv.request("/v1/document?root=jobs&path=o02_boxA.SLDPRT", method="HEAD")
    assert head.status == 200 and head.body == b"" and head.headers["etag"] == get.headers["etag"]
    assert head.headers["content-length"] == str(len(get.body))


@pytest.mark.parametrize(
    "extra", [["Content-Length: 5"], ["Transfer-Encoding: chunked"]], ids=["length", "chunked"]
)
def test_a_request_body_is_refused_and_the_connection_closed(srv, extra):
    raw = _raw(
        srv.port,
        ["GET /v1/version HTTP/1.1", f"Host: 127.0.0.1:{srv.port}", f"Authorization: Bearer {TOKEN}", *extra],
        body=b"hello",
    )
    assert status_of(raw) == 400 and body_of(raw)["error"]["detail"] == {"rule": "body"}
    assert _headers_of(raw)["connection"] == "close"


# --------------------------------------------------------------------------- request limits
def test_a_long_url_answers_414(srv):
    raw = _raw(srv.port, [f"GET /v1/health?{'a' * 5000} HTTP/1.1", f"Host: 127.0.0.1:{srv.port}"])
    assert status_of(raw) == 414 and body_of(raw)["error"]["code"] == "uri_too_long"
    raw = _raw(srv.port, [f"GET /v1/health?{'a' * 70_000} HTTP/1.1", f"Host: 127.0.0.1:{srv.port}"])
    assert status_of(raw) == 414  # past Python's own line limit too


def test_too_many_or_too_large_headers_answer_431(srv):
    host = f"Host: 127.0.0.1:{srv.port}"
    raw = _raw(srv.port, ["GET /v1/health HTTP/1.1", host, *[f"X-Pad-{i}: x" for i in range(101)]])
    assert status_of(raw) == 431 and body_of(raw)["error"]["code"] == "headers_too_large"
    raw = _raw(srv.port, ["GET /v1/health HTTP/1.1", host, "X-Pad: " + "x" * (17 << 10)])
    assert status_of(raw) == 431
    assert status_of(_raw(srv.port, ["GET /v1/health HTTP/1.1", host, "X-Pad: " + "x" * 1000])) == 200


def test_a_slow_sender_is_cut_off_while_others_are_served(tmp_path):
    shutil.copy2(O02, tmp_path / "a.SLDPRT")
    running = Running({"a": tmp_path}, workers=1, read_timeout=1.5)
    try:
        closed_after: list[float] = []

        def trickle():
            data = (
                f"GET /v1/health HTTP/1.1\r\nHost: 127.0.0.1:{running.port}\r\nX-Slow: ".encode() + b"x" * 200
            )
            start = time.monotonic()
            with socket.create_connection(("127.0.0.1", running.port), timeout=30) as s:
                try:
                    for byte in data:
                        s.sendall(bytes([byte]))
                        time.sleep(0.1)
                    s.recv(1)
                except OSError:
                    pass
            closed_after.append(time.monotonic() - start)

        t = threading.Thread(target=trickle)
        t.start()
        time.sleep(0.3)
        assert running.request("/v1/health", token=None).status == 200  # another client, meanwhile
        t.join(30)
        assert closed_after and closed_after[0] < 6, closed_after  # 200 bytes would take 20 s
    finally:
        running.close()


def test_an_oversized_head_is_not_read_past_its_limit(tmp_path, monkeypatch):
    """The stdlib would buffer 100 header lines of 64 KiB (6.4 MB) before the 16 KiB limit was
    checked, for every connection and before any token check: reading stops at the limit."""
    from solidseas.serve import server as server_mod

    readers: list = []

    class Counting(server_mod._HeadReader):
        def __init__(self, sock) -> None:
            super().__init__(sock)
            readers.append(self)

    monkeypatch.setattr(server_mod, "_HeadReader", Counting)
    running = Running({"a": tmp_path}, workers=1)
    try:
        head = f"GET /v1/health HTTP/1.1\r\nHost: 127.0.0.1:{running.port}\r\n".encode()
        pad = b"".join(b"X-Pad-%d: %s\r\n" % (i, b"x" * 64_000) for i in range(98))
        replies: list[bytes] = []

        def send() -> None:
            with socket.create_connection(("127.0.0.1", running.port), timeout=20) as s:
                try:
                    s.sendall(head + pad + b"\r\n")
                except OSError:
                    pass  # the service stopped reading and closed the connection
                try:
                    replies.append(s.recv(65536))
                except OSError:
                    pass

        t = threading.Thread(target=send)
        t.start()
        t.join(60)
        assert len(head + pad) > 6_000_000 and readers
        assert max(r.received for r in readers) <= len(head) + server_mod.HEAD_BUDGET + 8192
        if replies and replies[0]:  # it may be lost to the reset of a connection closed unread
            assert status_of(replies[0]) == 431
        # control: headers within the limit are read and answered
        host = f"Host: 127.0.0.1:{running.port}"
        ok = _raw(running.port, ["GET /v1/health HTTP/1.1", host, "X-Pad: " + "x" * 8000])
        assert status_of(ok) == 200
    finally:
        running.close()


def test_a_connection_whose_head_never_arrives_is_logged(tmp_path):
    """A connection closed because no request, or no complete head, arrived in time leaves a
    log line (peer and rule only), so a flood of idle connections or slow senders shows."""
    running = Running({"a": tmp_path}, workers=1, read_timeout=1.0, idle_timeout=0.5)
    try:
        with socket.create_connection(("127.0.0.1", running.port), timeout=10) as idle:
            with socket.create_connection(("127.0.0.1", running.port), timeout=10) as slow:
                slow.sendall(b"GET /v1/health HTTP/1.1\r\nX-Never-Ends: ")
                assert slow.recv(100) == b"" and idle.recv(100) == b""  # both closed by the service
        assert wait_for(lambda: sum("code=timeout" in line for line in running.log.lines) >= 2, 10)
        lines = [line for line in running.log.lines if "code=timeout" in line]
        assert sorted(re.search(r"rule=(\w+)", line).group(1) for line in lines) == [
            "head_deadline",
            "idle_connection",
        ]
        assert all("peer=127.0.0.1" in line and "GET" not in line for line in lines)
    finally:
        running.close()


def _read_response(s: socket.socket) -> bytes:
    data = b""
    while b"\r\n\r\n" not in data:
        data += s.recv(65536)
    head, _, body = data.partition(b"\r\n\r\n")
    length = int(_headers_of(data)["content-length"])
    while len(body) < length:
        body += s.recv(65536)
    return head + b"\r\n\r\n" + body


def test_an_idle_kept_alive_connection_closes_after_the_idle_window(tmp_path):
    running = Running({"a": tmp_path}, workers=1, read_timeout=10.0, idle_timeout=0.5)
    try:
        with socket.create_connection(("127.0.0.1", running.port), timeout=20) as s:
            s.sendall(f"GET /v1/health HTTP/1.1\r\nHost: 127.0.0.1:{running.port}\r\n\r\n".encode())
            assert status_of(_read_response(s)) == 200  # served, and kept alive
            start = time.monotonic()
            assert s.recv(100) == b""
            assert time.monotonic() - start < 3  # the idle window, not the 10 s head deadline
        assert not [line for line in running.log.lines if "code=timeout" in line]  # not news
    finally:
        running.close()


def test_refused_connections_do_not_hold_up_the_next_one(tmp_path):
    """Past the connection cap each connection is answered 503 and closed by one thread: an
    idle refused connection must not make the ones behind it wait a second each."""
    running = Running({"a": tmp_path}, workers=1, max_connections=2, read_timeout=10.0, idle_timeout=10.0)
    held = [socket.create_connection(("127.0.0.1", running.port), timeout=10) for _ in range(2)]
    refused: list[socket.socket] = []
    try:
        time.sleep(0.3)
        refused = [socket.create_connection(("127.0.0.1", running.port), timeout=10) for _ in range(10)]
        start = time.monotonic()
        raw = _raw(running.port, ["GET /v1/health HTTP/1.1", f"Host: 127.0.0.1:{running.port}"])
        assert status_of(raw) == 503 and body_of(raw)["error"]["code"] == "busy"
        assert time.monotonic() - start < 3  # ten idle refusals ahead of it, at most 0.1 s each
    finally:
        for s in held + refused:
            s.close()
        running.close()


def test_requests_past_the_in_flight_cap_answer_busy(tmp_path):
    shutil.copy2(O02, tmp_path / "slow.SLDPRT")
    shutil.copy2(O02, tmp_path / "quick.SLDPRT")
    pool = WorkerPool(2, jobs={"document_summary": "worker_jobs:document_summary"}, reader_message=False)
    running = Running({"a": tmp_path}, pool=pool, in_flight=1, deadlines={"document": 4.0})
    try:
        results: list[Response] = []
        t = threading.Thread(
            target=lambda: results.append(running.get("document", root="a", path="slow.SLDPRT"))
        )
        t.start()
        assert wait_for(lambda: len(running.server.dispatched) >= 1, 10)
        r = running.get("document", root="a", path="quick.SLDPRT")
        assert r.status == 503 and r.json()["error"]["code"] == "busy" and r.headers["retry-after"] == "2"
        t.join(30)
        assert results[0].status == 504 and results[0].json()["error"]["code"] == "timeout"
        assert running.get("document", root="a", path="quick.SLDPRT").status == 200  # the cap freed up
    finally:
        running.close()


def test_connections_past_the_cap_answer_503(tmp_path):
    shutil.copy2(O02, tmp_path / "a.SLDPRT")
    running = Running({"a": tmp_path}, workers=1, max_connections=2, read_timeout=5)
    idle = []
    try:
        for _ in range(2):
            idle.append(socket.create_connection(("127.0.0.1", running.port), timeout=10))
        time.sleep(0.3)
        raw = _raw(running.port, ["GET /v1/health HTTP/1.1", f"Host: 127.0.0.1:{running.port}"])
        assert status_of(raw) == 503 and body_of(raw)["error"]["code"] == "busy"
        for s in idle:
            s.close()
        assert wait_for(lambda: running.request("/v1/health", token=None).status == 200, 10)
    finally:
        for s in idle:
            s.close()
        running.close()


# --------------------------------------------------------------------------- the query allowlist
BAD_QUERIES = [
    ("document", "root=jobs&path=o02_boxA.SLDPRT&bogus=1", "unknown_parameter", "bogus"),
    ("document", "root=jobs&root=jobs&path=o02_boxA.SLDPRT", "duplicate_parameter", "root"),
    ("document", "root=jobs&path=", "invalid_argument", "path"),
    ("document", "root=jobs", "invalid_argument", "path"),
    ("document", "root=JOBS&path=o02_boxA.SLDPRT", "invalid_argument", "root"),
    ("components", "root=jobs&path=o08_asm_2x_boxA.SLDASM&max_depth=-1", "invalid_argument", "max_depth"),
    ("components", "root=jobs&path=o08_asm_2x_boxA.SLDASM&max_depth=01", "invalid_argument", "max_depth"),
    ("components", "root=jobs&path=o08_asm_2x_boxA.SLDASM&max_depth=1e3", "invalid_argument", "max_depth"),
    ("components", "root=jobs&path=o08_asm_2x_boxA.SLDASM&max_depth=+5", "invalid_argument", "max_depth"),
    ("components", "root=jobs&path=o08_asm_2x_boxA.SLDASM&max_depth=33", "invalid_argument", "max_depth"),
    ("components", "root=jobs&path=o08_asm_2x_boxA.SLDASM&max_nodes=0", "invalid_argument", "max_nodes"),
    ("components", "root=jobs&path=o08_asm_2x_boxA.SLDASM&flat=yes", "invalid_argument", "flat"),
    ("preview", "root=jobs&path=o02_boxA.SLDPRT&prefer=PNG", "invalid_argument", "prefer"),
    ("properties", "root=jobs&path=o02_boxA.SLDPRT&view=Effective", "invalid_argument", "view"),
    (
        "properties",
        f"root=jobs&path=o02_boxA.SLDPRT&configuration={'c' * 257}",
        "invalid_argument",
        "configuration",
    ),
    ("properties", "root=jobs&path=o02_boxA.SLDPRT&configuration=a%01b", "invalid_argument", "configuration"),
    ("list", "root=jobs&include=thumbnails", "invalid_argument", "include"),
    ("list", "root=jobs&include=properties,properties", "invalid_argument", "include"),
    ("list", "root=jobs&limit=501", "invalid_argument", "limit"),
    ("list", "root=jobs&cursor=not-a-cursor", "invalid_argument", "cursor"),
    ("document", "root=jobs&path=%C0%AE", "invalid_argument", "query"),
    ("document", "root=jobs&path=a%zz.SLDPRT", "invalid_argument", "query"),
    ("document", "root=jobs&path=a%", "invalid_argument", "query"),
    ("document", "root=jobs&&path=o02_boxA.SLDPRT", "invalid_argument", "query"),
    ("document", "root=jobs&path", "invalid_argument", "query"),
    ("document", "&".join(f"p{i}=1" for i in range(13)), "invalid_argument", "query"),
]


@pytest.mark.parametrize(("route", "query", "code", "parameter"), BAD_QUERIES)
def test_the_query_allowlist(srv, route, query, code, parameter):
    r = srv.request(f"/v1/{route}?{query}")
    assert r.status == 400 and r.json()["error"]["code"] == code
    assert r.json()["error"]["detail"] == {"parameter": parameter}


def test_the_allowlist_has_a_control(srv):
    r = srv.request("/v1/components?root=jobs&path=o08_asm_2x_boxA.SLDASM&max_depth=5&max_nodes=10&flat=true")
    assert r.status == 200 and r.json()["data"]["limits"] == {"max_nodes": 10, "max_depth": 5}


# --------------------------------------------------------------------------- confinement
REFUSED_PATHS = [
    ("/etc/o02_boxA.SLDPRT", "absolute", 0),
    ("//host/share/o02_boxA.SLDPRT", "absolute", 0),
    ("../o02_boxA.SLDPRT", "dot_component", 0),
    ("sub/../o02_boxA.SLDPRT", "dot_component", 1),
    ("./o02_boxA.SLDPRT", "dot_component", 0),
    ("... /o02_boxA.SLDPRT", "dot_component", 0),
    (". ./o02_boxA.SLDPRT", "dot_component", 0),
    ("sub//o04_boxA_props.SLDPRT", "empty_component", 1),
    ("sub/", "empty_component", 1),
    ("sub\\o04_boxA_props.SLDPRT", "backslash", 0),
    ("..\\o02_boxA.SLDPRT", "backslash", 0),
    ("\\\\host\\share\\o02_boxA.SLDPRT", "backslash", 0),
    ("C:/Windows/o02_boxA.SLDPRT", "colon", 0),
    ("C:o02_boxA.SLDPRT", "colon", 0),
    ("o02_boxA.SLDPRT:hidden", "colon", 0),
    ("o02_boxA.SLDPRT::$DATA", "colon", 0),
    ("sub/o04_boxA_props.SLDPRT:Zone.Identifier", "colon", 1),
    ("CON.SLDPRT", "device_name", 0),
    ("nul.sldprt", "device_name", 0),
    ("COM1.SLDPRT", "device_name", 0),
    ("lpt9.SLDPRT", "device_name", 0),
    ("COM\u00b9.SLDPRT", "device_name", 0),
    ("sub/AUX/o04_boxA_props.SLDPRT", "device_name", 1),
    ("CON .tar.SLDPRT", "device_name", 0),
    ("o02_boxA.SLDPRT.", "trailing_dot_or_space", 0),
    ("o02_boxA.SLDPRT ", "trailing_dot_or_space", 0),
    ("sub./o04_boxA_props.SLDPRT", "trailing_dot_or_space", 0),
    ("a\x00b.SLDPRT", "control_character", 0),
    ("a\x1fb.SLDPRT", "control_character", 0),
    ("a\x7fb.SLDPRT", "control_character", 0),
    ("a<b.SLDPRT", "reserved_character", 0),
    ("a|b.SLDPRT", "reserved_character", 0),
    ('a"b.SLDPRT', "reserved_character", 0),
    ("a?b.SLDPRT", "reserved_character", 0),
    ("o0*.SLDPRT", "reserved_character", 0),
    ("x" * 1100 + ".SLDPRT", "too_long", None),
    ("/".join(["d"] * 70) + "/x.SLDPRT", "too_deep", None),
    ("d" * 256 + "/x.SLDPRT", "component_too_long", 0),
    ("notes.txt", "not_a_document", 0),
    ("o02_boxA.SLDPRT.bak", "not_a_document", 0),
    ("sub", "not_a_document", 0),
]


def test_the_refused_path_table_is_large_enough():
    assert len(REFUSED_PATHS) >= 30
    assert len({rule for _, rule, _ in REFUSED_PATHS}) >= 12


@pytest.mark.parametrize(("path", "rule", "index"), REFUSED_PATHS, ids=lambda v: repr(v)[:40])
def test_a_refused_path_never_reaches_the_disk(srv, path, rule, index):
    seen = len(srv.server.dispatched)
    r = srv.request(f"/v1/document?root=jobs&path={quote(path, safe='')}")
    err = r.json()["error"]
    assert r.status == 403 and err["code"] == "path_refused" and err["detail"]["rule"] == rule, err
    assert err["detail"].get("component_index") == index
    assert len(srv.server.dispatched) == seen  # no worker was asked to open anything


@pytest.mark.parametrize(
    ("raw_path", "status"),
    [
        ("..%2F..%2Fo02_boxA.SLDPRT", 403),
        ("%2E%2E%2Fo02_boxA.SLDPRT", 403),
        ("sub%5Co04_boxA_props.SLDPRT", 403),
        ("..%252F..%252Fo02_boxA.SLDPRT", 404),  # decoded once: a name with % in it, not a traversal
        ("o02_boxA.SLDPRT%00.txt", 403),
    ],
)
def test_encoded_traversal_is_decoded_once_and_refused(srv, raw_path, status):
    r = srv.request(f"/v1/document?root=jobs&path={raw_path}")
    assert r.status == status, r.json()


def test_a_link_inside_the_root_leads_nowhere(srv, tree):
    assert (tree / "jobs" / "escape" / "secret.SLDPRT").is_file()  # control: the link leads to a document
    r = srv.get("document", root="jobs", path="escape/secret.SLDPRT")
    assert r.status == 403 and r.json()["error"]["code"] == "link_refused"
    assert r.json()["error"]["detail"] == {"rule": "link_in_path", "component_index": 0}
    r = srv.get("list", root="jobs", path="escape")
    assert r.status == 403 and r.json()["error"]["code"] == "link_refused"
    entries = {e["path"]: e for e in srv.get("list", root="jobs").json()["data"]["entries"]}
    assert entries["escape"]["status"] == "link"
    recursive = srv.get("list", root="jobs", recursive="1").json()["data"]["entries"]
    assert not any(e["path"].startswith("escape/") for e in recursive)
    assert any(e["path"] == "sub/o04_boxA_props.SLDPRT" for e in recursive)  # control: it does recurse


def _make_link(link: Path, target: Path) -> None:
    if WINDOWS:
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:  # pragma: no cover - POSIX
        os.symlink(target, link, target_is_directory=True)


def _record_filesystem_calls(monkeypatch, seen: list) -> None:
    """Record every ``lstat``, ``stat`` and folder listing made in this process."""
    for name in ("lstat", "stat"):
        real = getattr(os, name)

        def call(p, *a, _real=real, _name=name, **k):
            seen.append((_name, os.fspath(p)))
            return _real(p, *a, **k)

        monkeypatch.setattr(os, name, call)
    real_scandir = os.scandir

    def scandir(p):
        seen.append(("scandir", os.fspath(p)))
        return real_scandir(p)

    monkeypatch.setattr(walk_mod, "_scandir", scandir)


def test_an_indexed_folder_swapped_for_a_link_is_never_entered(tmp_path, monkeypatch):
    """The index is built at start; a folder in it that is later replaced by a link must be
    refused before anything is asked of a path through the link. A symbolic link to a share
    would otherwise make the operating system connect there just to answer the ``lstat``."""
    root, outside = tmp_path / "root", tmp_path / "outside"
    (root / "sub").mkdir(parents=True)
    outside.mkdir()
    shutil.copy2(O02, root / "sub" / "o02_boxA.SLDPRT")
    shutil.copy2(O02, outside / "o02_boxA.SLDPRT")
    running = Running({"r": root}, workers=1)
    try:
        assert running.get("document", root="r", path="sub/o02_boxA.SLDPRT").status == 200  # control
        (root / "sub").rename(root / "sub_before")
        link = str(root / "sub")
        _make_link(root / "sub", outside)
        assert (root / "sub" / "o02_boxA.SLDPRT").is_file()  # control: the link leads to a document
        seen: list[tuple[str, str]] = []
        _record_filesystem_calls(monkeypatch, seen)
        for route, params in (
            ("document", {"path": "sub/o02_boxA.SLDPRT"}),
            ("document", {"path": "sub/added_later.SLDPRT"}),  # not in the index: a live lookup
            ("list", {"path": "sub"}),
        ):
            r = running.get(route, root="r", **params)
            assert r.status == 403 and r.json()["error"]["code"] == "link_refused", (route, params)
        monkeypatch.undo()
        through = [
            (kind, p)
            for kind, p in seen
            if p.startswith(link + os.sep) or (kind != "lstat" and p.rstrip(r"\/") == link)
        ]
        assert any(p == link for _kind, p in seen) and through == []
        assert len(running.server.dispatched) == 1  # only the control was handed to a worker
    finally:
        running.close()


@pytest.mark.skipif(not WINDOWS, reason="the POSIX open walks with O_NOFOLLOW, which never follows a link")
def test_the_workers_open_refuses_a_link_before_opening_through_it(tmp_path, monkeypatch):
    from solidseas.formats.solidworks import _io

    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    shutil.copy2(O02, outside / "o02_boxA.SLDPRT")
    _make_link(root / "sub", outside)
    opened: list[str] = []
    real = _io._create
    monkeypatch.setattr(_io, "_create", lambda p, *a: (opened.append(p), real(p, *a))[1])
    target = root / "sub" / "o02_boxA.SLDPRT"
    with open(target, "rb"):
        pass  # control: the path opens when links are followed
    with pytest.raises(LinkRefusedError) as caught:
        _io.open_readonly(str(target), within=str(root))
    assert caught.value.detail == {"rule": "link_in_path"}
    with pytest.raises(LinkRefusedError):
        _io.check_folder_within(str(root / "sub"), str(root))
    assert [p for p in opened if p.startswith(str(root / "sub"))] == []
    shutil.copy2(O02, root / "o02_boxA.SLDPRT")
    with _io.open_readonly(str(root / "o02_boxA.SLDPRT"), within=str(root)):  # control: no link
        pass
    assert opened


def test_a_hard_link_is_refused(srv, tree):
    if not (tree / "jobs" / "twin_b.SLDPRT").exists():
        pytest.skip("hard links are not supported here")
    for name in ("twin_a.SLDPRT", "twin_b.SLDPRT"):
        r = srv.get("document", root="jobs", path=name)
        assert r.status == 403 and r.json()["error"]["detail"] == {"rule": "hard_link"}
    assert srv.get("document", root="jobs", path="o02_boxA.SLDPRT").status == 200  # control


@pytest.mark.skipif(not WINDOWS, reason="8.3 short names are a Windows feature")
def test_a_short_name_is_not_found(srv, tree):
    import ctypes

    long_path = str(tree / "jobs" / "o06_boxA_props_mat_cfg.SLDPRT")
    buf = ctypes.create_unicode_buffer(512)
    ctypes.windll.kernel32.GetShortPathNameW(long_path, buf, 512)
    short = os.path.basename(buf.value)
    if not short or short == os.path.basename(long_path):
        pytest.skip("this volume makes no 8.3 names")
    assert (tree / "jobs" / short).is_file()  # control: the short name opens the file on disk
    r = srv.get("document", root="jobs", path=short)
    # A short name keeps three letters of the extension (.SLD), so the service refuses it
    # as not a document before it looks for the file; either way the file is not reached.
    assert (r.status, r.json()["error"]["code"]) in ((404, "not_found"), (403, "path_refused"))


def test_names_compare_as_ntfs_does(srv):
    exact = srv.get("document", root="jobs", path="o02_boxA.SLDPRT")
    other_case = srv.get("document", root="jobs", path="O02_BOXA.sldprt")
    assert exact.status == other_case.status == 200
    assert other_case.json()["source"] == {"root": "jobs", "path": "o02_boxA.SLDPRT"}  # the on-disk spelling


def test_a_root_that_does_not_exist_is_not_found(srv):
    r = srv.get("document", root="nope", path="o02_boxA.SLDPRT")
    assert r.status == 404 and r.json()["error"]["code"] == "root_not_found"


def test_workers_only_ever_open_paths_inside_the_root(srv, tree):
    srv.get("references", root="jobs", path="o08_asm_2x_boxA.SLDASM", resolve="1")
    opened = list(srv.server.dispatched)
    root = os.path.normcase(str(tree / "jobs")) + os.sep
    assert len(opened) >= 5, "the record of opened paths is empty"
    assert all(os.path.normcase(p).startswith(root) for p in opened), opened


# --------------------------------------------------------------------------- hostile files
def _hostile(tmp: Path) -> dict[str, bytes]:
    files = {"eocd_flood.SLDPRT": _eocd_flood(20_000)}
    for i, label in enumerate(LEGACY_LIES):
        files[f"legacy_lie_{i}.SLDPRT"] = _legacy_crafted(**LEGACY_LIES[label])
    streams = fixture_streams(O02)
    files["runaway_header2.SLDPRT"] = build_modern({**streams, "Header2": _runaway_strings(20_000)})
    files["doctype.SLDPRT"] = rebuild(
        O04, {"docProps/custom.xml": b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;&a;</x>'}
    )
    partition = fixture_streams(fixture_path("o01_empty.SLDPRT"))["Contents/Config-0-Partition"]
    files["inflate_budget.SLDPRT"] = build_modern(
        {
            "Contents/Config-0-Partition": partition,
            "Config-0-FeatureBodies/LocalBodies": _local_bodies("Imported1", [bytes(200_000)] * 5),
        }
    )
    files["nan_and_huge.SLDPRT"] = rebuild(
        O04,
        {
            "docProps/custom.xml": _custom_xml(
                ("Big", "i8", str(2**60)), ("NotANumber", "r8", "NaN"), ("Huge", "r8", "1e999")
            )
        },
    )
    from builders import TreeXml, assembly_with_tree

    t = TreeXml()
    t.file("2", "C:\\J\\a.SLDASM", "ASSEMBLY")
    t.top("m1")
    t.model("m2", "2")
    t.ref("m1", "a", 1, "m2")
    t.ref("m2", "back", 1, "m1")
    files["cycle.SLDASM"] = assembly_with_tree(t)
    t = TreeXml()
    t.top("m0")
    for level in range(1, 31):
        t.file(str(level + 1), f"C:\\J\\l{level}.SLDASM", "ASSEMBLY")
        t.model(f"m{level}", str(level + 1))
        for k in (1, 2):
            t.ref(f"m{level - 1}", f"l{level}", k, f"m{level}")
    files["doubling_dag.SLDASM"] = assembly_with_tree(t)
    files["step_inside.SLDPRT"] = b"ISO-10303-21;\nHEADER;\n"
    files["empty.SLDPRT"] = b""
    files["noise.SLDASM"] = bytes((i * 131 + 7) % 256 for i in range(50_000))
    return files


def test_hostile_files_get_strict_answers_in_time(tmp_path):
    root = tmp_path / "hostile"
    root.mkdir()
    files = _hostile(tmp_path)
    for name, data in files.items():
        (root / name).write_bytes(data)
    running = Running({"h": root}, workers=2, catalog=True)  # the catalog scans them too
    try:
        routes = (
            "document",
            "properties",
            "configurations",
            "components",
            "references",
            "bom",
            "path-report",
            "preview",
            "mesh",
        )
        answered = 0
        for name in files:
            for route in routes:
                start = time.monotonic()
                r = running.get(route, root="h", path=name)
                assert time.monotonic() - start < 30, (name, route)
                assert r.status in (200, 404, 422), (name, route, r.status, r.body[:200])
                if r.headers["content-type"].startswith("application/json"):
                    env = r.json()  # strict: NaN or a bare big number would raise
                    assert env["ok"] is (r.status == 200)
                    assert r.status != 404 or env["error"]["code"] in ("no_preview", "nothing_to_export")
                elif route == "mesh":
                    assert r.headers["content-type"] == "model/gltf-binary" and is_glb(r.body)
                else:
                    assert route == "preview" and r.body.startswith(PNG)
                answered += 1
        assert answered == len(files) * len(routes) >= 100
        listing = running.get("list", root="h", include="properties,configurations,preview").json()["data"]
        assert listing["counts"]["entries"] == len(files)
        assert wait_for(lambda: running.server._catalog_path is not None, 120)
        for name in files:  # every file has its row in the catalog, read or not
            start = time.monotonic()
            r = running.get("where-used", root="h", path=name)
            assert time.monotonic() - start < 10 and r.status == 200, (name, r.status, r.body[:200])
            assert r.json()["ok"]
        for route, params in (("search", {"q": "a"}), ("search", {"q": "type:part"}), ("catalog", {})):
            r = running.get(route, **params)
            assert r.status == 200 and r.json()["ok"], (route, r.body[:200])
        assert running.request("/v1/health", token=None).status == 200  # the service is still up
    finally:
        running.close()


def _hostile_models(root: Path, outside: Path) -> dict[str, str]:
    """Hostile model files in ``root`` (some naming files in ``outside`` through a link),
    each with what its preview must not be: ``drawn`` when a link would let it draw from
    a file outside the root."""
    import io as _io
    import zipfile as _zip

    import alibre_writers as A
    import mesh_writers as mw
    from model_writers import box

    def put(name: str, data: bytes) -> None:
        (root / name).write_bytes(data)

    def zipped(parts: dict) -> bytes:
        buf = _io.BytesIO()
        with _zip.ZipFile(buf, "w", _zip.ZIP_DEFLATED) as z:
            for n, d in parts.items():
                z.writestr(n, d)
        return buf.getvalue()

    def members(data: bytes) -> dict:
        with _zip.ZipFile(_io.BytesIO(data)) as z:
            return {n: z.read(n) for n in z.namelist()}

    kinds: dict[str, str] = {}
    ok = mw.threemf(box(10, 20, 30))
    nan = '<build><item objectid="1" transform="1 0 0 0 1 0 0 0 1 nan 0 0"/></build>'
    put("nan_item.3mf", mw.threemf(box(10, 20, 30), build_xml=nan))
    utf8, unknown = b'encoding="UTF-8"', b'encoding="x-unknown"'
    parts = members(ok)
    parts["3D/3dmodel.model"] = parts["3D/3dmodel.model"].replace(utf8, unknown)
    put("enc.3mf", zipped(parts))
    put("enc.amf", mw.amf(box(1, 2, 3)).replace(utf8, unknown))
    zv = bytearray(ok)
    zv[zv.find(b"PK\x01\x02") + 6] = 0xFF
    put("zipver.3mf", bytes(zv))
    put("bomb.3mf", zipped({**members(ok), "3D/3dmodel.model": b" " * (40 << 20)}))
    off = mw.off(box(10, 20, 30)).decode().splitlines()
    first = next(i for i, line in enumerate(off) if len(line.split()) == 3 and line[0] in "0123456789")
    off[first + 1] = "1e300 0 0"
    put("overflow.off", ("\n".join(off) + "\n").encode())
    put("garbage.stl", b"solid x\nthis is not an STL statement\nendsolid x\n")
    # files named through a link to a file outside the root
    data, siblings = mw.gltf(box(10, 20, 30), buffer="file")
    (outside / "scene.bin").write_bytes(siblings["scene.bin"])
    os.link(outside / "scene.bin", root / "scene.bin")
    put("hard_buffer.gltf", data)
    kinds["hard_buffer.gltf"] = "drawn"
    (outside / "c.mtl").write_bytes(b"newmtl mat0\nKd 1 0 0\n")
    os.link(outside / "c.mtl", root / "c.mtl")
    obj, _sib = mw.obj(box(1, 1, 1, color=(1.0, 0.0, 0.0, 1.0)), mtl="c.mtl")
    put("hard_mtl.obj", obj)
    (outside / "cube.AD_PRT").write_bytes(A.part())
    os.link(outside / "cube.AD_PRT", root / "cube.AD_PRT")
    put("hard_pair.AD_ASM", A.assembly([A.Placed(A.CUBE_GUID), A.Placed(A.CUBE_GUID, origin=(2.0, 0, 0))]))
    kinds["hard_pair.AD_ASM"] = "drawn"
    if WINDOWS:
        import _winapi

        _winapi.CreateJunction(str(outside), str(root / "jn"))
        d = json.loads(data)
        d["buffers"][0]["uri"] = "jn/scene.bin"
        put("junction.gltf", json.dumps(d).encode())
        kinds["junction.gltf"] = "drawn"
    d = json.loads(data)
    d["buffers"][0]["uri"] = "../outside/scene.bin"
    put("escape.gltf", json.dumps(d).encode())
    kinds["escape.gltf"] = "drawn"
    return kinds


def test_hostile_model_files_get_strict_answers_in_time(tmp_path):
    """Model files served with ``--formats all``: strict JSON within the deadlines, no 500
    or 501, no host path in any answer, and no file outside the root read through a hard
    link or a junction (a buffer, a material library, an Alibre component)."""
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    kinds = _hostile_models(root, outside)
    names = sorted(p.name for p in root.iterdir() if p.suffix.lower() not in (".bin", ".mtl") and p.is_file())
    names = [n for n in names if n != "cube.AD_PRT"] + ["cube.AD_PRT"]
    running = Running({"m": root}, workers=2, formats="all")  # refuse_hard_links is on by default
    try:
        host = (str(tmp_path), str(tmp_path).replace("\\", "/"), str(tmp_path).replace("\\", "\\\\"))
        for name in names:
            for route, extra in (
                ("document", {}),
                ("properties", {}),
                ("preview", {}),
                ("preview", {"render": "always"}),
            ):
                start = time.monotonic()
                r = running.get(route, root="m", path=name, **extra)
                assert time.monotonic() - start < 60, (name, route)
                assert r.status in (200, 403, 404, 413, 422), (name, route, r.status, r.body[:300])
                assert not any(h.encode() in r.body for h in host), (name, route, r.body[:300])
                if r.headers["content-type"].startswith("application/json"):
                    env = r.json()  # strict: NaN or a bare big number would raise
                    assert env["ok"] is (r.status == 200)
                else:
                    assert route == "preview" and r.body.startswith(PNG)
                if kinds.get(name) == "drawn" and extra:  # a stored image is the file's own; a drawn one not
                    assert r.status != 200, (name, "drew from a file outside the root")
        doc = running.get("document", root="m", path="hard_mtl.obj").json()["data"]
        assert [x["resolution"]["status"] for x in doc["references"]] == ["refused"]
        assert running.get("document", root="m", path="cube.AD_PRT").status == 403  # the document itself
        assert running.request("/v1/health", token=None).status == 200  # the service is still up
    finally:
        running.close()
        if WINDOWS and (root / "jn").exists():
            os.rmdir(root / "jn")


def test_a_file_is_read_only_as_a_format_the_service_reads(tmp_path):
    """``serve --formats stl``: a ``.stl`` holding a 3MF, a glTF or a STEP file answers
    ``format_not_supported`` (rule ``format_not_enabled``) on every route, and is never
    read by those formats' readers; model files are read within SERVE_LIMITS."""
    import mesh_writers as mw
    from model_writers import box, stl_binary
    from solidseas.serve.server import SERVE_LIMITS

    (tmp_path / "box.stl").write_bytes(stl_binary(box(1, 1, 1)))
    (tmp_path / "pkg.stl").write_bytes(mw.threemf(box(1, 1, 1)))
    (tmp_path / "scene.stl").write_bytes(mw.gltf(box(1, 1, 1))[0])
    (tmp_path / "step.stl").write_bytes(fixture_path("o02_boxA.step").read_bytes())
    running = Running({"m": tmp_path}, formats="stl")
    try:
        assert running.server.config.limits == SERVE_LIMITS and SERVE_LIMITS.triangles == 10_000_000
        assert running.get("document", root="m", path="box.stl").status == 200
        for name, held in (("pkg.stl", "3mf"), ("scene.stl", "gltf"), ("step.stl", "step")):
            for route in ("document", "properties", "preview"):
                r = running.get(route, root="m", path=name)
                assert r.status == 422, (name, route, r.status)
                error = r.json()["error"]
                assert error["code"] == "format_not_supported", (name, route)
                assert error["detail"] == {"rule": "format_not_enabled", "value": held}, (name, route)
        listed = {e["path"]: e for e in running.get("list", root="m").json()["data"]["entries"]}
        assert listed["box.stl"]["status"] == "ok"
        assert listed["pkg.stl"]["error"]["detail"] == {"rule": "format_not_enabled", "value": "3mf"}
    finally:
        running.close()
    from solidseas.errors import InvalidArgumentError

    with pytest.raises(InvalidArgumentError):
        ServeConfig(roots=Roots([Root("m", str(tmp_path))]), tokens={"t": "x" * 32}, limits=7)
    assert ServeConfig(
        roots=Roots([Root("m", str(tmp_path))]), tokens={"t": "x" * 32}, limits={"triangles": 5}
    ).limits == SERVE_LIMITS.replace(triangles=5)



def test_a_root_served_without_subfolders_reads_no_file_below_a_documents_folder(tmp_path):
    """A model file in a root served without its subfolders reads the files it names from
    its own folder only, and the service's Alibre component search has bounds of its own."""
    import mesh_writers as mw
    from model_writers import box
    from solidseas.serve.server import SERVE_LIMITS

    root = tmp_path / "flat"
    (root / "sub").mkdir(parents=True)
    data, sib = mw.gltf(box(1, 1, 1), buffer="file")
    doc = json.loads(data)
    doc["buffers"][0]["uri"] = "sub/scene.bin"
    (root / "sub" / "scene.bin").write_bytes(sib["scene.bin"])
    (root / "s.gltf").write_text(json.dumps(doc))
    running = Running(Roots([Root("m", str(root), recursive=False)]), formats="all")
    try:
        r = running.get("document", root="m", path="s.gltf")
        assert r.status == 200 and r.json()["data"]["references"][0]["resolution"]["status"] == "refused"
        r = running.get("preview", root="m", path="s.gltf", render="always")
        assert r.status == 403 and r.json()["error"]["detail"]["rule"] == "subfolder"
    finally:
        running.close()
    assert (SERVE_LIMITS.resolve_examined, SERVE_LIMITS.resolve_candidates, SERVE_LIMITS.resolve_seconds) == (
        5_000,
        500,
        5.0,
    )

def test_a_slow_crashing_or_greedy_file_is_contained(tmp_path):
    for name in ("slow.SLDPRT", "crash.SLDPRT", "bomb.SLDPRT", "fine.SLDPRT"):
        shutil.copy2(O02, tmp_path / name)
    pool = WorkerPool(
        2,
        memory_mb=512,
        reader_message=False,
        jobs={
            "document_summary": "worker_jobs:document_summary",
            "listing_entry": "worker_jobs:listing_entry",
        },
    )
    running = Running({"a": tmp_path}, pool=pool, deadlines={"document": 2.0, "list_file": 2.0})
    try:
        start = time.monotonic()
        r = running.get("document", root="a", path="slow.SLDPRT")
        assert r.status == 504 and r.json()["error"]["code"] == "timeout"
        assert time.monotonic() - start < 2.0 + 2.0  # the deadline plus a little
        r = running.get("document", root="a", path="crash.SLDPRT")
        assert r.status == 500 and r.json()["error"]["code"] == "worker_crashed"
        r = running.get("document", root="a", path="bomb.SLDPRT")
        if WINDOWS or sys.platform.startswith("linux"):
            assert r.status == 422 and r.json()["error"]["code"] == "limit_exceeded"
        assert wait_for(lambda: running.get("document", root="a", path="fine.SLDPRT").status == 200, 30)
        entries = {e["path"]: e for e in running.get("list", root="a").json()["data"]["entries"]}
        assert entries["slow.SLDPRT"]["error"]["code"] == "timeout"
        assert entries["crash.SLDPRT"]["error"]["code"] == "worker_crashed"
        assert entries["fine.SLDPRT"]["status"] == "ok"
        assert running.request("/v1/health", token=None).status == 200
    finally:
        running.close()


def test_only_a_checked_image_is_served_as_a_preview(tmp_path):
    shutil.copy2(O02, tmp_path / "a.SLDPRT")
    pool = WorkerPool(1, reader_message=False, jobs={"preview": "worker_jobs:html_preview"})
    running = Running({"a": tmp_path}, pool=pool)
    try:
        r = running.get("preview", root="a", path="a.SLDPRT")
        assert r.status == 500 and r.json()["error"]["code"] == "worker_crashed"
        assert r.headers["content-type"] == "application/json; charset=utf-8" and b"<html" not in r.body
    finally:
        running.close()


def test_errors_never_carry_the_readers_message(srv, tree):
    """The reader's exception text can hold an absolute path: REST always sends null, for an
    error raised in the server process and for one raised in a worker."""
    calls = [
        ("document", {"root": "jobs", "path": "missing.SLDPRT"}, 404),
        ("document", {"root": "jobs", "path": "sub/missing.SLDPRT"}, 404),
        ("list", {"root": "jobs", "path": "nowhere"}, 404),
        ("properties", {"root": "jobs", "path": "o02_boxA.SLDPRT", "configuration": "Zq7"}, 404),
        ("document", {"root": "jobs", "path": "escape/secret.SLDPRT"}, 403),
        ("preview", {"root": "jobs", "path": "o02_boxA.SLDPRT", "nested": "Zq7"}, 404),
    ]
    for route, params, status in calls:
        r = srv.get(route, **params)
        assert r.status == status, (route, params, r.body[:200])
        assert r.json()["error"]["reader_message"] is None, (route, params)
    # the service's workers leave it out as well, so the text never even reaches the server process
    root = str(tree / "jobs")
    params = {"path": str(tree / "jobs" / "o02_boxA.SLDPRT"), "within": root, "configuration": "Zq7"}
    with pytest.raises(WorkerJobError) as caught:
        srv.server.pool.call("properties", params)
    assert caught.value.code == "configuration_not_found" and caught.value.info["reader_message"] is None


def test_a_response_over_its_cap_answers_422(tmp_path):
    shutil.copy2(O08, tmp_path / "o08_asm_2x_boxA.SLDASM")
    running = Running({"a": tmp_path}, workers=1, response_caps={"components": 1024})
    try:
        r = running.get("components", root="a", path="o08_asm_2x_boxA.SLDASM")
        assert r.status == 422 and r.json()["error"]["code"] == "response_too_large"
        assert r.json()["error"]["detail"] == {"limit": 1024}
        assert running.get("configurations", root="a", path="o08_asm_2x_boxA.SLDASM").status == 200
    finally:
        running.close()


def test_an_answer_over_its_cap_never_reaches_the_server_process(tmp_path, monkeypatch):
    """The service's own process has no memory cap, so a small crafted document must not make
    it read, parse and re-encode a huge worker answer just to refuse it: each call carries its
    route's cap, and the worker refuses a longer answer before sending it."""
    from builders import TreeXml, assembly_with_tree
    from solidseas import model as model_mod
    from solidseas import workers as workers_mod
    from solidseas.serve.server import REPLY_MARGIN

    t = TreeXml()
    t.top("m1")
    t.file("2", "C:\\Jobs\\p.SLDPRT")
    t.model("m2", "2")
    for i in range(1, 1001):
        t.ref("m1", "p", i, "m2")
    (tmp_path / "big.SLDASM").write_bytes(assembly_with_tree(t))
    with open_document(tmp_path / "big.SLDASM") as doc:
        whole = len(json.dumps(model_mod.build_components(doc)))
    cap = 4096
    assert whole > cap + REPLY_MARGIN  # the premise: the answer is far over its cap
    running = Running({"a": tmp_path}, workers=1, response_caps={"components": cap})
    try:
        largest = max(running.server.config.response_caps.values())
        assert running.server.pool.max_result_bytes == largest + REPLY_MARGIN
        sizes: list[int] = []
        real = workers_mod._loads
        monkeypatch.setattr(workers_mod, "_loads", lambda raw: (sizes.append(len(raw)), real(raw))[1])
        r = running.get("components", root="a", path="big.SLDASM")
        assert r.status == 422 and r.json()["error"]["code"] == "response_too_large"
        assert r.json()["error"]["detail"] == {"limit": cap}
        assert sizes and max(sizes) <= cap + REPLY_MARGIN
        assert not [e for e in running.server.pool.events if e[0] == "killed"]  # the worker lived on
        assert running.get("configurations", root="a", path="big.SLDASM").status == 200  # control
    finally:
        running.close()


def test_health_fails_while_no_worker_is_running(tmp_path):
    """A worker lost and not yet replaced leaves the service unable to read anything: health
    says so instead of answering ok, and recovers once a replacement starts."""
    shutil.copy2(O02, tmp_path / "a.SLDPRT")
    pool = WorkerPool(1, reader_message=False, jobs={"document_summary": "worker_jobs:document_summary"})
    running = Running({"a": tmp_path}, pool=pool)
    try:
        assert running.request("/v1/health", token=None).status == 200
        real, gate = pool._spawn, threading.Event()

        def held():
            if not gate.is_set():
                raise OSError(1455, "the paging file is too small for this operation to complete")
            return real()

        pool._spawn = held
        shutil.copy2(O02, tmp_path / "crash.SLDPRT")
        crashed = running.get("document", root="a", path="crash.SLDPRT").json()
        assert crashed["error"]["code"] == "worker_crashed"
        r = running.request("/v1/health", token=None)
        assert r.status == 503 and r.json()["error"]["code"] == "busy"
        assert r.json()["error"]["detail"] == {"rule": "no_workers"} and r.headers["retry-after"] == "2"
        gate.set()
        assert wait_for(lambda: running.request("/v1/health", token=None).status == 200, 60)
        assert running.get("document", root="a", path="a.SLDPRT").status == 200
    finally:
        running.close()


# --------------------------------------------------------------------------- headers and leaks
def test_every_response_carries_the_security_headers(srv):
    ok = srv.request("/v1/document?root=jobs&path=o02_boxA.SLDPRT")
    responses = [
        ok,
        srv.request(
            "/v1/document?root=jobs&path=o02_boxA.SLDPRT", headers={"If-None-Match": ok.headers["etag"]}
        ),
        srv.request("/v1/preview?root=jobs&path=o02_boxA.SLDPRT"),
        srv.request("/v1/document?root=jobs&path=missing.SLDPRT"),
        srv.request("/v1/version", token=None),
        srv.request("/v1/document?root=jobs&path=..%2Fx.SLDPRT"),
        srv.request("/v1/nope"),
    ]
    assert [r.status for r in responses] == [200, 304, 200, 404, 401, 403, 404]
    for r in responses:
        for name, value in SECURITY.items():
            assert r.headers.get(name) == value, (r.status, name)
        assert r.headers["server"] == "solidseas"  # no Python version
        assert r.headers["cache-control"] == "private, no-cache" and r.headers["x-request-id"]
    preview = responses[2]
    assert preview.headers["content-type"] == "image/png" and preview.body.startswith(PNG)
    assert all("text/html" not in r.headers.get("content-type", "") for r in responses)


def test_nothing_planted_reaches_the_logs(srv, tree):
    leaky = {"root": "jobs", "path": "leaky.SLDPRT"}
    report = srv.get("path-report", **leaky)
    props = srv.get("properties", **leaky)
    mix = [
        report,
        props,
        srv.get("document", **leaky),
        srv.get("components", **leaky),
        srv.get("references", resolve="1", **leaky),
        srv.get("properties", configuration="Zq7NoSuchConfiguration", **leaky),
        srv.get("document", root="jobs", path="Zq7Missing.SLDPRT"),
        srv.get("document", token=PLANTED_TOKEN, **leaky),
        srv.request("/v1/document?root=jobs&path=..%2FZq7Escape.SLDPRT"),
        srv.request(f"/v1/version?token={PLANTED_TOKEN}"),
    ]
    assert [r.status for r in mix] == [200, 200, 200, 200, 200, 404, 404, 401, 403, 400]
    # the planted values are really in the file: the report and the properties show them
    shown = report.body.decode("ascii") + props.body.decode("ascii")
    planted = [*PLANTED, *PLANTED_NAMES, PLANTED_VALUE]
    for value in planted:
        assert json.dumps(value)[1:-1] in shown, value
    logs = srv.log.text
    assert len(srv.log.lines) >= len(mix) and "route=/v1/path-report" in logs  # the log is being read
    secrets = [*planted, TOKEN, PLANTED_TOKEN, "Zq7", "zq7", "leaky", str(tree), "Users"]
    for value in secrets:
        assert value not in logs, value


def test_no_response_carries_cors_headers(srv):
    assert len(srv.responses) >= 100, "too few responses were collected to say anything"
    assert not any("access-control-allow-origin" in r.headers for r in srv.responses)


# --------------------------------------------------------------------------- what the server process does
def test_the_outbound_guard_is_on(outbound_guard):
    """Control for the module's guard: it really refuses what it is there to refuse."""
    seen = len(outbound_guard)
    with pytest.raises(OutboundConnection):
        socket.create_connection(("192.0.2.1", 9), timeout=1)
    with pytest.raises(OutboundConnection):
        socket.getaddrinfo("fileserver.example", 445)
    with pytest.raises(OutboundConnection):
        socket.socket().connect(("192.0.2.1", 9))
    assert len(outbound_guard) == seen + 3
    del outbound_guard[seen:]  # these attempts were the test's own


ROUTE_MIX = [
    ("list", {"root": "jobs", "recursive": "1", "include": "properties,configurations,preview"}),
    ("document", {"root": "jobs", "path": "o04_boxA_props.SLDPRT"}),
    ("properties", {"root": "jobs", "path": "o04_boxA_props.SLDPRT"}),
    ("configurations", {"root": "jobs", "path": "o02_boxA.SLDPRT"}),
    ("components", {"root": "jobs", "path": "o08_asm_2x_boxA.SLDASM"}),
    ("references", {"root": "jobs", "path": "o08_asm_2x_boxA.SLDASM", "resolve": "1"}),
    ("bom", {"root": "jobs", "path": "o08_asm_2x_boxA.SLDASM", "type": "indented"}),
    ("preview", {"root": "jobs", "path": "o02_boxA.SLDPRT"}),
    ("path-report", {"root": "jobs", "path": "o08_asm_2x_boxA.SLDASM"}),
    ("mesh", {"root": "jobs", "path": "o08_asm_2x_boxA.SLDASM"}),
    ("catalog", {}),
    ("where-used", {"root": "jobs", "path": "o02_boxA.SLDPRT"}),
    ("search", {"q": "boxA"}),
]


def test_the_server_process_never_opens_a_document(tree, monkeypatch):
    """Every document is read in a worker process; the server process opens none, not
    even to resolve references (C10)."""
    from solidseas import listing as listing_mod
    from solidseas.formats.solidworks import container

    opened: list[tuple[str, str]] = []
    real = container.open_readonly

    def record(path, **kwargs):
        opened.append((threading.current_thread().name, os.fspath(path)))
        return real(path, **kwargs)

    monkeypatch.setattr(container, "open_readonly", record)
    monkeypatch.setattr(listing_mod, "open_readonly", record)
    control = threading.Thread(target=lambda: open_document(O02).close(), name="control-thread")
    control.start()
    control.join(30)
    assert opened == [("control-thread", str(O02))]  # control: an open in this process is seen
    opened.clear()
    running = Running({"jobs": tree / "jobs"}, workers=1, catalog=True)  # its scans read in workers too
    try:
        assert wait_for(lambda: running.server._catalog_path is not None, 120)
        assert {route for route, _ in ROUTE_MIX} | {"health", "identity", "version", "roots"} == {
            p.removeprefix("/v1/") for p in ROUTES
        }
        for route, params in ROUTE_MIX:
            r = running.get(route, **params)
            assert r.status == 200, (route, r.body[:200])
    finally:
        running.close()
    assert opened == []


# --------------------------------------------------------------------------- what the code can reach
def _code_only(source: str) -> str:
    q = chr(34) * 3
    without_docstrings = re.sub(q + ".*?" + q, "", source, flags=re.S)
    return "\n".join(line.split("#", 1)[0] for line in without_docstrings.split("\n"))


def test_the_service_has_no_json_encoder_of_its_own():
    modules = sorted(SERVE_DIR.glob("*.py"))
    assert len(modules) >= 5
    code = {p.name: _code_only(p.read_text(encoding="utf-8")) for p in modules}
    assert "model.dumps(" in code["server.py"]  # the anchor
    assert not any("json.dumps(" in c or "import json" in c for c in code.values())


_NETWORK = [
    r"\bimport socket\b",
    r"\bsocket\.(socket|create_connection|getaddrinfo|getfqdn|gethostbyname)\b",
    r"\burllib\.request\b",
    r"\bhttp\.(client|server)\b",
    r"\bimport (requests|httpx)\b",
]


def test_only_the_service_module_touches_the_network():
    package = SRC / "solidseas"
    files = [p for p in package.rglob("*.py") if not ({"ai", "swapi"} & set(p.relative_to(package).parts))]
    assert len(files) >= 30, "the source walk found too few modules"
    hits = set()
    for p in files:
        code = _code_only(p.read_text(encoding="utf-8"))
        if any(re.search(rx, code) for rx in _NETWORK):
            hits.add(p.relative_to(package).as_posix())
    assert hits == {"serve/server.py"}


# --------------------------------------------------------------------------- shutdown
CHILD = Path(__file__).with_name("serve_child.py")


def test_a_stopped_service_ends_within_its_budget_with_a_worker_stuck(tmp_path):
    shutil.copy2(O02, tmp_path / "slow.SLDPRT")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(SRC), str(CHILD.parent)])}
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if WINDOWS else 0
    log = tmp_path / "stderr.txt"
    log_fh = open(log, "wb")  # a file, not a pipe nobody reads
    proc = subprocess.Popen(
        [sys.executable, str(CHILD), str(tmp_path)],
        stdout=subprocess.PIPE,
        stderr=log_fh,
        env=env,
        creationflags=flags,
    )
    try:
        port = int(proc.stdout.readline())
        results = []

        def stuck():
            import http.client

            c = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
            try:
                c.request(
                    "GET",
                    "/v1/document?root=a&path=slow.SLDPRT",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )
                results.append(c.getresponse().status)
            except OSError as exc:
                results.append(type(exc).__name__)

        t = threading.Thread(target=stuck, daemon=True)
        t.start()
        time.sleep(1.5)  # the request is waiting on a worker that sleeps
        start = time.monotonic()
        proc.send_signal(signal.CTRL_BREAK_EVENT if WINDOWS else signal.SIGTERM)
        proc.wait(15)
        elapsed = time.monotonic() - start
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        log_fh.close()
    err = log.read_text(encoding="utf-8", errors="replace")
    assert elapsed < 7, elapsed  # a 5 s budget, then the worker is killed and the process leaves
    assert elapsed > 4, elapsed  # control: it did wait for the request in flight
    assert proc.returncode == 0, err
    assert "stopping" in err and "stopped" in err
    t.join(10)
    assert results == [500]  # the stuck request was answered (worker_crashed) before the exit
