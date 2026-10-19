"""Alibre Design sample files (opt-in, numbers only).

Runs only when ``SOLIDSEAS_ALIBRE_SAMPLES`` names a text file, kept outside the
repository, that lists sample files one path a line. Each sample is read in a worker
process below normal priority, and only counts, booleans and ratios come back: no
file name, folder, property value or geometry is printed or asserted. Every sample's
size and modification time are taken before and after, and must not change.

What is checked (``docs/formats/alibre.md`` sections 6 to 8): every sample is
identified; the stored thumbnails convert to PNG; each part's display mesh reads
with the B-rep's face count; each part's ACIS body is mapped and tessellated closed,
its box within the tessellation's chord of the display mesh's and inside the box the
file stores, and face by face (matched by ``PersistentID``) its orientation agrees
with the display mesh and its area mostly does; and the assembly finds its
components by GUID.
"""

import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor

import pytest

SAMPLES = os.environ.get("SOLIDSEAS_ALIBRE_SAMPLES")
pytestmark = pytest.mark.skipif(not SAMPLES, reason="SOLIDSEAS_ALIBRE_SAMPLES is not set")


def _lower_priority() -> None:
    if sys.platform == "win32":
        import ctypes

        k32 = ctypes.windll.kernel32
        k32.SetPriorityClass(k32.GetCurrentProcess(), 0x4000)  # BELOW_NORMAL_PRIORITY_CLASS
    else:
        os.nice(10)


def _paths() -> list[str]:
    with open(SAMPLES, encoding="utf-8-sig") as fh:
        return [line.strip() for line in fh if line.strip()]


def _snapshot(paths: list[str]) -> list[tuple[int, int]]:
    out = []
    for p in paths:
        st = os.stat(p)
        out.append((st.st_size, st.st_mtime_ns))
    return out


def _tri(p, a, b, c):
    ax, ay, az = p[3 * a : 3 * a + 3]
    bx, by, bz = p[3 * b : 3 * b + 3]
    cx, cy, cz = p[3 * c : 3 * c + 3]
    ux, uy, uz = bx - ax, by - ay, bz - az
    vx, vy, vz = cx - ax, cy - ay, cz - az
    return (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)  # twice the area, along the normal


def _measure(path: str) -> dict:
    """One sample read: tokens, counts and ratios only."""
    from solidseas.formats import open_model
    from solidseas.formats._source import Clock, preview_png
    from solidseas.tessellate import tessellate_transmit

    out: dict = {}
    with open_model(path) as doc:
        out["format"] = doc.format
        out["doc_type"] = doc.doc_type
        pv = doc.preview()
        if pv is not None:
            png, w, h, _stream = preview_png(pv, doc.limits)
            out["thumbnail"] = png.startswith(b"\x89PNG") and (w, h) == (pv.width, pv.height)
        out["warnings"] = sorted({w.code for w in doc.warnings})
        if doc.doc_type == "assembly":
            refs = doc.references()
            out["components"] = len(doc.design().inclusions)
            out["found_by_guid"] = sum(1 for r in refs if r.resolution["found_by"] == "document_guid")
            out["references"] = len(refs)
            out["placed"] = len(doc.scene(prefer="display").items)
            return out
        dm = doc.display_mesh()
        m = doc.sab()
        out["mesh_faces"] = len(dm.faces)
        out["sab_faces"] = len(m.indices("face"))
        build = doc.body_build(Clock(300))
        tess = tessellate_transmit(build.transmit, max_seconds=300)
        out["closed"] = bool(tess.closed)
        out["faces"], out["faces_done"] = tess.counts["faces"], tess.counts["faces_done"]
        scale = doc.scale_m
        ext = dm.header.extent
        lo, hi = tess.measures()["box"]
        # the display mesh lies on the surfaces; the stored extent is a box round the body
        P = dm.positions
        mlo = [min(P[k::3]) * scale for k in range(3)]
        mhi = [max(P[k::3]) * scale for k in range(3)]
        dev = max(max(abs(lo[k] - mlo[k]), abs(hi[k] - mhi[k])) for k in range(3))
        out["box_deviation_in_chords"] = dev / tess.chord_m
        out["inside_extent"] = all(
            ext[k] * scale - 1e-9 <= lo[k] and hi[k] <= ext[3 + k] * scale + 1e-9 for k in range(3)
        )
        # face by face: display faces by id, tessellated faces by PersistentID
        pid = m.persistent_ids()
        display = {}
        for fid, _v0, _nv, t0, nt in dm.faces:
            area = 0.0
            probes = []
            for t in range(t0, t0 + nt):
                a, b, c = dm.triangles[3 * t : 3 * t + 3]
                x = _tri(dm.positions, a, b, c)
                area += math.sqrt(x[0] ** 2 + x[1] ** 2 + x[2] ** 2) / 2
                if (t - t0) % max(1, nt // 5) == 0 and len(probes) < 5:
                    centre = [
                        (dm.positions[3 * a + k] + dm.positions[3 * b + k] + dm.positions[3 * c + k])
                        * scale
                        / 3
                        for k in range(3)
                    ]
                    probes.append((centre, x))
            display[fid] = (area * scale * scale, probes)
        Pt, T = tess.mesh.positions, tess.mesh.triangles
        compared = within = oriented = 0
        for k, (_body, node) in enumerate(tess.face_ids):
            face = build.face_map.get(node)
            got = display.get(pid.get(face))
            if got is None:
                continue
            ft = tess.mesh.faces[k]
            area = 0.0
            tris = []
            for t in range(ft.first_triangle, ft.first_triangle + ft.n_triangles):
                i0, i1, i2 = T[3 * t], T[3 * t + 1], T[3 * t + 2]
                x = _tri(Pt, i0, i1, i2)
                area += math.sqrt(x[0] ** 2 + x[1] ** 2 + x[2] ** 2) / 2
                centre = [(Pt[3 * i0 + j] + Pt[3 * i1 + j] + Pt[3 * i2 + j]) / 3 for j in range(3)]
                tris.append((centre, x))
            compared += 1
            within += abs(area / got[0] - 1.0) <= 0.02 if got[0] > 0 else 0
            votes = 0
            for centre, nd in got[1]:  # the nearest tessellated triangle's normal against the display one
                near = min(tris, key=lambda q, c=centre: sum((q[0][j] - c[j]) ** 2 for j in range(3)))
                votes += 1 if sum(near[1][j] * nd[j] for j in range(3)) > 0 else -1
            oriented += votes > 0
        out["faces_compared"], out["faces_area_within_2pct"], out["faces_oriented"] = (
            compared,
            within,
            oriented,
        )
        out["area_ratio"] = tess.measures()["area"] / sum(a for a, _n in display.values())
    return out


def test_the_alibre_samples():
    paths = _paths()
    before = _snapshot(paths)
    with ProcessPoolExecutor(max_workers=1, initializer=_lower_priority) as pool:
        results = list(pool.map(_measure, paths))
    after = _snapshot(paths)
    assert before == after, "a sample changed while it was read"
    parts = [r for r in results if r["doc_type"] == "part"]
    assemblies = [r for r in results if r["doc_type"] == "assembly"]
    summary = {
        "samples": len(results),
        "identified": sum(r["format"] == "alibre" for r in results),
        "parts": len(parts),
        "assemblies": len(assemblies),
        "thumbnails": sum(1 for r in results if r.get("thumbnail")),
        "display_meshes_matching_the_brep": sum(r["mesh_faces"] == r["sab_faces"] for r in parts),
        "closed": sum(r["closed"] for r in parts),
        "faces": sum(r["faces"] for r in parts),
        "faces_done": sum(r["faces_done"] for r in parts),
        "faces_compared": sum(r["faces_compared"] for r in parts),
        "faces_area_within_2pct": sum(r["faces_area_within_2pct"] for r in parts),
        "faces_oriented": sum(r["faces_oriented"] for r in parts),
        "largest_box_deviation_in_chords": round(
            max((r["box_deviation_in_chords"] for r in parts), default=0), 3
        ),
        "inside_extent": sum(r["inside_extent"] for r in parts),
        "area_ratios": sorted(round(r["area_ratio"], 4) for r in parts),
        "components_found_by_guid": sum(r["found_by_guid"] for r in assemblies),
        "components": sum(r["components"] for r in assemblies),
        "placed": sum(r["placed"] for r in assemblies),
        "warnings": sorted({c for r in results for c in r["warnings"]}),
        "unchanged": before == after,
    }
    print(summary)
    assert summary["identified"] == summary["samples"]
    assert summary["thumbnails"] >= 1
    assert summary["display_meshes_matching_the_brep"] == summary["parts"]
    assert summary["closed"] == summary["parts"]
    assert summary["faces_done"] == summary["faces"]
    assert summary["faces_oriented"] == summary["faces_compared"] == summary["faces"]
    assert summary["faces_area_within_2pct"] >= 0.9 * summary["faces_compared"]
    assert summary["largest_box_deviation_in_chords"] <= 1.0 and summary["inside_extent"] == summary["parts"]
    assert all(abs(a - 1.0) < 0.005 for a in summary["area_ratios"])
    assert summary["components_found_by_guid"] == summary["components"] == summary["placed"]
