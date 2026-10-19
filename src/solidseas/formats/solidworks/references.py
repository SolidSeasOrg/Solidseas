"""Component references in the 0.1 shape (``Document.references()``).

``swXmlContents/COMPINSTANCETREE`` (legacy: ``COMPINSTANCETREE__ZLB``) is UTF-8
XML in the swSolidWorks schema and holds the whole component hierarchy:

* ``swFile``: one per referenced document, with its absolute ``swPath`` as it
  was when the assembly was saved, ``swDocType`` and ``swCreationTime``;
* ``swModel``: a document in one configuration, with a bounding box;
* ``swReference``: one per component instance, with its name and number,
  configuration, suppressed, hidden, excluded-from-BOM and virtual flags, and a
  4 x 4 ``swTransform`` in metres, relative to the parent instance (layout and
  evidence in :mod:`.components`).

Instances whose parent ``swModel`` is not the assembly itself belong to
sub-assemblies; they are reported with ``direct=False``. ``Header2`` keeps a
second, sometimes stale, list of absolute paths and confirms direct
references. Drawings have no tree; their ``Header2`` model paths are reported
as references (checked against SOLIDWORKS on fixtures o18 and o19 only, so a
hypothesis for drawings of several models; see :mod:`.components`).

:mod:`.components` builds the per-configuration component tree
(``Document.components()``) and the ``references`` JSON kind; this list mixes
every configuration's instances and is kept for 0.1 callers.
"""

import warnings
from dataclasses import dataclass, field

from ...errors import SolidSeasDeprecationWarning
from .components import _file_name, header2_paths
from .metadata import Metadata, basename_lower


@dataclass
class Instance:
    name: str  # "<component>-<number>", e.g. "bracket-2"
    configuration: str | None
    suppressed: bool
    hidden: bool  # what SOLIDWORKS reports as hidden (a suppressed instance is not hidden)
    exclude_from_bom: bool
    transform: tuple[float, ...] | None  # the 16 stored numbers, metres

    @property
    def translation(self) -> tuple[float, float, float] | None:
        """Elements 12 to 14 of the stored transform (metres)."""
        if not self.transform or len(self.transform) < 15:
            return None
        return self.transform[12], self.transform[13], self.transform[14]


@dataclass
class Reference:
    path: str | None  # absolute path when the referencing document was saved
    file_name: str | None
    doc_type: str | None  # swDocType as stored
    virtual: bool
    direct: bool | None  # False: inside a sub-assembly; None: unknown (Header2 only)
    configurations: list[str | None] = field(default_factory=list)
    instances: list[Instance] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    key: str | None = None  # the file key of docs/API.md C7: the swFile id, or "header2:<n>"

    @property
    def quantity(self) -> int:
        """Deprecated: the instances of every configuration and every sub-assembly
        counted together, which is no bill-of-materials quantity. Use
        ``Document.reference_set(configuration).files[reference.key]``: its
        ``instances`` (0 for a file that configuration does not use, None for a
        drawing's model) and ``per_configuration`` counts, as in the ``references``
        JSON kind."""
        warnings.warn(
            "Reference.quantity counts the instances of every configuration together; use "
            "Document.reference_set(configuration).files[reference.key].instances (or its "
            "per_configuration counts) instead",
            SolidSeasDeprecationWarning,
            stacklevel=2,
        )
        return len(self.instances)


def _transform(text: str | None) -> tuple[float, ...] | None:
    if not text:
        return None
    try:
        return tuple(float(x) for x in text.split())
    except ValueError:
        return None


def references_from_metadata(md: Metadata, path: str | None = None) -> list[Reference]:
    """Build the reference list from the carriers :func:`~.metadata.read_metadata` parsed."""
    tree, h2 = md.tree or {}, md.header2 or {}
    refs: dict[str, Reference] = {}
    parents: dict[str, set[str]] = {}
    tree_stream = md.tree_stream or "swXmlContents/COMPINSTANCETREE"
    for r in tree.get("refs", []):
        mdl = tree["models"].get(r["model_ref"], {})
        fid = mdl.get("file_ref")
        fi = tree["files"].get(fid, {})
        fpath = fi.get("path")
        key = fpath or (f"<virtual>{r['name'] or ''}" if r["virtual"] else None)
        if key is None:
            continue
        ref = refs.get(key)
        if ref is None:
            ref = Reference(
                path=fpath,
                file_name=_file_name(fpath),
                doc_type=fi.get("doc_type"),
                virtual=r["virtual"],
                direct=None,
                sources=[tree_stream],
                key=fid if fid in tree["files"] else None,
            )
            refs[key] = ref
        ref.instances.append(
            Instance(
                name=f"{r['name']}-{r['number']}",
                configuration=r["config"],
                suppressed=r["suppressed"],
                hidden=r["hidden"],
                exclude_from_bom=r["exclude_from_bom"],
                transform=_transform(r["transform"]),
            )
        )
        if r["config"] not in ref.configurations:
            ref.configurations.append(r["config"])
        parents.setdefault(key, set()).add(r["parent_model"])
    top_models = {mid for mid, m in tree.get("models", {}).items() if m.get("file_ref") in md.own_file_ids}
    for key, ref in refs.items():
        ref.direct = bool(parents.get(key, set()) & top_models)
    out = list(refs.values())
    header_names = {basename_lower(p) for p in h2.get("ext_paths", [])}
    for ref in out:
        if ref.path and basename_lower(ref.path) in header_names:
            ref.sources.append("Header2")
    if not out and md.doc_type in ("assembly", "drawing"):
        for n, p in enumerate(header2_paths(md, path), start=1):
            out.append(
                Reference(
                    path=p,
                    file_name=_file_name(p),
                    doc_type=None,
                    virtual=False,
                    direct=None,
                    sources=["Header2"],
                    key=f"header2:{n}",
                )
            )
    return out
