"""Which file on this machine each reference of a document names.

A document stores, for each file it references, the absolute path the file had
when the document was last saved, and the file's creation time. Folders get
moved, copied, synced and renamed, so the stored path is often wrong. This
module finds the file the way SOLIDWORKS' own search routine does, kept inside
the caller's roots, and checks every answer against the stored creation time.

**Rules, in order** (``docs/API.md`` section 3.10 has the evidence):

0. ``embedded``: a virtual component, or an imported one whose nested
   document exists, is stored inside the document: status ``embedded``,
   ``embedded_not_found`` or ``embedded_in_subassembly``. Never looked up on
   disk, even when a file of that name exists.
1. ``stored_unmoved``: the document is where it was saved (its folder equals
   ``SW-Folder Name``) and the stored path exists.
2. ``path_map``: the first path mapping whose prefix matches the stored path.
3. ``rebased``: the stored path taken relative to the folder at save, from
   where the document is now.
4. ``same_folder``: the name in the document's folder.
5. ``suffix_probe``: SOLIDWORKS' folder-suffix probe, from the document's
   folder up to the root that holds it and never above it: for each ancestor,
   the name under the stored folder's last 0, 1, 2... components.
6. ``stored_path``: the stored path, for a document that has moved.
7. ``name_index``: the name anywhere under each root, in root order. Candidates
   whose identity differs are dropped, and identity matches are preferred. One
   left: chosen. Several: the one with the unique highest folder-suffix score
   against the stored folder, when that score is above 0
   (``name_index_suffix``); otherwise ``ambiguous``.
8. If a rule found a file whose identity differs and nothing better was found,
   that file is returned with low confidence and the warning
   ``identity_mismatch``; otherwise the reference is ``missing``.

A hit at rules 1 to 6 whose identity differs is remembered and skipped. No
rule uses version or update stamps (they decided 4 of 3,225 direct references
in measurement, and disagreed with the ground truth too often).

**Work happens in three steps** (C10): the candidates of every reference are
collected from the folder indexes and point lookups, their identities are
read in one batch, and then the rules decide; the name index is consulted
the same way, for the references still undecided. All filesystem access goes
through :class:`.gateway.Gateway`.

What the rules need from the document itself (each referenced file's stored
path and creation time, the folder at save, the embedded documents'
identities) is read first into a :class:`ResolutionInput`. The REST service
reads it in a worker process, as JSON, and resolves in its own process, which
never opens a CAD file; the library and the CLI read it from the open
document.

Phase 1 resolves the top document's own tree in the top document's context
(C7): files inside sub-assemblies are resolved from the paths the top document
stored (warning ``from_parent_tree``), and a file used by more than one parent
document carries ``context_varies``.
"""

import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from ..errors import InvalidArgumentError, ReaderWarning
from ..roots import Root, Roots
from .gateway import Gateway, PointHit, within_of
from .identity import Identity, compare, own_identity, parse_creation_time
from .index import FolderIndex, IndexedFile
from .names import (
    HOST_WINDOWS,
    HostPath,
    PathMapping,
    StoredFolder,
    StoredPath,
    fold,
    from_stored,
    parse_path_map,
    parse_stored,
    parse_stored_folder,
    suffix_score,
)

MAX_REFERENCES = 100_000
DEFAULT_MAX_EXAMINED = 250_000
DEFAULT_MAX_SECONDS = 15.0
DEFAULT_MAX_CANDIDATES = 20
DEFAULT_MAX_IDENTITY_READS = 5_000
DOCUMENT_ROOT_ID = "document"

POSITIONAL_RULES = ("stored_unmoved", "path_map", "rebased", "same_folder", "suffix_probe", "stored_path")
RULES = ("embedded", *POSITIONAL_RULES, "name_index", "name_index_suffix")
STATUSES = (
    "resolved",
    "moved",
    "embedded",
    "embedded_not_found",
    "embedded_in_subassembly",
    "ambiguous",
    "missing",
)
# Confidence by rule: (identity match, identity unknown). An identity that differs is
# always "low" (the fallback), and ambiguous and missing are "none". With an identity
# match, a rule is "high" when its pick agreed with the positional ground truth in at
# least 97% of the development corpus's tuning set, "medium" from 85% and "low" below
# (docs/API.md 3.10 has the numbers): stored_path 94.8%, name_index_suffix 77.0%,
# the others 99.7% or more. Without an identity there is no evidence either way, so
# the level drops to medium for the rules that follow stored paths and to low for the
# rest.
CONFIDENCE: dict[str, tuple[str, str]] = {
    "embedded": ("high", "medium"),
    "stored_unmoved": ("high", "medium"),
    "path_map": ("high", "medium"),
    "rebased": ("high", "medium"),
    "same_folder": ("high", "low"),
    "suffix_probe": ("high", "low"),
    "stored_path": ("medium", "low"),
    "name_index": ("high", "low"),
    "name_index_suffix": ("low", "low"),
}
_ALSO_EXISTS_RULES = ("rebased", "same_folder", "suffix_probe")


# --------------------------------------------------------------------------- results
@dataclass(frozen=True)
class Location:
    """Where a file is (C1): ``root`` is a root id and ``path`` relative to it,
    ``/``-separated, in the on-disk spelling; for a file outside every root (CLI and
    Python only) ``root`` is None and ``path`` the absolute host path. ``host_path``
    is the absolute host path in every case, for Python callers; it is never sent
    as JSON."""

    root: str | None
    path: str
    host_path: str = field(compare=False, repr=False)


@dataclass(frozen=True)
class Candidate:
    """Another file a rule looked at: where it is, which rule found it, its identity
    and whether it is a cloud placeholder (never opened)."""

    location: Location
    found_by: str
    identity: str
    placeholder: bool


@dataclass(frozen=True)
class ResolvedReference:
    """The answer for one referenced file, by its key (C7, C9)."""

    key: str
    status: str
    stored_path: str | None
    match: Location | None
    rule: str | None
    confidence: str
    identity: str
    nested: str | None
    candidates: tuple[Candidate, ...]
    warnings: tuple[ReaderWarning, ...]


@dataclass(frozen=True)
class RootState:
    id: str
    role: str
    recursive: bool
    index_partial: bool
    truncated_reason: str | None


@dataclass(frozen=True)
class Resolution:
    """Every referenced file of one document, resolved. ``results`` is keyed by file
    key, in the order of the ``references`` kind. ``index_partial`` is True when a
    limit cut a root's folder index short; ``truncated`` when the document has more
    than 100,000 referenced files and only the first were resolved."""

    results: dict[str, ResolvedReference]
    roots: tuple[RootState, ...]
    index_partial: bool
    allow_outside_roots: bool
    truncated: bool

    def counts(self) -> dict[str, int]:
        out = dict.fromkeys(STATUSES, 0)
        for r in self.results.values():
            out[r.status] = out.get(r.status, 0) + 1
        return out


@dataclass(frozen=True)
class InputFile:
    """What resolution needs to know about one referenced file, read from the document:
    its key, the path and creation time stored for it, whether the top document uses
    it directly, its embedded status and nested stream, how many parent documents use
    it, and for an embedded file the identity its nested document stores."""

    key: str
    stored_path: str | None
    direct: bool | None
    embedded: str | None
    nested: str | None
    stored_creation_time: int | None
    parent_documents: int
    nested_identity: Identity | None = None


@dataclass(frozen=True)
class ResolutionInput:
    """Everything the rules read from the document being resolved. ``path`` is the
    document's path on this machine (None for bytes), ``folder_at_save`` its
    ``SW-Folder Name`` as stored. :meth:`from_document` reads it from an open
    document; :meth:`to_json` and :meth:`from_json` carry it between processes."""

    path: str | None
    folder_at_save: str | None
    files: tuple[InputFile, ...]

    @classmethod
    def from_document(cls, doc) -> "ResolutionInput":
        md = doc.metadata
        tree = md.tree or {}
        tree_files = tree.get("files", {})
        h2_times = (md.header2 or {}).get("creation_times", {})
        models = tree.get("models", {})
        parents: dict[str, set] = {}
        for r in tree.get("refs", []):
            fid = models.get(r["model_ref"], {}).get("file_ref")
            if fid is None:
                continue
            parent = models.get(r["parent_model"], {}).get("file_ref")
            parents.setdefault(fid, set()).add("top" if parent in md.own_file_ids else parent)
        files = []
        for f in doc.reference_set().files.values():
            if f.key in tree_files:
                stored_ct = parse_creation_time(tree_files[f.key].get("creation_time"))
            else:
                stored_ct = parse_creation_time(h2_times.get(f.stored_path))
            nested_identity = None
            if f.embedded == "embedded" and f.nested:
                try:
                    nested_identity = own_identity(doc.nested(f.nested))
                except Exception as exc:  # a damaged nested document: say so, carry on
                    nested_identity = Identity(None, error=type(exc).__name__)
            files.append(
                InputFile(
                    key=f.key,
                    stored_path=f.stored_path,
                    direct=f.direct,
                    embedded=f.embedded,
                    nested=f.nested,
                    stored_creation_time=stored_ct,
                    parent_documents=len(parents.get(f.key, ())),
                    nested_identity=nested_identity,
                )
            )
        folder = md.summary.get("folder_at_save")
        return cls(doc.path, folder if isinstance(folder, str) else None, tuple(files))

    def to_json(self) -> dict:
        """JSON data for another process. ``path`` is left out: the receiver knows where
        the document is and sets it with :meth:`from_json`."""
        return {
            "folder_at_save": self.folder_at_save,
            "files": [
                {
                    "key": f.key,
                    "stored_path": f.stored_path,
                    "direct": f.direct,
                    "embedded": f.embedded,
                    "nested": f.nested,
                    "stored_creation_time": f.stored_creation_time,
                    "parent_documents": f.parent_documents,
                    "nested_identity": None
                    if f.nested_identity is None
                    else {
                        "creation_time": f.nested_identity.creation_time,
                        "source": f.nested_identity.source,
                        "error": f.nested_identity.error,
                    },
                }
                for f in self.files
            ],
        }

    @classmethod
    def from_json(cls, data, *, path: str | None) -> "ResolutionInput":
        """The input :meth:`to_json` produced, checked field by field: it comes from another
        process, so a value of the wrong type raises :class:`InvalidArgumentError`."""

        def bad(what: str) -> InvalidArgumentError:
            return InvalidArgumentError(f"resolution input: {what}", detail={"parameter": "resolution_input"})

        def text(v, what, *, limit=4096):
            if v is None:
                return None
            if not isinstance(v, str) or len(v) > limit:
                raise bad(what)
            return v

        if not isinstance(data, dict) or not isinstance(data.get("files"), list):
            raise bad("not an object with files")
        if len(data["files"]) > MAX_REFERENCES + 1:
            raise bad("too many files")
        files = []
        for item in data["files"]:
            if not isinstance(item, dict):
                raise bad("a file is not an object")
            key = text(item.get("key"), "key", limit=64)
            if key is None:
                raise bad("a file has no key")
            direct = item.get("direct")
            if direct is not None and not isinstance(direct, bool):
                raise bad("direct")
            count = item.get("parent_documents")
            if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= MAX_REFERENCES:
                raise bad("parent_documents")
            ident = item.get("nested_identity")
            nested_identity = None
            if ident is not None:
                if not isinstance(ident, dict):
                    raise bad("nested_identity")
                nested_identity = Identity(
                    parse_creation_time(ident.get("creation_time")),
                    text(ident.get("source"), "source", limit=32),
                    text(ident.get("error"), "error", limit=100),
                )
            files.append(
                InputFile(
                    key=key,
                    stored_path=text(item.get("stored_path"), "stored_path"),
                    direct=direct,
                    embedded=text(item.get("embedded"), "embedded", limit=64),
                    nested=text(item.get("nested"), "nested", limit=1024),
                    stored_creation_time=parse_creation_time(item.get("stored_creation_time")),
                    parent_documents=count,
                    nested_identity=nested_identity,
                )
            )
        return cls(path, text(data.get("folder_at_save"), "folder_at_save"), tuple(files))


class IndexCache:
    """Folder indexes and file identities kept between resolution calls, for a batch
    over many documents. An index is a snapshot of its root when it was built: make
    a new cache to see later changes. Identities are keyed by path, size and
    modification time, so a changed file is read again."""

    def __init__(self) -> None:
        self.indexes: dict[tuple[str, bool], FolderIndex] = {}
        self.identities: dict[tuple, Identity] = {}


# --------------------------------------------------------------------------- internals
@dataclass
class _Hit:
    host: HostPath
    path: str
    location: Location
    found_by: str
    name: str
    size: int | None
    mtime_ns: int | None
    placeholder: bool
    within: str
    nfc_only: bool
    folder: tuple[str, ...]  # host folder components, for suffix scores
    # Equal for two hits on the same file. An index entry is itself (two entries whose names
    # differ only by case are two files, as a case-sensitive folder can hold); a point
    # lookup is its path, folded on Windows, where it may be spelled in another case.
    key: tuple
    identity: Identity | None = None
    state: str = "unknown"


@dataclass
class _Ref:
    file: object  # ComponentFile
    stored: StoredPath
    stored_ct: int | None
    warnings: list[ReaderWarning] = field(default_factory=list)
    groups: dict[str, list[list[_Hit]]] = field(default_factory=dict)
    stored_hits: list[_Hit] = field(default_factory=list)
    name_groups: list[tuple[FolderIndex, list[_Hit]]] = field(default_factory=list)
    others: list[_Hit] = field(default_factory=list)
    fallback: _Hit | None = None
    result: ResolvedReference | None = None
    skipped_reads: bool = False


def _warn(code: str, message: str) -> ReaderWarning:
    return ReaderWarning(code, message)


def _as_roots(roots, doc_folder: HostPath | None) -> Roots:
    if roots is None:
        if doc_folder is None:
            raise InvalidArgumentError(
                "a document opened from bytes needs roots to resolve against", detail={"parameter": "roots"}
            )
        return Roots([Root(DOCUMENT_ROOT_ID, doc_folder.join())])
    if isinstance(roots, Roots):
        return roots
    if isinstance(roots, Mapping):
        return Roots.from_mapping(roots)
    if isinstance(roots, Root):
        return Roots([roots])
    if isinstance(roots, Iterable) and not isinstance(roots, (str, bytes)):
        return Roots(roots)
    raise InvalidArgumentError(
        "roots is a Roots, a Root, Roots entries or {id: folder}", detail={"parameter": "roots"}
    )


def _check_count(value, name: str, low: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not value >= low:
        raise InvalidArgumentError(f"{name} must be a number of at least {low}", detail={"parameter": name})


class Resolver:
    """One resolution call; use :func:`resolve_references`."""

    def __init__(
        self,
        inp: ResolutionInput,
        roots,
        *,
        path_map,
        allow_outside_roots: bool,
        max_examined: int,
        max_seconds: float,
        max_candidates: int,
        max_identity_reads: int,
        cache: IndexCache | None,
        gateway: Gateway | None,
        skip_unavailable_roots: bool = False,
    ) -> None:
        for value, name, low in (
            (max_examined, "max_examined", 1),
            (max_seconds, "max_seconds", 0),
            (max_candidates, "max_candidates", 1),
            (max_identity_reads, "max_identity_reads", 0),
        ):
            _check_count(value, name, low)
        if not isinstance(allow_outside_roots, bool):
            raise InvalidArgumentError(
                "allow_outside_roots is true or false", detail={"parameter": "allow_outside_roots"}
            )
        self.inp = inp
        self.deadline = time.monotonic() + max_seconds
        self.gateway = gateway or Gateway(
            allow_outside_roots=allow_outside_roots,
            max_identity_reads=int(max_identity_reads),
            deadline=self.deadline,
        )
        self.allow_outside_roots = self.gateway.allow_outside_roots
        self.path_map: tuple[PathMapping, ...] = parse_path_map(path_map)
        self.max_examined = int(max_examined)
        self.max_candidates = int(max_candidates)
        self.cache = cache if cache is not None else IndexCache()
        self.folder: HostPath | None = self.gateway.document_folder(inp.path) if inp.path else None
        self.roots = _as_roots(roots, self.folder)
        self.folder_at_save: StoredFolder | None = parse_stored_folder(inp.folder_at_save)
        self.unmoved = (
            self.folder is not None
            and self.folder_at_save is not None
            and from_stored(self.folder_at_save.anchor, self.folder_at_save.parts) is not None
            and self.folder_at_save.key == self.folder.key
        )
        self.indexes: list[FolderIndex] = []
        self.skip_unavailable_roots = bool(skip_unavailable_roots)
        self.unavailable: list[str] = []  # ids of roots whose folder could not be walked
        self._memo: dict[tuple, list | str] = {}

    # ------------------------------------------------------------------ indexes
    def _build_indexes(self) -> None:
        spent = 0
        for root in self.roots:
            ck = (fold(root.path), root.recursive)
            index = self.cache.indexes.get(ck)
            if index is None:
                try:
                    index = self.gateway.build_index(
                        root, max_examined=self.max_examined - spent, deadline=self.deadline
                    )
                except OSError:
                    if not self.skip_unavailable_roots:
                        raise
                    self.unavailable.append(root.id)  # searched without it, and every result says so
                    continue
                spent += index.examined
                self.cache.indexes[ck] = index
            else:
                self.gateway.adopt(index)
            # a cached index may have been built for the same folder under another id or role
            self.indexes.append(index if index.root == root else index.with_root(root))

    # ------------------------------------------------------------------ lookups
    def _index_hit(self, index: FolderIndex, f: IndexedFile, rule: str, nfc: bool) -> _Hit:
        host = index.host_of(f)
        path = host.join()
        return _Hit(
            host=host,
            path=path,
            location=Location(index.root.id, f.rel, path),
            found_by=rule,
            name=f.name,
            size=f.size,
            mtime_ns=f.mtime_ns,
            placeholder=f.placeholder,
            within=index.host.join(),
            nfc_only=nfc,
            folder=index.folder_parts(f),
            key=("index", index.host.key, f.rel),
        )

    def _point_hit(self, p: PointHit, rule: str) -> _Hit:
        return _Hit(
            host=p.host,
            path=p.path,
            location=Location(None, p.path, p.path),
            found_by=rule,
            name=p.name,
            size=p.size,
            mtime_ns=p.mtime_ns,
            placeholder=p.placeholder,
            within=within_of(p.host),
            nfc_only=False,
            folder=p.host.parts[:-1],
            key=("point", fold(p.path) if HOST_WINDOWS else p.path),
        )

    def _lookup(self, host: HostPath, rule: str, configured: HostPath | None = None) -> list[_Hit] | str:
        """The documents at ``host`` (a file path): from the index of the first root that
        covers its folder, else by a point lookup through the gateway. Returns hits, or
        the gateway's reason for not looking."""
        memo_key = (host.key, configured.key if configured else None)
        found = self._memo.get(memo_key)
        if found is None:
            folder = HostPath(host.anchor, host.parts[:-1])
            found = None
            for index in self.indexes:
                rel = index.covers(folder)
                if rel is not None:
                    files, nfc = index.lookup(rel, host.parts[-1])
                    found = [(index, f, nfc) for f in files]
                    break
            if found is None:
                p = self.gateway.point_lookup(host, configured=configured)
                found = p if isinstance(p, str) else [p]
            self._memo[memo_key] = found
        if isinstance(found, str):
            return found
        return [
            self._point_hit(x, rule) if isinstance(x, PointHit) else self._index_hit(x[0], x[1], rule, x[2])
            for x in found
        ]

    def _stored_host(self, sp: StoredPath) -> HostPath | None:
        if not sp.usable or sp.name is None:
            return None
        return from_stored(sp.anchor, (*sp.folder, sp.name))

    def _stored_lookup(self, ref: _Ref, rule: str) -> list[_Hit]:
        sp = ref.stored
        host = self._stored_host(sp)
        if host is None:
            if sp.kind == "unc" and sp.usable:
                self._note(
                    ref, "stored_unc_not_checked", "the stored path is on a network share; it was not checked"
                )
            return []
        found = self._lookup(host, rule)
        if isinstance(found, str):
            if found == "unc":
                self._note(
                    ref, "stored_unc_not_checked", "the stored path is on a network share; it was not checked"
                )
            elif found == "network_drive":
                self._note(
                    ref,
                    "stored_network_drive_not_checked",
                    "the stored path is on a mapped network drive; it was not checked",
                )
            return []
        return found

    @staticmethod
    def _note(ref: _Ref, code: str, message: str) -> None:
        if all(w.code != code for w in ref.warnings):
            ref.warnings.append(_warn(code, message))

    # ------------------------------------------------------------------ step 1: positional candidates
    def _positional(self, ref: _Ref) -> None:
        sp = ref.stored
        groups = ref.groups
        stored_hits = self._stored_lookup(ref, "stored_path")
        ref.stored_hits = stored_hits
        if self.unmoved and stored_hits:
            groups["stored_unmoved"] = [[_retag(h, "stored_unmoved") for h in stored_hits]]
        for mapping in self.path_map:
            target = mapping.apply(sp)
            if target is not None:
                found = self._lookup(target, "path_map", configured=mapping.target)
                if not isinstance(found, str) and found:
                    groups["path_map"] = [found]
                break
        name = sp.name if sp.name_ok else None
        fs, a = self.folder_at_save, self.folder
        if (
            fs is not None
            and a is not None
            and sp.usable
            and name is not None
            and fold(fs.anchor) == fold(sp.anchor)
        ):
            k = 0
            for x, y in zip(fs.parts, sp.folder, strict=False):
                if fold(x) != fold(y):
                    break
                k += 1
            ups = len(fs.parts) - k
            if ups <= len(a.parts):
                target = HostPath(a.anchor, (*a.parts[: len(a.parts) - ups], *sp.folder[k:], name))
                found = self._lookup(target, "rebased")
                if not isinstance(found, str) and found:
                    groups["rebased"] = [found]
        if a is not None and name is not None:
            found = self._lookup(a.child(name), "same_folder")
            if not isinstance(found, str) and found:
                groups["same_folder"] = [found]
            probe = self._suffix_probe(ref, a, name)
            if probe:
                groups["suffix_probe"] = probe
        if stored_hits:
            groups["stored_path"] = [stored_hits]

    def _suffix_probe(self, ref: _Ref, a: HostPath, name: str) -> list[list[_Hit]]:
        for index in self.indexes:
            below = index.covers(a)
            if below is None:
                continue
            folder = ref.stored.folder if ref.stored.usable else ()
            out: list[list[_Hit]] = []
            seen: set[str] = set()
            for j in range(len(below), -1, -1):
                base = below[:j]
                for n in range(len(folder) + 1):
                    tail = folder[len(folder) - n :] if n else ()
                    files, nfc = index.lookup((*base, *tail), name)
                    group = [
                        self._index_hit(index, f, "suffix_probe", nfc) for f in files if f.rel not in seen
                    ]
                    if group:
                        seen.update(f.rel for f in files)
                        out.append(group)
                        if sum(len(g) for g in out) >= self.max_candidates:
                            return out
            return out
        return []

    # ------------------------------------------------------------------ step 2: identities
    def _read_identities(self, hits: Iterable[_Hit], stored_ct: dict[int, int | None]) -> None:
        """Every hit's identity, from the cache or from one batched read through the gateway
        (one worker job in the REST service, C10). A file hit twice is read once."""
        todo: dict[tuple, list[_Hit]] = {}
        for h in hits:
            if h.identity is not None:
                continue
            ck = (h.key, h.size, h.mtime_ns)
            ident = self.cache.identities.get(ck)
            if ident is None:
                todo.setdefault(ck, []).append(h)
                continue
            h.identity = ident
            h.state = compare(stored_ct[id(h)], ident)
        if not todo:
            return
        keys = list(todo)
        reads = self.gateway.read_identities(
            [(todo[k][0].path, todo[k][0].within, todo[k][0].placeholder) for k in keys]
        )
        for ck, ident in zip(keys, reads, strict=True):
            if not ident.skipped:
                self.cache.identities[ck] = ident
            for h in todo[ck]:
                h.identity = ident
                h.state = compare(stored_ct[id(h)], ident)

    # ------------------------------------------------------------------ step 3: decide
    def _decide_positional(self, ref: _Ref) -> tuple[_Hit, str] | list[_Hit] | None:
        for rule in POSITIONAL_RULES:
            for group in ref.groups.get(rule, ()):
                acceptable = []
                for h in group:
                    if h.state == "differ":
                        if ref.fallback is None:
                            ref.fallback = h
                        ref.others.append(h)
                    else:
                        acceptable.append(h)
                if not acceptable:
                    continue
                matches = [h for h in acceptable if h.state == "match"]
                pool = matches or acceptable
                if len(pool) == 1:
                    return pool[0], rule
                return pool  # names that differ only by case, both acceptable
        return None

    def _name_candidates(self, ref: _Ref) -> None:
        name = ref.stored.name
        for index in self.indexes:
            files, nfc = index.by_name(name)
            if not files:
                continue
            hits = [self._index_hit(index, f, "name_index", nfc) for f in files]
            hits.sort(key=lambda h: (-suffix_score(h.folder, ref.stored.folder), h.location.path))
            ref.name_groups.append((index, hits))

    def _decide_name(self, ref: _Ref) -> tuple[_Hit, str] | list[_Hit] | None:
        for _index, hits in ref.name_groups:
            read = hits[: self.max_candidates]
            acceptable = []
            for h in read:
                if h.state == "differ":
                    ref.others.append(h)
                else:
                    acceptable.append(h)
            if not acceptable:
                continue
            matches = [h for h in acceptable if h.state == "match"]
            pool = matches or acceptable
            ref.others.extend(h for h in acceptable if h not in pool)
            if len(pool) == 1:
                return pool[0], "name_index"
            scores = sorted(
                ((suffix_score(h.folder, ref.stored.folder), h) for h in pool), key=lambda x: -x[0]
            )
            if scores[0][0] > scores[1][0]:  # a unique highest score, so above 0
                ref.others.extend(h for h in pool if h is not scores[0][1])
                return scores[0][1], "name_index_suffix"
            return pool
        return None

    # ------------------------------------------------------------------ results
    def _is_stored(self, h: _Hit, sp: StoredPath) -> bool:
        """Whether ``h`` is the stored path itself, as stored or through the path map."""
        host = self._stored_host(sp)
        if host is not None and host.key == h.host.key:
            return True
        for mapping in self.path_map:
            target = mapping.apply(sp)
            if target is not None:
                return target.key == h.host.key
        return False

    def _candidates(self, hits: Iterable[_Hit], exclude: _Hit | None = None) -> tuple[Candidate, ...]:
        out: list[Candidate] = []
        seen = {exclude.key} if exclude is not None else set()
        for h in hits:
            if h.key in seen:
                continue
            seen.add(h.key)
            out.append(Candidate(h.location, h.found_by, h.state, h.placeholder))
            if len(out) >= self.max_candidates:
                break
        return tuple(out)

    def _hit_warnings(self, ref: _Ref, h: _Hit) -> None:
        sp = ref.stored
        if sp.name and h.name != sp.name and fold(h.name) == fold(sp.name):
            self._note(ref, "case_differs", "the file's name differs from the stored name only by case")
        if h.nfc_only:
            self._note(
                ref,
                "normalization_differs",
                "the name matches the stored one only after Unicode normalisation",
            )
        if h.location.root is None:
            self._note(ref, "outside_roots", "the file is outside every root")
        if h.placeholder:
            self._note(ref, "placeholder_not_read", "the file is a cloud placeholder and was not opened")
        if h.identity is not None and h.identity.error is not None:
            self._note(ref, "identity_read_failed", f"the file could not be read ({h.identity.error})")
        if h.identity is not None and h.identity.skipped:
            ref.skipped_reads = True

    def _finish(self, ref: _Ref, decision) -> ResolvedReference:
        sp = ref.stored
        partial = any(i.partial for i in self.indexes)
        if partial:
            self._note(ref, "index_partial", "a limit cut a root's folder index short")
        if self.unavailable:
            self._note(ref, "root_unavailable", "a root could not be searched; its files are not candidates")
            partial = True
        if isinstance(decision, tuple):
            h, rule = decision
            self._hit_warnings(ref, h)
            others = list(ref.others)
            if rule in _ALSO_EXISTS_RULES:
                also = [s for s in ref.stored_hits if s.key != h.key]
                if also:
                    self._note(ref, "stored_path_also_exists", "another file still exists at the stored path")
                    others = also + others
            ident = h.state
            conf = CONFIDENCE[rule][0 if ident == "match" else 1]
            if ref.skipped_reads:
                self._note(ref, "search_incomplete", "a limit stopped reading some files' identity")
            return self._result(
                ref,
                "resolved" if self._is_stored(h, sp) else "moved",
                h.location,
                rule,
                conf,
                ident,
                others,
                h,
            )
        if isinstance(decision, list):
            for h in decision:
                self._hit_warnings(ref, h)
            ref.warnings = [w for w in ref.warnings if w.code not in ("case_differs", "outside_roots")]
            return self._result(ref, "ambiguous", None, None, "none", "unknown", decision + ref.others, None)
        if ref.fallback is not None:
            h = ref.fallback
            self._hit_warnings(ref, h)
            self._note(ref, "identity_mismatch", "the only file found has another creation time")
            status = "resolved" if self._is_stored(h, sp) else "moved"
            return self._result(ref, status, h.location, h.found_by, "low", "differ", ref.others, h)
        if partial or ref.skipped_reads:
            self._note(ref, "search_incomplete", "a limit stopped the search before it was complete")
        all_others = ref.others + [h for _i, hits in ref.name_groups for h in hits]
        return self._result(ref, "missing", None, None, "none", "unknown", all_others, None)

    def _result(self, ref, status, match, rule, confidence, identity, others, chosen) -> ResolvedReference:
        return ResolvedReference(
            key=ref.file.key,
            status=status,
            stored_path=ref.stored.raw or None,
            match=match,
            rule=rule,
            confidence=confidence,
            identity=identity,
            nested=None,
            candidates=self._candidates(others, chosen),
            warnings=tuple(ref.warnings),
        )

    def _embedded(
        self, f: InputFile, stored_ct: int | None, warnings: list[ReaderWarning]
    ) -> ResolvedReference:
        status = f.embedded
        identity, confidence = "unknown", "none"
        if status == "embedded" and f.nested:
            ident = f.nested_identity or Identity(None)
            if ident.error is not None:
                warnings.append(_warn("identity_read_failed", "the nested document could not be read"))
            identity = compare(stored_ct, ident)
            if identity == "differ":
                warnings.append(_warn("identity_mismatch", "the nested document has another creation time"))
                confidence = "low"
            else:
                confidence = CONFIDENCE["embedded"][0 if identity == "match" else 1]
        return ResolvedReference(
            key=f.key,
            status=status,
            stored_path=f.stored_path,
            match=None,
            rule="embedded",
            confidence=confidence,
            identity=identity,
            nested=f.nested if status == "embedded" else None,
            candidates=(),
            warnings=tuple(warnings),
        )

    # ------------------------------------------------------------------ the call
    def run(self) -> Resolution:
        files = list(self.inp.files)
        truncated = len(files) > MAX_REFERENCES
        files = files[:MAX_REFERENCES]
        results: dict[str, ResolvedReference] = {}
        pending: list[_Ref] = []
        for f in files:
            warnings: list[ReaderWarning] = []
            if f.direct is False:
                warnings.append(
                    _warn(
                        "from_parent_tree",
                        "resolved from the path the top document stored for a sub-assembly's file",
                    )
                )
            if f.parent_documents > 1:
                warnings.append(_warn("context_varies", "the file is used by more than one parent document"))
            stored_ct = f.stored_creation_time
            if f.embedded is not None:
                results[f.key] = self._embedded(f, stored_ct, warnings)
                continue
            sp = parse_stored(f.stored_path)
            ref = _Ref(f, sp, stored_ct, warnings)
            if sp.problem is not None:
                self._note(
                    ref, "stored_path_refused", f"the stored path is not used as a location ({sp.problem})"
                )
            results[f.key] = None  # keeps the references order
            pending.append(ref)
        if pending:  # a part, or only embedded files: no folder needs walking
            self._build_indexes()
        # step 1 and 2: positional candidates, then their identities in one batch
        for ref in pending:
            self._positional(ref)
        cts: dict[int, int | None] = {}
        batch: list[_Hit] = []
        for ref in pending:
            for groups in ref.groups.values():
                for g in groups:
                    for h in g:
                        cts[id(h)] = ref.stored_ct
                        batch.append(h)
            for h in ref.stored_hits:
                cts[id(h)] = ref.stored_ct
                batch.append(h)
        self._read_identities(batch, cts)
        undecided: list[_Ref] = []
        for ref in pending:
            decision = self._decide_positional(ref)
            if decision is None and ref.stored.name_ok:
                undecided.append(ref)
            else:
                ref.result = self._finish(ref, decision)
        # the name index, the same way
        batch = []
        for ref in undecided:
            self._name_candidates(ref)
            for _i, hits in ref.name_groups:
                for h in hits[: self.max_candidates]:
                    cts[id(h)] = ref.stored_ct
                    batch.append(h)
        self._read_identities(batch, cts)
        for ref in undecided:
            ref.result = self._finish(ref, self._decide_name(ref))
        for ref in pending:
            results[ref.file.key] = ref.result
        built = {i.root.id: i for i in self.indexes}
        states = tuple(
            RootState(r.id, r.role, r.recursive, True, "unavailable")
            if r.id in self.unavailable
            else RootState(
                r.id,
                r.role,
                r.recursive,
                r.id in built and built[r.id].partial is not None,
                built[r.id].partial if r.id in built else None,
            )
            for r in self.roots
        )
        return Resolution(
            results=results,
            roots=states,
            index_partial=any(s.index_partial for s in states),
            allow_outside_roots=self.allow_outside_roots,
            truncated=truncated,
        )


def _retag(h: _Hit, rule: str) -> _Hit:
    return _Hit(**{**h.__dict__, "found_by": rule})


def resolve_references(
    doc: "ResolutionInput | object",
    roots=None,
    *,
    path_map=(),
    allow_outside_roots: bool = True,
    max_examined: int = DEFAULT_MAX_EXAMINED,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    max_identity_reads: int = DEFAULT_MAX_IDENTITY_READS,
    cache: IndexCache | None = None,
    gateway: Gateway | None = None,
    skip_unavailable_roots: bool = False,
) -> Resolution:
    """Resolve every file ``doc`` references (``docs/API.md`` section 3.10).

    ``doc`` is an open document, or a :class:`ResolutionInput` read from one
    (the REST service reads it in a worker process). ``roots`` is a
    :class:`~solidseas.roots.Roots`, Root objects or ``{id: folder}``; None searches
    the document's own folder, recursively, as root ``document``. ``path_map`` maps
    stored prefixes to folders on this machine (``"S:\\\\=/mnt/eng"`` strings or
    pairs). ``allow_outside_roots`` permits point lookups of single known paths
    outside every root, on local drives only.
    ``max_examined`` and ``max_seconds`` bound the folder walks of this call
    (indexes in ``cache`` are reused), ``max_candidates`` the candidates read and
    reported per reference, and ``max_identity_reads`` the documents opened.
    ``skip_unavailable_roots`` searches without a root whose folder cannot be walked
    (it is gone, or access is denied) instead of raising: that root is reported with
    ``index_partial`` and ``truncated_reason`` ``"unavailable"``, and every result
    carries the warning ``root_unavailable``. The REST service sets it.
    """
    inp = doc if isinstance(doc, ResolutionInput) else ResolutionInput.from_document(doc)
    return Resolver(
        inp,
        roots,
        path_map=path_map,
        allow_outside_roots=allow_outside_roots,
        max_examined=max_examined,
        max_seconds=max_seconds,
        max_candidates=max_candidates,
        max_identity_reads=max_identity_reads,
        cache=cache,
        gateway=gateway,
        skip_unavailable_roots=skip_unavailable_roots,
    ).run()


__all__ = [
    "CONFIDENCE",
    "DOCUMENT_ROOT_ID",
    "MAX_REFERENCES",
    "POSITIONAL_RULES",
    "RULES",
    "STATUSES",
    "Candidate",
    "IndexCache",
    "InputFile",
    "Location",
    "Resolution",
    "ResolutionInput",
    "ResolvedReference",
    "Resolver",
    "RootState",
    "resolve_references",
]
