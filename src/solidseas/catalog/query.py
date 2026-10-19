"""The catalog's read-only queries: status, where-used, search, duplicates, missing
references and recent changes.

Every function takes a connection (a reader's, or the writer's in its own
thread) and returns plain JSON data, the ``data`` of its kind
(``docs/API.md`` 3.18 and 5.15), identical on every surface. A query that
reads several tables runs inside one read transaction, so it sees one snapshot
while a scan writes.

Locations are root ids and paths relative to the root (C1). Absolute paths
appear only as the roots' own paths in :func:`status`, and only when
``paths=True`` (Python and the command line; the service leaves them out).

**Where-used** follows resolved references (``refs.target``), never names:

* direct users: the assemblies whose own tree holds the file, with the
  quantity per configuration of the user and of the file (instances,
  unsuppressed, in the BOM), and the drawings whose views show it;
* an assembly with no component tree (its files named only in its header) is a
  direct user with no quantities and the warning ``quantity_unknown``; nothing
  above it is followed;
* indirect users: every assembly above those, through each sub-assembly's own
  document (what SOLIDWORKS loads), with quantities multiplied along the
  configuration chain. Unsuppressed and in-BOM counts multiply only through
  unsuppressed and in-BOM links, so a sub-assembly left out of the BOM takes
  its components with it. A drawing of an indirect user is
  ``drawing_of_assembly``;
* where a sub-assembly's own document cannot answer (it resolves to no file
  of the catalog, or to one not read, unreadable, a cloud placeholder, cut for
  size or without a component tree), what the top document's own tree stores
  inside it answers instead (``stored_tree``, warning ``from_parent_tree``), so
  a part inside a missing or unreadable sub-assembly still shows its top
  assembly; the warning ``unread_documents`` says the catalog holds assemblies
  or drawings it could not read;
* ``possible``: ambiguous references among whose candidates the file is;
  ``name_matches``: missing or ambiguous references whose file name is the
  file's. Neither is counted.

Every walk up is bounded whatever the stored trees hold: 32 levels,
:data:`MAX_USERS` users and :data:`WORK_STEPS` steps, then ``truncated``; a
``deadline`` holds inside the pure-Python climb as well as in the SQL.
"""

import base64
import datetime
import hashlib
import json
import re
import time
from typing import Any

from .. import model
from ..errors import (
    WARNING_CODES,
    ConfigurationNotFoundError,
    InvalidArgumentError,
    NotInCatalogError,
)
from ..formats import registry
from ..resolve.names import fold
from .record import file_format, stored_formats

FOUND = ("resolved", "moved")
UNRESOLVED = ("missing", "ambiguous", "embedded_not_found")
DEFAULT_MAX_DEPTH = 32
MAX_USERS = 10_000
MAX_LIMIT = 500
SORTS = ("relevance", "name", "modified")
RELATIONS = ("component", "drawing_view", "drawing_of_assembly", "stored_tree")
FILTERS = ("type", "format", "root", "folder", "pn", "desc", "prop", "changed")
TYPE_WORDS = {
    "part": "part",
    "parts": "part",
    "assembly": "assembly",
    "assemblies": "assembly",
    "drawing": "drawing",
}
# The type a file's extension says, for a file whose document was not read.
TYPE_EXTENSIONS = {
    "part": (".sldprt", ".ad_prt"),
    "assembly": (".sldasm", ".ad_asm"),
    "drawing": (".slddrw",),
}
MAX_OFFSET = 1 << 40  # a cursor's offset: far past any catalog, well inside SQLite's integers
WORK_STEPS = 200_000  # how far where-used goes up, in references, chains and uses, before truncated
_SPAN = re.compile(r"\A(\d{1,5})([hdw])\Z")
_DATE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# The files a scan hashes, by the policy each root's last scan applied (roots.hash_policy):
# "all" every file, "duplicates" only those whose size another file shares (which still finds
# every duplicate), "none" nothing. The same rule counts the hashes still to take, so a scan's
# hash_pending and the queries' agree.
_SHARED_SIZES = (
    "SELECT size FROM files WHERE kind = 'file' AND size IS NOT NULL GROUP BY size HAVING count(*) > 1"
)
HASH_WANTED = (
    "f.kind = 'file' AND f.stale = 0 AND (f.sha256 IS NULL OR f.hash_size IS NOT f.size OR "
    "f.hash_mtime_ns IS NOT f.mtime_ns) AND (coalesce(ro.hash_policy, 'all') = 'all' OR "
    f"(ro.hash_policy = 'duplicates' AND f.size IN ({_SHARED_SIZES})))"
)
# Whether the catalog holds an assembly or drawing it could not read (an error, a cloud placeholder
# never read, a document cut for size): it may use any file, so where-used says so. Both halves
# are answered by partial indexes.
_UNREAD_USERS = (
    "SELECT EXISTS (SELECT 1 FROM files WHERE state <> 'ok' AND state IN ('error', 'quarantined', "
    "'placeholder') AND ext IN ('.sldasm', '.slddrw', '.ad_asm')) OR EXISTS (SELECT 1 FROM documents d JOIN "
    "files f ON f.id = d.file WHERE d.references_state = 'truncated' AND f.state = 'ok')"
)


def hash_pending(con) -> int:
    """How many files the hash policy wants hashed that have no current hash."""
    return con.execute(
        f"SELECT count(*) FROM files f JOIN roots ro ON ro.id = f.root WHERE {HASH_WANTED}"
    ).fetchone()[0]


# --------------------------------------------------------------------------- helpers
def _warning(code: str) -> dict[str, Any]:
    return {"code": code, "stream": None, "message": WARNING_CODES.get(code, code)}


def _codes(text: str | None) -> list[str]:
    if not text:
        return []
    try:
        value = json.loads(text)
    except ValueError:
        return []
    return [c for c in value if isinstance(c, str)] if isinstance(value, list) else []


def _modified(mtime_ns: int | None) -> str | None:
    if mtime_ns is None:
        return None
    return model.file_object(None, 0, mtime_ns)["modified_utc"]


def _fold_eq(a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return a.casefold() == b.casefold()


class _Snapshot:
    """One read transaction around a query (a reader sees one consistent state)."""

    def __init__(self, con) -> None:
        self.con = con
        self.own = False

    def __enter__(self):
        if not self.con.in_transaction:
            self.con.execute("BEGIN")
            self.own = True
        return self.con

    def __exit__(self, *exc) -> None:
        if self.own:
            self.con.execute("COMMIT")


def _cursor(offset: int, key: str) -> str:
    raw = json.dumps({"o": offset, "q": key}, separators=(",", ":")).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _offset(cursor: str | None, key: str) -> int:
    if cursor is None:
        return 0
    try:
        pad = "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(cursor + pad))
        offset = data["o"]
        if (
            data["q"] != key
            or not isinstance(offset, int)
            or isinstance(offset, bool)
            or not 0 <= offset <= MAX_OFFSET
        ):
            raise ValueError
        return offset
    except (ValueError, KeyError, TypeError):
        raise InvalidArgumentError(
            "the cursor is not one this query gave", detail={"parameter": "cursor"}
        ) from None


def _limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise InvalidArgumentError(f"limit is 1 to {MAX_LIMIT}", detail={"parameter": "limit"})
    return limit


def _key(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, default=str).encode("utf-8")).hexdigest()[:16]


class _Files:
    """File rows by id, read once each per query."""

    def __init__(self, con) -> None:
        self.con = con
        self._rows: dict[int, dict[str, Any]] = {}

    def get(self, fid: int) -> dict[str, Any]:
        row = self._rows.get(fid)
        if row is None:
            r = self.con.execute(
                "SELECT f.id, ro.root_id, f.rel, f.name, d.doc_type, d.active_configuration, f.state, "
                "f.sha256, d.format FROM files f JOIN roots ro ON ro.id = f.root LEFT JOIN documents d ON "
                "d.file = f.id WHERE f.id = ?",
                (fid,),
            ).fetchone()
            row = {
                "id": r[0],
                "root": r[1],
                "path": r[2],
                "name": r[3],
                "doc_type": r[4] or _type_of(r[3]),
                "format": file_format(r[8], r[3]),
                "active": r[5],
                "state": r[6],
                "sha256": r[7],
            }
            self._rows[fid] = row
        return row


def _type_of(name: str) -> str | None:
    lower = name.lower()
    for t, exts in TYPE_EXTENSIONS.items():
        if lower.endswith(exts):
            return t
    return None


def find_file(con, root: str, path: str) -> int:
    """The row id of the file at ``path`` below root ``root``: the exact spelling, else
    the one file that matches case-insensitively. Raises ``not_in_catalog``."""
    if not isinstance(root, str) or not isinstance(path, str):
        raise InvalidArgumentError("a file is a root id and a path", detail={"parameter": "path"})
    rel = path.replace("\\", "/").strip("/")
    row = con.execute(
        "SELECT f.id FROM files f JOIN roots r ON r.id = f.root WHERE r.root_id = ? AND f.rel = ?",
        (root, rel),
    ).fetchone()
    if row is not None:
        return row[0]
    name = rel.rpartition("/")[2]
    cands = [
        fid
        for fid, frel in con.execute(
            "SELECT f.id, f.rel FROM files f JOIN roots r ON r.id = f.root WHERE r.root_id = ? AND "
            "f.name_fold = ?",
            (root, fold(name)),
        )
        if fold(frel) == fold(rel)
    ]
    if len(cands) == 1:
        return cands[0]
    raise NotInCatalogError("the file is not in the catalog: index its folder first")


# --------------------------------------------------------------------------- status
def counts(con) -> dict[str, Any]:
    by_type = dict(
        con.execute(
            "SELECT d.doc_type, count(*) FROM files f JOIN documents d ON d.file = f.id GROUP BY d.doc_type"
        ).fetchall()
    )
    formats: dict[str, int] = {}
    for fmt, n in con.execute(
        "SELECT d.format, count(*) FROM files f JOIN documents d ON d.file = f.id GROUP BY d.format"
    ):
        key = file_format(fmt, "") or fmt
        formats[key] = formats.get(key, 0) + n
    states = dict(con.execute("SELECT state, count(*) FROM files GROUP BY state").fetchall())
    refs = {
        s: n for s, n in con.execute("SELECT status, count(*) FROM refs GROUP BY status") if s is not None
    }
    unresolved = con.execute("SELECT count(*) FROM refs WHERE status IS NULL").fetchone()[0]
    groups = con.execute(
        "SELECT count(*) FROM (SELECT sha256 FROM files WHERE sha256 IS NOT NULL GROUP BY sha256 HAVING "
        "count(*) > 1)"
    ).fetchone()[0]
    return {
        "files": sum(states.values()),
        "documents": sum(by_type.values()),
        "formats": dict(sorted(formats.items())),
        "parts": by_type.get("part", 0),
        "assemblies": by_type.get("assembly", 0),
        "drawings": by_type.get("drawing", 0),
        "pending": states.get("pending", 0),
        "read_errors": states.get("error", 0) + states.get("quarantined", 0),
        "quarantined": states.get("quarantined", 0),
        "not_solidworks": states.get("not_solidworks", 0),
        # cloud placeholders, those read before their data was freed included
        "placeholders": con.execute("SELECT count(*) FROM files WHERE kind = 'placeholder'").fetchone()[0],
        "stale": con.execute("SELECT count(*) FROM files WHERE stale = 1").fetchone()[0],
        "resolve_pending": con.execute("SELECT count(*) FROM files WHERE resolve = 1").fetchone()[0],
        "hash_pending": hash_pending(con),
        "references": refs,
        "references_unresolved": unresolved,
        "duplicate_groups": groups,
    }


def _scan_time(con, scan: int | None) -> str | None:
    if scan is None:
        return None
    row = con.execute("SELECT finished_utc, started_utc FROM scans WHERE id = ?", (scan,)).fetchone()
    return (row[0] or row[1]) if row else None


def complete(con) -> bool:
    """No row waits to be read or resolved, none is stale, and no root is partial."""
    for cond in ("state = 'pending'", "stale = 1", "resolve = 1"):  # each answered by its partial index
        if con.execute(f"SELECT EXISTS (SELECT 1 FROM files WHERE {cond})").fetchone()[0]:
            return False
    return not con.execute("SELECT EXISTS (SELECT 1 FROM roots WHERE state <> 'ready')").fetchone()[0]


def status(
    con,
    *,
    name: str,
    location: str,
    sizes: dict[str, int | None],
    paths: bool = True,
    writer: bool | None = None,
) -> dict[str, Any]:
    """``catalog`` data. ``writer`` says whether a writer holds the catalog's lock (None:
    not known): a last scan still marked running with no writer left was cut short (its
    process ended), and is reported ``failed``, as the next writer records it."""
    with _Snapshot(con):
        meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
        last = con.execute(
            "SELECT id, started_utc, finished_utc, state FROM scans ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if last is not None and last[3] == "running" and writer is False:
            last = (*last[:3], "failed")
        roots = []
        for (
            rid,
            root_id,
            path,
            role,
            recursive,
            state,
            partial,
            last_scan,
            last_complete,
            policy,
        ) in con.execute(
            "SELECT id, root_id, path, role, recursive, state, partial, last_scan, last_complete_scan, "
            "hash_policy FROM roots ORDER BY position"
        ).fetchall():
            roots.append(
                {
                    "id": root_id,
                    "path": path if paths else None,
                    "role": role,
                    "recursive": bool(recursive),
                    "state": state,
                    "partial": partial,
                    "hash_policy": policy,
                    "last_scan_utc": _scan_time(con, last_scan),
                    "last_complete_scan_utc": _scan_time(con, last_complete),
                    "documents": con.execute(
                        "SELECT count(*) FROM files f JOIN documents d ON d.file = f.id WHERE f.root = ?",
                        (rid,),
                    ).fetchone()[0],
                    "files": con.execute("SELECT count(*) FROM files WHERE root = ?", (rid,)).fetchone()[0],
                }
            )
        c = counts(con)
        if last is None:
            state = "empty"
        elif last[3] == "running":
            state = "scanning"
        elif complete(con):
            state = "ready"
        else:
            state = "partial"
        data = {
            "name": name,
            "location": location,
            "schema_version": int(con.execute("PRAGMA user_version").fetchone()[0]),
            "state": state,
            "search_engine": meta.get("search_engine", "like"),
            "hash_policy": meta.get("hash_policy") or None,
            "part_number_property": meta.get("part_number_property") or None,
            "formats": sorted(stored_formats(meta.get("formats"))),
            "last_scan": None
            if last is None
            else {"id": last[0], "started_utc": last[1], "finished_utc": last[2], "state": last[3]},
            "roots": roots,
            "counts": c,
            "sizes": dict(sizes),
        }
    return model.to_json_data(data)


# --------------------------------------------------------------------------- where-used
def _compose(edges: list[tuple], uses: list[tuple] | None, active: str | None) -> list[tuple]:
    """Uses one level up: ``edges`` are (parent configuration, child configuration,
    instances, unsuppressed, in BOM) of a parent holding a child; ``uses`` are (child
    configuration, target configuration, instances, unsuppressed, in BOM, the
    configurations in between) of the child holding the target, or None when the child
    is the target. Equal configuration chains are summed."""
    out: dict[tuple, list[int]] = {}
    for p_cfg, c_cfg, i1, u1, b1 in edges:
        if uses is None:
            key = (p_cfg, c_cfg, ())
            acc = out.setdefault(key, [0, 0, 0])
            acc[0] += i1
            acc[1] += u1
            acc[2] += b1
            continue
        want = c_cfg if c_cfg is not None else active
        for x_cfg, t_cfg, i2, u2, b2, chain in uses:
            if not _fold_eq(want, x_cfg) and not (want is None and c_cfg is None):
                continue
            key = (p_cfg, t_cfg, (x_cfg, *chain))
            acc = out.setdefault(key, [0, 0, 0])
            acc[0] += i1 * i2
            acc[1] += u1 * u2
            acc[2] += b1 * b2
    return [(k[0], k[1], v[0], v[1], v[2], k[2]) for k, v in out.items()]


def _uses_data(uses: list[tuple]) -> list[dict[str, Any]]:
    return [
        {
            "user_configuration": p,
            "configuration": t,
            "via_configurations": list(chain),
            "instances": i,
            "unsuppressed": u,
            "in_bom": b,
        }
        for p, t, i, u, b, chain in sorted(uses, key=lambda x: (x[0] or "", x[1] or "", x[5]))
    ]


class _Exhausted(Exception):
    """The where-used walk reached one of its bounds: what it found so far is the answer,
    ``truncated``."""


class _Budget:
    """How far one where-used walk may go: :data:`WORK_STEPS` steps (a reference followed,
    a chain of a stored tree climbed, a configuration use composed), whatever path they
    take, and the caller's ``deadline`` (``time.monotonic()``), checked every 256 steps so
    the pure-Python climb stops in time as well as the SQL."""

    def __init__(self, deadline: float | None) -> None:
        self.steps = 0
        self.deadline = deadline
        self.exhausted = False
        self._check = 256

    def spend(self, n: int = 1) -> None:
        self.steps += n
        if self.steps > WORK_STEPS:
            raise _Exhausted
        if self.deadline is not None and self.steps >= self._check:
            self._check = self.steps + 256
            if time.monotonic() > self.deadline:
                raise TimeoutError("the where-used query did not finish in time")


class _Doc:
    """One referencing document's rows, read per key as the query needs them (an index
    lookup each) and kept for the rest of the query."""

    def __init__(self, con, fid: int, answers) -> None:
        self.con = con
        self.id = fid
        self.answers = answers  # whether a row's own document answers for what is inside it
        self._edges: dict[str, list[tuple]] = {}
        self._refs: dict[str, tuple[int | None, str | None]] = {}

    def edges(self, child_key: str) -> list[tuple]:
        """(parent key, parent configuration, child configuration, instances,
        unsuppressed, in BOM) of every edge to ``child_key``."""
        got = self._edges.get(child_key)
        if got is None:
            got = self._edges[child_key] = self.con.execute(
                "SELECT parent_key, parent_configuration, child_configuration, instances, unsuppressed, "
                "in_bom FROM edges WHERE file = ? AND child_key = ?",
                (self.id, child_key),
            ).fetchall()
        return got

    def ref(self, key: str) -> tuple[int | None, str | None]:
        """The reference ``key``'s target row and stored file name."""
        got = self._refs.get(key)
        if got is None:
            row = self.con.execute(
                "SELECT target, file_name FROM refs WHERE file = ? AND key = ?", (self.id, key)
            ).fetchone()
            got = self._refs[key] = (row[0], row[1]) if row else (None, None)
        return got

    def top(self, key: str) -> list[tuple]:
        return [(pc, cc, i, u, b) for pk, pc, cc, i, u, b in self.edges(key) if pk is None]

    def stored_chains(
        self, key: str, uses: list[tuple] | None, active: str | None, budget: _Budget
    ) -> list[tuple[list[str], list[tuple]]]:
        """What this document's own tree says about ``key`` inside sub-assemblies whose own
        document cannot answer (one that resolves to no file of the catalog, or to a file
        not read, unreadable, cut for size or with no component tree): (the sub-assembly
        keys from the top down, uses of this document). Every step is spent from
        ``budget``, so a tree built to branch at every level stops at its bound."""
        out: list[tuple[list[str], list[tuple]]] = []

        def climb(k: str, u: list[tuple] | None, chain: list[str], depth: int) -> None:
            if depth > DEFAULT_MAX_DEPTH:
                return
            budget.spend()
            by_parent: dict[str, list[tuple]] = {}
            for pk, pc, cc, i, un, b in self.edges(k):
                if pk is not None and pk not in chain and not self.answers(self.ref(pk)[0]):
                    by_parent.setdefault(pk, []).append((pc, cc, i, un, b))
            for parent, edges in by_parent.items():
                up = _compose(edges, u, active if u is not None and not chain else None)
                budget.spend(len(up))
                if not up:
                    continue
                top = self.top(parent)
                if top:
                    found = _compose(top, up, None)
                    budget.spend(len(found))
                    if found:
                        if len(out) >= MAX_USERS:
                            raise _Exhausted
                        out.append(([parent, *chain], found))
                climb(parent, up, [parent, *chain], depth + 1)

        try:
            climb(key, uses, [], 0)
        except _Exhausted:  # what was found so far is kept; the caller stops after it
            budget.exhausted = True
        return out


def where_used(
    con,
    root: str,
    path: str,
    *,
    configuration: str | None = None,
    indirect: bool = True,
    max_depth: int = DEFAULT_MAX_DEPTH,
    deadline: float | None = None,
) -> dict[str, Any]:
    """``where_used`` data for the file at ``path`` below root ``root``. ``deadline`` (a
    ``time.monotonic()`` value) stops the walk up with ``TimeoutError`` once it passes."""
    if (
        isinstance(max_depth, bool)
        or not isinstance(max_depth, int)
        or not 1 <= max_depth <= DEFAULT_MAX_DEPTH
    ):
        raise InvalidArgumentError(
            f"max_depth is 1 to {DEFAULT_MAX_DEPTH}", detail={"parameter": "max_depth"}
        )
    if configuration is not None and (not isinstance(configuration, str) or not configuration):
        raise InvalidArgumentError("a configuration name is text", detail={"parameter": "configuration"})
    with _Snapshot(con):
        target_id = find_file(con, root, path)
        files = _Files(con)
        t = files.get(target_id)
        configs = [
            n
            for (n,) in con.execute(
                "SELECT name FROM configurations WHERE file = ? ORDER BY position", (target_id,)
            )
        ]
        if configuration is not None and configs:
            match = [c for c in configs if c == configuration] or [
                c for c in configs if _fold_eq(c, configuration)
            ]
            if not match:
                raise ConfigurationNotFoundError("the file has no configuration by that name")
            configuration = match[0]
        docs: dict[int, _Doc] = {}
        answering: dict[int, bool] = {}

        def answers(fid: int | None) -> bool:
            """Whether the row ``fid`` holds a document that answers for what is inside it."""
            if fid is None:
                return False
            got = answering.get(fid)
            if got is None:
                row = con.execute(
                    "SELECT f.state, d.references_state FROM files f LEFT JOIN documents d ON d.file = f.id "
                    "WHERE f.id = ?",
                    (fid,),
                ).fetchone()
                got = answering[fid] = bool(
                    row and row[0] == "ok" and row[1] not in (None, "truncated", "unknown")
                )
            return got

        def doc(fid: int) -> _Doc:
            d = docs.get(fid)
            if d is None:
                d = docs[fid] = _Doc(con, fid, answers)
            return d

        users: list[dict[str, Any]] = []
        drawn: set[tuple[int, int]] = set()  # (drawing, the model it shows): listed once
        warnings: set[str] = set()
        truncated = False
        budget = _Budget(deadline)

        def add(e: dict[str, Any]) -> None:
            if len(users) >= MAX_USERS:
                raise _Exhausted
            users.append(e)

        def ref_meta(row) -> tuple[dict[str, Any], list[str]]:
            key, status, rule, confidence, identity, codes = row
            notes = _codes(codes)
            if confidence == "low":
                notes.append("low_confidence")
            return {
                "key": key,
                "status": status,
                "rule": rule,
                "confidence": confidence,
                "identity": identity,
            }, notes

        def entry(
            fid: int, relation: str, depth: int, via: list[dict[str, Any]], **kw: Any
        ) -> dict[str, Any]:
            f = files.get(fid)
            return {
                "root": f["root"],
                "path": f["path"],
                "name": f["name"],
                "doc_type": f["doc_type"],
                "format": f["format"],
                "depth": depth,
                "relation": relation,
                "via": via,
                "uses": kw.get("uses", []),
                "views": kw.get("views", []),
                "resolution": kw.get("resolution"),
                "warnings": [_warning(c) for c in sorted(set(kw.get("notes", [])))],
            }

        def via_item(fid: int) -> dict[str, Any]:
            f = files.get(fid)
            return {"root": f["root"], "path": f["path"], "name": f["name"], "stored": False}

        def stored_item(d: _Doc, key: str) -> dict[str, Any]:
            """A sub-assembly on a chain from a document's own tree: by its stored file name,
            or by the catalog's file when it resolves to one that could not answer."""
            target, file_name = d.ref(key)
            if target is not None:
                f = files.get(target)
                return {"root": f["root"], "path": f["path"], "name": f["name"], "stored": True}
            return {"root": None, "path": None, "name": file_name or key, "stored": True}

        def views_of(user: int, key: str, allowed: set[str] | None) -> list[dict[str, Any]]:
            out = []
            for sheet, view, cfg in con.execute(
                "SELECT sheet, view, configuration FROM views WHERE file = ? AND key = ? ORDER BY position",
                (user, key),
            ):
                if allowed is not None and cfg is not None and cfg.casefold() not in allowed:
                    continue
                out.append({"sheet": sheet, "view": view, "configuration": cfg})
            return out

        # frontier: (file id, its uses of the target or None for the target, its via chain, files on the path)
        frontier: list[tuple[int, list[tuple] | None, list[dict[str, Any]], frozenset]] = [
            (target_id, None, [], frozenset((target_id,)))
        ]
        depth = 0
        try:
            while frontier and depth < max_depth:
                depth += 1
                nxt = []
                for x, uses_x, chain, on_path in frontier:
                    x_active = files.get(x)["active"]
                    allowed = None
                    if configuration is not None:
                        allowed = (
                            {configuration.casefold()}
                            if uses_x is None
                            else {(u[0] or "").casefold() for u in uses_x}
                        )
                    for y, key, direct, status, rule, confidence, identity, codes in con.execute(
                        "SELECT file, key, direct, status, rule, confidence, identity, warnings FROM refs "
                        "WHERE target = ? AND status IN ('resolved', 'moved') ORDER BY file, key",
                        (x,),
                    ).fetchall():
                        budget.spend()
                        if y in on_path:
                            warnings.add("cycle")
                            continue
                        resolution, notes = ref_meta((key, status, rule, confidence, identity, codes))
                        y_type = files.get(y)["doc_type"]
                        if y_type == "drawing":
                            if (y, x) in drawn:
                                continue
                            drawn.add((y, x))
                            views = views_of(y, key, allowed)
                            if allowed is not None and not views:
                                continue
                            relation = "drawing_view" if uses_x is None else "drawing_of_assembly"
                            add(
                                entry(
                                    y, relation, depth, chain, views=views, resolution=resolution, notes=notes
                                )
                            )
                            continue
                        d = doc(y)
                        top = d.top(key)
                        if top:
                            uses_y = _compose(top, uses_x, x_active)
                            budget.spend(len(uses_y))
                            if uses_x is None and configuration is not None:
                                uses_y = [u for u in uses_y if _fold_eq(u[1], configuration)]
                            if uses_y:
                                add(
                                    entry(
                                        y,
                                        "component",
                                        depth,
                                        chain,
                                        uses=_uses_data(uses_y),
                                        resolution=resolution,
                                        notes=notes,
                                    )
                                )
                                if indirect:
                                    nxt.append((y, uses_y, [via_item(y), *chain], on_path | {y}))
                        elif direct is None and not d.edges(key):
                            # an assembly with no component tree names its files in its header
                            # alone: it uses the file, but how many and in which configuration is
                            # not stored, and nothing above it can be counted through it
                            add(
                                entry(
                                    y,
                                    "component",
                                    depth,
                                    chain,
                                    resolution=resolution,
                                    notes=[*notes, "quantity_unknown"],
                                )
                            )
                        for keys, uses_y in d.stored_chains(key, uses_x, x_active, budget):
                            if uses_x is None and configuration is not None:
                                uses_y = [u for u in uses_y if _fold_eq(u[1], configuration)]
                            if not uses_y:
                                continue
                            stored = [stored_item(d, k) for k in keys]
                            add(
                                entry(
                                    y,
                                    "stored_tree",
                                    depth + len(keys),
                                    [*stored, *chain],
                                    uses=_uses_data(uses_y),
                                    resolution=resolution,
                                    notes=[*notes, "from_parent_tree"],
                                )
                            )
                            if indirect:
                                nxt.append((y, uses_y, [via_item(y), *stored, *chain], on_path | {y}))
                        if budget.exhausted:
                            raise _Exhausted
                frontier = nxt
                if not indirect:
                    break
        except _Exhausted:
            truncated = True
        if frontier and depth >= max_depth and indirect and not truncated:
            # the depth bound stopped the walk up: truncated only if something was left above
            ids = [x for x, *_rest in frontier]
            for i in range(0, len(ids), 500):
                chunk = ids[i : i + 500]
                marks = ",".join("?" * len(chunk))
                if con.execute(
                    f"SELECT EXISTS (SELECT 1 FROM refs WHERE target IN ({marks}) AND status IN "
                    "('resolved', 'moved'))",
                    chunk,
                ).fetchone()[0]:
                    truncated = True
                    break
        if con.execute(_UNREAD_USERS).fetchone()[0]:
            warnings.add("unread_documents")

        possible = []
        seen_refs: set[tuple[int, str]] = set()
        for user, key, file_name, stored_path, status in con.execute(
            "SELECT rc.file, rc.key, r.file_name, r.stored_path, r.status FROM ref_candidates rc JOIN refs r "
            "ON r.file = rc.file AND r.key = rc.key WHERE rc.candidate = ? AND r.status = 'ambiguous' ORDER "
            "BY rc.file, rc.key",
            (target_id,),
        ).fetchall():
            seen_refs.add((user, key))
            f = files.get(user)
            others = [
                {"root": files.get(c)["root"], "path": files.get(c)["path"]}
                for (c,) in con.execute(
                    "SELECT candidate FROM ref_candidates WHERE file = ? AND key = ? AND candidate <> ?",
                    (user, key, target_id),
                )
            ]
            possible.append(
                {
                    "root": f["root"],
                    "path": f["path"],
                    "name": f["name"],
                    "doc_type": f["doc_type"],
                    "format": f["format"],
                    "key": key,
                    "file_name": file_name,
                    "stored_path": stored_path,
                    "status": status,
                    "candidates": others,
                }
            )
        name_matches = []
        for user, key, file_name, stored_path, status in con.execute(
            "SELECT file, key, file_name, stored_path, status FROM refs WHERE name_fold = ? "
            "AND status IN ('missing', 'ambiguous') ORDER BY file, key",
            (fold(t["name"]),),
        ).fetchall():
            if (user, key) in seen_refs or user == target_id:
                continue
            f = files.get(user)
            name_matches.append(
                {
                    "root": f["root"],
                    "path": f["path"],
                    "name": f["name"],
                    "doc_type": f["doc_type"],
                    "format": f["format"],
                    "key": key,
                    "file_name": file_name,
                    "stored_path": stored_path,
                    "status": status,
                }
            )
        root_row = con.execute(
            "SELECT r.last_complete_scan FROM files f JOIN roots r ON r.id = f.root WHERE f.id = ?",
            (target_id,),
        ).fetchone()
        users.sort(
            key=lambda u: (u["depth"], RELATIONS.index(u["relation"]), u["root"] or "", u["path"] or "")
        )
        data = {
            "target": {
                "root": t["root"],
                "path": t["path"],
                "name": t["name"],
                "doc_type": t["doc_type"],
                "format": t["format"],
                "state": t["state"],
                "configurations": configs,
                "sha256": t["sha256"],
            },
            "configuration": configuration,
            "indirect": bool(indirect),
            "as_of": _scan_time(con, root_row[0] if root_row else None),
            "complete": complete(con),
            "users": users,
            "possible": possible,
            "name_matches": name_matches,
            "counts": {
                "users": len({(u["root"], u["path"]) for u in users}),
                "direct": sum(1 for u in users if u["depth"] == 1 and u["relation"] == "component"),
                "indirect": sum(
                    1 for u in users if u["depth"] > 1 and u["relation"] in ("component", "stored_tree")
                ),
                "drawings": len(
                    {
                        (u["root"], u["path"])
                        for u in users
                        if u["relation"] in ("drawing_view", "drawing_of_assembly")
                    }
                ),
                "possible": len(possible),
                "name_matches": len(name_matches),
            },
            "truncated": truncated,
            "warnings": [_warning(c) for c in sorted(warnings)],
        }
    return model.to_json_data(data)


# --------------------------------------------------------------------------- search
def _terms(text: str) -> tuple[list[str], dict[str, list[str]]]:
    """Free words and phrases, and the filters, of a search text."""
    if not isinstance(text, str) or len(text) > 1000:
        raise InvalidArgumentError(
            "the search text is at most 1,000 characters", detail={"parameter": "text"}
        )
    if _CONTROL.search(text):
        raise InvalidArgumentError("the search text holds a control character", detail={"parameter": "text"})
    words: list[str] = []
    filters: dict[str, list[str]] = {}
    i, n = 0, len(text)
    while i < n:
        if text[i].isspace():
            i += 1
            continue
        start = i
        token = []
        while i < n and not text[i].isspace():
            if text[i] == '"':
                j = text.find('"', i + 1)
                j = n if j < 0 else j
                token.append(text[i + 1 : j])
                i = j + 1
            else:
                token.append(text[i])
                i += 1
        raw = "".join(token)
        head, sep, rest = raw.partition(":")
        if sep and head.lower() in FILTERS and text[start] != '"':
            filters.setdefault(head.lower(), []).append(rest)
        elif raw.strip():
            words.append(raw.strip())
    return words, filters


def _fts_query(words: list[str]) -> str:
    return " ".join('"' + w.replace('"', '""') + '"*' for w in words)


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _since(value: str, parameter: str = "text") -> int:
    """``value`` (``7d``, ``12h``, ``2w`` or a date) as nanoseconds since 1970. A bad one is
    ``invalid_argument`` naming ``parameter``: the search text's ``changed:`` filter, or
    ``since`` of :func:`changes`."""
    what = "changed:" if parameter == "text" else parameter
    if not isinstance(value, str):
        raise InvalidArgumentError(f"{what} takes 7d, 12h, 2w or a date", detail={"parameter": parameter})
    m = _SPAN.match(value)
    now = datetime.datetime.now(datetime.UTC)
    if m:
        span = {
            "h": datetime.timedelta(hours=1),
            "d": datetime.timedelta(days=1),
            "w": datetime.timedelta(weeks=1),
        }
        when = now - int(m.group(1)) * span[m.group(2)]
    elif _DATE.match(value):
        try:
            when = datetime.datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=datetime.UTC)
        except ValueError:
            raise InvalidArgumentError(
                f"{what} takes 7d, 12h, 2w or a date", detail={"parameter": parameter}
            ) from None
    else:
        raise InvalidArgumentError(f"{what} takes 7d, 12h, 2w or a date", detail={"parameter": parameter})
    return max(-(2**63), min(2**63 - 1, int(when.timestamp()) * 1_000_000_000))


def search(
    con,
    text: str,
    *,
    fts5: bool,
    sort: str = "relevance",
    limit: int = 100,
    cursor: str | None = None,
) -> dict[str, Any]:
    """``catalog_search`` data (see ``docs/API.md`` 3.18 for the query text)."""
    if sort not in SORTS:
        raise InvalidArgumentError(f"sort is one of {', '.join(SORTS)}", detail={"parameter": "sort"})
    limit = _limit(limit)
    words, filters = _terms(text)
    words = [w for w in words if re.search(r"\w", w)]  # punctuation alone matches nothing
    qkey = _key(text, sort)
    offset = _offset(cursor, qkey)
    where: list[str] = []
    args: list[Any] = []
    engine = "fts5" if fts5 else "like"
    joins = "FROM files f JOIN roots ro ON ro.id = f.root LEFT JOIN documents d ON d.file = f.id"
    ranked = False
    if words and fts5:
        joins = (
            "FROM search JOIN files f ON f.id = search.rowid JOIN roots ro ON ro.id = f.root "
            "LEFT JOIN documents d ON d.file = f.id"
        )
        where.append("search MATCH ?")
        args.append(_fts_query(words))
        ranked = True
    elif words:
        for w in words:
            pat = _like(w)
            where.append(
                "(f.name LIKE ? ESCAPE '\\' OR f.rel LIKE ? ESCAPE '\\' OR f.id IN (SELECT file FROM "
                "configurations WHERE part_number LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\' OR "
                "name LIKE ? ESCAPE '\\') OR f.id IN (SELECT file FROM properties WHERE text LIKE ? ESCAPE "
                "'\\' OR name LIKE ? ESCAPE '\\'))"
            )
            args += [pat] * 7
    for value in filters.get("type", []):
        t = TYPE_WORDS.get(value.lower())
        if t is None:
            raise InvalidArgumentError("type: is part, assembly or drawing", detail={"parameter": "text"})
        exts = TYPE_EXTENSIONS[t]
        where.append(f"(d.doc_type = ? OR (d.doc_type IS NULL AND f.ext IN ({','.join('?' * len(exts))})))")
        args += [t, *exts]
    for value in filters.get("format", []):
        fid = value.lower()
        if fid not in registry.FORMATS:
            raise InvalidArgumentError(
                f"format: takes a format id: {', '.join(sorted(registry.FORMATS))}",
                detail={"parameter": "text"},
            )
        stored = ["modern", "ole"] if fid == registry.SOLIDWORKS else [fid]
        exts = registry.FORMATS[fid].extensions
        where.append(
            f"(d.format IN ({','.join('?' * len(stored))}) OR (d.format IS NULL AND f.ext IN "
            f"({','.join('?' * len(exts))})))"
        )
        args += [*stored, *exts]
    for value in filters.get("root", []):
        where.append("ro.root_id = ?")
        args.append(value)
    for value in filters.get("folder", []):
        folder = value.replace("\\", "/").strip("/")
        where.append("(f.rel LIKE ? ESCAPE '\\')")
        args.append(folder.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "/%")
    for value in filters.get("pn", []):
        where.append("f.id IN (SELECT file FROM configurations WHERE part_number LIKE ? ESCAPE '\\')")
        args.append(_like(value))
    for value in filters.get("desc", []):
        where.append("f.id IN (SELECT file FROM configurations WHERE description LIKE ? ESCAPE '\\')")
        args.append(_like(value))
    for value in filters.get("prop", []):
        name, eq, val = value.partition("=")
        if not name:
            raise InvalidArgumentError("prop: takes Name or Name=value", detail={"parameter": "text"})
        if eq:
            where.append(
                "f.id IN (SELECT file FROM properties WHERE name_fold = ? AND text = ? COLLATE NOCASE)"
            )
            args += [fold(name), val]
        else:
            where.append("f.id IN (SELECT file FROM properties WHERE name_fold = ?)")
            args.append(fold(name))
    for value in filters.get("changed", []):
        where.append("f.mtime_ns >= ?")
        args.append(_since(value))
    if not words and not filters:
        raise InvalidArgumentError("give words to search for, or a filter", detail={"parameter": "text"})
    if sort == "relevance" and ranked:
        order = "search.rank, f.name_fold, f.rel"
    elif sort == "modified":
        order = "f.mtime_ns DESC, f.rel"
    else:
        order = "f.name_fold, f.rel"
    sql = (
        "SELECT f.id, ro.root_id, f.rel, f.name, d.doc_type, f.mtime_ns, f.size, f.state, "
        "d.active_configuration, d.format "
        f"{joins} WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ? OFFSET ?"
    )
    with _Snapshot(con):
        rows = con.execute(sql, [*args, limit + 1, offset]).fetchall()
        more = len(rows) > limit
        results = []
        lowered = [w.casefold() for w in words]
        for fid, root_id, rel, name, doc_type, mtime, size, state, active, fmt in rows[:limit]:
            cfg = con.execute(
                "SELECT name, part_number, description FROM configurations WHERE file = ? "
                "ORDER BY (name = ?) DESC, active DESC, position LIMIT 1",
                (fid, active or ""),
            ).fetchone()
            matched = []
            if lowered:
                hay = {
                    "name": name.casefold(),
                    "folder": rel.rpartition("/")[0].casefold(),
                    "numbers": " ".join(
                        f"{p or ''} {d or ''}"
                        for p, d in con.execute(
                            "SELECT part_number, description FROM configurations WHERE file = ?", (fid,)
                        )
                    ).casefold(),
                    "configurations": " ".join(
                        n for (n,) in con.execute("SELECT name FROM configurations WHERE file = ?", (fid,))
                    ).casefold(),
                    "properties": " ".join(
                        f"{n} {v or ''}"
                        for n, v in con.execute("SELECT name, text FROM properties WHERE file = ?", (fid,))
                    ).casefold(),
                }
                for field_name, value in hay.items():
                    if any(_word_in(w, value) for w in lowered):
                        matched.append(field_name)
            for f in ("pn", "desc", "prop", "type", "format", "root", "folder", "changed"):
                if f in filters:
                    matched.append(f + ":")
            results.append(
                {
                    "root": root_id,
                    "path": rel,
                    "name": name,
                    "doc_type": doc_type or _type_of(name),
                    "format": file_format(fmt, name),
                    "modified_utc": _modified(mtime),
                    "size": size,
                    "state": state,
                    "configuration": cfg[0] if cfg else None,
                    "part_number": cfg[1] if cfg else None,
                    "description": cfg[2] if cfg else None,
                    "matched": matched,
                }
            )
    data = {
        "query": text,
        "engine": engine,
        "sort": sort,
        "results": results,
        "next_cursor": _cursor(offset + limit, qkey) if more else None,
        "truncated": more,
    }
    return model.to_json_data(data)


def _word_in(word: str, text: str) -> bool:
    """Whether every token of ``word`` starts a token of ``text`` (FTS5's prefix match,
    roughly: what the ``matched`` fields report)."""
    tokens = re.findall(r"\w+", text)
    parts = re.findall(r"\w+", word)
    return bool(parts) and all(any(tok.startswith(p) for tok in tokens) for p in parts)


# --------------------------------------------------------------------------- duplicates
def duplicates(
    con, *, names: bool = False, limit: int = MAX_LIMIT, cursor: str | None = None
) -> dict[str, Any]:
    """``duplicates`` data: groups of files with one SHA-256 (and with ``names``, groups
    of files that share a folded name but differ in content). Both lists are paged
    together: a page holds up to ``limit`` of each, and ``next_cursor`` continues while
    either has more."""
    limit = _limit(limit)
    qkey = _key("duplicates", names)
    offset = _offset(cursor, qkey)
    with _Snapshot(con):
        rows = con.execute(
            "SELECT sha256, count(*), max(size) FROM files WHERE sha256 IS NOT NULL GROUP BY sha256 "
            "HAVING count(*) > 1 ORDER BY max(size) * (count(*) - 1) DESC, sha256 LIMIT ? OFFSET ?",
            (limit + 1, offset),
        ).fetchall()
        more = len(rows) > limit
        groups = []
        for sha, n, size in rows[:limit]:
            members = [
                {"root": r, "path": p, "name": nm, "modified_utc": _modified(m)}
                for r, p, nm, m in con.execute(
                    "SELECT ro.root_id, f.rel, f.name, f.mtime_ns FROM files f JOIN roots ro ON ro.id = "
                    "f.root WHERE f.sha256 = ? ORDER BY ro.position, f.rel",
                    (sha,),
                )
            ]
            groups.append(
                {"sha256": sha, "size": size, "wasted_bytes": (size or 0) * (n - 1), "files": members}
            )
        totals = con.execute(
            "SELECT count(*), coalesce(sum(n), 0), coalesce(sum(s * (n - 1)), 0) FROM (SELECT count(*) AS n, "
            "max(size) AS s FROM files WHERE sha256 IS NOT NULL GROUP BY sha256 HAVING count(*) > 1)"
        ).fetchone()
        name_groups = None
        name_total = None
        if names:
            name_groups = []
            same_name = (
                "FROM files GROUP BY name_fold HAVING count(*) > 1 AND "
                "count(DISTINCT coalesce(sha256, 'size:' || size)) > 1"
            )
            name_total = con.execute(f"SELECT count(*) FROM (SELECT name_fold {same_name})").fetchone()[0]
            name_rows = con.execute(
                "SELECT name_fold, count(DISTINCT coalesce(sha256, 'size:' || size)) "
                f"{same_name} ORDER BY name_fold LIMIT ? OFFSET ?",
                (limit + 1, offset),
            ).fetchall()
            more = more or len(name_rows) > limit
            for name_fold, n in name_rows[:limit]:
                members = [
                    {"root": r, "path": p, "name": nm, "modified_utc": _modified(m), "sha256": sh, "size": sz}
                    for r, p, nm, m, sh, sz in con.execute(
                        "SELECT ro.root_id, f.rel, f.name, f.mtime_ns, f.sha256, f.size FROM files f "
                        "JOIN roots ro ON ro.id = f.root WHERE f.name_fold = ? ORDER BY ro.position, f.rel",
                        (name_fold,),
                    )
                ]
                name_groups.append({"name": members[0]["name"], "versions": n, "files": members})
        pending = hash_pending(con)
    data = {
        "groups": groups,
        "name_groups": name_groups,
        "counts": {
            "groups": totals[0],
            "files": totals[1],
            "wasted_bytes": totals[2],
            "name_groups": name_total,
        },
        "hash_pending": pending,
        "next_cursor": _cursor(offset + limit, qkey) if more else None,
    }
    return model.to_json_data(data)


# --------------------------------------------------------------------------- missing references
def missing_references(con, *, limit: int = MAX_LIMIT, cursor: str | None = None) -> dict[str, Any]:
    """``missing_references`` data: per referencing document, every reference that is
    missing, ambiguous or embedded but not found, and every low-confidence result, within
    the catalog's roots."""
    limit = _limit(limit)
    qkey = _key("missing")
    offset = _offset(cursor, qkey)
    cond = "(r.status IN ('missing', 'ambiguous', 'embedded_not_found') OR r.confidence = 'low')"
    with _Snapshot(con):
        files = _Files(con)
        docs = con.execute(
            "SELECT r.file FROM refs r JOIN files f ON f.id = r.file JOIN roots ro ON ro.id = f.root WHERE "
            f"{cond} "
            "GROUP BY r.file ORDER BY min(ro.position), min(f.rel) LIMIT ? OFFSET ?",
            (limit + 1, offset),
        ).fetchall()
        more = len(docs) > limit
        out = []
        for (fid,) in docs[:limit]:
            f = files.get(fid)
            refs = []
            for (
                key,
                file_name,
                stored_path,
                status,
                rule,
                confidence,
                identity,
                codes,
                name_fold,
            ) in con.execute(
                "SELECT r.key, r.file_name, r.stored_path, r.status, r.rule, r.confidence, r.identity, "
                "r.warnings, "
                f"r.name_fold FROM refs r WHERE r.file = ? AND {cond} ORDER BY r.position",
                (fid,),
            ):
                cands = [
                    {
                        "root": files.get(c)["root"],
                        "path": files.get(c)["path"],
                        "found_by": fb,
                        "identity": idn,
                    }
                    for c, fb, idn in con.execute(
                        "SELECT candidate, found_by, identity FROM ref_candidates WHERE file = ? AND key = ?",
                        (fid, key),
                    )
                ]
                same = (
                    con.execute("SELECT count(*) FROM files WHERE name_fold = ?", (name_fold,)).fetchone()[0]
                    if name_fold
                    else 0
                )
                notes = _codes(codes)
                refs.append(
                    {
                        "key": key,
                        "file_name": file_name,
                        "stored_path": stored_path,
                        "status": status,
                        "rule": rule,
                        "confidence": confidence,
                        "identity": identity,
                        "candidates": cands,
                        "name_matches": same,
                        "warnings": [_warning(c) for c in notes],
                    }
                )
            out.append(
                {
                    "root": f["root"],
                    "path": f["path"],
                    "name": f["name"],
                    "doc_type": f["doc_type"],
                    "format": f["format"],
                    "references": refs,
                }
            )
        by_status = dict(
            con.execute(
                "SELECT status, count(*) FROM refs WHERE status IN ('missing', 'ambiguous', "
                "'embedded_not_found') GROUP BY status"
            ).fetchall()
        )
        low = con.execute("SELECT count(*) FROM refs WHERE confidence = 'low'").fetchone()[0]
        documents = con.execute(f"SELECT count(DISTINCT r.file) FROM refs r WHERE {cond}").fetchone()[0]
    data = {
        "documents": out,
        "counts": {
            "documents": documents,
            "missing": by_status.get("missing", 0),
            "ambiguous": by_status.get("ambiguous", 0),
            "embedded_not_found": by_status.get("embedded_not_found", 0),
            "low_confidence": low,
        },
        "within_roots": True,
        "next_cursor": _cursor(offset + limit, qkey) if more else None,
    }
    return model.to_json_data(data)


# --------------------------------------------------------------------------- changes
EVENT_KINDS = ("added", "changed", "moved", "removed", "read_error")


def changes(
    con, *, since: str | None = None, limit: int = MAX_LIMIT, cursor: str | None = None
) -> dict[str, Any]:
    """``catalog_changes`` data: the newest events first, since ``since`` (``7d``, ``12h``,
    ``2w`` or a date) when given."""
    limit = _limit(limit)
    qkey = _key("changes", since)
    offset = _offset(cursor, qkey)
    args: list[Any] = []
    where = ""
    if since is not None:
        ns = _since(since, "since")
        when = datetime.datetime.fromtimestamp(ns / 1e9, datetime.UTC).replace(microsecond=0)
        where = "WHERE time_utc >= ?"
        args.append(model.iso8601(when))
    with _Snapshot(con):
        rows = con.execute(
            "SELECT time_utc, scan, kind, root, rel, previous_root, previous_rel, size, sha256, "
            "previous_sha256 "
            f"FROM events {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            (*args, limit + 1, offset),
        ).fetchall()
    more = len(rows) > limit
    events = [
        {
            "time_utc": r[0],
            "scan": r[1],
            "kind": r[2],
            "root": r[3],
            "path": r[4],
            "previous_root": r[5],
            "previous_path": r[6],
            "size": r[7],
            "sha256": r[8],
            "previous_sha256": r[9],
        }
        for r in rows[:limit]
    ]
    data = {"since": since, "events": events, "next_cursor": _cursor(offset + limit, qkey) if more else None}
    return model.to_json_data(data)


# --------------------------------------------------------------------------- previews
def preview(con, root: str, path: str) -> tuple[str, bytes] | None:
    """The stored preview image of a file, (mime, bytes), or None."""
    with _Snapshot(con):
        fid = find_file(con, root, path)
        row = con.execute(
            "SELECT p.mime, p.data FROM documents d JOIN pv.previews p ON p.sha256 = d.preview_sha256 WHERE "
            "d.file = ?",
            (fid,),
        ).fetchone()
    return (row[0], bytes(row[1])) if row else None


__all__ = [
    "EVENT_KINDS",
    "FILTERS",
    "RELATIONS",
    "SORTS",
    "changes",
    "complete",
    "counts",
    "duplicates",
    "find_file",
    "missing_references",
    "preview",
    "search",
    "status",
    "where_used",
]
