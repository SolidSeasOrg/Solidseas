"""The path-leak report: every path and name a document reveals to whoever receives it.

:func:`path_report` reads, for the document and recursively for every nested
document (virtual and imported components):

1. **Structured carriers first.** The folder and file name at save
   (``SW-Folder Name``, ``SW-File Name``), the user names (the ``Header2`` user
   list, ``SW-Author``, ``SW-Last Saved By``, every ``lastModifiedBy`` and the
   creator in ``docProps/core.xml``, the legacy summary author and last author),
   the component tree's ``swPath`` and ``swImportedPath``, ``Header2``'s
   reference paths, and the length-delimited strings of the streams that hold
   paths by design: ``_MO_VERSION_<n>/Biography``, ``Header2``,
   ``SwDocContentMgr/SwDocContentMgrInfo``, ``Contents/Config-<n>-ModelHeader``
   and ``Contents/DisplayLists``.
2. **Then the byte scan** (:func:`.paths.scan_bytes`) over every stream as a
   fallback, for paths stored anywhere else.

Paths are merged case-insensitively (``/`` read as ``\\``, a trailing ``\\``
ignored), keeping the first spelling, so a structured carrier's spelling wins.
Each keeps the streams and nested documents it was found in.

``complete`` is false when a stream was over the scan cap or unreadable, an
identity carrier could not be read, a nested document could not be opened, or
a limit stopped the report; ``incomplete`` says which. SolidSeas never rewrites
files: removing what the report lists means saving a new document in SOLIDWORKS
or sending a neutral format.

Per path the report gives a ``category`` (where on disk), the ``roles`` it plays
(why the file stores it), the ``account`` and UNC ``host`` and ``share`` it
names, and a ``severity`` for "sending this file to a customer". Severity is a
per-finding label only: a whole-file rating would read "high" for nearly every
document (the save location alone is in 3,153 of 3,501 corpus files), so the
report counts paths per category and role instead. An account seen only in
history records (the ``Biography`` paths, the ``Header2`` user list, older
saves) is ``inherited_likely``, probably from the template the document was made
from (a HYPOTHESIS, verified on the fixtures only), and stays at severity
``medium``: under-ranking is the dangerous direction for this report.
"""

import re
from dataclasses import dataclass, field

from ...errors import SolidSeasError
from .errors import LockedFileError, ReaderWarning
from .paths import DEFAULT_MAX_SCAN_BYTES, scan_bytes

DEFAULT_MAX_PATHS = 100_000
DEFAULT_MAX_DOCUMENTS = 1_000
DEFAULT_MAX_TOTAL_BYTES = 1 << 30  # the largest corpus document reads 79 MB

CATEGORIES = ("unc", "project", "profile", "desktop", "temp", "program", "windows", "drive_root")
ROLES = ("references", "imported_from", "save_location", "resources", "history", "other")
SEVERITIES = ("high", "medium", "low")
#: identity fields that hold a user name; ``file_name_at_save`` is the only other field
USER_FIELDS = (
    "header2_user",
    "core_last_modified_by",
    "core_creator",
    "sw_author",
    "sw_last_saved_by",
    "summary_author",
    "summary_last_author",
)
NAME_FIELDS = (*USER_FIELDS, "file_name_at_save")
WELL_KNOWN_PROFILES = frozenset(("public", "default", "default user", "all users"))
REWRITE_NOTE = (
    "SolidSeas never rewrites files. Removing these values means saving a new document in "
    "SOLIDWORKS or sending a neutral format."
)

# streams whose CStrings hold paths by design, and the source name each gets
_CARRIERS = (
    (re.compile(r"_MO_VERSION_\d+/Biography(?:__ZLB)?$", re.I), "biography"),
    (re.compile(r"Header2(?:__ZLB)?$", re.I), "header2"),
    (re.compile(r"SwDocContentMgr/SwDocContentMgrInfo(?:__ZLB)?$", re.I), "content_manager"),
    (re.compile(r"Contents/Config-\d+-ModelHeader(?:__ZLB)?$", re.I), "model_header"),
    (re.compile(r"Contents/DisplayLists(?:__ZLB)?$", re.I), "display_lists"),
)
_HISTORY = re.compile(r"_MO_VERSION_\d+/Biography(?:__ZLB)?$", re.I)
_SAVE_INFO = re.compile(r"(?:docProps/ISolidWorksInformation\.xml|\x05?ISolidWorksInformation)$", re.I)
_RESOURCES = re.compile(
    r"(?:Contents/CMgr|Contents/Config-\d+|swXmlContents/Features|ThirdPtyStore/VisualStates)(?:__ZLB)?$",
    re.I,
)
# carriers the identity fields and structured paths come from: a problem with one makes
# the report incomplete
_IDENTITY_CARRIERS = re.compile(
    r"(?:docProps/core\.xml|docProps/ISolidWorksInformation\.xml|\x05?ISolidWorksInformation"
    r"|\x05?SummaryInformation|Header2|swXmlContents/COMPINSTANCETREE)(?:__ZLB)?$",
    re.I,
)
_CARRIER_PROBLEMS = frozenset(
    ("stream_too_large", "stream_unreadable", "xml_doctype_refused", "xml_parse_error", "property_set_error")
)
_DOC_EXT = re.compile(r"\.(?:sldprt|sldasm|slddrw)$", re.I)
_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\[^\\]+\\|//[^/]+/)")
_DEVICE_UNC = re.compile(r"^\\\\[?.]\\UNC\\", re.I)
_DEVICE_DRIVE = re.compile(r"^\\\\[?.]\\(?=[A-Za-z]:)")
_UNC = re.compile(r"^\\\\([^\\]+)(?:\\([^\\]*))?")
_ACCOUNT = re.compile(r"^(?:[A-Za-z]:|\\\\[^\\]+\\[^\\]+)\\(?:users|documents and settings)\\([^\\]+)", re.I)
_TEMP = re.compile(
    r"\\appdata\\local\\temp(?:\\|$)|\\local settings\\temp(?:\\|$)|^[a-z]:\\(?:windows\\)?te?mp(?:\\|$)"
)
_DESKTOP = re.compile(r"^[a-z]:\\(?:users|documents and settings)\\[^\\]+\\desktop(?:\\|$)")
_PROFILE = re.compile(r"^[a-z]:\\(?:users|documents and settings)(?:\\|$)")
_WINDOWS = re.compile(r"^[a-z]:\\(?:windows|winnt)(?:\\|$)")
_PROGRAM = re.compile(r"^[a-z]:\\(?:program files(?: \(x86\))?|programdata)(?:\\|$)")


@dataclass(frozen=True)
class Location:
    """Where a value was found: the chain of nested-document streams from the top
    document (empty for the file itself) and the stream."""

    nested: tuple[str, ...]
    stream: str | None


@dataclass(frozen=True)
class FoundPath:
    path: str
    category: str
    account: str | None
    host: str | None
    share: str | None
    roles: tuple[str, ...]
    sources: tuple[str, ...]
    locations: tuple[Location, ...]
    history_only: bool
    inherited_likely: bool
    severity: str
    reason: str


@dataclass(frozen=True)
class IdentityField:
    """A user name, or the file name at save, as one carrier stores it. ``current`` is
    False for history: a ``Header2`` user list entry or an older save record."""

    field: str
    value: str
    current: bool
    location: Location


@dataclass(frozen=True)
class Account:
    name: str
    sources: tuple[str, ...]
    paths: int
    identity_fields: int
    history_only: bool
    inherited_likely: bool
    severity: str


@dataclass(frozen=True)
class Host:
    host: str
    shares: tuple[str, ...]
    paths: int
    severity: str


@dataclass(frozen=True)
class Incomplete:
    reason: str  # stream_over_cap, stream_unreadable, carrier_unreadable, nested_unreadable, ...
    nested: tuple[str, ...]
    stream: str | None


@dataclass(frozen=True)
class ScannedDocument:
    nested: tuple[str, ...]
    doc_type: str | None
    streams: int
    streams_scanned: int
    bytes_scanned: int


@dataclass(frozen=True)
class PathReport:
    """What :func:`path_report` found. ``docs/API.md`` section 5.11 describes every field."""

    complete: bool
    incomplete: tuple[Incomplete, ...]
    documents: tuple[ScannedDocument, ...]
    paths: tuple[FoundPath, ...]
    accounts: tuple[Account, ...]
    hosts: tuple[Host, ...]
    identity_fields: tuple[IdentityField, ...]
    warnings: tuple[ReaderWarning, ...] = field(default=())

    def counts(self) -> dict[str, object]:
        by_category = dict.fromkeys(CATEGORIES, 0)
        by_role = dict.fromkeys(ROLES, 0)
        for p in self.paths:
            by_category[p.category] = by_category.get(p.category, 0) + 1
            for r in p.roles:
                by_role[r] = by_role.get(r, 0) + 1
        return {
            "paths": len(self.paths),
            "accounts": len(self.accounts),
            "hosts": len(self.hosts),
            "identity_fields": len(self.identity_fields),
            "documents": len(self.documents),
            "by_category": by_category,
            "by_role": by_role,
        }


# --------------------------------------------------------------------------- classification
def _normal(path: str) -> str:
    p = path.replace("/", "\\")
    m = _DEVICE_UNC.match(p)
    if m:
        return "\\\\" + p[m.end() :]
    return _DEVICE_DRIVE.sub("", p, count=1)


def _key(path: str) -> str:
    k = _normal(path).casefold()
    trimmed = k.rstrip("\\")
    return trimmed if len(trimmed) > 2 else k


def _file_name(key: str) -> str:
    return key.rsplit("\\", 1)[-1]


def account_of(path: str) -> str | None:
    """The account a path names through ``\\Users\\<name>`` or ``\\Documents and
    Settings\\<name>``, or None (also for Public, Default, Default User and All Users)."""
    m = _ACCOUNT.match(_normal(path))
    if m is None or m.group(1).casefold() in WELL_KNOWN_PROFILES:
        return None
    return m.group(1)


def categorize(path: str) -> tuple[str, str | None, str | None]:
    """``(category, host, share)`` of an absolute path. A WebDAV host such as
    ``host@SSL@443`` is reported as ``host``."""
    p = _normal(path)
    if p.startswith("\\\\"):
        m = _UNC.match(p)
        host = (m.group(1).split("@", 1)[0] or None) if m else None
        share = (m.group(2) or None) if m else None
        return "unc", host, share
    low = p.casefold()
    if _TEMP.search(low):
        return "temp", None, None
    if _DESKTOP.match(low):
        return "desktop", None, None
    if _PROFILE.match(low):
        return "profile", None, None
    if _WINDOWS.match(low):
        return "windows", None, None
    if _PROGRAM.match(low):
        return "program", None, None
    rest = low[3:].strip("\\") if re.match(r"^[a-z]:\\", low) else low
    if "\\" not in rest:
        return "drive_root", None, None
    return "project", None, None


def severity(category: str, roles: tuple[str, ...], account: str | None, inherited: bool) -> tuple[str, str]:
    """``(severity, reason)`` for sending a file holding this path to a customer; the
    first rule that matches wins."""
    if category == "unc":
        return "high", "unc_share"
    if "references" in roles or "imported_from" in roles:
        return "high", "referenced_document"
    if "save_location" in roles:
        return "high", "save_location"
    if category == "project":
        return "high", "folder_names"
    if account is not None:
        return "medium", "inherited_template" if inherited else "account_name"
    if category in ("profile", "desktop", "temp"):
        return "medium", "profile_folder"
    return "low", "standard_folder"


def _role(stream: str, path: str) -> str:
    """The role of a path the scan found: ``history`` in the save-session records, the
    save location in ``ISolidWorksInformation``, ``references`` for a SOLIDWORKS
    document elsewhere, ``resources`` for any other file or folder in a stream that
    holds paths by design, and ``other`` for the rest."""
    if _HISTORY.search(stream):
        return "history"
    if _SAVE_INFO.search(stream):
        return "save_location"
    if _DOC_EXT.search(path.rstrip()):
        return "references"
    if _RESOURCES.search(stream) or _carrier(stream):
        return "resources"
    return "other"


def _carrier(stream: str) -> str | None:
    for rx, name in _CARRIERS:
        if rx.search(stream):
            return name
    return None


# --------------------------------------------------------------------------- collection
class _Limit(Exception):
    pass


class _Collector:
    def __init__(self, max_stream_bytes: int, max_paths: int, max_documents: int, max_total_bytes: int):
        self.max_stream_bytes = max_stream_bytes
        self.max_paths = max_paths
        self.max_documents = max_documents
        self.max_total_bytes = max_total_bytes
        self.total_bytes = 0
        self.paths: dict[str, dict] = {}
        self.fields: list[IdentityField] = []
        self.incomplete: list[Incomplete] = []
        self.documents: list[ScannedDocument] = []
        self.warnings: list[ReaderWarning] = []
        self.own: set[str] = set()  # file names (folded) of the current document itself

    def gap(self, reason: str, nested: tuple[str, ...], stream: str | None) -> None:
        item = Incomplete(reason, nested, stream)
        if item not in self.incomplete:
            self.incomplete.append(item)

    def add(self, path: str, role: str, source: str, loc: Location) -> None:
        key = _key(path)
        roles = [role]
        if role in ("references", "history") and _file_name(key) in self.own:
            # the document's own path at a save: where it was saved, not a reference
            roles = ["history", "save_location"] if role == "history" else ["save_location"]
        rec = self.paths.get(key)
        if rec is None:
            if len(self.paths) >= self.max_paths:
                self.gap("path_limit", (), None)
                return
            rec = self.paths[key] = {"path": path, "roles": [], "sources": [], "locations": []}
        for k, values in (("roles", roles), ("sources", [source]), ("locations", [loc])):
            for v in values:
                if v not in rec[k]:
                    rec[k].append(v)

    def charge(self, size: int, nested: tuple[str, ...], stream: str) -> bool:
        if self.total_bytes + size > self.max_total_bytes:
            self.gap("byte_limit", nested, stream)
            return False
        self.total_bytes += size
        return True


def _structured(doc, chain: tuple[str, ...], col: _Collector) -> None:
    md = doc.metadata
    for w in md.warnings:
        if w.code in _CARRIER_PROBLEMS and w.stream and _IDENTITY_CARRIERS.search(w.stream):
            col.gap("carrier_unreadable", chain, w.stream)
            if not chain:
                col.warnings.append(w)
    for item in md.identity:
        loc = Location(chain, item["stream"])
        if item["field"] == "folder_at_save":
            col.add(item["value"], "save_location", "save_folder", loc)
        elif item["field"] in NAME_FIELDS:
            col.fields.append(IdentityField(item["field"], item["value"], bool(item["current"]), loc))
    tree_loc = Location(chain, md.tree_stream)
    own = md.own_file_ids
    col.own = {
        _file_name(_key(f["path"]))
        for fid, f in (md.tree.get("files") or {}).items()
        if fid in own and isinstance(f.get("path"), str) and f["path"].strip()
    }
    if not chain and doc.name:
        col.own.add(_file_name(_key(doc.name)))
    for fid, f in (md.tree.get("files") or {}).items():
        p = f.get("path")
        if isinstance(p, str) and _ABSOLUTE.match(p):
            col.add(p, "save_location" if fid in own else "references", "tree", tree_loc)
        q = f.get("imported_path")
        if isinstance(q, str) and q.strip():
            col.add(q, "imported_from", "tree_imported", tree_loc)
    for p in (md.header2 or {}).get("ext_paths", []):
        col.add(p, "references", "header2", Location(chain, "Header2"))


def _scan_streams(doc, chain: tuple[str, ...], col: _Collector, skip: set[str]) -> tuple[int, int, bool]:
    """Scan the document's own streams; ``(streams scanned, bytes scanned, stopped by
    the byte limit)``. What was found before a limit stopped the scan is kept."""
    structured: list[tuple[str, str, str, Location]] = []
    scanned: list[tuple[str, str, str, Location]] = []
    n_scanned = n_bytes = 0
    limited = False
    for info in doc.streams():
        if info.name in skip:
            continue
        if info.size > col.max_stream_bytes:
            col.gap("stream_over_cap", chain, info.name)
            continue
        if not col.charge(info.size, chain, info.name):
            limited = True
            break
        try:
            data = doc.container.read(info.name, max_bytes=col.max_stream_bytes)
        except LockedFileError:
            raise
        except SolidSeasError:
            col.gap("stream_unreadable", chain, info.name)
            continue
        n_scanned += 1
        n_bytes += len(data)
        carrier = _carrier(info.name)
        loc = Location(chain, info.name)
        for p, enc in scan_bytes(data):
            hit = (p, _role(info.name, p), carrier if carrier and enc == "cstring" else "scan", loc)
            (structured if hit[2] != "scan" else scanned).append(hit)
    for hit in structured + scanned:
        col.add(*hit)
    return n_scanned, n_bytes, limited


def _document(doc, chain: tuple[str, ...], col: _Collector) -> None:
    if len(col.documents) >= col.max_documents:
        col.gap("document_limit", chain, None)
        raise _Limit
    nested = doc.nested_documents()
    _structured(doc, chain, col)
    n_scanned, n_bytes, limited = _scan_streams(doc, chain, col, set(nested))
    col.documents.append(ScannedDocument(chain, doc.doc_type, len(doc.streams()), n_scanned, n_bytes))
    if limited:
        raise _Limit
    for name in nested:
        sub = chain + (name,)
        try:
            size = doc.container.info(name).size
        except SolidSeasError:
            col.gap("nested_unreadable", chain, name)
            continue
        if not col.charge(size, chain, name):
            raise _Limit
        try:
            nd = doc.open_nested(name)
        except LockedFileError:
            raise
        except SolidSeasError:
            col.gap("nested_unreadable", chain, name)
            _scan_raw(doc, chain, name, col)
            continue
        try:
            _document(nd, sub, col)
        finally:
            nd.close()


def _scan_raw(doc, chain: tuple[str, ...], name: str, col: _Collector) -> None:
    """A nested document that does not open: scan its stored bytes for what they show."""
    try:
        if doc.container.info(name).size > col.max_stream_bytes:
            return
        data = doc.container.read(name, max_bytes=col.max_stream_bytes)
    except LockedFileError:
        raise
    except SolidSeasError:
        return
    loc = Location(chain, name)
    for p, _enc in scan_bytes(data):
        col.add(p, _role(name, p), "scan", loc)


def _finish(col: _Collector) -> PathReport:
    # accounts: from paths, then from user-name fields
    accounts: dict[str, dict] = {}

    def acct(name: str) -> dict:
        return accounts.setdefault(
            name.casefold(),
            {"name": name, "sources": [], "paths": 0, "history_paths": 0, "fields": 0, "current": False},
        )

    recs = list(col.paths.values())
    for rec in recs:
        rec["roles"] = tuple(r for r in ROLES if r in rec["roles"]) + tuple(
            r for r in rec["roles"] if r not in ROLES
        )
        rec["account"] = account_of(rec["path"])
        rec["category"], rec["host"], rec["share"] = categorize(rec["path"])
        if rec["account"] is not None:
            a = acct(rec["account"])
            a["paths"] += 1
            if rec["roles"] == ("history",):
                a["history_paths"] += 1
            else:
                a["current"] = True
            if "path" not in a["sources"]:
                a["sources"].append("path")
    for f in col.fields:
        if f.field not in USER_FIELDS:
            continue
        a = acct(f.value.strip())
        a["fields"] += 1
        a["current"] = a["current"] or f.current
        if f.field not in a["sources"]:
            a["sources"].append(f.field)
    out_accounts = []
    inherited: set[str] = set()
    for key, a in sorted(accounts.items()):
        history_only = a["paths"] > 0 and a["history_paths"] == a["paths"]
        inherited_likely = not a["current"]
        if inherited_likely:
            inherited.add(key)
        out_accounts.append(
            Account(
                name=a["name"],
                sources=tuple(a["sources"]),
                paths=a["paths"],
                identity_fields=a["fields"],
                history_only=history_only,
                inherited_likely=inherited_likely,
                severity="medium",
            )
        )
    hosts: dict[str, dict] = {}
    found = []
    for rec in recs:
        hist = rec["roles"] == ("history",)
        acc = rec["account"]
        inh = hist and acc is not None and acc.casefold() in inherited
        sev, reason = severity(rec["category"], rec["roles"], acc, inh)
        found.append(
            FoundPath(
                rec["path"],
                rec["category"],
                acc,
                rec["host"],
                rec["share"],
                rec["roles"],
                tuple(rec["sources"]),
                tuple(rec["locations"]),
                hist,
                inh,
                sev,
                reason,
            )
        )
        if rec["host"]:
            h = hosts.setdefault(rec["host"].casefold(), {"host": rec["host"], "shares": [], "paths": 0})
            h["paths"] += 1
            share = rec["share"]
            if share and share.casefold() not in {s.casefold() for s in h["shares"]}:
                h["shares"].append(share)
    rank = {s: i for i, s in enumerate(SEVERITIES)}
    cat_rank = {c: i for i, c in enumerate(CATEGORIES)}
    found.sort(key=lambda p: (rank.get(p.severity, 9), cat_rank.get(p.category, 99), p.path.casefold()))
    out_hosts = tuple(
        Host(h["host"], tuple(h["shares"]), h["paths"], "high") for _, h in sorted(hosts.items())
    )
    return PathReport(
        complete=not col.incomplete,
        incomplete=tuple(col.incomplete),
        documents=tuple(col.documents),
        paths=tuple(found),
        accounts=tuple(out_accounts),
        hosts=out_hosts,
        identity_fields=tuple(col.fields),
        warnings=tuple(col.warnings),
    )


def path_report(
    doc,
    *,
    max_stream_bytes: int = DEFAULT_MAX_SCAN_BYTES,
    max_paths: int = DEFAULT_MAX_PATHS,
    max_documents: int = DEFAULT_MAX_DOCUMENTS,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
) -> PathReport:
    """The path-leak report of an open :class:`~.document.Document` and every nested
    document in it. Never raises for what the file holds; a limit or an unreadable part
    makes ``complete`` false instead. Only a lock on the whole file
    (:class:`~.errors.LockedFileError`) propagates."""
    col = _Collector(max_stream_bytes, max_paths, max_documents, max_total_bytes)
    try:
        _document(doc, (), col)
    except _Limit:
        pass
    return _finish(col)
