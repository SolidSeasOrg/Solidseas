"""The catalog's tables, its version marks and its migrations (``docs/API.md`` 3.18).

A catalog is two SQLite files: ``catalog.sqlite`` holds everything but the
preview images, which ``previews.sqlite`` beside it keeps once each, by their
SHA-256. ``PRAGMA application_id`` marks both as SolidSeas files ("SSCT" and
"SSPV"), so a database that is not one is refused before anything is written
to it, and ``PRAGMA user_version`` is the schema version.

Only what SQLite 3.31 has is used (Ubuntu 20.04's library): no STRICT tables,
no ``RETURNING`` and no JSON functions in queries. Full-text search uses FTS5
where the library has it; elsewhere the search falls back on ``LIKE`` over the
same tables (:mod:`.query`).

**Migrations.** :data:`MIGRATIONS` maps a version to the function that brings
a database from it to the next one, run under the writer lock in one
``BEGIN IMMEDIATE`` transaction with ``user_version`` set in the same
transaction. A change that cannot be made in place is :func:`rebuild`: every
table but ``meta`` and ``roots`` is dropped and made again, and every root is
marked ``new``, so the next scan reads everything again. That is always
allowed because a catalog is a cache of what the files say.
"""

from collections.abc import Callable

APPLICATION_ID = 0x53534354  # "SSCT"
PREVIEWS_APPLICATION_ID = 0x53535056  # "SSPV"
SCHEMA_VERSION = 2
MIN_READER_SCHEMA = 1  # version 2 only added columns, which a version 1 reader passes over
PREVIEWS_VERSION = 1
# What the catalog_document job extracts. A row read by an older revision is read again
# by the next scan, after the rows that are new or changed.
READER_REVISION = 1

TABLES = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;

CREATE TABLE roots (
  id INTEGER PRIMARY KEY,
  root_id TEXT NOT NULL UNIQUE,
  path TEXT NOT NULL,
  path_fold TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL,
  recursive INTEGER NOT NULL,
  position INTEGER NOT NULL,
  network INTEGER NOT NULL,
  hash_policy TEXT,
  state TEXT NOT NULL,
  partial TEXT,
  last_scan INTEGER,
  last_complete_scan INTEGER
);

CREATE TABLE scans (
  id INTEGER PRIMARY KEY,
  started_utc TEXT NOT NULL,
  finished_utc TEXT,
  library_version TEXT NOT NULL,
  state TEXT NOT NULL,
  counts TEXT NOT NULL
);

CREATE TABLE folders (
  id INTEGER PRIMARY KEY,
  root INTEGER NOT NULL REFERENCES roots ON DELETE CASCADE,
  rel TEXT NOT NULL,
  name TEXT NOT NULL,
  UNIQUE (root, rel)
);

CREATE TABLE files (
  id INTEGER PRIMARY KEY,
  root INTEGER NOT NULL REFERENCES roots ON DELETE CASCADE,
  folder INTEGER NOT NULL REFERENCES folders,
  rel TEXT NOT NULL,
  name TEXT NOT NULL,
  name_fold TEXT NOT NULL,
  ext TEXT NOT NULL,
  kind TEXT NOT NULL,
  size INTEGER,
  mtime_ns INTEGER,
  file_id TEXT,
  first_scan INTEGER NOT NULL,
  seen_scan INTEGER NOT NULL,
  changed_scan INTEGER NOT NULL,
  stale INTEGER NOT NULL DEFAULT 0,
  state TEXT NOT NULL,
  read_size INTEGER,
  read_mtime_ns INTEGER,
  reader_revision INTEGER,
  error_code TEXT,
  error_retryable INTEGER,
  error_count INTEGER NOT NULL DEFAULT 0,
  sha256 TEXT,
  hash_size INTEGER,
  hash_mtime_ns INTEGER,
  resolve INTEGER NOT NULL DEFAULT 0,
  UNIQUE (root, rel)
);
CREATE INDEX files_name ON files (name_fold);
CREATE INDEX files_folder ON files (folder);
CREATE INDEX files_sha256 ON files (sha256) WHERE sha256 IS NOT NULL;
CREATE INDEX files_size ON files (size);
CREATE INDEX files_mtime ON files (mtime_ns);
CREATE INDEX files_state ON files (state) WHERE state <> 'ok';
CREATE INDEX files_seen ON files (root, seen_scan);
CREATE INDEX files_resolve ON files (resolve) WHERE resolve = 1;
CREATE INDEX files_stale ON files (stale) WHERE stale = 1;

CREATE TABLE documents (
  file INTEGER PRIMARY KEY REFERENCES files ON DELETE CASCADE,
  format TEXT NOT NULL,
  doc_type TEXT,
  doc_type_source TEXT,
  release TEXT,
  release_verified INTEGER,
  format_version INTEGER,
  last_build INTEGER,
  active_configuration TEXT,
  creation_time INTEGER,
  creation_source TEXT,
  folder_at_save TEXT,
  material TEXT,
  title TEXT,
  author TEXT,
  last_saved_by TEXT,
  keywords TEXT,
  comments TEXT,
  last_saved_utc TEXT,
  units TEXT,
  preview_mime TEXT,
  preview_width INTEGER,
  preview_height INTEGER,
  preview_bytes INTEGER,
  preview_sha256 TEXT,
  preview_stream TEXT,
  counts TEXT,
  warnings TEXT,
  references_state TEXT,
  doc_guid TEXT,
  doc_version INTEGER
);
CREATE INDEX documents_type ON documents (doc_type);
CREATE INDEX documents_guid ON documents (doc_guid) WHERE doc_guid IS NOT NULL;
CREATE INDEX documents_cut ON documents (references_state) WHERE references_state = 'truncated';

CREATE TABLE configurations (
  file INTEGER NOT NULL REFERENCES files ON DELETE CASCADE,
  position INTEGER NOT NULL,
  name TEXT NOT NULL,
  sw_id INTEGER,
  active INTEGER NOT NULL,
  most_recent INTEGER,
  comment TEXT,
  material TEXT,
  part_number TEXT NOT NULL,
  part_number_source TEXT NOT NULL,
  description TEXT,
  PRIMARY KEY (file, position)
) WITHOUT ROWID;

CREATE TABLE properties (
  file INTEGER NOT NULL REFERENCES files ON DELETE CASCADE,
  configuration TEXT,
  name TEXT NOT NULL,
  name_fold TEXT NOT NULL,
  type TEXT NOT NULL,
  text TEXT,
  value TEXT,
  expression TEXT,
  linked INTEGER NOT NULL
);
CREATE INDEX properties_file ON properties (file);
CREATE INDEX properties_name ON properties (name_fold, text COLLATE NOCASE);

CREATE TABLE refs (
  file INTEGER NOT NULL REFERENCES files ON DELETE CASCADE,
  key TEXT NOT NULL,
  position INTEGER NOT NULL,
  stored_path TEXT,
  file_name TEXT,
  name_fold TEXT,
  doc_type TEXT,
  direct INTEGER,
  virtual INTEGER NOT NULL,
  imported INTEGER NOT NULL,
  embedded TEXT,
  nested TEXT,
  stored_creation_time INTEGER,
  parent_documents INTEGER NOT NULL,
  nested_creation_time INTEGER,
  nested_identity_source TEXT,
  nested_identity_error TEXT,
  status TEXT,
  rule TEXT,
  confidence TEXT,
  identity TEXT,
  target INTEGER REFERENCES files ON DELETE SET NULL,
  warnings TEXT,
  resolved_scan INTEGER,
  doc_version INTEGER,
  PRIMARY KEY (file, key)
) WITHOUT ROWID;
CREATE INDEX refs_target ON refs (target) WHERE target IS NOT NULL;
CREATE INDEX refs_name ON refs (name_fold);
CREATE INDEX refs_unresolved ON refs (status) WHERE status IN ('missing', 'ambiguous', 'embedded_not_found');

CREATE TABLE ref_candidates (
  file INTEGER NOT NULL,
  key TEXT NOT NULL,
  candidate INTEGER NOT NULL REFERENCES files ON DELETE CASCADE,
  found_by TEXT NOT NULL,
  identity TEXT NOT NULL,
  FOREIGN KEY (file, key) REFERENCES refs ON DELETE CASCADE
);
CREATE INDEX ref_candidates_candidate ON ref_candidates (candidate);
CREATE INDEX ref_candidates_ref ON ref_candidates (file, key);

CREATE TABLE edges (
  file INTEGER NOT NULL REFERENCES files ON DELETE CASCADE,
  parent_key TEXT,
  parent_configuration TEXT,
  child_key TEXT NOT NULL,
  child_configuration TEXT,
  instances INTEGER NOT NULL,
  unsuppressed INTEGER NOT NULL,
  in_bom INTEGER NOT NULL,
  alternate_name TEXT
);
CREATE INDEX edges_child ON edges (file, child_key);

CREATE TABLE views (
  file INTEGER NOT NULL REFERENCES files ON DELETE CASCADE,
  position INTEGER NOT NULL,
  sheet TEXT,
  view TEXT,
  configuration TEXT,
  key TEXT
);
CREATE INDEX views_key ON views (file, key);

CREATE TABLE events (
  id INTEGER PRIMARY KEY,
  scan INTEGER NOT NULL,
  time_utc TEXT NOT NULL,
  kind TEXT NOT NULL,
  file INTEGER,
  root TEXT,
  rel TEXT,
  previous_root TEXT,
  previous_rel TEXT,
  size INTEGER,
  sha256 TEXT,
  previous_sha256 TEXT
);
CREATE INDEX events_time ON events (time_utc);
"""

# One row per document, rowid = files.id; made only where SQLite has FTS5.
SEARCH_TABLE = """
CREATE VIRTUAL TABLE search USING fts5(
  name, numbers, properties, configurations, folder,
  tokenize = 'unicode61 remove_diacritics 2', prefix = '2 3'
);
"""

PREVIEW_TABLES = """
CREATE TABLE previews (
  sha256 TEXT PRIMARY KEY,
  mime TEXT NOT NULL,
  width INTEGER,
  height INTEGER,
  data BLOB NOT NULL
) WITHOUT ROWID;
"""

# The tables a rebuild drops and makes again; meta and roots stay.
REBUILT = (
    "search",
    "events",
    "views",
    "edges",
    "ref_candidates",
    "refs",
    "properties",
    "configurations",
    "documents",
    "files",
    "folders",
    "scans",
)


def _statements(script: str) -> list[str]:
    return [s.strip() for s in script.split(";") if s.strip()]


def create(con, *, fts5: bool) -> None:
    """Make every table of a new catalog (inside the caller's transaction)."""
    for stmt in _statements(TABLES):
        con.execute(stmt)
    if fts5:
        con.execute(SEARCH_TABLE.strip().rstrip(";"))


def rebuild(con, *, fts5: bool) -> None:
    """Drop every table but ``meta`` and ``roots``, make them again and mark every root
    ``new``: the next scan reads everything again."""
    for name in REBUILT:
        con.execute(f"DROP TABLE IF EXISTS {name}")
    for stmt in _statements(TABLES):
        if stmt.startswith(("CREATE TABLE meta", "CREATE TABLE roots")):
            continue
        con.execute(stmt)
    if fts5:
        con.execute(SEARCH_TABLE.strip().rstrip(";"))
    con.execute("UPDATE roots SET state = 'new', partial = NULL, last_scan = NULL, last_complete_scan = NULL")


# The extensions of Alibre Design files, which version 2 reads again for their GUIDs.
_ALIBRE_EXTENSIONS = (".ad_prt", ".ad_asm", ".ad_smp")


def _version_2(con) -> None:
    """Version 1 to 2: an Alibre Design document's GUID and version (``documents``) and
    the version each of an Alibre assembly's references asks for (``refs``), which
    where-used of Alibre files resolves by. The Alibre files a version 1 catalog read
    are read again by the next scan; nothing else is."""
    con.execute("ALTER TABLE documents ADD COLUMN doc_guid TEXT")
    con.execute("ALTER TABLE documents ADD COLUMN doc_version INTEGER")
    con.execute("ALTER TABLE refs ADD COLUMN doc_version INTEGER")
    con.execute("CREATE INDEX documents_guid ON documents (doc_guid) WHERE doc_guid IS NOT NULL")
    marks = ",".join("?" * len(_ALIBRE_EXTENSIONS))
    con.execute(f"UPDATE files SET reader_revision = 0 WHERE ext IN ({marks})", _ALIBRE_EXTENSIONS)


# version -> the function that takes a database from that version to the next one, in place.
MIGRATIONS: dict[int, Callable[..., None]] = {1: _version_2}


__all__ = [
    "APPLICATION_ID",
    "MIGRATIONS",
    "MIN_READER_SCHEMA",
    "PREVIEWS_APPLICATION_ID",
    "PREVIEWS_VERSION",
    "PREVIEW_TABLES",
    "READER_REVISION",
    "SCHEMA_VERSION",
    "create",
    "rebuild",
]
