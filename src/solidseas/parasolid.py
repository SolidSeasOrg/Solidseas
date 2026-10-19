"""Parasolid of a SOLIDWORKS assembly (provisional, ``docs/API.md`` 3.25): one transmit
whose root ASSEMBLY places every part instance of one configuration by an INSTANCE and
its TRANSFORM, written as text (``.x_t``) or binary (``.x_b``).

The instances, their placements and the documents they come from are found as the 3D
view, 3D Print and the STEP export find them
(:func:`solidseas.geometry.display_geometry`): a part's own file, found by reference
resolution, or a virtual part's document stored inside the assembly. Suppressed and
hidden components are left out, and a component excluded from the bill of materials
is written, since it is still part of the model. A part's bodies are those
:meth:`~solidseas.formats.solidworks.Document.parasolid` extracts for the configuration
the instance uses, without the bodies SOLIDWORKS hides, each copied into the transmit
once however many instances place it. A part with one body is placed as that BODY; a
part with several is an ASSEMBLY of its bodies at the identity, as SOLIDWORKS writes a
multi-body part, placed as one. A sub-assembly the component tree lists is an ASSEMBLY
of its own, placing its components in its own frame, and sub-assemblies of one file
and configuration placed alike share one. Every assembly and instance is named with
the system attribute ``SDL/TYSA_NAME``: the document's or the part's name, and the
component's instance name.

Bodies saved by different SOLIDWORKS versions carry different node layouts, and a
transmit has one layout per node type. The layout of the newest transmit is used, and
the others' nodes are carried over field by field, by name: a field the newer layout
added is written unset (null pointer, zero, or Parasolid's null value), and a field it
lacks is left out. Equal attribute definitions of different parts become one. The
nodes this module adds (ASSEMBLY, INSTANCE, TRANSFORM and the name attributes) use the
layouts the parts already have, else those of the base schema.
"""

import os
import time
from collections import Counter
from contextlib import ExitStack
from dataclasses import dataclass, field
from typing import Any

from .errors import (
    ConfigurationNotFoundError,
    InvalidArgumentError,
    NothingToExportError,
    NotRepresentableError,
    ReaderWarning,
    SldError,
    SldLimitError,
)
from .formats.solidworks import xt_schema as S
from .formats.solidworks.components import IDENTITY, Placement
from .formats.solidworks.parasolid import (
    DEFAULT_MAX_TRANSMIT_BYTES,
    MAX_NODES,
    NULL_DOUBLE,
    Node,
    SchemaInfo,
    XtTransmit,
    text_header,
    validate,
    write_binary,
    write_text,
)

FORMATS = ("x_b", "x_t")
DEFAULT_MAX_SECONDS = 300.0
NAME_ATTRIBUTE = "SDL/TYSA_NAME"
NAME_TYPE_ID = 8017
# SDL/TYSA_NAME as SOLIDWORKS' own export defines it (o12_multibody.x_b): no actions,
# every owner class but two, one string field.
NAME_OWNERS = (1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1, 0)
NAME_FIELDS = (3,)
CHAIN_BLOCK = 20  # entries in a POINTER_LIS_BLOCK of attribute chains, as SOLIDWORKS writes them
MAX_LISTED = 20  # instances named in a refusal's detail
BASE_SCHEMA = 13006
# Bits of TRANSFORM.flag, as the XT Format Reference lists them.
FLAG_TRANSLATION, FLAG_ROTATION, FLAG_REFLECTION, FLAG_GENERAL = 1, 2, 8, 16

ASSEMBLY, INSTANCE, BODY, LIST, POINTER_LIS_BLOCK = 10, 11, 12, 70, 74
ATT_DEF_ID, ATTRIB_DEF, ATTRIBUTE, CHAR_VALUES, TRANSFORM = 79, 80, 81, 84, 100
VAR = S.VAR


@dataclass(frozen=True)
class PlacedPart:
    """One part instance in the transmit: its component tree id and instance name, its
    file key, the configuration whose bodies were written, how many bodies it places
    and its placement in the top assembly's frame."""

    id: str
    name: str
    file: str | None
    configuration: str | None
    bodies: int
    placement: Placement


@dataclass(frozen=True)
class AssemblyParasolid:
    """One assembly configuration as a Parasolid transmit, ready to write.

    ``instances`` are the part instances placed (:class:`PlacedPart`) and ``skipped``
    those left out, as :class:`solidseas.geometry.SkippedInstance` records with the
    reason. ``counts`` has ``instances``, ``bodies_placed`` (each instance's bodies),
    ``parts`` (part documents and configurations written), ``bodies`` (BODY nodes in
    the transmit), ``sub_assemblies``, ``skipped``, ``suppressed``, ``hidden``,
    ``bodies_hidden`` and ``nodes``. ``report`` is the structural check of the whole
    transmit (:func:`~solidseas.formats.solidworks.parasolid.validate`)."""

    name: str
    configuration: str | None
    transmit: XtTransmit = field(repr=False)
    instances: tuple[PlacedPart, ...]
    skipped: tuple[Any, ...]
    warnings: tuple[ReaderWarning, ...]
    counts: dict[str, int]
    report: dict[str, Any] = field(repr=False)
    seconds: float = 0.0

    @property
    def schema(self) -> str:
        return self.transmit.schema

    @property
    def valid(self) -> bool:
        return bool(self.report.get("ok"))

    def x_b(self, key: str | None = None) -> bytes:
        """The transmit as a binary Parasolid file (.x_b): the common text header, then
        neutral binary. ``key`` names it in the header (default: :attr:`name`)."""
        key = key or self.name
        header = text_header(self.transmit, fmt="binary", key=key, file=key + ".x_b")
        return header.encode("ascii") + write_binary(self.transmit)

    def x_t(self, key: str | None = None) -> bytes:
        """The transmit as a text Parasolid file (.x_t). Numbers keep 15 significant digits."""
        key = key or self.name
        header = text_header(self.transmit, fmt="text", key=key, file=key + ".x_t")
        return (header + write_text(self.transmit) + "\n").encode("latin-1")

    def data(self, format: str = "x_b", key: str | None = None) -> bytes:
        if format not in FORMATS:
            raise InvalidArgumentError(
                f"format must be one of {', '.join(FORMATS)}, not {format!r}", detail={"parameter": "format"}
            )
        return self.x_b(key) if format == "x_b" else self.x_t(key)


# --------------------------------------------------------------------------- one transmit of many
def _default(kind: str, n: int):
    """An unset value of a field: a null pointer, zero, or Parasolid's null double."""
    one: dict[str, Any] = {
        "f": NULL_DOUBLE,
        "v": (NULL_DOUBLE,) * 3,
        "h": (NULL_DOUBLE,) * 3,
        "i": (NULL_DOUBLE,) * 2,
        "b": (NULL_DOUBLE,) * 6,
    }
    if kind == "c":
        return "" if n == VAR else " " * n
    if n == VAR:
        return []
    if n == 1:
        return one.get(kind, 0)
    return [one.get(kind, 0)] * n


def _is_default(kind: str, v) -> bool:
    """Whether ``v`` holds nothing: null pointers, zeros, null doubles or blanks."""
    if isinstance(v, str):
        return not v.strip()
    if isinstance(v, (list, tuple)):
        return all(_is_default(kind, x) for x in v)
    return v in (0, 0.0, NULL_DOUBLE)


def _fit(kind: str, v, src_n: int, n: int):
    """A value of ``src_n`` elements as one of ``n`` (both fixed): cut, or padded unset."""
    seq = [v] if src_n == 1 and kind != "c" else list(v)
    if kind == "c":
        return "".join(seq)[:n].ljust(n)
    seq = [*seq[:n], *[_default(kind, 1)] * max(0, n - len(seq))]
    return seq[0] if n == 1 else seq


def _text_at(xt: XtTransmit, idx: dict[int, Node], ptr) -> str | None:
    node = idx.get(ptr) if isinstance(ptr, int) and ptr else None
    if node is None or node.type != ATT_DEF_ID:
        return None
    v = (
        node.vals[xt.field_names(ATT_DEF_ID).index("string")]
        if "string" in xt.field_names(ATT_DEF_ID)
        else None
    )
    return v if isinstance(v, str) else None


class _Merged:
    """The transmit being built: every node by its index, the layout of each node type,
    and how many fields carrying one transmit's nodes into another's layout filled in
    or left out."""

    def __init__(self, sources: list[XtTransmit]) -> None:
        order = sorted(sources, key=lambda x: x.modeller_version, reverse=True)  # stable: first wins a tie
        newest = order[0] if order else None
        self.layouts: dict[int, list[tuple[str, str, int]]] = {}
        self.info: dict[int, SchemaInfo] = {}
        for xt in order:
            for t, lay in xt.layouts.items():
                if t not in self.layouts:
                    self.layouts[t] = lay
                    self.info[t] = xt.schema_info[t]
        self.schemas = sorted({x.schema for x in sources})
        self.modeller = newest.modeller if newest else ": TRANSMIT FILE created by modeller version 3501251"
        self.schema = newest.schema if newest else "SCH_3501251_35102_13006"
        self.max_types = max((x.max_types or 0 for x in sources), default=0) or None
        self.nodes: dict[int, Node] = {}
        self.next = 2  # index 1 is the root assembly's, made last
        self.filled = 0  # fields a newer layout has and a node's own lacked: written unset
        self.dropped = 0  # fields holding a value that the layout used has no place for
        self.defs: dict[tuple, int] = {}  # an attribute definition's content: its node
        self.def_names: dict[str, int] = {}  # an attribute definition's name: its first node

    # -- layouts
    def layout(self, t: int) -> list[tuple[str, str, int]]:
        lay = self.layouts.get(t)
        if lay is None:
            lay = [tuple(f[:3]) for f in S.BASE[t]]  # type: ignore[misc]
            self.layouts[t] = lay
            self.info[t] = SchemaInfo("base")
        return lay

    def pos(self, t: int, name: str) -> int:
        return [f[0] for f in self.layout(t)].index(name)

    def get(self, i: int, name: str):
        nd = self.nodes[i]
        return nd.vals[self.pos(nd.type, name)]

    def set(self, i: int, name: str, value) -> None:
        nd = self.nodes[i]
        names = [f[0] for f in self.layout(nd.type)]
        if name in names:
            nd.vals[names.index(name)] = value

    def new(self, t: int, **fields) -> int:
        """A node of type ``t`` of this module's own, its fields by name (others unset)."""
        i = self.next
        self.next += 1
        self.nodes[i] = self._node(t, i, fields)
        return i

    def _node(self, t: int, i: int, fields: dict[str, Any]) -> Node:
        vals, count = [], None
        for name, kind, n in self.layout(t):
            v = fields[name] if name in fields else _default(kind, n)
            if n == VAR:
                count = len(v)
            vals.append(v)
        return Node(t, i, vals, count)

    def _convert(self, xt: XtTransmit, nd: Node, vals: list) -> tuple[list, int | None]:
        """``vals`` (``nd``'s values, pointers already renumbered) in this transmit's
        layout of the node's type: by field name, unset where the node has no such field."""
        src = xt.layouts[nd.type]
        dst = self.layout(nd.type)
        if src == dst:
            return vals, nd.count
        have = {f[0]: (f[1], f[2], v) for f, v in zip(src, vals, strict=True)}
        out, count = [], None
        for name, kind, n in dst:
            got = have.pop(name, None)
            if got is not None and got[0] == kind and got[1] == n:
                v = got[2]
            elif got is not None and got[0] == kind and VAR not in (got[1], n):
                v = _fit(kind, got[2], got[1], n)  # a fixed list of another length
            else:
                if got is not None and not _is_default(got[0], got[2]):
                    self.dropped += 1
                v = _default(kind, n)
                self.filled += 1
            if n == VAR:
                count = len(v)
            out.append(v)
        self.dropped += sum(1 for kind, _n, v in have.values() if not _is_default(kind, v))
        return out, count

    # -- copying a part transmit in
    def add(self, xt: XtTransmit) -> int:
        """Copy the part transmit ``xt`` (its BODY at index 1) in; returns the new index
        of its BODY. An attribute definition equal to one already here is not copied:
        its attributes point at the one here."""
        idx = xt.by_index()
        defs_here: dict[int, int] = {}  # a definition of xt that one here stands in for
        skip: set[int] = set()
        for nd in xt.nodes:
            if nd.type != ATTRIB_DEF:
                continue
            names = xt.field_names(ATTRIB_DEF)
            ident_ptr = nd.vals[names.index("identifier")] if "identifier" in names else 0
            name = _text_at(xt, idx, ident_ptr)
            fn = nd.vals[names.index("field_names")] if "field_names" in names else 0
            if name is None or fn:
                continue  # unnamed, or with field names: kept as it is
            vals, _count = self._convert(xt, nd, list(nd.vals))
            here = self.defs.get(self._signature(name, vals))
            if here is not None:
                defs_here[nd.index] = here
                skip.add(nd.index)
                skip.add(ident_ptr)
        remap: dict[int, int] = {}
        for nd in xt.nodes:
            if nd.index in skip:
                continue
            remap[nd.index] = self.next
            self.next += 1
        for nd in xt.nodes:
            if nd.index in skip:
                continue
            vals = list(nd.vals)
            for i, (_name, kind, n) in enumerate(xt.layouts[nd.type]):
                if kind != "p":
                    continue
                seq = [vals[i]] if n == 1 else list(vals[i])
                for k, x in enumerate(seq):
                    if not x:
                        continue
                    # a pointer outside the part's own transmit (a dangling BODY.next, which
                    # SOLIDWORKS' own exports carry) is written null
                    seq[k] = remap.get(x) or defs_here.get(x) or 0
                vals[i] = seq[0] if n == 1 else seq
            vals, count = self._convert(xt, nd, vals)
            node = Node(nd.type, remap[nd.index], vals, count)
            self.nodes[node.index] = node
            if nd.type == ATTRIB_DEF:
                names = [f[0] for f in self.layout(ATTRIB_DEF)]
                name = _text_at(xt, idx, nd.vals[xt.field_names(ATTRIB_DEF).index("identifier")])
                if name is not None:
                    self.def_names.setdefault(name, node.index)
                    if not vals[names.index("field_names")]:
                        self.defs.setdefault(self._signature(name, vals), node.index)
        body = remap[1]
        for name in ("owner", "next", "previous", "ref_instance"):
            self.set(body, name, 0)
        return body

    def _signature(self, name: str, vals: list) -> tuple:
        """What makes two attribute definitions the same: the name and every field but
        the pointers."""
        return (name,) + tuple(
            (f[0], tuple(v) if isinstance(v, list) else v)
            for f, v in zip(self.layout(ATTRIB_DEF), vals, strict=True)
            if f[1] != "p"
        )

    # -- the name attribute
    def name_definition(self) -> int:
        here = self.def_names.get(NAME_ATTRIBUTE)
        if here is not None:
            return here
        lay = {f[0]: f for f in self.layout(ATTRIB_DEF)}
        owners = lay.get("legal_owners")
        n_owners = owners[2] if owners is not None and owners[2] not in (1, VAR) else len(NAME_OWNERS)
        ident = self.new(ATT_DEF_ID, string=NAME_ATTRIBUTE)
        d = self.new(
            ATTRIB_DEF,
            identifier=ident,
            type_id=NAME_TYPE_ID,
            actions=[0] * 8,
            legal_owners=[*NAME_OWNERS[:n_owners], *[0] * max(0, n_owners - len(NAME_OWNERS))],
            fields=list(NAME_FIELDS),
        )
        self.def_names[NAME_ATTRIBUTE] = d
        self.defs.setdefault(self._signature(NAME_ATTRIBUTE, self.nodes[d].vals), d)
        return d

    def transmit(self) -> XtTransmit:
        # Chain the attribute definitions (ATTRIB_DEF.next), in index order.
        defs = sorted(i for i, nd in self.nodes.items() if nd.type == ATTRIB_DEF)
        for a, b in zip(defs, [*defs[1:], 0], strict=True):
            self.set(a, "next", b)
        xt = XtTransmit()
        xt.modeller = self.modeller.replace("TRANSMIT FILE (partition)", "TRANSMIT FILE")
        xt.schema = self.schema
        xt.base = BASE_SCHEMA
        xt.max_types = self.max_types or 231
        xt.usfld = 0
        xt.nodes = [self.nodes[i] for i in sorted(self.nodes)]
        used = {nd.type for nd in xt.nodes}
        xt.layouts = {t: self.layouts[t] for t in self.layouts if t in used}
        xt.schema_info = {t: self.info[t] for t in xt.layouts}
        return xt


class _Assembly:
    """One ASSEMBLY node being filled: its node ids (``node_id`` of what it owns), its
    instances in order and the attributes it owns."""

    def __init__(self, out: _Merged, index: int) -> None:
        self.out = out
        self.index = index
        self.ids = 0
        self.instances: list[int] = []
        self.attributes: list[int] = []

    def node_id(self) -> int:
        self.ids += 1
        return self.ids


def _flag(p: Placement) -> int:
    r, t = p.rotation, p.translation_m
    flag = FLAG_TRANSLATION if any(abs(x) > 0.0 for x in t) else 0
    if any(abs(r[i][j] - (1.0 if i == j else 0.0)) > 0.0 for i in range(3) for j in range(3)):
        flag |= FLAG_ROTATION
    det = (
        r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1])
        - r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0])
        + r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0])
    )
    if det < 0:
        flag |= FLAG_REFLECTION
    for i in range(3):
        for j in range(3):
            dot = r[0][i] * r[0][j] + r[1][i] * r[1][j] + r[2][i] * r[2][j]
            if abs(dot - (1.0 if i == j else 0.0)) > 1e-6:
                return flag | FLAG_GENERAL
    return flag


class _Writer:
    """Assemblies, instances and names over a :class:`_Merged` transmit."""

    def __init__(self, out: _Merged, res: tuple[float, float]) -> None:
        self.out = out
        self.res = res
        self.assemblies: dict[int, _Assembly] = {}
        self.of_part: dict[int, list[int]] = {}  # a part's instances, in order

    def assembly(self, name: str | None, index: int | None = None) -> int:
        out = self.out
        fields = dict(state=1, type=1, res_size=self.res[0], res_linear=self.res[1])
        if index is None:
            index = out.new(ASSEMBLY, **fields)
        else:
            out.nodes[index] = out._node(ASSEMBLY, index, fields)
        asm = self.assemblies[index] = _Assembly(out, index)
        if name:
            self.set_name(asm, index, name)
        return index

    def set_name(self, asm: _Assembly, owner: int, name: str) -> None:
        out = self.out
        # A name is a string of bytes: one outside Latin-1's ASCII part is written as UTF-8,
        # which SolidSeas' reader decodes back.
        text = name.encode("utf-8").decode("latin-1")
        value = out.new(CHAR_VALUES, values=text)
        att = out.new(
            ATTRIBUTE, node_id=asm.node_id(), definition=out.name_definition(), owner=owner, fields=[value]
        )
        out.set(owner, "attributes_features", att)
        asm.attributes.append(att)

    def place(self, asm_index: int, part: int, placement: Placement, name: str | None) -> int:
        out = self.out
        asm = self.assemblies[asm_index]
        inst = out.new(INSTANCE, node_id=asm.node_id(), type=1, part=part, assembly=asm_index)
        r, t = placement.rotation, placement.translation_m
        tf = out.new(
            TRANSFORM,
            node_id=asm.node_id(),
            owner=inst,
            rotation_matrix=[float(r[i][j]) for i in range(3) for j in range(3)],
            translation_vector=tuple(float(x) for x in t),
            scale=1.0,
            flag=_flag(placement),
            perspective_vector=(NULL_DOUBLE,) * 3,
        )
        out.set(inst, "transform", tf)
        if asm.instances:
            out.set(asm.instances[-1], "next_in_part", inst)
            out.set(inst, "prev_in_part", asm.instances[-1])
        else:
            out.set(asm_index, "sub_instance", inst)
        asm.instances.append(inst)
        mine = self.of_part.setdefault(part, [])
        if mine:
            out.set(mine[-1], "next_of_part", inst)
            out.set(inst, "prev_of_part", mine[-1])
        else:
            out.set(part, "ref_instance", inst)
        mine.append(inst)
        if name:
            self.set_name(asm, inst, name)
        return inst

    def finish(self) -> None:
        """Each assembly's attribute chains (one per definition, by ``next_of_type``)
        listed in its ``attribute_chains``, and its highest node id."""
        out = self.out
        for index, asm in self.assemblies.items():
            heads: list[int] = []
            last: dict[int, int] = {}
            for att in asm.attributes:
                d = out.get(att, "definition")
                if d in last:
                    out.set(last[d], "next_of_type", att)
                    out.set(att, "previous_of_type", last[d])
                else:
                    heads.append(att)
                last[d] = att
            if heads:
                blocks = []
                for k in range(0, len(heads), CHAIN_BLOCK):
                    part = heads[k : k + CHAIN_BLOCK]
                    blocks.append(
                        out.new(
                            POINTER_LIS_BLOCK,
                            n_entries=len(part),
                            entries=[*part, *[0] * (CHAIN_BLOCK - len(part))],
                        )
                    )
                for a, b in zip(blocks, blocks[1:], strict=False):
                    out.set(a, "next_block", b)
                chain = out.new(
                    LIST,
                    list_type=4,
                    notransmit=1,
                    owner=index,
                    list_length=len(heads),
                    block_length=CHAIN_BLOCK,
                    size_of_entry=1,
                    finger_index=1,
                    finger_block=blocks[0],
                    list_block=blocks[0],
                )
                out.set(index, "attribute_chains", chain)
            out.set(index, "highest_node_id", asm.ids)


# --------------------------------------------------------------------------- the assembly
def _number(value: Any, name: str, low: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not value >= low:
        raise InvalidArgumentError(f"{name} must be a number of at least {low:g}", detail={"parameter": name})
    return float(value)


def _short(exc: BaseException) -> str:
    text = str(exc).removeprefix("nothing to export: ")
    return text.split(" (", 1)[0].split("; ", 1)[0]


def _part_bodies(part, cfg, *, include_hidden, other_configurations, max_bytes, warnings, label):
    """``(configuration written, [part transmit], bodies hidden)`` of the part document
    ``part`` in ``cfg``, or raise :class:`NothingToExportError` with why not."""
    from .formats.xt import extract_body
    from .tessellate import bodies_of, shown_bodies

    name, bodies, found, _n = bodies_of(part, cfg, max_bytes=max_bytes)
    if not bodies and other_configurations:
        active, bodies, found2, _n = bodies_of(part, None, max_bytes=max_bytes)
        if bodies and active != name:
            warnings.append(
                ReaderWarning(
                    "parasolid_other_configuration",
                    f"{label}: the part stores no bodies of configuration {name!r}; "
                    f"the bodies of {active!r} are written in its place",
                )
            )
            found = [*found, *found2]
            name = active
    for w in found:
        if w.code != "no_stored_bodies":
            warnings.append(ReaderWarning(w.code, f"{label}: {w.message}", getattr(w, "stream", None)))
    if not bodies:
        from .step import step_configurations

        stored = step_configurations(part)
        where = (
            f"it stores the bodies of {', '.join(repr(s) for s in stored)}"
            if stored
            else "it stores no bodies at all"
        )
        raise NothingToExportError(
            f"nothing to export: the part does not store the bodies of configuration {name!r} ({where})"
        )
    hidden = 0
    if not include_hidden:
        kept, hidden = shown_bodies(bodies)
        if not kept:
            raise NothingToExportError("nothing to export: every body of the part is hidden in SOLIDWORKS")
        bodies = kept
    transmits = []
    for b in bodies:
        xt = b.transmit
        if xt.base != BASE_SCHEMA:
            raise NothingToExportError(
                f"nothing to export: a body's transmit does not embed its schema ({xt.schema})"
            )
        root = xt.by_index().get(1)
        if root is not None and root.type == BODY:
            transmits.append(xt)
        else:  # bodies placed by an assembly of their own: each copied out as a part
            transmits.extend(extract_body(xt, n) for n in xt.nodes if n.type == BODY)
    if not transmits:
        raise NothingToExportError("nothing to export: the part's transmits hold no body")
    return name, transmits, hidden


def assembly_parasolid(
    doc,
    configuration: str | None = None,
    *,
    name: str | None = None,
    allow_partial: bool = False,
    other_configurations: bool = False,
    include_hidden: bool = False,
    max_bytes: int = DEFAULT_MAX_TRANSMIT_BYTES,
    max_nodes: int = MAX_NODES,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    roots=None,
    path_map=(),
    allow_outside_roots: bool = True,
    cache=None,
) -> AssemblyParasolid:
    """The assembly ``doc`` in ``configuration`` (None: the active one) as one Parasolid
    transmit of every part instance, ready for :func:`write_parasolid`. Provisional
    (``docs/API.md`` 3.25).

    ``roots``, ``path_map``, ``allow_outside_roots`` and ``cache`` find the component
    files as :func:`~solidseas.geometry.display_geometry` does (None: the document's own
    folder). A component that was not found, could not be read, or whose part does not
    store the bodies of the configuration it uses raises ``NotRepresentableError``
    (rule ``instances_left_out``), unless ``allow_partial`` leaves it out and says so;
    ``other_configurations`` writes such a part's stored bodies instead, with the
    warning ``parasolid_other_configuration``. Bodies SOLIDWORKS hides are left out
    unless ``include_hidden``. ``max_bytes`` bounds each Parasolid transmit read,
    ``max_nodes`` the nodes of the transmit written and ``max_seconds`` the whole call
    (``SldLimitError``). Raises ``InvalidArgumentError`` for a part, a drawing or a bad
    option, ``ConfigurationNotFoundError`` for an unknown configuration and
    ``NothingToExportError`` when no instance can be written. Nothing is written."""
    from .formats.solidworks import open_document
    from .geometry import display_geometry
    from .step.assembly import _left_out, _relative, _rounded, _Tree

    t0 = time.perf_counter()
    max_seconds = _number(max_seconds, "max_seconds", 0.001)
    if isinstance(max_nodes, bool) or not isinstance(max_nodes, int) or max_nodes < 1:
        raise InvalidArgumentError(
            "max_nodes must be a whole number of at least 1", detail={"parameter": "max_nodes"}
        )
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise InvalidArgumentError(
            "max_bytes must be a whole number of at least 1", detail={"parameter": "max_bytes"}
        )
    if getattr(doc, "doc_type", None) != "assembly":
        raise InvalidArgumentError(
            f"the document is a {getattr(doc, 'doc_type', None) or 'document of unknown type'}, not an "
            "assembly: a part's bodies are written by Document.parasolid()",
            detail={"parameter": "doc"},
        )
    stem = (
        name
        or os.path.splitext(os.path.basename(getattr(doc, "name", None) or getattr(doc, "path", "") or ""))[0]
    )
    stem = stem or "assembly"

    def check_time() -> None:
        if time.perf_counter() - t0 > max_seconds:
            raise SldLimitError(
                f"writing the assembly's Parasolid took longer than {max_seconds:g} s",
                detail={"limit": "seconds"},
            )

    g = display_geometry(
        doc,
        configuration,
        sources=("file", "brep"),
        max_brep_seconds=max_seconds,
        brep_options={"body_types": ("solid", "sheet"), "max_seconds": max_seconds},
        roots=roots,
        path_map=path_map,
        allow_outside_roots=allow_outside_roots,
        cache=cache,
    )
    if g is None:  # not reached for an assembly; kept for a document that reads as none
        raise InvalidArgumentError("the document is not an assembly", detail={"parameter": "doc"})
    warnings: list[ReaderWarning] = list(g.warnings)
    skipped = list(g.skipped)
    instances = list(g.instances)

    def key_of(inst) -> tuple:
        src = g.meshes[inst.mesh]
        return (src.path, tuple(src.nested), inst.configuration)

    keys: dict[tuple, Any] = {}
    for inst in instances:
        keys.setdefault(key_of(inst), g.meshes[inst.mesh])
    stems: Counter = Counter()
    labels: dict[tuple, str] = {}
    for key, src in keys.items():
        f = g.files.get(src.file or "")
        label = os.path.splitext(
            f.file_name if f is not None and f.file_name else os.path.basename(src.path or "")
        )[0]
        labels[key] = label or "part"
        stems[labels[key]] += 1
    parts: dict[tuple, tuple[str, str | None, list[XtTransmit]]] = {}
    refused: dict[tuple, str] = {}
    hidden_total = 0
    for key in keys:
        check_time()
        path, nested, cfg = key
        label = labels[key]
        if stems[label] > 1 and cfg:
            label = f"{label} ({cfg})"
        try:
            with ExitStack() as stack:
                part = doc if path is None else stack.enter_context(open_document(path))
                for stream in nested:
                    part = part.nested(stream)  # owned by its parent, which closes it
                cfg_name, transmits, hidden = _part_bodies(
                    part,
                    cfg,
                    include_hidden=include_hidden,
                    other_configurations=other_configurations,
                    max_bytes=max_bytes,
                    warnings=warnings,
                    label=label,
                )
        except NothingToExportError as exc:
            refused[key] = _short(exc)
            continue
        except ConfigurationNotFoundError:
            refused[key] = f"the part has no configuration named {cfg!r}"
            continue
        except SldLimitError:
            raise
        except SldError as exc:
            refused[key] = f"its document could not be read: {exc}"
            continue
        hidden_total += hidden
        parts[key] = (label, cfg_name, transmits)
    kept = []
    for inst in instances:
        if key_of(inst) in refused:
            skipped.append(_left_out(inst, "parasolid_refused", refused[key_of(inst)]))
        else:
            kept.append(inst)
    instances = kept
    reasons = [f"{s.id}: {s.message}" for s in skipped]
    if not instances:
        raise NothingToExportError(
            "nothing to export: none of the assembly's instances can be written"
            + (f": {'; '.join(reasons[:3])}" if reasons else ""),
            detail={"rule": "no_instances"},
        )
    if skipped and not allow_partial:
        raise NotRepresentableError(
            f"{len(skipped)} of the assembly's instances cannot be written: {'; '.join(reasons[:3])}"
            f"{'; ...' if len(reasons) > 3 else ''}",
            detail={"rule": "instances_left_out", "value": len(skipped), "instances": reasons[:MAX_LISTED]},
        )
    if hidden_total:
        warnings.append(
            ReaderWarning(
                "parasolid_bodies_hidden",
                f"{hidden_total} {'body is' if hidden_total == 1 else 'bodies are'} hidden in SOLIDWORKS and "
                "left out, as SOLIDWORKS leaves hidden bodies out of what it exports",
            )
        )

    # The transmit: every part's bodies once, then the assemblies placing them.
    sources = [xt for _l, _c, transmits in parts.values() for xt in transmits]
    if sum(len(xt.nodes) for xt in sources) > max_nodes:
        raise SldLimitError(
            f"the parts' bodies hold more than {max_nodes:,} Parasolid nodes", detail={"limit": "max_nodes"}
        )
    out = _Merged(sources)
    first = sources[0]
    root_body = first.by_index()[1]
    names = first.field_names(BODY)
    res = (
        root_body.vals[names.index("res_size")] if "res_size" in names else 1e3,
        root_body.vals[names.index("res_linear")] if "res_linear" in names else 1e-8,
    )
    w = _Writer(out, res)
    body_nodes_of: dict[tuple, list[int]] = {}
    for key, (_label, _cfg, transmits) in parts.items():
        check_time()
        body_nodes_of[key] = [out.add(xt) for xt in transmits]
    # Names come after the bodies, so that a name definition a part brings is the one used.
    w.assembly(stem, index=1)
    placed_as: dict[tuple, int] = {}  # a part: the BODY, or the ASSEMBLY of its bodies, that places it
    bodies_of_part: dict[tuple, int] = {}
    body_count = 0
    for key, (label, _cfg, _transmits) in parts.items():
        body_nodes = body_nodes_of[key]
        body_count += len(body_nodes)
        bodies_of_part[key] = len(body_nodes)
        if len(body_nodes) == 1:
            placed_as[key] = body_nodes[0]
        else:  # as SOLIDWORKS writes a multi-body part: an assembly of its bodies where they are
            asm = w.assembly(label)
            for b in body_nodes:
                w.place(asm, b, IDENTITY, None)
            placed_as[key] = asm

    tree = _Tree(doc, g.configuration, instances)
    subs: dict[tuple, int] = {}
    sub_labels: Counter = Counter()

    def write(asm: str | None) -> tuple[tuple, int]:
        """The ASSEMBLY of the sub-assembly ``asm`` (None: the top's, index 1) once its
        children's exist; its signature, which an identical one shares, and its index."""
        children = []
        for kind, child in tree.children.get(asm, []):
            check_time()
            if kind == "part":
                k = key_of(child)
                children.append((k, child.name, child.placement, placed_as[k]))
            else:
                sig, index = write(child)
                node = tree.nodes[child]
                children.append((sig, node["name"], tree.placement(child), index))
        frame = tree.placement(asm) if asm is not None else None
        local = [(k, nm, _relative(frame, pl), index) for k, nm, pl, index in children]
        if asm is None:
            for _k, nm, pl, index in local:
                w.place(1, index, pl, nm)
            return (), 1
        node = tree.nodes[asm]
        sig = (
            node["file"],
            node.get("configuration"),
            tuple((k, nm, _rounded(pl)) for k, nm, pl, _i in local),
        )
        if sig not in subs:
            label = tree.stem(node)
            sub_labels[label] += 1
            label = label if sub_labels[label] == 1 else f"{label} ({sub_labels[label]})"
            index = w.assembly(label)
            for _k, nm, pl, child_index in local:
                w.place(index, child_index, pl, nm)
            subs[sig] = index
        return sig, subs[sig]

    write(None)
    w.finish()
    xt = out.transmit()
    if len(xt.nodes) > max_nodes:
        raise SldLimitError(
            f"the assembly's transmit would hold more than {max_nodes:,} nodes", detail={"limit": "max_nodes"}
        )
    if len(out.schemas) > 1:
        warnings.append(
            ReaderWarning(
                "parasolid_schemas_merged",
                f"the parts' bodies come from {len(out.schemas)} Parasolid schema versions; they are "
                f"written in the newest, {out.schema}, with {out.filled} field(s) it adds written unset and "
                f"{out.dropped} value(s) it has no place for left out",
            )
        )
    if skipped:
        warnings.append(
            ReaderWarning(
                "parasolid_instances_left_out",
                f"{len(skipped)} of the assembly's instances are left out: {'; '.join(reasons[:3])}"
                f"{'; ...' if len(reasons) > 3 else ''}",
            )
        )
    report = validate(xt)
    placed = tuple(
        PlacedPart(
            inst.id,
            inst.name,
            inst.file,
            parts[key_of(inst)][1],
            bodies_of_part[key_of(inst)],
            inst.placement,
        )
        for inst in instances
    )
    counts = {
        "instances": len(placed),
        "bodies_placed": sum(p.bodies for p in placed),
        "parts": len(parts),
        "bodies": body_count,
        "sub_assemblies": len(subs),
        "skipped": len(skipped),
        "suppressed": int(g.counts.get("suppressed", 0)),
        "hidden": int(g.counts.get("hidden", 0)),
        "bodies_hidden": hidden_total,
        "nodes": len(xt.nodes),
    }
    return AssemblyParasolid(
        name=stem,
        configuration=g.configuration,
        transmit=xt,
        instances=placed,
        skipped=tuple(skipped),
        warnings=tuple(warnings),
        counts=counts,
        report=report,
        seconds=time.perf_counter() - t0,
    )


def write_parasolid(
    model: AssemblyParasolid, path, format: str | None = None, *, overwrite: bool = False
) -> tuple[str, int]:
    """Write ``model`` to the new file ``path`` as ``format`` (``x_b`` or ``x_t``; None:
    from the path's extension), under the rules every export writes by
    (:func:`solidseas.export.write_new`): never over an existing file unless
    ``overwrite``, never through a link. Returns the absolute path and its size."""
    from .export import write_new

    if format is None:
        format = os.path.splitext(os.fspath(path))[1].lower().lstrip(".")
    if format not in FORMATS:
        raise InvalidArgumentError(
            f"a Parasolid file is .x_b or .x_t, not {format!r}", detail={"parameter": "format"}
        )
    key = os.path.splitext(os.path.basename(os.fspath(path)))[0] or model.name
    data = model.data(format, key)

    def write(fh) -> int:
        fh.write(data)
        return len(data)

    return write_new(path, write, overwrite=overwrite)
