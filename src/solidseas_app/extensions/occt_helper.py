"""The OCCT backend's helper: IGES and BREP files read and written through Open CASCADE
(``docs/EXTENSIONS.md`` sections 6 and 9, ``docs/OCCT.md`` tier 1).

It runs as a program of its own, never inside SolidSeas: in the extension's package as
``solidseas-occt.exe`` (this module built by PyInstaller with OCP, the Python bindings of
Open CASCADE), or from a source checkout in an interpreter where OCP imports
(``SOLIDSEAS_OCCT_HELPER_PYTHON``, :mod:`solidseas.convert.occt`). It imports the
standard library and OCP only, never solidseas, and nothing in SolidSeas imports it.

It speaks the helpers' JSON lines (:mod:`solidseas.helpers`): a ready line naming the
helper, its protocol, its operations and the versions of OCP and Open CASCADE, then
requests by id:

* ``convert`` with ``path`` (a file the core staged in a folder of its own), ``from``
  (``iges``, ``occt_brep`` or ``step``), ``to`` (``step``, ``iges`` or ``occt_brep``),
  ``out_dir`` (an empty folder the core gave it) and optionally ``name`` (the product
  name a STEP file gets). It reads the file with the basic readers only (never the XCAF
  readers, which follow references out of the file's folder), sews an IGES file's loose
  faces at 0.01 mm and makes solids of the shells that close, runs OCCT's validity check,
  and writes ``model.step``, ``model.igs`` (BRep mode) or ``model.brep`` into ``out_dir``,
  never over a file. The reply says what was read: solids, shells closed by sewing,
  shells left open, loose faces, whether the result is valid, and for IGES the unit and
  the sending system the file names.
* ``version`` and ``shutdown``.

The rules of ``docs/OCCT.md`` section 3 hold here: file descriptor 1 points at the null
device before OCP is imported, so nothing OCCT prints (it can quote the file) reaches the
core, and the replies go to a copy of the original descriptor; an error says only a fixed
message or an exception's class name, never OCCT's text or a path; a crash or a fault
never shows a dialog or writes a dump (``SetErrorMode`` on Windows, where the core's Job
Object also caps memory and ends the helper on an unhandled exception); elsewhere the
helper caps its own address space (``--memory-mb``), writes no core file and, on Linux,
ends with the process that started it.
"""

import json
import math
import os
import platform
import sys

PROTOCOL = 1
HELPER = "occt"
OPERATIONS = ("convert", "version", "shutdown")
READS = ("iges", "occt_brep", "step")
WRITES = ("step", "iges", "occt_brep")
OUTPUT_NAMES = {"step": "model.step", "iges": "model.igs", "occt_brep": "model.brep"}
SEW_TOLERANCE_MM = 0.01  # docs/OCCT.md tier 1
MAX_REQUEST_BYTES = 4 << 20  # one request line, UTF-8
MAX_NAME = 120
# IGES unit flags (global parameter 14) and the unit each names.
IGES_UNITS = {1: "in", 2: "mm", 4: "ft", 5: "mi", 6: "m", 7: "km", 8: "mil", 9: "micron", 10: "cm", 11: "uin"}


class Refused(ValueError):
    """A request the helper will not carry out, with its protocol code and a fixed message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------- the process
def harden(memory_mb: int | None) -> None:
    """No error box, crash dump or core file for a fault, a cap on memory, and an end with
    the parent (module notes). Run before OCP is imported."""
    if sys.platform == "win32":
        import ctypes

        # SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX
        ctypes.windll.kernel32.SetErrorMode(0x8003)
        return
    import resource

    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if memory_mb:
        # never above what the process that started it allows (a worker's own cap)
        cap = int(memory_mb) << 20
        hard = resource.getrlimit(resource.RLIMIT_AS)[1]
        if hard != resource.RLIM_INFINITY:
            cap = min(cap, hard)
        try:
            resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
        except (OSError, ValueError):  # macOS may refuse it: the cap is then best effort
            pass
    if sys.platform.startswith("linux"):
        import ctypes
        import signal

        try:
            ctypes.CDLL(None).prctl(1, int(signal.SIGKILL))  # PR_SET_PDEATHSIG
        except (OSError, AttributeError):
            pass
        if os.getppid() == 1:  # the parent is already gone
            os._exit(0)


def versions() -> dict:
    import OCP

    out = {"python": platform.python_version(), "ocp": getattr(OCP, "__version__", None)}
    out["occt"] = ".".join(str(out["ocp"]).split(".")[:3]) if out["ocp"] else None
    return out


def _clean(value):
    """``value`` with every float that is not finite turned into None."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


# --------------------------------------------------------------------------- arguments
def _local_file(path, what: str) -> str:
    if not isinstance(path, str) or not path or "\x00" in path:
        raise Refused("refused", f"{what} is not a path")
    if path.startswith(("\\\\", "//")):
        raise Refused("refused", f"{what} is a network path")  # docs/OCCT.md 3: never a network path
    return path


def _arguments(args: dict) -> tuple[str, str, str, str, str | None]:
    if not isinstance(args, dict):
        raise Refused("refused", "the request has no arguments")
    src = _local_file(args.get("path"), "path")
    out_dir = _local_file(args.get("out_dir"), "out_dir")
    fmt_in, fmt_out = args.get("from"), args.get("to")
    if fmt_in not in READS:
        raise Refused("refused", f"from is one of {', '.join(READS)}")
    if fmt_out not in WRITES:
        raise Refused("refused", f"to is one of {', '.join(WRITES)}")
    if os.path.islink(src) or not os.path.isfile(src):
        raise Refused("refused", "path is not a plain file")
    if os.path.islink(out_dir) or not os.path.isdir(out_dir):
        raise Refused("refused", "out_dir is not a folder")
    name = args.get("name")
    if name is not None and (
        not isinstance(name, str)
        or not name.strip()
        or len(name) > MAX_NAME
        or any(ord(c) < 32 or ord(c) > 126 or c == "'" for c in name)
    ):
        name = None  # a product name OCCT writes as it is: plain ASCII only, else its default
    return src, fmt_in, fmt_out, out_dir, name


# --------------------------------------------------------------------------- reading
def _items(shape, kind, avoid=None) -> list:
    from OCP.TopExp import TopExp_Explorer

    ex = TopExp_Explorer(shape, kind) if avoid is None else TopExp_Explorer(shape, kind, avoid)
    out = []
    while ex.More():
        out.append(ex.Current())
        ex.Next()
    return out


def _compound(shapes):
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    c = TopoDS_Compound()
    b = BRep_Builder()
    b.MakeCompound(c)
    for s in shapes:
        b.Add(c, s)
    return c


def _text(handle) -> str | None:
    """A ``TCollection_HAsciiString`` handle's text, or None."""
    try:
        if handle is None:
            return None
        value = handle.ToCString()
    except Exception:
        return None
    value = value.strip() if isinstance(value, str) else None
    return value[:200] if value else None


def _read_iges(path: str, report: dict):
    from OCP.IFSelect import IFSelect_ReturnStatus
    from OCP.IGESControl import IGESControl_Controller, IGESControl_Reader
    from OCP.Interface import Interface_Static

    IGESControl_Controller.Init_s()
    # Blanked entities are construction geometry the sending system hides: left out, as
    # SolidSeas leaves out the bodies SOLIDWORKS hides.
    Interface_Static.SetIVal_s("read.iges.onlyvisible", 1)
    reader = IGESControl_Reader()
    if reader.ReadFile(path) != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise Refused("read_failed", "Open CASCADE could not read the IGES file")
    try:
        g = reader.IGESModel().GlobalSection()
        flag = g.UnitFlag()
        report["unit"] = IGES_UNITS.get(flag)
        report["unit_name"] = _text(g.UnitName())
        report["application"] = {"name": _text(g.SystemId()), "version": _text(g.InterfaceVersion())}
    except Exception:
        report["unit"] = None
    report["roots"] = reader.NbRootsForTransfer()
    reader.TransferRoots()
    report["shapes"] = reader.NbShapes()
    if reader.NbShapes() == 0:
        raise Refused("no_geometry", "the IGES file holds no surfaces or solids Open CASCADE could read")
    return reader.OneShape()


def _read_step(path: str, report: dict):
    from OCP.IFSelect import IFSelect_ReturnStatus
    from OCP.STEPControl import STEPControl_Reader

    reader = STEPControl_Reader()  # the basic reader: it follows no external reference
    if reader.ReadFile(path) != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise Refused("read_failed", "Open CASCADE could not read the STEP file")
    report["roots"] = reader.NbRootsForTransfer()
    reader.TransferRoots()
    report["shapes"] = reader.NbShapes()
    if reader.NbShapes() == 0:
        raise Refused("no_geometry", "the STEP file holds no shape Open CASCADE could read")
    return reader.OneShape()


def brep_kind(head: bytes) -> str | None:
    """``text`` or ``binary`` for the start of an OCCT BREP file, else None."""
    text = head.lstrip()
    if text.startswith(b"DBRep_DrawableShape"):
        text = text[len(b"DBRep_DrawableShape") :].lstrip()
    if text.startswith(b"CASCADE Topology V"):
        return "text"
    if text.startswith(b"Open CASCADE Topology V"):
        return "binary"
    return None


def _read_brep(path: str, report: dict):
    from OCP.BinTools import BinTools
    from OCP.BRep import BRep_Builder
    from OCP.BRepTools import BRepTools
    from OCP.TopoDS import TopoDS_Shape

    with open(path, "rb") as fh:
        kind = brep_kind(fh.read(256))
    if kind is None:
        raise Refused("read_failed", "the file is not an Open CASCADE BREP file")
    shape = TopoDS_Shape()
    ok = BinTools.Read_s(shape, path) if kind == "binary" else BRepTools.Read_s(shape, path, BRep_Builder())
    if not ok or shape.IsNull():
        raise Refused("read_failed", "Open CASCADE could not read the BREP file")
    report["variant"] = kind
    return shape


def _sew(shape, report: dict):
    """An IGES file's shape as solids: those it holds, and those its loose faces make once
    sewn at :data:`SEW_TOLERANCE_MM` and closed; the shells that stay open and the faces
    that join nothing are kept as they are (docs/OCCT.md tier 1)."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.BRepLib import BRepLib
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID
    from OCP.TopoDS import TopoDS

    solids = _items(shape, TopAbs_SOLID)
    loose = _items(shape, TopAbs_FACE, TopAbs_SOLID)
    report["solids_read"] = len(solids)
    report["loose_faces_read"] = len(loose)
    closed, open_shells, free = [], [], []
    if loose:
        sew = BRepBuilderAPI_Sewing(SEW_TOLERANCE_MM)
        for f in loose:
            sew.Add(f)
        sew.Perform()
        sewn = sew.SewedShape()
        for sh in _items(sewn, TopAbs_SHELL):
            shell = TopoDS.Shell_s(sh)
            if BRep_Tool.IsClosed_s(shell):
                made = BRepBuilderAPI_MakeSolid(shell)
                if made.IsDone():
                    solid = made.Solid()
                    BRepLib.OrientClosedSolid_s(solid)
                    closed.append(solid)
                    continue
            open_shells.append(shell)
        free = _items(sewn, TopAbs_FACE, TopAbs_SHELL)
    report["solids_sewn"] = len(closed)
    report["open_shells"] = len(open_shells)
    report["free_faces"] = len(free)
    return _compound(solids + closed + open_shells + free)


def _census(shape, report: dict) -> None:
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID

    report["solids"] = len(_items(shape, TopAbs_SOLID))
    report["shells"] = len(_items(shape, TopAbs_SHELL))
    report["faces"] = len(_items(shape, TopAbs_FACE))
    try:
        report["valid"] = bool(BRepCheck_Analyzer(shape).IsValid())
    except Exception:
        report["valid"] = None


# --------------------------------------------------------------------------- writing
def _write(shape, fmt: str, target: str, name: str | None) -> None:
    from OCP.Interface import Interface_Static

    if fmt == "step":
        from OCP.IFSelect import IFSelect_ReturnStatus
        from OCP.STEPControl import STEPControl_AsIs, STEPControl_Controller, STEPControl_Writer

        STEPControl_Controller.Init_s()
        Interface_Static.SetCVal_s("write.step.unit", "MM")
        Interface_Static.SetCVal_s("write.step.product.name", name or "model")
        writer = STEPControl_Writer()
        if writer.Transfer(shape, STEPControl_AsIs) != IFSelect_ReturnStatus.IFSelect_RetDone:
            raise Refused("write_failed", "Open CASCADE could not make a STEP model of the shape")
        ok = writer.Write(target) == IFSelect_ReturnStatus.IFSelect_RetDone
    elif fmt == "iges":
        from OCP.IGESControl import IGESControl_Controller, IGESControl_Writer
        from OCP.TCollection import TCollection_HAsciiString

        IGESControl_Controller.Init_s()
        Interface_Static.SetIVal_s("write.iges.brep.mode", 1)  # BRep (MSBO): solids stay solids
        writer = IGESControl_Writer("MM", 1)
        if not writer.AddShape(shape):
            raise Refused("write_failed", "Open CASCADE could not make an IGES model of the shape")
        writer.ComputeModel()
        # The header names no one and no folder: OCCT would put the account's login name in it.
        model = writer.Model()
        g = model.GlobalSection()
        g.SetAuthorName(TCollection_HAsciiString(""))
        g.SetCompanyName(TCollection_HAsciiString(""))
        g.SetFileName(TCollection_HAsciiString(OUTPUT_NAMES["iges"]))
        g.SetSendName(TCollection_HAsciiString(name or "model"))
        model.SetGlobalSection(g)
        ok = bool(writer.Write(target))
    else:
        from OCP.BRepTools import BRepTools

        ok = bool(BRepTools.Write_s(shape, target))
    if not ok or not os.path.isfile(target):
        raise Refused("write_failed", "Open CASCADE could not write the file")


def convert(args: dict) -> dict:
    """Carry out a ``convert`` request (module notes) and return its result."""
    src, fmt_in, fmt_out, out_dir, name = _arguments(args)
    target = os.path.join(out_dir, OUTPUT_NAMES[fmt_out])
    if os.path.lexists(target):
        raise Refused("refused", f"{OUTPUT_NAMES[fmt_out]} is already in out_dir")
    report: dict = {"from": fmt_in}
    if fmt_in == "iges":
        shape = _sew(_read_iges(src, report), report)
    elif fmt_in == "step":
        shape = _read_step(src, report)
    else:
        shape = _read_brep(src, report)
    _census(shape, report)
    if report["faces"] == 0:
        raise Refused("no_geometry", "the file holds curves or points only, no surfaces or solids")
    _write(shape, fmt_out, target, name)
    return {"path": target, "bytes": os.path.getsize(target), "format": fmt_out, "report": report}


# --------------------------------------------------------------------------- the conversation
def _memory_mb(argv: list[str]) -> int | None:
    if "--memory-mb" in argv:
        i = argv.index("--memory-mb")
        try:
            value = int(argv[i + 1])
        except (IndexError, ValueError):
            return None
        return value if value > 0 else None
    return None


def serve(read_line, say) -> int:
    """The request loop: ``read_line()`` gives one request line as bytes (b"" at the end)
    and ``say(dict)`` sends one line. Returns the exit code."""
    while True:
        line = read_line()
        if not line:
            return 0
        if len(line) > MAX_REQUEST_BYTES:
            while line and not line.endswith(b"\n"):  # the rest of that line is not a request
                line = read_line()
            say({"id": None, "ok": False, "error": {"code": "invalid_request", "message": "too long"}})
            continue
        try:
            message = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            say({"id": None, "ok": False, "error": {"code": "invalid_request", "message": "not JSON"}})
            continue
        if not isinstance(message, dict):
            say({"id": None, "ok": False, "error": {"code": "invalid_request", "message": "not an object"}})
            continue
        rid, op = message.get("id"), message.get("op")
        if op == "shutdown":
            say({"id": rid, "ok": True, "result": {}})
            return 0
        try:
            if op == "convert":
                result = convert(message.get("args") or {})
            elif op == "version":
                result = {"versions": versions()}
            else:
                say({"id": rid, "ok": False, "error": {"code": "unknown_op", "message": "no such operation"}})
                continue
            say({"id": rid, "ok": True, "result": _clean(result)})
        except Refused as exc:
            say({"id": rid, "ok": False, "error": {"code": exc.code, "message": str(exc)}})
        except MemoryError:
            say({"id": rid, "ok": False, "error": {"code": "out_of_memory", "message": "MemoryError"}})
        except Exception as exc:  # the class only: OCCT's message can quote the file
            say({"id": rid, "ok": False, "error": {"code": "failed", "message": type(exc).__name__}})


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - runs as the helper's own process
    argv = list(sys.argv[1:] if argv is None else argv)
    harden(_memory_mb(argv))
    out_fd = os.dup(1)
    null = os.open(os.devnull, os.O_WRONLY)
    os.dup2(null, 1)  # whatever OCCT prints goes nowhere
    sys.stdout = open(os.devnull, "w", encoding="utf-8")

    def say(message: dict) -> None:
        data = memoryview((json.dumps(message, allow_nan=False) + "\n").encode("utf-8"))
        while data:
            data = data[os.write(out_fd, data) :]

    try:
        found = versions()
    except Exception as exc:
        sys.stderr.write(f"{type(exc).__name__}: OCP does not import here\n")
        return 3
    say(
        {
            "event": "ready",
            "protocol": PROTOCOL,
            "helper": HELPER,
            "operations": list(OPERATIONS),
            "reads": list(READS),
            "writes": list(WRITES),
            "versions": found,
        }
    )
    stdin = sys.stdin.buffer
    code = serve(lambda: stdin.readline(MAX_REQUEST_BYTES + 1), say)
    os._exit(code)  # skip OCCT's teardown: every answer is out


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = [
    "HELPER",
    "OPERATIONS",
    "OUTPUT_NAMES",
    "PROTOCOL",
    "READS",
    "SEW_TOLERANCE_MM",
    "WRITES",
    "Refused",
    "brep_kind",
    "convert",
    "harden",
    "main",
    "serve",
    "versions",
]
