"""``--set-policy`` writes the machine policy as the fail-closed-machine-policy pattern asks:
every argument checked before anything is written, elevation asked of Windows (a check that
cannot say is a no), restrictions written first, and the policy read back with SolidSeas'
own reader, any difference a failure. Every branch has a test.

Nothing here writes a registry: the policy key is held in memory (:class:`FakeKey`, read
through the reader's own :class:`ai_support.FakeRegistry`), the real writer is replaced for
every test, and the test that starts SolidSeas stops at its argument check.
"""

import datetime
import io
import os
import subprocess
import sys
import textwrap
import types
from pathlib import Path

import pytest

from ai_support import REG_DWORD, REG_MULTI_SZ, REG_SZ, FakeRegistry
from solidseas import policy
from solidseas.policy import NO_POLICY, read_policy
from solidseas_app import setpolicy
from solidseas_app.setpolicy import EXIT_FAILED, EXIT_OK, EXIT_REFUSED, EXIT_USAGE, Machine

SRC = Path(__file__).resolve().parents[1] / "src"
REAL_KEY = setpolicy.WindowsPolicyKey
REAL_IS_ADMIN = setpolicy.is_admin
NOW = datetime.datetime(2026, 10, 22, 14, 3, 0, tzinfo=datetime.UTC)
HANDLE = "writable key"


@pytest.fixture(autouse=True)
def no_real_registry(monkeypatch):
    """A test that reached the real policy key would change this PC's policy, and on a test
    machine whose session runs elevated it could: fail instead."""

    def refuse(*args, **kwargs):
        raise AssertionError("a test reached the real policy key")

    monkeypatch.setattr(setpolicy, "WindowsPolicyKey", refuse)
    monkeypatch.setattr(setpolicy, "is_admin", lambda: False)


class FakeKey(FakeRegistry):
    """The policy key in memory, written with winreg's semantics and read through the
    FakeRegistry the reader's tests use. ``fail`` makes the write of that value raise,
    ``create_error`` opening the key and ``delete_error`` removing it; ``drop`` names values
    whose write does not stick, and ``stays`` keeps the key when it is removed."""

    def __init__(self, values=None, *, fail=None, create_error=None, delete_error=None, drop=(), stays=False):
        super().__init__(values)
        self.fail = dict(fail or {})
        self.create_error = create_error
        self.delete_error = delete_error
        self.drop = set(drop)
        self.stays = stays
        self.writes: list[tuple] = []
        self.held = 0  # handles opened to write and not closed

    def create(self):
        self.writes.append(("create",))
        if self.create_error is not None:
            raise self.create_error
        if self.values is None:
            self.values = {}
        self.held += 1
        return HANDLE

    def set(self, key, name, kind, value):
        assert key == HANDLE
        if name in self.fail:
            raise self.fail[name]
        self.writes.append(("set", name, kind, value))
        if name not in self.drop:
            self.values[name] = (value, kind)

    def remove(self, key, name):
        assert key == HANDLE
        self.writes.append(("remove", name))
        if name not in self.values:
            raise FileNotFoundError(2, "The system cannot find the file specified")
        del self.values[name]

    def close(self, key):
        if key == HANDLE:
            self.held -= 1
        else:
            super().close(key)

    def delete(self):
        self.writes.append(("delete",))
        if self.delete_error is not None:
            raise self.delete_error
        if self.values is None:
            raise FileNotFoundError(2, "The system cannot find the file specified")
        if not self.stays:
            self.values = None

    def changes(self) -> list[tuple]:
        return [w for w in self.writes if w[0] in ("set", "remove", "delete")]


def machine(key, *, windows=True, admin=True, read=None) -> Machine:
    return Machine(
        windows=windows,
        is_admin=admin if callable(admin) else (lambda: admin),
        key=lambda: key,
        read=read or (lambda: read_policy(key)),
        account=lambda: "LAB\\admin",
        now=lambda: NOW,
    )


def run(args, key, **kw) -> tuple[int, str]:
    out = io.StringIO()
    code = setpolicy.main(args, machine=machine(key, **kw), out=out)
    return code, out.getvalue()


# --------------------------------------------------------------------------- writing
def test_values_are_written_as_the_reader_takes_them_with_who_and_when():
    key = FakeKey(None)
    code, out = run(
        [
            "DisableAutomaticMode=1",
            "localprovideronly=1",  # registry names ignore case
            "AllowedProviderHosts= Ollama.Lab.Internal. ,198.51.100.3,[::1],ollama.lab.internal",
            "DisableImages=0",
            "AllowedExtensions= Gridfinity ,video",
        ],
        key,
    )
    assert code == EXIT_OK, out
    assert key.values == {
        "DisableAutomaticMode": (1, REG_DWORD),
        "LocalProviderOnly": (1, REG_DWORD),
        "AllowedProviderHosts": (["ollama.lab.internal", "198.51.100.3", "::1"], REG_MULTI_SZ),
        "DisableImages": (0, REG_DWORD),
        "AllowedExtensions": (["gridfinity", "video"], REG_MULTI_SZ),
        "SetBy": ("LAB\\admin", REG_SZ),
        "SetAt": ("2026-10-22T14:03:00Z", REG_SZ),
    }
    read = read_policy(key)
    assert read.automatic_disabled and read.local_only and not read.images_disabled and read.locked
    assert read.allowed_hosts == ("ollama.lab.internal", "198.51.100.3", "::1")
    assert read.allowed_extensions == ("gridfinity", "video") and read.error is None
    assert key.held == 0, "the key is closed again"
    assert policy.KEY_DISPLAY in out
    for line in (
        "DisableAutomaticMode = 1  (Automatic mode is off)",
        "AllowedProviderHosts = ollama.lab.internal, 198.51.100.3, ::1",
        "DisableImages = 0",
        "SetBy = LAB\\admin, SetAt = 2026-10-22T14:03:00Z",
    ):
        assert line in out


def test_restrictions_are_written_first_and_what_relaxes_one_last():
    key = FakeKey({"DisableExtensions": (1, REG_DWORD)})
    code, _ = run(
        [
            "DisableImages=0",
            "AllowedExtensions=video",
            "LocalProviderOnly=1",
            "--remove",
            "DisableExtensions",
            "DisableAutomaticMode=1",
        ],
        key,
    )
    assert code == EXIT_OK
    assert [w[1] for w in key.changes()] == [
        "DisableAutomaticMode",
        "LocalProviderOnly",
        "AllowedExtensions",
        "DisableImages",
        "DisableExtensions",
        "SetBy",
        "SetAt",
    ]


def test_values_not_named_stay_as_they_are():
    kept = {"DisableImages": (1, REG_DWORD), "AllowedExtensions": (["gridfinity"], REG_MULTI_SZ)}
    key = FakeKey(dict(kept))
    code, _ = run(["LocalProviderOnly=1"], key)
    assert code == EXIT_OK
    assert {name: key.values[name] for name in kept} == kept


def test_a_value_is_removed_and_one_not_set_is_no_error():
    key = FakeKey({"AllowedExtensions": (["video"], REG_MULTI_SZ), "DisableImages": (1, REG_DWORD)})
    code, out = run(["--remove", "allowedextensions", "--remove", "DisableAutomaticMode"], key)
    assert code == EXIT_OK, out
    assert "AllowedExtensions" not in key.values and read_policy(key).allowed_extensions is None
    assert key.values["DisableImages"] == (1, REG_DWORD)
    assert key.values["SetBy"] == ("LAB\\admin", REG_SZ), "a removal records who made it too"
    assert "AllowedExtensions = not set" in out


def test_remove_all_takes_the_key_away_and_nothing_is_managed_any_more():
    key = FakeKey({"DisableImages": (1, REG_DWORD), "SetBy": ("LAB\\admin", REG_SZ)})
    code, out = run(["--remove-all"], key)
    assert code == EXIT_OK
    assert key.values is None and read_policy(key) == NO_POLICY and not read_policy(key).locked
    assert "There is no machine policy" in out
    code, _ = run(["--remove-all"], key)
    assert code == EXIT_OK, "a key that is not there is already removed"


def test_help_writes_nothing():
    key = FakeKey(None)
    code, out = run(["--help"], key)
    assert code == EXIT_OK and "usage:" in out and key.writes == []


# --------------------------------------------------------------------------- refusals
@pytest.mark.parametrize(
    "args",
    [
        [],
        ["Bogus=1"],
        ["DisableImages=2"],
        ["DisableImages=yes"],
        ["DisableImages=true"],
        ["DisableImages="],
        ["DisableImages"],
        ["DisableImages=1", "disableimages=0"],
        ["--remove", "DisableImages", "DisableImages=1"],
        ["--remove"],
        ["--remove", "Bogus"],
        ["--remove-all", "DisableImages=1"],
        ["--remove-all", "--remove", "DisableImages"],
        ["--force"],
        ["SetBy=someone"],
        ["--remove", "SetAt"],
        ["AllowedProviderHosts="],
        ["AllowedProviderHosts=lab.internal,,other.internal"],
        ["AllowedProviderHosts=not a host!"],
        ["AllowedProviderHosts=lab.internal:11434"],
        ["AllowedProviderHosts=" + ",".join(f"h{i}.example" for i in range(policy.MAX_ALLOWED_HOSTS + 1))],
        ["AllowedExtensions=Not_An_Id"],
        ["AllowedExtensions=" + ",".join(f"x{i}" for i in range(policy.MAX_ALLOWED_EXTENSIONS + 1))],
        ["LocalProviderOnly=1", "AllowedProviderHosts=good.internal,bad host"],
    ],
)
def test_a_usage_error_writes_nothing_and_asks_nothing(args):
    key = FakeKey({"DisableImages": (1, REG_DWORD)})
    asked = []
    out = io.StringIO()
    code = setpolicy.main(args, machine=machine(key, admin=lambda: asked.append(1) or True), out=out)
    assert code == EXIT_USAGE
    assert key.writes == [] and asked == [], "nothing is written, and elevation is not asked about"
    assert "usage:" in out.getvalue()


@pytest.mark.parametrize("admin", [False, None, 1, "yes"])
def test_only_a_process_windows_calls_elevated_writes(admin):
    key = FakeKey(None)
    code, out = run(["DisableImages=1"], key, admin=admin)
    assert code == EXIT_REFUSED and key.writes == [] and "Run as administrator" in out


def test_an_elevation_check_that_fails_counts_as_no():
    def broken():
        raise OSError("shell32 could not be loaded")

    key = FakeKey(None)
    code, out = run(["DisableImages=1"], key, admin=broken)
    assert code == EXIT_REFUSED and key.writes == [] and "Nothing was written" in out


def test_off_windows_there_is_no_key_to_write():
    key = FakeKey(None)
    code, out = run(["DisableImages=1"], key, windows=False)
    assert code == EXIT_REFUSED and key.writes == [] and "no registry" in out


# --------------------------------------------------------------------------- failures
def test_a_key_that_cannot_be_opened_writes_nothing():
    key = FakeKey(None, create_error=PermissionError(13, "Access is denied"))
    code, out = run(["DisableImages=1"], key)
    assert code == EXIT_FAILED and key.changes() == [] and key.values is None
    assert "could not be opened to write (PermissionError, error 13)" in out and "Nothing was written" in out


def test_a_write_that_stops_part_way_says_what_was_written_and_how_the_policy_reads():
    gone = OSError(1018, "illegal operation on a key marked for deletion")
    key = FakeKey({}, fail={"LocalProviderOnly": gone})
    code, out = run(["LocalProviderOnly=0", "DisableAutomaticMode=1", "DisableImages=1"], key)
    assert code == EXIT_FAILED
    # the restrictions went first, and nothing after the value that failed
    assert key.values == {"DisableAutomaticMode": (1, REG_DWORD), "DisableImages": (1, REG_DWORD)}
    assert "LocalProviderOnly could not be written (OSError, error 1018)" in out
    assert "Written before it: DisableAutomaticMode, DisableImages." in out
    assert "DisableImages = 1" in out and key.held == 0


def test_who_and_when_that_cannot_be_written_is_a_failure():
    key = FakeKey({}, fail={"SetAt": PermissionError(5, "Access is denied")})
    code, out = run(["DisableImages=1"], key)
    assert code == EXIT_FAILED and "SetAt could not be written" in out


def test_a_value_that_does_not_read_back_as_written_is_a_failure():
    key = FakeKey({}, drop={"DisableImages"})
    code, out = run(["DisableImages=1", "LocalProviderOnly=1"], key)
    assert code == EXIT_FAILED
    assert "SolidSeas does not read the policy as it was written: DisableImages reads as 0, not 1" in out


def test_a_problem_in_a_value_left_alone_is_a_failure_until_it_is_put_right():
    key = FakeKey({"DisableAutomaticMode": ("1", REG_SZ)})
    code, out = run(["DisableImages=1"], key)
    assert code == EXIT_FAILED and "DisableAutomaticMode is not a DWORD" in out
    code, out = run(["DisableAutomaticMode=1"], key)
    assert code == EXIT_OK, out


def stopped_service():
    raise OSError("registry service stopped")


@pytest.mark.parametrize("reader", [stopped_service, lambda: {"automatic_disabled": True}])
def test_a_policy_that_cannot_be_read_back_is_a_failure(reader):
    key = FakeKey(None)
    code, out = run(["DisableImages=1"], key, read=reader)
    assert code == EXIT_FAILED
    assert "Problem:" in out and "SolidSeas does not read the policy as it was written" in out


def test_a_key_that_cannot_be_removed_says_so_and_how_it_reads():
    key = FakeKey({"DisableImages": (1, REG_DWORD)}, delete_error=PermissionError(5, "Access is denied"))
    code, out = run(["--remove-all"], key)
    assert code == EXIT_FAILED and "could not be removed (PermissionError, error 5)" in out
    assert "DisableImages = 1" in out


def test_a_key_still_there_after_its_removal_is_a_failure():
    key = FakeKey({"DisableImages": (1, REG_DWORD)}, stays=True)
    code, out = run(["--remove-all"], key)
    assert code == EXIT_FAILED and "the key is still there" in out


# --------------------------------------------------------------------------- the real machine
def test_the_real_writer_changes_the_key_the_reader_reads_in_the_same_view(monkeypatch):
    calls = []

    def call(name, answer=None):
        return lambda *args: calls.append((name, *args)) or answer

    fake = types.SimpleNamespace(
        HKEY_LOCAL_MACHINE="HKLM",
        KEY_QUERY_VALUE=0x1,
        KEY_SET_VALUE=0x2,
        KEY_READ=0x20019,
        KEY_WOW64_64KEY=0x100,
        CreateKeyEx=call("create", "k"),
        SetValueEx=call("set"),
        DeleteValue=call("remove"),
        CloseKey=call("close"),
        DeleteKeyEx=call("delete"),
        OpenKey=call("open", "r"),
    )
    monkeypatch.setitem(sys.modules, "winreg", fake)
    writer = REAL_KEY()
    handle = writer.create()
    writer.set(handle, "DisableImages", REG_DWORD, 1)
    writer.remove(handle, "AllowedExtensions")
    writer.close(handle)
    writer.delete()
    policy.WindowsRegistry().open()
    assert calls == [
        ("create", "HKLM", policy.KEY_PATH, 0, 0x1 | 0x2 | 0x100),
        ("set", "k", "DisableImages", 0, REG_DWORD, 1),
        ("remove", "k", "AllowedExtensions"),
        ("close", "k"),
        ("delete", "HKLM", policy.KEY_PATH, 0x100, 0),
        ("open", "HKLM", policy.KEY_PATH, 0, 0x20019 | 0x100),
    ]


def test_elevation_is_what_windows_says_and_a_check_that_cannot_say_is_no(monkeypatch):
    import ctypes

    monkeypatch.setattr(setpolicy.sys, "platform", "linux")
    assert REAL_IS_ADMIN() is False, "off Windows nothing is elevated"
    monkeypatch.setattr(setpolicy.sys, "platform", "win32")

    def shell(answer):
        return types.SimpleNamespace(shell32=types.SimpleNamespace(IsUserAnAdmin=answer))

    def broken():
        raise OSError("shell32 could not be loaded")

    for answer, expected in ((lambda: 1, True), (lambda: 0, False), (broken, False)):
        monkeypatch.setattr(ctypes, "windll", shell(answer), raising=False)
        assert REAL_IS_ADMIN() is expected


def test_who_set_it_is_the_account_windows_names(monkeypatch):
    import ctypes

    def named(kind, buffer, size):
        assert kind == 2  # NameSamCompatible: DOMAIN\name
        buffer.value = "LAB\\admin"
        return 1

    def secur32(call):
        return types.SimpleNamespace(secur32=types.SimpleNamespace(GetUserNameExW=call))

    monkeypatch.setattr(setpolicy.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", secur32(named), raising=False)
    assert setpolicy.account_name() == "LAB\\admin"
    monkeypatch.setattr(ctypes, "windll", secur32(lambda *args: 0), raising=False)
    assert setpolicy.account_name()  # the name the system gives otherwise


def test_this_pc_reads_the_registry_itself_never_the_substitutable_reader():
    real = Machine.this_pc()
    assert real.read is policy.read_policy and real.windows == (sys.platform == "win32")


# --------------------------------------------------------------------------- the entry point
def test_solidseas_starts_the_writer_before_anything_that_imports_qt():
    """``SolidSeasViewer.exe --set-policy`` runs elevated, so it must not load the viewer: in a
    fresh interpreter, the flag reaches the writer (here its argument check, which writes
    nothing anywhere) and no Qt module is imported."""
    script = textwrap.dedent(
        """
        import sys
        from solidseas_app.__main__ import main
        code = main(["SolidSeasViewer", "--set-policy", "NotAPolicyValue=1"])
        print(code, sorted(m for m in sys.modules if m.startswith("PySide6")))
        """
    )
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=120, env=env, check=False
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip().splitlines()[-1] == f"{EXIT_USAGE} []"
    assert "usage: SolidSeasViewer.exe --set-policy" in done.stdout


@pytest.mark.skipif(sys.platform == "win32", reason="off Windows only: there is no registry to refuse")
def test_off_windows_the_entry_point_refuses_with_its_exit_code():
    from solidseas_app.__main__ import main

    assert main(["SolidSeasViewer", "--set-policy", "DisableImages=1"]) == EXIT_REFUSED


REGISTRY_WRITES = frozenset(
    {
        "CreateKey",
        "CreateKeyEx",
        "DeleteKey",
        "DeleteKeyEx",
        "DeleteValue",
        "SetValue",
        "SetValueEx",
        "SaveKey",
        "LoadKey",
        "RegCreateKeyExW",
        "RegSetValueExW",
        "RegSetKeyValueW",
        "RegDeleteKeyExW",
        "RegDeleteValueW",
        "RegDeleteTreeW",
    }
)


def test_the_policy_key_is_written_only_by_set_policy():
    """The search the security review records: nothing in src names a registry call that
    writes, in any form (an attribute, a name, an import), but the writer of
    ``--set-policy`` and ``solidseas.swapi.hkcu``, which puts back only the values
    SolidSeas' own SOLIDWORKS changed under ``HKEY_CURRENT_USER\\Software\\SolidWorks``
    and refuses any other key (AGENTS.md, SolidSeas-1k3); neither of the others writes
    the policy key."""
    import ast

    hits = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Attribute):
                names = [node.attr]
            elif isinstance(node, ast.Name):
                names = [node.id]
            elif isinstance(node, ast.ImportFrom):
                names = [a.name for a in node.names]
            if REGISTRY_WRITES.intersection(names):
                hits.append(rel)
    assert sorted(set(hits)) == ["solidseas/swapi/hkcu.py", "solidseas_app/setpolicy.py"]
