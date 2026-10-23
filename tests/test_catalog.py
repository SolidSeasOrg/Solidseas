"""The catalog (``docs/API.md`` 3.18): scans, incremental rescans, where-used, search,
duplicates, missing references, changes, the schema and where a catalog lives.

Every scan reads copies of the fixtures in ``tmp_path`` (nothing is written beside
the fixtures) and keeps its catalog in the temporary cache folder the session
sets (``SOLIDSEAS_CACHE_DIR``, see ``conftest.py``) or under ``tmp_path``.
Documents are read by a worker pool shared by the module, whose calls a wrapper
counts, so a test can prove a rescan read nothing.
"""

import hashlib
import json
import os
import shutil
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from jsonschema_subset import validate
from serve_support import copy_documents
from solidseas import Root, Roots, catalog, model, open_document
from solidseas.catalog import query as query_mod
from solidseas.catalog import scan as scan_mod
from solidseas.catalog import schema, store
from solidseas.errors import (
    BusyError,
    CatalogIncompatibleError,
    ConfigurationNotFoundError,
    InvalidArgumentError,
    NotInCatalogError,
    PathRefusedError,
)
from solidseas.resolve import resolve_references
from solidseas.workers import WorkerPool
from support import FIXTURES

WINDOWS = os.name == "nt"


class CountingPool:
    """A worker pool that counts the documents each job was asked to read."""

    def __init__(self, pool: WorkerPool) -> None:
        self.pool = pool
        self.workers = pool.workers
        self.calls: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def call(self, job, params=None, **kw):
        with self._lock:
            self.calls.append((job, os.path.basename(params.get("path", ""))))
        return self.pool.call(job, params, **kw)

    def reset(self) -> list[tuple[str, str]]:
        with self._lock:
            out, self.calls = self.calls, []
        return out


@pytest.fixture(scope="module")
def real_pool():
    with WorkerPool(2, jobs={"catalog_document": "worker_jobs:catalog_document"}) as p:
        yield p


@pytest.fixture
def pool(real_pool):
    return CountingPool(real_pool)


def project(tmp_path: Path, name: str = "proj") -> Path:
    folder = tmp_path / name
    copy_documents(folder)
    return folder


def _check(kind: str, data: dict) -> dict:
    assert validate(data, model.KINDS[kind].schema, strict=True) == [], kind
    return data


def _users(data: dict) -> list[tuple]:
    return [
        (
            u["depth"],
            u["relation"],
            u["path"],
            tuple(v["path"] or v["name"] for v in u["via"]),
            tuple(
                (x["user_configuration"], x["configuration"], x["instances"], x["unsuppressed"], x["in_bom"])
                for x in u["uses"]
            ),
            tuple((v["sheet"], v["view"], v["configuration"]) for v in u["views"]),
        )
        for u in data["users"]
    ]


@pytest.fixture
def scanned(tmp_path, pool):
    folder = project(tmp_path)
    cat = catalog.open(folder)
    data = _check("catalog_scan", cat.scan(pool=pool))
    assert data["counts"]["read_ok"] == 19 and data["counts"]["read_errors"] == 0
    yield cat, folder
    cat.close()


# --------------------------------------------------------------------------- where-used
def test_where_used_o02(scanned):
    cat, _folder = scanned
    data = _check("where_used", cat.where_used("project", "o02_boxA.SLDPRT"))
    assert _users(data) == [
        (1, "component", "o08_asm_2x_boxA.SLDASM", (), (("Default", "Default", 2, 2, 2),), ()),
        (1, "component", "o15_sub_asm.SLDASM", (), (("Default", "Default", 1, 1, 1),), ()),
        (
            1,
            "component",
            "o16_asm_features.SLDASM",
            (),
            (("Default", "Default", 3, 3, 2), ("Lite", "Default", 3, 3, 2)),
            (),
        ),
        (1, "drawing_view", "o18_drw_boxA.SLDDRW", (), (), (("Sheet1", "Drawing View1", "Default"),)),
        (
            2,
            "component",
            "o16_asm_features.SLDASM",
            ("o15_sub_asm.SLDASM",),
            (("Default", "Default", 1, 1, 1), ("Lite", "Default", 1, 0, 0)),
            (),
        ),
        (
            2,
            "drawing_of_assembly",
            "o19_drw_asm.SLDDRW",
            ("o16_asm_features.SLDASM",),
            (),
            (("Sheet1", "Drawing View1", "Default"),),
        ),
    ]
    via = [u for u in data["users"] if u["via"]][0]["uses"]
    assert [u["via_configurations"] for u in via] == [["Default"], ["Default"]]  # o15 in Default
    assert data["counts"] == {
        "users": 5,
        "direct": 3,
        "indirect": 1,
        "drawings": 2,
        "possible": 0,
        "name_matches": 0,
    }
    assert data["complete"] and data["as_of"] and not data["truncated"]
    assert data["target"]["doc_type"] == "part" and data["target"]["configurations"] == ["Default"]
    for u in data["users"]:
        assert u["resolution"]["status"] in ("resolved", "moved")


def test_where_used_of_a_sub_assembly_an_assembly_and_a_drawing(scanned):
    cat, _folder = scanned
    o15 = _users(cat.where_used("project", "o15_sub_asm.SLDASM"))
    assert o15 == [
        (
            1,
            "component",
            "o16_asm_features.SLDASM",
            (),
            (("Default", "Default", 1, 1, 1), ("Lite", "Default", 1, 0, 0)),
            (),
        ),
        (
            2,
            "drawing_of_assembly",
            "o19_drw_asm.SLDDRW",
            ("o16_asm_features.SLDASM",),
            (),
            (("Sheet1", "Drawing View1", "Default"),),
        ),
    ]
    o16 = _users(cat.where_used("project", "o16_asm_features.SLDASM"))
    assert o16 == [
        (1, "drawing_view", "o19_drw_asm.SLDDRW", (), (), (("Sheet1", "Drawing View1", "Default"),))
    ]
    assert cat.where_used("project", "o19_drw_asm.SLDDRW")["users"] == []
    assert cat.where_used("project", "o08_asm_2x_boxA.SLDASM")["users"] == []


def test_where_used_direct_only_and_by_configuration(scanned):
    cat, _folder = scanned
    direct = cat.where_used("project", "o02_boxA.SLDPRT", indirect=False)
    assert {u["depth"] for u in direct["users"]} == {1}
    assert len(direct["users"]) == 4
    o06 = cat.where_used("project", "o06_boxA_props_mat_cfg.SLDPRT", configuration="OracleAlt")
    assert _users(o06)[0][:3] == (1, "component", "o16_asm_features.SLDASM")
    assert {x[1] for x in _users(o06)[0][4]} == {"OracleAlt"}
    case = cat.where_used("project", "o06_boxA_props_mat_cfg.SLDPRT", configuration="oraclealt")
    assert case["configuration"] == "OracleAlt" and case["users"]
    other = cat.where_used("project", "o06_boxA_props_mat_cfg.SLDPRT", configuration="Default")
    assert other["users"] == []
    with pytest.raises(ConfigurationNotFoundError):
        cat.where_used("project", "o06_boxA_props_mat_cfg.SLDPRT", configuration="Zq7 none")
    with pytest.raises(NotInCatalogError):
        cat.where_used("project", "nope.SLDPRT")
    assert cat.where_used("project", "O02_BOXA.sldprt")["target"]["path"] == "o02_boxA.SLDPRT"
    with pytest.raises(InvalidArgumentError):
        cat.where_used("project", "o02_boxA.SLDPRT", max_depth=0)
    shallow = cat.where_used("project", "o02_boxA.SLDPRT", max_depth=1)
    assert shallow["truncated"] and {u["depth"] for u in shallow["users"]} == {1}
    assert not cat.where_used("project", "o19_drw_asm.SLDDRW", max_depth=1)["truncated"]
    assert not cat.where_used("project", "o15_sub_asm.SLDASM", max_depth=2)["truncated"]


def test_catalog_resolution_equals_live_resolution(scanned):
    """Every assembly's and drawing's references, resolved from the catalog's rows, equal
    resolve_references on the same root with nothing looked up outside it."""
    cat, folder = scanned
    roots = Roots([Root("project", str(folder))])
    compared = 0
    for name in sorted(os.listdir(folder)):
        if not name.lower().endswith((".sldasm", ".slddrw")):
            continue
        with open_document(folder / name) as doc:
            live = resolve_references(doc, roots, allow_outside_roots=False)
        rows = {
            key: (status, rule, confidence, identity, target)
            for key, status, rule, confidence, identity, target in cat.con.execute(
                "SELECT r.key, r.status, r.rule, r.confidence, r.identity, t.rel FROM refs r "
                "JOIN files f ON f.id = r.file LEFT JOIN files t ON t.id = r.target WHERE f.rel = ?",
                (name,),
            )
        }
        assert set(rows) == set(live.results), name
        for key, r in live.results.items():
            target = r.match.path if r.match is not None else None
            assert rows[key] == (r.status, r.rule, r.confidence, r.identity, target), (name, key)
            compared += 1
    assert compared == 12


# --------------------------------------------------------------------------- incremental scans
def test_an_unchanged_rescan_reads_nothing_and_starts_no_pool(scanned, pool, monkeypatch):
    cat, _folder = scanned
    pool.reset()
    data = cat.scan(pool=pool)
    assert pool.reset() == []
    assert data["counts"]["unchanged"] == 19 and data["counts"]["read_ok"] == 0
    monkeypatch.setattr(scan_mod.Scanner, "_make_pool", lambda self: pytest.fail("a pool was started"))
    assert cat.scan()["counts"]["unchanged"] == 19


def test_touch_add_move_delete(scanned, pool):
    cat, folder = scanned
    pool.reset()
    p = folder / "o03_boxA_again.SLDPRT"
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
    shutil.copy2(FIXTURES / "o02_boxA.SLDPRT", folder / "copy_of_o02.SLDPRT")
    data = cat.scan(pool=pool)
    reads = sorted(n for job, n in pool.reset() if job == "catalog_document")
    assert reads == ["copy_of_o02.SLDPRT", "o03_boxA_again.SLDPRT"]
    assert (data["counts"]["changed"], data["counts"]["added"]) == (1, 1)
    dup = _check("duplicates", cat.duplicates())
    assert dup["counts"] == {
        "groups": 1,
        "files": 2,
        "wasted_bytes": (FIXTURES / "o02_boxA.SLDPRT").stat().st_size,
        "name_groups": None,
    }
    assert {f["path"] for f in dup["groups"][0]["files"]} == {"o02_boxA.SLDPRT", "copy_of_o02.SLDPRT"}

    # a folder of documents renamed: every row follows its file by its file id, nothing is read
    sub = folder / "sub"
    sub.mkdir()
    for name in ("o15_sub_asm.SLDASM", "o16_asm_features.SLDASM", "o19_drw_asm.SLDDRW"):
        os.rename(folder / name, sub / name)
    data = cat.scan(pool=pool)
    assert [job for job, _n in pool.reset() if job == "catalog_document"] == []
    assert data["counts"]["moved"] == 3 and data["counts"]["removed"] == 0
    moved = [e for e in _check("catalog_changes", cat.changes())["events"] if e["kind"] == "moved"]
    assert {(e["previous_path"], e["path"]) for e in moved} == {
        ("o15_sub_asm.SLDASM", "sub/o15_sub_asm.SLDASM"),
        ("o16_asm_features.SLDASM", "sub/o16_asm_features.SLDASM"),
        ("o19_drw_asm.SLDDRW", "sub/o19_drw_asm.SLDDRW"),
    }
    users = _users(cat.where_used("project", "o02_boxA.SLDPRT"))
    assert ("sub/o16_asm_features.SLDASM", ("sub/o15_sub_asm.SLDASM",)) in [(u[2], u[3]) for u in users]

    # the sub-assembly deleted: its row goes, o16's reference to it is missing, and what o16's
    # own tree stores inside it still shows o16 as a user of o02
    os.remove(sub / "o15_sub_asm.SLDASM")
    data = cat.scan(pool=pool)
    assert data["counts"]["removed"] == 1 and pool.reset() == []
    with pytest.raises(NotInCatalogError):
        cat.where_used("project", "sub/o15_sub_asm.SLDASM")
    missing = _check("missing_references", cat.missing_references())
    assert missing["counts"]["missing"] == 1
    assert [d["path"] for d in missing["documents"]] == ["sub/o16_asm_features.SLDASM"]
    assert missing["documents"][0]["references"][0]["file_name"] == "o15_sub_asm.SLDASM"
    stored = [
        u for u in cat.where_used("project", "o02_boxA.SLDPRT")["users"] if u["relation"] == "stored_tree"
    ]
    assert len(stored) == 1 and stored[0]["path"] == "sub/o16_asm_features.SLDASM"
    assert stored[0]["via"] == [{"root": None, "path": None, "name": "o15_sub_asm.SLDASM", "stored": True}]
    assert [(x["user_configuration"], x["unsuppressed"]) for x in stored[0]["uses"]] == [
        ("Default", 1),
        ("Lite", 0),
    ]
    assert "from_parent_tree" in [w["code"] for w in stored[0]["warnings"]]
    kinds = [e["kind"] for e in cat.changes(since="1d")["events"]]
    assert kinds[0] == "removed" and "added" in kinds and "changed" in kinds


def test_an_unavailable_root_keeps_its_rows(scanned, pool):
    cat, folder = scanned
    away = folder.with_name("away")
    os.rename(folder, away)
    try:
        data = cat.scan(pool=pool)
        assert data["roots"][0]["state"] == "unavailable" and data["counts"]["removed"] == 0
        status = _check("catalog", cat.status())
        assert status["counts"]["stale"] == 19 and status["state"] == "partial"
        assert cat.where_used("project", "o02_boxA.SLDPRT")["complete"] is False
    finally:
        os.rename(away, folder)
    pool.reset()
    data = cat.scan(pool=pool)
    assert pool.reset() == [] and data["counts"]["unchanged"] == 19
    assert cat.status()["counts"]["stale"] == 0 and cat.status()["state"] == "ready"


def test_a_truncated_walk_deletes_nothing(scanned, pool, monkeypatch):
    cat, _folder = scanned
    monkeypatch.setattr(scan_mod, "WALK_MAX_EXAMINED", 4)
    data = cat.scan(pool=pool)
    assert data["truncated"] and data["truncated_reason"] == "max_examined"
    assert data["counts"]["removed"] == 0 and data["counts"]["stale"] == 15
    assert cat.status()["counts"]["files"] == 19


def test_cancel_and_deadline_keep_what_was_committed(tmp_path, pool):
    folder = project(tmp_path)
    with catalog.open(folder) as cat:
        stop = threading.Event()
        stop.set()
        data = cat.scan(pool=pool, cancel=stop)
        assert data["cancelled"] and data["state"] == "cancelled"
        data = cat.scan(pool=pool, max_seconds=0.000001)
        assert data["truncated"] and data["truncated_reason"] == "deadline"
        data = cat.scan(pool=pool)
        assert data["state"] == "done" and cat.status()["counts"]["documents"] == 19


def test_the_walker_rules_hold(tmp_path, monkeypatch):
    """A linked folder is never entered, a cloud placeholder is a row that is never read,
    and a SOLIDWORKS lock file is no row at all."""
    from fakefs import ARCHIVE, DIRECTORY, REPARSE, FakeEntry, fake_tree
    from solidseas.walk import FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS, IO_REPARSE_TAG_MOUNT_POINT

    root = tmp_path / "fake"
    root.mkdir()
    listed = fake_tree(
        monkeypatch,
        str(root),
        {
            "": [
                FakeEntry("part.SLDPRT", ARCHIVE, size=100),
                FakeEntry("cloud.SLDPRT", ARCHIVE | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS, size=200),
                FakeEntry("~$part.SLDPRT", ARCHIVE, size=1),
                FakeEntry("linked", DIRECTORY | REPARSE, IO_REPARSE_TAG_MOUNT_POINT),
                FakeEntry("sub", DIRECTORY),
            ],
            "sub": [FakeEntry("inner.SLDASM", ARCHIVE, size=300)],
        },
    )

    class Refusing:
        workers = 1

        def __init__(self) -> None:
            self.paths: list[str] = []

        def call(self, job, params=None, **kw):
            from solidseas.errors import WorkerJobError

            self.paths.append(os.path.basename(params["path"]))
            raise WorkerJobError({"code": "not_found"})

    fake = Refusing()
    with catalog.open(root) as cat:
        data = cat.scan(pool=fake)
        rows = dict(cat.con.execute("SELECT rel, state FROM files").fetchall())
    assert "linked" not in listed and listed == ["", "sub"]
    assert rows == {"part.SLDPRT": "error", "cloud.SLDPRT": "placeholder", "sub/inner.SLDASM": "error"}
    assert sorted(set(fake.paths)) == ["inner.SLDASM", "part.SLDPRT"]  # the placeholder was never read
    assert data["counts"]["seen"] == 3


def test_untrusted_records_store_nothing(tmp_path, pool):
    folder = tmp_path / "bad"
    folder.mkdir()
    for name in ("badtype", "oversize", "toomany", "badimage"):
        shutil.copy2(FIXTURES / "o02_boxA.SLDPRT", folder / f"{name}.SLDPRT")
    with catalog.open(folder) as cat:
        data = cat.scan(pool=pool)
        errors = {e["path"]: e["error"] for e in data["errors"]}
        assert set(errors) == {"badtype.SLDPRT", "oversize.SLDPRT", "toomany.SLDPRT"}
        for err in errors.values():
            assert err["code"] == "internal" and err["detail"] == {"rule": "invalid_record"}
        stored = {
            r for (r,) in cat.con.execute("SELECT f.rel FROM documents d JOIN files f ON f.id = d.file")
        }
        assert stored == {"badimage.SLDPRT"}  # its record is fine, its image is not
        assert cat.con.execute("SELECT count(*) FROM properties").fetchone()[0] == 0
        assert cat.preview("project", "badimage.SLDPRT") is None
        assert cat.con.execute("SELECT count(*) FROM pv.previews").fetchone()[0] == 0


def test_a_file_that_crashes_its_worker_twice_is_quarantined(tmp_path, pool):
    folder = tmp_path / "crashy"
    folder.mkdir()
    shutil.copy2(FIXTURES / "o02_boxA.SLDPRT", folder / "crash.SLDPRT")
    shutil.copy2(FIXTURES / "o02_boxA.SLDPRT", folder / "fine.SLDPRT")
    with catalog.open(folder) as cat:
        first = cat.scan(pool=pool)
        assert [e["error"]["code"] for e in first["errors"]] == ["worker_crashed"]
        second = cat.scan(pool=pool)
        assert [e["error"]["code"] for e in second["errors"]] == ["quarantined"]
        pool.reset()
        third = cat.scan(pool=pool)
        assert third["errors"] == [] and pool.reset() == []  # left alone until it changes
        state = cat.con.execute("SELECT state FROM files WHERE rel = 'crash.SLDPRT'").fetchone()[0]
        assert state == "quarantined" and cat.status()["counts"]["quarantined"] == 1


def test_a_file_over_the_size_limit_is_never_read(tmp_path, pool):
    folder = project(tmp_path)
    with catalog.open(folder) as cat:
        data = cat.scan(pool=pool, max_file_bytes=40_000)
        big = {e["path"] for e in data["errors"]}
        assert big and all(e["error"]["code"] == "file_too_large" for e in data["errors"])
        assert not {n for job, n in pool.calls if job == "catalog_document"} & big


# --------------------------------------------------------------------------- writers and readers
def test_a_second_writer_is_busy_and_readers_are_not(scanned):
    cat, folder = scanned
    with pytest.raises(BusyError) as err:
        catalog.open(folder)
    assert model.error_info(err.value)["code"] == "busy"
    assert model.error_info(err.value)["message"] == model.RULE_MESSAGES[("busy", "catalog_locked")]
    with catalog.open(folder, mode="r") as reader:
        assert reader.status()["counts"]["documents"] == 19
        with pytest.raises(InvalidArgumentError):
            reader.scan()
    with pytest.raises(BusyError):
        catalog.clear(roots=folder)


def test_a_reader_during_a_scan_sees_whole_batches(tmp_path, pool):
    root = tmp_path / "big"
    for i in range(12):
        copy_documents(root / f"job{i:02d}")
    seen: list[tuple[int, int]] = []
    bad: list[str] = []
    done = threading.Event()
    path = catalog.locate(root)[0]

    def read() -> None:
        while not done.is_set():
            try:
                with catalog.Catalog(path, location="cache", name="x", roots=None, mode="r") as r:
                    with r.con:
                        r.con.execute("BEGIN")
                        ok = r.con.execute("SELECT count(*) FROM files WHERE state = 'ok'").fetchone()[0]
                        docs = r.con.execute("SELECT count(*) FROM documents").fetchone()[0]
                        orphans = r.con.execute(
                            "SELECT count(*) FROM documents d JOIN files f ON f.id = d.file WHERE f.state "
                            "<> 'ok'"
                        ).fetchone()[0]
                        r.con.execute("COMMIT")
                    seen.append((ok, docs))
                    if ok != docs or orphans:
                        bad.append(f"{ok} ok, {docs} documents, {orphans} without their state")
            except (FileNotFoundError, CatalogIncompatibleError):
                pass  # not made yet
            time.sleep(0.005)

    with catalog.open(root) as cat:
        t = threading.Thread(target=read)
        t.start()
        try:
            data = cat.scan(pool=pool)
        finally:
            done.set()
            t.join(30)
    assert data["counts"]["read_ok"] == 12 * 19
    assert bad == [] and len(seen) > 5
    assert any(0 < docs < 12 * 19 for _ok, docs in seen)  # the reader saw the scan in progress


# --------------------------------------------------------------------------- the schema
@pytest.mark.parametrize(
    "crafted",
    [
        "CREATE VIEW slow AS WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) SELECT i FROM n",
        "CREATE TRIGGER t AFTER INSERT ON scans BEGIN DELETE FROM roots; END",
    ],
)
def test_a_catalog_holding_a_view_or_a_trigger_is_never_opened(tmp_path, crafted):
    """SolidSeas never makes a view or a trigger, and one in a catalog someone else made
    (a shared project's .solidseas folder) could hang a query or change what it says."""
    _put(tmp_path / "proj", "o02_boxA.SLDPRT")
    db = tmp_path / "shared.sqlite"
    with catalog.open(tmp_path / "proj", db=db) as cat:
        assert cat.con.execute("PRAGMA trusted_schema").fetchone()[0] == 0
    con = sqlite3.connect(db)
    con.execute(crafted)
    con.commit()
    con.close()
    for mode in ("w", "r"):
        with pytest.raises(CatalogIncompatibleError) as err:
            catalog.open(tmp_path / "proj", db=db, mode=mode)
        assert err.value.detail["rule"] == "unexpected_schema" and err.value.detail["value"] == 1


def test_previews_holding_a_trigger_are_never_opened(tmp_path):
    _put(tmp_path / "proj", "o02_boxA.SLDPRT")
    db = tmp_path / "shared.sqlite"
    with catalog.open(tmp_path / "proj", db=db):
        pass
    con = sqlite3.connect(store.sidecar(str(db), store.PREVIEWS_FILE))
    con.execute("CREATE TRIGGER t AFTER INSERT ON previews BEGIN DELETE FROM previews; END")
    con.commit()
    con.close()
    with pytest.raises(CatalogIncompatibleError) as err:
        catalog.open(tmp_path / "proj", db=db)
    assert err.value.detail["rule"] == "unexpected_schema"


@pytest.mark.skipif(os.name == "nt", reason="Windows folders are guarded by their access lists")
def test_a_catalog_folder_another_account_could_swap_is_refused(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o777)  # everyone may write, and no sticky bit: anyone could rename what is in it
    with pytest.raises(PathRefusedError) as err:
        store.make_private_dir(str(shared / "cache" / "catalogs" / "one"))
    assert err.value.detail["rule"] == "not_private"
    shared.chmod(0o1777)  # as /tmp: the sticky bit keeps others from renaming what is not theirs
    store.make_private_dir(str(shared / "cache" / "catalogs" / "two"))


def test_a_catalog_being_made_reads_as_not_indexed_yet(tmp_path):
    """A reader that opens a catalog while its writer makes it, the file empty or marked
    as a catalog with no tables yet, finds nothing indexed yet, not a damaged catalog or
    a file that is not one."""
    from solidseas.errors import NotInCatalogError

    db = tmp_path / "new.sqlite"
    db.write_bytes(b"")  # the moment SQLite has made the file
    with pytest.raises(NotInCatalogError):
        catalog.Catalog(str(db), location="file", name="x", roots=None, mode="r")
    con = sqlite3.connect(db)  # marked as a catalog, its tables not made yet
    con.execute(f"PRAGMA application_id={schema.APPLICATION_ID}")
    con.close()
    assert store.file_application_id(str(db)) == schema.APPLICATION_ID
    with pytest.raises(NotInCatalogError):
        catalog.Catalog(str(db), location="file", name="x", roots=None, mode="r")


def test_a_database_that_is_not_a_catalog_is_left_alone(tmp_path):
    other = tmp_path / "other.sqlite"
    con = sqlite3.connect(other)
    con.execute("CREATE TABLE t (x)")
    con.commit()
    con.close()
    before = hashlib.sha256(other.read_bytes()).hexdigest()
    for mode in ("w", "r"):
        with pytest.raises(CatalogIncompatibleError) as err:
            catalog.open(tmp_path, db=other, mode=mode)
        assert err.value.detail["rule"] == "not_a_catalog"
    text = tmp_path / "notes.txt"
    text.write_text("not a database")
    with pytest.raises(CatalogIncompatibleError):
        catalog.open(tmp_path, db=text)
    with pytest.raises(CatalogIncompatibleError):
        catalog.clear(db=other)  # never deleted
    assert hashlib.sha256(other.read_bytes()).hexdigest() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["notes.txt", "other.sqlite"]
    with pytest.raises(PathRefusedError):
        catalog.open(tmp_path, db=tmp_path / "x.SLDPRT")


def test_a_newer_catalog_is_refused_for_writing(tmp_path, pool):
    folder = project(tmp_path)
    db = tmp_path / "cat.sqlite"
    with catalog.open(folder, db=db) as cat:
        cat.scan(pool=pool)
    con = sqlite3.connect(db)
    con.execute(f"PRAGMA user_version={schema.SCHEMA_VERSION + 1}")
    con.commit()
    con.close()
    with pytest.raises(CatalogIncompatibleError) as err:
        catalog.open(folder, db=db)
    assert err.value.detail["rule"] == "too_new"
    with catalog.open(db=db, mode="r") as reader:  # min_reader_schema still allows reading
        assert reader.status()["counts"]["documents"] == 19
    con = sqlite3.connect(db)
    con.execute("UPDATE meta SET value = '99' WHERE key = 'min_reader_schema'")
    con.commit()
    con.close()
    with pytest.raises(CatalogIncompatibleError):
        catalog.open(db=db, mode="r")


def test_migrations_and_rebuild(tmp_path, pool, monkeypatch):
    folder = project(tmp_path)
    db = tmp_path / "cat.sqlite"
    with catalog.open(folder, db=db) as cat:
        cat.scan(pool=pool)
    # a migration to the next version runs once, in a transaction, and sets the version
    calls = []

    def add_column(con):
        calls.append(1)
        con.execute("ALTER TABLE files ADD COLUMN note TEXT")

    now = schema.SCHEMA_VERSION
    monkeypatch.setattr(schema, "SCHEMA_VERSION", now + 1)
    monkeypatch.setattr(schema, "MIGRATIONS", {now: add_column})
    with catalog.open(folder, db=db) as cat:
        assert cat.con.execute("PRAGMA user_version").fetchone()[0] == now + 1
        assert cat.status()["counts"]["documents"] == 19
    with catalog.open(folder, db=db):
        pass
    assert calls == [1]
    # without a migration for a version the catalog is rebuilt: the roots stay, and the
    # next scan reads everything again
    monkeypatch.setattr(schema, "SCHEMA_VERSION", now + 2)
    monkeypatch.setattr(schema, "MIGRATIONS", {})
    with catalog.open(db=db) as cat:
        assert [r.id for r in cat.roots] == ["project"] and cat.status()["counts"]["files"] == 0
        pool.reset()
        data = cat.scan(pool=pool)
        assert data["counts"]["read_ok"] == 19


def _version_1_tables() -> str:
    """The catalog's tables as schema version 1 made them: version 2 added two columns to
    documents, one to refs and the documents_guid index (schema._version_2). Each is
    found once in today's statements, so a later change to them fails here first."""
    text = schema.TABLES
    for v2, v1 in (
        ("  references_state TEXT,\n  doc_guid TEXT,\n  doc_version INTEGER\n", "  references_state TEXT\n"),
        ("CREATE INDEX documents_guid ON documents (doc_guid) WHERE doc_guid IS NOT NULL;\n", ""),
        ("  doc_version INTEGER,\n", ""),
    ):
        assert text.count(v2) == 1, v2
        text = text.replace(v2, v1)
    return text


def _as_version_1(src: Path, dst: Path) -> None:
    """A version 1 catalog at ``dst`` holding the rows of the catalog at ``src`` in version
    1's tables and columns, its previews beside it, as an older SolidSeas left it."""
    con = sqlite3.connect(dst)
    con.execute(f"PRAGMA application_id={schema.APPLICATION_ID}")
    for stmt in schema._statements(_version_1_tables()):
        con.execute(stmt)
    con.execute("ATTACH DATABASE ? AS v2", (str(src),))
    if con.execute("SELECT count(*) FROM v2.sqlite_master WHERE name = 'search'").fetchone()[0]:
        con.execute(schema.SEARCH_TABLE.strip().rstrip(";"))
    tables = con.execute(
        "SELECT name FROM main.sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite%' "
        "AND name NOT LIKE 'search_%'"
    ).fetchall()
    for (table,) in tables:
        columns = ", ".join(r[1] for r in con.execute(f"PRAGMA main.table_info({table})"))
        if table == "search":
            columns = "rowid, " + columns
        con.execute(f"INSERT INTO main.{table} ({columns}) SELECT {columns} FROM v2.{table}")
    con.execute("UPDATE meta SET value = '1' WHERE key = 'schema_version'")
    con.execute("PRAGMA user_version=1")
    con.commit()
    con.close()
    shutil.copy(store.sidecar(str(src), store.PREVIEWS_FILE), store.sidecar(str(dst), store.PREVIEWS_FILE))


def test_a_version_1_catalog_is_brought_up_to_date_and_reads_only_its_alibre_files_again(tmp_path, pool):
    """A catalog an older SolidSeas wrote (schema 1, before the Alibre GUIDs): the next
    writer adds the columns and the index in place, the next scan reads the Alibre files
    again and nothing else, and Where Used answers for both kinds of file."""
    from solidseas_app.viewer import samples

    folder = project(tmp_path)
    samples.write_samples(str(folder / "samples"))
    fresh = tmp_path / "fresh.sqlite"
    with catalog.open(folder, db=fresh) as cat:
        cat.configure(formats="all")
        cat.scan(pool=pool)
    old = tmp_path / "old.sqlite"
    _as_version_1(fresh, old)
    con = sqlite3.connect(old)
    assert con.execute("PRAGMA user_version").fetchone()[0] == 1
    assert "doc_guid" not in {r[1] for r in con.execute("PRAGMA table_info(documents)")}
    documents = con.execute("SELECT count(*) FROM documents").fetchone()[0]
    con.close()
    with catalog.open(folder, db=old) as cat:
        con = cat.con
        assert con.execute("PRAGMA user_version").fetchone()[0] == schema.SCHEMA_VERSION == 2
        assert {"doc_guid", "doc_version"} <= {r[1] for r in con.execute("PRAGMA table_info(documents)")}
        assert "doc_version" in {r[1] for r in con.execute("PRAGMA table_info(refs)")}
        index = con.execute("SELECT count(*) FROM sqlite_master WHERE name = 'documents_guid'").fetchone()
        assert index[0] == 1
        assert cat.meta("schema_version") == "2"
        pool.reset()
        data = cat.scan(pool=pool)
        assert data["state"] == "done"
        assert sorted(name for _job, name in pool.reset()) == ["cube.AD_PRT", "pair.AD_ASM"]
        assert con.execute("SELECT count(*) FROM documents").fetchone()[0] == documents
        guids = con.execute(
            "SELECT count(*) FROM documents d JOIN files f ON f.id = d.file "
            "WHERE f.ext IN ('.ad_prt', '.ad_asm') AND d.doc_guid IS NOT NULL"
        ).fetchone()[0]
        assert guids == 2
        used = cat.where_used("project", "samples/cube.AD_PRT")
        assert [u["path"] for u in used["users"]] == ["samples/pair.AD_ASM"]
        used = cat.where_used("project", "o02_boxA.SLDPRT")
        assert "o08_asm_2x_boxA.SLDASM" in {u["path"] for u in used["users"]}


# --------------------------------------------------------------------------- where it lives
def test_the_cache_folder_and_the_default_names(tmp_path, monkeypatch):
    monkeypatch.setenv("SOLIDSEAS_CACHE_DIR", str(tmp_path / "c"))
    assert catalog.cache_dir() == str(tmp_path / "c")
    path, location, name = catalog.locate(str(tmp_path / "Jobs"))
    assert location == "cache" and name.startswith("folder-") and len(name) == 23
    assert path == os.path.join(str(tmp_path / "c"), "catalogs", name, "catalog.sqlite")
    assert catalog.locate(str(tmp_path / "JOBS"))[2] == name or not WINDOWS
    monkeypatch.delenv("SOLIDSEAS_CACHE_DIR")
    if WINDOWS:
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
        assert catalog.cache_dir() == str(tmp_path / "local" / "SolidSeas")
    else:
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
        assert catalog.cache_dir() == str(tmp_path / "xdg" / "solidseas")
    assert not (tmp_path / "local").exists() and not (tmp_path / "xdg").exists()  # nothing made
    with pytest.raises(InvalidArgumentError):
        catalog.locate(name="Bad Name!")
    with pytest.raises(InvalidArgumentError) as err:
        catalog.open([str(tmp_path / "a"), str(tmp_path / "a" / "b")])
    assert err.value.detail["rule"] == "overlapping_roots"


@pytest.mark.skipif(not WINDOWS, reason="drive types are Windows'")
def test_the_in_project_catalog_is_refused_on_a_network_drive(tmp_path, monkeypatch):
    from solidseas.resolve import gateway

    monkeypatch.setattr(gateway, "_drive_type", lambda root: gateway.DRIVE_REMOTE)
    with pytest.raises(PathRefusedError) as err:
        catalog.open(tmp_path, location="project")
    assert err.value.detail["rule"] == "network_location"
    with pytest.raises(PathRefusedError):
        catalog.open("\\\\server\\share\\jobs", location="project")
    assert not (tmp_path / ".solidseas").exists()
    monkeypatch.undo()
    for db in ("\\\\server\\share\\cat.sqlite", "\\\\server\\share\\sub\\catalog.sqlite"):
        for mode in ("w", "r"):
            with pytest.raises(PathRefusedError) as err:  # refused from the text: nothing connects
                catalog.open(tmp_path, db=db, mode=mode)
            assert err.value.detail["rule"] == "network_location"


def _tree_state(folder: Path) -> list[tuple]:
    return sorted(
        (str(p.relative_to(folder)), p.stat().st_size, p.stat().st_mtime_ns) for p in folder.rglob("*")
    )


def test_a_scan_writes_nothing_into_the_scanned_folder(tmp_path, pool):
    folder = project(tmp_path)
    before = _tree_state(folder)
    with catalog.open(folder) as cat:
        cat.scan(pool=pool)
        assert not cat.path.startswith(str(folder))
    assert _tree_state(folder) == before
    with catalog.open(folder, location="project") as cat:  # only when asked by name
        cat.scan(pool=pool)
    assert (folder / ".solidseas" / "catalog.sqlite").is_file()
    removed = catalog.clear(roots=folder, location="project")
    assert removed and not (folder / ".solidseas").exists()
    assert _tree_state(folder) == before


def test_verify_finds_a_file_rewritten_in_place_with_its_time_put_back(scanned, pool):
    """Same size, same modification time, same file id: the listing cannot tell. A scan
    with verify hashes it again, reads it again, resolves again the documents that use it
    and records the change; a scan without verify, or of files that did not change, does
    not."""
    cat, folder = scanned
    path = folder / "o02_boxA.SLDPRT"
    st = path.stat()
    data = bytearray(path.read_bytes())
    data[-1] ^= 0xFF  # other bytes, the same length
    with open(path, "r+b") as fh:  # in place: the file id stays
        fh.write(data)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert path.stat().st_size == st.st_size and path.stat().st_ino == st.st_ino
    plain = _check("catalog_scan", cat.scan(pool=pool))
    assert plain["counts"]["changed"] == 0 and plain["counts"]["verified"] == 0
    checked = _check("catalog_scan", cat.scan(pool=pool, verify=True))
    c = checked["counts"]
    assert c["verified"] >= 19 and c["changed"] == 1 and c["read_ok"] + c["read_errors"] == 1
    assert c["resolved_documents"] > 0
    (event,) = [e for e in cat.changes()["events"] if e["kind"] == "changed"]
    assert event["path"] == "o02_boxA.SLDPRT" and event["previous_sha256"] != event["sha256"]
    again = _check("catalog_scan", cat.scan(pool=pool, verify=True))
    assert again["counts"]["changed"] == 0 and again["counts"]["read_ok"] == 0


def test_a_scan_of_a_home_folder_leaves_the_catalogs_folders_out(tmp_path, monkeypatch):
    """A root that holds SolidSeas' cache folder (a home folder, say): the walk does not go
    into the cache folder, where the catalog itself lives, nor into an in-project
    catalog's folder, so a document copied into either is never indexed."""
    home = tmp_path / "home"
    copy_documents(home / "work")
    cache = home / ".cache" / "solidseas"
    monkeypatch.setenv("SOLIDSEAS_CACHE_DIR", str(cache))
    (cache / "elsewhere").mkdir(parents=True)
    shutil.copy2(home / "work" / "o02_boxA.SLDPRT", cache / "elsewhere" / "stray.SLDPRT")
    with catalog.open(home) as cat:
        assert cat.path.startswith(str(cache))
        cat.scan(workers=1)
        shutil.copy2(home / "work" / "o02_boxA.SLDPRT", os.path.join(os.path.dirname(cat.path), "own.SLDPRT"))
        data = cat.scan(workers=1)
        assert data["counts"]["seen"] == 19 and data["counts"]["added"] == 0
        assert cat.search("stray")["results"] == [] and cat.search("own")["results"] == []
    project_root = home / "work"
    with catalog.open(project_root, location="project") as cat:
        shutil.copy2(project_root / "o02_boxA.SLDPRT", project_root / ".solidseas" / "inside.SLDPRT")
        assert cat.scan(workers=1)["counts"]["seen"] == 19
        assert cat.search("inside")["results"] == []


def test_clear_and_list(tmp_path, pool):
    folder = project(tmp_path)
    with catalog.open(folder) as cat:
        cat.scan(pool=pool)
        name = cat.name
    listed = catalog.list_catalogs()
    assert name in [c["name"] for c in listed]
    mine = next(c for c in listed if c["name"] == name)
    assert mine["roots"] == [{"id": "project", "path": str(folder), "role": "project"}]
    assert mine["catalog_bytes"] > 0 and mine["previews_bytes"] > 0
    assert catalog.find_catalog(folder / "o02_boxA.SLDPRT") == name
    removed = catalog.clear(name)
    assert any(p.endswith("catalog.sqlite") for p in removed)
    assert name not in [c["name"] for c in catalog.list_catalogs()]
    with pytest.raises(NotInCatalogError):
        catalog.open(folder, mode="r")


def test_without_sqlite_the_catalog_says_why(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "sqlite3", None)
    with pytest.raises(NotImplementedError) as err:
        catalog.open(tmp_path)
    assert model.error_code(err.value) == "not_implemented"


# --------------------------------------------------------------------------- search and the rest
def test_search(scanned):
    cat, _folder = scanned
    paths = lambda text, **kw: [r["path"] for r in cat.search(text, **kw)["results"]]  # noqa: E731
    data = _check("catalog_search", cat.search("boxA type:part", sort="name"))
    assert data["engine"] == ("fts5" if cat.fts5 else "like")
    assert "o02_boxA.SLDPRT" in [r["path"] for r in data["results"]]
    assert all(r["doc_type"] == "part" for r in data["results"])
    assert paths("pn:o16") == ["o16_asm_features.SLDASM"]
    assert paths('prop:"Description=Oracle test box"', sort="name") == [
        "o04_boxA_props.SLDPRT",
        "o05_boxA_props_mat.SLDPRT",
        "o06_boxA_props_mat_cfg.SLDPRT",
    ]
    assert paths("desc:oracle", sort="name") == paths('prop:"Description=Oracle test box"', sort="name")
    assert paths("type:drawing", sort="name") == ["o18_drw_boxA.SLDDRW", "o19_drw_asm.SLDDRW"]
    assert paths("changed:2000-01-01 type:drawing", sort="name") == [
        "o18_drw_boxA.SLDDRW",
        "o19_drw_asm.SLDDRW",
    ]
    assert paths("changed:2999-01-01") == [] and paths("changed:520w type:drawing")
    oracle = cat.search("Oracle")["results"][0]
    assert "properties" in oracle["matched"]
    page1 = cat.search("type:part", sort="name", limit=5)
    page2 = cat.search("type:part", sort="name", limit=5, cursor=page1["next_cursor"])
    assert len(page1["results"]) == 5 and page1["truncated"] and page2["results"]
    assert not {r["path"] for r in page1["results"]} & {r["path"] for r in page2["results"]}
    with pytest.raises(InvalidArgumentError):
        cat.search("type:part", cursor=page1["next_cursor"][:-2] + "zz")
    with pytest.raises(InvalidArgumentError):
        cat.search("")
    with pytest.raises(InvalidArgumentError):
        cat.search("type:spaceship")
    for text in ('" OR 1=1 --', "NEAR(a b)", "boxA AND OR NOT", "box*", "o02 ^ -x {name}: (y)"):
        assert isinstance(cat.search(text)["results"], list), text  # quoted, never FTS syntax
    with pytest.raises(InvalidArgumentError):
        cat.search("* ^ -")  # nothing to search for
    # the LIKE fallback finds the same documents
    fts = {t: paths(t, sort="name") for t in ("boxA", "Oracle", "o16", "o02 boxA")}
    cat.fts5 = False
    try:
        like = {t: paths(t, sort="name") for t in fts}
        assert cat.search("boxA")["engine"] == "like"
    finally:
        cat.fts5 = cat.meta("search_engine") == "fts5"
    for t in fts:
        assert set(fts[t]) <= set(like[t]), t


def test_part_numbers_from_a_property(scanned):
    cat, _folder = scanned
    numbers = dict(
        cat.con.execute(
            "SELECT f.rel, c.part_number FROM configurations c JOIN files f ON f.id = c.file WHERE "
            "c.position = 0"
        ).fetchall()
    )
    assert numbers["o06_boxA_props_mat_cfg.SLDPRT"] == "o06_boxA_props_mat_cfg"
    cat.configure(part_number_property="PartNo")
    row = cat.con.execute(
        "SELECT c.part_number, c.part_number_source FROM configurations c JOIN files f ON f.id = c.file "
        "WHERE f.rel = 'o06_boxA_props_mat_cfg.SLDPRT' AND c.position = 0"
    ).fetchone()
    assert row[1] == "property" and row[0] != "o06_boxA_props_mat_cfg"
    assert cat.status()["part_number_property"] == "PartNo"
    cat.configure(part_number_property=None)
    assert cat.status()["part_number_property"] is None


def test_status_and_kinds(scanned):
    cat, folder = scanned
    status = _check("catalog", cat.status())
    assert status["state"] == "ready" and status["location"] == "cache"
    assert status["roots"][0]["path"] == str(folder) and status["roots"][0]["documents"] == 19
    assert cat.status(paths=False)["roots"][0]["path"] is None
    c = status["counts"]
    assert (c["parts"], c["assemblies"], c["drawings"], c["hash_pending"]) == (14, 3, 2, 0)
    assert status["formats"] == ["solidworks"] and c["formats"] == {"solidworks": 19}
    assert sum(c["references"].values()) == 12
    mime, image = cat.preview("project", "o02_boxA.SLDPRT")
    assert mime == "image/png" and image.startswith(b"\x89PNG")
    _check("duplicates", cat.duplicates(names=True))
    _check("missing_references", cat.missing_references())
    _check("catalog_changes", cat.changes(since="2026-01-01"))
    for kind in ("catalog", "catalog_scan", "where_used", "catalog_search", "duplicates"):
        assert kind in model.KINDS


def test_a_scan_without_a_pool_runs_its_workers_below_normal_priority(tmp_path, monkeypatch):
    import solidseas.workers as workers_mod

    made = []
    real = workers_mod.WorkerPool

    class Recording(real):
        def __init__(self, *args, **kw):
            made.append(kw)
            super().__init__(*args, **kw)

    monkeypatch.setattr(workers_mod, "WorkerPool", Recording)
    folder = tmp_path / "one"
    folder.mkdir()
    shutil.copy2(FIXTURES / "o02_boxA.SLDPRT", folder / "o02_boxA.SLDPRT")
    with catalog.open(folder) as cat:
        assert cat.scan(workers=1)["counts"]["read_ok"] == 1
    assert made and made[0]["priority"] == "below_normal" and made[0]["roots"] == [str(folder)]
    assert made[0]["reader_message"] is False


def test_an_assembly_without_a_component_tree_is_a_user_of_unknown_quantity(tmp_path, pool):
    from builders import rebuild

    folder = tmp_path / "old"
    folder.mkdir()
    shutil.copy2(FIXTURES / "o02_boxA.SLDPRT", folder / "o02_boxA.SLDPRT")
    data = rebuild(FIXTURES / "o08_asm_2x_boxA.SLDASM", drop=("swXmlContents/COMPINSTANCETREE",))
    (folder / "o08_asm_2x_boxA.SLDASM").write_bytes(data)
    with catalog.open(folder) as cat:
        cat.scan(pool=pool)
        used = _check("where_used", cat.where_used("project", "o02_boxA.SLDPRT"))
    (user,) = used["users"]
    assert (user["path"], user["relation"], user["uses"]) == ("o08_asm_2x_boxA.SLDASM", "component", [])
    assert [w["code"] for w in user["warnings"]] == ["quantity_unknown"]


def test_a_root_that_cannot_be_listed_is_unavailable(tmp_path, pool, monkeypatch):
    from fakefs import fake_tree

    folder = project(tmp_path)
    with catalog.open(folder) as cat:
        cat.scan(pool=pool)
        fake_tree(monkeypatch, str(folder), {"": PermissionError(13, "denied")})
        data = cat.scan(pool=pool)
        assert data["roots"][0]["state"] == "unavailable" and data["counts"]["removed"] == 0
        assert cat.status()["counts"]["stale"] == 19


def test_a_document_over_the_record_limits_is_cut_not_refused(tmp_path, pool):
    from builders import build_modern, fixture_streams

    streams = fixture_streams(FIXTURES / "o04_boxA_props.SLDPRT")
    extra = "".join(
        f'<property name="P{i}" pid="{i + 10}" IsEquation="False" TypeID="30"><vt:lpstr>v{i}</vt:lpstr>'
        "</property>"
        for i in range(10_050)
    )
    end = b"</propertySection></Properties>"
    streams["docProps/custom.xml"] = streams["docProps/custom.xml"].replace(end, extra.encode() + end)
    folder = tmp_path / "many"
    folder.mkdir()
    (folder / "many_properties.SLDPRT").write_bytes(build_modern(streams))
    with catalog.open(folder) as cat:
        data = cat.scan(pool=pool)
        assert data["errors"] == [] and data["counts"]["read_ok"] == 1
        assert cat.con.execute("SELECT count(*) FROM properties").fetchone()[0] == 10_000


# ----------------------------------------------------------------- incremental scans agree with fresh ones
def _search_row(cat, rel: str) -> tuple | None:
    return cat.con.execute(
        "SELECT s.name, s.numbers, s.properties, s.configurations, s.folder FROM search s JOIN files f ON "
        "f.id = s.rowid WHERE f.rel = ?",
        (rel,),
    ).fetchone()


def _configurations(cat, rel: str) -> list[tuple]:
    return cat.con.execute(
        "SELECT c.position, c.name, c.part_number, c.part_number_source, c.description FROM configurations c "
        "JOIN files f ON f.id = c.file WHERE f.rel = ? ORDER BY c.position",
        (rel,),
    ).fetchall()


def _put(folder: Path, *names: str, rename: str | None = None) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for n in names:
        shutil.copy2(FIXTURES / n, folder / (rename or n))


def test_a_renamed_or_moved_document_keeps_its_words_and_takes_its_new_name(scanned, pool, tmp_path):
    cat, folder = scanned
    os.rename(folder / "o04_boxA_props.SLDPRT", folder / "o04_renamed.SLDPRT")
    (folder / "moved").mkdir()
    os.rename(folder / "o14_property_types.SLDPRT", folder / "moved" / "o14_property_types.SLDPRT")
    pool.reset()
    data = cat.scan(pool=pool)
    assert data["counts"]["moved"] == 2 and [j for j, _n in pool.reset() if j == "catalog_document"] == []
    paths = lambda text: [r["path"] for r in cat.search(text, sort="name")["results"]]  # noqa: E731
    assert "o04_renamed.SLDPRT" in paths("ORACLE-PN-123")
    assert paths("Plain text value") == ["moved/o14_property_types.SLDPRT"]
    # the part number SOLIDWORKS takes from the file name follows the rename
    assert paths("pn:o04_renamed") == ["o04_renamed.SLDPRT"] and paths("pn:o04_boxA_props") == []
    with catalog.open(folder, db=tmp_path / "fresh.sqlite") as fresh:
        fresh.scan(pool=pool)
        for rel in ("o04_renamed.SLDPRT", "moved/o14_property_types.SLDPRT"):
            assert _configurations(cat, rel) == _configurations(fresh, rel)
            if cat.fts5:
                assert _search_row(cat, rel) == _search_row(fresh, rel)


def test_what_must_be_resolved_again_outlives_a_cancelled_scan(tmp_path, pool):
    folder = tmp_path / "p"
    _put(folder, "o08_asm_2x_boxA.SLDASM", "o07_boxB_h31.SLDPRT")
    with catalog.open(folder) as cat:
        cat.scan(pool=pool)
        assert cat.missing_references()["counts"]["missing"] == 1
        _put(folder, "o02_boxA.SLDPRT")  # the part the assembly names arrives, among others
        for i in range(8):
            _put(folder, "o03_boxA_again.SLDPRT", rename=f"zz{i}.SLDPRT")
        stop = threading.Event()

        def progress(phase: str, done: int, total: int) -> None:
            if phase == "read":
                stop.set()

        assert cat.scan(pool=pool, cancel=stop, progress=progress)["state"] == "cancelled"
        assert cat.status()["state"] == "partial"  # what waits to be resolved is on record
        data = cat.scan(pool=pool)
        assert data["state"] == "done" and data["counts"]["resolved_documents"] >= 1
        used = cat.where_used("project", "o02_boxA.SLDPRT")
        assert [(u["path"], u["uses"][0]["instances"]) for u in used["users"]] == [
            ("o08_asm_2x_boxA.SLDASM", 2)
        ]
        assert used["complete"] and cat.missing_references()["counts"]["missing"] == 0


def test_a_moved_assembly_or_drawing_is_resolved_from_where_it_is(tmp_path, pool):
    folder = tmp_path / "p"
    _put(folder / "X", "o08_asm_2x_boxA.SLDASM", "o18_drw_boxA.SLDDRW", "o02_boxA.SLDPRT")
    _put(folder / "Y", "o02_boxA.SLDPRT")
    with catalog.open(folder) as cat:
        cat.scan(pool=pool)
        for name in ("o08_asm_2x_boxA.SLDASM", "o18_drw_boxA.SLDDRW"):
            os.rename(folder / "X" / name, folder / "Y" / name)
        pool.reset()
        data = cat.scan(pool=pool)
        assert data["counts"]["moved"] == 2 and pool.reset() == []
        y = cat.where_used("project", "Y/o02_boxA.SLDPRT")
        assert sorted((u["relation"], u["path"]) for u in y["users"]) == [
            ("component", "Y/o08_asm_2x_boxA.SLDASM"),
            ("drawing_view", "Y/o18_drw_boxA.SLDDRW"),
        ]
        assert cat.where_used("project", "X/o02_boxA.SLDPRT")["users"] == []


def test_where_used_counts_through_the_tree_above_an_unreadable_sub_assembly(scanned, pool):
    cat, folder = scanned
    sub = folder / "o15_sub_asm.SLDASM"
    sub.write_bytes(b"\0" * sub.stat().st_size)  # the sub-assembly can no longer be read
    data = cat.scan(pool=pool)
    assert data["counts"]["read_errors"] == 1
    used = _check("where_used", cat.where_used("project", "o02_boxA.SLDPRT"))
    stored = [u for u in used["users"] if u["path"] == "o16_asm_features.SLDASM" and u["depth"] == 2]
    (user,) = stored
    assert user["relation"] == "stored_tree"
    assert user["via"] == [
        {"root": "project", "path": "o15_sub_asm.SLDASM", "name": "o15_sub_asm.SLDASM", "stored": True}
    ]
    assert [
        (x["user_configuration"], x["instances"], x["unsuppressed"], x["in_bom"]) for x in user["uses"]
    ] == [
        ("Default", 1, 1, 1),
        ("Lite", 1, 0, 0),
    ]
    # the answer says some documents could not be read, as their users may be missing
    assert [w["code"] for w in used["warnings"]] == ["unread_documents"]


def test_a_document_freed_to_a_cloud_placeholder_keeps_what_was_read(scanned, pool, monkeypatch):
    import dataclasses

    from solidseas import walk as walk_mod

    cat, _folder = scanned
    freed = {"o08_asm_2x_boxA.SLDASM", "o04_boxA_props.SLDPRT"}
    real = walk_mod.classify

    def classify(entry, *args, **kw):
        e = real(entry, *args, **kw)
        if e.kind == "file" and e.name in freed:  # the same size and time, its data now online only
            e = dataclasses.replace(e, kind="placeholder", reason="recall_on_data_access")
        return e

    monkeypatch.setattr(walk_mod, "classify", classify)
    pool.reset()
    data = cat.scan(pool=pool)
    assert (data["counts"]["changed"], data["counts"]["unchanged"]) == (0, 19) and pool.reset() == []
    row = cat.con.execute("SELECT kind, state FROM files WHERE rel = 'o08_asm_2x_boxA.SLDASM'").fetchone()
    assert row == ("placeholder", "ok")
    assert "o08_asm_2x_boxA.SLDASM" in [
        u["path"] for u in cat.where_used("project", "o02_boxA.SLDPRT")["users"]
    ]
    assert [r["path"] for r in cat.search("pn:o04_boxA")["results"]] == ["o04_boxA_props.SLDPRT"]
    assert not [e for e in cat.changes()["events"] if e["kind"] == "changed"]
    monkeypatch.undo()  # brought back: nothing to read either
    data = cat.scan(pool=pool)
    assert data["counts"]["unchanged"] == 19 and pool.reset() == []
    assert cat.con.execute("SELECT count(*) FROM files WHERE kind = 'placeholder'").fetchone()[0] == 0


def test_a_probable_move_without_file_ids_is_read_again(tmp_path, pool, monkeypatch):
    import dataclasses

    from solidseas import walk as walk_mod

    real = walk_mod.classify
    monkeypatch.setattr(
        walk_mod, "classify", lambda *a, **kw: dataclasses.replace(real(*a, **kw), file_id=None)
    )
    monkeypatch.setattr(scan_mod.Scanner, "_lstat_id", lambda self, db, rel: None)  # FAT, exFAT, some shares
    folder = tmp_path / "p"
    _put(folder / "a", "o04_boxA_props.SLDPRT", rename="x.SLDPRT")
    with catalog.open(folder) as cat:
        cat.scan(pool=pool)
        old = folder / "a" / "x.SLDPRT"
        st = old.stat()
        old.unlink()
        other = (FIXTURES / "o02_boxA.SLDPRT").read_bytes()
        new = folder / "b" / "x.SLDPRT"
        new.parent.mkdir()
        new.write_bytes((other + bytes(st.st_size))[: st.st_size])  # another file of that size and time
        os.utime(new, ns=(st.st_atime_ns, st.st_mtime_ns))
        pool.reset()
        data = cat.scan(pool=pool)
        assert data["counts"]["moved"] == 1 and data["counts"]["read_ok"] == 1
        assert [n for j, n in pool.reset() if j == "catalog_document"] == ["x.SLDPRT"]
        assert cat.search("ORACLE-PN-123")["results"] == []  # the old file's properties are gone
        sha = cat.con.execute("SELECT sha256 FROM files WHERE rel = 'b/x.SLDPRT'").fetchone()[0]
        assert sha == hashlib.sha256(new.read_bytes()).hexdigest()


@pytest.mark.skipif(WINDOWS, reason="Windows listings carry no file id")
def test_a_file_made_again_with_the_same_size_and_time_is_read_again(tmp_path, pool):
    folder = tmp_path / "p"
    _put(folder, "o04_boxA_props.SLDPRT", rename="x.SLDPRT")
    with catalog.open(folder) as cat:
        cat.scan(pool=pool)
        old = folder / "x.SLDPRT"
        st = old.stat()
        other = (FIXTURES / "o02_boxA.SLDPRT").read_bytes()
        made = folder / "x.tmp"
        made.write_bytes((other + bytes(st.st_size))[: st.st_size])
        os.utime(made, ns=(st.st_atime_ns, st.st_mtime_ns))
        os.replace(made, old)  # another file (another inode) under the same name, size and time
        pool.reset()
        data = cat.scan(pool=pool)
        assert data["counts"]["changed"] == 1 and data["counts"]["read_ok"] == 1


def test_hashes_pending_follow_the_policy(tmp_path, pool):
    folder = project(tmp_path)
    shutil.copy2(FIXTURES / "o02_boxA.SLDPRT", folder / "copy_of_o02.SLDPRT")
    with catalog.open(folder) as cat:
        data = cat.scan(pool=pool, hash="duplicates")  # only files whose size another file shares
        dup = cat.duplicates()
        assert (
            data["counts"]["hash_pending"]
            == dup["hash_pending"]
            == cat.status()["counts"]["hash_pending"]
            == 0
        )
        assert dup["counts"]["groups"] == 1 and cat.status()["roots"][0]["hash_policy"] == "duplicates"
        assert cat.scan(pool=pool, hash="none")["counts"]["hash_pending"] == 0
        assert cat.duplicates()["hash_pending"] == 0 and cat.status()["roots"][0]["hash_policy"] == "none"
        cat.scan(pool=pool)  # all, on a local drive
        assert cat.duplicates()["hash_pending"] == 0
        assert cat.con.execute("SELECT count(*) FROM files WHERE sha256 IS NULL").fetchone()[0] == 0


def test_name_groups_are_paged_and_all_counted(tmp_path, pool):
    folder = tmp_path / "p"
    for i, (a, b) in enumerate(
        (
            ("o02_boxA.SLDPRT", "o03_boxA_again.SLDPRT"),
            ("o04_boxA_props.SLDPRT", "o05_boxA_props_mat.SLDPRT"),
            ("o06_boxA_props_mat_cfg.SLDPRT", "o07_boxB_h31.SLDPRT"),
        )
    ):
        _put(folder / "a", a, rename=f"n{i}.SLDPRT")
        _put(folder / "b", b, rename=f"n{i}.SLDPRT")
    with catalog.open(folder) as cat:
        cat.scan(pool=pool)
        first = _check("duplicates", cat.duplicates(names=True, limit=2))
        assert first["counts"]["name_groups"] == 3 and len(first["name_groups"]) == 2 and first["next_cursor"]
        second = cat.duplicates(names=True, limit=2, cursor=first["next_cursor"])
        assert [g["name"] for g in second["name_groups"]] == ["n2.SLDPRT"] and second["next_cursor"] is None


def test_the_where_used_walk_is_bounded(tmp_path, pool, monkeypatch):
    from builders import TreeXml, assembly_with_tree

    # a stored tree of 10 levels of two missing sub-assemblies, each holding both of the level
    # below, the part at the bottom: 1,024 chains up
    t = TreeXml()
    t.file("2", "C:\\J\\o02_boxA.SLDPRT", "PART")
    t.model("mP", "2")
    t.top("m1")
    levels = 10
    for i in range(1, levels + 1):
        for a in (0, 1):
            t.file(f"{i}{a}x", f"C:\\J\\gone_{i}_{a}.SLDASM", "ASSEMBLY")
            t.model(f"mL{i}{a}", f"{i}{a}x")
            if i == 1:
                t.ref(f"mL1{a}", f"p{a}", 1, "mP")
            else:
                for b in (0, 1):
                    t.ref(f"mL{i}{a}", f"s{i}{a}{b}", 1, f"mL{i - 1}{b}")
    for a in (0, 1):
        t.ref("m1", f"top{a}", 1, f"mL{levels}{a}")
    folder = tmp_path / "dag"
    _put(folder, "o02_boxA.SLDPRT")
    (folder / "branching.SLDASM").write_bytes(assembly_with_tree(t))
    with catalog.open(folder) as cat:
        cat.scan(pool=pool)
        used = cat.where_used("project", "o02_boxA.SLDPRT")
        assert len(used["users"]) == 2**levels and not used["truncated"]
        monkeypatch.setattr(query_mod, "MAX_USERS", 100)
        used = cat.where_used("project", "o02_boxA.SLDPRT")
        assert len(used["users"]) == 100 and used["truncated"]
        monkeypatch.setattr(query_mod, "MAX_USERS", 10_000)
        monkeypatch.setattr(query_mod, "WORK_STEPS", 500)  # steps, whatever the users found
        assert cat.where_used("project", "o02_boxA.SLDPRT")["truncated"]
        monkeypatch.setattr(query_mod, "WORK_STEPS", 200_000)
        with pytest.raises(TimeoutError) as err:  # a deadline holds inside the climb too
            query_mod.where_used(cat.con, "project", "o02_boxA.SLDPRT", deadline=time.monotonic() - 1)
        assert model.error_code(err.value) == "timeout"
        with pytest.raises(InvalidArgumentError):
            cat.where_used("project", "o02_boxA.SLDPRT", max_seconds=0)


def test_a_shared_pool_with_no_free_worker_never_quarantines_a_file(tmp_path):
    folder = tmp_path / "p"
    _put(folder, "o02_boxA.SLDPRT")
    with WorkerPool(1, jobs={"sleep": "worker_jobs:sleep"}) as shared, catalog.open(folder) as cat:
        for _ in range(2):  # twice: a timeout twice would quarantine the file
            hold = threading.Thread(target=lambda: shared.call("sleep", {"seconds": 3}, timeout=20))
            hold.start()
            time.sleep(0.5)
            data = cat.scan(pool=shared, file_timeout=0.5, hash="none")
            hold.join()
            (error,) = data["errors"]
            assert error["error"]["code"] == "busy" and error["error"]["detail"] == {"rule": "no_free_worker"}
        data = cat.scan(pool=shared, hash="none")
        assert data["counts"]["read_ok"] == 1
        assert cat.con.execute("SELECT state, error_count FROM files").fetchone() == ("ok", 0)


def test_roots_that_trade_folders_keep_their_rows(tmp_path, pool, monkeypatch):
    a, b = tmp_path / "A", tmp_path / "B"
    _put(a, "o08_asm_2x_boxA.SLDASM")
    _put(b, "o02_boxA.SLDPRT")
    with catalog.open(Roots([Root("x", str(a)), Root("y", str(b))]), name="swap") as cat:
        cat.scan(pool=pool)
    with catalog.open(Roots([Root("x", str(b)), Root("y", str(a))]), name="swap") as cat:
        pool.reset()
        data = cat.scan(pool=pool)
        assert data["state"] == "done" and pool.reset() == []
        assert [u["path"] for u in cat.where_used("x", "o02_boxA.SLDPRT")["users"]] == [
            "o08_asm_2x_boxA.SLDASM"
        ]
        # a scan that fails before its first phase leaves no transaction open behind it
        real = scan_mod.Scanner._sync_roots

        def failing(self):
            monkeypatch.setattr(scan_mod.Scanner, "_sync_roots", real)
            raise RuntimeError("the roots could not be stored")

        monkeypatch.setattr(scan_mod.Scanner, "_sync_roots", failing)
        with pytest.raises(RuntimeError):
            cat.scan(pool=pool)
        assert not cat.con.in_transaction
        assert cat.scan(pool=pool)["state"] == "done"


def _folder_link(target: Path, link: Path) -> None:
    if WINDOWS:
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def test_the_move_pass_never_goes_through_a_link(tmp_path, monkeypatch):
    root, outside = tmp_path / "root", tmp_path / "outside"
    _put(outside, "o02_boxA.SLDPRT", rename="x.SLDPRT")
    root.mkdir()
    _folder_link(outside, root / "B")
    scanner = scan_mod.Scanner.__new__(scan_mod.Scanner)
    scanner.root_paths = {1: str(root)}
    looked: list[str] = []
    real = os.lstat
    monkeypatch.setattr(os, "lstat", lambda p, *a, **kw: looked.append(os.fspath(p)) or real(p, *a, **kw))
    assert scanner._lstat_id(1, "B/x.SLDPRT") is None
    mine = [p for p in looked if p.startswith(str(root))]
    assert mine == [os.path.join(str(root), "B")]  # the link itself, never anything through it
    monkeypatch.undo()
    _put(root / "C", "o02_boxA.SLDPRT", rename="x.SLDPRT")
    assert scanner._lstat_id(1, "C/x.SLDPRT")


def test_the_in_project_catalog_never_writes_through_a_planted_link(tmp_path):
    project_dir, outside = tmp_path / "proj", tmp_path / "outside"
    _put(project_dir, "o02_boxA.SLDPRT")
    outside.mkdir()
    (project_dir / ".solidseas").mkdir()
    try:
        os.symlink(outside / "planted.sqlite", project_dir / ".solidseas" / "catalog.sqlite")
    except OSError:
        pytest.skip("file symbolic links need extra rights here")
    with pytest.raises(PathRefusedError) as err:
        catalog.open(project_dir, location="project")
    assert err.value.detail["rule"] == "link"
    assert list(outside.iterdir()) == []
    (project_dir / ".solidseas" / "catalog.sqlite").unlink()
    os.symlink(outside / "planted.lock", project_dir / ".solidseas" / "catalog.lock")
    with pytest.raises(PathRefusedError):
        catalog.open(project_dir, location="project")
    assert list(outside.iterdir()) == []


def test_crafted_cursors_and_control_characters_are_invalid_arguments(scanned):
    import base64
    import json

    cat, _folder = scanned
    page = cat.search("type:part", limit=1)
    key = json.loads(base64.urlsafe_b64decode(page["next_cursor"] + "=="))["q"]
    for offset in (2**63, 10**30):
        raw = json.dumps({"o": offset, "q": key}, separators=(",", ":")).encode()
        cursor = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        with pytest.raises(InvalidArgumentError):
            cat.search("type:part", limit=1, cursor=cursor)
    with pytest.raises(InvalidArgumentError):
        cat.search("box\x00a")
    with pytest.raises(InvalidArgumentError) as err:
        cat.changes(since="bogus")
    assert err.value.detail == {"parameter": "since"} and "since" in str(err.value)


def test_a_damaged_catalog_says_so_and_one_in_the_cache_is_made_again(tmp_path, pool):
    folder = project(tmp_path)
    with catalog.open(folder) as cat:
        cat.scan(pool=pool)
        path = cat.path
    db = tmp_path / "file.sqlite"
    with catalog.open(folder, db=db) as cat:
        cat.scan(pool=pool)
    for p in (path, db):
        size = os.path.getsize(p)
        with open(p, "r+b") as fh:  # every page after the first overwritten
            fh.seek(4096)
            fh.write(b"\xff" * (size - 4096))
    with pytest.raises(CatalogIncompatibleError) as err:
        with catalog.open(folder, mode="r") as cat:
            cat.where_used("project", "o02_boxA.SLDPRT")
    assert err.value.detail["rule"] == "damaged" and "clear" in model.error_info(err.value)["message"]
    assert catalog.find_catalog(folder / "o02_boxA.SLDPRT") == catalog.locate(folder)[2]  # found, to say so
    with pytest.raises(CatalogIncompatibleError):  # one the caller named is never deleted
        with catalog.open(folder, db=db) as cat:
            cat.scan(pool=pool)
    with catalog.open(folder) as cat:  # one in the cache is a cache: made again
        data = cat.scan(pool=pool)
    assert data["counts"]["read_ok"] == 19
    with catalog.open(folder, mode="r") as cat:
        assert cat.status()["counts"]["documents"] == 19


def test_a_scan_whose_writer_died_is_not_reported_as_running(tmp_path, pool):
    folder = project(tmp_path)
    with catalog.open(folder) as cat:
        cat.scan(pool=pool)
        cat.con.execute(
            "INSERT INTO scans (started_utc, library_version, state, counts) VALUES ('2026-01-01T00:00:00Z', "
            "'0', 'running', '{}')"
        )
        with catalog.open(folder, mode="r") as reader:  # its writer still holds the lock
            assert reader.status()["state"] == "scanning"
    with catalog.open(folder, mode="r") as reader:  # the writer is gone, its scan cut short
        status = reader.status()
    assert status["state"] == "ready" and status["last_scan"]["state"] == "failed"


# --------------------------------------------------------------------------- other 3D formats
def _with_samples(tmp_path: Path) -> Path:
    """The fixture documents, with the viewer's synthetic sample of every other 3D format
    SolidSeas reads (and an IGES file it cannot read) in a subfolder."""
    from solidseas_app.viewer import samples

    folder = project(tmp_path)
    samples.write_samples(str(folder / "samples"))
    return folder


def test_a_catalog_indexes_the_formats_it_is_told_to(tmp_path, pool):
    from collections import Counter

    from solidseas_app.viewer import samples

    folder = _with_samples(tmp_path)
    with catalog.open(folder) as cat:
        assert cat.formats == {"solidworks"}  # until told otherwise
        assert cat.scan(pool=pool)["counts"]["seen"] == 19
        assert not [
            n for _job, n in pool.reset() if not n.lower().endswith((".sldprt", ".sldasm", ".slddrw"))
        ]
        cat.configure(formats="all")
        assert "stl" in cat.formats and "iges" not in cat.formats  # only formats SolidSeas reads
        data = _check("catalog_scan", cat.scan(pool=pool))
        c = data["counts"]
        assert (c["added"], c["read_ok"], c["read_errors"]) == (
            len(samples.EXPECTED),
            len(samples.EXPECTED),
            0,
        )
        read = {n for _job, n in pool.reset()}
        assert read == set(samples.EXPECTED)  # the IGES file is never read
        status = _check("catalog", cat.status())
        assert status["formats"] == sorted(catalog.record.indexed_formats("all"))
        expected = Counter(fmt for fmt, *_rest in samples.EXPECTED.values())
        assert status["counts"]["formats"] == dict(sorted({"solidworks": 19, **expected}.items()))
        assert status["counts"]["documents"] == 19 + len(samples.EXPECTED)
        row = cat.con.execute(
            "SELECT d.format, d.doc_type, d.units, d.counts, d.references_state FROM documents d "
            "JOIN files f ON f.id = d.file WHERE f.rel = 'samples/pair.step'"
        ).fetchone()
        assert row[:2] == ("step", "assembly") and row[4] == "none"
        assert set(json.loads(row[2])) == {"length", "scale_m", "source"}
        assert set(json.loads(row[3])) == set(catalog.record.MODEL_COUNT_NAMES)
        refs = cat.con.execute(
            "SELECT f.rel, r.status, r.rule FROM refs r JOIN files f ON f.id = r.file WHERE f.rel LIKE "
            "'samples/%'"
        ).fetchall()
        assert refs == [("samples/pair.AD_ASM", "resolved", "document_guid")]  # its one part, by GUID
        used = _check("where_used", cat.where_used("project", "samples/cube.AD_PRT"))
        assert [(u["path"], u["format"], u["uses"][0]["instances"]) for u in used["users"]] == [
            ("samples/pair.AD_ASM", "alibre", 2)
        ]
        mime, image = cat.preview("project", "samples/pair.3mf")  # the image the 3MF stores, as a PNG
        assert mime == "image/png" and image.startswith(b"\x89PNG")
        assert cat.preview("project", "samples/box.stl") is None  # none stored, none rendered
        used = _check("where_used", cat.where_used("project", "samples/box.stl"))
        assert used["target"]["format"] == "stl" and used["target"]["doc_type"] == "part"
        assert used["users"] == [] and used["target"]["configurations"] == []
        o02 = _check("where_used", cat.where_used("project", "o02_boxA.SLDPRT"))
        assert o02["target"]["format"] == "solidworks" and o02["counts"]["users"] == 5
        assert {u["format"] for u in o02["users"]} == {"solidworks"}
        found = _check("catalog_search", cat.search("format:step"))
        assert {(r["path"], r["format"]) for r in found["results"]} == {
            ("samples/bracket.step", "step"),
            ("samples/pair.step", "step"),
        }
        found = _check("catalog_search", cat.search("type:assembly format:alibre"))
        assert [r["path"] for r in found["results"]] == ["samples/pair.AD_ASM"]
        assert {r["format"] for r in cat.search("format:solidworks", limit=100)["results"]} == {"solidworks"}
        assert len(cat.search("format:solidworks", limit=100)["results"]) == 19
        with pytest.raises(InvalidArgumentError):
            cat.search("format:dwg")
        cat.scan(pool=pool)
        assert pool.reset() == []  # an unchanged rescan reads nothing, model files included
        # Told to index SOLIDWORKS documents alone, the catalog forgets the model files at once,
        # with no change events: the files did not change.
        events = cat.con.execute("SELECT count(*) FROM events").fetchone()[0]
        cat.configure(formats="solidworks")
        status = _check("catalog", cat.status())
        assert status["formats"] == ["solidworks"] and status["counts"]["formats"] == {"solidworks": 19}
        assert status["counts"]["files"] == 19
        assert cat.con.execute("SELECT count(*) FROM events").fetchone()[0] == events
        assert cat.search("format:stl")["results"] == []
        data = cat.scan(pool=pool)
        assert (data["counts"]["seen"], data["counts"]["removed"], data["counts"]["added"]) == (19, 0, 0)
        assert pool.reset() == []


def test_the_formats_setting_is_checked_and_kept(tmp_path, pool):
    folder = _with_samples(tmp_path)
    with catalog.open(folder) as cat:
        for bad in ("iges", "dwg", ["stl", "nonsense"], []):
            with pytest.raises(InvalidArgumentError) as e:
                cat.configure(formats=bad)
            assert e.value.detail == {"parameter": "formats"}
        cat.configure(formats=["step", "stl"])
        assert cat.formats == {"step", "stl"} and cat.meta("formats") == "step,stl"
        data = cat.scan(pool=pool)
        assert data["counts"]["seen"] == 3  # two STEP samples and the STL, no SOLIDWORKS document
    with catalog.open(folder) as cat:  # kept with the catalog
        assert cat.formats == {"step", "stl"}
        assert _check("catalog", cat.status())["formats"] == ["step", "stl"]
    # an id a newer SolidSeas stored is passed over, not refused
    assert catalog.record.stored_formats("stl,shiny_new_format") == {"stl"}
    assert catalog.record.stored_formats(None) == {"solidworks"}


def test_a_model_record_reads_only_the_head(tmp_path, monkeypatch):
    """The worker reads a model file's head for its record: never its tree, scene, bodies
    or the files it names, which an Alibre assembly's tree would open."""
    from solidseas.catalog.record import build_model_record, check_preview, check_record
    from solidseas.formats import open_any
    from solidseas.formats.base import ModelDocument
    from solidseas_app.viewer import samples

    def refuse(*_a, **_k):
        raise AssertionError("the record read more than the head")

    folder = tmp_path / "samples"
    samples.write_samples(str(folder))
    for method in ("tree", "scene", "bodies", "references"):
        monkeypatch.setattr(ModelDocument, method, refuse)
    stored = 0
    for name, (fmt, doc_type, _items, _size) in samples.EXPECTED.items():
        with open_any(str(folder / name), within=str(folder), hold_open=True) as doc:
            data, image = build_model_record(doc)
        rec = check_record(data)
        assert (rec["format"], rec["doc_type"]) == (fmt, doc_type), name
        assert rec["stat"]["size"] == (folder / name).stat().st_size
        assert rec["configurations"] == rec["views"] == []
        if name == "pair.AD_ASM":  # its components, from its design database alone
            assert [(e[2], e[4]) for e in rec["edges"]] == [(rec["references"][0]["key"], 2)]
        else:
            assert rec["references"] == rec["edges"] == []
        if rec["preview"] is not None:
            assert check_preview(rec["preview"], image) == image and image.startswith(b"\x89PNG")
            stored += 1
        else:
            assert image is None
    assert stored == 3  # the 3MF and the two Alibre files store an image


def test_a_model_record_that_breaks_the_rules_is_refused(tmp_path):
    from solidseas.catalog.record import InvalidRecord, build_model_record, check_record
    from solidseas.formats import open_any
    from solidseas_app.viewer import samples

    folder = tmp_path / "samples"
    samples.write_samples(str(folder))
    with open_any(str(folder / "box.stl"), within=str(folder)) as doc:
        good, _image = build_model_record(doc)
    assert check_record(good)["format"] == "stl"
    bad = [
        {"format": "iges"},  # a format SolidSeas cannot read
        {"format": "solidworks"},  # a SOLIDWORKS document's format is its container's
        {"format": 7},
        {"doc_type": "drawing"},
        {"units": {"length": "mm", "scale_m": float("nan"), "source": "file"}},
        {"units": {"length": "mm", "scale_m": -1.0, "source": "file"}},
        {"units": {"length": "mm", "scale_m": True, "source": "file"}},
        {"units": {"length": "x" * 65, "scale_m": 0.001, "source": "file"}},
        {"counts": {**good["counts"], "triangles": -1}},
        {"counts": {**good["counts"], "faces": "12"}},
        {
            "configurations": [
                {
                    "name": "Default",
                    "id": 1,
                    "active": True,
                    "most_recent": None,
                    "comment": None,
                    "material": None,
                    "properties": [],
                }
            ]
        },
        {
            "references": good["references"]
            + [
                {
                    "key": "k",
                    "stored_path": None,
                    "file_name": "x.stl",
                    "doc_type": None,
                    "direct": True,
                    "virtual": False,
                    "imported": False,
                    "embedded": None,
                    "nested": None,
                    "stored_creation_time": None,
                    "parent_documents": 0,
                    "nested_identity": None,
                }
            ]
        },
        {"edges": [[None, None, "k", None, 1, 1, 1, None]]},
        {"views": [["Sheet1", "Drawing View1", None, "k"]]},
    ]
    for change in bad:
        with pytest.raises(InvalidRecord):
            check_record({**good, **change})


# --------------------------------------------------------------------------- Alibre Design
def _alibre_project(folder: Path) -> Path:
    """An Alibre part, a sub-assembly that places it twice and a top assembly that places
    the sub-assembly and the part once each, written by code (tests/alibre_writers.py)."""
    import alibre_writers as A

    folder.mkdir(parents=True, exist_ok=True)
    (folder / "cube.AD_PRT").write_bytes(A.part(guid=A.CUBE_GUID, version=3))
    cube = A.Placed(A.CUBE_GUID, version=3, stored_path="C:/Repository/Parts/cube")
    (folder / "sub.AD_ASM").write_bytes(A.assembly([cube, A.Placed(A.CUBE_GUID, version=3)], guid=A.SUB_GUID))
    sub = A.Placed(A.SUB_GUID, version=1, stored_path="C:/Repository/Assemblies/sub")
    (folder / "top.AD_ASM").write_bytes(A.assembly([sub, cube]))
    return folder


def _alibre_users(data: dict) -> list[tuple]:
    return [
        (
            u["depth"],
            u["path"],
            tuple(v["path"] for v in u["via"]),
            tuple((x["user_configuration"], x["instances"], x["in_bom"]) for x in u["uses"]),
            (u["resolution"] or {}).get("rule"),
            (u["resolution"] or {}).get("confidence"),
            tuple(w["code"] for w in u["warnings"]),
        )
        for u in data["users"]
    ]


def test_where_alibre_parts_and_sub_assemblies_are_used(tmp_path, pool):
    folder = _alibre_project(tmp_path / "alibre")
    with catalog.open(folder) as cat:
        cat.configure(formats="alibre")
        data = _check("catalog_scan", cat.scan(pool=pool))
        assert data["counts"]["read_ok"] == 3 and data["counts"]["resolved_documents"] == 2
        guids = dict(
            cat.con.execute("SELECT f.name, d.doc_guid FROM documents d JOIN files f ON f.id = d.file")
        )
        assert guids["cube.AD_PRT"] == "11111111-2222-3333-4444-555555555555"
        used = _check("where_used", cat.where_used("project", "cube.AD_PRT"))
        guid = ("document_guid", "high", ())
        assert _alibre_users(used) == [
            (1, "sub.AD_ASM", (), (("Config<0>", 2, 2),), *guid),
            (1, "top.AD_ASM", (), (("Config<0>", 1, 1),), *guid),
            (2, "top.AD_ASM", ("sub.AD_ASM",), (("Config<0>", 2, 2),), *guid),
        ]
        assert used["target"]["format"] == "alibre" and {u["format"] for u in used["users"]} == {"alibre"}
        assert used["counts"]["users"] == 2 and used["warnings"] == []
        used = _check("where_used", cat.where_used("project", "sub.AD_ASM"))
        assert _alibre_users(used) == [(1, "top.AD_ASM", (), (("Config<0>", 1, 1),), *guid)]
        assert cat.missing_references()["counts"]["documents"] == 0
        assert cat.status()["counts"]["references"] == {"resolved": 3}  # one per document placed
        # A copy of the part further down is a second file of that GUID: the one beside the
        # assemblies is used, with low confidence, and both are candidates.
        (folder / "old").mkdir()
        shutil.copy2(folder / "cube.AD_PRT", folder / "old" / "cube copy.AD_PRT")
        pool.reset()
        data = cat.scan(pool=pool)
        read = [n for job, n in pool.reset() if job == "catalog_document"]
        assert read == ["cube copy.AD_PRT"]  # read; the assemblies are not
        assert data["counts"]["resolved_documents"] == 2
        used = cat.where_used("project", "cube.AD_PRT")
        assert [(u["path"], u["resolution"]["confidence"]) for u in used["users"]][:2] == [
            ("sub.AD_ASM", "low"),
            ("top.AD_ASM", "low"),
        ]
        assert "component_ambiguous" in [w["code"] for w in used["users"][0]["warnings"]]
        assert cat.where_used("project", "old/cube copy.AD_PRT")["users"] == []
        missing = _check("missing_references", cat.missing_references())
        assert missing["counts"]["low_confidence"] == 2
        cands = {c["path"] for c in missing["documents"][0]["references"][0]["candidates"]}
        assert cands == {"cube.AD_PRT", "old/cube copy.AD_PRT"}
        # The part moved down: its only copy now holds the GUID, and the users follow it.
        os.remove(folder / "old" / "cube copy.AD_PRT")
        os.rename(folder / "cube.AD_PRT", folder / "old" / "cube.AD_PRT")
        data = cat.scan(pool=pool)
        assert data["counts"]["moved"] == 1
        used = cat.where_used("project", "old/cube.AD_PRT")
        assert [(u["depth"], u["path"], u["resolution"]["confidence"]) for u in used["users"]] == [
            (1, "sub.AD_ASM", "high"),
            (1, "top.AD_ASM", "high"),
            (2, "top.AD_ASM", "high"),
        ]
        # Gone: missing, within the indexed folders.
        os.remove(folder / "old" / "cube.AD_PRT")
        cat.scan(pool=pool)
        missing = cat.missing_references()
        assert missing["counts"]["missing"] == 2
        assert {r["file_name"] for d in missing["documents"] for r in d["references"]} == {"cube"}


def test_an_alibre_component_of_another_version_or_found_by_name(tmp_path, pool):
    import alibre_writers as A

    folder = _alibre_project(tmp_path / "alibre")
    (folder / "cube.AD_PRT").write_bytes(A.part(guid=A.CUBE_GUID, version=5))  # newer than asked for
    with catalog.open(folder) as cat:
        cat.configure(formats="all")
        cat.scan(pool=pool)
        used = cat.where_used("project", "cube.AD_PRT")
        assert {w["code"] for u in used["users"] for w in u["warnings"]} == {"component_newer"}
        # A part whose GUID cannot be read is the stored name's only in the assembly's folder.
        (folder / "cube.AD_PRT").write_bytes(A.part(guid=A.CUBE_GUID, streams={"VERSION": A.ustr("garbled")}))
        cat.scan(pool=pool)
        assert cat.con.execute(
            "SELECT f.state, d.doc_guid FROM documents d JOIN files f ON f.id = d.file WHERE f.name = "
            "'cube.AD_PRT'"
        ).fetchone() == ("ok", None)
        used = cat.where_used("project", "cube.AD_PRT")
        assert [(u["path"], u["resolution"]["rule"], u["resolution"]["confidence"]) for u in used["users"]][
            :2
        ] == [("sub.AD_ASM", "name", "low"), ("top.AD_ASM", "name", "low")]
        assert "component_found_by_name" in [w["code"] for w in used["users"][0]["warnings"]]
        # An Alibre assembly that could not be read may use it too: where-used says so.
        (folder / "broken.AD_ASM").write_bytes(b"not an Alibre file" * 20)
        cat.scan(pool=pool)
        warned = [w["code"] for w in cat.where_used("project", "cube.AD_PRT")["warnings"]]
        assert "unread_documents" in warned


def test_a_hostile_alibre_record_is_refused(tmp_path):
    import alibre_writers as A
    from solidseas.catalog.record import InvalidRecord, build_model_record, check_record
    from solidseas.formats import open_any

    folder = _alibre_project(tmp_path / "alibre")
    with open_any(str(folder / "top.AD_ASM"), within=str(folder)) as doc:
        good, _image = build_model_record(doc)
    rec = check_record(good)
    assert rec["document"] == {"guid": A.ASM_GUID, "version": 1} and rec["references_state"] == "described"
    assert [(r["key"], r["version"], r["file_name"]) for r in rec["references"]] == [
        (A.SUB_GUID, 1, "sub"),
        (A.CUBE_GUID, 3, "cube"),
    ]
    assert rec["edges"] == [
        (None, "Config<0>", A.SUB_GUID, None, 1, 1, 1, None),
        (None, "Config<0>", A.CUBE_GUID, None, 1, 1, 1, None),
    ]
    ref = good["references"][0]
    bad = [
        {"document": {"guid": "../../etc", "version": 1}},
        {"document": {"guid": A.ASM_GUID.upper(), "version": 1}},
        {"document": {"guid": A.ASM_GUID, "version": "1"}},
        {"references": [{**ref, "key": "not-a-guid"}]},
        {"references": [{**ref, "version": 1.5}]},
        {"edges": [[None, None, "22222222-2222-2222-2222-222222222222", None, 1, 1, 1, None]]},  # no such ref
        {"edges": [[A.SUB_GUID, None, A.CUBE_GUID, None, 1, 1, 1, None]]},  # no tree inside a model file
        {"format": "step"},  # only Alibre files' references are followed
    ]
    for change in bad:
        with pytest.raises(InvalidRecord):
            check_record({**good, **change})
    with pytest.raises(InvalidRecord):  # a SOLIDWORKS record names no Alibre document
        with open_document(str(FIXTURES / "o02_boxA.SLDPRT")) as doc:
            data, _image = catalog.record.build_record(doc)
        check_record({**data, "document": {"guid": A.ASM_GUID, "version": 1}})


@pytest.mark.skipif(sqlite3.sqlite_version_info < (3, 35), reason="the test drops columns (SQLite 3.35)")
def test_a_version_1_catalog_is_migrated_in_place(tmp_path, pool):
    """Version 2 added the Alibre GUID columns: a version 1 catalog gains them in place,
    equal to a new one's, and reads its Alibre files again, nothing else."""
    folder = _with_samples(tmp_path)
    db = tmp_path / "cat.sqlite"
    with catalog.open(folder, db=db) as cat:
        cat.configure(formats="all")
        cat.scan(pool=pool)
        fresh = {t: cat.con.execute(f"PRAGMA table_info({t})").fetchall() for t in ("documents", "refs")}
        indexes = {r[0] for r in cat.con.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    con = sqlite3.connect(db)  # make it what version 1 wrote
    con.execute("DROP INDEX documents_guid")
    for table, column in (("documents", "doc_guid"), ("documents", "doc_version"), ("refs", "doc_version")):
        con.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    con.execute("PRAGMA user_version=1")
    con.commit()
    con.close()
    pool.reset()
    with catalog.open(folder, db=db) as cat:
        assert cat.con.execute("PRAGMA user_version").fetchone()[0] == schema.SCHEMA_VERSION == 2
        assert {
            t: cat.con.execute(f"PRAGMA table_info({t})").fetchall() for t in ("documents", "refs")
        } == fresh
        assert {
            r[0] for r in cat.con.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
        } == indexes
        cat.scan(pool=pool)
        read = sorted(n for job, n in pool.reset() if job == "catalog_document")
        assert read == ["cube.AD_PRT", "pair.AD_ASM"]
        assert cat.con.execute("SELECT count(*) FROM documents WHERE doc_guid IS NOT NULL").fetchone()[0] == 2
