"""Every bound a model-file reader keeps, in one object (provisional).

:class:`Limits` is a frozen dataclass with one field per bound ``docs/API.md``
section 3.20.2 lists, set to its default. :func:`solidseas.formats.open_model`,
the worker jobs and the command line pass one down to every reader;
:meth:`Limits.replace` makes a variant. Reaching a bound raises
:class:`~solidseas.errors.SldLimitError` (code ``limit_exceeded``) whose
``detail["limit"]`` is the field's name, unless the field's notes say the
result is cut short instead (``tree_nodes``, ``text_bytes``, the viewer's
triangle cap).

The core's fields come first, then the surfaces' (rendered previews), then one
group per format. Every format's fields are here from the start, so a reader
never edits this module: it reads ``limits.<field>``.
"""

import math
from dataclasses import dataclass, fields
from dataclasses import replace as _replace
from typing import Any

from ..errors import InvalidArgumentError, SldLimitError

KIB = 1 << 10
MIB = 1 << 20
GIB = 1 << 30


@dataclass(frozen=True)
class Limits:
    """The bounds of one read. Every field is a positive number; ``file_bytes`` may be
    None (no limit beyond the caller's ``max_file_bytes``)."""

    # -- the core -----------------------------------------------------------------
    file_bytes: int | None = None  # the file, from fstat (code file_too_large)
    whole_read_bytes: int = 512 * MIB  # files up to this size are read whole and the handle closed
    seconds: float = 30.0  # one head, tree, bodies or references call
    triangles: int = 20_000_000  # triangles read or tessellated in one document
    vertices: int = 60_000_000  # vertices read in one document
    objects: int = 100_000  # mesh objects in one scene
    items: int = 1_000_000  # placed items in one scene
    tree_nodes: int = 10_000  # tree() nodes (then truncated)
    depth: int = 32  # trees, node hierarchies, sub-assemblies, references
    components: int = 10_000  # component documents one scene opens
    text_bytes: int = 64 * KIB  # one name, property value or metadata value (then cut)
    properties: int = 10_000  # properties of one document
    references: int = 10_000  # external references of one document
    colors_per_object: int = 256  # colour splits of one object (then merged)
    siblings: int = 1_000  # files beside the document that one document reads
    sibling_bytes: int = 512 * MIB  # each such file
    zip_members: int = 10_000  # members of a zip
    zip_directory_bytes: int = 64 * MIB  # a zip's central directory
    zip_member_bytes: int = GIB  # one member, inflated, counted as it inflates
    zip_total_bytes: int = 2 * GIB  # every member one document inflates
    zip_ratio: int = 200  # inflated to stored size of one member (past 1 MiB inflated)
    xml_depth: int = 64  # element nesting (damaged_file)
    xml_attribute_bytes: int = 64 * KIB  # one attribute value
    xml_text_bytes: int = 64 * KIB  # one element's text
    json_bytes: int = 64 * MIB  # one JSON document
    json_depth: int = 64  # JSON nesting (damaged_file)
    image_side: int = 4096  # width and height of a stored or converted image
    image_bytes: int = 64 * MIB  # a stored image, and its inflated pixel data
    png_chunks: int = 10_000  # chunks of a stored PNG
    # -- the surfaces: rendered previews and their cache -----------------------------
    render_triangles: int = 500_000  # placed triangles drawn in a thumbnail (the rest counted)
    render_side: int = 4096  # a thumbnail's width and height
    render_seconds: float = 5.0  # drawing one thumbnail (then partial)
    thumbnail_brep_seconds: float = 15.0  # the coarse tessellation behind a B-rep thumbnail
    thumbnail_cache_bytes: int = 256_000_000  # the thumbnail cache file
    # -- STL ----------------------------------------------------------------------------
    stl_line_bytes: int = 4 * KIB  # one ASCII STL line
    stl_name_bytes: int = 256  # an ASCII solid's name
    # -- 3MF, OBJ, PLY, OFF, glTF and AMF -----------------------------------------------
    threemf_model_parts: int = 10_000
    threemf_components: int = 1_000_000
    threemf_component_depth: int = 16
    threemf_color_groups: int = 65_536
    threemf_metadata: int = 1_000
    obj_line_bytes: int = MIB
    polygon_corners: int = 1_024
    obj_materials: int = 10_000
    obj_material_libraries: int = 16
    ply_header_bytes: int = 64 * KIB
    ply_elements: int = 32
    ply_properties: int = 64
    gltf_buffers: int = 1_000
    gltf_data_uri_bytes: int = 256 * MIB
    gltf_array_items: int = 100_000
    amf_constellation_depth: int = 16
    # -- Parasolid files ------------------------------------------------------------------
    xt_transmit_bytes: int = 64 * MIB
    xt_nodes: int = 20_000_000
    xt_header_bytes: int = 64 * KIB
    # -- ISO 10303-21 and the B-rep builder -------------------------------------------------
    p21_header_bytes: int = MIB
    p21_record_bytes: int = 16 * MIB
    p21_records: int = 20_000_000
    p21_list_items: int = 10_000_000
    p21_list_depth: int = 32
    p21_string_bytes: int = MIB
    p21_complex_parts: int = 64
    brep_nodes: int = 20_000_000
    bspline_knots: int = 100_000
    # -- STEP --------------------------------------------------------------------------------
    step_products: int = 100_000
    step_occurrences: int = 1_000_000
    step_styled_items: int = 10_000_000
    # -- Alibre Design and ACIS ----------------------------------------------------------------
    ole_streams: int = 256
    alibre_small_stream_bytes: int = 64 * KIB
    alibre_constituents_bytes: int = MIB
    alibre_stream_bytes: int = 512 * MIB
    alibre_text_stream_bytes: int = 64 * MIB
    prop_entries: int = 10_000
    prop_values: int = 10_000
    mesh_dictionary_entries: int = 1_000
    mesh_key_bytes: int = 256
    mesh_blocks: int = 10_000_000
    inclusions: int = 100_000
    resolve_depth: int = 8
    resolve_examined: int = 50_000
    resolve_candidates: int = 5_000
    resolve_seconds: float = 10.0
    sab_records: int = 20_000_000
    sab_subtype_depth: int = 64
    sab_subtypes: int = 10_000_000
    sab_string_bytes: int = 64 * KIB
    sab_values: int = 20_000_000  # values of one SAB stream (about 40 bytes of memory each)

    def __post_init__(self) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            if value is None and f.name == "file_bytes":
                continue
            if f.name in FLOAT_FIELDS:
                ok = (
                    not isinstance(value, bool)
                    and isinstance(value, (int, float))
                    and math.isfinite(value)
                    and value > 0
                )
            else:
                ok = not isinstance(value, bool) and isinstance(value, int) and value > 0
            if not ok:
                raise InvalidArgumentError(
                    f"the limit {f.name} must be a positive number", detail={"parameter": f.name}
                )

    def replace(self, **changes: Any) -> "Limits":
        """A copy with ``changes`` (field names and values) applied, each checked."""
        names = {f.name for f in fields(self)}
        for name in changes:
            if name not in names:
                raise InvalidArgumentError(f"no limit is named {name!r}", detail={"parameter": name})
        return _replace(self, **changes)

    def exceeded(self, name: str, message: str, value: int | None = None) -> SldLimitError:
        """The :class:`SldLimitError` for reaching the bound ``name`` (not raised here)."""
        detail: dict[str, Any] = {"limit": name}
        if value is not None:
            detail["value"] = value
        return SldLimitError(message, detail=detail)


FLOAT_FIELDS = frozenset({"seconds", "render_seconds", "thumbnail_brep_seconds", "resolve_seconds"})
DEFAULT_LIMITS = Limits()


def check_limits(value: Any) -> Limits:
    """``value`` as a :class:`Limits`: None gives the defaults, a mapping the defaults with
    those fields changed; anything else raises ``InvalidArgumentError``."""
    if value is None:
        return DEFAULT_LIMITS
    if isinstance(value, Limits):
        return value
    if isinstance(value, dict):
        return DEFAULT_LIMITS.replace(**value)
    raise InvalidArgumentError("limits must be a Limits object", detail={"parameter": "limits"})


__all__ = ["DEFAULT_LIMITS", "FLOAT_FIELDS", "Limits", "check_limits"]
