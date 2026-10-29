"""Component trees and drawing references against what SOLIDWORKS itself reported.

The fixture kit makes its documents through the SOLIDWORKS API and records, in
``ground_truth.json``, what SOLIDWORKS reported about each one: for every
assembly configuration the full component list (instance name, file,
referenced configuration, suppressed, hidden, excluded from BOM, virtual,
parent and ``IMathTransform.ArrayData`` in the top assembly's frame), and for
every drawing its sheets, views and bill-of-materials tables. These tests check
``Document.components()`` and ``reference_set()`` against it, instance by
instance in every configuration; ``test_ground_truth.py`` checks the 0.1
``references()`` list, properties, configurations, units and bodies.

Reference resolution is checked against the same records: the documents are
copied to a new folder, so every stored path is stale, and each referenced
file SOLIDWORKS reported must resolve to the copy of that file.

The path report is checked against the kit's own scrub expectations, which
``ground_truth.json`` records without naming anyone (template paths and names
only as SHA-256 of the lower-cased text): every path must be inherited from a
template the kit recorded, or lie in Windows, the SOLIDWORKS installation or
templates folder, the generating account's profile or the kit's output folder,
and every user name must be the generating account or a template author. The
report must also find what SOLIDWORKS says each document references, whole.

The documents and ``ground_truth.json`` are read from ``tests/fixtures``, where
they are committed, or from the folder in ``SOLIDSEAS_FIXTURES_DIR``, to check a
new kit output before it replaces them. A test skips, naming what is missing,
when ``ground_truth.json`` or a document it needs is not there. Nothing in the
folder is modified: a module guard checks sizes, times and hashes before and
after.
"""

import hashlib
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from solidseas import open_document
from solidseas.formats.solidworks.pathreport import USER_FIELDS
from solidseas.resolve import resolve_references
from solidseas.resolve.identity import own_identity
from solidseas.resolve.names import parse_stored_folder
from support import FIXTURES

FIXDIR = Path(os.environ.get("SOLIDSEAS_FIXTURES_DIR") or FIXTURES)
GT_PATH = FIXDIR / "ground_truth.json"
TOL = 1e-9
MISSING = f"{GT_PATH.name} is not in {FIXDIR}; set SOLIDSEAS_FIXTURES_DIR to a fixture kit output folder"


def _load() -> dict | None:
    try:
        gt = json.loads(GT_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    private = FIXDIR / "ground_truth.private.json"
    if private.is_file():  # the account fields the public copy leaves out (support.ground_truth)
        for key, value in json.loads(private.read_text(encoding="utf-8")).items():
            gt[key] = {**gt.get(key, {}), **value} if isinstance(value, dict) else value
    return gt


GT = _load()


def _entries(doc_type: str) -> list[str]:
    if GT is None:
        return []
    return [n for n, e in GT.items() if isinstance(e, dict) and e.get("type") == doc_type and e.get("api")]


def _params(values: list, ids=None):
    if GT is None:
        return [pytest.param(None, marks=pytest.mark.skip(reason=MISSING))]
    return [pytest.param(v, id=ids(v) if ids else None) for v in values]


ASSEMBLY_CONFIGS = [
    (name, cfg) for name in _entries("assembly") for cfg in GT[name]["api"].get("configurations") or {}
]
DRAWINGS = _entries("drawing")


def _need(name: str) -> Path:
    path = FIXDIR / name
    if not path.is_file():
        pytest.skip(f"{name} is not in {FIXDIR}")
    return path


def _snapshot() -> dict[str, tuple]:
    if not FIXDIR.is_dir():
        return {}
    return {
        p.name: (p.stat().st_size, p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
        for p in sorted(FIXDIR.iterdir())
        if p.is_file()
    }


@pytest.fixture(scope="module", autouse=True)
def fixture_folder_stays_unchanged():
    before = _snapshot()
    yield
    assert _snapshot() == before, f"a test changed a file in {FIXDIR}"


def _base(path: str | None) -> str:
    return (path or "").replace("\\", "/").rsplit("/", 1)[-1].casefold()


def _ancestors(node_id: str):
    parts = node_id.split("/")
    for k in range(1, len(parts)):
        yield "/".join(parts[:k])


# --------------------------------------------------------------------------- assemblies
def test_the_ground_truth_is_read():
    """Guards the sweeps below against passing because they found nothing to compare."""
    if GT is None:
        pytest.skip(MISSING)
    assert len(ASSEMBLY_CONFIGS) >= 3 and len(DRAWINGS) >= 1
    configs = [GT[a]["api"]["configurations"][c] for a, c in ASSEMBLY_CONFIGS]
    compared = sum(len(c.get("components") or []) for c in configs)
    assert compared >= 20


@pytest.mark.parametrize("item", _params(ASSEMBLY_CONFIGS, ids=lambda v: f"{v[0]}-{v[1]}"))
def test_every_instance_matches_solidworks(item):
    name, cfg = item
    comps = GT[name]["api"]["configurations"][cfg].get("components")
    assert comps, "the ground truth lists no components"
    with open_document(_need(name)) as doc:
        tree = doc.components(cfg)
    assert (tree.configuration, tree.children_state) == (cfg, "described")
    nodes = {n.id: n for n in tree.walk()}
    for c in comps:
        label = f"{name} {cfg} {c['name']}"
        node = nodes.get(c["name"])
        assert node is not None, f"{label}: not in the tree"
        f = tree.files[node.file]
        assert _base(f.file_name) == _base(c["file_name"]), label
        assert node.parent == c["parent"] and node.depth == c["depth"], label
        assert node.configuration == c["referenced_configuration"], label
        assert node.suppressed is c["suppressed"], label
        assert node.hidden is c["hidden"], label
        assert node.excluded_from_bom is c["exclude_from_bom"], label
        assert node.virtual is c["virtual"] and f.virtual is c["virtual"], label
        ad = c["transform_array_data"]  # rotation 0-8 (axis images), translation 9-11, scale 12
        p = node.placement
        assert p is not None, label
        for i in range(3):
            for j in range(3):
                assert abs(p.rotation[i][j] - ad[3 * j + i]) <= TOL, (label, i, j)
            assert abs(p.translation_m[i] - ad[9 + i]) <= TOL, (label, i)
        assert node.transform.scale == ad[12], label
    listed = {c["name"] for c in comps}
    by_name = {c["name"]: c for c in comps}
    for node_id, node in nodes.items():
        if node_id in listed:
            continue
        # SOLIDWORKS lists no children of a suppressed component; the tree still stores them.
        assert any(by_name.get(a, {}).get("suppressed") for a in _ancestors(node_id)), node_id
        assert tree.files[node.file].instances_unsuppressed < tree.files[node.file].instances


def test_the_hidden_comparison_is_not_vacuous():
    """The instance check above compares ``hidden`` with SOLIDWORKS, which proves the rule only
    if SOLIDWORKS reports some instance hidden. The fixtures' assemblies show every
    instance, so the rule that makes an instance hidden stays a HYPOTHESIS (docs/FORMAT.md
    12.1) until a kit with a hidden component exists (section 16, item 17)."""
    if GT is None:
        pytest.skip(MISSING)
    hidden = [
        (name, cfg, c["name"])
        for name, cfg in ASSEMBLY_CONFIGS
        for c in GT[name]["api"]["configurations"][cfg].get("components") or []
        if c["hidden"]
    ]
    if not hidden:
        pytest.skip("the fixtures report no hidden instance: the hidden rule is not checked against them")
    assert len(hidden) >= 1


@pytest.mark.parametrize("name", _params(_entries("assembly")))
def test_configurations_match_solidworks(name):
    api = GT[name]["api"]
    with open_document(_need(name)) as doc:
        tree = doc.components()
    assert sorted(tree.configurations_described) == sorted(api["configuration_names"])
    assert (tree.configuration, tree.configuration_source) == (api["active_configuration"], "active")


@pytest.mark.parametrize("name", _params(_entries("assembly")))
def test_direct_virtual_files_open_as_nested_documents(name):
    comps = GT[name]["api"]["configurations"][GT[name]["api"]["active_configuration"]]["components"]
    virtual = [c for c in comps if c["virtual"] and c["parent"] is None]
    if not virtual:
        pytest.skip(f"{name} has no direct virtual component")
    with open_document(_need(name)) as doc:
        tree = doc.components()
        nodes = {n.id: n for n in tree.walk()}
        for c in virtual:
            f = tree.files[nodes[c["name"]].file]
            assert (f.embedded, f.direct) == ("embedded", True) and f.nested, c["name"]
            expected = {".sldprt": "part", ".sldasm": "assembly"}[os.path.splitext(c["file_name"])[1].lower()]
            assert doc.nested(f.nested).doc_type == expected


def _bom_quantities(table: dict) -> list[tuple[str, int]]:
    qty = next(i for i, t in enumerate(table["column_titles"]) if "QTY" in t.upper())
    out = []
    for row in table["row_documents"]:
        if not row["documents"]:
            continue  # the header row
        (document,) = row["documents"]
        out.append((_base(document), int(table["cells"][row["row"]][qty])))
    return out


@pytest.mark.parametrize("name", _params(DRAWINGS))
def test_bill_of_materials_counts_match_solidworks(name):
    api = GT[name]["api"]
    tables = api.get("bom_tables") or []
    if not tables:
        pytest.skip(f"{name} has no bill of materials table")
    (model_name,) = {_base(v["referenced_document"]) for s in api["sheets"] for v in s["views"]}
    asm = next((n for n in _entries("assembly") if n.casefold() == model_name), None)
    if asm is None:
        pytest.skip(f"the ground truth does not describe {model_name}")
    with open_document(_need(asm)) as doc:
        for table in tables:
            cfg = table["bom_configuration"] or None  # empty: the configuration the view shows
            refs = doc.reference_set(cfg)
            tree = doc.components(cfg)
            by_name = {_base(f.file_name): f for f in refs.files.values()}
            rows = _bom_quantities(table)
            assert rows, "the table has no rows"
            if table["bom_type"] == 3:  # indented: every level, so per-file totals are in_bom counts
                totals: dict[str, int] = {}
                for doc_name, q in rows:
                    totals[doc_name] = totals.get(doc_name, 0) + q
                got = {n: f.instances_in_bom for n, f in by_name.items() if f.instances_in_bom}
                assert got == totals, table["bom_type_name"]
            else:  # top level only
                top: dict[str, int] = {}
                for node in tree.children:
                    if not node.suppressed and not node.excluded_from_bom:
                        key = _base(tree.files[node.file].file_name)
                        top[key] = top.get(key, 0) + 1
                assert top == dict(rows), table["bom_type_name"]


# --------------------------------------------------------------------------- drawings
@pytest.mark.parametrize("name", _params(DRAWINGS))
def test_drawing_models_sheets_and_views_match_solidworks(name):
    api = GT[name]["api"]
    with open_document(_need(name)) as doc:
        refs = doc.reference_set()
        assert doc.active_configuration is None and doc.components() is None
    assert [s.name for s in refs.sheets] == [s["name"] for s in api["sheets"]]
    for got, want in zip(refs.sheets, api["sheets"], strict=True):
        assert [(v.name, v.configuration, _base(v.file_name)) for v in got.views] == [
            (v["name"], v["referenced_configuration"], _base(v["referenced_document"])) for v in want["views"]
        ]
        assert all(v.file in refs.files for v in got.views)
    models = {_base(v["referenced_document"]) for s in api["sheets"] for v in s["views"]}
    assert {_base(f.file_name) for f in refs.files.values()} == models
    for f in refs.files.values():
        assert f.direct is None and f.sources[0] == "Header2" and f.instances is None
        used = [
            v["referenced_configuration"]
            for s in api["sheets"]
            for v in s["views"]
            if _base(v["referenced_document"]) == _base(f.file_name)
        ]
        assert list(f.configurations_used) == list(dict.fromkeys(used))


def _utc_seconds(text: str) -> int:
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())


# The drawing template SOLIDWORKS 2024 installs, data\templates\ansi.drwdot, known by the
# SHA-256 ground_truth.json records for it, stores 1196966037 (2007-12-06T18:33:57Z) as its
# identity. That value was read once from the installed template, read-only; the kit records
# the template's hash and file time but not the identity it stores.
ANSI_DRWDOT_SHA256 = "b33fef64aadd4e9c73966bff71d6602f9086e186d3b2b46e033a665f99639d3a"
ANSI_DRWDOT_IDENTITY = 1196966037
# No SOLIDWORKS document predates SOLIDWORKS: an identity before 1995 is 0 or another stand-in.
EARLIEST_IDENTITY = _utc_seconds("1995-01-01T00:00:00Z")


def test_a_drawings_identity_is_its_templates():
    """A part's or assembly's ``ModelStamps`` and ``KeyWords`` id are its creation time, but a
    drawing carries the identity stored in its drawing template instead (docs/FORMAT.md
    11.7): every drawing made from one template shares one identity, a lineage of the
    template. For any template the identity must be shared, a real time (not 0 or another
    stand-in), not the drawing's own, and no later than the template's file time. For the
    shipped ``ansi.drwdot``, which the committed drawings were made from, it must be exactly
    the value that template stores, 1196966037 (2007-12-06); its file time, 2024-01-17, is the
    installation's."""
    if GT is None:
        pytest.skip(MISSING)
    drawing_template = (GT["_generation"].get("templates") or {}).get("drawing") or {}
    template = drawing_template.get("last_write_utc")
    if len(DRAWINGS) < 2 or not template:
        pytest.skip("the ground truth records fewer than two drawings, or no drawing template")
    shipped = drawing_template.get("sha256") == ANSI_DRWDOT_SHA256
    if FIXDIR == FIXTURES:  # the committed drawings: a new template needs its own pinned value
        assert shipped, "the committed drawings no longer come from the shipped ansi.drwdot"
    compared = 0
    identities = set()
    for name in DRAWINGS:
        with open_document(_need(name)) as doc:
            ident = own_identity(doc)
            created = doc.fields.created_utc
        assert ident.source == "ModelStamps" and ident.creation_time is not None, name
        assert ident.error is None and not ident.skipped, name
        assert EARLIEST_IDENTITY <= ident.creation_time <= _utc_seconds(template), name
        assert abs(created.timestamp() - ident.creation_time) > 86_400, name  # not its own creation
        identities.add(ident.creation_time)
        compared += 1
    assert len(identities) == 1, "drawings made from one template carry different identities"
    if shipped:
        assert identities == {ANSI_DRWDOT_IDENTITY}
    for name in [*_entries("part"), *_entries("assembly")]:  # control: these carry their own
        with open_document(_need(name)) as doc:
            ident = own_identity(doc)
            created = doc.fields.created_utc
        if ident.creation_time is not None and created is not None:
            assert abs(created.timestamp() - ident.creation_time) <= 120, name
            compared += 1
    assert compared >= 3


# --------------------------------------------------------------------------- reference resolution
def _moved_copy(tmp_path: Path) -> Path:
    """Every document the ground truth describes, copied to a folder of its own."""
    dst = tmp_path / "Moved" / "Kit"
    dst.mkdir(parents=True)
    for name in [*_entries("part"), *_entries("assembly"), *_entries("drawing")]:
        shutil.copy2(_need(name), dst / name)
    return dst


@pytest.mark.parametrize("name", _params([*_entries("assembly"), *DRAWINGS]))
def test_references_resolve_to_the_files_solidworks_reported(tmp_path, name):
    api = GT[name]["api"]
    if GT[name]["type"] == "drawing":
        wanted = [(_base(v["referenced_document"]), False) for s in api["sheets"] for v in s["views"]]
    else:
        wanted = [
            (_base(c["file_name"]), c["virtual"])
            for cfg in api["configurations"].values()
            for c in cfg.get("components") or []
        ]
    assert wanted, "the ground truth lists no referenced file"
    kit = _moved_copy(tmp_path)
    with open_document(kit / name) as doc:
        keys = {_base(f.file_name): k for k, f in doc.reference_set().files.items()}
        # the stored paths name where the kit was made: only the copy may be consulted
        res = resolve_references(doc, allow_outside_roots=False)
        # a document that stored the folder it was saved in is rebased from it
        rule = "rebased" if parse_stored_folder(doc.metadata.summary.get("folder_at_save")) else "same_folder"
    compared = 0
    for file_name, virtual in dict.fromkeys(wanted):
        r = res.results[keys[file_name]]
        if virtual:
            assert (r.status, r.identity) == ("embedded", "match") and r.nested, file_name
        else:
            assert (r.status, r.identity, r.confidence) == ("moved", "match", "high"), (file_name, r)
            assert r.rule == rule and r.match.root == "document", (file_name, r.rule)
            assert _base(r.match.path) == file_name, file_name
        compared += 1
    assert compared >= 1 and not res.index_partial


# --------------------------------------------------------------------------- the path report
NATIVES = [n for n in (GT or {}) if os.path.splitext(n)[1].lower() in (".sldprt", ".sldasm", ".slddrw")]


def _text_hash(text: str) -> str:
    """SHA-256 of the lower-cased text, as the kit stores template paths and names."""
    return hashlib.sha256(text.lower().encode("utf-8")).hexdigest()


def _under(path: str, folder: str) -> bool:
    folder = folder if folder.endswith("\\") else folder + "\\"
    return path == folder.rstrip("\\") or path.startswith(folder)


class _Scrub:
    """The kit's scrub expectations, read from ``ground_truth.json``."""

    def __init__(self, gt: dict) -> None:
        gen = gt["_generation"]
        keys = ("windows_account", "profile_folder_name", "profile_folder_short_name")
        self.accounts = {(gen.get(k) or "").casefold() for k in keys} - {""}
        self.template_paths: set[str] = set()
        self.template_names: set[str] = set()
        # the hashes of the paths and names stored in the templates are kept in the
        # private overlay (scripts/split-ground-truth.py): they include the account's own
        for t in (gt.get("_template_hashes") or {}).values():
            if isinstance(t, dict):
                self.template_paths.update(t.get("embedded_path_sha256") or [])
                self.template_names.update(t.get("name_sha256") or [])
        self.output = (gen.get("output_folder") or "").replace("/", "\\").casefold()

    def path_ok(self, path: str) -> bool:
        q = path.replace("/", "\\").casefold()
        return (
            _text_hash(path.replace("/", "\\")) in self.template_paths
            or re.fullmatch(r"c:\\windows\\(system32\\)?", q) is not None
            or _under(q, "c:\\program files\\solidworks corp\\solidworks\\")
            or _under(q, "c:\\programdata\\solidworks\\solidworks 2024\\templates\\")
            or any(_under(q, f"c:\\users\\{a}\\") for a in self.accounts)
            or bool(self.output and _under(q, self.output))
        )

    def template_author(self, name: str) -> bool:
        return _text_hash(name) in self.template_names


def _report(name: str):
    with open_document(_need(name)) as doc:
        return doc.path_report()


def test_the_kit_records_its_scrub_expectations():
    if GT is None:
        pytest.skip(MISSING)
    scrub = _Scrub(GT)
    assert scrub.accounts and scrub.output and len(scrub.template_paths) >= 5 and scrub.template_names
    assert len(NATIVES) >= 10


@pytest.mark.parametrize("name", _params(NATIVES))
def test_the_path_report_meets_the_kits_scrub_expectations(name):
    """What the kit's own audit allows, applied to the report, which reads more than the
    byte scan the audit used: nested documents, non-ASCII text and the structured carriers."""
    scrub = _Scrub(GT)
    rep = _report(name)
    assert rep.complete and len(rep.paths) >= 5
    assert [p.path for p in rep.paths if not scrub.path_ok(p.path)] == []
    accounts = {a.name.casefold(): a for a in rep.accounts}
    # SOLIDWORKS writes the saving account's temp folder into every document it saves
    mine = [a for k, a in accounts.items() if k in scrub.accounts]
    assert mine and any("path" in a.sources for a in mine), "the generating account is not reported"
    for key, a in accounts.items():
        if key in scrub.accounts:
            assert not a.inherited_likely, a.name
        else:  # anyone else came with a template, and is only in its history
            assert scrub.template_author(a.name) and a.inherited_likely and a.severity == "medium", key
    for f in rep.identity_fields:
        if f.field in USER_FIELDS:
            assert f.value.casefold() in scrub.accounts or scrub.template_author(f.value), f.field
    # the document's own path at a save is where it was saved, never one of its references
    for p in rep.paths:
        if _base(p.path) == name.casefold():
            assert "save_location" in p.roles and "references" not in p.roles, p.roles


def test_the_save_location_is_the_kits_output_folder():
    if GT is None:
        pytest.skip(MISSING)
    scrub = _Scrub(GT)
    compared = 0
    for name in NATIVES:
        for p in _report(name).paths:
            own = [loc for loc in p.locations if loc.nested == () and "save_folder" in p.sources]
            if own and "save_location" in p.roles:
                assert p.path.replace("/", "\\").casefold().rstrip("\\") == scrub.output.rstrip("\\"), name
                compared += 1
    assert compared >= 1, "no fixture stored the folder it was saved in"


def _referenced_names(name: str) -> set[str]:
    api = GT[name]["api"]
    if GT[name]["type"] == "drawing":
        return {v["referenced_document"] for s in api["sheets"] for v in s["views"]}
    return {c["file_name"] for cfg in api["configurations"].values() for c in cfg.get("components") or []}


@pytest.mark.parametrize("name", _params([*_entries("assembly"), *DRAWINGS]))
def test_the_path_report_names_every_file_solidworks_reported(name):
    wanted = _referenced_names(name)
    assert wanted, "the ground truth lists no referenced file"
    rep = _report(name)
    refs = [p for p in rep.paths if "references" in p.roles]
    for file_name in wanted:
        hits = [p for p in refs if _base(p.path) == file_name.casefold()]
        assert hits, file_name
        # read whole: no path is the same one cut short inside its file name, as the ASCII
        # scan of 0.1 cut a name at its first non-ASCII character
        for h in hits:
            folded = h.path.casefold()
            cut = [
                p.path
                for p in rep.paths
                if len(p.path) < len(h.path)
                and folded.startswith(p.path.casefold())
                and not p.path.endswith("\\")
                and folded[len(p.path)] != "\\"
            ]
            assert cut == [], file_name


def test_non_ascii_file_names_are_read_whole():
    if GT is None:
        pytest.skip(MISSING)
    names = [n for n in NATIVES if not n.isascii()]
    if not names:
        pytest.skip("the fixture kit made no document with a non-ASCII name")
    for target in names:
        documents = [
            n for n in NATIVES if any(_base(p.path) == target.casefold() for p in _report(n).paths)
        ]
        referencing = [n for n in [*_entries("assembly"), *DRAWINGS] if target in _referenced_names(n)]
        assert referencing and set(referencing) <= set(documents), target


@pytest.mark.parametrize("name", _params(_entries("assembly")))
def test_a_virtual_components_own_document_is_read(name):
    comps = [c for cfg in GT[name]["api"]["configurations"].values() for c in cfg.get("components") or []]
    if not any(c["virtual"] for c in comps):
        pytest.skip(f"{name} has no virtual component")
    rep = _report(name)
    assert len(rep.documents) >= 2 and rep.complete
    nested = [p for p in rep.paths if any(loc.nested for loc in p.locations)]
    assert any("save_location" in p.roles for p in nested)
    assert any(f.location.nested for f in rep.identity_fields)


def test_the_public_ground_truth_holds_no_template_path_or_name_hashes():
    """An unsalted hash of a short name is confirmed by one guess, and the templates store
    the generating account's own folders and name: their hashes stay in the private overlay."""
    if not GT_PATH.is_file():
        pytest.skip(MISSING)
    public = json.loads(GT_PATH.read_text(encoding="utf-8"))
    for name, entry in (public["_generation"].get("templates") or {}).items():
        if isinstance(entry, dict):
            assert not {"embedded_path_sha256", "name_sha256"} & set(entry), name
