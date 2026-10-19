"""The OCCT side of the opt-in oracle tests (``occt_support``).

Runs in the interpreter ``SOLIDSEAS_OCCT_PYTHON`` names, started by
:func:`occt_support.run_child` inside a Job Object, never in the tests' own
interpreter. It imports the standard library and OCP only: never solidseas, never
pytest. It reads one JSON request from standard input and writes one line, ``MARK``
then JSON, to the standard output it was given. Before it imports OCP it points file
descriptor 1 at the null device, so nothing OCCT prints (its messages can quote the
file) reaches the parent; the answer goes to a duplicate of the original descriptor,
and the process then ends at once, skipping OCCT's teardown.

Requests:

* ``{"op": "version"}``: the versions of Python, the ``cadquery-ocp`` wheel and OCCT.
* ``{"op": "step", "path": ..., "faces": bool, "mesh_mm": float | None, "mesh_rel":
  float | None, "mesh_min_mm": float | None}``: read one STEP file with the basic
  ``STEPControl_Reader`` (never the XCAF reader, which follows external references out
  of the file's folder) and measure it: the read's and the transfer's checks, the
  topology, ``BRepCheck_Analyzer``'s verdict, each shell's Gauss-Kronrod volume (a
  void's negative) and centre, the solids' adaptive area and the box; with ``faces``
  each face's surface type, adaptive area and centre, and the area of the whole surface
  it lies on when that surface is bounded; with a mesh deflection (``mesh_mm``, or
  ``mesh_rel`` times the box's diagonal, at least ``mesh_min_mm``) a fine mesh's volume
  and area, and each face's. Lengths are in the units OCCT reads in (millimetres) and
  are converted to metres here, so the reply is in SI throughout.

Every float in a reply is finite or None. Errors come back as ``{"error": class
name}``, without the message, which can quote a path.
"""

import json
import math
import os
import platform
import re
import sys
import time

MARK = "SOLIDSEAS-OCCT:"
GK_EPS = 1e-9  # Gauss-Kronrod: the relative error allowed per face
AREA_EPS = 1e-9  # adaptive surface integration
MM, MM2, MM3 = 1e-3, 1e-6, 1e-9


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


def _norm(msg: str) -> str:
    """A check message as a kind: quoted text and numbers removed."""
    msg = re.sub(r"'[^']*'|\"[^\"]*\"", "<q>", msg)
    msg = re.sub(r"[-+]?\d+(\.\d+)?([eE][-+]?\d+)?", "N", msg)
    return msg.strip()[:120]


def versions() -> dict:
    import OCP

    out = {"python": platform.python_version(), "ocp": getattr(OCP, "__version__", None)}
    try:
        from importlib import metadata

        out["cadquery-ocp"] = metadata.version("cadquery-ocp")
    except Exception:  # another build of OCP: no wheel metadata
        out["cadquery-ocp"] = None
    out["occt"] = ".".join(str(out["ocp"]).split(".")[:3]) if out["ocp"] else None
    return out


def _checks(check_list) -> dict:
    from collections import Counter

    warn, fail = Counter(), Counter()
    it = check_list
    it.Start()
    while it.More():
        ch = it.Value()
        for i in range(1, ch.NbWarnings() + 1):
            warn[_norm(ch.CWarning(i, True))] += 1
        for i in range(1, ch.NbFails() + 1):
            fail[_norm(ch.CFail(i, True))] += 1
        it.Next()
    return {"warnings": dict(warn.most_common(20)), "fails": dict(fail.most_common(20))}


def step(req: dict) -> dict:
    from OCP.Bnd import Bnd_Box
    from OCP.BRep import BRep_Builder, BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.IFSelect import IFSelect_ReturnStatus
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID
    from OCP.TopExp import TopExp, TopExp_Explorer
    from OCP.TopoDS import TopoDS, TopoDS_Compound
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape

    seconds: dict = {}
    res: dict = {"seconds": seconds}

    def items(shape, kind, avoid=None):
        ex = TopExp_Explorer(shape, kind) if avoid is None else TopExp_Explorer(shape, kind, avoid)
        out = []
        while ex.More():
            out.append(ex.Current())
            ex.Next()
        return out

    def compound(shapes):
        c = TopoDS_Compound()
        b = BRep_Builder()
        b.MakeCompound(c)
        for s in shapes:
            b.Add(c, s)
        return c

    def volume(shape):
        """Gauss-Kronrod: (volume m^3, centre of mass m, the method's error estimate)."""
        p = GProp_GProps()
        err = BRepGProp.VolumePropertiesGK_s(shape, p, GK_EPS, False, True, True, False)
        c = p.CentreOfMass()
        return p.Mass() * MM3, [c.X() * MM, c.Y() * MM, c.Z() * MM], err

    def area(shape):
        p = GProp_GProps()
        err = BRepGProp.SurfaceProperties_s(shape, p, AREA_EPS)
        c = p.CentreOfMass()
        return p.Mass() * MM2, [c.X() * MM, c.Y() * MM, c.Z() * MM], err

    def box(shape):
        bx = Bnd_Box()
        BRepBndLib.AddOptimal_s(shape, bx, False, False)
        if bx.IsVoid():
            return None
        p0, p1 = bx.CornerMin(), bx.CornerMax()
        return [p0.X() * MM, p0.Y() * MM, p0.Z() * MM, p1.X() * MM, p1.Y() * MM, p1.Z() * MM]

    def free_edges(shape) -> tuple[int, int]:
        """Edges of ``shape`` used by one face only (a seam's two uses count as two), and
        by more than two."""
        m = TopTools_IndexedDataMapOfShapeListOfShape()
        TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, m)
        free = nonmanifold = 0
        for i in range(1, m.Extent() + 1):
            e = TopoDS.Edge_s(m.FindKey(i))
            n = m.FindFromIndex(i).Size()
            if BRep_Tool.Degenerated_s(e):
                continue
            if n == 1 and not BRep_Tool.IsClosed_s(e, TopoDS.Face_s(m.FindFromIndex(i).First())):
                free += 1
            elif n > 2:
                nonmanifold += 1
        return free, nonmanifold

    t = time.perf_counter()
    reader = STEPControl_Reader()
    status = reader.ReadFile(req["path"])
    seconds["read"] = time.perf_counter() - t
    res["read_status"] = str(status).rsplit(".", 1)[-1].replace("IFSelect_", "")
    if status != IFSelect_ReturnStatus.IFSelect_RetDone:
        return res
    ws = reader.WS()
    res["load_checks"] = _checks(ws.ModelCheckList())
    res["roots"] = reader.NbRootsForTransfer()
    t = time.perf_counter()
    res["roots_transferred"] = reader.TransferRoots()
    seconds["transfer"] = time.perf_counter() - t
    res["transfer_checks"] = _checks(ws.TransferReader().LastCheckList())
    shape = reader.OneShape()
    if shape.IsNull():
        res["null_shape"] = True
        return res
    t = time.perf_counter()
    solids = items(shape, TopAbs_SOLID)
    free_shells = items(shape, TopAbs_SHELL, TopAbs_SOLID)
    free_faces = items(shape, TopAbs_FACE, TopAbs_SHELL)
    res["counts"] = {
        "solids": len(solids),
        "free_shells": len(free_shells),
        "free_faces": len(free_faces),
        "faces": len(items(shape, TopAbs_FACE)),
    }
    shells, open_solid_shells, edges_free, edges_nonmanifold = [], 0, 0, 0
    for k, so in enumerate(solids):
        for sh in items(so, TopAbs_SHELL):
            closed = bool(BRep_Tool.IsClosed_s(sh))
            open_solid_shells += not closed
            shells.append({"solid": k, "closed": closed, "faces": len(items(sh, TopAbs_FACE)), "shape": sh})
        f, n = free_edges(so)
        edges_free += f
        edges_nonmanifold += n
    res["open_solid_shells"] = open_solid_shells
    res["solid_free_edges"] = edges_free
    res["solid_nonmanifold_edges"] = edges_nonmanifold
    res["free_shells_closed"] = sum(1 for s in free_shells if BRep_Tool.IsClosed_s(s))
    seconds["topology"] = time.perf_counter() - t
    t = time.perf_counter()
    res["valid"] = bool(BRepCheck_Analyzer(shape).IsValid())
    seconds["check"] = time.perf_counter() - t
    t = time.perf_counter()
    # One Gauss-Kronrod pass per shell, as the shell lies in its solid (a void's volume
    # comes out negative); the solids' and the whole's volume and centre are their sums.
    errors = []
    for s in shells:
        s["volume"], s["centroid"], err = volume(s.pop("shape"))
        errors.append(err)
    res["shells"] = shells
    if solids:
        total = sum(s["volume"] for s in shells)
        res["volume"] = total
        res["centre_of_mass"] = (
            [sum(s["volume"] * s["centroid"][i] for s in shells) / total for i in range(3)] if total else None
        )
        res["volume_error"] = max(errors) if errors and min(errors) >= 0 else -1.0
        res["solid_volumes"] = [
            sum(s["volume"] for s in shells if s["solid"] == k) for k in range(len(solids))
        ]
        sc = compound(solids)
        a, _c, aerr = area(sc)
        res["area"], res["area_error"] = a, aerr
        res["box_solids"] = box(sc)
    seconds["volume"] = time.perf_counter() - t
    if free_shells or free_faces:
        sheets = compound(items(shape, TopAbs_FACE, TopAbs_SOLID))
        res["sheet_area"] = area(sheets)[0]
    res["box"] = box(shape)
    if req.get("faces"):
        t = time.perf_counter()
        kinds = {0: "plane", 1: "cylinder", 2: "cone", 3: "sphere", 4: "torus", 5: "bezier", 6: "bspline",
                 7: "revolution", 8: "extrusion", 9: "offset"}  # fmt: skip
        bounded = {"sphere", "torus", "bezier", "bspline"}
        faces = []
        for f in items(shape, TopAbs_FACE):
            face = TopoDS.Face_s(f)
            surf = BRepAdaptor_Surface(face)
            kind = kinds.get(int(surf.GetType()), "other")
            a, c, _err = area(face)
            rec = {"kind": kind, "area": a, "centroid": c}
            # the surface's smallest radius of curvature, where it is known: a mesh's
            # chord error on the face is about the chord over it
            if kind == "cylinder":
                rec["min_radius"] = surf.Cylinder().Radius() * MM
            elif kind == "sphere":
                rec["min_radius"] = surf.Sphere().Radius() * MM
            elif kind == "torus":
                torus = surf.Torus()
                big, small = torus.MajorRadius(), torus.MinorRadius()
                rec["min_radius"] = min(small, abs(big - small)) * MM if big != small else small * MM
            if kind in bounded:
                # the area of the whole surface the face lies on, untrimmed
                from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace

                try:
                    whole = BRepBuilderAPI_MakeFace(BRep_Tool.Surface_s(face), 1e-7)
                    rec["surface_area"] = area(whole.Face())[0] if whole.IsDone() else None
                except Exception:  # a surface OCCT cannot bound
                    rec["surface_area"] = None
            faces.append(rec)
        res["faces"] = faces
        seconds["faces"] = time.perf_counter() - t
    deflection = req.get("mesh_mm")
    if req.get("mesh_rel") and res["box"]:
        # a deflection relative to the shape's size: the box's diagonal times mesh_rel
        b = res["box"]
        deflection = max(
            float(req.get("mesh_min_mm") or 0.0), math.dist(b[:3], b[3:]) / MM * float(req["mesh_rel"])
        )
    if deflection:
        # a fine mesh, to check the integrators: its volume and area in total (solids
        # only when there are solids) and, with ``faces``, each face's area
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.TopAbs import TopAbs_REVERSED
        from OCP.TopLoc import TopLoc_Location

        t = time.perf_counter()
        BRepMesh_IncrementalMesh(shape, float(deflection), False, 0.1, True)

        def triangles(face):
            loc = TopLoc_Location()
            tri = BRep_Tool.Triangulation_s(face, loc)
            if tri is None:
                return None
            tr = loc.Transformation()
            pts = [tri.Node(i).Transformed(tr) for i in range(1, tri.NbNodes() + 1)]
            pts = [(p.X(), p.Y(), p.Z()) for p in pts]
            rev = face.Orientation() == TopAbs_REVERSED
            out = []
            for i in range(1, tri.NbTriangles() + 1):
                a, b, c = tri.Triangle(i).Get()
                if rev:
                    b, c = c, b
                out.append((pts[a - 1], pts[b - 1], pts[c - 1]))
            return out

        def tri_area(A, B, C):
            ux, uy, uz = B[0] - A[0], B[1] - A[1], B[2] - A[2]
            vx, vy, vz = C[0] - A[0], C[1] - A[1], C[2] - A[2]
            cx, cy, cz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            return 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz)

        vol = ar = 0.0
        meshed = True
        for f in items(compound(solids) if solids else shape, TopAbs_FACE):
            tris = triangles(TopoDS.Face_s(f))
            if tris is None:
                meshed = False
                continue
            for A, B, C in tris:
                ar += tri_area(A, B, C)
                vol += (A[0] * (B[1] * C[2] - B[2] * C[1]) - A[1] * (B[0] * C[2] - B[2] * C[0])
                        + A[2] * (B[0] * C[1] - B[1] * C[0])) / 6.0  # fmt: skip
        res["mesh"] = {"deflection_m": float(deflection) * MM, "volume": vol * MM3, "area": ar * MM2,
                       "complete": meshed}  # fmt: skip
        if req.get("faces"):
            for rec, f in zip(res["faces"], items(shape, TopAbs_FACE), strict=True):
                tris = triangles(TopoDS.Face_s(f))
                rec["mesh_area"] = None if tris is None else sum(tri_area(*t) for t in tris) * MM2
        seconds["mesh"] = time.perf_counter() - t
    return res


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
        if op == "version":
            res = {}
        elif op == "step":
            res = step(req)
        else:
            res = {"error": "UnknownRequest"}
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
