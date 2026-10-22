"""Parts' tessellations kept between reads (``solidseas.tesscache``).

A part saved without a display mesh is drawn from its bodies, tessellated, which can
take seconds a part. The cache keeps each whole tessellation, keyed by what the part's
document holds, within a bound in bytes: display geometry's ``brep`` source and the
SolidSeas Viewer's mesh process take a part from it instead of tessellating it again,
and a part saved again (another key) is tessellated again. These tests check the
bound, the keys, that nothing cut short is kept, and that every path that tessellates a
part for the 3D view reuses what an earlier read kept, with the same result.

Every test that reads files checks that none of them changed.
"""

import dataclasses
import hashlib
import shutil
from array import array
from pathlib import Path

import pytest

from builders import build_modern, fixture_streams
from solidseas import geometry as geo
from solidseas import open_document
from solidseas import tessellate as tess
from solidseas.errors import InvalidArgumentError
from solidseas.formats.solidworks.mesh import Mesh
from solidseas.tesscache import (
    DEFAULT_SETTINGS,
    KEPT_REASONS,
    CachedTessellation,
    TessellationCache,
    document_digest,
    keepable,
    settings_key,
)
from solidseas_app.viewer import mesh3d, meshproc
from support import fixture_path

O08 = "o08_asm_2x_boxA.SLDASM"
BOX, CURVED = "o02_boxA.SLDPRT", "o11_curved.SLDPRT"
HERE = {"sources": ("file", "brep"), "allow_outside_roots": False}  # the part files, then their bodies


def _bare(name: str) -> bytes:
    """A fixture part as if saved without a display mesh: drawn from its bodies."""
    streams = fixture_streams(fixture_path(name))
    return build_modern({n: d for n, d in streams.items() if n != "Contents/DisplayLists"})


def _state(folder: Path) -> dict[str, str]:
    files = sorted(p for p in folder.rglob("*") if p.is_file())
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


@pytest.fixture
def jobs(tmp_path):
    """o08, whose two instances of o02_boxA are drawn from the part's bodies: its file is
    saved without a display mesh, and the assembly's own meshes are not asked for."""
    folder = tmp_path / "jobs"
    folder.mkdir()
    shutil.copy2(fixture_path(O08), folder / O08)
    (folder / BOX).write_bytes(_bare(BOX))
    return folder


@pytest.fixture
def runs(monkeypatch):
    """How many times the tessellator has run."""
    count = [0]
    real = tess._run

    def counted(*args, **kwargs):
        count[0] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(tess, "_run", counted)
    return lambda: count[0]


def _entry(floats: int) -> CachedTessellation:
    mesh = Mesh()
    mesh.positions = array("f", bytes(4 * floats))
    return CachedTessellation("Default", "Contents/Config-0-Partition", mesh, (), 1e-4)


def _one(g) -> geo.MeshSource:
    (source,) = g.meshes.values()
    return source


# --------------------------------------------------------------------------- the cache itself
def test_the_cache_lets_the_least_recently_used_go_to_keep_within_its_bound():
    one = _entry(1000).nbytes
    assert one > 4000  # the arrays and the entry's own objects
    cache = TessellationCache(3 * one)
    for k in "abc":
        assert cache.put((k,), _entry(1000))
    assert len(cache) == 3 and cache.nbytes == 3 * one
    assert cache.get(("a",)) is not None  # now the most recently used
    assert cache.put(("d",), _entry(1000))  # b goes: the least recently used
    assert cache.get(("b",)) is None and all(cache.get((k,)) for k in "acd")
    assert (cache.dropped, cache.hits, cache.misses) == (1, 4, 1)
    # Larger than the bound alone: not kept, and nothing let go for it.
    assert not cache.put(("big",), _entry(4000)) and cache.refused == 1 and len(cache) == 3
    cache.put(("a",), _entry(10))  # the same key again: replaced and counted anew
    assert len(cache) == 3 and cache.nbytes == 2 * one + _entry(10).nbytes
    assert cache.get(None) is None and not cache.put(None, _entry(1))
    stats = cache.stats()
    assert stats["entries"] == 3 and stats["max_bytes"] == 3 * one and stats["kept"] == 5
    cache.clear()
    assert len(cache) == 0 and cache.nbytes == 0 and cache.stats()["kept"] == 5  # the counts stay
    for bad in (-1, 1.5, True):
        with pytest.raises(InvalidArgumentError):
            TessellationCache(bad)
    assert not TessellationCache(0).put(("a",), _entry(1))  # a bound of nothing keeps nothing


def test_only_a_whole_tessellation_is_kept():
    """A result a limit stopped, or with a face left out for want of time (or for a reason
    not known here), is not what a later call would give: not kept."""
    with open_document(fixture_path(CURVED)) as doc:
        t = doc.tessellate()
    assert keepable(t) and t.reasons == {} and not t.truncated
    assert keepable(dataclasses.replace(t, reasons={"unsupported_surface": 2, "degenerate": 1}))
    assert not keepable(dataclasses.replace(t, truncated=("max_faces",)))
    # A blend the time ran out on, and a blend's fit, which has a share of the time too.
    assert not keepable(dataclasses.replace(t, reasons={"max_seconds": 1}))
    assert not keepable(dataclasses.replace(t, reasons={"fit_failed": 1}))
    assert not keepable(dataclasses.replace(t, reasons={"a_reason_added_later": 1}))
    assert not keepable(dataclasses.replace(t, mesh=Mesh())) and not keepable(None)
    assert {"max_seconds", "fit_failed"}.isdisjoint(KEPT_REASONS)
    assert KEPT_REASONS <= set(tess.REASONS)  # every reason kept is one the tessellator gives


def test_a_parts_key_follows_what_it_holds_not_its_name_or_time(tmp_path):
    a, b, bare = tmp_path / "a.SLDPRT", tmp_path / "b.SLDPRT", tmp_path / "bare.SLDPRT"
    shutil.copy2(fixture_path(BOX), a)
    shutil.copy2(fixture_path(BOX), b)
    bare.write_bytes(_bare(BOX))
    streams = fixture_streams(fixture_path(BOX))
    partition = next(n for n in streams if n.endswith("-Partition"))
    edited = bytearray(streams[partition])
    edited[len(edited) // 2] ^= 0x01  # one bit of the bodies changed
    one, other = tmp_path / "one.SLDPRT", tmp_path / "other.SLDPRT"
    one.write_bytes(build_modern(streams))
    other.write_bytes(build_modern({**streams, partition: bytes(edited)}))
    before = _state(tmp_path)
    cache = TessellationCache()
    with open_document(a) as da, open_document(b) as db, open_document(bare) as dbare:
        key = cache.key(da, None)
        assert key is not None and key == cache.key(db, None)  # a copy elsewhere: the same entry
        assert key != cache.key(dbare, None)  # saved without its display mesh: another document
        assert key[0] == document_digest(da) and len(key[0]) == 64
        # The active configuration asked for by name or as None: one entry.
        assert cache.key(da, da.active_configuration) == key and key[1] == da.active_configuration
        assert cache.key(da, "no such configuration") != key
        assert cache.key(da, None, settings_key({"angle_deg": 30.0})) != key
        assert cache.key(da, None, settings_key(keep_welded=True)) != key
        assert cache.key(da, None, settings_key(body_types=("solid",))) != key
        assert DEFAULT_SETTINGS == settings_key({}, ("sheet", "solid"), True, False)
    with open_document(one) as d1, open_document(other) as d2:
        assert cache.key(d1, None) != cache.key(d2, None)
    # Too large to read whole for its digest: not cached.
    with open_document(a) as da:
        assert document_digest(da, max_bytes=100) is None
    assert _state(tmp_path) == before


# --------------------------------------------------------------------------- display geometry
def test_display_geometry_takes_a_parts_tessellation_from_the_cache(jobs, runs):
    before = _state(jobs)
    cache = TessellationCache()
    with open_document(jobs / O08) as doc:
        plain = geo.display_geometry(doc, **HERE)
        first = geo.display_geometry(doc, brep_cache=cache, **HERE)
        second = geo.display_geometry(doc, brep_cache=cache, **HERE)
        assert runs() == 2  # without the cache, and the first with it: the second took it from there
        assert cache.stats() | {"bytes": 0} == {
            "entries": 1,
            "bytes": 0,
            "max_bytes": cache.max_bytes,
            "hits": 1,
            "misses": 1,
            "kept": 1,
            "dropped": 0,
            "refused": 0,
        }
        # Spent time does not stop a part the cache holds, but the call's other limits do.
        spent = geo.display_geometry(doc, brep_cache=cache, max_brep_seconds=0, **HERE)
        few = geo.display_geometry(doc, brep_cache=cache, max_triangles=11, **HERE)
        assert runs() == 2
    p = _one(plain)
    for g in (first, second, spent):
        m = _one(g)
        assert [(i.id, i.placement) for i in g.instances] == [(i.id, i.placement) for i in plain.instances]
        assert g.skipped == () and len(g.instances) == 2 and g.counts["meshes_tessellated"] == 1
        assert (m.kind, m.file, m.stream, m.path, m.nested, m.configuration, m.warnings, m.chord_m) == (
            p.kind,
            p.file,
            p.stream,
            p.path,
            p.nested,
            p.configuration,
            p.warnings,
            p.chord_m,
        )
        assert m.mesh.positions == p.mesh.positions and m.mesh.triangles == p.mesh.triangles
        assert m.mesh.normals == p.mesh.normals and m.triangles == 12
    assert _one(second).mesh is _one(first).mesh  # the same triangles, not made again
    assert few.instances == () and {s.reason for s in few.skipped} == {"max_triangles"}
    assert _state(jobs) == before


def test_a_part_saved_again_is_tessellated_again(jobs, runs):
    cache = TessellationCache()
    with open_document(jobs / O08) as doc:
        box = _one(geo.display_geometry(doc, brep_cache=cache, **HERE))
    (jobs / BOX).write_bytes(_bare(CURVED))  # the same name, other bodies
    with open_document(jobs / O08) as doc:
        curved = _one(geo.display_geometry(doc, brep_cache=cache, **HERE))
        again = _one(geo.display_geometry(doc, brep_cache=cache, **HERE))
    assert runs() == 2 and len(cache) == 2  # each document tessellated once
    assert box.triangles == 12 and curved.triangles > 1000 and again.mesh is curved.mesh


@pytest.mark.parametrize(
    ("change", "kept"),
    [
        ({"reasons": {"unsupported_surface": 1}}, True),
        ({"truncated": ("max_faces",)}, False),
        ({"reasons": {"max_seconds": 1}}, False),
        ({"reasons": {"fit_failed": 1}}, False),
    ],
)
def test_the_brep_source_keeps_only_whole_tessellations(jobs, monkeypatch, change, kept):
    real = tess._run
    monkeypatch.setattr(tess, "_run", lambda *a, **k: dataclasses.replace(real(*a, **k), **change))
    cache = TessellationCache()
    with open_document(jobs / O08) as doc:
        g = geo.display_geometry(doc, brep_cache=cache, **HERE)
    assert len(g.instances) == 2  # drawn either way
    assert (len(cache), cache.refused) == ((1, 0) if kept else (0, 1))


def test_a_cache_is_checked_and_can_be_left_out(jobs):
    with open_document(jobs / O08) as doc:
        with pytest.raises(InvalidArgumentError):
            geo.display_geometry(doc, brep_cache={}, **HERE)
        assert len(geo.display_geometry(doc, brep_cache=None, **HERE).instances) == 2


def test_a_part_too_large_to_key_is_drawn_without_the_cache(jobs, runs, monkeypatch):
    import solidseas.tesscache as tc

    monkeypatch.setattr(tc, "MAX_DIGEST_BYTES", 100)
    cache = TessellationCache()
    with open_document(jobs / O08) as doc:
        for _ in range(2):
            g = geo.display_geometry(doc, brep_cache=cache, **HERE)
            assert len(g.instances) == 2 and g.skipped == ()
    assert runs() == 2 and len(cache) == 0 and cache.stats()["misses"] == 0
    part = mesh3d.read_part_mesh(str(jobs / BOX), str(jobs), 1000, brep_cache=cache)
    assert part["state"] == "ok" and "reused" not in part and runs() == 3


# --------------------------------------------------------------------------- the 3D view
def test_the_3d_view_takes_a_parts_tessellation_from_the_cache(tmp_path, runs):
    part = tmp_path / "no_display.SLDPRT"
    part.write_bytes(_bare(BOX))
    before = _state(tmp_path)
    cache = TessellationCache()
    first = mesh3d.read_part_mesh(str(part), str(tmp_path), 1000, brep_cache=cache)
    second = mesh3d.read_part_mesh(str(part), str(tmp_path), 1000, brep_cache=cache)
    assert first["state"] == second["state"] == "ok" and runs() == 1
    assert "reused" not in first and second["reused"] and second["stored_in"] == "bodies"
    assert second["data"] == first["data"]
    assert set(second["seconds"]) == {"open", "read", "tessellate", "build"}
    # Kept whole, but over a lower cap: refused as a tessellation over it is.
    assert mesh3d.read_part_mesh(str(part), str(tmp_path), 11, brep_cache=cache) | {"seconds": None} == {
        "state": "too_large",
        "triangles": 12,
        "from_bodies": True,
        "cap": 11,
        "seconds": None,
    }
    assert runs() == 1
    # Without a cache, as before: tessellated each time.
    assert "reused" not in mesh3d.read_part_mesh(str(part), str(tmp_path), 1000) and runs() == 2
    assert _state(tmp_path) == before


def _assembly_from_bodies(folder: Path) -> Path:
    """o08 saved without the meshes it keeps of its components, next to its part saved
    without a display mesh: the 3D view draws both instances from the part's bodies."""
    streams = fixture_streams(fixture_path(O08))
    stored = [n for n in streams if n.startswith("FaceTessellations/") or n == "Contents/DisplayLists"]
    (folder / O08).write_bytes(build_modern({n: d for n, d in streams.items() if n not in stored}))
    (folder / BOX).write_bytes(_bare(BOX))
    return folder / O08


def test_the_3d_view_of_an_assembly_takes_its_parts_from_the_cache(tmp_path, runs):
    asm = _assembly_from_bodies(tmp_path)
    before = _state(tmp_path)
    cache = TessellationCache()
    folder = str(tmp_path)
    first = mesh3d.read_assembly_scene(str(asm), folder, folder, 1_000_000, brep_cache=cache)
    second = mesh3d.read_assembly_scene(str(asm), folder, folder, 1_000_000, brep_cache=cache)
    assert first["state"] == second["state"] == "ok" and runs() == 1
    assert first["geometry"]["sources"] == ["brep"] and first["geometry"]["placed"] == 2
    assert (first["geometry"]["tessellations_reused"], second["geometry"]["tessellations_reused"]) == (0, 1)
    a, b = first["data"], second["data"]
    assert a.meshes == b.meshes and a.matrices == b.matrices and a.instance_ids == b.instance_ids
    # The part shown on its own takes the tessellation the assembly's read kept.
    part = mesh3d.read_part_mesh(str(tmp_path / BOX), folder, 1000, brep_cache=cache)
    assert part["state"] == "ok" and part["reused"] and runs() == 1
    assert part["data"].positions == a.meshes[0].positions
    # And without a cache nothing is said of it.
    plain = mesh3d.read_assembly_scene(str(asm), folder, folder, 1_000_000)
    assert "tessellations_reused" not in plain["geometry"]
    assert _state(tmp_path) == before


def test_a_part_shown_first_is_tessellated_again_whole_for_its_assembly(tmp_path, runs):
    """A part shown on its own keeps its tessellation without the warnings an assembly's
    read gives with it: the assembly's read makes it again, whole, once."""
    asm = _assembly_from_bodies(tmp_path)
    cache = TessellationCache()
    folder = str(tmp_path)
    assert mesh3d.read_part_mesh(str(tmp_path / BOX), folder, 1000, brep_cache=cache)["state"] == "ok"
    first = mesh3d.read_assembly_scene(str(asm), folder, folder, 1_000_000, brep_cache=cache)
    second = mesh3d.read_assembly_scene(str(asm), folder, folder, 1_000_000, brep_cache=cache)
    assert runs() == 2 and len(cache) == 1
    assert (first["geometry"]["tessellations_reused"], second["geometry"]["tessellations_reused"]) == (0, 1)
    assert mesh3d.read_part_mesh(str(tmp_path / BOX), folder, 1000, brep_cache=cache)["reused"]


def test_the_mesh_process_keeps_the_tessellations_from_one_read_to_the_next(tmp_path):
    """The child process keeps one cache while it runs: the second read of a part drawn
    from its bodies takes it from there, and the memory it may use allows for it."""
    assert meshproc.memory_limit(mesh3d.DEFAULT_TRIANGLE_CAP) == (
        (768 << 20) + 4 * 256_000_000 + meshproc.TESSELLATION_CACHE_BYTES
    )
    part = tmp_path / "no_display.SLDPRT"
    part.write_bytes(_bare(CURVED))
    before = _state(tmp_path)
    reader = meshproc.MeshReader()
    try:
        first = reader.read(str(part), str(tmp_path), 1_000_000)
        second = reader.read(str(part), str(tmp_path), 1_000_000)
    finally:
        reader.close()
    assert first["state"] == second["state"] == "ok" and reader.started == 1
    assert "reused" not in first and second["reused"] is True
    assert second["data"] == first["data"] and first["data"].n_triangles > 1000
    assert _state(tmp_path) == before
