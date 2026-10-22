"""Putting back the registry values SolidSeas' own SOLIDWORKS changed (``solidseas.swapi.hkcu``).

The rule runs here on a stand-in registry. On Windows, the winreg backend also writes and reads
a scratch key of its own under ``HKEY_CURRENT_USER\\Software``, removed again, and the process
listing is checked on the test's own Python.
"""

import os
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

from registry_fake import FakeRegistry
from solidseas.swapi import hkcu

WINDOWS = sys.platform == "win32"
V = r"Software\SolidWorks\SOLIDWORKS 2024"
UI = V + r"\User Interface"
TABS = UI + r"\CommandManager\PartContext\Tab26"
TOOLBARS = UI + r"\Custom API Toolbars"
GENERAL = V + r"\General"
SZ, DWORD, BINARY = hkcu.REG_SZ, hkcu.REG_DWORD, hkcu.REG_BINARY


def _registry() -> FakeRegistry:
    """The account's SOLIDWORKS keys before SolidSeas' SOLIDWORKS starts: the layout under User
    Interface, General, and keys outside the scope."""
    return FakeRegistry({
        (TABS, "Button1"): (SZ, "Extrude"),
        (TABS, "Button2"): (SZ, "Cut"),
        (UI + r"\CommandManager", "TabContext3"): (BINARY, b"\x01\x02"),
        (TOOLBARS, "Toolbar1"): (DWORD, 7),
        (GENERAL, "Last Splash Id"): (SZ, "2024-old"),
        (GENERAL, "AutoRecover Directory"): (SZ, "%TEMP%"),
        (V + r"\Elsewhere", "Kept"): (SZ, "mine"),
        (r"Software\SolidWorks\Security", "Value"): (DWORD, 1),
    })


def _instance_writes(reg: FakeRegistry) -> None:
    """What SolidSeas' SOLIDWORKS writes while it runs, as measured: tabs changed, one added and
    one removed, a toolbar value, Last Splash Id, and values outside the scope."""
    reg.set_value(TABS, "Button1", (SZ, "Revolve"))
    reg.set_value(TABS, "Button3", (SZ, "Fillet"))
    reg.delete_value(UI + r"\CommandManager", "TabContext3")
    reg.set_value(TOOLBARS, "Toolbar1", (DWORD, 9))
    reg.set_value(GENERAL, "Last Splash Id", (SZ, "2024-new"))
    reg.set_value(GENERAL, "AutoRecover Directory", (SZ, "elsewhere"))  # not in the scope
    reg.set_value(V + r"\Elsewhere", "Kept", (SZ, "changed"))  # not in the scope
    reg.writes.clear()


def test_a_reading_holds_only_the_scope_of_each_version():
    reg = _registry()
    reg.set_value(r"Software\SolidWorks\SOLIDWORKS 2023\General", "Last Splash Id", (SZ, "2023"))
    reg.set_value(r"Software\SolidWorks\Not A Version\General", "Last Splash Id", (SZ, "x"))
    got = hkcu.read(reg)
    assert set(got.values) == {
        (TABS, "Button1"), (TABS, "Button2"), (UI + r"\CommandManager", "TabContext3"),
        (TOOLBARS, "Toolbar1"),
        (GENERAL, "Last Splash Id"), (r"Software\SolidWorks\SOLIDWORKS 2023\General", "Last Splash Id"),
    }
    assert got.roots == {
        (UI, None), (GENERAL, "Last Splash Id"),
        (r"Software\SolidWorks\SOLIDWORKS 2023\General", "Last Splash Id"),
    }, "2023 has no User Interface key, so it is not a root"
    assert got.covers(TABS, "Anything") and got.covers(UI, "Direct")
    assert not got.covers(GENERAL, "AutoRecover Directory") and not got.covers(V + r"\User Interfaces", "x")
    assert hkcu.read(FakeRegistry()) == hkcu.Reading({}, frozenset())


def test_what_the_instance_changed_in_the_scope_is_put_back():
    reg = _registry()
    before = hkcu.read(reg)
    _instance_writes(reg)
    found = hkcu.changes(before, hkcu.read(reg))
    assert [(c.path, c.name) for c in found] == [
        (GENERAL, "Last Splash Id"), (UI + r"\CommandManager", "TabContext3"), (TABS, "Button1"),
        (TABS, "Button3"), (TOOLBARS, "Toolbar1"),
    ]
    done = hkcu.put_back(reg, found)
    assert len(done.restored) == 5 and not done.changed_since and not done.not_written
    now = reg.snapshot()
    original = _registry().snapshot()
    for c in found:
        assert now.get((c.path, c.name)) == original.get((c.path, c.name)), c
    assert (TABS, "Button3") not in now, "a value the instance added is deleted"
    # Values outside the scope stay as the instance left them.
    assert now[(GENERAL, "AutoRecover Directory")] == (SZ, "elsewhere")
    assert now[(V + r"\Elsewhere", "Kept")] == (SZ, "changed")
    assert {w[0] for w in reg.writes} == {"set", "delete"}


def test_a_value_changed_again_since_or_of_another_type_is_left_as_it_is():
    reg = _registry()
    reg.set_value(TABS, "Link", (6, b"\x00"))  # REG_LINK: not one that reads and writes back unchanged
    before = hkcu.read(reg)
    _instance_writes(reg)
    reg.delete_value(TABS, "Link")
    found = hkcu.changes(before, hkcu.read(reg))
    reg.set_value(GENERAL, "Last Splash Id", (SZ, "the user's own"))  # changed again since
    reg.writes.clear()
    done = hkcu.put_back(reg, found)
    assert [(c.path, c.name) for c in done.changed_since] == [(GENERAL, "Last Splash Id")]
    assert [(c.name, why) for c, why in done.not_written] == [("Link", "it is of registry type 6")]
    assert reg.value(GENERAL, "Last Splash Id") == (SZ, "the user's own")
    assert ("set", GENERAL, "Last Splash Id", (SZ, "2024-old")) not in reg.writes
    assert len(done.restored) == 4  # the six changes, but those two


def test_a_write_that_fails_is_reported_and_the_rest_go_on():
    reg = _registry()
    before = hkcu.read(reg)
    _instance_writes(reg)
    found = hkcu.changes(before, hkcu.read(reg))
    real = reg.set_value

    def refusing(path, name, value):
        if name == "Toolbar1":
            raise PermissionError("access denied")
        real(path, name, value)

    reg.set_value = refusing
    done = hkcu.put_back(reg, found)
    assert [(c.name, why) for c, why in done.not_written] == [("Toolbar1", "access denied")]
    assert len(done.restored) == 4


def test_what_a_new_version_makes_is_left_alone():
    # The first start of a new SOLIDWORKS makes its keys: nothing under a key that was not there
    # before the instance started is deleted.
    reg = _registry()
    before = hkcu.read(reg)
    new = r"Software\SolidWorks\SOLIDWORKS 2025"
    reg.set_value(new + r"\User Interface\CommandManager", "TabContext1", (SZ, "made"))
    reg.set_value(new + r"\General", "Last Splash Id", (SZ, "2025"))
    assert hkcu.changes(before, hkcu.read(reg)) == []


def test_a_reading_too_large_is_refused(monkeypatch):
    monkeypatch.setattr(hkcu, "MAX_VALUES", 3)
    with pytest.raises(OSError, match="more than 3 values"):
        hkcu.read(_registry())


class Processes:
    """A stand-in for the process listing: the SLDWORKS.exe ids it gives, call by call."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        answer = self.answers[min(self.calls, len(self.answers)) - 1]
        if isinstance(answer, Exception):
            raise answer
        return set(answer)


def _run(processes, own_pid=4321, interval=3600.0, during=None):
    reg = _registry()
    restore = hkcu.RegistryRestore(reg, processes, interval=interval)
    restore.begin()
    _instance_writes(reg)
    if during is not None:
        during()
    return reg, restore.finish(own_pid)


def test_the_restore_puts_back_only_when_no_other_solidworks_ran():
    reg, outcome = _run(Processes(set(), {4321}))  # only SolidSeas' own instance, at the end
    assert outcome.others == () and not outcome.unknown and len(outcome.done.restored) == 5
    assert reg.value(TABS, "Button1") == (SZ, "Extrude")
    assert outcome.message() == (
        "put back 5 of the 5 registry values SolidSeas' SOLIDWORKS changed under "
        r"HKEY_CURRENT_USER\Software\SolidWorks"
    )
    # Another SOLIDWORKS running when the instance started: nothing is put back.
    reg, outcome = _run(Processes({77}, {77, 4321}))
    assert outcome.done is None and outcome.others == (77,) and reg.writes == []
    assert reg.value(TABS, "Button1") == (SZ, "Revolve")
    assert outcome.message() == (
        r"5 registry values under HKEY_CURRENT_USER\Software\SolidWorks changed while SolidSeas' SOLIDWORKS "
        "ran; another SOLIDWORKS ran meanwhile (PID 77), so they are left as they are"
    )
    # The processes could not be listed once: whether one ran is not known, so nothing either.
    reg, outcome = _run(Processes(set(), OSError("denied"), {4321}))
    assert outcome.done is None and outcome.unknown and reg.writes == []
    assert "; whether another SOLIDWORKS ran meanwhile could not be told, so they" in outcome.message()
    # An instance whose start failed before its process id was known cannot be told from another.
    reg, outcome = _run(Processes(set(), {4321}), own_pid=None)
    assert outcome.done is None and outcome.others == (4321,) and outcome.not_started
    why = "SolidSeas' SOLIDWORKS did not start, so it cannot be told from the SOLIDWORKS that ran (PID 4321)"
    assert f"; {why}, so" in outcome.message()
    change = hkcu.Change(GENERAL, "Last Splash Id", None, (SZ, "x"))
    one = hkcu.Outcome([change], None, others=(5,)).message()
    assert one.startswith(r"1 registry value under HKEY_CURRENT_USER")
    assert one.endswith("so it is left as it is")


def test_a_solidworks_that_came_and_went_while_the_instance_ran_is_seen():
    # The user's SOLIDWORKS started and exited while SolidSeas' ran: the watch thread saw it.
    processes = Processes(set(), {4321}, {4321, 88}, {4321, 88}, {4321})
    reg, outcome = _run(processes, interval=0.01, during=lambda: _until(lambda: processes.calls >= 5))
    assert outcome.others == (88,) and outcome.done is None and reg.writes == []


def test_nothing_changed_says_nothing():
    reg = _registry()
    restore = hkcu.RegistryRestore(reg, Processes(set()), interval=3600.0)
    restore.begin()
    outcome = restore.finish(4321)
    assert outcome.changed == [] and outcome.message() is None and reg.writes == []
    if not WINDOWS:
        assert hkcu.RegistryRestore.for_this_system() is None, "no SOLIDWORKS is started here"


def test_a_reading_that_fails_at_the_start_stops_the_watch():
    class Unreadable(FakeRegistry):
        def subkeys(self, path):
            raise PermissionError("access denied")

    restore = hkcu.RegistryRestore(Unreadable(), Processes(set()), interval=0.01)
    before = threading.active_count()
    with pytest.raises(PermissionError):
        restore.begin()
    assert _until(lambda: threading.active_count() <= before), "the watch thread was left running"


def _until(condition, wait: float = 15.0) -> bool:
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


# --------------------------------------------------------------------------- Windows
@pytest.mark.skipif(not WINDOWS, reason="winreg is Windows'")
def test_the_windows_registry_reads_and_writes_back_every_kind_of_value():
    import winreg

    root = rf"Software\SolidSeas-test-{uuid.uuid4().hex}"
    reg = hkcu.WinRegistry(root)
    kinds = {
        "sz": (winreg.REG_SZ, "text"), "expand": (winreg.REG_EXPAND_SZ, "%TEMP%\\x"),
        "binary": (winreg.REG_BINARY, b"\x00\x01\xff"), "dword": (winreg.REG_DWORD, 0xFFFFFFFF),
        "multi": (winreg.REG_MULTI_SZ, ["a", "b"]), "qword": (winreg.REG_QWORD, 2**40),
    }
    try:
        for name, value in kinds.items():
            reg.set_value(root + r"\sub", name, value)
        assert reg.values(root + r"\sub") == kinds and reg.subkeys(root) == ["sub"]
        assert all(reg.value(root + r"\sub", n) == v for n, v in kinds.items())
        reg.delete_value(root + r"\sub", "sz")
        with pytest.raises(FileNotFoundError):
            reg.value(root + r"\sub", "sz")
        with pytest.raises(FileNotFoundError):
            reg.subkeys(root + r"\missing")
        # It writes nowhere but under its root.
        for outside in (r"Software\Elsewhere", root + "-other"):
            with pytest.raises(PermissionError):
                reg.set_value(outside, "x", (winreg.REG_SZ, "x"))
            with pytest.raises(PermissionError):
                reg.delete_value(outside, "x")
        assert hkcu.WinRegistry().root == hkcu.ROOT
    finally:
        for path in (root + r"\sub", root):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
            except OSError:
                pass


@pytest.mark.skipif(not WINDOWS, reason="the process listing is Windows'")
def test_the_process_listing_finds_processes_by_their_program():
    # The test's own Python stands in for SLDWORKS.exe: the listing matches the program's file
    # name in any case.
    program = Path(sys.executable).name
    assert os.getpid() in hkcu.process_ids(program)
    assert os.getpid() in hkcu.process_ids(program.upper())
    assert hkcu.process_ids(f"no-such-program-{uuid.uuid4().hex}.exe") == set()
    assert isinstance(hkcu.solidworks_pids(), set)
