"""Reference resolution inside the catalog, from rows, with no file opened.

Each assembly and drawing is resolved with
:func:`solidseas.resolve.resolve_references` itself, so the rules, confidence
levels and warnings are those of ``docs/API.md`` 3.10:

* the :class:`~solidseas.resolve.ResolutionInput` is rebuilt from the
  document's ``folder_at_save`` and its ``refs`` rows, with the document's host
  path from its root and relative path;
* the roots are the catalog's, in their order;
* each root's :class:`~solidseas.resolve.index.FolderIndex` is filled from the
  ``folders`` and ``files`` rows (placeholders included) and handed to the
  resolver in an :class:`~solidseas.resolve.IndexCache`, so no folder is walked;
* identity reads are answered from the creation time stored for the candidate's
  row, and only while that row's read size and time equal the listing's; a row
  not read yet is ``skipped`` and one that could not be read answers with its
  error code, as the live gateway would;
* nothing outside the roots is looked at (``allow_outside_roots=False``): a
  component found only at its stored path outside every root is ``missing``
  here, which is why the catalog's answers say "within the indexed folders".

Results go to the ``refs`` rows (status, rule, confidence, identity, the target
row, warning codes) and, for ambiguous and low-confidence results, to
``ref_candidates``.

An Alibre Design assembly names each component by its document GUID, which no
SOLIDWORKS rule knows: :func:`resolve_alibre` finds it among the rows by the GUID
each Alibre file's record gave, with the order and warnings of the live
resolver (:mod:`solidseas.formats.alibre.resolve`), within the roots alone:

* one file with the GUID is ``resolved`` (rule ``document_guid``, confidence
  ``high``, identity ``match``); among several, the one in the assembly's own
  folder, then below it, then the fewest folders down, the shortest path, the
  version asked for, the root's order and the path, with confidence ``low``,
  the warning ``component_ambiguous`` and every one in ``ref_candidates``; a
  newer or older version than the one asked for is warned ``component_newer``
  or ``component_older``;
* failing that, a file in the assembly's folder whose name is the stored name
  with an Alibre extension, and whose GUID could not be read (it could not be
  read, or its ``VERSION`` stream could not), is ``resolved`` by rule ``name``,
  confidence ``low``, identity ``unknown``, warned ``component_found_by_name``:
  one whose GUID was read is another document;
* otherwise the reference is ``missing``.
"""

import json
import os
import time
from collections.abc import Callable, Iterable

from ..resolve import IndexCache, InputFile, ResolutionInput, resolve_references
from ..resolve.gateway import Gateway
from ..resolve.identity import Identity
from ..resolve.index import FolderIndex
from ..resolve.names import fold, host_split
from ..roots import Root, Roots

ALIBRE_EXTENSIONS = (".ad_prt", ".ad_asm", ".ad_smp")
MAX_SECONDS_PER_DOCUMENT = 15.0
MAX_CANDIDATES = 20
MAX_IDENTITY_READS = 5_000
_SEP = "\\" if os.name == "nt" else "/"


def host_path(root_path: str, rel: str) -> str:
    """The absolute host path of ``rel`` below a root, as the folder index builds it."""
    return host_split(root_path).child(*rel.split("/")).join()


class RowIndexes:
    """The folder index of every root of a catalog, from its rows, and the identity
    reader that answers from them."""

    def __init__(self, con, roots: list[tuple[int, Root, str | None]]) -> None:
        self.con = con
        self.roots = roots  # (db id, Root, partial reason)
        self.cache = IndexCache()
        self._by_root_id = {r.id: (db, r) for db, r, _p in roots}
        self._ident: dict[str, Identity] = {}
        for db, root, partial in roots:
            index = FolderIndex(root, host_split(root.path))
            for rel, name in con.execute("SELECT rel, name FROM folders WHERE root = ? AND rel <> ''", (db,)):
                index.add_folder(rel, name)
            for rel, name, size, mtime, kind in con.execute(
                "SELECT rel, name, size, mtime_ns, kind FROM files WHERE root = ?", (db,)
            ):
                index.add_file(rel, name, size, mtime, kind == "placeholder")
            index.partial = partial
            self.cache.indexes[(fold(root.path), root.recursive)] = index

    def file_row(self, root_id: str, rel: str) -> int | None:
        found = self._by_root_id.get(root_id)
        if found is None:
            return None
        row = self.con.execute("SELECT id FROM files WHERE root = ? AND rel = ?", (found[0], rel)).fetchone()
        return row[0] if row else None

    def _locate(self, path: str) -> tuple[int, str] | None:
        # The gateway asks for paths its folder index built from the root's own host path,
        # so the root's part is spelled exactly as here.
        for db, root, _p in self.roots:
            base = host_split(root.path).join().rstrip("\\/") + _SEP
            if path.startswith(base):
                return db, path[len(base) :].replace(_SEP, "/")
        return None

    def identity(self, path: str) -> Identity:
        found = self._locate(path)
        if found is None:
            return Identity(None, error="not_found")
        row = self.con.execute(
            "SELECT f.state, f.size, f.mtime_ns, f.read_size, f.read_mtime_ns, f.error_code, "
            "d.creation_time, d.creation_source FROM files f LEFT JOIN documents d ON d.file = f.id "
            "WHERE f.root = ? AND f.rel = ?",
            found,
        ).fetchone()
        if row is None:
            return Identity(None, error="not_found")
        state, size, mtime, rsize, rmtime, code, ct, src = row
        if state == "ok":
            if (rsize, rmtime) != (size, mtime):
                return Identity(None, skipped=True)
            return Identity(ct, src)
        if state in ("error", "quarantined"):
            return Identity(None, error=code or "internal")
        if state == "not_solidworks":
            return Identity(None, error="unknown_format")
        if state == "placeholder":
            return Identity(None, placeholder=True)
        return Identity(None, skipped=True)  # pending: not read yet

    def reader(self, items: list[tuple[str, str]]) -> list[Identity]:
        return [self.identity(path) for path, _within in items]


def resolution_input(con, file_id: int, doc_path: str) -> ResolutionInput:
    """The resolution input of one document, rebuilt from its rows."""
    row = con.execute("SELECT folder_at_save FROM documents WHERE file = ?", (file_id,)).fetchone()
    folder = row[0] if row else None
    files = []
    for (
        key,
        stored_path,
        direct,
        embedded,
        nested,
        stored_ct,
        parents,
        nct,
        nsrc,
        nerr,
    ) in con.execute(
        "SELECT key, stored_path, direct, embedded, nested, stored_creation_time, parent_documents, "
        "nested_creation_time, nested_identity_source, nested_identity_error FROM refs WHERE file = ? "
        "ORDER BY position",
        (file_id,),
    ):
        nested_identity = Identity(nct, nsrc, nerr) if embedded == "embedded" and nested else None
        files.append(
            InputFile(
                key=key,
                stored_path=stored_path,
                direct=None if direct is None else bool(direct),
                embedded=embedded,
                nested=nested,
                stored_creation_time=stored_ct,
                parent_documents=parents,
                nested_identity=nested_identity,
            )
        )
    return ResolutionInput(doc_path, folder, tuple(files))


def resolve_documents(
    con,
    indexes: RowIndexes,
    roots: Roots,
    documents: Iterable[tuple[int, str]],
    *,
    scan_id: int,
    over: Callable[[], bool],
    begin: Callable[[], None],
    commit: Callable[[], None],
    errors: list,
    progress: Callable[[int], None] | None = None,
) -> int:
    """Resolve each ``(file id, host path)`` document and store its results; returns how
    many were resolved. ``over`` stops between documents; ``begin`` opens the writer's
    transaction (when none is open) before a document's results are written and
    ``commit`` counts the document into the writer's batch."""
    root_db = {r.id: db for db, r, _p in indexes.roots}
    done = 0
    for file_id, path in documents:
        if over():
            break
        try:
            inp = resolution_input(con, file_id, path)
            gw = Gateway(
                allow_outside_roots=False,
                identity_reader=indexes.reader,
                max_identity_reads=MAX_IDENTITY_READS,
                deadline=time.monotonic() + MAX_SECONDS_PER_DOCUMENT,
            )
            res = resolve_references(
                inp,
                roots,
                allow_outside_roots=False,
                cache=indexes.cache,
                gateway=gw,
                skip_unavailable_roots=True,
                max_seconds=MAX_SECONDS_PER_DOCUMENT,
                max_candidates=MAX_CANDIDATES,
            )
        except Exception as exc:  # one document never stops the phase
            errors.append((file_id, exc))
            begin()
            con.execute("UPDATE files SET resolve = 0 WHERE id = ?", (file_id,))
            commit()
            continue

        def row_of(loc) -> int | None:
            if loc is None or loc.root is None or loc.root not in root_db:
                return None
            hit = con.execute(
                "SELECT id FROM files WHERE root = ? AND rel = ?", (root_db[loc.root], loc.path)
            ).fetchone()
            return hit[0] if hit else None

        begin()
        con.execute("DELETE FROM ref_candidates WHERE file = ?", (file_id,))
        for key, r in res.results.items():
            codes = sorted({w.code for w in r.warnings})
            con.execute(
                "UPDATE refs SET status = ?, rule = ?, confidence = ?, identity = ?, target = ?, warnings = "
                "?, resolved_scan = ? WHERE file = ? AND key = ?",
                (
                    r.status,
                    r.rule,
                    r.confidence,
                    r.identity,
                    row_of(r.match),
                    json.dumps(codes) if codes else None,
                    scan_id,
                    file_id,
                    key,
                ),
            )
            if r.status == "ambiguous" or r.confidence == "low":
                for c in r.candidates:
                    cand = row_of(c.location)
                    if cand is not None:
                        con.execute(
                            "INSERT INTO ref_candidates (file, key, candidate, found_by, identity) VALUES "
                            "(?, ?, ?, ?, ?)",
                            (file_id, key, cand, c.found_by, c.identity),
                        )
        con.execute("UPDATE files SET resolve = 0 WHERE id = ?", (file_id,))
        done += 1
        commit()
        if progress is not None:
            progress(done)
    return done


def resolve_alibre(con, file_id: int, *, scan_id: int) -> None:
    """Resolve the components of the Alibre assembly ``file_id`` from rows, by document
    GUID, and store the results (see the module notes)."""
    root, rel = con.execute("SELECT root, rel FROM files WHERE id = ?", (file_id,)).fetchone()
    folder = rel.rpartition("/")[0]
    below = folder + "/" if folder else ""

    def where(c_root: int, c_rel: str) -> tuple:
        c_folder = c_rel.rpartition("/")[0]
        own = c_root == root and c_folder == folder
        under = c_root == root and c_rel.startswith(below)
        depth = c_rel[len(below) :].count("/") if under else c_rel.count("/")
        return (not own, not under, depth, len(c_rel))

    con.execute("DELETE FROM ref_candidates WHERE file = ?", (file_id,))
    refs = con.execute(
        "SELECT key, file_name, doc_version FROM refs WHERE file = ? ORDER BY position", (file_id,)
    ).fetchall()
    for key, stored_name, version in refs:
        found = con.execute(
            "SELECT f.id, f.root, f.rel, d.doc_version, ro.position FROM documents d JOIN files f ON f.id = "
            "d.file JOIN roots ro ON ro.id = f.root WHERE d.doc_guid = ? AND d.format = 'alibre' AND "
            "f.state = 'ok' AND f.id <> ?",
            (key, file_id),
        ).fetchall()
        found.sort(key=lambda c: (*where(c[1], c[2]), c[3] != version, c[4], c[2]))
        codes: list[str] = []
        cands: list[tuple[int, str, str]] = []
        if found:
            target, _r, _p, got, _pos = found[0]
            status, rule, identity = "resolved", "document_guid", "match"
            confidence = "high" if len(found) == 1 else "low"
            if len(found) > 1:
                codes.append("component_ambiguous")
                cands = [(c[0], "document_guid", "match") for c in found]
            if version is not None and got is not None and got != version:
                codes.append("component_newer" if got > version else "component_older")
        else:
            target = None
            want = (stored_name or "").casefold()
            if want:
                for c_id, c_name, c_state, c_guid in con.execute(
                    "SELECT f.id, f.name, f.state, d.doc_guid FROM files f JOIN folders fo ON fo.id = "
                    "f.folder LEFT JOIN documents d ON d.file = f.id WHERE f.root = ? AND fo.rel = ? AND "
                    "f.kind = 'file' AND f.id <> ? ORDER BY f.rel",
                    (root, folder, file_id),
                ):
                    stem, ext = os.path.splitext(c_name)
                    if ext.lower() not in ALIBRE_EXTENSIONS or stem.casefold() != want:
                        continue
                    if c_state in ("error", "quarantined") or (c_state == "ok" and c_guid is None):
                        target = c_id  # its GUID could not be read; one whose GUID was read is another
                        break
            if target is not None:
                status, rule, confidence, identity = "resolved", "name", "low", "unknown"
                codes.append("component_found_by_name")
                cands = [(target, "name", "unknown")]
            else:
                status, rule, confidence, identity = "missing", None, "none", "unknown"
        con.execute(
            "UPDATE refs SET status = ?, rule = ?, confidence = ?, identity = ?, target = ?, warnings = ?, "
            "resolved_scan = ? WHERE file = ? AND key = ?",
            (
                status,
                rule,
                confidence,
                identity,
                target,
                json.dumps(codes) if codes else None,
                scan_id,
                file_id,
                key,
            ),
        )
        for cand, found_by, ident in cands:
            con.execute(
                "INSERT INTO ref_candidates (file, key, candidate, found_by, identity) VALUES "
                "(?, ?, ?, ?, ?)",
                (file_id, key, cand, found_by, ident),
            )
    con.execute("UPDATE files SET resolve = 0 WHERE id = ?", (file_id,))


__all__ = [
    "ALIBRE_EXTENSIONS",
    "RowIndexes",
    "host_path",
    "resolution_input",
    "resolve_alibre",
    "resolve_documents",
]
