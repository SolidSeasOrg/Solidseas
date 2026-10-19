"""A stand-in for ``SolidSeas.SwBridge.exe`` that speaks its protocol, for the client tests.

Run as ``python swbridge_fake.py --behaviour JSON``. It answers the bridge's
operations without SOLIDWORKS: ``start_solidworks`` starts a sleeping Python
child in place of ``SLDWORKS.exe`` (so a test can see that ending the bridge's
job ends it too), ``open_document`` checks the file exists, and ``save_copy``
writes a few bytes. The behaviour object makes it misbehave on purpose:

* ``no_ready``: never sends the ready line; ``exit_at_start``: exits at once
  with a message on standard error; ``protocol``: the protocol number it claims.
* ``open_delay`` and ``save_delay``: ``{file name: seconds}`` (for a save the
  output's file name) to sleep before answering, as a stuck SOLIDWORKS call does.
* ``open_fail`` and ``save_fail``: file names whose request fails with
  ``open_failed`` or ``save_failed``; ``start_fail``: ``start_solidworks`` fails,
  with ``start_failed`` or the code given (``solidworks_not_activated``).
* ``start_events``: event lines ``start_solidworks`` sends before its reply, as
  the bridge's window watch does when it hides the journal file message box.
* ``import_dialog``: ``{file name: dialog}``: ``import_file`` of that file sends a
  ``window`` event leaving that dialog (``title``, ``text``) and then never
  answers, as a SOLIDWORKS call held by a dialog does; ``import_fail``: file
  names whose import fails with ``import_failed``.

``import_file`` checks its arguments as the bridge does before it calls
SOLIDWORKS, and makes a document whose ``mass_properties`` are those of a 10 x 20
x 30 mm box (``measure``, below), or of the file's own entry in the behaviour's
``measures`` (``{file name: measure}``).

Like the bridge, it ends its stand-in SOLIDWORKS directly (``"ended":
"job_terminated"``, exit code 21331), never through SOLIDWORKS' own shutdown.

Two test operations besides the bridge's own: ``emit`` sends ``count`` event
lines before its reply, as a burst of SOLIDWORKS notifications does, and
``noid`` answers with an error whose id is null, as the bridge does for a line
it could not read.
"""

import json
import os
import subprocess
import sys
import time

behaviour = {}
if len(sys.argv) >= 3 and sys.argv[1] == "--behaviour":
    behaviour = json.loads(sys.argv[2])

out = sys.stdout.buffer


def send(message):
    out.write((json.dumps(message) + "\n").encode("utf-8"))
    out.flush()


if behaviour.get("exit_at_start"):
    sys.stderr.write("fake bridge: refusing to start\n")
    sys.stderr.flush()
    sys.exit(3)
if behaviour.get("no_ready"):
    time.sleep(600)

OPS = [
    "hello", "start_solidworks", "solidworks_info", "open_document", "save_copy", "close_document",
    "mass_properties", "import_file", "exit_solidworks", "shutdown", "sleep", "exit", "emit", "garbage",
    "noid",
]
IMPORTED = (".step", ".stp", ".igs", ".iges", ".x_t", ".x_b")
PREFERENCES = {"swMultiCAD_Enable3DInterconnect": True, "swAlwaysUseDefaultTemplates": True,
               "swImportAutoRunImportDiagnosticsPersist": False, "swImportNeutralAssemblyStructureMapping": 1}


def measure(volume=6e-06, area=0.0022, com=(0.005, 0.01, 0.015), box=(0, 0, 0, 0.01, 0.02, 0.03), solids=1):
    """A measure as the bridge's mass_properties gives one, of a 10 x 20 x 30 mm box by default."""
    return {
        "solid_bodies": solids, "sheet_bodies": 0, "hidden_solid_bodies": 0, "hidden_sheet_bodies": 0,
        "solid_topology": {"faces": 6 * solids, "edges": 12 * solids, "vertices": 8 * solids},
        "sheet_topology": {"faces": 0, "edges": 0, "vertices": 0},
        "check3": {"faults": 0, "bodies_with_faults": 0, "fault_codes": {}, "check_errors": 0},
        "sheet_area_m2": 0.0, "bbox_m": list(box), "bbox_solids_m": list(box), "bbox_all_bodies_m": list(box),
        "bbox_method": "IBody2.GetExtremePoint", "bbox_errors": 0, "api_box_m": list(box),
        "mass": {"api": "IMassProperty2", "volume_m3": volume, "surface_area_m2": area,
                 "center_of_mass_m": list(com), "mass_kg": volume * 1000, "density_kg_m3": 1000.0,
                 "include_hidden": False, "use_system_units": True, "accuracy_level": 2, "overrides": {},
                 "valid": True},
        "warnings": [], "seconds": 0.01,
    }

send({"event": "ready", "protocol": behaviour.get("protocol", 1), "pid": os.getpid(), "apartment": "STA",
      "message_filter": True, "in_job": False, "test_ops": True, "ops": OPS, "bridge_version": "fake"})

child = None
docs = {}
next_doc = 1


class Fail(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.details = details


ENDED_EXIT_CODE = 0x5353  # the exit code the bridge gives the processes of its job when it ends them


def end_child():
    global child
    if child is None:
        return {"ended": "not_started"}
    pid = child.pid
    closed = len(docs)
    child.kill()
    child.wait()
    child = None
    docs.clear()
    return {"ended": "job_terminated", "pid": pid, "exit_code": ENDED_EXIT_CODE, "documents_closed": closed,
            "documents_open": 0, "windows_hidden": 0}


def handle(op, args):
    global child, next_doc
    if op == "hello":
        return {"protocol": 1, "solidworks": child.pid if child else None}
    if op == "start_solidworks":
        fail = behaviour.get("start_fail")
        if fail:
            raise Fail(fail if isinstance(fail, str) else "start_failed", "fake SOLIDWORKS would not start")
        if child is not None:
            raise Fail("refused", "already started")
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(600)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for event in behaviour.get("start_events", []):
            send(dict(event, pid=child.pid))
        return {"pid": child.pid, "revision": "fake", "visible": False, "user_control": False, "in_job": True}
    if op == "solidworks_info":
        if child is None:
            raise Fail("not_started", "start_solidworks first")
        return {"pid": child.pid, "document_count": len(docs), "documents": [], "step_ap": 214}
    if op == "open_document":
        path = args["path"]
        name = os.path.basename(path)
        time.sleep(behaviour.get("open_delay", {}).get(name, 0))
        if name in behaviour.get("open_fail", []):
            details = {"errors": 2, "warnings": 0, "error_names": ["swFileNotFoundError"]}
            raise Fail("open_failed", "OpenDoc6 failed for " + path, details)
        if not os.path.isfile(path):
            raise Fail("not_found", "no such file: " + path)
        handle_ = next_doc
        next_doc += 1
        docs[handle_] = path
        return {"doc": handle_, "path": path, "title": name, "type": "part", "read_only": True}
    if op == "save_copy":
        if args["doc"] not in docs:
            raise Fail("not_found", "no document")
        target = args["path"]
        name = os.path.basename(target)
        time.sleep(behaviour.get("save_delay", {}).get(name, 0))
        if name in behaviour.get("save_fail", []):
            raise Fail("save_failed", "SaveAs3 failed", {"errors": 1, "warnings": 0})
        if target.lower().endswith(".gltf"):
            # As SOLIDWORKS does: a folder named after the file, lowercased, holding the .gltf
            # and its .bin.
            stem = os.path.splitext(name)[0].lower()
            folder = os.path.join(os.path.dirname(target), stem)
            if os.path.isdir(folder) and not args.get("overwrite"):
                raise Fail("refused", "output exists")
            os.makedirs(folder, exist_ok=True)
            files = [os.path.join(folder, stem + ".gltf"), os.path.join(folder, "data.bin")]
            for f in files:
                with open(f, "wb") as fh:
                    fh.write(b"fake gltf of " + docs[args["doc"]].encode("utf-8"))
            result = {"doc": args["doc"], "path": files[0], "files": files,
                      "bytes": sum(os.path.getsize(f) for f in files), "errors": 0}
            return result
        if os.path.exists(target) and not args.get("overwrite"):
            raise Fail("refused", "output exists")
        with open(target, "wb") as f:
            f.write(b"fake export of " + docs[args["doc"]].encode("utf-8"))
        result = {"doc": args["doc"], "path": target, "bytes": os.path.getsize(target), "errors": 0}
        if target.lower().endswith((".step", ".stp")):
            result["step_ap"] = 214
        return result
    if op == "close_document":
        docs.pop(args["doc"], None)
        return {"closed": True}
    if op == "import_file":
        unknown = set(args) - {"path", "method", "template", "map_configuration_data", "allow_network"}
        if unknown:
            raise Fail("invalid_argument", "unknown argument: " + sorted(unknown)[0])
        path = args.get("path") or ""
        name = os.path.basename(path)
        method = args.get("method", "insert")
        if not os.path.isabs(path) or not name.lower().endswith(IMPORTED):
            raise Fail("invalid_argument", "imported are " + " ".join(IMPORTED) + " files")
        if method not in ("insert", "load", "component"):
            raise Fail("invalid_argument", "method is insert, load or component")
        if (method != "load") != ("template" in args):
            raise Fail("invalid_argument", "insert and component take a template, load none")
        if not os.path.isfile(path):
            raise Fail("not_found", "no such file: " + path)
        if child is None:
            raise Fail("not_started", "start_solidworks first")
        facts = {"method": method, "format": "step", "preferences": PREFERENCES}
        if name in behaviour.get("import_dialog", {}):
            dialog = behaviour["import_dialog"][name]
            send({"event": "window", "action": "left", "kind": "dialog", "pid": child.pid, "hwnd": 4242,
                  "class": "#32770", "title": dialog.get("title", ""), "text": dialog.get("text", "")})
            time.sleep(600)
        if name in behaviour.get("import_fail", []):
            details = dict(facts, errors=1, error_names=["swGenericError"], dialogs=[], dialog_appeared=False)
            raise Fail("import_failed", "InsertImportedFeature imported nothing from " + path, details)
        handle_ = next_doc
        next_doc += 1
        docs[handle_] = path
        found = behaviour.get("measures", {}).get(name, measure())
        if method == "component":
            component = {"name": name + "-1", "refers_to_source": False, "document_extension": ".sldprt",
                         "virtual": False, "children": 0, "placed": [1, 0, 0, 0, 1, 0, 0, 0, 1, 0.01, 0, 0],
                         "at_origin": True}
            made = {"title": f"Assem{handle_}", "type": "assembly", "component": component}
        else:
            made = {"title": f"Part{handle_}", "type": "part",
                    "feature": {"name": name + "<1>", "type": "MBimport", "interconnect": True}}
        return dict(facts, doc=handle_, path="", read_only=False, dirty=True, source=path, errors=0,
                    solid_bodies=found["solid_bodies"], sheet_bodies=found["sheet_bodies"],
                    result_kind="solids", dialogs=[], dialog_appeared=False, window_watch=True,
                    seconds=0.1, **made)
    if op == "mass_properties":
        if args.get("doc") not in docs:
            raise Fail("not_found", f"no document {args.get('doc')} opened or created by this bridge")
        name = os.path.basename(docs[args["doc"]])
        found = dict(behaviour.get("measures", {}).get(name, measure()), configuration="Default", active=True,
                     shown=False)
        return {"doc": args["doc"], "type": "part", "units": "SI", "active_configuration": "Default",
                "configurations": ["Default"], "measures": [found], "dirty": False}
    if op in ("exit_solidworks", "shutdown"):
        return end_child()
    if op == "sleep":
        time.sleep(args.get("ms", 1000) / 1000.0)
        return {"slept_ms": args.get("ms", 1000)}
    if op == "exit":
        os._exit(args.get("code", 3))
    if op == "emit":
        for i in range(args.get("count", 1)):
            event = {"event": "document", "doc": 1, "name": "ModifyNotify"}
            if "count" in args:
                event["data"] = {"n": i}
            send(event)
        return {}
    if op == "garbage":
        out.write(b"this is not JSON\n")
        out.flush()
        return {}
    raise Fail("unknown_op", "no operation named " + str(op))


for raw in sys.stdin.buffer:
    request = json.loads(raw)
    rid = request.get("id")
    op = request.get("op")
    if op == "noid":
        error = {"code": "bad_request", "message": "request longer than allowed"}
        send({"id": None, "ok": False, "error": error})
        continue
    try:
        result = handle(op, request.get("args") or {})
        send({"id": rid, "ok": True, "result": result})
    except Fail as e:
        error = {"code": e.code, "message": str(e)}
        if e.details:
            error["details"] = e.details
        send({"id": rid, "ok": False, "error": error})
    if op == "shutdown":
        break
end_child()
