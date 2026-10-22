"""The 3D view's mesh reads, in a process of their own.

Reading a display mesh is pure Python and, for a large part, runs for seconds
and takes hundreds of megabytes. Run in the window's process it held the
interpreter lock against the UI thread (repaints of the file list took a
median 205 ms instead of 24 while a large mesh read), it could not be stopped
partway, and a crafted part could make it take gigabytes. So it runs in a
child process (:class:`MeshReader`), started with ``multiprocessing`` the
first time a mesh is wanted and kept for the next one:

* The window's process only waits on a pipe, in a worker thread, without the
  interpreter lock, and receives the finished vertex and index buffers.
* Cancelling a read that is running (another document selected, the 3D view
  turned off, the window closed) ends the child at once; the next read starts
  a new one.
* On Windows the child runs in a job object: at most :func:`memory_limit`
  bytes of memory, below-normal priority, and ended with the viewer even if
  the viewer is ended abruptly. A read that runs out of that memory reports
  ``too_large``.

An assembly is read the same way (:func:`.mesh3d.read_assembly_scene`): its
component files are found by reference resolution in the opened folder, and
the child keeps that folder's index from one assembly to the next until the
window opens a folder again. Its meshes arrive once each, with the matrices of
the instances that use them, and the boxes to draw where an instance has no mesh
(:class:`.mesh3d.BoxBuffers`, made from where it sits and the box its assembly
stores for it, :func:`.mesh3d.placeholders`) arrive with them, ready to upload.

A file of another format than SOLIDWORKS (STEP, STL, 3MF, Alibre Design...) is
read the same way (:func:`.mesh3d.read_model_scene`, request ``kind`` ``model``):
a part as one mesh, an assembly as its objects placed by their items, named as
the Components tab names its rows.

What crosses the pipe is never a pickle, either way: the request is one JSON
frame, and the answer one JSON frame read with a length limit
(:data:`MAX_HEADER_BYTES`), then the raw buffer frames it announces, each read
with the child's memory limit as its bound and checked against the sizes the
header gives before the window uses it (:func:`check_mesh`). A child that a
crafted file took over can then send the window nothing but data it checks, as
the library's worker pool does (:mod:`solidseas.workers`).

The child opens documents read-only, as every read of the viewer does, and
imports no Qt. Nothing here imports Qt either.
"""

import json
import math
import multiprocessing
import multiprocessing.util
import os
import threading
import time
import weakref
from typing import Any

from . import mesh3d

_BASE_MEMORY = 768 << 20  # the child's interpreter, the library and a part file open in memory
MAX_REQUEST_BYTES = 1 << 20
MAX_HEADER_BYTES = 256 << 20  # an answer's JSON: an assembly's ids and its boxes' names, at most
DRAWN = ("ok", "partial")  # the states whose answer carries buffers (partial: faces left out)
_READERS: "weakref.WeakSet[MeshReader]" = weakref.WeakSet()


def _close_all() -> None:
    """Close every reader the window did not, when Python exits."""
    for reader in list(_READERS):
        reader.close()


# Run by multiprocessing's exit handler before it ends the children it still knows
# of: ended and reaped here first, none is left half-gone for it to end again.
multiprocessing.util.Finalize(None, _close_all, exitpriority=10)


def memory_limit(cap: int) -> int:
    """The most memory the mesh process may use under a triangle cap of ``cap``:
    room for the file, its display-list stream at the byte budget and the mesh
    expanded from it. 1.7 GiB at the default cap."""
    return _BASE_MEMORY + 4 * mesh3d.byte_budget(cap)


# The error a read reports when the child ended without answering, and nobody
# asked it to: a crash, or the operating system ended it.
STOPPED = {
    "code": "mesh_process_stopped",
    "message": "The process reading the display mesh stopped before it finished.",
    "exception": None,
    "retryable": True,
    "detail": None,
    "reader_message": None,
}


def _serve(conn) -> None:
    """The child: read each requested mesh and send it back, until the pipe closes.
    It keeps one folder index for reference resolution, for the folder the window
    opened, while the window keeps that folder open (``cache_key``)."""
    from solidseas.resolve import IndexCache

    cache, cache_key = IndexCache(), None
    while True:
        try:
            raw = conn.recv_bytes(MAX_REQUEST_BYTES)
        except (EOFError, OSError):
            return
        try:
            request = json.loads(raw)
        except ValueError:
            return
        if not isinstance(request, dict):
            return
        cap = request["cap"]
        buffers: list[bytes] = []
        try:
            if request.get("kind") == "model":
                result = mesh3d.read_model_scene(request["path"], request["within"], cap)
                data = result.pop("data", None)
                if isinstance(data, mesh3d.SceneBuffers):
                    result["scene"], buffers = _scene_header(data)
                elif data is not None:
                    result["mesh"] = _mesh_header(data)
                    buffers = [data.positions, data.normals, data.indices]
            elif request.get("kind") == "assembly":
                if request.get("cache_key") != cache_key:
                    cache, cache_key = IndexCache(), request.get("cache_key")
                result = mesh3d.read_assembly_scene(
                    request["path"],
                    request["within"],
                    request["root"],
                    cap,
                    nested=tuple(request["nested"]),
                    configuration=request.get("configuration"),
                    cache=cache,
                    outside=request.get("outside", True) is not False,
                )
                scene = result.pop("data", None)
                if scene is not None:
                    result["scene"], buffers = _scene_header(scene)
            else:
                result = mesh3d.read_part_mesh(
                    request["path"], request["within"], cap, nested=tuple(request["nested"])
                )
                data = result.pop("data", None)
                if data is not None:
                    result["mesh"] = _mesh_header(data)
                    buffers = [data.positions, data.normals, data.indices]
            _drop_bytes(result)
            header = json.dumps(result).encode("utf-8")
        except MemoryError:  # past the job object's limit outside the read itself
            result = {"state": "too_large", "memory": True, "cap": cap, "seconds": {}}
            header, buffers = json.dumps(result).encode("utf-8"), []
        except Exception as exc:  # a read that failed past its own checks, or an answer not JSON: said
            from solidseas import model

            result = {"state": "error", "error": model.error_info(exc), "seconds": {}}
            if request.get("kind") == "model":
                result["model"] = True
            header, buffers = json.dumps(result).encode("utf-8"), []
        try:
            conn.send_bytes(header)
            for buf in buffers:
                conn.send_bytes(buf)
        except (EOFError, OSError, MemoryError):  # the parent sees the pipe close
            return
        buffers = result = header = None  # type: ignore[assignment]


def _mesh_header(m: "mesh3d.MeshBuffers") -> dict[str, Any]:
    return {"n_vertices": m.n_vertices, "n_triangles": m.n_triangles, "bbox": m.bbox}


def _scene_header(scene: "mesh3d.SceneBuffers") -> tuple[dict[str, Any], list[bytes]]:
    """What the answer's JSON says of an assembly's buffers, and the buffers to send after
    it, in the order :meth:`MeshReader._recv_scene` takes them."""
    boxes = scene.boxes
    header = {
        "meshes": [_mesh_header(m) for m in scene.meshes],
        "files": scene.files,
        "instance_ids": scene.instance_ids,
        "documents": scene.documents,
        "missing": scene.missing,
        "bbox": scene.bbox,
        "n_instances": scene.n_instances,
        "n_triangles": scene.n_triangles,
        "info": dict(scene.info or {}),
        "boxes": None
        if boxes is None
        else {
            "ids": boxes.ids,
            "files": boxes.files,
            "names": boxes.names,
            "reasons": boxes.reasons,
            "count": boxes.count,
            "bbox": boxes.bbox,
        },
    }
    buffers: list[bytes] = []
    for i, m in enumerate(scene.meshes):
        buffers += [m.positions, m.normals, m.indices]
        buffers += [scene.matrices[i], scene.files_of[i], scene.bounds[i]]
    if boxes is not None:
        buffers += [boxes.matrices, boxes.bounds]
    return header, buffers


def _drop_bytes(result: dict[str, Any]) -> None:
    """The placeholders' packed matrices and boxes stay in the child: the boxes travel as
    buffers of their own (:class:`.mesh3d.BoxBuffers`), and JSON holds no bytes."""
    for where in (result.get("geometry"), (result.get("scene") or {}).get("info")):
        ph = where.get("placeholders") if isinstance(where, dict) else None
        if isinstance(ph, dict):
            where["placeholders"] = {k: v for k, v in ph.items() if not isinstance(v, (bytes, bytearray))}


# --------------------------------------------------------------------------- checking an answer
class BadAnswer(Exception):
    """The mesh process's answer does not hold together: it is not used."""


def _count(value: Any, most: int = 1 << 40) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= most:
        raise BadAnswer("a count is not a whole number in range")
    return value


def _box(value: Any) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    try:
        lo, hi = value
        out = (tuple(float(v) for v in lo), tuple(float(v) for v in hi))
    except (TypeError, ValueError):
        raise BadAnswer("a box is not two points") from None
    if len(out[0]) != 3 or len(out[1]) != 3 or not all(math.isfinite(v) for p in out for v in p):
        raise BadAnswer("a box is not two finite points")
    return out  # type: ignore[return-value]


def check_mesh(m: Any, positions: bytes, normals: bytes, indices: bytes) -> None:
    """Raise :class:`BadAnswer` unless a mesh's buffers are the size its header says (12
    bytes a vertex for the positions and the normals, 12 a triangle for the indices)
    and every index is below the vertex count."""
    if not isinstance(m, dict):
        raise BadAnswer("a mesh header is not an object")
    nv, nt = _count(m.get("n_vertices")), _count(m.get("n_triangles"))
    if len(positions) != 12 * nv or len(normals) != 12 * nv or len(indices) != 12 * nt:
        raise BadAnswer("a mesh's buffers are not the size its header says")
    if indices:
        from array import array

        idx = array("I")
        idx.frombytes(indices)
        if max(idx) >= nv:
            raise BadAnswer("a triangle names a vertex the mesh does not have")
    _box(m.get("bbox"))


def check_scene(s: Any, n_meshes: int) -> None:
    """Raise :class:`BadAnswer` unless an assembly's header holds what the window uses."""
    if not isinstance(s, dict) or not isinstance(s.get("meshes"), list) or len(s["meshes"]) != n_meshes:
        raise BadAnswer("an assembly's header does not list its meshes")
    ids = s.get("instance_ids")
    if not isinstance(ids, list) or len(ids) != n_meshes:
        raise BadAnswer("an assembly's instances are not listed per mesh")
    if not all(isinstance(group, list) and all(isinstance(i, str) for i in group) for group in ids):
        raise BadAnswer("an instance id is not text")
    files = s.get("files")
    if not isinstance(files, list) or not all(isinstance(f, dict) for f in files):
        raise BadAnswer("an assembly's files are not listed")
    _box(s.get("bbox"))
    _count(s.get("n_instances"))
    _count(s.get("n_triangles"), 1 << 50)


class MeshReader:
    """Reads display meshes in a child process, one at a time.

    :meth:`read` runs in a worker thread and blocks until the answer arrives.
    :meth:`cancel` and :meth:`close` come from the UI thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: Any = None
        self._conn: Any = None
        self._job: _Job | None = None
        self._busy: object | None = None  # the token of the read in progress
        self._kill_busy = False
        self._closed = False
        self.started = 0  # child processes started, for the self-test's report
        self.contained = False  # whether the last child is in a job object
        _READERS.add(self)

    # -- the UI thread -----------------------------------------------------------------
    def cancel(self, token: object) -> None:
        """Stop the read for ``token`` if it is the one running, by ending the child."""
        with self._lock:
            if token is not None and self._busy is token:
                self._kill_locked()

    def close(self) -> None:
        """End the child and wait for it to go; no read starts after this."""
        with self._lock:
            self._closed = True
            if self._busy is not None:
                self._kill_locked()  # the reading thread closes the pipe
                try:
                    if self._proc is not None:
                        self._proc.join(2)
                except (OSError, ValueError, AssertionError):
                    pass
            else:
                self._drop_locked()

    @property
    def running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.is_alive()

    def peak_memory(self) -> int | None:
        """The most memory the current child has used, where a job object measures it."""
        with self._lock:
            return self._job.peak() if self._job is not None else None

    # -- the worker thread -------------------------------------------------------------
    def warm(self, cap: int) -> None:
        """Start the child now, before the first read, so its start-up (a few tenths
        of a second) overlaps something else."""
        with self._lock:
            if self._closed or (self._proc is not None and self._proc.is_alive()):
                return
            self._drop_locked()
        try:
            proc, conn, job = _start(memory_limit(cap))
        except Exception:  # the first read tries again and reports what fails
            return
        with self._lock:
            self._proc, self._conn, self._job = proc, conn, job
            self.started += 1
            self.contained = job is not None
            if self._closed:
                self._kill_locked()
                self._drop_locked()

    def read(
        self,
        path: str,
        folder: str,
        cap: int,
        cancelled=lambda: False,
        *,
        token: object = None,
        nested: tuple[str, ...] = (),
        assembly: bool = False,
        root: str | None = None,
        configuration: str | None = None,
        cache_key: object = None,
        model_file: bool = False,
        outside: bool = True,
    ) -> dict:
        """:func:`.mesh3d.read_part_mesh` in the child, or with ``assembly``
        :func:`.mesh3d.read_assembly_scene`: ``root`` is the folder reference
        resolution searches (``folder`` by default), without ``outside`` the only one,
        and ``cache_key`` says when the
        child must index it again. With ``model_file``, a file of another format
        than SOLIDWORKS: :func:`.mesh3d.read_model_scene`. ``seconds`` gains
        ``start`` when a child had to be started for it and ``transfer`` for the
        buffers, and ``wall`` is the whole wait, a new child's start-up included."""
        t = time.perf_counter()
        if cancelled():
            return {"state": "cancelled", "seconds": {}}
        with self._lock:
            if self._closed:
                return {"state": "cancelled", "seconds": {}}
            self._busy, self._kill_busy = token, False
            alive = self._proc is not None and self._proc.is_alive()
            child = (self._proc, self._conn) if alive else None
            if child is None:
                self._drop_locked()
        request = {
            "kind": "model" if model_file else "assembly" if assembly else "part",
            "path": path,
            "within": folder,
            "root": root or folder,
            "cap": cap,
            "nested": list(nested),
            "configuration": configuration,
            "cache_key": None if cache_key is None else repr(cache_key),
        }
        if not outside:
            request["outside"] = False
        try:
            result = self._read(request, cancelled, child)
        finally:
            with self._lock:
                self._busy = None
        result["wall"] = time.perf_counter() - t
        return result

    def _read(self, request: dict, cancelled, child) -> dict:
        """Send ``request`` to the child and wait for it."""
        cap = request["cap"]
        extra: dict[str, float] = {}
        if child is None:
            t = time.perf_counter()
            try:
                proc, conn, job = _start(memory_limit(cap))
            except Exception as exc:  # no child: say so in the 3D view
                from solidseas import model

                return {"state": "error", "error": model.error_info(exc), "seconds": {}}
            extra["start"] = time.perf_counter() - t
            with self._lock:
                self._proc, self._conn, self._job = proc, conn, job
                self.started += 1
                self.contained = job is not None
                if self._closed:
                    self._kill_locked()
                    self._drop_locked()
                    return {"state": "cancelled", "seconds": extra}
                if self._kill_busy or cancelled():  # nothing asked yet: the child waits for the next read
                    return {"state": "cancelled", "seconds": extra}
        else:
            proc, conn = child
            with self._lock:
                if self._job is not None:
                    self._job.set_memory(memory_limit(cap))
        limit = memory_limit(cap)  # no buffer can be larger than the child may hold
        try:
            conn.send_bytes(json.dumps(request).encode("utf-8"))
            result = json.loads(self._recv(conn, proc, MAX_HEADER_BYTES))
            if not isinstance(result, dict):
                raise BadAnswer("the answer is not an object")
            t = time.perf_counter()
            if result.get("state") in DRAWN and "scene" in result:
                result["data"] = self._recv_scene(conn, proc, result.pop("scene"), limit)
                extra["transfer"] = time.perf_counter() - t
            elif result.get("state") in DRAWN:
                result["data"] = self._recv_mesh(conn, proc, result.pop("mesh", None), limit)
                extra["transfer"] = time.perf_counter() - t
        except (
            Exception
        ) as exc:  # the child ended (cancelled, closed or crashed), the pipe broke, or a bad answer
            with self._lock:
                stopped_by_us = self._kill_busy or self._closed
                self._drop_locked()
            if stopped_by_us or cancelled():
                return {"state": "cancelled", "seconds": extra}
            error = dict(STOPPED)
            if not isinstance(exc, EOFError):
                error["reader_message"] = f"{type(exc).__name__}: {exc}"
            return {"state": "error", "error": error, "seconds": extra}
        if not isinstance(result.get("seconds"), dict):
            result["seconds"] = {}
        result["seconds"].update(extra)
        return result

    def _recv_mesh(self, conn, proc, m: Any, limit: int) -> mesh3d.MeshBuffers:
        positions = self._recv(conn, proc, limit)
        normals = self._recv(conn, proc, limit)
        indices = self._recv(conn, proc, limit)
        check_mesh(m, positions, normals, indices)
        return mesh3d.MeshBuffers(
            positions=positions,
            normals=normals,
            indices=indices,
            n_vertices=m["n_vertices"],
            n_triangles=m["n_triangles"],
            bbox=_box(m["bbox"]),
        )

    def _recv_scene(self, conn, proc, s: Any, limit: int) -> mesh3d.SceneBuffers:
        if not isinstance(s, dict) or not isinstance(s.get("meshes"), list):
            raise BadAnswer("an assembly's header does not list its meshes")
        check_scene(s, len(s["meshes"]))
        meshes, matrices, files_of, bounds = [], [], [], []
        n_files = len(s["files"])
        for m, ids in zip(s["meshes"], s["instance_ids"], strict=True):
            meshes.append(self._recv_mesh(conn, proc, m, limit))
            placed = self._recv(conn, proc, limit)
            index = self._recv(conn, proc, limit)
            box = self._recv(conn, proc, limit)
            n = len(ids)
            if len(placed) != 64 * n or len(index) != 4 * n or len(box) != 24 * n:
                raise BadAnswer("a mesh's instances are not as many as its ids")
            if n:
                from array import array

                which = array("I")
                which.frombytes(index)
                if max(which) >= n_files:
                    raise BadAnswer("an instance names a file the assembly does not list")
            matrices.append(placed)
            files_of.append(index)
            bounds.append(box)
        boxes = None
        b = s.get("boxes")
        if b is not None:
            if not isinstance(b, dict) or not isinstance(b.get("ids"), list):
                raise BadAnswer("the boxes are not listed")
            matrices_b = self._recv(conn, proc, limit)
            bounds_b = self._recv(conn, proc, limit)
            n = len(b["ids"])
            lists = [b.get(k) for k in ("files", "names", "reasons")]
            if (
                len(matrices_b) != 64 * n
                or len(bounds_b) != 24 * n
                or any(not isinstance(v, list) or len(v) != n for v in lists)
            ):
                raise BadAnswer("the boxes are not as many as their ids")
            boxes = mesh3d.BoxBuffers(
                matrices=matrices_b,
                bounds=bounds_b,
                ids=b["ids"],
                files=b["files"],
                names=b["names"],
                reasons=b["reasons"],
                count=_count(b.get("count")),
                bbox=_box(b.get("bbox")),
            )
        return mesh3d.SceneBuffers(
            meshes=meshes,
            matrices=matrices,
            files_of=files_of,
            instance_ids=s["instance_ids"],
            documents=s.get("documents") if isinstance(s.get("documents"), dict) else {},
            missing=s.get("missing") if isinstance(s.get("missing"), dict) else {},
            files=s["files"],
            bbox=_box(s["bbox"]),
            n_instances=s["n_instances"],
            n_triangles=s["n_triangles"],
            info=s.get("info") if isinstance(s.get("info"), dict) else {},
            bounds=bounds,
            boxes=boxes,
        )

    def _recv(self, conn, proc, limit: int) -> bytes:
        """The child's next frame, at most ``limit`` bytes. Raises EOFError once the child
        has ended, which the pipe alone does not always show: ``multiprocessing`` passes
        the child its end of the pipe through a duplicate the child takes over when it
        starts, so a child ended before then leaves that duplicate open here and the pipe
        never breaks."""
        while not conn.poll(0.05):
            if self._kill_busy or not proc.is_alive():
                raise EOFError
        return conn.recv_bytes(limit)

    # -- with the lock held --------------------------------------------------------------
    def _kill_locked(self) -> None:
        self._kill_busy = True
        if self._proc is not None:
            try:
                self._proc.kill()
            except (OSError, ValueError):
                pass

    def _drop_locked(self) -> None:
        """Forget the child: close the pipe, reap it and let go of its job object."""
        proc, conn, job = self._proc, self._conn, self._job
        self._proc = self._conn = self._job = None
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass
        if proc is not None:
            try:
                if proc.is_alive():
                    proc.kill()
                proc.join(2)
            except (OSError, ValueError, AssertionError):
                pass
        if job is not None:
            job.close()  # ends the child, if anything is left of it


def _start(limit: int, target=None, name: str = "SolidSeas mesh reader"):
    """A new child running ``target`` (:func:`_serve`; the 3D Print export gives its
    own): its process, the parent's end of the pipe and its job object (None where
    there is none)."""
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=True)
    proc = ctx.Process(target=target or _serve, args=(child,), name=name, daemon=True)
    proc.start()
    child.close()
    return proc, parent, _Job.contain(proc.pid, limit)


class _Job:
    """A Windows job object holding one process: a memory limit, below-normal
    priority, and the process ended when the job's last handle closes, which
    happens when the viewer ends however it ends."""

    _EXTENDED_LIMITS = 9  # JobObjectExtendedLimitInformation
    _PRIORITY_CLASS = 0x20
    _PROCESS_MEMORY = 0x100
    _KILL_ON_CLOSE = 0x2000
    _BELOW_NORMAL = 0x4000

    def __init__(self, handle: int, k32, info) -> None:
        self.handle, self._k32, self._info = handle, k32, info

    @classmethod
    def contain(cls, pid: int, limit: int) -> "_Job | None":
        if os.name != "nt":
            return None
        try:
            import ctypes
            from ctypes import wintypes

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.CreateJobObjectW.restype = wintypes.HANDLE
            k32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
            k32.OpenProcess.restype = wintypes.HANDLE
            k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
            k32.SetInformationJobObject.argtypes = (
                wintypes.HANDLE,
                ctypes.c_int,
                ctypes.c_void_p,
                wintypes.DWORD,
            )
            k32.QueryInformationJobObject.argtypes = (
                wintypes.HANDLE,
                ctypes.c_int,
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.c_void_p,
            )
            k32.CloseHandle.argtypes = (wintypes.HANDLE,)
            job = k32.CreateJobObjectW(None, None)
            if not job:
                return None
            info = _extended_limits()
            self = cls(job, k32, info)
            info.BasicLimitInformation.LimitFlags = (
                cls._PROCESS_MEMORY | cls._KILL_ON_CLOSE | cls._PRIORITY_CLASS
            )
            info.BasicLimitInformation.PriorityClass = cls._BELOW_NORMAL
            info.ProcessMemoryLimit = limit
            process = k32.OpenProcess(0x0100 | 0x0001, False, pid)  # PROCESS_SET_QUOTA | PROCESS_TERMINATE
            ok = bool(process) and self._apply() and bool(k32.AssignProcessToJobObject(job, process))
            if process:
                k32.CloseHandle(process)
            if not ok:
                self.close()
                return None
            return self
        except (OSError, AttributeError, ValueError):
            return None

    def _apply(self) -> bool:
        import ctypes

        return bool(
            self._k32.SetInformationJobObject(
                self.handle, self._EXTENDED_LIMITS, ctypes.byref(self._info), ctypes.sizeof(self._info)
            )
        )

    def set_memory(self, limit: int) -> None:
        if self.handle and self._info.ProcessMemoryLimit != limit:
            self._info.ProcessMemoryLimit = limit
            self._apply()

    def peak(self) -> int | None:
        import ctypes

        if not self.handle:
            return None
        out = _extended_limits()
        ok = self._k32.QueryInformationJobObject(
            self.handle, self._EXTENDED_LIMITS, ctypes.byref(out), ctypes.sizeof(out), None
        )
        return int(out.PeakProcessMemoryUsed) if ok else None

    def close(self) -> None:
        if self.handle:
            self._k32.CloseHandle(self.handle)
            self.handle = 0


def _extended_limits():
    import ctypes
    from ctypes import wintypes

    class IoCounters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_ulonglong)
            for name in ("reads", "writes", "others", "read_bytes", "write_bytes", "other_bytes")
        ]

    class BasicLimits(ctypes.Structure):
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

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimits),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    return ExtendedLimits()
