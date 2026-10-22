"""The SOLIDWORKS bridge (``solidseas.swapi``): its client, the batch conversion on it, and its source.

Nothing here starts SOLIDWORKS unless asked. The client and batch tests run a
stand-in bridge (``swbridge_fake.py``) that speaks the same protocol, on every
operating system, so CI covers the timeouts, the crashes and the job that ends
the bridge together with what it started.

Opt-in, on Windows:

* ``SOLIDSEAS_SWAPI_BUILD_CHECK=1`` compiles the real bridge with the .NET
  Framework's ``csc.exe`` against the SOLIDWORKS interop assemblies and runs it
  without SOLIDWORKS: the protocol, and a request that blocks its apartment
  thread, which must not hang the caller. ``SOLIDSEAS_SWBRIDGE`` names an
  already built one instead.
* ``SOLIDSEAS_SWAPI_WINDOW_CHECK=1``, with the build check, also compiles a
  stand-in ``SLDWORKS.exe`` that shows dialogs off every screen without
  activating them, has the bridge start one copy and starts another as the
  user's SOLIDWORKS, and checks that the bridge hides the journal file message
  box of its own copy and touches nothing else, and that once the watch looks
  only slowly its WinEvent hook still has a box shown again hidden at once.
* ``SOLIDSEAS_SWAPI_SOLIDWORKS=1`` also starts SolidSeas' own SOLIDWORKS through
  that bridge: a batch conversion of fixture copies to every format, a real
  SOLIDWORKS call given a timeout it cannot meet, ``save_copy`` given another
  name for the open part's own file, the journal file message box hidden while
  another SOLIDWORKS runs, an instance ended through its job leaving the
  registry layout, lock files and the next start alone, and, with no other
  SOLIDWORKS running, instances ended through their job, one by a timeout,
  leaving no auto-recover copy, no backup and no new dialog for the next start.
  It also measures fixture copies with ``mass_properties``, and imports
  ``o02_boxA.step``, ``.x_t`` and ``.x_b`` and SolidSeas' own STEP of o11 and
  o12 (written by ``solidseas.step``) with ``import_file``, both ways, and
  SolidSeas' own STEP of o12 and of the assemblies o08 and o15, with
  ``o02_boxA.step``, as components, each in a SOLIDWORKS of its own, and
  compares the measures with ``ground_truth.json``.
  It also runs the window check. Starting SOLIDWORKS takes the foreground for
  6 to 7 s, so run it off-hours, with ``--basetemp`` on a scratch folder:
  SOLIDWORKS adds every document it opens to the account's recent documents.
  It takes two runs, because the journal box comes only while another
  SOLIDWORKS runs and the off-hours case is SolidSeas' instance alone: first,
  with your SOLIDWORKS closed normally, ``-k no_recovery_behind`` by itself,
  so its first start follows a clean exit; then the whole file with your
  SOLIDWORKS open. Each of the two journal tests skips in the other run.
"""

import datetime as dt
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from solidseas.swapi import batch, bridge, build
from solidseas.swapi.bridge import (
    Bridge,
    BridgeExitedError,
    BridgeNotFoundError,
    BridgeRequestError,
    BridgeTimeoutError,
)
from support import FIXTURES

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
FAKE = TESTS / "swbridge_fake.py"
SWAPI = ROOT / "src" / "solidseas" / "swapi"
BUILD_SCRIPT = ROOT / "scripts" / "build-bridge.ps1"
POWERSHELL = shutil.which("powershell.exe") if sys.platform == "win32" else None
WINDOWS = sys.platform == "win32"


def fake(behaviour: dict | None = None, **kwargs) -> Bridge:
    return Bridge(command=[sys.executable, str(FAKE), "--behaviour", json.dumps(behaviour or {})], **kwargs)


def _alive(pid: int) -> bool:
    if WINDOWS:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k32.WaitForSingleObject.restype = wintypes.DWORD
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = k32.OpenProcess(0x00100000 | 0x1000, False, pid)  # SYNCHRONIZE | QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            return k32.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT: still running
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return True


def _gone(pid: int, wait: float = 15.0) -> bool:
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return False


def _until(condition, wait: float = 15.0) -> bool:
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


# --------------------------------------------------------------------------- the C# source
def _source() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(build.SOURCE_DIR.glob("*.cs")))


def test_sources_and_build_script_present():
    names = {p.name for p in build.SOURCE_DIR.glob("*.cs")}
    assert names == {
        "Program.cs", "Native.cs", "Operations.cs", "WindowWatch.cs", "Measure.cs", "Import.cs", "Live.cs",
        "NativeCheck.cs", "TestSession.cs",
    }
    assert BUILD_SCRIPT.is_file()
    assert not list(SWAPI.rglob("*.dll")) and not list(SWAPI.rglob("*.exe")), "nothing built goes in the tree"
    readme = (SWAPI / "README.md").read_text(encoding="utf-8")
    needles = ("SolidWorks_PID_", "SwDocumentMgr.SwDMClassFactory", "Customer Portal", "OpenCASCADE")
    needles += ("timeout_s",)
    for needle in needles:
        assert needle in readme


def test_the_traps_page_says_where_each_trap_was_measured():
    page = (ROOT / "docs" / "SOLIDWORKS_API_TRAPS.md").read_text(encoding="utf-8")
    rows = [line for line in page.splitlines() if line.startswith("| ") and not line.startswith("| Symptom ")]
    assert len(rows) > 30, f"only {len(rows)} rows were read"
    for row in rows:
        cells = [c.strip() for c in row.strip().strip("|").split(" | ")]
        assert len(cells) == 3 and all(cells), row  # symptom, what to do, where it was measured
    readme = (SWAPI / "README.md").read_text(encoding="utf-8")
    assert "(../../../docs/SOLIDWORKS_API_TRAPS.md)" in readme


def test_bridge_offers_only_its_named_operations():
    source = _source()
    ops = set(re.findall(r'handlers\["(\w+)"\]', source))
    assert ops == {
        "hello", "shutdown", "sleep", "exit", "emit", "classify_windows", "watch_timing", "start_solidworks",
        "solidworks_info", "exit_solidworks", "new_document", "open_document", "document_info",
        "list_features", "save_copy", "close_document", "watch_document", "unwatch_document",
        "mass_properties", "import_file", "native_check", *LIVE_OPERATIONS, *TEST_SESSION_OPERATIONS,
    }
    # The test-session operations exist only with --test-session.
    assert re.search(r"if \(Program\.TestSession\) Operations\.RegisterTestSession\(handlers\);", source)
    registered = source[source.index("public static void RegisterTestSession("):]
    registered = registered[: registered.index("\n        }\n")]
    assert set(re.findall(r'handlers\["(\w+)"\]', registered)) == set(TEST_SESSION_OPERATIONS)
    # The test operations exist only with --test-ops.
    test_ops = re.search(r'if \(Program\.TestOps\)\s*\{([^}]*)\}', source).group(1)
    test_names = {"sleep", "exit", "emit", "classify_windows", "watch_timing"}
    assert set(re.findall(r'handlers\["(\w+)"\]', test_ops)) == test_names
    # Every operation is documented.
    readme = (SWAPI / "README.md").read_text(encoding="utf-8")
    for op in ops:
        assert f"`{op}`" in readme, op


def _code() -> str:
    """The C# without its line comments, which may name what the code must never do."""
    return re.sub(r"//[^\n]*", "", _source())


TEST_SESSION_OPERATIONS = (
    "test_session_new_part", "test_session_open", "test_session_native_check", "test_session_close",
    "test_session_documents",
)
LIVE_OPERATIONS = (
    "list_sessions", "live_attach", "live_detach", "live_documents", "live_document_info", "live_snapshot",
    "live_features", "live_dimensions", "live_properties", "live_mass_properties", "live_checkpoint",
    "live_begin_undo", "live_end_undo", "live_operation", "live_delete_feature", "live_restore_property",
    "live_current_refs",
)


def _function(code: str, signature: str) -> str:
    """One method of the C#, from its signature to the next method at the same depth."""
    start = code.index(signature)
    end = code.find("\n        static ", start + len(signature))
    return code[start: end if end > 0 else len(code)]


def test_live_mode_never_ends_closes_or_saves_the_persons_work():
    # Live mode works in a SOLIDWORKS the person started: it binds it by its moniker only, and
    # never ends it, closes or saves a document of it, or changes an option.
    code = re.sub(r"//[^\n]*", "", (build.SOURCE_DIR / "Live.cs").read_text(encoding="utf-8"))
    for forbidden in (
        "ExitApp", "CloseDoc", "CloseAllDocuments", "TerminateJob", "TerminateProcess", "Kill(", ".Save3(",
        ".Save2(", ".Save(", "SetUserPreference", "EditUndo", "RunCommand", "GetActiveObject", "ForceRebuild",
        "Process.Start", "QuitDoc", "OpenDoc", "NewDocument",
    ):
        assert forbidden not in code, forbidden
    attach = _function(code, "static Dictionary<string, object> LiveAttach(")
    assert "Rot.Find(pid)" in attach and "CheckSolidWorksProcess(pid)" in attach
    assert attach.index("CheckSolidWorksProcess(pid)") < attach.index("Rot.Find(pid)")
    # The one file it writes in SOLIDWORKS: the safety copy, a copy, checked before it is written.
    assert code.count("SaveAs3(") == 1
    checkpoint = _function(code, "static Dictionary<string, object> LiveCheckpoint(")
    assert "swSaveAsOptions_Copy" in checkpoint and "SaveAs3(" in checkpoint
    for check in ("CheckpointName.IsMatch(", "Path.GetDirectoryName(folder), runs", "File.Exists(target)"):
        assert checkpoint.index(check) < checkpoint.index("SaveAs3("), check
    # Deleting: only a feature this bridge made, or the sketch a failed extrude of its own left.
    assert code.count("DeleteSelection2(") == 2
    delete = _function(code, "static Dictionary<string, object> LiveDeleteFeature(")
    assert delete.index("madeHere.Contains(reference)") < delete.index("DeleteSelection2(")
    assert "swDelete_Absorbed" in delete
    assert "DeleteSelection2(" in _function(code, "static void DeleteSelected(")
    extrude = _function(code, "static Dictionary<string, object> SketchExtrude(")
    assert "if (made == null) DeleteSelected(doc, sketchFeature)" in extrude
    # An undo entry's opening, and a lock, are on disk before they happen, so an ended bridge's
    # are closed and released again.
    opener = _function(code, "static void OpenUndoEntry(")
    assert opener.index("WriteState(") < opener.index("StartRecordingUndoObject()")
    state = _function(code, "static void WriteState(")
    assert "FileMode.CreateNew" in state and "Flush(true)" in state
    begin = _function(code, "static Dictionary<string, object> LiveBeginUndo(")
    assert begin.index("CloseLeftUndoEntry(livePid)") < begin.index("OpenUndoEntry(")
    assert code.count("StartRecordingUndoObject()") == 1
    operation = _function(code, "static Dictionary<string, object> LiveOperation(")
    assert operation.index("WriteState(LockStatePath(livePid), key)") < operation.index("doc.Lock()")
    assert operation.index("doc.Lock()") < operation.index("doc.UnLock()")
    assert "FinishRecordingUndoObject2(name, false)" in _function(code, "static bool CloseUndoEntry(")
    # Changes act on the active part only, with the selection checked just before the call.
    operation = _function(code, "static Dictionary<string, object> LiveOperation(")
    assert "LivePart(args, out key)" in operation and "!IsActive(doc)" in operation
    assert "ActiveSketch != null" in operation
    assert "ExpectSelection(doc, (int)swSelectType_e.swSelSKETCHES, 1)" in extrude
    assert "ExpectSelection(doc, (int)swSelectType_e.swSelEDGES, edges.Length)" in code
    fillet = _function(code, "static Dictionary<string, object> Fillet(")
    assert fillet.index("ExpectSelection(doc, (int)swSelectType_e.swSelEDGES, edges.Length)") < fillet.index(
        "FeatureFillet3("
    )
    assert "swFeatureFilletPropagate" not in fillet
    # Each body is measured on its own, so the person's selection is neither used nor touched.
    mass = _function(code, "static Dictionary<string, object> LiveMass(")
    assert "GetMassProperties(1.0)" in mass and "CreateMassProperty" not in mass
    # The batch instance carries its mark while it runs.
    operations = _code_of("Operations.cs")
    start = operations[operations.index("static Dictionary<string, object> StartSolidWorks("):]
    assert start.index("OwnedProcess.Start(exe)") < start.index("MarkBatch(process.Id)")
    end = operations[operations.index("public static Dictionary<string, object> EndSolidWorks("):]
    assert "UnmarkBatch()" in end[: end.index("static void TakeInstanceMutex()")]
    program = _code_of("Program.cs")
    assert "Operations.DetachLive()" in program


def _code_outside_native_check() -> str:
    """The C# without comments, leaving out NativeCheck.cs (checked on its own below)."""
    files = sorted(p for p in build.SOURCE_DIR.glob("*.cs") if p.name != "NativeCheck.cs")
    parts = [p.read_text(encoding="utf-8") for p in files]
    return re.sub(r"//[^\n]*", "", "\n".join(parts))


def test_bridge_never_saves_a_document_or_changes_an_option():
    source = _code()
    for needle in (
        "swSaveAsOptions_Copy", "swOpenDocOptions_ReadOnly", "SolidWorks_PID_", "CoRegisterMessageFilter",
        "[STAThread]", "MsgWaitForMultipleObjectsEx", "KillOnJobClose", "CREATE_SUSPENDED",
        "TerminateJobObject", "sw.Visible = false", "sw.UserControl = false", "FileIdentity(",
        "OpenDocumentFile(",
    ):
        assert needle in source, needle
    for forbidden in (
        ".Save3(", ".Save2(", ".Save(", "GetActiveObject", "SetUserPreference", "CloseAllDocuments",
        "ForceRebuild", "EditUndo", "RunMacro", "CSharpCodeProvider", "Process.Start", "Assembly.Load(",
        "SetCurrentWorkingDirectory", "SetSearchFolders", "ExitApp",
        # measured 2026-10-15: with new documents hidden, component imports faulted and live
        # mode's new part was not the active document (SolidSeas-okg)
        "DocumentVisible(",
    ):
        pattern = (r"(?<!\w)" if forbidden[0].isalpha() else "") + re.escape(forbidden)
        # native_check alone forces a full rebuild, of a part opened read-only in the bridge's own
        # instance: whether SOLIDWORKS regenerates a written part's geometry is what it measures.
        where = _code_outside_native_check() if forbidden == "ForceRebuild" else source
        assert not re.search(pattern, where), forbidden


def test_native_check_rebuilds_and_saves_only_a_copy_to_a_new_file():
    check = re.sub(r"//[^\n]*", "", (build.SOURCE_DIR / "NativeCheck.cs").read_text(encoding="utf-8"))
    assert check.count("ForceRebuild3(false)") == 1
    assert "swSaveAsOptions_Copy" in check and "File.Exists(target) || Directory.Exists(target)" in check
    assert "never saved over its own file" in check
    for forbidden in (".Save3(", ".Save2(", ".Save(", "SetUserPreference", "Select", "live_", "LivePart("):
        assert forbidden not in check, forbidden


def test_a_new_document_hides_the_frame_again_after_it_is_made():
    # Alone (no other SOLIDWORKS running) the frame showed after a new document even though it
    # was hidden right after NewDocument returned (SolidSeas-okg): it is hidden again, settled.
    source = _code()
    made = source[source.index("static ModelDoc2 NewDocumentHidden("):]
    made = made[: made.index("\n        }\n")]
    assert made.index("NewDocument(template") < made.index("finally") < made.index("KeepHiddenSettled(app)")
    # Except a test-session part, made in the person's own session, whose frame is theirs.
    files = [p for p in sorted(build.SOURCE_DIR.glob("*.cs")) if p.name != "TestSession.cs"]
    outside = re.sub(r"//[^\n]*", "", "\n".join(p.read_text(encoding="utf-8") for p in files))
    assert "app.NewDocument(" not in outside.replace("return app.NewDocument(template, 0, 0, 0)", ""), (
        "every new document is made through NewDocumentHidden"
    )

def test_save_copy_writes_export_formats_only_and_never_over_an_open_file():
    source = _code()
    exts = re.search(r"SaveExtensions = \{([^}]*)\}", source).group(1)
    assert ".step" in exts and ".3mf" in exts
    assert not re.search(r"\.sld", exts, re.I), "a native SOLIDWORKS file is never written by save_copy"
    save = source[source.index("static Dictionary<string, object> SaveCopy("):]
    save = save[: save.index("SaveAs3(")]
    assert "FileIdentity(target)" in save and "OpenDocumentFile(identity)" in save
    # A document is opened read-only, always: no ~$ lock file is ever left next to it.
    opened = source[source.index("static Dictionary<string, object> OpenDocument("):]
    opened = opened[: opened.index("OpenDoc6(")]
    assert '!args.Bool("read_only", true)' in opened and '"refused"' in opened


def test_event_handlers_never_wait_for_the_pipe():
    source = _code()
    start = source.index("sealed class PartWatch")
    watch = source[start:source.index("static partial class Operations", start)]
    assert "Output.Event(" in watch and "Output.Send(" not in watch
    output = source[source.index("static class Output"):source.index("sealed class Args")]
    assert "MaxQueuedEvents" in output and "events_lost" in output


def test_the_bridge_ends_its_instance_through_its_job_never_with_exit_app():
    # ExitApp, SOLIDWORKS' own shutdown, rewrites about 230 values under User Interface in the
    # registry the user's session shares; the bridge terminates its job instead.
    source = _code()
    end = source[source.index("public static Dictionary<string, object> EndSolidWorks("):]
    end = end[: end.index("static void TakeInstanceMutex()")]
    assert "process.TerminateJob(EndedExitCode)" in end and '"job_terminated"' in end
    # Its own documents are closed first, and nothing is ever saved.
    assert end.index("Close(handle)") < end.index("TerminateJob(")
    for forbidden in ("ExitApp", "TerminateProcess", "Terminate()", ".Save", "CloseAllDocuments", "CloseDoc"):
        assert forbidden not in end, forbidden
    job = source[source.index("public bool TerminateJob("):]
    assert "Native.TerminateJobObject(job, exitCode)" in job[: job.index("}")]
    # TerminateProcess is left only for a process that never ran: still suspended, outside its job.
    calls = [m.start() for m in re.finditer(r"(?<!extern bool )TerminateProcess\(", source)]
    assert len(calls) == 1 and "AssignProcessToJobObject" in source[calls[0] - 400: calls[0]]
    assert "EndedExitCode = 0x5353" in source


def test_the_window_watch_hides_only_the_journal_box_of_its_own_solidworks():
    code = re.sub(r"//[^\n]*", "", (build.SOURCE_DIR / "WindowWatch.cs").read_text(encoding="utf-8"))
    # A window of another process is never looked at past its process id: collecting the
    # top-level windows reads the id and nothing else, and the rule asks it first.
    collect = code[code.index("bool CollectOwn("):]
    collect = collect[: collect.index("bool CollectChild(")]
    assert "GetWindowThreadProcessId(" in collect
    for call in ("GetClassName", "GetWindowText", "IsWindowVisible", "ShowWindow", "Describe"):
        assert call not in collect, call
    first = r"Classify\(WindowInfo w, Func<int, bool> inJob, int ownPid\)\s*\{\s*"
    assert re.search(first + r"if \(!inJob\(w\.ProcessId\)\) return NotOurs;", code)
    assert "return processId == pid && inJob && !Exited();" in code
    # A program SOLIDWORKS started is one of the job only through a handle of the watch's own,
    # checked to be in the job through it; nothing past the process id is read otherwise.
    members = code[code.index("void OpenMembers("):code.index("void CloseMembers(")]
    assert members.index("Native.OpenProcess(") < members.index("Native.IsProcessInJob(h, job,")
    assert members.index("Native.IsProcessInJob(h, job,") < members.index("members[id] = h;")
    describe = code[code.index("WindowInfo Describe("):code.index("void HideBox(")]
    assert describe.index("if (!InJob(w.ProcessId)) return w;") < describe.index("ClassOf(")
    # Only the journal box of SLDWORKS.exe itself is ever hidden; the activation wizard is reported.
    assert "return w.ProcessId == ownPid && IsJournalBox(w) ? Hide : Leave;" in code
    assert '"swactwiz.exe"' in code
    scan = code[code.index("void Scan("):code.index("WindowInfo Describe(")]
    assert "if (verdict == WindowRule.Hide) HideBox(hwnd, w);" in scan
    assert "verdict == WindowRule.Activation) Report(hwnd, w, verdict);" in scan
    # Hiding is one ShowWindow(SW_HIDE), after checking the window is still its own SOLIDWORKS's.
    assert re.findall(r"(?<!\w)ShowWindow\((\w+), (\w+)\)", code) == [("hwnd", "SW_HIDE")]
    assert "SW_HIDE = 0" in code
    hide = code[code.index("void HideBox("):]
    assert hide.index("OwnProcess(") < hide.index("ShowWindow(")
    # The rule: a visible #32770 titled SOLIDWORKS, holding only static texts and buttons, one of
    # them with the journal message's stable words.
    for needle in ('"#32770"', '"SOLIDWORKS"', '"Static"', '"Button"', '"journal file"',
                   '"could not be created"', '"another session of solidworks"'):
        assert needle in code, needle
    # The hook hears that one process only.
    hook = "SetWinEventHook(EVENT_OBJECT_SHOW, EVENT_OBJECT_SHOW, IntPtr.Zero, onShow, (uint)pid, 0, "
    assert hook + "WINEVENT_OUTOFCONTEXT)" in code
    # No window anywhere in the bridge is clicked, closed, activated, moved or sent a message.
    source = _code()
    for forbidden in (
        "SendMessage", "PostMessage", "SendNotifyMessage", "EndDialog", "DestroyWindow", "CloseWindow",
        "SetForegroundWindow", "BringWindowToTop", "SetActiveWindow", "SetFocus", "SendInput", "keybd_event",
        "mouse_event", "WM_CLOSE", "BM_CLICK", "SetWindowPos", "MoveWindow", "ShowWindowAsync",
        "SetWindowLong", "AttachThreadInput", "SetParent",
    ):
        assert not re.search(r"(?<!\w)" + forbidden, source), forbidden
    # It watches from the moment SOLIDWORKS starts, and knows when it registered.
    ops = source[source.index("static Dictionary<string, object> StartSolidWorks("):]
    assert ops.index("OwnedProcess.Start(exe)") < ops.index("WindowWatch.Start(process)")
    assert ops.index("WindowWatch.Start(process)") < ops.index("Rot.Find(")
    assert ops.index("sw = found as ISldWorks") < ops.index("watch.Registered()")
    # While it waits, the activation wizard ends the wait at once, before the timeout would.
    wait = ops[ops.index("while ((found = Rot.Find(process.Id)) == null)"):]
    wait = wait[: wait.index("sw = found as ISldWorks")]
    assert wait.index("watch.Activation") < wait.index('"solidworks_not_activated"') < wait.index('"timeout"')


def _code_of(name: str) -> str:
    return re.sub(r"//[^\n]*", "", (build.SOURCE_DIR / name).read_text(encoding="utf-8"))


def test_import_file_takes_its_template_from_the_request_and_sets_no_option():
    code = _code_of("Import.cs")
    # Insert: a part made from the request's template, then the file inserted into it.
    insert = code[code.index('if (method == "insert")\n                {'):]
    made = insert.index("NewDocumentHidden(app, template)")
    assert made < insert.index("InsertImportedFeature(path, out errors)")
    # Component: an assembly made from the request's template, the file inserted into it as one
    # component, which is then moved to the origin.
    component = code[code.index('else if (method == "component")\n                {'):]
    made = component.index("NewDocumentHidden(app, template)")
    inserted = component.index("InsertImportedComponent(path, 0, 0, 0, out inserted)")
    moved = component.index("component.Transform2 = (MathTransform)math.CreateTransform(Identity())")
    assert made < inserted < moved
    # Load: File Open's import, with "r", and per-call data only when the request gives it.
    assert 'LoadFile4(path, "r", data, ref errors)' in code
    assert re.findall(r"\.(\w+) = mapConfiguration\.Value", code) == ["MapConfigurationData"]
    # Options are read, never set, and every refusal comes before SOLIDWORKS imports anything.
    assert "GetUserPreferenceToggle(" in code and "GetUserPreferenceIntegerValue(" in code
    assert not re.search(r"SetUserPreference|ShowLevel\s*=[^=]|\.Include\w+\s*=[^=]", code)
    first_call = code.index("NewDocumentHidden(")
    for reason in ("step_assembly", "no_bodies", "interconnect_off", "default_templates_off",
                   "default_template_missing", "several_bodies_as_assembly", "several_bodies_insert",
                   "iges_levels_dialog", "title_open"):
        assert reason in code, reason
    assert code.index('Refuse("step_assembly"') < code.index("ISldWorks app = Require()")
    assert code.index("Refusals(method, format, census") < first_call
    assert code.index("RefuseOpenTitle(app, path, facts)") < first_call
    assert code.index("StepCensus.Read(path)") < code.index("ISldWorks app = Require()")
    # A document made for an import that brought nothing is closed again, unsaved.
    assert "Close(handle)" in code[code.index("catch (Exception)"):]
    # Which dialogs appeared while it ran: the window watch's, from the moment it started.
    assert code.index("watch.DialogsSeen") < first_call
    assert "watch.DialogsSince(seen, 1000)" in code


def test_an_iges_load_is_refused_as_several_bodies_only_through_3d_interconnect():
    # "Import multiple bodies as parts" is for STEP and ACIS files only, the API help says, so an
    # IGES file is refused as several_bodies_as_assembly only while 3D Interconnect maps several
    # bodies to parts. The code, its header comment and the README's row say the same.
    code = _code_of("Import.cs")
    refusals = code[code.index("static void Refusals("): code.index("static void Refuse(")]
    conditions = re.findall(r'if \((.+)\)\s+Refuse\("several_bodies_as_assembly"', refusals)
    assert conditions == ['asParts && format == "step" && !census.OneBody',
                          'asParts && format == "iges" && interconnect']
    as_parts = refusals[refusals.index("bool asParts = "):]
    as_parts = re.sub(r"\s+", " ", as_parts[: as_parts.index(";")])
    assert as_parts.startswith("bool asParts = interconnect ? mapping == ")
    assert as_parts.endswith(': (bool)preferences["swImportMultBodyAsPartData"]')
    header = (build.SOURCE_DIR / "Import.cs").read_text(encoding="utf-8")
    header = " ".join(line.lstrip("/ ") for line in header[: header.index("using System;")].splitlines())
    readme = (SWAPI / "README.md").read_text(encoding="utf-8")
    row = next(line for line in readme.splitlines() if line.startswith("| `several_bodies_as_assembly` |"))
    for text in (header, row):
        assert "is for STEP and ACIS files only" in text
        assert "IGES file, whose bodies are not counted, is refused only" in text


def test_mass_properties_read_the_document_and_set_nothing():
    code = _code_of("Measure.cs")
    for needle in (
        "CreateMassProperty2()", "CreateMassProperty()", "GetExtremePoint(", "Check3", ".Copy()",
        "ApplyTransform(", "GetBodies3(", "GetBodies2(", "Transform2", "GetOverrideOptions()",
        "mass_zero_with_visible_solids",
    ):
        assert needle in code, needle
    for forbidden in ("SelectByID", "SelectedItems", "SetOverride", "EditRebuild", "ForceRebuild",
                      "SetMaterial"):
        assert forbidden not in code, forbidden
    assert not re.search(r"\.(UseSystemUnits|IncludeHiddenBodiesOrComponents|AccuracyLevel)\s*=[^=]", code)
    # Another configuration is shown only to measure it, and the active one is shown again at the end.
    final = code[code.index("finally\n            {\n                if (switched && active != null)"):]
    assert "doc.ShowConfiguration2(active)" in final[: final.index("}")]
    # The window watch keeps every dialog it leaves, the activation wizard's too, for the requests
    # that say which appeared.
    watch = _code_of("WindowWatch.cs").replace("\r\n", "\n")
    kept = watch[watch.index("if (verdict != WindowRule.Hide)\n            {"):]
    assert "leftDialogs.Add(kept)" in kept[: kept.index("\n            }\n")]


def test_build_script_matches_the_build_module():
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    items = (*build.CSC_OPTIONS, *build.FRAMEWORK_REFERENCES, *build.INTEROP_REFERENCES)
    items += ("AssemblyInformationalVersion",)
    for item in items:
        assert item in script, item


@pytest.mark.skipif(POWERSHELL is None, reason="needs Windows PowerShell")
def test_build_script_parses(tmp_path):
    cmd = (
        "$t=$null;$e=$null;"
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{BUILD_SCRIPT}',[ref]$t,[ref]$e);"
        "$e.Count"
    )
    env = dict(os.environ, TEMP=str(tmp_path), TMP=str(tmp_path))
    proc = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", cmd],
        capture_output=True, text=True, env=env, timeout=180, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "0"


# --------------------------------------------------------------------------- finding the program
def test_find_bridge_order(tmp_path, monkeypatch):
    monkeypatch.delenv(bridge.ENV_BRIDGE, raising=False)
    explicit = tmp_path / "explicit.exe"
    assert bridge.find_bridge(explicit) == explicit
    monkeypatch.setenv(bridge.ENV_BRIDGE, str(tmp_path / "from-env.exe"))
    assert bridge.find_bridge() == tmp_path / "from-env.exe"
    monkeypatch.delenv(bridge.ENV_BRIDGE)
    frozen = tmp_path / "app"
    frozen.mkdir()
    (frozen / bridge.EXE_NAME).write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(frozen / "SolidSeasViewer.exe"))
    assert bridge.find_bridge() == (frozen / bridge.EXE_NAME).resolve()
    with pytest.raises(BridgeNotFoundError):
        Bridge(tmp_path / "missing" / bridge.EXE_NAME)


def test_interop_folder_follows_the_installation(tmp_path):
    assert bridge.interop_folder(tmp_path / "SLDWORKS.exe") == tmp_path / "api" / "redist"


# --------------------------------------------------------------------------- the client, on the stand-in
def test_round_trip_and_ready_line():
    with fake() as b:
        assert b.ready["protocol"] == bridge.PROTOCOL and b.ready["apartment"] == "STA"
        assert b.request("hello")["solidworks"] is None
        info = b.request("start_solidworks", {"exe": "C:/fake/SLDWORKS.exe"})
        assert b.request("hello")["solidworks"] == info["pid"]
        assert b.request("sleep", {"ms": 10}) == {"slept_ms": 10}
    assert not b.alive and _gone(info["pid"])


def test_error_reply_raises_and_leaves_the_bridge_running():
    with fake() as b:
        with pytest.raises(BridgeRequestError) as caught:
            b.request("no_such_op")
        assert caught.value.code == "unknown_op" and caught.value.op == "no_such_op"
        with pytest.raises(BridgeRequestError) as caught:
            b.request("solidworks_info")
        assert caught.value.code == "not_started"
        assert b.alive and b.request("hello")


def test_a_stuck_request_ends_the_bridge_and_what_it_started():
    b = fake()
    sw_pid = b.request("start_solidworks")["pid"]
    if WINDOWS:
        assert {b.pid, sw_pid} <= set(b.job_pids())
    start = time.monotonic()
    with pytest.raises(BridgeTimeoutError) as caught:
        b.request("sleep", {"ms": 120_000}, timeout=0.5)
    elapsed = time.monotonic() - start
    assert elapsed < 20, f"the caller waited {elapsed:.1f} s"
    assert caught.value.op == "sleep" and "ended" in str(caught.value)
    assert not b.alive
    assert _gone(sw_pid), "the stand-in SOLIDWORKS outlived its bridge"
    with pytest.raises(BridgeExitedError, match="ended"):
        b.request("hello")
    b.close()


def test_a_crash_fails_the_request_at_once():
    b = fake()
    sw_pid = b.request("start_solidworks")["pid"]
    start = time.monotonic()
    with pytest.raises(BridgeExitedError):
        b.request("exit", {"code": 7}, timeout=60)
    assert time.monotonic() - start < 20
    with pytest.raises(BridgeExitedError):
        b.request("hello")
    b.close()  # ends what the crashed bridge left behind
    assert _gone(sw_pid)


def test_a_bridge_that_never_gets_ready_is_ended():
    start = time.monotonic()
    with pytest.raises(BridgeExitedError) as caught:
        fake({"no_ready": True}, ready_timeout=1.0)
    assert caught.value.code == "start_failed"
    assert time.monotonic() - start < 30


def test_a_bridge_that_exits_at_start_says_why():
    with pytest.raises(BridgeExitedError, match="refusing to start"):
        fake({"exit_at_start": True})


def test_a_bridge_with_another_protocol_is_refused():
    with pytest.raises(bridge.BridgeError) as caught:
        fake({"protocol": 99})
    assert caught.value.code == "protocol_mismatch"


def test_events_reach_the_listener_and_noise_is_ignored():
    seen = []
    threads = set()

    def listener(event):
        threads.add(threading.current_thread().name)
        seen.append(event)

    with fake(on_event=listener) as b:
        b.request("emit")
        b.request("garbage")
        assert b.request("hello")["protocol"] == 1
        assert _until(lambda: len(seen) == 1)
        assert seen == [{"event": "document", "doc": 1, "name": "ModifyNotify"}]
        assert list(b.events) == seen
        assert any("not JSON" in line for line in b.stderr_tail())
    assert threads == {"swbridge-events"}, "listeners never run on the thread that reads replies"


def test_a_slow_listener_never_holds_the_replies():
    # Far more event lines than a pipe holds: a listener called on the reader thread would
    # stop the reading, the stand-in would block writing, and hello would time out.
    release = threading.Event()
    seen = []

    def listener(event):
        if not seen:
            release.wait(60)
        seen.append(event)

    count = 5000
    with fake(on_event=listener) as b:
        b.request("emit", {"count": count}, timeout=60)
        start = time.monotonic()
        assert b.request("hello", timeout=30)["protocol"] == 1
        assert time.monotonic() - start < 10
        assert len(seen) == 0, "the listener is still held"
        release.set()
        assert _until(lambda: len(seen) == count, 30)
        assert [e["data"]["n"] for e in seen] == list(range(count)), "in order, none lost"
        assert b.events_lost == 0


def test_a_listener_too_slow_for_the_backlog_is_told_what_it_missed(monkeypatch):
    from solidseas import helpers

    monkeypatch.setattr(helpers, "_EVENT_BACKLOG", 50)  # the backlog is the shared helper runner's
    release = threading.Event()
    seen = []

    def listener(event):
        if not seen:
            release.wait(60)
        seen.append(event)

    count = 2000
    with fake(on_event=listener) as b:
        b.request("emit", {"count": count}, timeout=60)
        assert b.request("hello", timeout=30)["protocol"] == 1
        release.set()
        assert _until(lambda: any(e["event"] == "events_lost" for e in seen), 30)
        time.sleep(0.2)
        kept = [e["data"]["n"] for e in seen if e["event"] == "document"]
        lost = sum(e["count"] for e in seen if e["event"] == "events_lost")
        assert kept == sorted(kept) and len(kept) + lost == count
        assert 0 < lost == b.events_lost and len(kept) <= 52
        assert all(e.get("where") == "client" for e in seen if e["event"] == "events_lost")


def test_close_ends_a_stuck_bridge_in_bounded_time():
    b = fake()
    sw_pid = b.request("start_solidworks")["pid"]
    errors = []

    def stuck():
        try:
            b.request("sleep", {"ms": 120_000}, timeout=300)
        except Exception as e:
            errors.append(e)

    worker = threading.Thread(target=stuck)
    worker.start()
    time.sleep(0.3)
    start = time.monotonic()
    b.close(timeout=1.0)
    assert time.monotonic() - start < 30
    worker.join(30)
    assert not worker.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], BridgeExitedError)
    assert _gone(sw_pid)


def test_requests_need_a_timeout_the_bridge_accepts():
    with fake() as b:
        for bad in (0, -1, float("nan"), float("inf"), bridge.MAX_TIMEOUT_S + 0.5, 100_000, True):
            with pytest.raises(ValueError, match="timeout"):
                b.request("hello", timeout=bad)
        assert b.alive and b.request("hello", timeout=bridge.MAX_TIMEOUT_S)["protocol"] == 1


def test_a_request_longer_than_the_bridge_reads_is_never_sent():
    with fake() as b:
        with pytest.raises(ValueError, match="at most"):
            b.request("hello", {"x": "a" * bridge.MAX_REQUEST_CHARS})
        # Counted as the bridge counts, in UTF-16 code units: a character beyond U+FFFF is two.
        with pytest.raises(ValueError, match="at most"):
            b.request("hello", {"x": "\U0001f600" * (bridge.MAX_REQUEST_CHARS // 2)})
        assert b.alive and b.request("hello")["protocol"] == 1


def test_a_reply_without_an_id_answers_the_oldest_request():
    # The bridge answers a line it cannot read with an error whose id is null, in turn.
    with fake() as b:
        start = time.monotonic()
        with pytest.raises(BridgeRequestError) as caught:
            b.request("noid", timeout=60)
        assert caught.value.code == "bad_request" and time.monotonic() - start < 10
        assert b.alive and b.request("hello")["protocol"] == 1
        assert any("longer than allowed" in line for line in b.stderr_tail())


def test_import_and_measure_through_the_client(tmp_path):
    assert bridge.DEFAULT_TIMEOUTS["import_file"] == bridge.DEFAULT_TIMEOUTS["mass_properties"] == 600
    step = tmp_path / "o02_boxA.step"
    shutil.copyfile(FIXTURES / "o02_boxA.step", step)
    imported = {"path": str(step), "template": str(MBD_PART_TEMPLATE)}
    with fake() as b:
        with pytest.raises(BridgeRequestError) as caught:
            b.request("import_file", imported)
        assert caught.value.code == "not_started"
        b.request("start_solidworks")
        got = b.request("import_file", imported)
        assert got["method"] == "insert" and got["result_kind"] == "solids"
        assert got["dialog_appeared"] is False
        measured = b.request("mass_properties", {"doc": got["doc"]})
        assert measured["units"] == "SI" and [m["configuration"] for m in measured["measures"]] == ["Default"]
        assert _against_truth(measured["measures"][0], _truth("o02_boxA.SLDPRT"), rel=1e-6, abs_m=1e-7) == []
        component = dict(imported, method="component", template=str(MBD_ASSEMBLY_TEMPLATE))
        assembled = b.request("import_file", component)
        assert assembled["type"] == "assembly" and assembled["component"]["at_origin"] is True
        for bad in (dict(imported, method="copy"), dict(imported, method="load"), dict(imported, colour=1),
                    {"path": str(step), "method": "component"}):
            with pytest.raises(BridgeRequestError) as caught:
                b.request("import_file", bad)
            assert caught.value.code == "invalid_argument", bad
    with fake({"import_fail": [step.name]}) as b:
        b.request("start_solidworks")
        with pytest.raises(BridgeRequestError) as caught:
            b.request("import_file", imported)
        assert caught.value.code == "import_failed"
        assert caught.value.details["error_names"] == ["swGenericError"]
        assert b.alive, "a failed import leaves the bridge and its SOLIDWORKS running"


def test_a_request_held_by_a_dialog_times_out_and_says_which(tmp_path):
    step = tmp_path / "o02_boxA.step"
    shutil.copyfile(FIXTURES / "o02_boxA.step", step)
    question = "Do you want to run Import Diagnostics on the part?"
    earlier = {"event": "window", "action": "left", "kind": "dialog", "hwnd": 41, "class": "#32770",
               "title": "SOLIDWORKS", "text": "Rebuild errors occurred."}
    dialog = {"title": "SOLIDWORKS", "text": question}
    b = fake({"import_dialog": {step.name: dialog}, "start_events": [earlier]})
    try:
        sw_pid = b.request("start_solidworks")["pid"]
        start = time.monotonic()
        with pytest.raises(BridgeTimeoutError) as caught:
            b.request("import_file", {"path": str(step), "template": str(MBD_PART_TEMPLATE)}, timeout=2.0)
        assert time.monotonic() - start < 20
        # Only the dialog that appeared while the request waited, not the one from the start.
        assert [d["hwnd"] for d in caught.value.details["dialogs"]] == [4242]
        assert f"while SOLIDWORKS showed a dialog (SOLIDWORKS: {question})" in str(caught.value)
        assert not b.alive and _gone(sw_pid), "the dialog went with the SOLIDWORKS it belonged to"
    finally:
        b.close()
    with fake() as b:
        with pytest.raises(BridgeTimeoutError) as caught:
            b.request("sleep", {"ms": 60_000}, timeout=0.5)
        assert caught.value.details is None and "dialog" not in str(caught.value)
    dialogs = [{"title": "A", "text": "x"}, {"title": "B"}, {}, {"text": "y"}]
    note = " while SOLIDWORKS showed 4 dialogs (A: x; B; untitled; and 1 more)"
    assert bridge._dialog_note(dialogs) == note
    assert bridge._dialog_note([]) == ""


@pytest.mark.skipif(not WINDOWS, reason="the Job Object is Windows'")
def test_a_bridge_left_outside_its_job_is_ended_at_once(monkeypatch):
    from solidseas import helpers  # the bridge starts on the shared helper runner

    started = []
    popen = helpers.subprocess.Popen

    class Recording(popen):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            started.append(self.pid)

    def refuse(self, pid):
        raise OSError(5, "AssignProcessToJobObject failed (test)")

    monkeypatch.setattr(helpers.subprocess, "Popen", Recording)
    monkeypatch.setattr(bridge._Job, "assign", refuse)
    start = time.monotonic()
    with pytest.raises(bridge.BridgeError) as caught:
        fake()
    assert caught.value.code == "start_failed"
    assert time.monotonic() - start < 10, "it waited for a bridge it never ended"
    assert not _alive(started[0])


@pytest.mark.skipif(not WINDOWS, reason="the Job Object is Windows'")
def test_a_bridge_starts_suspended_and_runs_once_it_is_in_its_job(monkeypatch):
    from solidseas import helpers

    flags = []
    popen = helpers.subprocess.Popen

    class Recording(popen):
        def __init__(self, *args, **kwargs):
            flags.append(kwargs.get("creationflags", 0))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(helpers.subprocess, "Popen", Recording)
    b = fake()
    try:
        assert flags[0] & 0x4, "CREATE_SUSPENDED"
        assert b._job.contains(b._proc.pid)
        assert "solidworks" in b.request("hello"), "it was resumed and answers"
    finally:
        b.close()


# --------------------------------------------------------------------------- batch conversion
PARTS = ("o02_boxA.SLDPRT", "o11_curved.SLDPRT")
JOURNAL = (
    "A journal file could not be created. Auto recover will not work. "
    "Another session of SOLIDWORKS may already be running on this machine."
)


def _inputs(tmp_path: Path, names=PARTS) -> Path:
    folder = tmp_path / "in"
    folder.mkdir()
    for n in names:
        shutil.copyfile(FIXTURES / n, folder / n)
    return folder


def _factory(behaviour=None, made=None):
    def make():
        b = fake(behaviour)
        if made is not None:
            made.append(b)
        return b

    return make


def test_convert_writes_every_format_and_a_report(tmp_path):
    src = _inputs(tmp_path)
    out = tmp_path / "out"
    made = []
    rows = batch.convert([src], out, ["step", "stl", "3mf"], bridge_factory=_factory(made=made))
    assert [(Path(r.input).name, r.format, r.status) for r in rows] == [
        (n, f, "ok") for n in sorted(PARTS) for f in ("step", "stl", "3mf")
    ]
    for r in rows:
        assert Path(r.output).is_file() and Path(r.output).parent == out.resolve()
    assert {r.step_ap for r in rows if r.format == "step"} == {214}
    assert len(made) == 1 and not made[0].alive
    report = batch.write_report(rows, out / "report.tsv")
    lines = report.read_text(encoding="utf-8").splitlines()
    assert lines[0].split("\t") == list(batch.REPORT_COLUMNS) and len(lines) == 7
    with pytest.raises(FileExistsError):
        batch.write_report(rows, report)


def test_convert_keeps_existing_outputs_and_refuses_the_source_folder(tmp_path):
    src = _inputs(tmp_path, PARTS[:1])
    out = tmp_path / "out"
    out.mkdir()
    (out / "o02_boxA.stl").write_bytes(b"mine")
    rows = batch.convert([src], out, ["stl", "x_t"], bridge_factory=_factory())
    assert [(r.format, r.status) for r in rows] == [("stl", "skip"), ("x_t", "ok")]
    assert (out / "o02_boxA.stl").read_bytes() == b"mine"
    rows = batch.convert([src], out, ["stl"], overwrite=True, bridge_factory=_factory())
    assert [(r.format, r.status) for r in rows] == [("stl", "ok")]
    with pytest.raises(ValueError, match="source document"):
        batch.convert([src], src / "exports", ["stl"], bridge_factory=_factory())
    with pytest.raises(ValueError, match="unknown format"):
        batch.convert([src], out, ["dwg"], bridge_factory=_factory())
    rows = batch.convert(
        [src], src / "exports", ["stl"], allow_source_folder=True, bridge_factory=_factory()
    )
    assert [r.status for r in rows] == ["ok"]


def test_convert_reports_a_gltf_written_into_its_folder_and_keeps_it_next_time(tmp_path):
    src = _inputs(tmp_path, PARTS[:1])
    out = tmp_path / "out"
    rows = batch.convert([src], out, ["gltf", "glb"], bridge_factory=_factory())
    assert [(r.format, r.status) for r in rows] == [("gltf", "ok"), ("glb", "ok")]
    assert Path(rows[0].output) == out.resolve() / "o02_boxa" / "o02_boxa.gltf"
    assert Path(rows[0].output).is_file()
    rows = batch.convert([src], out, ["gltf"], bridge_factory=_factory())
    assert [(r.format, r.status) for r in rows] == [("gltf", "skip")], "its folder is the output"
    rows = batch.convert([src], out, ["gltf"], overwrite=True, bridge_factory=_factory())
    assert [(r.format, r.status) for r in rows] == [("gltf", "ok")]


def test_convert_recovers_after_a_stuck_export(tmp_path):
    src = _inputs(tmp_path)
    made = []
    rows = batch.convert(
        [src], tmp_path / "out", ["stl", "step", "3mf"],
        timeouts=batch.Timeouts(export=1.0),
        bridge_factory=_factory({"save_delay": {"o02_boxA.step": 120}}, made),
    )
    got = [(Path(r.input).name, r.format, r.status, r.code) for r in rows]
    assert got == [
        ("o02_boxA.SLDPRT", "stl", "ok", ""),
        ("o02_boxA.SLDPRT", "step", "fail", "timeout"),
        ("o02_boxA.SLDPRT", "3mf", "fail", "not_attempted"),
        ("o11_curved.SLDPRT", "stl", "ok", ""),
        ("o11_curved.SLDPRT", "step", "ok", ""),
        ("o11_curved.SLDPRT", "3mf", "ok", ""),
    ]
    assert len(made) == 2 and not any(b.alive for b in made)
    assert made[0].ended_reason.startswith("save_copy had no reply")


def test_convert_reports_refusals_and_gives_up_after_restarts(tmp_path):
    src = _inputs(tmp_path)
    rows = batch.convert(
        [src], tmp_path / "out", ["stl"],
        bridge_factory=_factory({"open_fail": ["o02_boxA.SLDPRT"], "save_fail": ["o11_curved.stl"]}),
    )
    got = [(r.status, r.code, r.errors) for r in rows]
    assert got == [("fail", "open_failed", 2), ("fail", "save_failed", 1)]
    assert rows[0].message.endswith("(swFileNotFoundError)")
    made = []
    rows = batch.convert(
        [src], tmp_path / "out2", ["stl"], timeouts=batch.Timeouts(open=0.5), max_restarts=0,
        bridge_factory=_factory({"open_delay": {"o02_boxA.SLDPRT": 120, "o11_curved.SLDPRT": 120}}, made),
    )
    assert [(r.status, r.code) for r in rows] == [("fail", "timeout"), ("fail", "not_attempted")]
    assert len(made) == 1
    rows = batch.convert([src], tmp_path / "out3", ["stl"], bridge_factory=_factory({"start_fail": True}))
    assert [(r.status, r.code) for r in rows] == [("fail", "start_failed"), ("fail", "start_failed")]


def test_convert_never_writes_one_output_twice(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    shutil.copyfile(FIXTURES / "o02_boxA.SLDPRT", a / "part.SLDPRT")
    shutil.copyfile(FIXTURES / "o11_curved.SLDPRT", b / "part.SLDPRT")
    rows = batch.convert([a, b], tmp_path / "out", ["stl"], bridge_factory=_factory())
    assert [(r.status, r.code) for r in rows] == [("ok", ""), ("fail", "refused")]


def test_timeouts_are_checked_before_anything_starts():
    for bad in (0, -5, float("nan"), float("inf"), bridge.MAX_TIMEOUT_S * 2, True, "60"):
        with pytest.raises(ValueError, match="timeout"):
            batch.Timeouts(open=bad)
    assert batch.Timeouts(export=bridge.MAX_TIMEOUT_S).export == bridge.MAX_TIMEOUT_S


def test_convert_allows_a_network_path_only_where_it_was_named(tmp_path):
    assert batch._network("\\\\server\\share\\in\\part.SLDPRT")
    assert batch._network("//server/share/part.SLDPRT")
    assert not batch._network("C:\\in\\part.SLDPRT") and not batch._network(tmp_path / "part.SLDPRT")
    calls = []

    def make():
        b = fake()
        send = b.request

        def request(op, args=None, **kwargs):
            calls.append((op, dict(args or {})))
            return send(op, args, **kwargs)

        b.request = request
        return b

    rows = batch.convert([_inputs(tmp_path, PARTS[:1])], tmp_path / "out", ["stl"], bridge_factory=make)
    assert [r.status for r in rows] == ["ok"]
    sent = {op: args for op, args in calls if op in ("open_document", "save_copy")}
    assert sent["open_document"]["allow_network"] is False and sent["open_document"]["read_only"] is True
    assert sent["save_copy"]["allow_network"] is False


def test_convert_logs_the_windows_the_bridge_hid_or_left(tmp_path):
    events = [
        {"event": "window", "action": "hidden", "kind": "journal_box", "hwnd": 66, "class": "#32770",
         "title": "SOLIDWORKS", "text": JOURNAL, "again": False},
        {"event": "window", "action": "hidden", "kind": "journal_box", "hwnd": 66, "class": "#32770",
         "title": "SOLIDWORKS", "text": JOURNAL, "again": True},
        {"event": "window", "action": "left", "kind": "dialog", "hwnd": 67, "class": "#32770",
         "title": "SOLIDWORKS", "text": "Rebuild errors occurred."},
        {"event": "document", "doc": 1, "name": "ModifyNotify"},
    ]
    log = []
    made = []
    rows = batch.convert(
        [_inputs(tmp_path, PARTS[:1])], tmp_path / "out", ["stl"], log=log.append,
        bridge_factory=_factory({"start_events": events}, made),
    )
    assert [r.status for r in rows] == ["ok"]
    pid = made[0].events[0]["pid"]
    windows = [m for m in log if "PID" in m and "SOLIDWORKS (" in m]
    assert windows == [
        f"hid the journal file message box of SolidSeas' SOLIDWORKS (PID {pid})",
        f"hid again the journal file message box of SolidSeas' SOLIDWORKS (PID {pid})",
        f"SolidSeas' SOLIDWORKS (PID {pid}) shows a dialog, left as it is: "
        "SOLIDWORKS: Rebuild errors occurred.; a request it holds up ends at its timeout",
    ]
    # A listener the caller gave its bridge is kept.
    seen = []
    log = []
    again = tmp_path / "again"
    again.mkdir()
    batch.convert(
        [_inputs(again, PARTS[:1])], tmp_path / "out2", ["stl"], log=log.append,
        bridge_factory=lambda: fake({"start_events": events}, on_event=seen.append),
    )
    assert len(seen) == len(events) and not any("journal" in m for m in log)
    assert batch._window_message({"event": "document"}) is None and batch._window_message("noise") is None


def test_the_log_names_product_activation_and_the_program_a_dialog_belongs_to():
    asking = {"event": "window", "action": "left", "kind": "activation", "pid": 7, "process": "swactwiz.exe",
              "title": "SOLIDWORKS Product Activation", "text": "You must activate your installation."}
    assert batch._window_message(asking) == (
        "SOLIDWORKS Product Activation (PID 7) is asking: SOLIDWORKS Product Activation: "
        "You must activate your installation.; SolidSeas never answers it, and SOLIDWORKS does not "
        "start until it is activated"
    )
    other = dict(asking, kind="dialog", process="helper.exe", title="Helper", text="Something happened.")
    assert batch._window_message(other) == (
        "helper.exe (PID 7), which SolidSeas' SOLIDWORKS started, shows a dialog, left as it is: Helper: "
        "Something happened.; a request it holds up ends at its timeout"
    )
    assert batch._window_message(dict(other, process="SLDWORKS.exe")).startswith(
        "SolidSeas' SOLIDWORKS (PID 7) shows a dialog"
    )


def test_convert_does_not_start_solidworks_again_while_it_needs_activation(tmp_path):
    made = []
    log = []
    rows = batch.convert(
        [_inputs(tmp_path)], tmp_path / "out", ["stl", "step"], log=log.append,
        bridge_factory=_factory({"start_fail": "solidworks_not_activated"}, made),
    )
    assert [(Path(r.input).name, r.format, r.status, r.code) for r in rows] == [
        ("o02_boxA.SLDPRT", "*", "fail", "solidworks_not_activated"),
        ("o11_curved.SLDPRT", "*", "fail", "not_attempted"),
    ]
    assert rows[1].message == "not attempted: SOLIDWORKS needs product activation on this PC"
    assert len(made) == 1, "starting SOLIDWORKS again would show its activation wizard again"
    assert "SOLIDWORKS needs product activation on this PC; not starting it again in this run" in log


def test_off_hours_window():
    window = batch.OffHours()
    assert str(window) == "02:00 to 07:00" and window == batch.OffHours.parse("02:00-07:00")
    day = dt.datetime(2026, 10, 5)
    assert window.contains(day.replace(hour=2)) and window.contains(day.replace(hour=6, minute=59, second=59))
    assert not window.contains(day.replace(hour=7)) and not window.contains(day.replace(hour=1, minute=59))
    assert window.seconds_until(day.replace(hour=3)) == 0
    assert window.seconds_until(day.replace(hour=1, minute=30)) == 1800
    assert window.seconds_until(day.replace(hour=7)) == 19 * 3600
    night = batch.OffHours.parse(" 22:30 - 6:00 ")
    assert night == batch.OffHours(dt.time(22, 30), dt.time(6, 0))
    assert night.contains(day.replace(hour=23)) and night.contains(day.replace(hour=5, minute=59))
    assert not night.contains(day.replace(hour=6)) and not night.contains(day.replace(hour=22, minute=29))
    assert night.seconds_until(day.replace(hour=12)) == 10.5 * 3600
    for bad in ("", "2-7", "02:00", "24:00-07:00", "02:60-07:00", "02:00-02:00", "02:00 07:00", "soon"):
        with pytest.raises(ValueError):
            batch.OffHours.parse(bad)
    with pytest.raises(ValueError):
        batch.OffHours(dt.time(2), dt.time(2))
    with pytest.raises(ValueError):
        batch.OffHours(dt.time(2, tzinfo=dt.UTC), dt.time(7))


def test_convert_starts_solidworks_only_off_hours(tmp_path, monkeypatch):
    clock = [dt.datetime(2026, 10, 5, 23, 30)]
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        clock[0] += dt.timedelta(seconds=seconds)

    monkeypatch.setattr(batch, "_now", lambda: clock[0])
    monkeypatch.setattr(batch, "_sleep", sleep)
    started = []

    def make(behaviour=None, later=None):
        def factory():
            started.append(clock[0])
            b = fake(behaviour)
            if later is not None:
                clock[0] = clock[0].replace(hour=later.hour, minute=later.minute)
            return b

        return factory

    src = _inputs(tmp_path)
    log = []
    rows = batch.convert(
        [src], tmp_path / "o1", ["stl"], off_hours=batch.OffHours(), bridge_factory=make(), log=log.append,
    )
    assert [r.status for r in rows] == ["ok", "ok"]
    assert started == [dt.datetime(2026, 10, 6, 2, 0)], "one start, when the window opened"
    assert max(slept) <= batch._WAIT_STEP_S and sum(slept) == 2.5 * 3600
    assert log[0].startswith("waiting 2 h 30 min for the off-hours window (02:00 to 07:00)")
    day = dt.datetime(2026, 10, 6)
    # Inside the window, or for a job the user started, it starts at once.
    for when, window in ((day.replace(hour=3), batch.OffHours()), (day.replace(hour=12), None)):
        clock[0] = when
        started.clear()
        slept.clear()
        rows = batch.convert(
            [src], tmp_path / f"o{when.hour}", ["stl"], off_hours=window, bridge_factory=make(),
        )
        assert [r.status for r in rows] == ["ok", "ok"] and started == [when] and slept == []
    # A restart after a timeout, once the window has closed, waits for the next one.
    clock[0] = dt.datetime(2026, 10, 6, 6, 59)
    started.clear()
    rows = batch.convert(
        [src], tmp_path / "o5", ["stl"], off_hours=batch.OffHours(), timeouts=batch.Timeouts(export=1.0),
        bridge_factory=make({"save_delay": {"o02_boxA.stl": 120}}, later=dt.time(7, 30)),
    )
    assert [(r.status, r.code) for r in rows] == [("fail", "timeout"), ("ok", "")]
    assert started == [dt.datetime(2026, 10, 6, 6, 59), dt.datetime(2026, 10, 7, 2, 0)]


def test_convert_ends_solidworks_when_the_off_hours_window_closes(tmp_path, monkeypatch):
    # Started alone at 06:58, SolidSeas' instance holds the journal file; a SOLIDWORKS the user
    # starts at 07:00 would be the second session, without auto-recover. So the instance never
    # runs past the window: the export in hand finishes, the document is closed, SOLIDWORKS is
    # ended through its job, and the rest of that document waits for the next window.
    clock = [dt.datetime(2026, 10, 6, 6, 58)]
    monkeypatch.setattr(batch, "_now", lambda: clock[0])
    monkeypatch.setattr(batch, "_sleep", lambda s: clock.__setitem__(0, clock[0] + dt.timedelta(seconds=s)))
    calls = []
    made = []

    def make():
        b = fake()
        made.append(b)
        send = b.request

        def request(op, args=None, **kwargs):
            calls.append((clock[0].strftime("%d %H:%M"), op, Path((args or {}).get("path", "")).name))
            result = send(op, args, **kwargs)
            if op == "save_copy":
                clock[0] += dt.timedelta(minutes=5)  # each export takes five minutes
            return result

        b.request = request
        return b

    log = []
    rows = batch.convert(
        [_inputs(tmp_path)], tmp_path / "out", ["stl", "step"], off_hours=batch.OffHours(),
        bridge_factory=make, log=log.append, max_restarts=0,
    )
    assert [(Path(r.input).name, r.format, r.status) for r in rows] == [
        ("o02_boxA.SLDPRT", "stl", "ok"), ("o02_boxA.SLDPRT", "step", "ok"),
        ("o11_curved.SLDPRT", "stl", "ok"), ("o11_curved.SLDPRT", "step", "ok"),
    ]
    assert calls == [
        ("06 06:58", "start_solidworks", ""), ("06 06:58", "open_document", "o02_boxA.SLDPRT"),
        ("06 06:58", "save_copy", "o02_boxA.stl"),
        ("06 07:03", "close_document", ""), ("06 07:03", "exit_solidworks", ""), ("06 07:03", "shutdown", ""),
        ("07 02:00", "start_solidworks", ""), ("07 02:00", "open_document", "o02_boxA.SLDPRT"),
        ("07 02:00", "save_copy", "o02_boxA.step"), ("07 02:05", "close_document", ""),
        ("07 02:05", "open_document", "o11_curved.SLDPRT"), ("07 02:05", "save_copy", "o11_curved.stl"),
        ("07 02:10", "save_copy", "o11_curved.step"), ("07 02:15", "close_document", ""),
        ("07 02:15", "exit_solidworks", ""), ("07 02:15", "shutdown", ""),
    ]
    assert len(made) == 2 and not any(b.alive for b in made), "the pause is not a restart, and both ended"
    closing = ("the off-hours window (02:00 to 07:00) has closed; "
               "ending SolidSeas' SOLIDWORKS until it opens again")
    assert log.count(closing) == 1, log
    ended = [m for m in log if m.startswith("SolidSeas' SOLIDWORKS ended:")]
    assert len(ended) == 2 and all("job_terminated" in m and "exit code 21331" in m for m in ended), log
    assert any(m.startswith("waiting 18 h 57 min for the off-hours window") for m in log)
    # Between documents too: the second document waits when the first ends after the window.
    clock[0] = dt.datetime(2026, 10, 6, 6, 58)
    calls.clear()
    made.clear()
    (tmp_path / "again").mkdir()
    (tmp_path / "mine").mkdir()
    rows = batch.convert(
        [_inputs(tmp_path / "again", PARTS)], tmp_path / "out2", ["stl"], off_hours=batch.OffHours(),
        bridge_factory=make,
    )
    assert [r.status for r in rows] == ["ok", "ok"] and len(made) == 2
    assert [c for c in calls if c[1] in ("start_solidworks", "exit_solidworks")] == [
        ("06 06:58", "start_solidworks", ""), ("06 07:03", "exit_solidworks", ""),
        ("07 02:00", "start_solidworks", ""), ("07 02:05", "exit_solidworks", ""),
    ]
    # A job the user started runs to its end, whatever the time.
    clock[0] = dt.datetime(2026, 10, 6, 6, 58)
    made.clear()
    rows = batch.convert(
        [_inputs(tmp_path / "mine", PARTS)], tmp_path / "out3", ["stl", "step"], bridge_factory=make,
    )
    assert [r.status for r in rows] == ["ok"] * 4 and len(made) == 1


def test_command_line_off_hours(tmp_path, monkeypatch):
    from solidseas.swapi import __main__ as cli

    got = {}

    def convert(inputs, output, formats, **kwargs):
        got.clear()
        got.update(kwargs)
        Path(output).mkdir(parents=True, exist_ok=True)
        return []

    monkeypatch.setattr(batch, "convert", convert)
    src = _inputs(tmp_path, PARTS[:1])
    assert cli.main(["convert", str(src), "-o", str(tmp_path / "o1")]) == 0
    assert got["off_hours"] is None, "a job you start runs at once"
    assert cli.main(["convert", str(src), "-o", str(tmp_path / "o2"), "--off-hours"]) == 0
    assert got["off_hours"] == batch.OffHours()
    assert cli.main(["convert", str(src), "-o", str(tmp_path / "o3"), "--off-hours", "22:00-05:30"]) == 0
    assert got["off_hours"] == batch.OffHours(dt.time(22), dt.time(5, 30))
    for bad in ("soon", "02:00-02:00", "24:00-07:00"):
        with pytest.raises(SystemExit) as caught:
            cli.main(["convert", str(src), "-o", str(tmp_path / "o4"), "--off-hours", bad])
        assert caught.value.code == 2


def test_find_documents(tmp_path):
    src = _inputs(tmp_path)
    (src / "~$o02_boxA.SLDPRT").write_bytes(b"lock")
    (src / "sub").mkdir()
    shutil.copyfile(FIXTURES / "o08_asm_2x_boxA.SLDASM", src / "sub" / "asm.SLDASM")
    assert [p.name for p in batch.find_documents([src])] == list(PARTS)
    assert sorted(p.name for p in batch.find_documents([src], recurse=True)) == sorted([*PARTS, "asm.SLDASM"])
    with pytest.raises(ValueError):
        batch.find_documents([FIXTURES / "o02_boxA.step"])
    with pytest.raises(FileNotFoundError):
        batch.find_documents([tmp_path / "nothing"])


def test_report_never_hands_a_spreadsheet_a_formula(tmp_path):
    row = batch.ConversionRow("=cmd|' /c calc'!A1", "fail", "*", message="+SUM(1)\tand\nmore")
    text = batch.write_report([row], tmp_path / "r.tsv").read_text(encoding="utf-8")
    cells = text.splitlines()[1].split("\t")
    assert cells[0].startswith("'=") and cells[-1] == "'+SUM(1) and more"


def test_command_line_convert(tmp_path, monkeypatch, capsys):
    from solidseas.swapi import __main__ as cli

    monkeypatch.setattr(batch, "Bridge", lambda *a, **k: fake())
    src = _inputs(tmp_path, PARTS[:1])
    out = tmp_path / "out"
    assert cli.main(["convert", str(src), "-o", str(out), "--format", "stl,x_t", "--json"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [(r["format"], r["status"]) for r in rows] == [("stl", "ok"), ("x_t", "ok")]
    assert (out / "report.tsv").is_file()
    assert cli.main(["convert", str(src), "-o", str(out)]) == 3  # the report exists
    assert cli.main(["convert", str(src), "-o", str(src)]) == 2
    monkeypatch.setattr(batch, "Bridge", lambda *a, **k: fake({"save_fail": ["o02_boxA.stl"]}))
    assert cli.main(["convert", str(src), "-o", str(tmp_path / "o2"), "--format", "stl"]) == 4
    for option in ("--open-timeout", "--export-timeout"):
        for bad in ("0", "-1", "nan", "100000", "soon"):
            with pytest.raises(SystemExit) as caught:
                cli.main(["convert", str(src), "-o", str(tmp_path / "o3"), option, bad])
            assert caught.value.code == 2
    assert not (tmp_path / "o3").exists()


# --------------------------------------------------------------------------- measures and the ground truth
MBD_PART_TEMPLATE = Path(
    "C:/ProgramData/SolidWorks/SOLIDWORKS 2024/templates/MBD/part 0051mm to 0250mm.prtdot"
)
GROUND_TRUTH = json.loads((FIXTURES / "ground_truth.json").read_text(encoding="utf-8"))


def _truth(name: str, configuration: str = "Default") -> dict:
    """What the fixture kit measured of a fixture's configuration with SOLIDWORKS 2024."""
    return GROUND_TRUTH[name]["api"]["configurations"][configuration]


def _against_truth(
    measure: dict, truth: dict, *, rel: float = 1e-9, abs_m: float = 1e-12, mass: bool = False
) -> list:
    """What in one of ``mass_properties``' measures differs from the ground truth, as lines.

    Volume and area are compared relative to the truth (``rel``), the centre of
    mass and the box in metres (``abs_m``), and the mass too when ``mass`` (it
    depends on the material, which an import takes from its template). A truth
    without a volume (a part with no body) wants no valid mass.
    """
    problems = []
    got = measure.get("mass") or {}

    def near(a, b, tolerance) -> bool:
        return isinstance(a, (int, float)) and not isinstance(a, bool) and abs(a - b) <= tolerance

    if "volume_m3" in truth:
        for key in ("volume_m3", "surface_area_m2") + (("mass_kg",) if mass else ()):
            if not near(got.get(key), truth[key], rel * abs(truth[key])):
                problems.append(f"{key} {got.get(key)!r}, truth {truth[key]!r}")
        com = got.get("center_of_mass_m") or []
        want = truth["center_of_mass_m"]
        if len(com) != 3 or not all(near(a, b, abs_m) for a, b in zip(com, want, strict=True)):
            problems.append(f"center_of_mass_m {com!r}, truth {truth['center_of_mass_m']!r}")
        if got.get("valid") is not True:
            problems.append(f"the mass is not valid: {measure.get('warnings')}")
    elif got.get("valid") is not False:
        problems.append("a mass was given for a document with no volume")
    if "solid_bodies" in truth and measure.get("solid_bodies") != truth["solid_bodies"]:
        problems.append(f"solid_bodies {measure.get('solid_bodies')!r}, truth {truth['solid_bodies']!r}")
    if truth.get("solid_bodies", 1) and truth.get("bounding_box_m") is not None:
        box = measure.get("bbox_m") or []
        want = truth["bounding_box_m"]
        if len(box) != 6 or not all(near(a, b, abs_m) for a, b in zip(box, want, strict=True)):
            problems.append(f"bbox_m {box!r}, truth {truth['bounding_box_m']!r}")
    return problems


def _like(truth: dict) -> dict:
    """The measure ``mass_properties`` would give for a truth entry, for the comparison's own test."""
    volume = truth.get("volume_m3")
    mass = {"api": "IMassProperty2", "valid": volume is not None}
    if volume is not None:
        mass.update(volume_m3=volume, surface_area_m2=truth["surface_area_m2"], mass_kg=truth["mass_kg"],
                    center_of_mass_m=list(truth["center_of_mass_m"]))
    box = list(truth["bounding_box_m"])
    return {"solid_bodies": truth.get("solid_bodies", 1), "bbox_m": box, "mass": mass}


def test_measures_are_compared_with_the_ground_truth():
    for name, configuration in (("o02_boxA.SLDPRT", "Default"), ("o13_two_geometry_configs.SLDPRT", "Tall"),
                                ("o08_asm_2x_boxA.SLDASM", "Default"), ("o01_empty.SLDPRT", "Default")):
        truth = _truth(name, configuration)
        assert _against_truth(_like(truth), truth, mass=True) == [], name
    tall = _truth("o13_two_geometry_configs.SLDPRT", "Tall")
    default = _truth("o13_two_geometry_configs.SLDPRT")
    problems = _against_truth(_like(tall), default)
    assert [p.split()[0] for p in problems] == ["volume_m3", "surface_area_m2", "center_of_mass_m", "bbox_m"]
    near = _like(default)
    near["mass"]["volume_m3"] *= 1 + 1e-7
    near["bbox_m"][5] += 5e-8
    assert len(_against_truth(near, default)) == 2
    assert _against_truth(near, default, rel=1e-6, abs_m=1e-7) == []
    zero = _like(default)
    zero["mass"].update(volume_m3=0.0, valid=False)
    assert _against_truth(zero, default)[0].startswith("volume_m3 0.0")
    assert _against_truth(_like(default), _truth("o01_empty.SLDPRT")) == [
        "a mass was given for a document with no volume", "solid_bodies 1, truth 0",
    ]


# --------------------------------------------------------------------------- the real bridge (opt-in)
def _real_bridge_reason() -> str | None:
    if not WINDOWS:
        return "the bridge runs on Windows"
    if os.environ.get(bridge.ENV_BRIDGE):
        return None
    if os.environ.get("SOLIDSEAS_SWAPI_BUILD_CHECK") != "1":
        return "set SOLIDSEAS_SWAPI_BUILD_CHECK=1 on a machine with SOLIDWORKS to build and run the bridge"
    if not build.default_csc().is_file() or not bridge.interop_folder().is_dir():
        return "needs csc.exe and the SOLIDWORKS interop assemblies"
    return None


REAL_REASON = _real_bridge_reason()
real = pytest.mark.skipif(REAL_REASON is not None, reason=REAL_REASON or "")


@pytest.fixture(scope="module")
def real_exe(tmp_path_factory):
    given = os.environ.get(bridge.ENV_BRIDGE)
    if given:
        return Path(given)
    return build.build_bridge(tmp_path_factory.mktemp("swbridge"))


@real
def test_real_bridge_speaks_the_protocol(real_exe):
    with Bridge(real_exe, test_ops=True) as b:
        assert b.ready["apartment"] == "STA" and b.ready["message_filter"] is True
        assert b.ready["in_job"] is True and b.ready["test_ops"] is True
        hello = b.request("hello")
        assert hello["solidworks"] is None and "start_solidworks" in hello["ops"]
        assert re.fullmatch(r"\d+\.\d+\.\d+", hello["bridge_version"])
        with pytest.raises(BridgeRequestError) as caught:
            b.request("hello", {"unexpected": 1})
        assert caught.value.code == "invalid_argument"
        with pytest.raises(BridgeRequestError) as caught:
            b.request("open_document", {"path": "relative.sldprt"})
        assert caught.value.code in ("not_started", "invalid_argument")
        with pytest.raises(BridgeRequestError) as caught:
            b.request("start_solidworks", {"exe": str(Path(sys.executable))})
        assert caught.value.code == "invalid_argument"  # only SLDWORKS.exe is ever started
        assert b.request("sleep", {"ms": 50}) == {"slept_ms": 50}
    assert not b.alive
    with Bridge(real_exe) as b:
        assert "sleep" not in b.ready["ops"] and b.ready["test_ops"] is False


@real
def test_real_bridge_takes_only_paths_on_a_drive(real_exe, tmp_path, monkeypatch):
    # The bridge's working directory is this process's: a relative path would land in it.
    monkeypatch.chdir(tmp_path)
    with Bridge(real_exe) as b:
        for exe in (
            "C:SLDWORKS.exe", "\\SLDWORKS.exe", "/SLDWORKS.exe", "SLDWORKS.exe", "sub\\SLDWORKS.exe",
            "\\\\localhost\\c$\\SLDWORKS.exe", "//localhost/c$/SLDWORKS.exe", "\\\\?\\C:\\SLDWORKS.exe",
            "\\\\.\\C:\\SLDWORKS.exe", "C:\\x\\SLDWORKS.exe:stream",
        ):
            with pytest.raises(BridgeRequestError) as caught:
                b.request("start_solidworks", {"exe": exe})
            assert caught.value.code == "invalid_argument", exe
        # A full path on a drive is taken, and gets as far as looking for the file.
        with pytest.raises(BridgeRequestError) as caught:
            b.request("start_solidworks", {"exe": str(tmp_path / "SLDWORKS.exe")})
        assert caught.value.code == "not_found"


@real
def test_real_bridge_and_client_agree_on_the_longest_request(real_exe, monkeypatch):
    with Bridge(real_exe) as b:
        empty = {"id": 1, "op": "hello", "timeout_s": 15.0, "args": {"x": ""}}
        room = bridge.MAX_REQUEST_CHARS - len(json.dumps(empty, ensure_ascii=False))
        # The longest line the client sends is read whole: the bridge objects to its argument.
        with pytest.raises(BridgeRequestError) as caught:
            b.request("hello", {"x": "a" * room})
        assert caught.value.code == "invalid_argument"
        with pytest.raises(ValueError):
            b.request("hello", {"x": "a" * (room + 1)})
        # A line the bridge cannot read is answered without an id; that answers the request.
        monkeypatch.setattr(bridge, "MAX_REQUEST_CHARS", 4 * bridge.MAX_REQUEST_CHARS)
        start = time.monotonic()
        with pytest.raises(BridgeRequestError) as caught:
            b.request("hello", {"x": "a" * 2 * room}, timeout=60)
        assert caught.value.code == "bad_request" and time.monotonic() - start < 10
        assert b.alive and b.request("hello")["solidworks"] is None


@real
def test_real_bridge_never_waits_for_a_reader_to_queue_an_event(real_exe):
    # The protocol by hand, so that nothing reads standard output while the events are queued:
    # a notification handler that waited for the pipe would hold SOLIDWORKS with it.
    command = [str(real_exe), "--interop", str(bridge.interop_folder()), "--test-ops"]
    proc = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        assert json.loads(proc.stdout.readline())["event"] == "ready"
        count = 20000
        for rid, op, args in ((1, "emit", {"count": count}), (2, "hello", {})):
            request = {"id": rid, "op": op, "args": args, "timeout_s": 60}
            proc.stdin.write((json.dumps(request) + "\n").encode())
        proc.stdin.flush()
        time.sleep(3)  # nobody reads; the pipe fills long before the burst ends
        events = lost = 0
        replies = {}
        while len(replies) < 2:
            line = json.loads(proc.stdout.readline())
            if "id" in line:
                replies[line["id"]] = line
            elif line["event"] == "test":
                events += 1
            elif line["event"] == "events_lost":
                lost += line["count"]
        emitted = replies[1]["result"]
        assert emitted["emitted"] == count and emitted["ms"] < 2500, emitted
        assert lost > 0 and events + lost == count
        assert replies[2]["result"]["events_lost"] == lost
    finally:
        proc.kill()
        proc.wait(30)


STEP_HEAD = "ISO-10303-21;\nHEADER;\nFILE_NAME('PRODUCT(x)','',(''),(''),'','','');\nENDSEC;\nDATA;\n"
STEP_TAIL = "ENDSEC;\nEND-ISO-10303-21;\n"
ONE_PRODUCT = "#1=PRODUCT('a','a','',(#9));\n"
ONE_SOLID = "#2=MANIFOLD_SOLID_BREP('',#3);\n#3=CLOSED_SHELL('',());\n"


@real
def test_real_bridge_checks_imports_and_measures_before_solidworks(real_exe, tmp_path):
    template = tmp_path / "part.prtdot"  # only its name and existence are looked at before SOLIDWORKS
    template.write_bytes(b"not a template")
    assembly_template = tmp_path / "assembly.asmdot"
    assembly_template.write_bytes(b"not a template")
    step = tmp_path / "o02_boxA.step"
    shutil.copyfile(FIXTURES / "o02_boxA.step", step)

    def write(name: str, data: str) -> str:
        (tmp_path / name).write_text(data, encoding="ascii")
        return str(tmp_path / name)

    files = {
        "assembly": write("assembly.step", STEP_HEAD + ONE_PRODUCT + "#4=PRODUCT('b','b','',(#9));\n"
                          + ONE_SOLID + STEP_TAIL),
        "linked": write("linked.stp", STEP_HEAD + ONE_PRODUCT + ONE_SOLID
                        + "#5=NEXT_ASSEMBLY_USAGE_OCCURRENCE('','','',#1,#1,$);\n" + STEP_TAIL),
        # The words in a string, a comment and a header record are not entities.
        "quoted": write("quoted.step", STEP_HEAD + "/* PRODUCT( MAPPED_ITEM( */\n#1=PRODUCT('it''s PRODUCT(',"
                        "'a','',(#9));\n" + ONE_SOLID + STEP_TAIL),
        "lower": write("lower.step", STEP_HEAD + ONE_PRODUCT + "#2=manifold_solid_brep ('',#3);\n"
                       "#3=CLOSED_SHELL('',());\n#6 = product ('b','b','',(#9));\n" + STEP_TAIL),
        "empty": write("empty.step", STEP_HEAD + ONE_PRODUCT + STEP_TAIL),
        "not_step": write("not.step", "solid\n"),
    }
    insert = {"template": str(template)}
    component = {"method": "component", "template": str(assembly_template)}
    with Bridge(real_exe) as b:
        def refused(args, code="refused"):
            with pytest.raises(BridgeRequestError) as caught:
                b.request("import_file", args)
            assert caught.value.code == code, (args, caught.value)
            return caught.value

        got = refused(dict(insert, path=files["assembly"]))
        assert got.details["reason"] == "step_assembly" and got.details["step_census"]["products"] == 2
        assert "use method component" in str(got)
        # The component method takes an assembly, so the census lets it through to SOLIDWORKS.
        for name in ("assembly", "linked"):
            refused(dict(component, path=files[name]), "not_started")
        assert refused(dict(component, path=files["empty"])).details["reason"] == "no_bodies"
        no_template = {"path": str(step), "method": "component"}
        for bad in (no_template, dict(component, path=str(step), template=str(template))):
            refused(bad, "invalid_argument")
        assert refused(dict(insert, path=files["linked"])).details["step_census"]["assembly_links"] == 1
        assert refused({"path": files["lower"], "method": "load"}).details["step_census"]["products"] == 2
        got = refused({"path": files["empty"], "method": "load"})
        assert got.details["reason"] == "no_bodies" and got.details["step_census"]["solids"] == 0
        refused(dict(insert, path=files["not_step"]), "invalid_argument")
        # What passes the census goes as far as asking for SOLIDWORKS.
        loaded = {"path": str(step), "method": "load"}
        for args in (dict(insert, path=files["quoted"]), dict(insert, path=str(step)), loaded,
                     dict(loaded, map_configuration_data=False)):
            refused(args, "not_started")
        for bad in (
            {"path": str(step)}, dict(insert, path=str(step), method="copy"),
            dict(insert, path=str(step), colour=1),
            {"path": str(step), "method": "load", "template": str(template)},
            dict(insert, path=str(step), map_configuration_data=True),
            {"path": str(step), "method": "load", "map_configuration_data": "yes"},
            dict(insert, path=str(FIXTURES / "o02_boxA.SLDPRT")), dict(insert, path="o02_boxA.step"),
            dict(insert, path="\\\\localhost\\c$\\o02_boxA.step"),
            {"path": str(step), "template": str(tmp_path / "a.asmdot")},
        ):
            refused(bad, "invalid_argument")
        refused(dict(insert, path=str(tmp_path / "missing.step")), "not_found")
        refused({"path": str(step), "template": str(tmp_path / "missing.prtdot")}, "not_found")
        for args, code in (
            ({"doc": 1}, "not_started"), ({"doc": 1, "configuration": ""}, "invalid_argument"),
            ({"doc": 1, "configuration": "Default", "all_configurations": True}, "invalid_argument"),
            ({"doc": 1, "max_configurations": 0}, "invalid_argument"),
            ({"doc": 1, "colour": 1}, "invalid_argument"),
            ({"doc": 0}, "not_started"),
        ):
            with pytest.raises(BridgeRequestError) as caught:
                b.request("mass_properties", args)
            assert caught.value.code == code, args


@real
def test_real_bridge_stuck_in_its_apartment_cannot_hang_the_caller(real_exe):
    b = Bridge(real_exe, test_ops=True)
    pid = b.pid
    start = time.monotonic()
    with pytest.raises(BridgeTimeoutError):
        b.request("sleep", {"ms": 600_000}, timeout=1.0)
    elapsed = time.monotonic() - start
    assert elapsed < 10, f"the caller waited {elapsed:.1f} s"
    assert _gone(pid)
    b.close()
    b = Bridge(real_exe, test_ops=True)
    with pytest.raises(BridgeExitedError):
        b.request("exit", {"code": 5})
    b.close()


def _dialog(hwnd, pid=100, text=JOURNAL, title="SOLIDWORKS", cls="#32770", visible=True, extra=(), image=""):
    """A described window, as the classify_windows test operation takes it: a message box by default."""
    children = [
        {"class": "Static", "text": ""}, {"class": "Static", "text": text}, {"class": "Button", "text": "OK"},
    ]
    children += [{"class": c, "text": ""} for c in extra]
    return {"hwnd": hwnd, "pid": pid, "image": image, "class": cls, "title": title, "visible": visible,
            "children": children}


ACTIVATION_TITLE = "SOLIDWORKS Product Activation"
ACTIVATION_TEXT = "There are 0 day(s) left in your grace period:"


def _wizard(hwnd, pid=150, **kw):
    """A described SOLIDWORKS Product Activation dialog, of swactwiz.exe."""
    kw.setdefault("image", "swactwiz.exe")
    kw.setdefault("title", ACTIVATION_TITLE)
    kw.setdefault("text", ACTIVATION_TEXT)
    return _dialog(hwnd, pid, **kw)


@real
def test_real_bridge_picks_out_only_its_own_journal_box(real_exe):
    # The bridge's own SOLIDWORKS is process 100, in a stand-in job with 150 (a process it
    # started); 200 is the user's SOLIDWORKS. The rule the window watch applies, on these.
    windows = {
        1: ("hide", _dialog(1)),
        2: ("hide", _dialog(2, text=JOURNAL.replace(". ", ".\r\n").upper())),
        3: ("not_ours", _dialog(3, pid=200)),
        4: ("leave", _dialog(4, pid=150)),  # the journal words in a program SOLIDWORKS started: never hidden
        5: ("leave", _dialog(5, extra=("Edit",))),
        6: ("leave", _dialog(6, text="Rebuild errors occurred in the part.")),
        7: ("leave", _dialog(7, title="Microsoft Visual C++ Runtime Library")),
        8: ("not_a_dialog", _dialog(8, cls="Afx:00400000:8")),
        9: ("not_shown", _dialog(9, visible=False)),
        10: ("leave", _dialog(10, text="A journal file could not be created.")),
        11: ("leave", _dialog(11, text="Die Journaldatei konnte nicht erstellt werden.")),
        12: ("leave", {"hwnd": 12, "pid": 100, "class": "#32770", "title": "SOLIDWORKS", "visible": True}),
        13: ("leave", _dialog(13, text="")),
        # SOLIDWORKS Product Activation, which a SOLIDWORKS that is not activated starts and waits for
        14: ("activation", _wizard(14)),
        15: ("activation", _wizard(15, image="SWACTWIZ.EXE", title="SOLIDWORKS Produktaktivierung")),
        16: ("not_ours", _wizard(16, pid=200)),  # the wizard of the user's own SOLIDWORKS
        17: ("not_shown", _wizard(17, visible=False)),
        18: ("not_a_dialog", _wizard(18, cls="Afx:00400000:8")),
        19: ("leave", _dialog(19, text=ACTIVATION_TEXT, title=ACTIVATION_TITLE)),  # not swactwiz.exe's
        20: ("leave", _wizard(20, image="swactwiz.exe.old")),
    }
    with Bridge(real_exe, test_ops=True) as b:
        described = [w for _, w in windows.values()]
        got = b.request(
            "classify_windows", {"own_pid": 100, "job_pids": [100, 150], "windows": described}
        )["verdicts"]
        assert {v["hwnd"]: v["verdict"] for v in got} == {h: verdict for h, (verdict, _) in windows.items()}
        assert got[0]["text"] == JOURNAL and got[5]["text"] == "Rebuild errors occurred in the part."
        # A SOLIDWORKS outside the bridge's job is never its own, whatever its id.
        got = b.request("classify_windows", {"own_pid": 100, "job_pids": [], "windows": [_dialog(1)]})
        assert [v["verdict"] for v in got["verdicts"]] == ["not_ours"]
        for bad in (
            {"own_pid": 100, "windows": [{"hwnd": 1, "colour": "red"}]}, {"own_pid": 100, "windows": [7]},
            {"own_pid": 100, "job_pids": ["100"]}, {"own_pid": 0},
        ):
            with pytest.raises(BridgeRequestError) as caught:
                b.request("classify_windows", bad)
            assert caught.value.code == "invalid_argument", bad


# --------------------------------------------------------------------------- real windows (opt-in)
STANDIN = TESTS / "swbridge_standin_sldworks.cs"


def _windows(pids: set[int], *, details: bool = True) -> list[dict]:
    """The top-level windows of the processes named, read without sending any window a message.

    Each is ``hwnd``, ``pid``, ``visible`` and ``owned``, and with ``details`` its
    ``class``, ``title`` and ``children`` (class and text of each window inside
    it). A window of any other process is read no further than its process id.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [enum_proc, wintypes.LPARAM]
    user32.EnumChildWindows.argtypes = [wintypes.HWND, enum_proc, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND

    def read(fn, hwnd) -> str:
        buf = ctypes.create_unicode_buffer(2048)
        fn(hwnd, buf, len(buf))
        return buf.value

    found = []

    def top(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids:
            found.append((hwnd, pid.value))
        return True

    user32.EnumWindows(enum_proc(top), 0)
    out = []
    for hwnd, pid in found:
        w = {"hwnd": hwnd, "pid": pid, "visible": bool(user32.IsWindowVisible(hwnd)),
             "owned": bool(user32.GetWindow(hwnd, 4))}  # GW_OWNER
        if details:
            w["class"] = read(user32.GetClassNameW, hwnd)
            w["title"] = read(user32.GetWindowTextW, hwnd)
            kids = []

            def child(h, _, kids=kids):
                kids.append((read(user32.GetClassNameW, h), read(user32.GetWindowTextW, h)))
                return True

            user32.EnumChildWindows(hwnd, enum_proc(child), 0)
            w["children"] = kids
        out.append(w)
    return out


def _dialogs(pid: int) -> list[dict]:
    return [w for w in _windows({pid}) if w["class"] == "#32770"]


def _foreground() -> tuple[int, int]:
    """The foreground window and its process id."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32")
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    hwnd = user32.GetForegroundWindow()
    pid = wintypes.DWORD()
    if hwnd:
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return hwnd or 0, pid.value


def _own_window(hold: float = 0.5, *, show: bool = True) -> bool | None:
    """A window of this test's own process comes and goes, as other programs' windows do.

    On a thread of its own, which dispatches its messages, it makes a window off
    every screen, shows it and asks for it to be the foreground window, keeps it
    ``hold`` seconds and destroys it, so Windows then activates another window.
    It touches no window of any other process. Returns whether it was the
    foreground window (Windows may refuse that to a process the user is not
    using), or None when it could not be made; ``show=False`` only makes and
    destroys it, which changes no foreground.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.PeekMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT,
    ]
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    got: list[bool] = []

    def pump(seconds: float) -> None:
        msg = wintypes.MSG()
        end = time.monotonic() + seconds
        while True:
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):  # PM_REMOVE
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            if time.monotonic() >= end:
                return
            time.sleep(0.01)

    def run() -> None:
        # WS_POPUP | WS_CAPTION, at -32000,-32000: off every screen.
        hwnd = user32.CreateWindowExW(0, "STATIC", "SolidSeas test window", 0x80000000 | 0x00C00000,
                                      -32000, -32000, 200, 100, None, None, None, None)
        if not hwnd:
            return
        try:
            if show:
                user32.ShowWindow(hwnd, 5)  # SW_SHOW
                user32.SetForegroundWindow(hwnd)
            pump(hold)
            got.append(user32.GetForegroundWindow() == hwnd)
        finally:
            user32.DestroyWindow(hwnd)
            pump(0.2)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(hold + 10)
    return got[0] if got else None


def _journal_boxes(windows: list[dict]) -> list[dict]:
    return [
        w for w in windows
        if w.get("class") == "#32770" and any("journal file" in t.lower() for _, t in w["children"])
    ]


def _standin(folder: Path, steps: list[str], name: str = "SLDWORKS.exe") -> Path:
    """A stand-in SLDWORKS.exe (or the program ``name``) in ``folder``, doing what ``steps`` describe."""
    folder.mkdir(parents=True)
    exe = folder / name
    proc = subprocess.run(
        [str(build.default_csc()), "/nologo", "/target:winexe", "/langversion:5", "/warnaserror+",
         f"/out:{exe}", str(STANDIN)],
        capture_output=True, text=True, timeout=300, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    (folder / "standin.txt").write_text("\n".join(steps) + "\n", encoding="utf-8")
    return exe


SOLIDWORKS = os.environ.get("SOLIDSEAS_SWAPI_SOLIDWORKS") == "1" and REAL_REASON is None
with_solidworks = pytest.mark.skipif(
    not SOLIDWORKS or not bridge.DEFAULT_SOLIDWORKS_EXE.is_file(),
    reason="set SOLIDSEAS_SWAPI_SOLIDWORKS=1 (with the build check) to start SolidSeas' own SOLIDWORKS",
)
WINDOW_CHECK = REAL_REASON is None and (os.environ.get("SOLIDSEAS_SWAPI_WINDOW_CHECK") == "1" or SOLIDWORKS)
window_check = pytest.mark.skipif(
    not WINDOW_CHECK,
    reason="set SOLIDSEAS_SWAPI_WINDOW_CHECK=1 (with the build check) to show stand-in dialogs off screen",
)


@window_check
def test_real_bridge_hides_the_journal_box_of_its_own_process_only(real_exe, tmp_path):
    steps = [
        f"show|300|SOLIDWORKS|{JOURNAL}|",           # 0: the journal file message box: hidden
        "show|300|SOLIDWORKS|Rebuild errors occurred.|",  # 1: another dialog: left, reported
        f"show|300|SOLIDWORKS|{JOURNAL}|Edit",       # 2: the words, but something to type in: left
        "reshow|1500|0",                              # SOLIDWORKS showing it again: hidden again
    ]
    own_exe = _standin(tmp_path / "own", steps)
    user_exe = _standin(tmp_path / "user", steps[:3])
    user = subprocess.Popen([str(user_exe)])  # the user's SOLIDWORKS, outside every job of the bridge
    try:
        assert _until(lambda: len([w for w in _dialogs(user.pid) if w["visible"]]) == 3, 30)
        seen = []
        failed = []

        def start():
            try:
                b.request("start_solidworks", {"exe": str(own_exe)}, timeout=12)
            except bridge.BridgeError as e:
                failed.append(e)

        def hidden():
            return [e for e in list(seen) if e.get("event") == "window" and e["action"] == "hidden"]

        with Bridge(real_exe, on_event=seen.append) as b:
            worker = threading.Thread(target=start)
            worker.start()
            # It never registers, so the bridge waits for it about 10 s: look while it does.
            assert _until(lambda: len(hidden()) >= 2, 9), seen
            pid = hidden()[0]["pid"]
            assert pid != user.pid and pid in b.job_pids()
            mine = _windows({pid})
            box = [w for w in _journal_boxes(mine) if not any(c == "Edit" for c, _ in w["children"])]
            assert len(box) == 1 and not box[0]["visible"]
            assert {e["hwnd"] for e in hidden()} == {box[0]["hwnd"]}
            assert [e["again"] for e in hidden()][:2] == [False, True]
            for e in hidden():
                assert e["kind"] == "journal_box" and e["class"] == "#32770" and e["text"] == JOURNAL, e
            others = [w for w in mine if w["class"] == "#32770" and w["hwnd"] != box[0]["hwnd"]]
            assert len(others) == 2 and all(w["visible"] for w in others)
            left = [e for e in list(seen) if e.get("event") == "window" and e["action"] == "left"]
            assert sorted(e["hwnd"] for e in left) == sorted(w["hwnd"] for w in others)
            assert all(e["pid"] == pid for e in seen if e.get("event") == "window")
            worker.join(60)
            assert len(failed) == 1 and failed[0].code == "timeout"
            # The failure says which dialogs the instance showed: the two it left, not the box it hid.
            dialogs = (failed[0].details or {}).get("dialogs") or []
            assert sorted(d["hwnd"] for d in dialogs) == sorted(w["hwnd"] for w in others), dialogs
            assert sorted(d["text"] for d in dialogs) == sorted([JOURNAL, "Rebuild errors occurred."])
            assert _gone(pid), "the stand-in outlived the bridge's job"
        assert _alive(user.pid)
        theirs = _dialogs(user.pid)
        assert len(theirs) == 3 and all(w["visible"] for w in theirs), "a window of another process changed"
    finally:
        user.kill()
        user.wait(30)


def _tick() -> int:
    """GetTickCount: the clock the stand-in writes in its log, in milliseconds."""
    import ctypes

    k32 = ctypes.WinDLL("kernel32")
    k32.GetTickCount.restype = ctypes.c_uint32
    return k32.GetTickCount()


@window_check
def test_real_bridge_hides_a_box_shown_again_at_once_while_it_looks_slowly(real_exe, tmp_path):
    # A minute after the instance registers, the watch looks only every second, and a box
    # SOLIDWORKS shows again is hidden at once only because the WinEvent hook wakes it. The
    # stand-in never registers, so the watch_timing test operation ends the fast phase after 1 s
    # and spaces the slow looks 20 s apart: only the hook can hide the box again within a second.
    steps = [f"show|300|SOLIDWORKS|{JOURNAL}|", "reshow|3000|0"]
    own_exe = _standin(tmp_path / "own", steps)
    seen = []  # (GetTickCount on arrival, event)
    failed = []

    def start():
        try:
            b.request("start_solidworks", {"exe": str(own_exe)}, timeout=12)
        except bridge.BridgeError as e:
            failed.append(e)

    def hidden():
        return [(t, e) for t, e in list(seen) if e.get("event") == "window" and e["action"] == "hidden"]

    with Bridge(real_exe, test_ops=True, on_event=lambda e: seen.append((_tick(), e))) as b:
        timing = {"fast_ms": 1000, "slow_ms": 20000}
        assert b.request("watch_timing", timing) == timing
        for bad in ({"fast_ms": -1}, {"fast_ms": 0, "slow_ms": 50}, {"slow_ms": 1000, "colour": 1}):
            with pytest.raises(BridgeRequestError) as caught:
                b.request("watch_timing", bad)
            assert caught.value.code == "invalid_argument", bad
        worker = threading.Thread(target=start)
        worker.start()
        assert _until(lambda: len(hidden()) >= 2, 9), seen
        pid = hidden()[0][1]["pid"]
        notes = (tmp_path / "own" / "standin.log").read_text(encoding="utf-8").split()
        steps_at = {(notes[i], int(notes[i + 1])): int(notes[i + 2]) for i in range(0, len(notes), 3)}
        shown, reshown = steps_at[("show", 0)], steps_at[("reshow", 0)]
        again = [t for t, e in hidden() if e["again"]]
        assert len(again) == 1 and [e["again"] for _, e in hidden()] == [False, True]
        latency = (again[0] - reshown) & 0xFFFFFFFF
        print(f"\nthe box was shown again {(reshown - shown) & 0xFFFFFFFF} ms after it was first shown, "
              f"and hidden again {latency} ms after that")
        assert latency < 1000, f"the box shown again stayed for {latency} ms: the hook did not wake the watch"
        box = _journal_boxes(_windows({pid}))
        assert len(box) == 1 and not box[0]["visible"]
        worker.join(60)
        assert len(failed) == 1 and failed[0].code == "timeout"
        assert _gone(pid), "the stand-in outlived the bridge's job"
    with Bridge(real_exe) as plain:
        with pytest.raises(BridgeRequestError) as caught:
            plain.request("watch_timing", {"fast_ms": 1000})
        assert caught.value.code == "unknown_op", "the test timing exists only with --test-ops"


@window_check
def test_real_bridge_says_at_once_that_solidworks_waits_for_product_activation(real_exe, tmp_path):
    # A SOLIDWORKS that is not activated starts swactwiz.exe and waits while its wizard asks. The
    # stand-in SLDWORKS.exe shows its journal box, then starts a stand-in swactwiz.exe, which is in
    # the bridge's job as SOLIDWORKS' own would be and shows a dialog titled as the wizard. An
    # identical swactwiz.exe outside the job plays the wizard of the user's own SOLIDWORKS.
    own = tmp_path / "own"
    own_exe = _standin(own, [f"show|300|SOLIDWORKS|{JOURNAL}|", r"start|200|setup\i386\swactwiz.exe"])
    _standin(own / "setup" / "i386", [f"show|300|{ACTIVATION_TITLE}|{ACTIVATION_TEXT}|"], "swactwiz.exe")
    user_exe = _standin(tmp_path / "user", [f"show|0|{ACTIVATION_TITLE}|{ACTIVATION_TEXT}|"], "swactwiz.exe")
    user = subprocess.Popen([str(user_exe)])
    try:
        assert _until(lambda: len([w for w in _dialogs(user.pid) if w["visible"]]) == 1, 30)
        seen = []
        with Bridge(real_exe, on_event=seen.append) as b:
            started = time.monotonic()
            with pytest.raises(BridgeRequestError) as caught:
                b.request("start_solidworks", {"exe": str(own_exe)}, timeout=60)
            took = time.monotonic() - started
            failed = caught.value
            assert failed.code == "solidworks_not_activated", failed
            assert "SOLIDWORKS needs product activation on this PC" in str(failed)
            assert took < 20, f"start_solidworks took {took:.1f} s: it waited instead of saying so at once"
            asking = (failed.details or {}).get("activation") or {}
            assert asking["kind"] == "activation" and asking["process"].lower() == "swactwiz.exe"
            assert asking["title"] == ACTIVATION_TITLE and asking["text"] == ACTIVATION_TEXT
            assert [d["kind"] for d in (failed.details or {}).get("dialogs") or []] == ["activation"]
            windows = [e for e in list(seen) if e.get("event") == "window"]
            hidden = [e for e in windows if e["action"] == "hidden"]
            left = [e for e in windows if e["action"] == "left"]
            assert hidden
            assert all(e["kind"] == "journal_box" and e["process"] == "SLDWORKS.exe" for e in hidden)
            assert [(e["kind"], e["pid"], e["hwnd"]) for e in left] == [
                ("activation", asking["pid"], asking["hwnd"])
            ]
            notes = (own / "standin.log").read_text(encoding="utf-8").split()
            wizard_pid = [int(notes[i + 1]) for i in range(0, len(notes), 3) if notes[i] == "start"][0]
            assert asking["pid"] == wizard_pid != user.pid
            assert _gone(hidden[0]["pid"]), "the stand-in SOLIDWORKS outlived the bridge's job"
            assert _gone(wizard_pid), "ending the instance ends the wizard with it"
        assert _alive(user.pid)
        theirs = _dialogs(user.pid)
        assert len(theirs) == 1 and theirs[0]["visible"], "the wizard outside the job changed"
    finally:
        user.kill()
        user.wait(30)


def _solidworks_pids() -> set[int]:
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq SLDWORKS.exe", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, check=False, timeout=60,
    ).stdout
    return {int(m) for m in re.findall(r'^"SLDWORKS\.exe","(\d+)"', out, re.M | re.I)}


@with_solidworks
def test_batch_conversion_in_solidseas_own_solidworks(real_exe, tmp_path):
    others = _solidworks_pids()
    names = ("o02_boxA.SLDPRT", "o11_curved.SLDPRT", "o12_multibody.SLDPRT", "o17_деталь.SLDPRT")
    src = _inputs(tmp_path, names)
    out = tmp_path / "out"
    log = []
    rows = batch.convert(
        [src], out, list(batch.FORMATS), log=log.append,
        bridge_factory=lambda: Bridge(real_exe),
    )
    batch.write_report(rows, tmp_path / "report.tsv")
    assert len(rows) == len(names) * len(batch.FORMATS)
    # SOLIDWORKS 2024 SP1's SaveAs3 refused .gltf and .glb on 2026-10-05 and wrote both on
    # 2026-10-14 (the .gltf into a folder named after it); either passes.
    gltf = [r for r in rows if r.format in ("gltf", "glb")]
    assert all(r.status == "ok" or (r.code == "save_failed" and r.errors) for r in gltf), gltf
    failed = [r for r in rows if r.status != "ok" and r not in gltf]
    assert not failed, failed
    for r in rows:
        if r.status == "ok":
            assert Path(r.output).stat().st_size > 0
            assert r.step_ap is None or r.format == "step"
    started = [int(m) for m in re.findall(r"started, PID (\d+)", " ".join(log))]
    assert len(started) == 1 and started[0] not in others
    # Ended through its job, never by SOLIDWORKS' own shutdown.
    ended = [m for m in log if m.startswith("SolidSeas' SOLIDWORKS ended:")]
    assert ended == [f"SolidSeas' SOLIDWORKS ended: job_terminated, PID {started[0]}, exit code 21331"], log
    assert _gone(started[0], 60)
    assert others <= _solidworks_pids(), "a SOLIDWORKS SolidSeas did not start has gone"


@with_solidworks
def test_a_real_call_past_its_timeout_ends_solidseas_solidworks(real_exe, tmp_path):
    others = _solidworks_pids()
    src = _inputs(tmp_path, ("o02_boxA.SLDPRT",))
    b = Bridge(real_exe)
    try:
        info = b.request("start_solidworks")
        sw_pid = info["pid"]
        assert info["visible"] is False and info["user_control"] is False and info["in_job"] is True
        assert sw_pid not in others and sw_pid in b.job_pids()
        start = time.monotonic()
        with pytest.raises(BridgeTimeoutError):
            b.request("open_document", {"path": str(src / "o02_boxA.SLDPRT")}, timeout=0.05)
        assert time.monotonic() - start < 40
        assert _gone(sw_pid, 30) and not b.alive
        assert b.job_pids() == []
    finally:
        b.close()
    # The apartment thread stuck while SOLIDWORKS holds an open document, and a second
    # SolidSeas SOLIDWORKS refused while the first runs.
    b = Bridge(real_exe, test_ops=True)
    try:
        sw_pid = b.request("start_solidworks")["pid"]
        b.request("open_document", {"path": str(src / "o02_boxA.SLDPRT")})
        with Bridge(real_exe) as second:
            with pytest.raises(BridgeRequestError) as caught:
                second.request("start_solidworks")
            assert caught.value.code == "refused"
        start = time.monotonic()
        with pytest.raises(BridgeTimeoutError):
            b.request("sleep", {"ms": 600_000}, timeout=2.0)
        assert time.monotonic() - start < 40
        assert _gone(sw_pid, 30) and not b.alive
    finally:
        b.close()
    assert others <= _solidworks_pids()


@with_solidworks
def test_save_copy_never_writes_an_open_document_under_another_name(real_exe, tmp_path):
    others = _solidworks_pids()
    src = _inputs(tmp_path, ("o02_boxA.SLDPRT",))
    part = src / "o02_boxA.SLDPRT"
    out = tmp_path / "out"
    out.mkdir()
    linked = out / "o02_boxA.step"
    os.link(part, linked)  # a hard link: another name for the part's own file
    alias = tmp_path / "alias"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(alias), str(src)], check=True, capture_output=True)
    before = part.read_bytes()
    try:
        with Bridge(real_exe) as b:
            sw_pid = b.request("start_solidworks")["pid"]
            with pytest.raises(BridgeRequestError) as caught:
                b.request("open_document", {"path": str(part), "read_only": False})
            assert caught.value.code == "refused"
            doc = b.request("open_document", {"path": str(alias / part.name)})["doc"]
            # Measured before this check existed: SaveAs3 through the hard link emptied the part.
            with pytest.raises(BridgeRequestError) as caught:
                b.request("save_copy", {"doc": doc, "path": str(linked), "overwrite": True})
            assert caught.value.code == "refused" and "own file" in str(caught.value)
            for target in (part, alias / "copy.sldprt", "\\\\localhost\\c$\\copy.step", "C:copy.step"):
                with pytest.raises(BridgeRequestError) as caught:
                    b.request("save_copy", {"doc": doc, "path": str(target), "overwrite": True})
                assert caught.value.code in ("invalid_argument", "refused"), target
            written = b.request("save_copy", {"doc": doc, "path": str(out / "copy.step")})
            assert written["bytes"] > 0
            ended = b.request("exit_solidworks")
            assert ended["ended"] == "job_terminated" and ended["exit_code"] == 0x5353
        assert part.read_bytes() == before and linked.read_bytes() == before
        assert not list(src.glob("~$*")), "a read-only open leaves no lock file"
        assert _gone(sw_pid, 60)
    finally:
        os.rmdir(alias)  # the junction only, never what it points at
    assert others <= _solidworks_pids()


@with_solidworks
def test_a_new_document_reports_its_own_close(real_exe):
    template = MBD_PART_TEMPLATE
    if not template.is_file():
        pytest.skip("needs the MBD part template SOLIDWORKS 2024 installs")
    others = _solidworks_pids()
    seen = []
    with Bridge(real_exe, on_event=seen.append) as b:
        sw_pid = b.request("start_solidworks")["pid"]
        with pytest.raises(BridgeRequestError) as caught:
            b.request("open_document", {"path": "C:/in" + chr(9) + "valid.sldprt"})
        assert caught.value.code == "invalid_argument"
        new = b.request("new_document", {"template": str(template)})
        assert new["type"] == "part" and new["path"] == "" and new["dirty"] is False
        info = b.request("solidworks_info")
        assert info["user_control"] is False and info["visible"] is False
        assert info["documents"] == [new["title"]]
        assert "DestroyNotify2" in b.request("watch_document", {"doc": new["doc"]})["events"]
        b.request("close_document", {"doc": new["doc"]})
        destroyed = {"event": "document", "doc": new["doc"], "name": "DestroyNotify2"}
        destroyed["data"] = {"destroy_type": 0}
        assert destroyed in seen
        assert b.request("exit_solidworks")["ended"] == "job_terminated"
    assert _gone(sw_pid, 60)
    assert others <= _solidworks_pids()


@with_solidworks
def test_solidseas_solidworks_hides_its_journal_box_and_nothing_else(real_exe):
    others = _solidworks_pids()
    if not others:
        pytest.skip("needs another SOLIDWORKS running, such as your own: only then does the journal box come")
    theirs = {w["hwnd"] for w in _windows(others, details=False) if w["visible"] and not w["owned"]}
    seen = []
    samples = []
    stop = threading.Event()
    began = time.monotonic()

    def sample():
        while not stop.is_set():
            samples.append((time.monotonic() - began, *_foreground()))
            time.sleep(0.05)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    provoked = []
    try:
        with Bridge(real_exe, on_event=lambda e: seen.append((time.monotonic() - began, e))) as b:
            sw_pid = b.request("start_solidworks")["pid"]
            started = time.monotonic() - began  # from here the instance's main window is hidden

            def hidden():
                return [(t, e) for t, e in list(seen) if e.get("action") == "hidden"]

            assert _until(hidden, 60), "no journal file message box was hidden"
            # Before the bridge hid it, the box took the foreground again as other programs'
            # windows came and went. A window of the test's own comes and goes five times here.
            for _ in range(5):
                provoked.append(_own_window(0.5))
                time.sleep(3.5)
            for _, e in hidden():
                assert e["pid"] == sw_pid and e["kind"] == "journal_box" and e["class"] == "#32770", e
            boxes = _journal_boxes(_windows({sw_pid}))
            assert boxes and not any(w["visible"] for w in boxes)
            assert {e["hwnd"] for _, e in hidden()} <= {w["hwnd"] for w in boxes}
            info = b.request("solidworks_info")
            assert info["window_watch"] is True and info["windows_hidden"] >= 1
            ended = b.request("exit_solidworks")
            assert ended["ended"] == "job_terminated" and ended["exit_code"] == 0x5353
    finally:
        stop.set()
        sampler.join(5)
    assert _gone(sw_pid, 60)
    assert others <= _solidworks_pids(), "a SOLIDWORKS SolidSeas did not start has gone"
    after = {w["hwnd"] for w in _windows(others, details=False) if w["visible"] and not w["owned"]}
    assert theirs <= after, "a window of another SOLIDWORKS was hidden"
    hid_at = min(t for t, _ in hidden())
    box_handles = {e["hwnd"] for _, e in hidden()}
    late = [t for t, hwnd, _ in samples if t > hid_at + 0.5 and hwnd in box_handles]
    assert not late, "the hidden box held the foreground"
    # Hiding the box while it is the foreground window makes Windows activate another one. Before
    # start_solidworks returned that may be SolidSeas' own splash or main window; after it, with
    # the instance hidden, it must never be a window of SolidSeas' SOLIDWORKS.
    handed = []
    for t, _ in hidden():
        after_hide = [(s, hwnd, pid) for s, hwnd, pid in samples if s > t + 0.1][:1]
        if not after_hide:
            continue
        _, hwnd, pid = after_hide[0]
        if pid == sw_pid:
            who = "SolidSeas' SOLIDWORKS"
        elif pid in others:
            who = f"another SOLIDWORKS (PID {pid})"
        else:
            who = f"another program (PID {pid})" if hwnd else "no window"
        handed.append((t, who, pid))
    print("\nthe foreground right after each hide: "
          + "; ".join(f"{t:.1f} s: {who}" for t, who, _ in handed))
    to_us = [h for h in handed if h[0] > started and h[2] == sw_pid]
    assert not to_us, "a hide handed SolidSeas' SOLIDWORKS the foreground"
    held = [t for t, _, pid in samples if pid == sw_pid]
    left = [e for _, e in seen if e.get("event") == "window" and e["action"] == "left"]
    print(f"SolidSeas' SOLIDWORKS was the foreground for {len(held) * 0.05:.1f} s of samples, "
          f"the last {max(held, default=0.0):.1f} s after the start, which returned after {started:.1f} s; "
          f"the journal box was hidden {hid_at:.1f} s after the start; the test's own window was the "
          f"foreground {provoked.count(True)} of {len(provoked)} times; dialogs left alone: {left}")
    if not any(provoked):
        print("Windows did not let the test's window take the foreground, so the case of other windows "
              "coming and going was not provoked")


def _registry_values(root: str = r"Software\SolidWorks") -> dict[str, str]:
    """Every value under ``HKEY_CURRENT_USER\\<root>``, read only: its path and a hash of its data."""
    import hashlib
    import winreg

    values: dict[str, str] = {}

    def walk(path: str) -> None:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ)
        except OSError:
            return
        subkeys = []
        with key:
            for i in itertools.count():
                try:
                    name, data, kind = winreg.EnumValue(key, i)
                except OSError:
                    break
                digest = hashlib.sha256(repr((kind, data)).encode("utf-8", "surrogatepass")).hexdigest()
                values[path + "\\" + name] = digest
            for i in itertools.count():
                try:
                    subkeys.append(winreg.EnumKey(key, i))
                except OSError:
                    break
        for sub in subkeys:
            walk(path + "\\" + sub)

    walk(root)
    return values


@with_solidworks
def test_ending_through_the_job_leaves_the_layout_lock_files_and_next_start_alone(real_exe, tmp_path):
    template = MBD_PART_TEMPLATE
    others = _solidworks_pids()
    src = _inputs(tmp_path, ("o02_boxA.SLDPRT",))
    part = src / "o02_boxA.SLDPRT"
    before_bytes = part.read_bytes()
    before = _registry_values()
    dialogs = []
    for run in (1, 2):
        seen = []
        with Bridge(real_exe, on_event=seen.append) as b:
            sw_pid = b.request("start_solidworks")["pid"]
            time.sleep(30)  # the dialogs a start brings
            if run == 1:
                b.request("open_document", {"path": str(part)})
                if template.is_file():
                    b.request("new_document", {"template": str(template)})
            ended = b.request("exit_solidworks")
        assert ended["ended"] == "job_terminated" and ended["exit_code"] == 0x5353, ended
        assert ended["documents_open"] == 0
        assert _gone(sw_pid, 60) and not b.alive
        dialogs.append({(e["title"], e["text"]) for e in seen if e.get("action") == "left"})
        if run == 1:
            assert ended["documents_closed"] == (2 if template.is_file() else 1)
            after = _registry_values()
            changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
            ui = "\\User Interface\\"
            layout = [k for k in changed if ui in k and ui + "Custom API Toolbars" not in k]
            print(f"\nregistry: {len(changed)} values added, removed or changed under "
                  f"HKCU\\Software\\SolidWorks, {len(layout)} of them in the User Interface layout")
            for k in changed:
                print("  ", "added" if k not in before else "removed" if k not in after else "changed", k)
            assert not layout, "the instance wrote its layout, as ExitApp does"
            # A document opened read-only leaves no lock file and is never changed.
            assert not list(src.glob("~$*")) and part.read_bytes() == before_bytes
    # A start after one ended through its job shows no dialog the first start did not.
    assert dialogs[1] <= dialogs[0], dialogs[1] - dialogs[0]
    assert others <= _solidworks_pids()


def _solidworks_files() -> dict[str, dict[str, tuple[int, int]]]:
    """What SOLIDWORKS keeps on disk that a later start may act on, read only, never changed.

    By place: the files directly in ``%APPDATA%\\SolidWorks`` and in each
    ``SOLIDWORKS <year>`` folder in it (where the journal file, ``swxJRNL.swj``,
    is), and every file in the auto-recover and backup folders the account's
    options name (``AutoRecover Directory`` and ``Backup directory`` under
    ``HKEY_CURRENT_USER\\Software\\SolidWorks\\SOLIDWORKS <year>\\General``, read,
    never set), each with its size and modification time.
    """
    import winreg

    places: dict[str, Path] = {}
    appdata = Path(os.environ.get("APPDATA", "")) / "SolidWorks"
    if appdata.is_dir():
        places["appdata"] = appdata
        for folder in sorted(appdata.glob("SOLIDWORKS *")):
            places[folder.name] = folder
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\SolidWorks", 0, winreg.KEY_READ) as root:
            versions = []
            for i in itertools.count():
                try:
                    versions.append(winreg.EnumKey(root, i))
                except OSError:
                    break
    except OSError:
        versions = []
    for version in versions:
        if not re.fullmatch(r"SOLIDWORKS \d{4}", version):
            continue
        try:
            general_key = rf"Software\SolidWorks\{version}\General"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, general_key, 0, winreg.KEY_READ) as general:
                named = (("AutoRecover Directory", "auto-recover"), ("Backup directory", "backup"))
                for value, place in named:
                    try:
                        folder = Path(os.path.expandvars(str(winreg.QueryValueEx(general, value)[0])))
                    except OSError:
                        continue
                    if str(folder) and folder.is_dir():
                        places[f"{version} {place}"] = folder
        except OSError:
            continue
    out: dict[str, dict[str, tuple[int, int]]] = {}
    for place, folder in places.items():
        files: dict[str, tuple[int, int]] = {}
        if place.endswith(("auto-recover", "backup")):
            walker = os.walk(folder)
        else:
            try:
                walker = [(str(folder), [], os.listdir(folder))]
            except OSError:
                walker = []
        for top, _dirs, names in walker:
            for name in names:
                path = Path(top) / name
                try:
                    if path.is_file():
                        st = path.stat()
                        files[str(path.relative_to(folder))] = (st.st_size, st.st_mtime_ns)
                except OSError:
                    continue
            if len(files) > 20000:
                break
        out[place] = files
    return out


def _file_changes(before: dict, after: dict) -> dict[str, list[str]]:
    """What changed between two :func:`_solidworks_files` readings, by place: lines naming each file."""
    changes: dict[str, list[str]] = {}
    for place in sorted(set(before) | set(after)):
        a, b = before.get(place, {}), after.get(place, {})
        lines = [f"added {n}" for n in sorted(set(b) - set(a))]
        lines += [f"removed {n}" for n in sorted(set(a) - set(b))]
        lines += [f"changed {n}" for n in sorted(set(a) & set(b)) if a[n] != b[n]]
        if lines:
            changes[place] = lines
    return changes


@with_solidworks
def test_solidseas_solidworks_alone_ended_through_its_job_leaves_no_recovery_behind(real_exe, tmp_path):
    # The off-hours case: no other SOLIDWORKS runs, so SolidSeas' instance is the first session.
    # It makes the journal file, auto-recover is on, it shows no journal box, and it is ended
    # through its job, so SOLIDWORKS' own clean-up at exit never runs. Three starts: one ended
    # by exit_solidworks after opening a part and making a new document, one ended by a timeout
    # with the part open, and the next start, which stands in for yours in the morning.
    if _solidworks_pids():
        pytest.skip("needs no other SOLIDWORKS running: close yours, normally, for this run")
    template = MBD_PART_TEMPLATE
    src = _inputs(tmp_path, ("o02_boxA.SLDPRT",))
    part = src / "o02_boxA.SLDPRT"
    before_bytes = part.read_bytes()
    readings = [("before", _solidworks_files())]
    first = readings[0][1]
    journal = [p for p in first if p.startswith("SOLIDWORKS ") and "swxJRNL.swj" in first[p]]
    events = {}

    seen = []
    with Bridge(real_exe, on_event=seen.append) as b:
        sw_pid = b.request("start_solidworks")["pid"]
        time.sleep(30)  # the dialogs a start brings
        b.request("open_document", {"path": str(part)})
        if template.is_file():
            b.request("new_document", {"template": str(template)})
        readings.append(("while the first ran", _solidworks_files()))
        ended = b.request("exit_solidworks")
    assert ended["ended"] == "job_terminated" and ended["exit_code"] == 0x5353, ended
    assert ended["documents_open"] == 0
    assert _gone(sw_pid, 60)
    events["first"] = seen
    readings.append(("after exit_solidworks", _solidworks_files()))

    seen = []
    b = Bridge(real_exe, test_ops=True, on_event=seen.append)
    try:
        sw_pid = b.request("start_solidworks")["pid"]
        b.request("open_document", {"path": str(part)})
        time.sleep(15)
        with pytest.raises(BridgeTimeoutError):
            b.request("sleep", {"ms": 600_000}, timeout=2.0)  # the client ends the bridge's job
        assert _gone(sw_pid, 30)
    finally:
        b.close()
    events["timeout"] = seen
    readings.append(("after the timeout", _solidworks_files()))

    seen = []
    with Bridge(real_exe, on_event=seen.append) as b:
        sw_pid = b.request("start_solidworks")["pid"]
        time.sleep(30)
        ended = b.request("exit_solidworks")
    assert ended["ended"] == "job_terminated", ended
    assert _gone(sw_pid, 60)
    events["next"] = seen
    readings.append(("after the next start", _solidworks_files()))

    print(f"\nbefore the first start, with no SOLIDWORKS running, a journal file was in: {journal or 'none'}")
    for (name_a, a), (name_b, b_) in itertools.pairwise(readings):
        changes = _file_changes(a, b_)
        print(f"from {name_a} to {name_b}: " + ("nothing changed" if not changes else ""))
        for place, lines in changes.items():
            print(f"  {place}: " + ", ".join(lines))
    windows = {
        run: [(e["action"], e.get("title"), e.get("text")) for e in seen_ if e.get("event") == "window"]
        for run, seen_ in events.items()
    }
    print(f"window events: {windows}")
    # Alone, the instance shows no journal box; nothing was hidden in any of the three runs.
    assert not [w for run in windows.values() for w in run if w[0] == "hidden"], windows
    # The next start shows no dialog the first did not: no recovery or crash prompt.
    assert set(windows["next"]) <= set(windows["first"]), windows
    # No auto-recover copy and no backup was made of a document the bridge never changes or
    # saves, so the next start, yours included, has nothing to offer under Document Recovery.
    for (name_a, a), (name_b, b_) in itertools.pairwise(readings):
        changes = _file_changes(a, b_)
        recovery = {p: lines for p, lines in changes.items() if p.endswith(("auto-recover", "backup"))}
        assert not recovery, f"from {name_a} to {name_b}: {recovery}"
    assert not list(src.glob("~$*")) and part.read_bytes() == before_bytes
    assert not _solidworks_pids(), "a SOLIDWORKS is left running"


# --------------------------------------------------------------------------- imports and measures (opt-in)
# What each file imported in SolidSeas' own SOLIDWORKS is compared with: the fixture it was made from.
IMPORTS = {
    "o02_boxA.step": "o02_boxA.SLDPRT",  # SOLIDWORKS' own STEP of o02, a fixture
    "o02_boxA.x_t": "o02_boxA.SLDPRT",
    "o02_boxA.x_b": "o02_boxA.SLDPRT",
    "o11_curved_solidseas.step": "o11_curved.SLDPRT",  # SolidSeas' own STEP (solidseas.step), written here
    "o12_multibody_solidseas.step": "o12_multibody.SLDPRT",  # two solid bodies
}
# What import_file's component method takes, each with the solid bodies it brings: several
# bodies, or an assembly, come in as a sub-assembly; one body as a part.
COMPONENT_IMPORTS = {
    "o12_multibody_solidseas.step": ("o12_multibody.SLDPRT", 2),
    "o08_asm_2x_boxA_solidseas.step": ("o08_asm_2x_boxA.SLDASM", 2),  # one part placed twice
    "o15_sub_asm_solidseas.step": ("o15_sub_asm.SLDASM", 2),  # two parts
    "o02_boxA.step": ("o02_boxA.SLDPRT", 1),
}
MBD_ASSEMBLY_TEMPLATE = MBD_PART_TEMPLATE.parent / "assembly 0250mm and smaller.asmdot"


def _import_source(name: str, folder: Path) -> Path:
    """The file to import, in ``folder``: a fixture's copy, or SolidSeas' own STEP of a fixture."""
    target = folder / name
    if name.endswith("_solidseas.step"):
        from solidseas import open_document, step

        fixture = IMPORTS.get(name) or COMPONENT_IMPORTS[name][0]
        with open_document(FIXTURES / fixture) as doc:
            model = step.step_model(doc)
        step.write_step(model, target)
    else:
        shutil.copyfile(FIXTURES / name, target)
    return target


@pytest.mark.parametrize("name", sorted({*IMPORTS, *COMPONENT_IMPORTS}))
def test_each_file_to_import_is_made_without_solidworks(tmp_path, name):
    # The opt-in imports below start SOLIDWORKS; the files they import are made here on every run,
    # so SolidSeas' own STEP of o11, o12 and the assemblies o08 and o15 is known to be written
    # before a night's run needs it.
    source = _import_source(name, tmp_path)
    head = source.read_bytes()[:20]
    if name.endswith(".step"):
        assert head.startswith(b"ISO-10303-21;")
    else:
        assert head.startswith(b"**ABCDEFGHIJKLMNOPQR")
    assert sorted(p.name for p in tmp_path.iterdir()) == [name]


def _recovery(files: dict) -> dict:
    return {place: names for place, names in files.items() if place.endswith(("auto-recover", "backup"))}


@with_solidworks
@pytest.mark.parametrize("method", ["insert", "load"])
@pytest.mark.parametrize("name", list(IMPORTS))
def test_an_import_in_solidseas_own_solidworks_matches_the_ground_truth(real_exe, tmp_path, name, method):
    # Each import in a SOLIDWORKS of its own: one held by a dialog ends only its own instance.
    if method == "insert" and not MBD_PART_TEMPLATE.is_file():
        pytest.skip("needs the MBD part template SOLIDWORKS 2024 installs")
    others = _solidworks_pids()
    folder = tmp_path / "in"
    folder.mkdir()
    source = _import_source(name, folder)
    listing, data = sorted(p.name for p in folder.iterdir()), source.read_bytes()
    recovery = _recovery(_solidworks_files())
    truth = _truth(IMPORTS[name])
    args = {"path": str(source), "method": method}
    if method == "insert":
        args["template"] = str(MBD_PART_TEMPLATE)
    seen = []
    refused = got = measured = None
    with Bridge(real_exe, on_event=seen.append) as b:
        sw_pid = b.request("start_solidworks")["pid"]
        try:
            got = b.request("import_file", args)
        except BridgeRequestError as e:
            print(f"\n{name}, {method}: {e.code}: {e}; details: {json.dumps(e.details)}")
            reason = (e.details or {}).get("reason")
            if e.code == "refused" and reason in ("several_bodies_as_assembly", "several_bodies_insert"):
                refused = e
            elif e.code == "import_failed" and method == "insert" and name.endswith((".x_t", ".x_b")):
                pytest.xfail(f"3D Interconnect did not insert a Parasolid file: {e}")
            else:
                raise
        if got is not None:
            prefs = got["preferences"]
            print(f"\n{name}, {method}: {got['result_kind']}, {got['solid_bodies']} solid and "
                  f"{got['sheet_bodies']} sheet bodies, errors {got['errors']} {got.get('error_names', [])}, "
                  f"feature {got.get('feature')}, "
                  f"feature types {got['feature_types']}, {got['seconds']} s, dialogs {got['dialogs']}, "
                  f"census {got.get('step_census', {}).get('entities')}; options: {prefs}, "
                  f"default part template {got['default_part_template']}")
            measured = b.request("mass_properties", {"doc": got["doc"]})
            m = measured["measures"][0]
            print(f"measured: mass {m['mass']}, box {m['bbox_m']}, solid topology {m['solid_topology']}, "
                  f"Check3 {m['check3']}, warnings {m['warnings']}")
            b.request("close_document", {"doc": got["doc"]})
        ended = b.request("exit_solidworks")
    assert ended["ended"] == "job_terminated" and ended["documents_open"] == 0, ended
    assert _gone(sw_pid, 60)
    window_events = [e for e in seen if e.get("event") == "window" and e["action"] == "left"]
    print(f"dialogs the instance showed: {window_events}")
    # The source is read and nothing is written next to it; no auto-recover copy of the
    # imported document, which is changed and never saved, is left for the next start.
    assert sorted(p.name for p in folder.iterdir()) == listing and source.read_bytes() == data
    changed = _file_changes(recovery, _recovery(_solidworks_files()))
    print(f"auto-recover and backup folders: {changed or 'unchanged'}")
    if not others:  # while another SOLIDWORKS runs, SolidSeas' has no auto-recover and the changes are its
        assert not changed, "an auto-recover copy or a backup appeared"
    assert others <= _solidworks_pids()
    if refused is not None:
        # The predictable cases, refused before SOLIDWORKS imported anything: several bodies
        # loaded while the account's options make them an assembly, which asked for a template,
        # or inserted into a part while they make them parts, which faulted. Both take the
        # component method (below).
        prefs = refused.details["preferences"]
        assert not refused.details["step_census"]["one_body"], refused.details
        mapping = prefs["swImportNeutralAssemblyStructureMapping"]
        if method == "load":
            assert refused.details["reason"] == "several_bodies_as_assembly"
            assert mapping == 1 or not prefs["swMultiCAD_Enable3DInterconnect"]
        else:
            assert refused.details["reason"] == "several_bodies_insert" and mapping == 1
        assert "use method component" in str(refused)
        return
    assert got["errors"] == 0 and got["dialog_appeared"] is False, got
    assert got["result_kind"] == "solids" and got["solid_bodies"] == truth["solid_bodies"], got
    assert got["type"] == "part" and got["read_only"] is False
    m = measured["measures"][0]
    assert _against_truth(m, truth, rel=1e-6, abs_m=1e-7) == [], m
    assert m["check3"]["faults"] == 0 and m["check3"]["check_errors"] == 0, m["check3"]


@with_solidworks
@pytest.mark.parametrize("name", list(COMPONENT_IMPORTS))
def test_a_step_of_several_bodies_or_an_assembly_comes_in_as_a_component(real_exe, tmp_path, name):
    # Each in a SOLIDWORKS of its own, as the imports above. Several bodies or an assembly come in
    # as a sub-assembly of parts 3D Interconnect makes, one body as a part, in a new assembly made
    # from the template given, moved to the origin so the measures are the file's own.
    if not MBD_ASSEMBLY_TEMPLATE.is_file():
        pytest.skip("needs the MBD assembly template SOLIDWORKS 2024 installs")
    fixture, bodies = COMPONENT_IMPORTS[name]
    others = _solidworks_pids()
    folder = tmp_path / "in"
    folder.mkdir()
    source = _import_source(name, folder)
    listing, data = sorted(p.name for p in folder.iterdir()), source.read_bytes()
    recovery = _recovery(_solidworks_files())
    args = {"path": str(source), "method": "component", "template": str(MBD_ASSEMBLY_TEMPLATE)}
    with Bridge(real_exe) as b:
        sw_pid = b.request("start_solidworks")["pid"]
        got = b.request("import_file", args)
        print(f"\n{name}: {got['component']}, {got['solid_bodies']} solid and {got['sheet_bodies']} sheet "
              f"bodies, {got['seconds']} s, dialogs {got['dialogs']}")
        measured = b.request("mass_properties", {"doc": got["doc"]})
        b.request("close_document", {"doc": got["doc"]})
        left = b.request("solidworks_info")["documents"]
        ended = b.request("exit_solidworks")
    assert ended["ended"] == "job_terminated" and ended["documents_open"] == 0, ended
    assert _gone(sw_pid, 60)
    # Closing the assembly closes the documents 3D Interconnect made for its component too.
    assert left == []
    assert sorted(p.name for p in folder.iterdir()) == listing and source.read_bytes() == data
    changed = _file_changes(recovery, _recovery(_solidworks_files()))
    print(f"auto-recover and backup folders: {changed or 'unchanged'}")
    if not others:
        assert not changed, "an auto-recover copy or a backup appeared"
    assert others <= _solidworks_pids()
    assert got["type"] == "assembly" and got["errors"] == 0 and got["result_kind"] == "solids", got
    assert got["solid_bodies"] == bodies and got["sheet_bodies"] == 0, got
    component = got["component"]
    assert component["at_origin"] is True and len(component["placed"]) == 12, component
    assert component["refers_to_source"] is False and component["virtual"] is False, component
    assert component["document_extension"] == (".sldasm" if bodies > 1 else ".sldprt"), component
    assert component["children"] == (2 if bodies > 1 else 0), component
    # Measured on 2026-10-14: "Open Progress..." with each import, and mostly an untitled empty
    # box too, both gone again when it answered (the window watch counts them, a known issue).
    assert all(d["title"] in ("Open Progress...", "") for d in got["dialogs"]), got["dialogs"]
    m = measured["measures"][0]
    assert m["solid_bodies"] == bodies and m["sheet_bodies"] == 0, m
    assert _against_truth(m, _truth(fixture), rel=1e-6, abs_m=1e-7) == [], m
    assert m["check3"]["faults"] == 0 and m["check3"]["check_errors"] == 0, m["check3"]


@with_solidworks
def test_mass_properties_of_fixture_copies_match_the_ground_truth(real_exe, tmp_path):
    others = _solidworks_pids()
    parts = ("o02_boxA.SLDPRT", "o01_empty.SLDPRT", "o06_boxA_props_mat_cfg.SLDPRT", "o11_curved.SLDPRT",
             "o12_multibody.SLDPRT", "o13_two_geometry_configs.SLDPRT")
    assembly = "o08_asm_2x_boxA.SLDASM"  # two instances of o02_boxA.SLDPRT, opened first, beside it
    src = _inputs(tmp_path, (*parts, assembly))
    before = {p.name: p.read_bytes() for p in src.iterdir()}
    recovery = _recovery(_solidworks_files())
    # The harness saw an assembly opened read-only change its folder's time, the entries the same
    # before and after, and part opens leave it alone: the times are printed, never asserted.
    folder_times = {"before": src.stat().st_mtime_ns}
    with Bridge(real_exe) as b:
        sw_pid = b.request("start_solidworks")["pid"]
        docs = {n: b.request("open_document", {"path": str(src / n)})["doc"] for n in parts}
        folder_times["parts opened"] = src.stat().st_mtime_ns
        docs[assembly] = b.request("open_document", {"path": str(src / assembly)})["doc"]
        folder_times["assembly opened"] = src.stat().st_mtime_ns

        def measure(name: str, **args) -> dict:
            got = b.request("mass_properties", {"doc": docs[name], **args})
            assert got["units"] == "SI" and got["doc"] == docs[name]
            for m in got["measures"]:
                print(f"\n{name} {m['configuration']}: mass {m.get('mass')}, box {m.get('bbox_m')}, "
                      f"api box {m.get('api_box_m')}, solids {m.get('solid_bodies')}, "
                      f"sheets {m.get('sheet_bodies')}, topology {m.get('solid_topology')}, "
                      f"Check3 {m.get('check3')}, warnings {m.get('warnings')}, {m.get('seconds')} s")
            return got

        for name in ("o02_boxA.SLDPRT", "o11_curved.SLDPRT", "o12_multibody.SLDPRT"):
            got = measure(name)
            assert [m["configuration"] for m in got["measures"]] == ["Default"]
            assert "restored_active_configuration" not in got
            m = got["measures"][0]
            assert m["active"] is True and m["shown"] is False and m["warnings"] == []
            assert _against_truth(m, _truth(name), mass=True) == [], m
            faces = sum(body["faces"] for body in _truth(name)["bodies"])
            assert m["solid_topology"]["faces"] == faces and m["check3"]["faults"] == 0
        # Every configuration, the active one shown again at the end.
        dirty_before = b.request("document_info", {"doc": docs["o13_two_geometry_configs.SLDPRT"]})["dirty"]
        got = measure("o13_two_geometry_configs.SLDPRT", all_configurations=True)
        assert [m["configuration"] for m in got["measures"]] == ["Default", "Tall"]
        for m in got["measures"]:
            truth = _truth("o13_two_geometry_configs.SLDPRT", m["configuration"])
            assert _against_truth(m, truth, mass=True) == [], m
        assert got["restored_active_configuration"] is True
        info = b.request("document_info", {"doc": docs["o13_two_geometry_configs.SLDPRT"]})
        assert info["active_configuration"] == "Default"
        # Whether showing the active one again clears the changed mark is not known: printed.
        print(f"o13 dirty before mass_properties {dirty_before}, in its reply {got['dirty']}, "
              f"after it {info['dirty']}")
        # One configuration by name; a material's density in the mass.
        got = measure("o06_boxA_props_mat_cfg.SLDPRT", configuration="OracleAlt")
        truth = _truth("o06_boxA_props_mat_cfg.SLDPRT", "OracleAlt")
        assert _against_truth(got["measures"][0], truth, mass=True) == []
        with pytest.raises(BridgeRequestError) as caught:
            measure("o06_boxA_props_mat_cfg.SLDPRT", configuration="Nope")
        assert caught.value.code == "not_found"
        # No body: no mass, said so.
        m = measure("o01_empty.SLDPRT")["measures"][0]
        assert m["solid_bodies"] == m["sheet_bodies"] == 0 and m["bbox_m"] is None
        assert m["mass"]["valid"] is False and "no_visible_solids" in m["warnings"]
        # An assembly: its components' bodies moved into its coordinates, from the copies beside it.
        m = measure(assembly)["measures"][0]
        assert _against_truth(m, _truth(assembly), mass=True) == [], m
        parts_in = m["assembly"]
        assert parts_in["part_components"] == 2 and parts_in["unresolved"] == 0
        assert parts_in["paths_elsewhere"] == 0, "a component came from outside the copies' folder"
        assert m["solid_bodies"] == 2 and m["warnings"] == []
        with pytest.raises(BridgeRequestError) as caught:
            b.request("mass_properties", {"doc": 999})
        assert caught.value.code == "not_found"
        for name in (assembly, *parts):
            b.request("close_document", {"doc": docs[name]})
        folder_times["documents closed"] = src.stat().st_mtime_ns
        ended = b.request("exit_solidworks")
    assert ended["ended"] == "job_terminated" and ended["documents_open"] == 0, ended
    assert _gone(sw_pid, 60)
    folder_times["instance ended"] = src.stat().st_mtime_ns
    print(f"modification time of the copies' folder, ns: {folder_times}")
    assert {p.name: p.read_bytes() for p in src.iterdir()} == before, "a source changed, or a file appeared"
    # A document mass_properties showed another configuration of is changed while open: no
    # auto-recover copy of it, or a backup, is left for the next start.
    changed = _file_changes(recovery, _recovery(_solidworks_files()))
    print(f"auto-recover and backup folders: {changed or 'unchanged'}")
    if not others:  # while another SOLIDWORKS runs, SolidSeas' has no auto-recover and the changes are its
        assert not changed, "an auto-recover copy or a backup appeared"
    assert others <= _solidworks_pids()


def test_test_session_touches_only_its_own_documents_and_never_saves():
    code = re.sub(r"//[^\n]*", "", (build.SOURCE_DIR / "TestSession.cs").read_text(encoding="utf-8"))
    for forbidden in (".Save3(", ".Save2(", ".Save(", "SaveAs", "CloseDoc(", "CloseAllDocuments", "ExitApp",
                      "SetUserPreference", "LoadFile", "Import", "GetActiveObject", "TerminateJobObject"):
        assert forbidden not in code, forbidden
    # QuitDoc twice: the close operation and the clean-up at detach, both on its own documents.
    assert code.count("QuitDoc(") == 2
    assert "testDocuments.TryGetValue(key, out doc)" in code and "it may be the person's" in code
    assert "CloseTestDocuments();" in (build.SOURCE_DIR / "Live.cs").read_text(encoding="utf-8")
