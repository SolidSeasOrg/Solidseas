"""The opt-in OCCT oracle: Open CASCADE (OCCT 7.9.3 through OCP, the bindings the
``cadquery-ocp`` wheel ships) as an independent kernel that reads the STEP files
SolidSeas writes and the ones it reads, and measures them exactly. ``tests/README.md``
says how to run it; ``test_occt_oracle.py`` and ``test_occt_corpus.py`` are the tiers.

SolidSeas never imports OCP, and neither does this module. OCCT runs only in a child
process (``occt_child.py``, the standard library and OCP only), in the interpreter
``SOLIDSEAS_OCCT_PYTHON`` names; the tests that need it are marked ``occt`` and skip
when the variable is unset or ``import OCP`` fails there. OCCT is not safe on every
file: it can crash with an access violation, overflow its stack, hang, or use
gigabytes, so

* on Windows the child is created with a quiet error mode (no error box and no
  Windows Error Reporting, so a native crash ends it at once and writes no crash
  dump; children inherit the mode their parent has when they are created, so this
  process takes it only while it creates one), starts suspended, is put in a Job
  Object of its own (``KILL_ON_JOB_CLOSE``, ``DIE_ON_UNHANDLED_EXCEPTION``, a memory
  cap per process, below-normal priority, and at most two processes, a venv's
  launcher and its interpreter, so that ``WerFault.exe`` cannot start inside it
  either) and only then resumed. Without the quiet mode a crash in the job does not
  end the process: Windows Error Reporting waits on the ``WerFault.exe`` the job
  refuses until the timeout kills it. Elsewhere the child runs in a session of its
  own with ``RLIMIT_AS``, no core file, ``nice`` 10 and, on Linux, ``SIGKILL`` when
  the parent dies, all set before the child's script runs;
* every call has a timeout, after which the whole job (or process group) is killed;
* the request goes in on standard input as JSON and the answer comes back as one
  line, :data:`MARK` then JSON, read strictly (no NaN, a dict, at most
  ``max_reply_bytes``). The child points its file descriptor 1 at the null device
  before it imports OCP, so OCCT's own messages, which can quote the file, never
  reach this process; of standard error only an exception's class name is kept.

:func:`run_child` reports what happened as a :class:`ChildResult`, a crash or a
timeout included, and never raises for the child's sake.

Measurement settings are part of the oracle: OCCT's default
``BRepGProp.VolumeProperties`` and ``SurfaceProperties`` were wrong by up to 8.6 %
on volume and 4.5 % on area on B-spline-heavy parts, so the child measures volume
with Gauss-Kronrod integration (``VolumePropertiesGK``, eps 1e-9, spans split,
centre of mass on) and area adaptively (``SurfaceProperties`` with eps 1e-9), and
can cross-check both against a fine mesh. The version of OCP is pinned
(:data:`PINNED`) and recorded in every reply.

The comparisons (:func:`match_faces`, :func:`match_shells`, :func:`reader_report`,
:func:`reader_kinds`) are plain Python on numbers, so their own tests run without OCCT.
:func:`solidseas_reading` reads a file as the oracle compares it, at a chord or as the
viewer and 3D Print draw it (:data:`DRAWN`).
"""

import json
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

OCCT_PYTHON_ENV = "SOLIDSEAS_OCCT_PYTHON"
CHILD = Path(__file__).with_name("occt_child.py")
MARK = "SOLIDSEAS-OCCT:"
# The versions the tolerances below were measured with. Another version may heal,
# integrate or check differently: test_occt_oracle fails until the pin is moved on purpose.
PINNED = {"cadquery-ocp": "7.9.3.1.1", "occt": "7.9.3"}
DEFAULT_TIMEOUT_S = 300.0
DEFAULT_MEMORY_MB = 3072
DEFAULT_MAX_REPLY_BYTES = 64 << 20
# The one message OCCT's shape healing may give on transfer: a closed periodic face
# written whole, without a seam edge (docs/formats/step.md, the oracle).
ALLOWED_HEALING = frozenset({"Missing seam-edge added"})

_WINDOWS = sys.platform == "win32"
_EXC_LINE = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Warning))(?::|$)")
_CRASH_CODES = {
    0xC0000005: "access_violation",
    0xC00000FD: "stack_overflow",
    0xC0000409: "fail_fast",
    0xC0000374: "heap_corruption",
    0xC0000017: "no_memory",
    0xC000001D: "illegal_instruction",
    0xC0000094: "integer_divide_by_zero",
    0xC0000420: "assertion",
    0xE06D7363: "cpp_exception",
}


@dataclass
class ChildResult:
    """What one child run gave: ``status`` is ``ok``, ``error`` (the child answered with
    an exception's class name, or died of one), ``memory`` (it ran out of memory under
    the cap), ``crash`` (it ended natively; ``crash`` names the code), ``timeout``,
    ``no_result`` (it ended cleanly without answering) or ``bad_reply`` (its answer
    broke the protocol). ``reply`` is the answer, ``peak_mb`` the job's peak memory
    per process (Windows only)."""

    status: str
    returncode: int | None
    seconds: float
    reply: dict | None = None
    exception: str | None = None
    crash: str | None = None
    peak_mb: float | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def describe(self) -> str:
        """A line for an assertion message: numbers and class names only."""
        bits = [self.status, f"rc {self.returncode}", f"{self.seconds:.1f} s"]
        if self.exception:
            bits.append(self.exception)
        if self.crash:
            bits.append(self.crash)
        if self.peak_mb is not None:
            bits.append(f"peak {self.peak_mb:.0f} MB")
        versions = (self.reply or {}).get("versions")
        if versions:
            bits.append(f"OCP {versions.get('cadquery-ocp')}, OCCT {versions.get('occt')}")
        return ", ".join(bits)


# --------------------------------------------------------------------------- the interpreter
def occt_python() -> str | None:
    """The interpreter ``SOLIDSEAS_OCCT_PYTHON`` names, when it is a file."""
    value = os.environ.get(OCCT_PYTHON_ENV, "").strip()
    return value if value and os.path.isfile(value) else None


@lru_cache(maxsize=1)
def probe() -> ChildResult | None:
    """One ``version`` call in the OCCT interpreter, made once per test session: None
    when ``SOLIDSEAS_OCCT_PYTHON`` names no interpreter."""
    python = occt_python()
    if python is None:
        return None
    return run_child({"op": "version"}, python=python, timeout_s=120.0, memory_mb=1024)


def skip_reason() -> str | None:
    """Why the OCCT tests cannot run here, or None when they can."""
    if occt_python() is None:
        return f"{OCCT_PYTHON_ENV} does not name an interpreter where OCP imports"
    got = probe()
    if got is None or not got.ok:
        what = got.describe() if got else "none"
        return f"import OCP fails in the interpreter {OCCT_PYTHON_ENV} names ({what})"
    return None


def versions() -> dict:
    got = probe()
    return dict((got.reply or {}).get("versions") or {}) if got else {}


# --------------------------------------------------------------------------- running the child
if _WINDOWS:
    import ctypes
    from ctypes import wintypes

    class _Basic(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _Extended(ctypes.Structure):
        _fields_ = [
            ("Basic", _Basic),
            ("Io", ctypes.c_ulonglong * 6),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
    _k32.SetInformationJobObject.restype = wintypes.BOOL
    _k32.QueryInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPVOID,
    )
    _k32.QueryInformationJobObject.restype = wintypes.BOOL
    _k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    _k32.AssignProcessToJobObject.restype = wintypes.BOOL
    _k32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    _k32.TerminateJobObject.restype = wintypes.BOOL
    _k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _k32.CloseHandle.restype = wintypes.BOOL
    _k32.SetErrorMode.argtypes = (wintypes.UINT,)
    _k32.SetErrorMode.restype = wintypes.UINT
    _ntdll = ctypes.WinDLL("ntdll")
    _ntdll.NtResumeProcess.argtypes = (wintypes.HANDLE,)
    _ntdll.NtResumeProcess.restype = ctypes.c_long

    _ACTIVE_PROCESS = 0x8
    _PRIORITY_CLASS = 0x20
    _PROCESS_MEMORY = 0x100
    _DIE_ON_UNHANDLED_EXCEPTION = 0x400
    _KILL_ON_JOB_CLOSE = 0x2000
    _BELOW_NORMAL = 0x4000
    _CREATE_SUSPENDED = 0x4
    _CREATE_NO_WINDOW = 0x08000000
    _EXTENDED_INFO = 9
    # SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX: no error box
    # and no Windows Error Reporting, so no crash dump. A child inherits its parent's mode
    # when it is created, so this process holds it only while it creates one.
    _QUIET_ERROR_MODE = 0x8003
    _error_mode_lock = threading.Lock()

    class _Job:
        """A Job Object for one child (see the module notes)."""

        def __init__(self, memory_mb: int, processes: int = 2) -> None:
            handle = _k32.CreateJobObjectW(None, None)
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            self.handle = handle
            info = _Extended()
            info.Basic.LimitFlags = (
                _KILL_ON_JOB_CLOSE
                | _DIE_ON_UNHANDLED_EXCEPTION
                | _PROCESS_MEMORY
                | _ACTIVE_PROCESS
                | _PRIORITY_CLASS
            )
            info.Basic.ActiveProcessLimit = processes
            info.Basic.PriorityClass = _BELOW_NORMAL
            info.ProcessMemoryLimit = int(memory_mb) << 20
            if not _k32.SetInformationJobObject(
                handle, _EXTENDED_INFO, ctypes.byref(info), ctypes.sizeof(info)
            ):
                error = ctypes.WinError(ctypes.get_last_error())
                self.close()
                raise error

        def adopt(self, proc: subprocess.Popen) -> None:
            """Put the suspended ``proc`` in the job, then let it run."""
            if not _k32.AssignProcessToJobObject(self.handle, int(proc._handle)):
                raise ctypes.WinError(ctypes.get_last_error())
            if _ntdll.NtResumeProcess(int(proc._handle)) != 0:
                raise OSError("NtResumeProcess failed")

        def peak_mb(self) -> float | None:
            q = _Extended()
            if not _k32.QueryInformationJobObject(
                self.handle, _EXTENDED_INFO, ctypes.byref(q), ctypes.sizeof(q), None
            ):
                return None
            return q.PeakProcessMemoryUsed / (1 << 20)

        def kill(self) -> None:
            _k32.TerminateJobObject(self.handle, 1)

        def close(self) -> None:
            if self.handle:
                _k32.CloseHandle(self.handle)  # KILL_ON_JOB_CLOSE ends anything still in it
                self.handle = None


# Applied in the child before its script runs, on systems without Job Objects.
_POSIX_BOOT = r"""
import os, runpy, sys
mb = int(sys.argv[1])
try:
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if mb:
        resource.setrlimit(resource.RLIMIT_AS, (mb << 20, mb << 20))
except (ImportError, OSError, ValueError):
    pass
try:
    os.nice(10)
except OSError:
    pass
if sys.platform.startswith("linux"):
    try:
        import ctypes, signal
        ctypes.CDLL(None, use_errno=True).prctl(1, int(signal.SIGKILL), 0, 0, 0)
    except (OSError, AttributeError):
        pass
sys.argv = sys.argv[2:]
runpy.run_path(sys.argv[0], run_name="__main__")
"""


def _child_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _exception_name(err: bytes) -> str | None:
    """The class name of the last exception a traceback on standard error names: the
    rest of its text can quote a path or the file, and is dropped."""
    name = None
    for line in err.decode("utf-8", "replace").splitlines():
        m = _EXC_LINE.match(line.strip())
        if m and not line.startswith((" ", "\t")):
            name = m.group(1).rsplit(".", 1)[-1]
    return name


def _refuse_constant(name: str) -> None:
    raise ValueError(f"{name} is not strict JSON")


def parse_reply(out: bytes, max_reply_bytes: int = DEFAULT_MAX_REPLY_BYTES) -> tuple[dict | None, str | None]:
    """The child's one answer line from its standard output: ``(reply, None)``, or
    ``(None, why)`` when there is none or it breaks the protocol."""
    if len(out) > max_reply_bytes:
        return None, "the output is larger than max_reply_bytes"
    lines = [ln for ln in out.decode("utf-8", "replace").splitlines() if ln.startswith(MARK)]
    if not lines:
        return None, "no answer line"
    if len(lines) > 1:
        return None, "more than one answer line"
    try:
        reply = json.loads(lines[0][len(MARK) :], parse_constant=_refuse_constant)
    except ValueError:
        return None, "the answer is not strict JSON"
    if not isinstance(reply, dict):
        return None, "the answer is not an object"
    return reply, None


def run_child(
    request: dict,
    *,
    python: str | None = None,
    script: str | os.PathLike | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    memory_mb: int = DEFAULT_MEMORY_MB,
    max_reply_bytes: int = DEFAULT_MAX_REPLY_BYTES,
) -> ChildResult:
    """Run ``script`` (``occt_child.py``) in ``python`` (``SOLIDSEAS_OCCT_PYTHON``) with
    ``request`` on its standard input, inside a Job Object (see the module notes)."""
    python = python or occt_python()
    if python is None:
        raise RuntimeError(f"{OCCT_PYTHON_ENV} is not set")
    script = str(script or CHILD)
    data = (json.dumps(request, allow_nan=False) + "\n").encode("utf-8")
    flags = ["-I", "-B", "-X", "utf8"]
    job = None
    t0 = time.perf_counter()
    if _WINDOWS:
        job = _Job(memory_mb)
        try:
            with _error_mode_lock:
                previous = _k32.SetErrorMode(_QUIET_ERROR_MODE)
                try:
                    proc = subprocess.Popen(
                        [python, *flags, script],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        env=_child_env(),
                        cwd=tempfile.gettempdir(),
                        creationflags=_CREATE_SUSPENDED | _CREATE_NO_WINDOW | _BELOW_NORMAL,
                    )
                finally:
                    _k32.SetErrorMode(previous)
        except BaseException:
            job.close()
            raise
        try:
            job.adopt(proc)
        except BaseException:
            proc.kill()  # still suspended, outside the job: never let it run
            proc.communicate()
            job.close()
            raise
    else:
        proc = subprocess.Popen(
            [python, *flags, "-c", _POSIX_BOOT, str(int(memory_mb)), script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_child_env(),
            cwd=tempfile.gettempdir(),
            start_new_session=True,
        )
    timed_out = False
    try:
        try:
            out, err = proc.communicate(data, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            if job is not None:
                job.kill()
            else:
                import signal

                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    proc.kill()
            out, err = proc.communicate()
        seconds = time.perf_counter() - t0
        peak = job.peak_mb() if job is not None else None
    finally:
        if job is not None:
            job.close()
    rc = proc.returncode
    reply, why = parse_reply(out, max_reply_bytes)
    exc = _exception_name(err)
    res = ChildResult("ok", rc, seconds, reply, exc, None, peak)
    if timed_out:
        res.status = "timeout"
        res.reply = None
        return res
    if reply is not None and rc == 0:
        if reply.get("error"):
            res.status = "error"
            res.exception = str(reply["error"])[:80]
        return res
    if why and why != "no answer line":
        res.status = "bad_reply"
        res.notes.append(why)
        return res
    code = (rc or 0) & 0xFFFFFFFF
    near_cap = peak is not None and peak >= 0.97 * memory_mb
    if rc == 0:
        res.status = "no_result"
    elif exc == "MemoryError":
        res.status = "memory"
    elif exc is not None and rc == 1:
        res.status = "error"
    elif _WINDOWS and code in _CRASH_CODES:
        res.status = "memory" if near_cap else "crash"
        res.crash = _CRASH_CODES[code]
    elif not _WINDOWS and rc is not None and rc < 0:
        res.status = "crash"
        res.crash = f"signal {-rc}"
    else:
        res.status = "memory" if near_cap else "crash"
        res.crash = hex(code)
    return res


def call(request: dict, *, timeout_s: float = DEFAULT_TIMEOUT_S, memory_mb: int = DEFAULT_MEMORY_MB) -> dict:
    """``request`` in the OCCT child; its reply, or an AssertionError that says what
    happened instead."""
    got = run_child(request, timeout_s=timeout_s, memory_mb=memory_mb)
    assert got.ok, f"the OCCT child did not answer: {got.describe()}"
    return got.reply


# --------------------------------------------------------------------------- comparisons
def rel(a: float | None, b: float | None) -> float:
    """``|a - b| / |b|``, infinite when either is missing or ``b`` is 0 and ``a`` is not."""
    if a is None or b is None or not (math.isfinite(a) and math.isfinite(b)):
        return math.inf
    if b == 0:
        return 0.0 if a == 0 else math.inf
    return abs(a - b) / abs(b)


def box_deviation(a, b) -> float:
    """The largest difference between two boxes ``[x0, y0, z0, x1, y1, z1]`` over the
    diagonal of ``b``."""
    if not a or not b:
        return math.inf
    d = math.dist(b[:3], b[3:])
    return max(abs(x - y) for x, y in zip(a, b, strict=True)) / d if d else math.inf


@dataclass
class FaceMeasure:
    """One face as measured: ``area`` (m^2), ``centroid`` (m), and, from OCCT, the
    surface type, for a bounded surface the area of the whole surface it lies on, the
    area of OCCT's own mesh of the face (``alt_area``), a second opinion, and the
    surface's smallest radius of curvature where it is known (a cylinder's, a
    sphere's, a torus's)."""

    area: float
    centroid: tuple[float, float, float]
    kind: str | None = None
    surface_area: float | None = None
    alt_area: float | None = None
    min_radius: float | None = None


# The principal directions in which a surface curves: a polygon inscribed in it falls short
# of its area by about a third of the chord over the radius in each (sin(t) / t on an arc
# whose sagitta is the chord), so a cylinder's faces by chord / 3r, a sphere's and a torus's
# by at most twice that over their smallest radius.
CURVED_DIRECTIONS = {"cylinder": 1, "sphere": 2, "torus": 2}
CHORD_MARGIN = 1.5  # on that estimate: a tessellation does not reach its chord everywhere


def _pairs(a_centroids, b_centroids, near: float, cost) -> dict[int, int]:
    """Pairs ``{index in a: index in b}`` of items whose centroids are within ``near``,
    the cheapest first by ``cost(i, j, distance)``, each item in one pair at most."""
    if not near or not math.isfinite(near) or near <= 0:
        return {}
    grid: dict[tuple[int, int, int], list[int]] = {}
    for i, c in enumerate(a_centroids):  # a's items by the cell of side ``near`` their centroid is in
        grid.setdefault(tuple(math.floor(x / near) for x in c), []).append(i)
    cands = []
    for j, c in enumerate(b_centroids):
        cx, cy, cz = (math.floor(x / near) for x in c)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for i in grid.get((cx + dx, cy + dy, cz + dz), ()):
                        d = math.dist(a_centroids[i], c)
                        if d <= near:
                            cands.append((cost(i, j, d), i, j))
    cands.sort()
    took_a: dict[int, int] = {}
    took_b: set[int] = set()
    for _cost, i, j in cands:
        if i in took_a or j in took_b:
            continue
        took_a[i] = j
        took_b.add(j)
    return took_a


def _log_ratio(x: float, y: float) -> float:
    tiny = 1e-30
    return abs(math.log(max(abs(x), tiny) / max(abs(y), tiny)))


def match_faces(
    occt: list[FaceMeasure], ours: list[FaceMeasure], *, tol: float, near: float, chord: float | None = None
) -> dict:
    """Pair every SolidSeas face with an OCCT face and report the faces that disagree.
    ``tol`` is the relative area allowed; ``near`` (metres) how far apart the centroids
    of a pair may be. Pairs are taken cheapest first, the cost being the centroids'
    distance over ``near`` plus how far the areas' ratio is from 1 (as a logarithm),
    so that faces sharing a centroid, such as the two walls of a hollow cylinder, pair by size.

    A face is ``wrong`` when its area is more than ``tol`` from both of OCCT's: each
    can fail on its own (the adaptive integration on some surfaces, a mesh too coarse
    for a small fillet), but the reader's defects put a face far from both. With
    ``chord`` (the tessellation's, metres) a face on a cylinder, sphere or torus may
    also fall short by its polygons' own error, :data:`CHORD_MARGIN` times a third of
    the chord over the surface's smallest radius for each direction in which it curves
    (:data:`CURVED_DIRECTIONS`): a torus fillet of 0.05 mm tessellated at 1.6
    micrometres is 1.1 % short and right. The allowance is one-sided: a polygon is
    never larger than its surface, so a face larger than OCCT's by more than ``tol`` is
    wrong whatever the chord. A face larger than the whole surface it lies on is
    ``folded`` whatever ``tol`` says: its triangles must overlap. The OCCT faces left
    over are ``missing`` (the reader dropped them), the SolidSeas faces left over
    ``extra``."""
    took_o = _pairs(
        [o.centroid for o in occt],
        [s.centroid for s in ours],
        near,
        lambda i, j, d: d / near + _log_ratio(ours[j].area, occt[i].area),
    )
    wrong, folded = [], []
    for i, j in sorted(took_o.items()):
        o, s = occt[i], ours[j]
        short = tol
        if chord and o.min_radius and o.kind in CURVED_DIRECTIONS:
            short += CHORD_MARGIN * CURVED_DIRECTIONS[o.kind] * chord / (3.0 * o.min_radius)
        refs = [o.area] + ([o.alt_area] if o.alt_area is not None and o.alt_area > 0 else [])
        if o.surface_area is not None and s.area > o.surface_area * (1.0 + tol):
            folded.append(
                {"face": i, "kind": o.kind, "area": s.area, "occt": o.area, "surface": o.surface_area}
            )
        if not any(-short <= (s.area - ref) / ref <= tol if ref else s.area == 0 for ref in refs):
            r = min(rel(s.area, ref) for ref in refs)
            wrong.append({"face": i, "kind": o.kind, "area": s.area, "occt": o.area, "rel": r})
    missing = [
        {"face": i, "kind": occt[i].kind, "occt": occt[i].area} for i in range(len(occt)) if i not in took_o
    ]
    took_s = set(took_o.values())
    extra = [{"area": ours[j].area} for j in range(len(ours)) if j not in took_s]
    return {"pairs": len(took_o), "wrong": wrong, "folded": folded, "missing": missing, "extra": extra}


def match_shells(occt: list[dict], ours: list[dict], *, tol: float, near: float | None = None) -> dict:
    """Pair OCCT's shells with SolidSeas' closed mesh pieces, each a dict with its signed
    ``volume`` (m^3) and its ``centroid`` (m), and report the pairs whose signs differ (a
    shell inside out, such as a void that adds its volume) or whose sizes differ by more
    than ``tol``.

    With ``near`` (metres) shells pair as :func:`match_faces` pairs faces: cheapest first,
    by the centroids' distance over ``near`` plus how far the sizes' ratio is from 1 (as a
    logarithm), only within ``near``, so that each void pairs with the void at its place
    and a void at its solid's centre pairs by size. The shells left over on either side
    are counted (``unpaired``). Without ``near``, or where a centroid is missing, shells
    pair by size, largest first, and only when both sides have as many: with a piece too
    many or too few, pairing by size alone would pair everything after it with an
    unrelated shell, so then only the counts are reported."""
    a = [(float(s["volume"]), s.get("centroid")) for s in occt]
    b = [(float(s["volume"]), s.get("centroid")) for s in ours]
    if near and all(c is not None for _v, c in a + b):

        def cost(i: int, j: int, d: float) -> float:
            return d / near + _log_ratio(b[j][0], a[i][0])

        pairs = _pairs([c for _v, c in a], [c for _v, c in b], near, cost)
    elif len(a) == len(b):
        oa = sorted(range(len(a)), key=lambda i: -abs(a[i][0]))
        ob = sorted(range(len(b)), key=lambda j: -abs(b[j][0]))
        pairs = dict(zip(oa, ob, strict=True))
    else:
        pairs = {}
    inverted, wrong = [], []
    for i, j in sorted(pairs.items()):
        o, s = a[i][0], b[j][0]
        if (o > 0) != (s > 0):
            inverted.append({"shell": i, "occt": o, "ours": s})
        elif rel(abs(s), abs(o)) > tol:
            wrong.append({"shell": i, "occt": o, "ours": s})
    return {
        "shells": (len(a), len(b)),
        "pairs": len(pairs),
        "unpaired": (len(a) - len(pairs), len(b) - len(pairs)),
        "inverted": inverted,
        "wrong": wrong,
    }


def _face_measures(positions, triangles, first: int, count: int) -> tuple[float, tuple[float, float, float]]:
    area = gx = gy = gz = 0.0
    for k in range(3 * first, 3 * (first + count), 3):
        ia, ib, ic = triangles[k], triangles[k + 1], triangles[k + 2]
        A = positions[3 * ia : 3 * ia + 3]
        B = positions[3 * ib : 3 * ib + 3]
        C = positions[3 * ic : 3 * ic + 3]
        ux, uy, uz = B[0] - A[0], B[1] - A[1], B[2] - A[2]
        vx, vy, vz = C[0] - A[0], C[1] - A[1], C[2] - A[2]
        cx, cy, cz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        a = 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz)
        area += a
        gx += a * (A[0] + B[0] + C[0]) / 3.0
        gy += a * (A[1] + B[1] + C[1]) / 3.0
        gz += a * (A[2] + B[2] + C[2]) / 3.0
    if area <= 0.0:
        return 0.0, (0.0, 0.0, 0.0)
    return area, (gx / area, gy / area, gz / area)


# What the user sees and prints, as the scene options of a model file: ``viewer`` is the
# reader's own scene, which the viewer draws (1e-3 of the box diagonal, 15 degrees);
# ``print`` is 3D Print's (``export.print_model``: solid bodies only, 2.5e-4 of the
# diagonal and at most 10 micrometres, each object welded by exact coordinates).
DRAWN = ("viewer", "print")


def drawn_options(drawn: str) -> dict:
    """The scene options of ``viewer`` or ``print`` (:data:`DRAWN`), from the library's
    own constants."""
    from solidseas import export

    if drawn == "viewer":
        return {}
    if drawn == "print":
        return {
            "chord_fraction": export.CHORD_FRACTION,
            "max_chord_m": export.MAX_CHORD_M,
            "angle_deg": export.DEFAULT_ANGLE_DEG,
            "body_types": ("solid",),
        }
    raise ValueError(f"drawn is one of {DRAWN}")


@contextmanager
def _tessellations():
    """Every tessellation ``solidseas.tessellate.tessellate_transmit`` makes meanwhile, by
    the id of its transmit: a STEP scene's own, so that the faces measured are the ones
    drawn, at the chord the scene chose. Not for threads."""
    import solidseas.tessellate as T

    real = T.tessellate_transmit
    made: dict[int, tuple] = {}

    def spy(xt, **kw):
        t = real(xt, **kw)
        made[id(xt)] = (xt, t)
        return t

    T.tessellate_transmit = spy
    try:
        yield made
    finally:
        T.tessellate_transmit = real


def _det(r) -> float:
    return (
        r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1])
        - r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0])
        + r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0])
    )


def solidseas_reading(
    src, *, chord_m: float | None = None, drawn: str | None = None, max_seconds: float = 300.0
) -> dict:
    """What SolidSeas' reader makes of a 3D file (a path or its bytes), as the oracle
    compares it, tessellated at ``chord_m`` or as ``drawn`` (:data:`DRAWN`): every face of
    every B-rep body as the scene tessellated it (:class:`FaceMeasure`, placed where the
    scene places it), the connected pieces of every placed mesh object (:func:`mesh_pieces`,
    placed, with whether its body is a solid), the volume of the solids and the area of
    everything the scene holds, the faces it skipped by reason, its warning codes, whether
    the tessellator found every solid closed before the scene turned faces round to agree,
    and the chord it used. ``faces_unmeasured`` counts bodies whose faces could not be
    measured (a scene that tessellates otherwise, at no explicit chord)."""
    from solidseas.formats import open_model
    from solidseas.tessellate import tessellate_transmit

    if (chord_m is None) == (drawn is None):
        raise ValueError("give chord_m or drawn")
    options = {"chord_m": chord_m} if drawn is None else drawn_options(drawn)
    weld = None
    if drawn == "print":
        from solidseas.export import weld
    with open_model(src) as doc, _tessellations() as made:
        scene = doc.scene(prefer="bodies", max_seconds=max_seconds, **options)
        bodies = doc.bodies(max_seconds=max_seconds) or []
    by_node = {b.node: b for b in bodies}
    tessellated: dict = {}
    welded: dict = {}
    faces: list[FaceMeasure] = []
    pieces: list[dict] = []
    volume = area = 0.0
    closed = True
    unmeasured = 0
    chords = {t.chord_m for _xt, t in made.values()}
    for item in scene.items:
        obj = scene.objects[item.object]
        place = item.placement.apply
        det = _det(item.placement.rotation)
        body = by_node.get(obj.node) if obj.source == "bodies" else None
        solid = body is not None and body.body_type == "solid"
        if weld is None:
            positions, triangles = obj.positions, obj.triangles
        else:
            if item.object not in welded:
                welded[item.object] = weld(obj)
            positions, triangles = welded[item.object]
        for p in mesh_pieces(positions, triangles):
            p = {
                **p,
                "volume": p["volume"] * det,
                "area": p["area"] * abs(det) ** (2.0 / 3.0),
                "centroid": place(p["centroid"]),
                "solid": solid,
            }
            pieces.append(p)
            volume += p["volume"] if solid else 0.0
            area += p["area"]
        if body is None:
            continue
        t = tessellated.get(obj.node)
        if t is None:
            got = made.get(id(body.transmit))
            if got is not None:
                t = got[1]
            elif chord_m is not None:
                t = tessellate_transmit(body.transmit, chord_m=chord_m, max_seconds=max_seconds)
                chords.add(chord_m)
            else:
                unmeasured += 1
                continue
            tessellated[obj.node] = t
            closed = closed and t.closed is not False
        pos, tris = t.welded()
        for f in t.mesh.faces:
            a, c = _face_measures(pos, tris, f.first_triangle, f.n_triangles)
            faces.append(FaceMeasure(a, place(c)))
    reasons: dict[str, int] = {}
    for s in scene.skipped:
        key = getattr(s, "reason", "?")
        reasons[key] = reasons.get(key, 0) + 1
    return {
        "faces": faces,
        "pieces": pieces,
        "volume": volume,
        "area": area,
        "skipped": reasons,
        "warnings": sorted({w.code for w in scene.warnings}),
        "closed": closed,
        "truncated": list(scene.truncated),
        "chord_m": chord_m if chord_m is not None else (max(chords) if chords else None),
        "drawn": drawn,
        "faces_unmeasured": unmeasured,
    }


def occt_faces(occt: dict, *, self_tol: float) -> tuple[list[FaceMeasure], int]:
    """OCCT's faces as references, and on how many of them its two measures disagree.

    A face carries its adaptive area and, as ``alt_area``, the area of OCCT's own mesh
    of it (the reply's ``mesh_area``, with a mesh deflection asked for). Where the two
    differ by more than ``self_tol`` one of them has failed: the adaptive integration
    is 1.2 % high on an extrusion of an ellipse (``occt_shapes``), and a mesh whose
    deflection is set by the part's size is coarse beside a small fillet. Such faces
    are counted (``occt_unsure``); :func:`match_faces` takes a SolidSeas face to agree
    with OCCT when it agrees with either."""
    out, unsure = [], 0
    for f in occt.get("faces") or []:
        a, c = f.get("area"), f.get("centroid")
        if a is None or c is None:
            continue
        m = f.get("mesh_area")
        if m is not None and m > 0 and rel(a, m) > self_tol:
            unsure += 1
        out.append(FaceMeasure(a, tuple(c), f.get("kind"), f.get("surface_area"), m, f.get("min_radius")))
    return out, unsure


def reader_report(occt: dict, ours: dict, *, tol: float, self_tol: float = 5e-3) -> dict:
    """SolidSeas' reading of a file (:func:`solidseas_reading`) against OCCT's (the
    child's ``step`` reply with ``faces``, and a mesh for the second opinion of
    :func:`occt_faces`): per face, per shell, in total and the mesh's own soundness.
    The totals, too, are the nearer of OCCT's two measures. :func:`reader_problems`
    lists what disagrees."""
    box = occt.get("box") or [0.0] * 6
    diag = math.dist(box[:3], box[3:]) or 1.0
    o_faces, unsure = occt_faces(occt, self_tol=self_tol)
    faces = match_faces(o_faces, ours["faces"], tol=tol, near=0.05 * diag, chord=ours.get("chord_m"))
    shells = match_shells(
        [s for s in occt.get("shells") or [] if s.get("volume") is not None],
        [p for p in ours["pieces"] if p["solid"]],
        tol=tol,
        near=0.05 * diag,
    )
    volume = occt.get("volume") or 0.0
    volume_rel = rel(ours["volume"], volume) if volume or ours["volume"] else 0.0
    mesh = occt.get("mesh") or {}
    if mesh.get("complete") and volume:
        if rel(volume, mesh.get("volume")) > self_tol:
            unsure += 1  # the Gauss-Kronrod volume and the mesh's disagree
        volume_rel = min(volume_rel, rel(ours["volume"], mesh.get("volume")))
    area_rel = rel(ours["area"], sum(f.area for f in o_faces))
    if o_faces and all(f.alt_area is not None for f in o_faces):
        area_rel = min(area_rel, rel(ours["area"], sum(f.alt_area for f in o_faces)))
    return {
        "faces": faces,
        "shells": shells,
        "volume_rel": volume_rel,
        "area_rel": area_rel,
        "open_edges": sum(p["open"] for p in ours["pieces"] if p["solid"]),
        "doubled_edges": sum(p["doubled"] for p in ours["pieces"]),
        "skipped": ours["skipped"],
        "occt_unsure": unsure,
    }


def reader_problems(report: dict, tol: float) -> list[str]:
    """The disagreements in a :func:`reader_report`, one line each (numbers and surface
    types only); empty when SolidSeas and OCCT agree."""
    out = []
    f = report["faces"]
    for w in f["folded"]:
        out.append(
            f"a {w['kind']} face is larger than its whole surface ({w['area']:.6g} > {w['surface']:.6g} m2)"
        )
    for w in f["wrong"]:
        out.append(
            f"a {w['kind']} face's area is off by {w['rel']:.3g} ({w['area']:.6g} against {w['occt']:.6g})"
        )
    for m in f["missing"]:
        out.append(f"a {m['kind']} face of {m['occt']:.6g} m2 is missing")
    for e in f["extra"]:
        out.append(f"a face of {e['area']:.6g} m2 has no counterpart")
    s = report["shells"]
    if s["shells"][0] != s["shells"][1]:
        out.append(f"{s['shells'][1]} closed pieces against {s['shells'][0]} shells")
    elif any(s["unpaired"]):
        out.append(f"{s['unpaired'][1]} pieces and {s['unpaired'][0]} shells have no counterpart")
    for i in s["inverted"]:
        out.append(f"a shell is inside out ({i['ours']:.6g} against {i['occt']:.6g} m3)")
    for w in s["wrong"]:
        out.append(f"a shell's volume is off ({w['ours']:.6g} against {w['occt']:.6g} m3)")
    for key in ("volume_rel", "area_rel"):
        if report[key] > tol:
            out.append(f"{key} {report[key]:.3g}")
    if report["open_edges"]:
        out.append(f"{report['open_edges']} open edges in solids")
    if report["doubled_edges"]:
        out.append(f"{report['doubled_edges']} edges used twice the same way")
    if report["skipped"]:
        out.append(f"faces skipped: {report['skipped']}")
    return out


# The kinds of disagreement no chord excuses: a polygon is never larger than its surface,
# and at any chord a solid must come out closed, its shells of their signs and every face
# drawn. Whether they happen does depend on the chord, so they are looked for in what the
# viewer and 3D Print draw as well as at the oracle's fine chord, where areas are compared.
SOUNDNESS = ("folded_faces", "shells_inverted", "open_edges", "doubled_edges", "faces_skipped")


def reader_kinds(report: dict, tol: float) -> list[str]:
    """The kinds of disagreement in a :func:`reader_report`, in a fixed order, or
    ``["agree"]``."""
    f, s = report["faces"], report["shells"]
    kinds = []
    for name, hit in (
        ("folded_faces", f["folded"]),
        ("faces_off", f["wrong"]),
        ("faces_missing", f["missing"]),
        ("faces_extra", f["extra"]),
        ("shells_inverted", s["inverted"]),
        ("shells_off", s["wrong"] or s["shells"][0] != s["shells"][1] or any(s["unpaired"])),
        ("volume_off", report["volume_rel"] > tol),
        ("area_off", report["area_rel"] > tol),
        ("open_edges", report["open_edges"]),
        ("doubled_edges", report["doubled_edges"]),
        ("faces_skipped", report["skipped"]),
    ):
        if hit:
            kinds.append(name)
    return kinds or ["agree"]


def mesh_pieces(positions, triangles) -> list[dict]:
    """The connected pieces of a welded mesh (float64 xyz positions, uint32 index
    triples): each piece's signed volume (m^3), area (m^2), ``open`` edges (used one way
    only), ``doubled`` edges (used twice the same way, where triangles fold) and
    ``centroid``: of its volume when it is closed (a void's too: its volume and its
    moment are both negative), else of its area, since an open piece's volume depends on
    where the origin is."""
    n = len(positions) // 3
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for k in range(0, len(triangles), 3):
        a, b, c = find(triangles[k]), find(triangles[k + 1]), find(triangles[k + 2])
        parent[b] = a
        parent[find(c)] = a
    acc: dict[int, list] = {}
    for k in range(0, len(triangles), 3):
        ia, ib, ic = triangles[k], triangles[k + 1], triangles[k + 2]
        root = find(ia)
        A = positions[3 * ia : 3 * ia + 3]
        B = positions[3 * ib : 3 * ib + 3]
        C = positions[3 * ic : 3 * ic + 3]
        ux, uy, uz = B[0] - A[0], B[1] - A[1], B[2] - A[2]
        vx, vy, vz = C[0] - A[0], C[1] - A[1], C[2] - A[2]
        cx, cy, cz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        s = acc.setdefault(root, [0.0, 0.0, {}, [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]])
        v = (A[0] * (B[1] * C[2] - B[2] * C[1]) - A[1] * (B[0] * C[2] - B[2] * C[0])
             + A[2] * (B[0] * C[1] - B[1] * C[0])) / 6.0  # fmt: skip
        a = 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz)
        s[0] += v
        s[1] += a
        for i in range(3):
            g = A[i] + B[i] + C[i]
            s[3][i] += v * g / 4.0  # the tetrahedron on the origin: its centroid is (A + B + C) / 4
            s[4][i] += a * g / 3.0
        for e in ((ia, ib), (ib, ic), (ic, ia)):
            s[2][e] = s[2].get(e, 0) + 1
    out = []
    for volume, area, edges, vm, am in acc.values():
        opened = sum(1 for (a, b) in edges if (b, a) not in edges)
        if not opened and volume != 0.0:
            centroid = tuple(m / volume for m in vm)
        else:
            centroid = tuple(m / area for m in am) if area > 0.0 else (0.0, 0.0, 0.0)
        out.append(
            {
                "volume": volume,
                "area": area,
                "open": opened,
                "doubled": sum(1 for m in edges.values() if m > 1),
                "centroid": centroid,
            }
        )
    out.sort(key=lambda p: -p["area"])
    return out
