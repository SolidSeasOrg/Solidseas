"""``solidseas serve --config FILE`` (``docs/API.md`` 8.17): the service's settings in a TOML
file, read failing closed.

The file's keys and types are checked one by one (an unknown key or a wrong type refuses
the start), its paths are taken from its own folder, and an option on the command line
replaces the file's setting. A file another account could change, or whose folder it could
change, refuses the start as the token file does, because the file decides what is served
and to whom.
"""

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from serve_support import TOKEN
from solidseas import cli
from solidseas.errors import InvalidArgumentError, PathRefusedError
from solidseas.serve import load_serve_config
from solidseas.serve import tokens as token_mod
from support import fixture_path

pytestmark = pytest.mark.usefixtures("outbound_guard")
WINDOWS = sys.platform == "win32"
O02 = fixture_path("o02_boxA.SLDPRT")
SRC = Path(__file__).resolve().parents[1] / "src"


def _write(folder, text: str, name: str = "serve.toml"):
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / name
    path.write_text(text, encoding="utf-8")
    if not WINDOWS:
        os.chmod(path, 0o644)  # readable by others is fine: the file holds no secret
    return path


def test_every_setting_is_read_with_its_type(tmp_path):
    folder = tmp_path / "etc"
    path = _write(
        folder,
        """
port = 9001
bind = "127.0.0.1"
token_file = "state/serve-tokens"
identity_key_file = "/var/lib/solidseas/key"
workers = 2
allow_remote = false
allowed_hosts = ["solidseas"]
identity_addresses = ["127.0.0.1:18765"]
allow_origins = ["https://intranet.example"]
catalog = true
catalog_rescan = 60
formats = ["stl", "3mf"]

[roots]
jobs = "../jobs"
archive = "/srv/archive"

[libraries]
std = "library"
""",
    )
    s = load_serve_config(path)
    assert s["port"] == 9001 and s["workers"] == 2 and s["catalog"] is True and s["allow_remote"] is False
    assert s["catalog_rescan"] == 60.0 and s["formats"] == "stl,3mf"
    assert s["token_file"] == os.path.normpath(str(folder / "state" / "serve-tokens"))  # from its folder
    assert s["identity_key_file"] == os.path.normpath("/var/lib/solidseas/key")
    assert s["allowed_hosts"] == ["solidseas"] and s["identity_addresses"] == ["127.0.0.1:18765"]
    assert [(r.id, r.role, r.path) for r in s["roots"]] == [
        ("jobs", "project", os.path.normpath(str(tmp_path / "jobs"))),
        ("archive", "project", os.path.normpath("/srv/archive")),
    ]
    assert [(r.id, r.role) for r in s["libraries"]] == [("std", "library")]
    assert load_serve_config(_write(tmp_path / "empty", "")) == {}  # nothing set is fine


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("prot = 8765", "prot"),
        ("port = true", "port"),
        ("port = 70000", "port"),
        ('port = "8765"', "port"),
        ("workers = 0", "workers"),
        ('catalog = "yes"', "catalog"),
        ("catalog_rescan = 0", "catalog_rescan"),
        ('allowed_hosts = "solidseas"', "allowed_hosts"),
        ("allowed_hosts = [1]", "allowed_hosts"),
        ('bind = ""', "bind"),
        ('token_file = "a\\u0000b"', "token_file"),
        ("[roots]", "roots"),
        ('roots = { Jobs = "/srv/jobs" }', "roots"),
        ('roots = "/srv/jobs"', "roots"),
        ("formats = 3", "formats"),
        ("[serve]\nport = 1", "serve"),
    ],
)
def test_a_setting_that_is_not_one_refuses_the_start(tmp_path, text, value):
    with pytest.raises(InvalidArgumentError) as caught:
        load_serve_config(_write(tmp_path, text))
    assert caught.value.detail == {"parameter": "config", "value": value}


@pytest.mark.parametrize(
    "data",
    [b"port = ", b"port = 1\nport = 2\n", b"\xff\xfe", b"# " + b"x" * (65 << 10)],
    ids=["not_toml", "twice", "not_utf8", "too_large"],
)
def test_a_file_that_is_not_a_settings_file_refuses_the_start(tmp_path, data):
    path = _write(tmp_path, "")
    path.write_bytes(data)
    with pytest.raises(InvalidArgumentError) as caught:
        load_serve_config(path)
    assert caught.value.detail == {"parameter": "config"}


def test_a_missing_file_is_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_serve_config(tmp_path / "nowhere.toml")
    with pytest.raises(PathRefusedError) as caught:
        load_serve_config(tmp_path)  # a folder
    assert caught.value.detail == {"rule": "not_regular_file", "parameter": "config"}


@pytest.mark.skipif(WINDOWS, reason="modes and owners are POSIX")
def test_a_file_others_may_change_refuses_the_start(tmp_path):  # pragma: no cover
    folder = tmp_path / "etc"
    path = _write(folder, "port = 9001\n")
    assert load_serve_config(path)["port"] == 9001  # control: readable by others, changed by us alone
    os.chmod(path, 0o664)
    with pytest.raises(PathRefusedError) as caught:
        load_serve_config(path)
    assert caught.value.code == "path_refused"
    assert caught.value.detail == {"rule": "shared_write", "parameter": "config"}
    os.chmod(path, 0o644)
    os.chmod(folder, 0o777)
    with pytest.raises(PathRefusedError) as caught:
        load_serve_config(path)
    assert caught.value.detail == {"rule": "folder_writable", "parameter": "config"}
    os.chmod(folder, 0o1777)  # sticky: each file stays its owner's, as in /tmp
    assert load_serve_config(path)["port"] == 9001
    os.chmod(folder, 0o700)
    link = tmp_path / "link.toml"
    os.symlink(path, link)
    assert load_serve_config(link)["port"] == 9001  # a link is followed, and its target checked
    os.chmod(path, 0o666)
    with pytest.raises(PathRefusedError):
        load_serve_config(link)


@pytest.mark.skipif(WINDOWS, reason="owners are POSIX")
def test_a_file_another_account_owns_refuses_the_start(tmp_path, monkeypatch):  # pragma: no cover
    path = _write(tmp_path / "etc", "port = 9001\n")
    real = os.stat

    def owned_by_someone(p, *args, **kwargs):
        st = real(p, *args, **kwargs)
        if os.fspath(p) == str(path):
            return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink, 4242, *tuple(st)[5:10]))
        return st

    monkeypatch.setattr(os, "stat", owned_by_someone)
    with pytest.raises(PathRefusedError) as caught:
        load_serve_config(path)
    assert caught.value.detail == {"rule": "not_owner", "parameter": "config"}


@pytest.mark.skipif(not WINDOWS, reason="access lists are Windows")
def test_a_file_others_may_change_refuses_the_start_on_windows(tmp_path, monkeypatch):
    """As the token file's checks, by access list: entries that only read are fine, any that
    may write, delete, re-permission or take the file or its folder refuse the start."""
    path = _write(tmp_path / "etc", "port = 9001\n")
    folder = "O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FR;;;BU)"
    cases = {
        "O:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;BU)(A;;FR;;;WD)": None,  # read by all: fine
        "O:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FW;;;BU)": "shared_write",
        "O:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;0x10000;;;AU)": "shared_write",  # delete it
        "O:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;WD;;;WD)": "shared_write",  # rewrite its list
        "O:BUD:P(A;;FA;;;SY)(A;;FA;;;BA)": "not_owner",
        "O:BAD:NO_ACCESS_CONTROL": "shared_write",
    }
    for sddl, rule in cases.items():
        monkeypatch.setattr(
            token_mod, "security_descriptor", lambda p, s=sddl: s if p.endswith(".toml") else folder
        )
        if rule is None:
            assert load_serve_config(path)["port"] == 9001, sddl
            continue
        with pytest.raises(PathRefusedError) as caught:
            load_serve_config(path)
        assert caught.value.detail == {"rule": rule, "parameter": "config"}, sddl
    own = "O:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)"
    for folder_sddl, rule in (
        ("O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;CI;0x2;;;BU)", "folder_writable"),  # add files
        ("O:BUD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)", "not_owner"),
        ("O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICIIO;FA;;;CO)", None),  # inherit-only
    ):
        monkeypatch.setattr(
            token_mod, "security_descriptor", lambda p, f=folder_sddl: own if p.endswith(".toml") else f
        )
        if rule is None:
            assert load_serve_config(path)["port"] == 9001, folder_sddl
            continue
        with pytest.raises(PathRefusedError) as caught:
            load_serve_config(path)
        assert caught.value.detail == {"rule": rule, "parameter": "config"}, folder_sddl


# --------------------------------------------------------------------------- the command line
@pytest.fixture
def started(monkeypatch):
    """Run ``solidseas serve`` in this process up to the point it serves: each start's
    ServeConfig is kept, and the service stops at once."""
    configs = []

    def stop_at_once(server) -> None:
        configs.append(server.config)
        server.shutdown(close_pool=True)

    monkeypatch.setattr("solidseas.serve.run_until_signalled", stop_at_once)
    log = logging.getLogger("solidseas.serve")  # leave the service's logger as it was
    monkeypatch.setattr(log, "handlers", list(log.handlers))
    monkeypatch.setattr(log, "propagate", log.propagate)
    return configs


def _tree(tmp_path):
    for name in ("jobs", "other", "lib"):
        (tmp_path / name).mkdir()
        shutil.copy2(O02, tmp_path / name / "a.SLDPRT")
    (tmp_path / "state").mkdir(mode=0o700)
    return tmp_path


def test_the_command_line_replaces_the_files_settings(tmp_path, capsys, started):
    base = _tree(tmp_path)
    config = _write(
        base / "etc",
        f"""
port = 0
workers = 1
token_file = "{(base / 'state' / 'tokens').as_posix()}"
catalog_rescan = 120
allow_origins = ["https://intranet.example"]

[roots]
jobs = "../jobs"

[libraries]
lib = "../lib"
""",
    )
    assert cli.main(["serve", "--config", str(config), "--json"]) == 0
    first = started[-1]
    assert [(r.id, r.role) for r in first.roots] == [("jobs", "project"), ("lib", "library")]
    assert first.roots["jobs"].path == os.path.normpath(str(base / "jobs"))
    assert first.allow_origins == ("https://intranet.example",) and first.catalog_rescan_s == 120.0
    assert (base / "state" / "tokens").is_file() and (base / "state" / "tokens.identity").is_file()
    out = json.loads(capsys.readouterr().out)
    assert out["kind"] == "serve_started" and out["data"]["roots"] == ["jobs", "lib"]
    argv = ["serve", "--config", str(config), "--root", f"other={base / 'other'}", "--catalog-rescan", "30"]
    assert cli.main([*argv, "--allow-origin", "http://127.0.0.1:3000", "--json"]) == 0
    second = started[-1]
    assert [(r.id, r.role) for r in second.roots] == [("other", "project"), ("lib", "library")]
    assert second.catalog_rescan_s == 30.0 and second.allow_origins == ("http://127.0.0.1:3000",)
    assert second.workers == 1  # the file's, where the command line says nothing
    capsys.readouterr()


@pytest.mark.parametrize(
    ("text", "code", "exit_code", "detail"),
    [
        ("prot = 1", "invalid_argument", 2, {"parameter": "config", "value": "prot"}),
        ('bind = "0.0.0.0"', "bind_refused", 3, {"rule": "remote_not_allowed"}),
        ('allow_origins = ["*"]', "invalid_argument", 2, {"parameter": "allow_origin"}),
        ('identity_addresses = ["localhost:1"]', "invalid_argument", 2, {"parameter": "identity_address"}),
    ],
)
def test_a_refused_file_stops_the_start_before_the_token_file_is_made(
    tmp_path, capsys, started, text, code, exit_code, detail
):
    base = _tree(tmp_path)
    tokens = base / "state" / "tokens"
    config = _write(base / "etc", f'{text}\ntoken_file = "{tokens.as_posix()}"\n[roots]\njobs = "../jobs"\n')
    assert cli.main(["serve", "--config", str(config), "--json"]) == exit_code
    env = json.loads(capsys.readouterr().out)
    assert env["error"]["code"] == code and env["error"]["detail"] == detail
    assert not tokens.exists() and started == []


def test_a_missing_file_exits_1(tmp_path, capsys, started):
    assert cli.main(["serve", "--config", str(tmp_path / "nowhere.toml"), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "not_found" and started == []


@pytest.mark.skipif(WINDOWS, reason="modes are POSIX")
def test_a_file_others_may_change_exits_3(tmp_path, capsys, started):  # pragma: no cover
    base = _tree(tmp_path)
    config = _write(base / "etc", '[roots]\njobs = "../jobs"\n')
    os.chmod(config, 0o666)
    assert cli.main(["serve", "--config", str(config), "--json"]) == 3
    env = json.loads(capsys.readouterr().out)
    assert env["error"]["code"] == "path_refused"
    assert env["error"]["detail"] == {"rule": "shared_write", "parameter": "config"} and started == []


def test_the_service_runs_from_its_file_alone(tmp_path):
    """The whole command in its own process, as a service manager starts it: every setting
    from the file, nothing else on the command line."""
    import http.client

    base = _tree(tmp_path)
    tokens = base / "state" / "tokens"
    token_mod._create_private(str(tokens), f"tests:{TOKEN}\n".encode("ascii"))
    config = _write(
        base / "etc",
        f'port = 0\nworkers = 1\ntoken_file = "{tokens.as_posix()}"\n[roots]\njobs = "../jobs"\n',
    )
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "solidseas", "serve", "--config", str(config), "--json"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if WINDOWS else 0,
    )
    try:
        port = json.loads(proc.stdout.readline())["data"]["port"]
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        auth = {"Authorization": f"Bearer {TOKEN}"}
        conn.request("GET", "/v1/document?root=jobs&path=a.SLDPRT", headers=auth)
        r = conn.getresponse()
        assert r.status == 200 and json.loads(r.read())["data"]["doc_type"] == "part"
        conn.close()
        proc.send_signal(signal.CTRL_BREAK_EVENT if WINDOWS else signal.SIGTERM)
        assert proc.wait(15) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        proc.stdout.close()
