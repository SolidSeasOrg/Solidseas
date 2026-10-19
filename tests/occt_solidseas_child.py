"""SolidSeas' side of the OCCT oracle's corpus tiers (``test_occt_corpus.py``), in a child
process of its own: run by :func:`occt_support.run_child` in the tests' interpreter, inside
the same Job Object as the OCCT child (a memory cap, a timeout, below-normal priority), so
that a private file that is slow or huge never stalls or swells the test process.

It reads one JSON request on standard input and answers with one line, ``MARK`` then JSON,
numbers and codes only (no path, file name or message text):

* ``{"op": "export", "path", "out", "name", "sys_path"}``: export the part's active
  configuration as the viewer's File > Export STEP does (``solidseas_app.viewer.
  stepexport``): its solid bodies, or, when the export finds only sheets (rule
  ``sheets_not_asked``), its sheet bodies, which are then what goes to a supplier; the
  product named ``name``, to the new file ``out``. ``sheets_fallback`` says which. (A STEP
  sent to the slicer by 3D Print is the solids alone: such a part is refused there.)
* ``{"op": "read", "path", "chord_m" or "drawn", "max_seconds", "sys_path"}``: what
  :func:`occt_support.solidseas_reading` makes of a STEP file, at ``chord_m`` or as the
  viewer or 3D Print draws it (``drawn``), faces as ``[area, x, y, z]``.

``sys_path`` holds the folders of ``src`` and ``tests``, put first on ``sys.path``: the
child runs with ``-I``, which ignores ``PYTHONPATH``.
"""

import json
import os
import sys
import time

MARK = "SOLIDSEAS-OCCT:"


def export(req: dict) -> dict:
    from solidseas.errors import NothingToExportError, SolidSeasError
    from solidseas.formats import open_any
    from solidseas.step import step_model, write_step

    res: dict = {}
    t0 = time.perf_counter()
    fallback = False
    name = req.get("name") or "part"
    try:
        with open_any(req["path"]) as doc:  # as the viewer opens a document to export
            if doc.doc_type != "part":
                return {"status": "not_a_part"}
            try:
                m = step_model(doc, name=name)
            except NothingToExportError as exc:
                if (exc.detail or {}).get("rule") != "sheets_not_asked":
                    raise
                # a part of surfaces only: File > Export STEP sends its surfaces
                m = step_model(doc, name=name, body_types=("solid", "sheet"))
                fallback = True
        write_step(m, req["out"], time_stamp="2026-10-04T00:00:00Z")
    except SolidSeasError as exc:
        res["status"] = "refused"
        res["code"] = exc.code
        rule = (getattr(exc, "detail", None) or {}).get("rule")
        res["rule"] = rule if isinstance(rule, str) else None
        bodies = getattr(exc, "bodies", None)
        if bodies:
            res["reasons"] = sorted({b.reason for b in bodies if getattr(b, "reason", None)})
        return res
    res.update(
        status="written",
        sheets_fallback=fallback,
        exact=bool(m.exact),
        faces=m.counts.get("faces"),
        solids=sum(1 for b in m.bodies if b.kind == "solid" and b.written),
        sheets=sum(1 for b in m.bodies if b.kind == "sheet" and b.written),
        approximated=sorted(m.approximated),
        warnings=sorted({w.code for w in m.warnings}),
        seconds=time.perf_counter() - t0,
    )
    return res


def read(req: dict) -> dict:
    import occt_support as O
    from solidseas.errors import SolidSeasError

    t0 = time.perf_counter()
    chord = req.get("chord_m")
    try:
        got = O.solidseas_reading(
            req["path"],
            chord_m=None if chord is None else float(chord),
            drawn=req.get("drawn"),
            max_seconds=float(req["max_seconds"]),
        )
    except SolidSeasError as exc:  # the reader refused the file, with its reason
        return {"refused": exc.code, "seconds": time.perf_counter() - t0}
    got["faces"] = [[f.area, *f.centroid] for f in got["faces"]]
    got["seconds"] = time.perf_counter() - t0
    return got


def main() -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.kernel32.SetErrorMode(0x8003)  # no error box, no crash report
    out_fd = os.dup(1)
    null = os.open(os.devnull, os.O_WRONLY)
    os.dup2(null, 1)
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
    try:
        req = json.loads(sys.stdin.readline(1 << 20))
        sys.path[:0] = [str(p) for p in req.get("sys_path", [])]
        op = req.get("op")
        res = export(req) if op == "export" else read(req) if op == "read" else {"error": "UnknownRequest"}
    except Exception as exc:  # the class only: the message can quote a path
        res = {"error": type(exc).__name__}
    data = memoryview((MARK + json.dumps(res, allow_nan=False, default=str) + "\n").encode("utf-8"))
    while data:
        data = data[os.write(out_fd, data) :]
    os._exit(0)


if __name__ == "__main__":
    main()
