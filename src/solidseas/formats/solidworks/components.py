"""Assembly component trees, the files they reference, and drawing sheets.

The tree is ``swXmlContents/COMPINSTANCETREE`` (legacy: ``COMPINSTANCETREE__ZLB``),
parsed by :func:`.metadata.parse_sw_tree`. ``docs/API.md`` section 5.9 has the
JSON shapes; this module builds the Python objects behind them.

* Every referenced document is one ``swFile``; its ``id`` is the file key
  (``docs/API.md`` C7), the same in ``components``, ``references`` and every
  resolution result.
* Each assembly configuration has a top ``swModel`` holding that configuration's
  instances (``swReference``). A referenced document has a ``swModel`` per
  configuration it is used in, and a sub-assembly's model holds its own
  instances, so the top document's tree describes the whole hierarchy.
* ``swTransform`` is 16 numbers. Elements 0 to 2, 4 to 6 and 8 to 10 are the
  images of the component's X, Y and Z axes in its parent's frame (the columns
  of the rotation ``R`` in ``p_parent = R p + t``), elements 12 to 14 are the
  translation ``t`` in metres, element 15 a scale and elements 3, 7 and 11
  zero. Read as a 4 x 4 matrix stored row by row, it is the row-vector form
  ``p_parent = p M``. Each transform is relative to the parent instance; the
  placement in the top assembly is the parents' placements composed with it.
  VERIFIED against the ``IMathTransform.ArrayData`` SOLIDWORKS 2024 reported for
  every instance of fixtures o08, o15 and o16 (rotations of 90 degrees about X
  and about Z, 40 degrees about (1, 1, 1), and a part inside a rotated
  sub-assembly): ArrayData holds the same numbers without elements 3, 7 and 11.
  On the development corpus all 8,688 stored transforms are proper rotations
  with elements 3, 7 and 11 zero and element 15 equal to 1, so the scale is
  reported but never applied.
* ``hidden`` is meant to be what SOLIDWORKS reports, not the raw ``swHidden``
  flag; how far that is checked is in :func:`.metadata.parse_sw_tree`.

Virtual components are documents stored inside the assembly as nested
documents. A virtual file used directly by the top assembly is the stream
``VirtualComp/<stored name before the caret>``, or that name followed by ``-``
and the extension without its dot (``VirtualComp/Part12-sldprt``, as
SOLIDWORKS 2024 writes it): 125 of the 129 direct virtual files on the
development corpus map this way (120 and 5), and each of the 125 opens as a
document of the stored type. HYPOTHESIS beyond that measurement. A virtual
file used only inside a sub-assembly is stored in that sub-assembly's own file
(``embedded_in_subassembly``). An imported component (``swImportedPath`` on its
``swFile``) is the stream ``ImportedComp/<stored file name>`` when that exists
(``docs/FORMAT.md`` 12.4 has the corpus counts). HYPOTHESIS.

Drawings have no tree. Their models are the ``Header2`` paths (provisional:
``direct`` is null), their sheets are ``SheetPreviews/SheetNames`` (a u16 count
and that many CStrings; it agrees with ``SW-Total Sheets`` in 22 of 22 corpus
drawings) and each sheet's views are the ``View`` children of the matching
``Sheet`` element in ``swXmlContents/KeyWords``: the view name, the model's
configuration in ``Description`` and the model's file name as text (57 of 57
corpus views name a ``Header2`` model; their count equals the
``SW-Config-Model-View-Sheet-List`` count in 22 of 22). Sheets, views and models
are VERIFIED against SOLIDWORKS on fixtures o18 and o19 only, so a HYPOTHESIS for
multi-sheet and multi-model drawings, which the corpus does not have. The view's
configuration is a HYPOTHESIS: every view on the fixtures shows ``Default``, the model's
active and first configuration (o16, which o19 shows, also has ``Lite``, which no view
shows), and every corpus view whose model could be checked (42 of 57) shows ``Default`` of
a model that has only that one, so a constant would match as well.
"""

import math
import os
import re
import struct
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from typing import Any

from ...errors import InvalidArgumentError, ReaderWarning
from .metadata import _local, _parse_xml, _read, basename_lower, read_cstring

DEFAULT_MAX_NODES = 10_000
DEFAULT_MAX_DEPTH = 32
MAX_NODES_LIMIT = 1_000_000
MAX_DEPTH_LIMIT = 64  # keeps the nested JSON well inside the encoder's nesting limit
# reference_set expands every configuration: all of them together build at most this many
# instances (the corpus needs at most a few thousand), so a file with thousands of
# configurations cannot multiply the work.
MAX_REFERENCE_SET_NODES = 100_000
TREE_STREAM = "swXmlContents/COMPINSTANCETREE"
SHEET_NAMES_STREAM = "SheetPreviews/SheetNames"
KEYWORDS_STREAM = "swXmlContents/KeyWords"
DOC_TYPES = {"PART": "part", "ASSEMBLY": "assembly"}
CHILDREN_STATES = ("none", "described", "truncated", "cycle", "unknown")
_MAX_TRANSFORM_TEXT = 2000
_ID_ESCAPES = {"%": "%25", "/": "%2F", "#": "%23"}
_ID_SPECIAL = re.compile("[%/#]")

Vec3 = tuple[float, float, float]
Mat3 = tuple[Vec3, Vec3, Vec3]


# --------------------------------------------------------------------------- placements
@dataclass(frozen=True)
class Placement:
    """Where a component sits: a point ``p`` of the component is at
    ``rotation @ p + translation_m`` in the other frame (column vectors, metres).
    ``rotation`` is given row by row."""

    rotation: Mat3
    translation_m: Vec3

    def apply(self, point: Sequence[float]) -> Vec3:
        """``point`` (component coordinates, metres) in the other frame."""
        r, t = self.rotation, self.translation_m
        x, y, z = point
        return (
            r[0][0] * x + r[0][1] * y + r[0][2] * z + t[0],
            r[1][0] * x + r[1][1] * y + r[1][2] * z + t[1],
            r[2][0] * x + r[2][1] * y + r[2][2] * z + t[2],
        )

    def then(self, inner: "Placement") -> "Placement":
        """``inner``, a placement in this component's own frame, seen from this
        placement's frame: rotations multiply and the translation is carried."""
        a, b = self.rotation, inner.rotation
        rot = tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))
        return Placement(rot, self.apply(inner.translation_m))  # type: ignore[arg-type]

    def is_finite(self) -> bool:
        return all(math.isfinite(v) for row in self.rotation for v in row) and all(
            math.isfinite(v) for v in self.translation_m
        )


IDENTITY = Placement(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), (0.0, 0.0, 0.0))


@dataclass(frozen=True)
class Transform(Placement):
    """An instance's stored ``swTransform``, relative to its parent instance: the 16
    stored numbers, the decoded rotation and translation, and element 15 (a scale,
    1 on every corpus instance, reported but not applied)."""

    stored: tuple[float, ...] = ()
    scale: float = 1.0

    @classmethod
    def from_stored(cls, s: Sequence[float]) -> "Transform":
        rotation = ((s[0], s[4], s[8]), (s[1], s[5], s[9]), (s[2], s[6], s[10]))
        return cls(rotation, (s[12], s[13], s[14]), tuple(s), s[15])


def parse_transform(text: Any) -> Transform | None:
    """The stored ``swTransform`` text as a :class:`Transform`, or None unless it is
    exactly 16 finite numbers."""
    if not isinstance(text, str) or len(text) > _MAX_TRANSFORM_TEXT:
        return None
    parts = text.split()
    if len(parts) != 16:
        return None
    try:
        values = [float(p) for p in parts]
    except ValueError:
        return None
    if not all(math.isfinite(v) for v in values):
        return None
    return Transform.from_stored(values)


Box = tuple[Vec3, Vec3]


def parse_bounding_box(text: Any) -> Box | None:
    """A model's stored ``swBoundingBox`` as ``(low corner, high corner)``, in metres and
    in that model's own coordinates (``docs/FORMAT.md`` 12.1), or None unless it is
    exactly six finite numbers with each low end at most its high end."""
    if not isinstance(text, str) or len(text) > _MAX_TRANSFORM_TEXT:
        return None
    parts = text.split()
    if len(parts) != 6:
        return None
    try:
        v = [float(p) for p in parts]
    except ValueError:
        return None
    if not all(math.isfinite(x) for x in v) or any(v[i] > v[3 + i] for i in range(3)):
        return None
    return (v[0], v[1], v[2]), (v[3], v[4], v[5])


# --------------------------------------------------------------------------- tree objects
@dataclass(frozen=True)
class ConfigurationCounts:
    """How many instances of one file one assembly configuration has."""

    configuration: str
    instances: int
    instances_unsuppressed: int
    instances_in_bom: int


@dataclass(frozen=True)
class ComponentFile:
    """One referenced document. ``key`` is its ``swFile`` id (``header2:<n>`` when only
    ``Header2`` names it). Instance counts are for one assembly configuration,
    expanded through sub-assemblies, and None when unknown (no component tree)."""

    key: str
    stored_path: str | None
    file_name: str | None
    doc_type: str | None
    direct: bool | None
    virtual: bool
    imported: bool
    nested: str | None
    embedded: str | None
    embedded_in_subassembly: bool
    configurations_used: tuple[str | None, ...]
    instances: int | None
    instances_unsuppressed: int | None
    instances_in_bom: int | None
    sources: tuple[str, ...]
    per_configuration: tuple[ConfigurationCounts, ...] | None = None
    resolution: dict[str, Any] | None = None


@dataclass(frozen=True)
class ComponentNode:
    """One component instance.

    ``id`` is the instance names from the top joined by ``/``; ``%``, ``/`` and
    ``#`` inside a name are percent-encoded, and a name repeated under one parent
    gets ``#2``, ``#3``... ``transform`` is the stored transform (relative to the
    parent instance) and ``placement`` the instance in the top assembly's frame;
    both are None when a stored transform on the way is unreadable.
    ``children_state`` is ``none`` (a part), ``described``, ``truncated`` (a
    limit stopped the expansion here), ``cycle`` (the model is already on the
    path) or ``unknown`` (the tree names a model it does not hold).
    ``alternate_name`` is the alternate name the tree stores for the file's
    configuration the instance uses (``swConfigurationAlternateName`` of its
    model), which SOLIDWORKS can show as the part number in a BOM, or None when it
    stores none (``docs/FORMAT.md`` 12.7).
    """

    id: str
    parent: str | None
    name: str
    component: str | None
    number: int | None
    depth: int
    file: str | None
    doc_type: str | None
    configuration: str | None
    suppressed: bool
    hidden: bool
    excluded_from_bom: bool
    virtual: bool
    transform: Transform | None
    placement: Placement | None
    children_state: str
    children: tuple["ComponentNode", ...]
    alternate_name: str | None = None


@dataclass(frozen=True)
class ComponentTree:
    """The component tree of one assembly configuration.

    ``configuration_source`` says how the configuration was chosen:
    ``requested``, ``active``, ``most_recent``, ``first`` or ``none``.
    ``children_state`` is ``described``, or ``unknown`` when the file has no
    component tree (its ``files`` then come from ``Header2``) or the tree has
    no component list for the configuration. ``files`` holds the files the
    described instances use, in first-seen order. ``truncated`` is True when
    ``max_nodes`` or ``max_depth`` stopped the expansion.
    """

    configuration: str | None
    configuration_source: str
    configurations_described: tuple[str, ...]
    children_state: str
    files: dict[str, ComponentFile]
    children: tuple[ComponentNode, ...]
    truncated: bool
    node_count: int
    depth: int
    max_nodes: int
    max_depth: int
    warnings: tuple[ReaderWarning, ...]

    def walk(self) -> Iterator[ComponentNode]:
        """Every instance, depth first, in stored order."""
        stack = list(reversed(self.children))
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(node.children))


@dataclass(frozen=True)
class DrawingView:
    """A drawing view: its name, the model's configuration and file name as the
    drawing stores them, and the key of that model in the references (or None)."""

    name: str | None
    configuration: str | None
    file_name: str | None
    file: str | None


@dataclass(frozen=True)
class DrawingSheet:
    name: str
    views: tuple[DrawingView, ...]


@dataclass(frozen=True)
class ReferenceSet:
    """Every file a document references, across all its configurations. ``files``
    carry the instance counts of ``configuration`` and ``per_configuration``
    counts; ``sheets`` is the list of a drawing's sheets, None for other types."""

    configuration: str | None
    configuration_source: str
    configurations_described: tuple[str, ...]
    children_state: str
    truncated: bool
    files: dict[str, ComponentFile]
    sheets: tuple[DrawingSheet, ...] | None
    warnings: tuple[ReaderWarning, ...]


# --------------------------------------------------------------------------- helpers
def _file_name(path: str | None) -> str | None:
    if not path:
        return None
    return path.replace("\\", "/").rsplit("/", 1)[-1] or None


def _number(text: Any) -> int | None:
    if isinstance(text, str) and text.isascii() and text.isdigit() and len(text) <= 15:
        return int(text)
    return None


def _escape(name: str) -> str:
    return _ID_SPECIAL.sub(lambda m: _ID_ESCAPES[m.group()], name)


def _check_limits(max_nodes: Any, max_depth: Any) -> None:
    for value, low, high, param in (
        (max_nodes, 1, MAX_NODES_LIMIT, "max_nodes"),
        (max_depth, 1, MAX_DEPTH_LIMIT, "max_depth"),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise InvalidArgumentError(
                f"{param} must be a whole number from {low} to {high}", detail={"parameter": param}
            )


def header2_paths(md, own_name: str | None) -> list[str]:
    """The ``Header2`` paths that name referenced documents: not the document's own
    name, and for a drawing not other drawings."""
    out = []
    own = basename_lower(own_name)
    for p in (md.header2 or {}).get("ext_paths", []):
        if own and basename_lower(p) == own:
            continue
        if md.doc_type == "drawing" and p.lower().endswith(".slddrw"):
            continue
        out.append(p)
    return out


class _Index:
    """The parsed tree, indexed once per document: models, instances by parent,
    and what holds for each file across every configuration."""

    def __init__(self, doc) -> None:
        md = doc.metadata
        tree = md.tree or {}
        self.md = md
        self.files: dict[str, dict] = tree.get("files", {})
        self.models: dict[str, dict] = tree.get("models", {})
        self.own = md.own_file_ids
        self.by_parent: dict[str | None, list[dict]] = {}
        refs = tree.get("refs", [])
        for r in refs:
            self.by_parent.setdefault(r["parent_model"], []).append(r)
        top_models = {mid for mid, m in self.models.items() if m.get("file_ref") in self.own}
        self.configs = [
            c
            for c in tree.get("configs", [])
            if c.get("name") is not None and c.get("model_ref") in self.models
        ]
        # A tree stream that parses to nothing (damaged) counts as no tree: Header2 is used.
        self.has_tree = bool(refs) or bool(self.configs)
        self.direct: dict[str, bool] = {}
        self.virtual: dict[str, bool] = {}
        self.used: dict[str, list[str | None]] = {}
        for r in refs:
            key = self.key_of(r)
            if key is None:
                continue
            self.direct[key] = self.direct.get(key, False) or r["parent_model"] in top_models
            self.virtual[key] = self.virtual.get(key, False) or r["virtual"]
            used = self.used.setdefault(key, [])
            if r["config"] not in used:
                used.append(r["config"])
        self.header2_names = {basename_lower(p) for p in (md.header2 or {}).get("ext_paths", [])}
        self.nested = self._map_nested(doc.nested_documents())

    def key_of(self, r: dict) -> str | None:
        fid = self.models.get(r["model_ref"], {}).get("file_ref")
        if fid is None or fid not in self.files or fid in self.own:
            return None
        return fid

    def _map_nested(self, names: list[str]) -> dict[str, str]:
        """file key -> the nested-document stream that holds it, one stream per file."""
        out: dict[str, str] = {}
        taken: set[str] = set()
        exact = set(names)
        folded: dict[str, list[str]] = {}
        for n in names:
            folded.setdefault(n.casefold(), []).append(n)

        def pick(candidates: list[str]) -> str | None:
            for cand in candidates:
                if cand in exact and cand not in taken:
                    return cand
            for cand in candidates:
                free = [n for n in folded.get(cand.casefold(), ()) if n not in taken]
                if len(free) == 1:
                    return free[0]
            return None

        for key, f in self.files.items():
            if key not in self.direct:
                continue
            base = _file_name(f.get("path")) or ""
            hit = None
            if self.virtual.get(key) and self.direct.get(key) and base:
                stem, ext = os.path.splitext(base)
                head = stem.split("^", 1)[0]
                cands = [f"VirtualComp/{head}-{ext[1:].lower()}"] if ext else []
                hit = pick([*cands, f"VirtualComp/{head}"])
            elif f.get("imported") and not self.virtual.get(key) and base:
                hit = pick([f"ImportedComp/{base}"])
            if hit is not None:
                out[key] = hit
                taken.add(hit)
        return out

    def file_object(self, key: str, acc: "_Acc | None", per: tuple | None = None) -> ComponentFile:
        f = self.files[key]
        path = f.get("path")
        virtual = self.virtual.get(key, False)
        direct = self.direct.get(key, False)
        nested = self.nested.get(key)
        if virtual and not direct:
            embedded = "embedded_in_subassembly"
        elif virtual:
            embedded = "embedded" if nested else "embedded_not_found"
        else:
            embedded = "embedded" if nested else None
        sources = [TREE_STREAM]
        if path and basename_lower(path) in self.header2_names:
            sources.append("Header2")
        return ComponentFile(
            key=key,
            stored_path=path,
            file_name=_file_name(path),
            doc_type=DOC_TYPES.get(f.get("doc_type") or ""),
            direct=direct,
            virtual=virtual,
            imported=bool(f.get("imported")),
            nested=nested,
            embedded=embedded,
            embedded_in_subassembly=virtual and not direct,
            configurations_used=tuple(acc.used if acc is not None else self.used.get(key, [])),
            instances=acc.instances if acc is not None else 0,
            instances_unsuppressed=acc.unsuppressed if acc is not None else 0,
            instances_in_bom=acc.in_bom if acc is not None else 0,
            sources=tuple(sources),
            per_configuration=per,
        )

    def choose(self, doc, configuration: str | None) -> tuple[dict | None, str | None, str]:
        """``(tree configuration, name, source)`` for a request; the tree
        configuration is None when the tree describes none by that name."""
        if configuration is not None:
            if not isinstance(configuration, str):
                raise InvalidArgumentError(
                    "a configuration name is a string", detail={"parameter": "configuration"}
                )
            exact = [c for c in self.configs if c["name"] == configuration]
            folded = [c for c in self.configs if c["name"].casefold() == configuration.casefold()]
            match = exact[0] if exact else (folded[0] if len(folded) == 1 else None)
            if match is not None:
                return match, match["name"], "requested"
            known = doc.configuration(configuration)  # raises for a name no carrier knows
            return None, known.name if known is not None else configuration, "requested"
        active = self.md.active_configuration
        for c in self.configs:
            if active is not None and c["name"] == active:
                return c, c["name"], "active"
        for c in self.configs:
            if c.get("most_recent"):
                return c, c["name"], "most_recent"
        if self.configs:
            return self.configs[0], self.configs[0]["name"], "first"
        if active is not None:
            return None, active, "active"
        return None, None, "none"


class _Acc:
    __slots__ = ("instances", "unsuppressed", "in_bom", "used")

    def __init__(self) -> None:
        self.instances = self.unsuppressed = self.in_bom = 0
        self.used: list[str | None] = []


class _Expansion:
    """One configuration expanded into nodes, bounded by ``max_nodes`` and ``max_depth``."""

    def __init__(self, index: _Index, max_nodes: int, max_depth: int) -> None:
        self.index = index
        self.max_nodes, self.max_depth = max_nodes, max_depth
        self.count = 0
        self.depth = 0
        self.truncated = False
        self.acc: dict[str, _Acc] = {}
        self.bad_transforms: list[str] = []
        self.bad_placements: list[str] = []
        self.duplicates: list[str] = []
        self.missing_models: list[str] = []
        self.children: tuple[ComponentNode, ...] = ()

    def run(self, top_model: str) -> "_Expansion":
        kids, _cut = self._children(top_model, None, IDENTITY, 1, frozenset((top_model,)), False, False)
        self.children = tuple(kids)
        return self

    def _children(self, model_id, parent_id, parent_place, depth, stack, anc_sup, anc_exc):
        out: list[ComponentNode] = []
        names: dict[str, int] = {}
        for r in self.index.by_parent.get(model_id, ()):
            if self.count >= self.max_nodes:
                self.truncated = True
                return out, True
            self.count += 1
            self.depth = max(self.depth, depth)
            out.append(self._node(r, parent_id, parent_place, depth, stack, anc_sup, anc_exc, names))
        return out, False

    def _node(self, r, parent_id, parent_place, depth, stack, anc_sup, anc_exc, names) -> ComponentNode:
        index = self.index
        component = r["name"]
        number_text = r["number"]
        name = f"{component or ''}-{number_text}" if number_text is not None else (component or "")
        local = _escape(name)
        seen = names.get(local, 0) + 1
        names[local] = seen
        if seen > 1:
            local = f"{local}#{seen}"
            self.duplicates.append(local)
        node_id = local if parent_id is None else f"{parent_id}/{local}"
        model = index.models.get(r["model_ref"])
        key = index.key_of(r)
        doc_type = DOC_TYPES.get(index.files[key].get("doc_type") or "") if key is not None else None
        transform = parse_transform(r["transform"])
        placement = None
        if transform is None:
            self.bad_transforms.append(node_id)
        elif parent_place is not None:
            placement = parent_place.then(transform)
            if not placement.is_finite():
                placement = None
                self.bad_placements.append(node_id)
        suppressed = anc_sup or r["suppressed"]
        excluded = anc_exc or r["exclude_from_bom"]
        if key is not None:
            acc = self.acc.get(key)
            if acc is None:
                acc = self.acc[key] = _Acc()
            acc.instances += 1
            acc.unsuppressed += not suppressed
            acc.in_bom += not suppressed and not excluded
            if r["config"] not in acc.used:
                acc.used.append(r["config"])
        children: tuple[ComponentNode, ...] = ()
        child_refs = index.by_parent.get(r["model_ref"]) if model is not None else None
        if model is None:
            state = "unknown"
            self.missing_models.append(node_id)
        elif not child_refs:
            state = "described" if doc_type == "assembly" else "none"
        elif r["model_ref"] in stack:
            state = "cycle"
        elif depth >= self.max_depth:
            state = "truncated"
            self.truncated = True
        else:
            kids, cut = self._children(
                r["model_ref"], node_id, placement, depth + 1, stack | {r["model_ref"]}, suppressed, excluded
            )
            children = tuple(kids)
            state = "truncated" if cut else "described"
        return ComponentNode(
            id=node_id,
            parent=parent_id,
            name=name,
            component=component,
            number=_number(number_text),
            depth=depth,
            file=key,
            doc_type=doc_type,
            configuration=r["config"],
            suppressed=bool(r["suppressed"]),
            hidden=bool(r["hidden"]),
            excluded_from_bom=bool(r["exclude_from_bom"]),
            virtual=bool(r["virtual"]),
            transform=transform,
            placement=placement,
            children_state=state,
            children=children,
            alternate_name=(model or {}).get("alternate_name") or None,
        )

    def warnings(self) -> list[ReaderWarning]:
        out = []

        def note(items: list[str], code: str, text: str) -> None:
            if items:
                out.append(ReaderWarning(code, f"{len(items)} {text} (first: {items[0]})", TREE_STREAM))

        note(
            self.bad_transforms,
            "transform_unreadable",
            "instances store a transform that is not 16 finite numbers; "
            "their transform and placement are null",
        )
        note(
            self.bad_placements,
            "non_finite_number",
            "instances have a placement in the top assembly that is not finite; it is null",
        )
        note(self.duplicates, "duplicate_instance_name", "instances repeat a name under their parent")
        note(self.missing_models, "component_model_missing", "instances name a model the tree does not hold")
        return out


def _reader_warnings(doc, streams: tuple[str, ...]) -> list[ReaderWarning]:
    return [w for w in doc.metadata.warnings if isinstance(w, ReaderWarning) and w.stream in streams]


def _header2_files(doc) -> dict[str, ComponentFile]:
    out = {}
    for n, p in enumerate(header2_paths(doc.metadata, doc.name), start=1):
        key = f"header2:{n}"
        out[key] = ComponentFile(
            key=key,
            stored_path=p,
            file_name=_file_name(p),
            doc_type=None,
            direct=None,
            virtual=False,
            imported=False,
            nested=None,
            embedded=None,
            embedded_in_subassembly=False,
            configurations_used=(),
            instances=None,
            instances_unsuppressed=None,
            instances_in_bom=None,
            sources=("Header2",),
        )
    return out


# --------------------------------------------------------------------------- public builders
def component_tree(
    doc,
    configuration: str | None = None,
    *,
    max_nodes: int = DEFAULT_MAX_NODES,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> ComponentTree:
    """The component tree of an assembly configuration (``Document.components``)."""
    _check_limits(max_nodes, max_depth)
    index = _Index(doc)
    described = tuple(c["name"] for c in index.configs)
    warnings = _reader_warnings(doc, (TREE_STREAM, "swXmlContents/COMPINSTANCETREE__ZLB", "Header2"))
    chosen, name, source = index.choose(doc, configuration)
    if chosen is None:
        if index.has_tree and name is not None:
            warnings.append(
                ReaderWarning(
                    "configuration_not_described",
                    f"the component tree has no component list for configuration {name!r}",
                    TREE_STREAM,
                )
            )
        files = {} if index.has_tree else _header2_files(doc)
        return ComponentTree(
            configuration=name,
            configuration_source=source,
            configurations_described=described,
            children_state="unknown",
            files=files,
            children=(),
            truncated=False,
            node_count=0,
            depth=0,
            max_nodes=max_nodes,
            max_depth=max_depth,
            warnings=tuple(warnings),
        )
    exp = _Expansion(index, max_nodes, max_depth).run(chosen["model_ref"])
    files = {key: index.file_object(key, acc) for key, acc in exp.acc.items()}
    return ComponentTree(
        configuration=name,
        configuration_source=source,
        configurations_described=described,
        children_state="described",
        files=files,
        children=exp.children,
        truncated=exp.truncated,
        node_count=exp.count,
        depth=exp.depth,
        max_nodes=max_nodes,
        max_depth=max_depth,
        warnings=tuple(warnings + exp.warnings()),
    )


def reference_set(
    doc,
    configuration: str | None = None,
    *,
    max_nodes: int = DEFAULT_MAX_NODES,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> ReferenceSet:
    """Every file the document references (the ``references`` kind): for an assembly
    every ``swFile`` an instance uses, in stored order, with the counts of
    ``configuration`` and of every configuration the tree describes; for a drawing
    its ``Header2`` models and its sheets; for a part nothing."""
    _check_limits(max_nodes, max_depth)
    if doc.doc_type == "drawing":
        files = _header2_files(doc)
        sheets, warns = read_sheets(doc, files)
        return ReferenceSet(
            configuration=None,
            configuration_source="none",
            configurations_described=(),
            children_state="none",
            truncated=False,
            files=files,
            sheets=sheets,
            warnings=tuple(_reader_warnings(doc, ("Header2",)) + warns),
        )
    if doc.doc_type != "assembly":
        return ReferenceSet(None, "none", (), "none", False, {}, None, ())
    index = _Index(doc)
    described = tuple(c["name"] for c in index.configs)
    warnings = _reader_warnings(doc, (TREE_STREAM, "swXmlContents/COMPINSTANCETREE__ZLB", "Header2"))
    chosen, name, source = index.choose(doc, configuration)
    if not index.has_tree:
        files = _header2_files(doc)
        return ReferenceSet(name, source, described, "unknown", False, files, None, tuple(warnings))
    expansions = []
    truncated = False
    budget = MAX_REFERENCE_SET_NODES
    for c in index.configs:
        exp = _Expansion(index, min(max_nodes, budget), max_depth).run(c["model_ref"])
        budget -= exp.count
        truncated = truncated or exp.truncated
        expansions.append((c["name"], exp))
        warnings += [w for w in exp.warnings() if w not in warnings]
    if chosen is None and name is not None:
        warnings.append(
            ReaderWarning(
                "configuration_not_described",
                f"the component tree has no component list for configuration {name!r}",
                TREE_STREAM,
            )
        )
    files = {}
    for key in index.files:
        if key not in index.direct:
            continue
        per = tuple(
            ConfigurationCounts(
                cname,
                exp.acc[key].instances if key in exp.acc else 0,
                exp.acc[key].unsuppressed if key in exp.acc else 0,
                exp.acc[key].in_bom if key in exp.acc else 0,
            )
            for cname, exp in expansions
        )
        f = index.file_object(key, None, per)
        mine = next((p for p in per if chosen is not None and p.configuration == chosen["name"]), None)
        files[key] = replace(
            f,
            instances=mine.instances if mine else None,
            instances_unsuppressed=mine.instances_unsuppressed if mine else None,
            instances_in_bom=mine.instances_in_bom if mine else None,
        )
    state = "described" if chosen is not None else "unknown"
    return ReferenceSet(name, source, described, state, truncated, files, None, tuple(warnings))


# --------------------------------------------------------------------------- drawings
def parse_sheet_names(d: bytes | None) -> list[str] | None:
    """``SheetPreviews/SheetNames``: a u16 count and that many CStrings. None when the
    bytes do not hold that."""
    if not d or len(d) < 2:
        return None
    (n,) = struct.unpack_from("<H", d, 0)
    if n * 4 > len(d) - 2:  # each CString takes at least 4 bytes
        return None
    p, out = 2, []
    for _ in range(n):
        s, q = read_cstring(d, p)
        if s is None:
            return None
        out.append(s)
        p = q
    return out


def read_sheets(doc, files: dict[str, ComponentFile]) -> tuple[tuple[DrawingSheet, ...], list[ReaderWarning]]:
    """A drawing's sheets and their views (see the module docstring). ``files`` are the
    drawing's ``Header2`` models, whose keys the views point at; it is updated in place:
    a file a view names gains that view's configuration and the ``KeyWords`` source."""
    c = doc.container
    warnings: list[ReaderWarning] = []
    names = None
    if SHEET_NAMES_STREAM in c:
        names = parse_sheet_names(_read(c, SHEET_NAMES_STREAM, warnings))
        if names is None and not warnings:
            warnings.append(
                ReaderWarning(
                    "drawing_sheets_unreadable",
                    "the sheet name list is not a count and that many names",
                    SHEET_NAMES_STREAM,
                )
            )
    root = _parse_xml(_read(c, KEYWORDS_STREAM, warnings), KEYWORDS_STREAM, warnings)
    by_name = {basename_lower(f.stored_path): k for k, f in files.items() if f.stored_path}
    kw_sheets: list[tuple[str | None, list[DrawingView]]] = []
    if root is not None:
        for el in root:
            if _local(el.tag) != "Sheet":
                continue
            views = []
            for v in el:
                if _local(v.tag) != "View":
                    continue
                file_name = (v.text or "").strip() or None
                views.append(
                    DrawingView(
                        name=v.get("Name"),
                        configuration=v.get("Description"),
                        file_name=file_name,
                        file=by_name.get(file_name.lower()) if file_name else None,
                    )
                )
            kw_sheets.append((el.get("Name"), views))
    if names is not None:
        sheets = []
        for nm in names:
            views = next((vs for sn, vs in kw_sheets if sn == nm), [])
            sheets.append(DrawingSheet(nm, tuple(views)))
    else:
        sheets = [DrawingSheet(sn, tuple(vs)) for sn, vs in kw_sheets if sn is not None and vs]
    used: dict[str, list[str | None]] = {}
    for sheet in sheets:
        for v in sheet.views:
            if v.file is not None:
                lst = used.setdefault(v.file, [])
                if v.configuration not in lst:
                    lst.append(v.configuration)
    for key, cfgs in used.items():
        f = files[key]
        files[key] = replace(f, configurations_used=tuple(cfgs), sources=(*f.sources, KEYWORDS_STREAM))
    return tuple(sheets), warnings
