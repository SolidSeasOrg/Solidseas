"""Settings > Connector (``solidseas_app.viewer.connectorpage`` and ``.connectorsvc``), and
``python -m solidseas_app --cli``, which the Connector and MCP apps start.

Most tests start the local API through a launcher of their own, a fake process that says
it is ready, ends when signalled or killed and records which. One test starts the real
service on port 0 against a temporary folder, calls ``/v1/roots`` with the token from its
file and turns it off again, leaving no process behind.
"""

import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from solidseas import policy
from test_viewer import needs_qt

SRC = Path(__file__).resolve().parents[1] / "src"
WINDOWS = sys.platform == "win32"
STOP_SIGNAL = signal.CTRL_BREAK_EVENT if WINDOWS else signal.SIGTERM


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _wait(app, condition, timeout: float = 30.0) -> None:
    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            raise AssertionError("timed out")
        app.processEvents()
        time.sleep(0.01)


def _ready_line(port: int = 8765) -> str:
    data = {"host": "127.0.0.1", "port": port, "url": f"http://127.0.0.1:{port}/v1/", "roots": ["folder"]}
    return json.dumps({"ok": True, "kind": "serve_started", "data": data}) + "\n"


class FakeProc:
    """A service process: ``out`` and ``err`` are its lines; it runs until signalled or
    killed (unless ``obeys`` is false), or until ``end`` is called, or at once with
    ``exit_code``."""

    def __init__(self, argv, out=None, err=(), *, exit_code=None, obeys=True):
        self.argv = argv
        self.pid = 4242
        self.obeys = obeys
        self.signals = []
        self.killed = False
        self.returncode = None
        self._done = threading.Event()
        self.stdout = self._lines([_ready_line()] if out is None else list(out))
        self.stderr = self._lines(list(err))
        if exit_code is not None:
            self.end(exit_code)

    def _lines(self, lines):
        yield from lines
        self._done.wait()

    def end(self, code):
        if self.returncode is None:
            self.returncode = code
        self._done.set()

    def poll(self):
        return self.returncode if self._done.is_set() else None

    def wait(self, timeout=None):
        if not self._done.wait(timeout):
            raise subprocess.TimeoutExpired(self.argv, timeout)
        return self.returncode

    def send_signal(self, sig):
        self.signals.append(sig)
        if self.obeys:
            self.end(0)

    def kill(self):
        self.killed = True
        self.end(-9)


class Launcher:
    def __init__(self, make=None):
        self.procs = []
        self.make = make or (lambda argv: FakeProc(argv))

    def __call__(self, argv):
        proc = self.make(argv)
        self.procs.append(proc)
        return proc


def _service(tmp_path, launcher=None, store=None):
    from solidseas_app.viewer.connectorsvc import ConnectorService
    from solidseas_app.viewer.settings import SettingsStore

    store = store or SettingsStore(str(tmp_path / "Viewer.ini"))
    return ConnectorService(
        None, store, launcher=launcher or Launcher(), token_file=str(tmp_path / "c" / "t")
    )


def _on(service, port=8765):
    from solidseas_app.viewer.connectorsvc import ConnectorSettings

    return service.apply(ConnectorSettings(share=True, port=port))


# --------------------------------------------------------------------------- the settings
@needs_qt
def test_the_page_starts_off_on_port_8765_and_a_bad_value_reads_as_its_default(app, tmp_path):
    from solidseas_app.viewer import connectorsvc as svc
    from solidseas_app.viewer.connectorpage import ConnectorPage
    from solidseas_app.viewer.settings import SettingsStore

    store = SettingsStore(str(tmp_path / "Viewer.ini"))
    assert svc.load_settings(store) == svc.ConnectorSettings(share=False, port=8765)
    service = _service(tmp_path, store=store)
    page = ConnectorPage(service)
    try:
        assert not page.share.isChecked() and page.port.value() == 8765
        assert page.status.text() == "Stopped." and not page.copy_address.isEnabled()
        assert page.config.toPlainText() == "Open a folder to see the configuration for it."
        assert not page.copy_config.isEnabled() and page.policy_note.isHidden()
        assert service.launcher.procs == [], "nothing runs until the person turns it on"
        store.save_section(svc.SECTION, {"share_open_folder": "maybe", "port": "80"})
        assert svc.load_settings(store) == svc.ConnectorSettings()
        page.share.setChecked(True)
        page.port.setValue(9001)
        page.restore_defaults()
        assert page.values() == svc.ConnectorSettings()
    finally:
        page.deleteLater()


# --------------------------------------------------------------------------- on, off, following
@needs_qt
def test_turning_it_on_starts_the_service_and_off_stops_it(app, tmp_path):
    from solidseas_app.viewer import connectorsvc as svc
    from solidseas_app.viewer.connectorpage import ConnectorPage

    folder = tmp_path / "Jobs"
    folder.mkdir()
    service = _service(tmp_path)
    service.folder_opened(str(folder))
    page = ConnectorPage(service)
    try:
        page.share.setChecked(True)
        page.port.setValue(9100)
        assert page.save()
        assert svc.load_settings(service.store) == svc.ConnectorSettings(share=True, port=9100)
        assert "[Connector]" in (tmp_path / "Viewer.ini").read_text(encoding="utf-8")
        (proc,) = service.launcher.procs
        assert proc.argv == [
            *svc.program(),
            "serve",
            "--root",
            f"folder={folder}",
            "--bind",
            "127.0.0.1",
            "--port",
            "9100",
            "--token-file",
            str(tmp_path / "c" / "t"),
            "--json",
        ]
        assert (tmp_path / "c").is_dir(), "the token file's folder is made; the service makes the file"
        assert service.state == svc.STARTING and page.status.text() == "Starting..."
        _wait(app, lambda: service.state == svc.RUNNING)
        assert page.status.text() == "Running at http://127.0.0.1:8765/v1/, reading the folder Jobs."
        assert page.copy_address.isEnabled()
        page.copy_address_clicked()
        from PySide6.QtGui import QGuiApplication

        assert QGuiApplication.clipboard().text() == "http://127.0.0.1:8765/v1/"

        page.share.setChecked(False)
        assert page.save()
        assert proc.signals == [STOP_SIGNAL] and not proc.killed and proc.poll() == 0
        assert service.state == svc.OFF and page.status.text() == "Stopped."
        assert len(service.launcher.procs) == 1
    finally:
        page.deleteLater()


def test_the_command_is_this_executable_with_cli_when_frozen():
    from solidseas_app.viewer import connectorsvc as svc

    exe = r"C:\Path\To\SolidSeas Viewer.exe"
    assert svc.program(is_frozen=True, executable=exe) == [exe, "--cli"]
    assert svc.program(is_frozen=False, executable="python") == ["python", "-m", "solidseas"]


@needs_qt
def test_another_folder_restarts_it_and_no_folder_waits(app, tmp_path):
    from solidseas_app.viewer import connectorsvc as svc

    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    service = _service(tmp_path)
    _on(service)
    assert service.state == svc.NO_FOLDER and service.launcher.procs == []
    service.folder_opened(str(a))
    _wait(app, lambda: service.state == svc.RUNNING)
    service.folder_opened(str(a))
    assert len(service.launcher.procs) == 1, "the same folder again changes nothing"
    service.folder_opened(str(b))
    first, second = service.launcher.procs
    assert first.poll() == 0 and first.signals == [STOP_SIGNAL]
    assert second.argv[second.argv.index("--root") + 1] == f"folder={b}"
    _wait(app, lambda: service.state == svc.RUNNING)
    service.folder_opened(None)
    assert second.poll() == 0 and service.state == svc.NO_FOLDER
    service.shutdown()


@needs_qt
def test_closing_the_window_stops_the_service(app, tmp_path):
    from solidseas_app.viewer import connectorsvc as svc
    from solidseas_app.viewer.settings import SettingsStore
    from solidseas_app.viewer.window import MainWindow

    folder = tmp_path / "Jobs"
    folder.mkdir()
    w = MainWindow(SettingsStore(str(tmp_path / "Viewer.ini")))
    launcher = Launcher()
    w.connector.launcher = launcher
    w.connector.token_file = str(tmp_path / "c" / "t")
    assert w.connector.token_file != svc.token_file_path(None)
    w.open_folder(str(folder))
    _on(w.connector)
    _wait(app, lambda: w.connector.state == svc.RUNNING)
    (proc,) = launcher.procs
    w.close()
    assert proc.poll() == 0 and proc.signals == [STOP_SIGNAL]
    assert launcher.procs == [proc], "it does not start again once the window closes"


def test_the_token_file_sits_beside_the_settings_file(tmp_path):
    from solidseas_app.viewer import connectorsvc as svc

    ini = tmp_path / "SolidSeas" / "Viewer.ini"
    assert svc.token_file_path(str(ini)) == str(tmp_path / "SolidSeas" / "Connector" / "serve-tokens")


def test_a_service_that_ignores_the_signal_is_killed(tmp_path):
    from solidseas_app.viewer import connectorsvc as svc

    proc = FakeProc(["serve"], obeys=False)
    svc.stop_process(proc, 0.1)
    assert proc.signals == [STOP_SIGNAL] and proc.killed and proc.poll() == -9


# --------------------------------------------------------------------------- the status line
@needs_qt
def test_a_port_in_use_says_so_in_plain_words(app, tmp_path):
    from solidseas_app.viewer import connectorsvc as svc
    from solidseas_app.viewer.connectorpage import ConnectorPage

    error = {"ok": False, "kind": "error", "error": {"code": "address_unavailable", "message": "x"}}
    out = json.dumps(error, indent=2).splitlines(keepends=True)
    service = _service(tmp_path, Launcher(lambda argv: FakeProc(argv, out, exit_code=1)))
    service.folder_opened(str(tmp_path))
    page = ConnectorPage(service)
    try:
        _on(service, 9200)
        _wait(app, lambda: service.state == svc.FAILED)
        assert page.status.text() == (
            "Stopped: Port 9200 is in use by another program. Choose another port, or close that program."
        )
        assert page.details.isHidden(), "nothing on standard error to show"
        (proc,) = service.launcher.procs
        assert proc.signals == [] and not proc.killed
    finally:
        page.deleteLater()


@needs_qt
def test_a_folder_refused_and_a_service_that_ends_on_its_own(app, tmp_path):
    from solidseas_app.viewer import connectorsvc as svc
    from solidseas_app.viewer.connectorpage import ConnectorPage

    error = {"ok": False, "kind": "error", "error": {"code": "not_found", "message": "gone"}}
    service = _service(tmp_path, Launcher(lambda argv: FakeProc(argv, [json.dumps(error)], exit_code=1)))
    service.folder_opened(str(tmp_path))
    page = ConnectorPage(service)
    try:
        _on(service)
        _wait(app, lambda: service.state == svc.FAILED)
        assert (
            page.status.text() == "Stopped: The folder was refused: it no longer exists or cannot be shared."
        )

        crashing = FakeProc(["serve"], err=["Traceback (most recent call last):", "MemoryError"])
        service.launcher.make = lambda argv: crashing
        service.restart()
        _wait(app, lambda: service.state == svc.RUNNING)
        crashing.end(3)
        _wait(app, lambda: service.state == svc.FAILED)
        assert page.status.text() == "Stopped: The service ended unexpectedly (exit code 3)."
        assert not page.details.isHidden()
        assert page.details.toPlainText() == "Traceback (most recent call last):\nMemoryError"
        assert not page.copy_address.isEnabled()
        service.launcher.make = lambda argv: FakeProc(argv)
        service.restart()  # the details go once it starts again
        assert page.details.isHidden()
        service.shutdown()
    finally:
        page.deleteLater()


@needs_qt
def test_a_launcher_that_cannot_start_it_fails_in_words(app, tmp_path):
    from solidseas_app.viewer import connectorsvc as svc

    def refuse(argv):
        raise FileNotFoundError(2, "No such file or directory")

    service = _service(tmp_path, refuse)
    service.folder_opened(str(tmp_path))
    _on(service)
    assert service.state == svc.FAILED
    assert service.error == "The service could not be started: No such file or directory."


# --------------------------------------------------------------------------- the buttons
@needs_qt
def test_the_buttons_copy_show_and_save_without_reading_the_token(app, tmp_path):
    from PySide6.QtGui import QGuiApplication

    from solidseas_app.viewer.connectorpage import ConnectorPage

    service = _service(tmp_path)
    page = ConnectorPage(service)
    try:
        page.copy_example_clicked()
        example = QGuiApplication.clipboard().text()
        assert f"Get-Content -LiteralPath '{tmp_path / 'c' / 't'}'" in example
        assert '"http://127.0.0.1:8765/v1/roots"' in example and "$auth" in example
        assert "Bearer" in example and "Invoke-RestMethod -Headers $auth" in example

        shown = []
        page.open_folder = shown.append
        page.show_token_clicked()
        assert shown == [str(tmp_path / "c")] and not (tmp_path / "c" / "t").exists()

        target = tmp_path / "out" / "api.json"
        target.parent.mkdir()
        page.ask_save_path = lambda: str(target)
        page.save_description_clicked()
        doc = json.loads(target.read_text(encoding="utf-8"))
        assert doc["openapi"].startswith("3.0") and "/v1/roots" in doc["paths"]
        assert page.result.text() == "Saved the API description as api.json."
        assert sorted(os.listdir(target.parent)) == ["api.json"]
        page.ask_save_path = lambda: ""
        page.save_description_clicked()  # cancelled: nothing more

        opened = []
        page.open_url = opened.append
        page.guide.linkActivated.emit(page.guide.text().split('"')[1])
        assert opened and opened[0].endswith("docs/guide/connector.md")
    finally:
        page.deleteLater()


# --------------------------------------------------------------------------- AI apps
def test_the_mcp_configuration_frozen_and_from_source():
    from solidseas_app.viewer import connectorsvc as svc

    folder = r"C:\Path\To\Projects"
    exe = r"C:\Path\To\SolidSeas Viewer.exe"
    frozen = json.loads(svc.mcp_config(folder, is_frozen=True, executable=exe))
    assert frozen == {
        "mcpServers": {
            "solidseas-files": {"command": exe, "args": ["--cli", "mcp", "--root", f"folder={folder}"]}
        }
    }
    source = json.loads(svc.mcp_config(folder, is_frozen=False, executable="python"))
    entry = source["mcpServers"]["solidseas-files"]
    assert entry == {"command": "python", "args": ["-m", "solidseas", "mcp", "--root", f"folder={folder}"]}


@needs_qt
def test_the_page_shows_the_open_folders_mcp_configuration(app, tmp_path):
    from PySide6.QtGui import QGuiApplication

    from solidseas_app.viewer.connectorpage import ConnectorPage

    service = _service(tmp_path)
    service.folder_opened(str(tmp_path))
    page = ConnectorPage(service)
    try:
        config = json.loads(page.config.toPlainText())
        assert config["mcpServers"]["solidseas-files"]["args"][-2:] == ["--root", f"folder={tmp_path}"]
        assert page.config.isReadOnly() and page.copy_config.isEnabled()
        page.copy_config_clicked()
        assert json.loads(QGuiApplication.clipboard().text()) == config
        assert "custom property values included" in page.privacy.text()
    finally:
        page.deleteLater()


@needs_qt
def test_local_provider_only_greys_the_mcp_part(app, tmp_path, policy_reader):
    from solidseas_app.viewer.connectorpage import POLICY_OFF, ConnectorPage

    policy_reader(policy.Policy(local_only=True, locked=True))
    service = _service(tmp_path)
    service.folder_opened(str(tmp_path))
    page = ConnectorPage(service)
    try:
        assert not page.policy_note.isHidden() and page.policy_note.text() == POLICY_OFF
        assert not page.config.isEnabled() and not page.copy_config.isEnabled()
        assert page.share.isEnabled(), "the local API is not an AI app's"
        policy_reader(lambda: (_ for _ in ()).throw(OSError("unreadable")))
        page.refresh()
        assert not page.copy_config.isEnabled(), "a policy that cannot be read restricts"
        policy_reader(policy.NO_POLICY)
        page.refresh()
        assert page.policy_note.isHidden() and page.copy_config.isEnabled()
    finally:
        page.deleteLater()


# --------------------------------------------------------------------------- the real service
def _children(pid: int) -> set[int]:
    """The processes whose parent is ``pid`` (Linux, from /proc)."""
    found = set()
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", encoding="ascii", errors="replace") as fh:
                fields = fh.read().rsplit(")", 1)[1].split()
        except OSError:
            continue
        if int(fields[1]) == pid:
            found.add(int(entry))
    return found


def _alive(pid: int) -> bool:
    if WINDOWS:  # pragma: no cover - Windows
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True
        ).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii") as fh:
            return fh.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return True


@needs_qt
def test_a_real_service_answers_with_the_token_from_its_file_and_stops(app, tmp_path, monkeypatch):
    from solidseas_app.viewer import connectorsvc as svc

    monkeypatch.setenv(
        "PYTHONPATH", os.pathsep.join(p for p in (str(SRC), os.environ.get("PYTHONPATH")) if p)
    )
    folder = tmp_path / "Jobs"
    folder.mkdir()
    (folder / "notes.txt").write_text("not a CAD file\n", encoding="utf-8")
    store_dir = tmp_path / "settings"
    store_dir.mkdir(mode=0o700)
    from solidseas_app.viewer.settings import SettingsStore

    service = svc.ConnectorService(None, SettingsStore(str(store_dir / "Viewer.ini")))
    assert service.token_file == str(store_dir / "Connector" / "serve-tokens")
    service.folder_opened(str(folder))
    service.apply(svc.ConnectorSettings(share=True, port=0))
    proc = service._proc
    try:
        _wait(app, lambda: service.state in (svc.RUNNING, svc.FAILED), timeout=120)
        assert service.state == svc.RUNNING, (service.error, service.details)
        assert service.port and service.url == f"http://127.0.0.1:{service.port}/v1/"
        lines = Path(service.token_file).read_text(encoding="utf-8").splitlines()
        token = next(line.split(":", 1)[1] for line in lines if line.startswith("default:"))
        request = urllib.request.Request(service.url + "roots", headers={"Authorization": f"Bearer {token}"})
        deadline = time.monotonic() + 60
        while True:
            with urllib.request.urlopen(request, timeout=30) as reply:
                env = json.loads(reply.read())
            roots = env["data"]["roots"]
            if roots[0].get("ready") or time.monotonic() > deadline:
                break
            time.sleep(0.2)
        assert env["ok"] and env["kind"] == "roots"
        assert [r["id"] for r in roots] == ["folder"]
        assert str(folder) not in json.dumps(env), "a client never sees the folder's path"
        workers = _children(proc.pid) if sys.platform.startswith("linux") else set()
    finally:
        service.apply(svc.ConnectorSettings(share=False, port=0))
    assert proc.poll() is not None
    assert service.state == svc.OFF and service._proc is None
    assert proc.returncode == 0, "it stopped the way it expects, not killed"
    assert not _alive(proc.pid)
    end = time.monotonic() + 15
    while any(_alive(p) for p in workers) and time.monotonic() < end:
        time.sleep(0.1)
    assert not any(_alive(p) for p in workers), "its worker processes end with it"


# --------------------------------------------------------------------------- --cli
def _env():
    return {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(p for p in (str(SRC), os.environ.get("PYTHONPATH")) if p),
    }


def test_cli_runs_the_command_line_and_exits_with_its_code():
    proc = subprocess.run(
        [sys.executable, "-m", "solidseas_app", "--cli", "version", "--json"],
        capture_output=True,
        text=True,
        env=_env(),
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    env = json.loads(proc.stdout)
    assert env["ok"] and env["kind"] == "version"
    bad = subprocess.run(
        [sys.executable, "-m", "solidseas_app", "--cli", "no-such-command"],
        capture_output=True,
        text=True,
        env=_env(),
        timeout=120,
    )
    assert bad.returncode == 2 and "PySide6" not in bad.stderr


def test_cli_mcp_answers_an_mcp_client_over_a_pipe(tmp_path):
    log = open(tmp_path / "stderr.txt", "wb")  # a file: a pipe nobody reads could fill
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "solidseas_app",
            "--cli",
            "mcp",
            "--root",
            f"folder={tmp_path}",
            "--workers",
            "1",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log,
        env=_env(),
    )
    try:

        def ask(rid, method, params=None):
            message = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
            proc.stdin.write(json.dumps(message).encode() + b"\n")
            proc.stdin.flush()
            reply = json.loads(proc.stdout.readline())
            assert reply["id"] == rid
            return reply["result"]

        result = ask(1, "initialize", {"protocolVersion": "2025-06-18"})
        assert result["protocolVersion"] == "2025-06-18" and result["serverInfo"]["name"]
        proc.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        assert "roots" in {t["name"] for t in ask(2, "tools/list")["tools"]}
        proc.stdin.close()
        assert proc.wait(60) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        log.close()
    text = (tmp_path / "stderr.txt").read_text(encoding="utf-8", errors="replace")
    assert "Traceback" not in text
