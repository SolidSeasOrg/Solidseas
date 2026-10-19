"""The catalog over a private corpus of real files (opt-in, ``docs/API.md`` 3.18).

Runs only when ``SOLIDSEAS_CORPUS_MANIFEST`` names a manifest CSV with a ``path``
column. The roots are the folders that cover every listed document. The test
runs at below-normal priority, builds the catalog under pytest's temporary folder
and deletes it at the end, prints numbers only (never a name or a path), and
checks:

* the budgets of the design: reading at most 5 ms a document wall with two
  workers, a rescan with nothing changed that reads nothing and costs the walk
  plus at most 0.5 s per 10,000 documents, ``catalog.sqlite`` at most 4 MB and
  ``previews.sqlite`` at most 25 MB per 1,000 documents;
* that the catalog's resolution of every reference equals a live resolution
  with the same roots, nothing outside them, identities read in a worker;
* that every reference live resolution finds shows its document in the
  where-used of the file it found, but for references whose sub-assembly's own
  document names another file (at most 1 in 200);
* that no corpus document's size or modification time changed.
"""

import csv
import os
import shutil
import sys
import time

import pytest

MANIFEST = os.environ.get("SOLIDSEAS_CORPUS_MANIFEST")
pytestmark = pytest.mark.skipif(not MANIFEST, reason="SOLIDSEAS_CORPUS_MANIFEST is not set")
DOC_EXT = (".sldprt", ".sldasm", ".slddrw")


def _lower_priority() -> None:
    if sys.platform != "win32":
        return
    import ctypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    k32.GetPriorityClass.argtypes = (ctypes.c_void_p,)
    k32.GetPriorityClass.restype = ctypes.c_uint32
    me = k32.GetCurrentProcess()
    if not k32.SetPriorityClass(me, 0x4000) or k32.GetPriorityClass(me) != 0x4000:
        raise ctypes.WinError(ctypes.get_last_error())


def _roots():
    from solidseas import Root, Roots

    with open(MANIFEST, encoding="utf-8-sig", newline="") as fh:
        folders = sorted({os.path.normcase(os.path.dirname(r["path"])) for r in csv.DictReader(fh)})
    cover: list[str] = []
    for f in folders:
        if not any(f.startswith(c + os.sep) for c in cover):
            cover.append(f)
    return Roots(Root(f"r{i:02d}", c) for i, c in enumerate(cover, 1))


def _stat_all(paths):
    out = {}
    for p in paths:
        try:
            st = os.stat(p)
            out[p] = (st.st_size, st.st_mtime_ns)
        except OSError:
            out[p] = None
    return out


def test_corpus_catalog(tmp_path, capsys):
    from solidseas import catalog
    from solidseas.resolve import IndexCache, ResolutionInput, resolve_references
    from solidseas.resolve.gateway import Gateway
    from solidseas.resolve.identity import Identity
    from solidseas.walk import Walk
    from solidseas.workers import WorkerPool

    _lower_priority()
    roots = _roots()
    docs = [
        e.path for r in roots for e in Walk(r.path) if e.kind == "file" and e.name.lower().endswith(DOC_EXT)
    ]
    before = _stat_all(docs)
    folder = tmp_path / "corpus-catalog"
    folder.mkdir()
    db = folder / "catalog.sqlite"
    numbers: dict = {"roots": len(roots), "documents": len(docs)}
    try:
        with catalog.open(roots, db=db) as cat:
            first = cat.scan(workers=2)
            n = first["counts"]["read_ok"] + first["counts"]["read_errors"]
            numbers["first_scan_s"] = first["seconds"]
            numbers["read_ms_per_document"] = round(1000 * first["seconds"]["read"] / max(1, n), 2)
            numbers["read_errors"] = first["counts"]["read_errors"]
            assert numbers["read_ms_per_document"] <= 5.0
            again = cat.scan(workers=2)
            assert again["counts"]["unchanged"] == first["counts"]["seen"]
            assert again["counts"]["read_ok"] == again["counts"]["hashed"] == 0
            overhead = again["seconds"]["total"] - again["seconds"]["walk"]
            numbers["rescan_s"] = again["seconds"]["total"]
            assert overhead <= 0.5 * max(1, len(docs) / 10_000) + 0.5
            cat._checkpoint()
            indexed = cat.status()["counts"]["documents"]
            per_k = 1000 / max(1, indexed)
            numbers["catalog_mb_per_1000"] = round(os.path.getsize(db) / 1e6 * per_k, 2)
            numbers["previews_mb_per_1000"] = round(
                os.path.getsize(folder / "previews.sqlite") / 1e6 * per_k, 2
            )
            assert numbers["catalog_mb_per_1000"] <= 4.0 and numbers["previews_mb_per_1000"] <= 25.0
            root_db = dict(cat.con.execute("SELECT root_id, id FROM roots").fetchall())
            users_of: dict[int, set] = {}
            agree = differ = used = not_used = 0
            cache = IndexCache()
            refdocs = cat.con.execute(
                "SELECT DISTINCT r.file, ro.root_id, f.rel, ro.path FROM refs r JOIN files f ON f.id = "
                "r.file JOIN roots ro ON ro.id = f.root"
            ).fetchall()
            with WorkerPool(
                2, priority="below_normal", roots=[r.path for r in roots], reader_message=False
            ) as pool:
                for fid, root_id, rel, rpath in refdocs:
                    path = os.path.join(rpath, *rel.split("/"))
                    got = pool.call(
                        "references", {"path": path, "within": rpath, "resolution_input": True}
                    ).data
                    inp = ResolutionInput.from_json(got["resolution_input"], path=path)

                    def reader(items):
                        rows = pool.call(
                            "identities", {"items": [{"path": p, "within": w} for p, w in items]}, timeout=300
                        ).data
                        return [Identity(r["creation_time"], r["source"], r["error"]) for r in rows]

                    live = resolve_references(
                        inp,
                        roots,
                        allow_outside_roots=False,
                        cache=cache,
                        gateway=Gateway(allow_outside_roots=False, identity_reader=reader),
                        skip_unavailable_roots=True,
                        max_seconds=120,
                    )
                    rows = {
                        k: (s, ru, c, i, tr, tp)
                        for k, s, ru, c, i, tr, tp in cat.con.execute(
                            "SELECT r.key, r.status, r.rule, r.confidence, r.identity, tr.root_id, t.rel "
                            "FROM refs r LEFT JOIN files t ON t.id = r.target LEFT JOIN roots tr ON tr.id = "
                            "t.root WHERE r.file = ?",
                            (fid,),
                        )
                    }
                    for key, r in live.results.items():
                        match = (r.match.root, r.match.path) if r.match is not None else (None, None)
                        mine = rows.get(key)
                        if mine is not None and mine == (r.status, r.rule, r.confidence, r.identity, *match):
                            agree += 1
                        else:
                            differ += 1
                        if (
                            r.status in ("resolved", "moved")
                            and r.match is not None
                            and r.match.root is not None
                        ):
                            target = cat.con.execute(
                                "SELECT id FROM files WHERE root = ? AND rel = ?",
                                (root_db[r.match.root], r.match.path),
                            ).fetchone()[0]
                            if target not in users_of:
                                found = cat.where_used(r.match.root, r.match.path)["users"]
                                users_of[target] = {(u["root"], u["path"]) for u in found}
                            if (root_id, rel) in users_of[target]:
                                used += 1
                            else:
                                not_used += 1
            numbers["resolution"] = {"agree": agree, "differ": differ}
            numbers["where_used"] = {"agree": used, "other_file_in_subassembly": not_used}
            assert differ == 0 and agree > 0
            assert not_used * 200 <= used
            t = time.perf_counter()
            for root_id, rel in cat.con.execute(
                "SELECT ro.root_id, f.rel FROM files f JOIN roots ro ON ro.id = f.root"
            ).fetchall():
                cat.where_used(root_id, rel)
            numbers["where_used_ms_mean"] = round(1000 * (time.perf_counter() - t) / max(1, indexed), 3)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
        after = _stat_all(docs)
        numbers["documents_changed"] = sum(1 for p in docs if before[p] != after[p])
        with capsys.disabled():
            print(f"\ncatalog corpus: {numbers}")
    assert numbers["documents_changed"] == 0
    assert not folder.exists()
