"""The OCCT side of the opt-in drawings cross-check (``drawing_occt``): Open CASCADE's
two hidden-line algorithms on a STEP file, for the views asked for.

Runs as ``occt_child.py`` runs: started by :func:`occt_support.run_child` (its
``script``) in the interpreter ``SOLIDSEAS_OCCT_PYTHON`` names, inside a Job Object,
never in the tests' own interpreter. It imports the standard library and OCP only,
reads one JSON request from standard input and writes one line, ``MARK`` then JSON, to
the standard output it was given; before it imports OCP it points file descriptor 1 at
the null device, so nothing OCCT prints reaches the parent, and it ends at once after
answering, skipping OCCT's teardown.

The request: ``{"op": "hlr", "path": a STEP file, "views": {name: [direction,
x_direction]}, "deflection_mm": float}``. The file is read with the basic
``STEPControl_Reader``. For each view, ``exact`` is ``HLRBRep_Algo`` and ``poly``
``HLRBRep_PolyAlgo`` on OCCT's own mesh at ``deflection_mm``; each gives polylines of
(x, y) points in millimetres in the view's plane, x along ``x_direction`` and y along
``direction`` x ``x_direction``, the part's origin at (0, 0), sampled within
``deflection_mm`` of the curve:

* ``visible`` and ``hidden``: the sharp edges and the outlines (silhouettes) seen and
  hidden;
* ``smooth_visible`` and ``smooth_hidden``: the smooth (tangent) edges, which a drawing
  draws or leaves out by a setting of its own;

and ``seconds``. An algorithm that raises gives ``{"error": its class name}`` for that
view, and the other still runs.
"""

import json
import math
import os
import platform
import sys
import time

MARK = "SOLIDSEAS-OCCT:"
MAX_POINTS = 20000  # an edge's samples


def _harden() -> None:
    if sys.platform == "win32":
        import ctypes

        # no error box and no Windows Error Reporting for a crash (the job does it too)
        ctypes.windll.kernel32.SetErrorMode(0x8003)


def _clean(value):
    """``value`` with every float that is not finite turned into None."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def versions() -> dict:
    import OCP

    out = {"python": platform.python_version(), "ocp": getattr(OCP, "__version__", None)}
    out["occt"] = ".".join(str(out["ocp"]).split(".")[:3]) if out["ocp"] else None
    return out


def _read(path: str):
    from OCP.IFSelect import IFSelect_ReturnStatus
    from OCP.STEPControl import STEPControl_Reader

    reader = STEPControl_Reader()  # the basic reader: it follows no external reference
    if reader.ReadFile(path) != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise ValueError("the STEP file was not read")
    reader.TransferRoots()
    shape = reader.OneShape()
    if shape.IsNull():
        raise ValueError("the STEP file holds no shape")
    return shape


def _polylines(compound, deflection: float) -> list:
    """The edges of ``compound`` (a shape the hidden-line algorithm built in the view's
    plane, or None) as lists of (x, y) points."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepLib import BRepLib
    from OCP.GCPnts import GCPnts_QuasiUniformDeflection
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    if compound is None or compound.IsNull():
        return []
    BRepLib.BuildCurves3d_s(compound)  # an edge built from its plane curve alone gets its 3D curve
    out = []
    ex = TopExp_Explorer(compound, TopAbs_EDGE)
    while ex.More():
        edge = TopoDS.Edge_s(ex.Current())
        ex.Next()
        try:
            curve = BRepAdaptor_Curve(edge)
            sampler = GCPnts_QuasiUniformDeflection(curve, deflection)
            if not sampler.IsDone() or sampler.NbPoints() < 2:
                continue
            n = min(sampler.NbPoints(), MAX_POINTS)
            pts = [sampler.Value(i) for i in range(1, n + 1)]
        except Exception:  # an edge OCCT cannot sample: left out, and counted
            out.append(None)
            continue
        out.append([[p.X(), p.Y()] for p in pts])
    return out


def _sets(hlr, deflection: float) -> dict:
    """The four sets of polylines of a finished hidden-line run (its HLRToShape)."""

    def get(name):
        try:
            return getattr(hlr, name)()
        except Exception:
            return None

    lines = {
        "visible": _polylines(get("VCompound"), deflection) + _polylines(get("OutLineVCompound"), deflection),
        "hidden": _polylines(get("HCompound"), deflection) + _polylines(get("OutLineHCompound"), deflection),
        "smooth_visible": _polylines(get("Rg1LineVCompound"), deflection),
        "smooth_hidden": _polylines(get("Rg1LineHCompound"), deflection),
    }
    skipped = sum(1 for v in lines.values() for p in v if p is None)
    return {**{k: [p for p in v if p is not None] for k, v in lines.items()}, "edges_skipped": skipped}


def _projector(direction, x_direction):
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.HLRAlgo import HLRAlgo_Projector

    return HLRAlgo_Projector(gp_Ax2(gp_Pnt(0.0, 0.0, 0.0), gp_Dir(*direction), gp_Dir(*x_direction)))


def exact(shape, direction, x_direction, deflection: float) -> dict:
    from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape

    algo = HLRBRep_Algo()
    algo.Add(shape)
    algo.Projector(_projector(direction, x_direction))
    algo.Update()
    algo.Hide()
    return _sets(HLRBRep_HLRToShape(algo), deflection)


def poly(shape, direction, x_direction, deflection: float) -> dict:
    from OCP.HLRBRep import HLRBRep_PolyAlgo, HLRBRep_PolyHLRToShape

    algo = HLRBRep_PolyAlgo()
    algo.Load(shape)
    algo.Projector(_projector(direction, x_direction))
    algo.Update()
    hlr = HLRBRep_PolyHLRToShape()
    hlr.Update(algo)
    return _sets(hlr, deflection)


def hlr(req: dict) -> dict:
    from OCP.BRepMesh import BRepMesh_IncrementalMesh

    deflection = float(req.get("deflection_mm") or 0.01)
    shape = _read(req["path"])
    BRepMesh_IncrementalMesh(shape, deflection, False, 0.2, True)  # the polygon algorithm's mesh
    out = {}
    for name, (direction, x_direction) in req["views"].items():
        got = {}
        for label, run in (("exact", exact), ("poly", poly)):
            t = time.perf_counter()
            try:
                got[label] = run(shape, direction, x_direction, deflection)
            except Exception as exc:  # the class only: OCCT's message can quote the file
                got[label] = {"error": type(exc).__name__}
            got[label]["seconds"] = time.perf_counter() - t
        out[name] = got
    return {"views": out}


def main() -> None:
    _harden()
    out_fd = os.dup(1)
    null = os.open(os.devnull, os.O_WRONLY)
    os.dup2(null, 1)  # OCCT's messages go nowhere
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
    t0 = time.perf_counter()
    try:
        req = json.loads(sys.stdin.readline(1 << 20))
        op = req.get("op") if isinstance(req, dict) else None
        res = hlr(req) if op == "hlr" else {"error": "UnknownRequest"}
        res["versions"] = versions()
    except Exception as exc:  # the class only: the message can quote a path or the file
        res = {"error": type(exc).__name__}
    res["child_seconds"] = time.perf_counter() - t0
    data = memoryview((MARK + json.dumps(_clean(res), allow_nan=False) + "\n").encode("utf-8"))
    while data:
        data = data[os.write(out_fd, data) :]
    os._exit(0)  # skip OCCT's teardown: the answer is out


if __name__ == "__main__":
    main()
