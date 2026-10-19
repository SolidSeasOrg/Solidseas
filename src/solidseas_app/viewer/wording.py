"""Plain English for what the library reports as tokens, and safe tooltip text.

The library speaks in stable codes: error codes, listing statuses and reasons,
path roles, stream names, resolution rules. The viewer shows a sentence for
each and keeps the code and the reader's own text for a "Technical details"
line, where an engineer can still find them. An unknown code, since every one
of these sets is open, is shown as it is with its underscores turned into
spaces.

Nothing here imports Qt, so it is tested everywhere.
"""

import html
import os
import re
from typing import Any


def plural(n: int, word: str, many: str | None = None) -> str:
    """``1 part``, ``3 parts``, ``2 assemblies`` (given ``many``), with thousands separators."""
    return f"{n:,} {word if n == 1 else (many or word + 's')}"


def ago(iso: str | None, now: float | None = None) -> str:
    """How long ago an ISO 8601 UTC time was, in words."""
    if not iso:
        return "never"
    import datetime
    import time

    try:
        when = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    seconds = (now if now is not None else time.time()) - when.timestamp()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{plural(int(seconds // 60), 'minute')} ago"
    if seconds < 86400:
        return f"{plural(int(seconds // 3600), 'hour')} ago"
    return f"{plural(int(seconds // 86400), 'day')} ago"


def seconds_text(seconds: float) -> str:
    """``0.31 s``; a time that would round to 0.00 reads ``under 0.01 s``."""
    return "under 0.01 s" if seconds < 0.005 else f"{seconds:.2f} s"


def tip(text: str | None) -> str:
    """Tooltip text that Qt shows as plain text.

    Qt decides by itself whether a tooltip is rich text, and rich text loads the
    images it names: an ``<img src="file://server/share/x.png">`` in a custom
    property or a stored path would make Windows connect to that server when
    the row is hovered. Escaping every tooltip, and wrapping it in ``<qt>`` so
    the decision is always "rich text with no markup", closes that door."""
    if not text:
        return ""
    return "<qt>" + html.escape(str(text)).replace("\n", "<br>") + "</qt>"


def _words(token: str | None) -> str:
    return (token or "").replace("_", " ")


# --------------------------------------------------------------------------- errors
_ERROR_SHORT = {
    "locked": "Locked by another program",
    "damaged_file": "Damaged or incomplete",
    "unknown_format": "Not a SOLIDWORKS file",
    "limit_exceeded": "Over a safety limit",
    "file_too_large": "Too large to read",
    "permission_denied": "Access denied",
    "not_found": "No longer there",
    "link_refused": "Became a link, not followed",
    "placeholder_file": "Cloud placeholder",
    "path_refused": "Refused by a safety rule",
    "timeout": "Took too long to read",
    "mesh_process_stopped": "Mesh reader stopped",
    "format_not_supported": "Not read: a feature SolidSeas lacks",
    "worker_crashed": "The reader stopped",
}
_ERROR_LONG = {
    "locked": "Another program has the file locked, usually SOLIDWORKS while it saves.",
    "damaged_file": "The file is damaged or incomplete: it is not a whole SOLIDWORKS document.",
    "unknown_format": "The file is not a SOLIDWORKS document, although its name says it is.",
    "limit_exceeded": "The document goes past a safety limit SolidSeas keeps while reading.",
    "file_too_large": "The file is larger than SolidSeas will read.",
    "permission_denied": "Windows denied access to the file.",
    "not_found": "The file is no longer there: it was moved or deleted after the folder was listed.",
    "link_refused": "The file became a link after the folder was listed, and SolidSeas never follows links.",
    "placeholder_file": (
        "The file became a cloud placeholder: its data is not on this machine, and SolidSeas never "
        "starts a download."
    ),
    "path_refused": "The path was refused by a safety rule.",
    "timeout": "Reading the file did not finish in time.",
    "worker_crashed": "The reader stopped unexpectedly on this file.",
    "mesh_process_stopped": "The process reading the display mesh stopped before it finished.",
    "internal": "SolidSeas met something in this file it did not expect.",
}
EMPTY_FILE = "The file is empty."
RETRY = "Select another document and then this one again to retry, or press F5 to list the folder again."


def _empty(error: dict[str, Any], size: int | None) -> bool:
    return error.get("code") in ("unknown_format", "damaged_file") and size == 0


def error_short(error: dict[str, Any] | None, size: int | None = None) -> str:
    """A few words for the Status column."""
    error = error or {}
    if _empty(error, size):
        return "Empty file"
    return _ERROR_SHORT.get(error.get("code") or "", "Could not be read")


def technical(error: dict[str, Any] | None, path: str | None = None) -> str:
    """The error code and the reader's own text, with the file's full path shortened
    to its name: what an engineer needs, kept apart from the sentence."""
    error = error or {}
    text = str(error.get("reader_message") or "")
    if path and text:
        text = text.replace(path, os.path.basename(path))
    code = error.get("code") or "unknown"
    return f"{code}: {text}" if text else code


def format_name(path: str | None) -> str | None:
    """The name of the 3D format a file's extension names, when it is not SOLIDWORKS
    (``STEP`` for ``bracket.stp``), else None."""
    if not path:
        return None
    from solidseas.formats import registry

    spec = registry.by_extension(path)
    return spec.name if spec is not None and spec.id != registry.SOLIDWORKS else None


# A model file's errors, where the SOLIDWORKS sentence would be wrong; {fmt} is its format's name.
_MODEL_LONG = {
    "damaged_file": (
        "The file is damaged or incomplete: it is not a whole {fmt} file, or it holds something the "
        "{fmt} reader does not expect."
    ),
    "unknown_format": "The file's content is not {fmt}, although its name says it is, and SolidSeas does not "
    "know what it is.",
    "limit_exceeded": "The file goes past a safety limit SolidSeas keeps while reading {fmt} files.",
}
# Why a format or a feature of a file is not read (FormatNotSupportedError's rule).
_NOT_SUPPORTED = {
    "no_reader": "SolidSeas recognises this as {article} {value} file, but cannot read that format yet.",
    "required_extension": (
        "The file needs an extension of its format that SolidSeas does not read ({value}), so it is not "
        "opened rather than shown wrongly."
    ),
    "compression": "The file's geometry is compressed in a way SolidSeas does not read ({value}).",
    "binary_off": "Binary OFF files are not read; SolidSeas reads OFF text files.",
    "unsupported_variant": "This kind of {fmt} file is not read ({value}).",
    "schema_not_embedded": (
        "This Parasolid file needs a schema file it does not carry inside it, so SolidSeas cannot decode it."
    ),
    "bare_binary": (
        "This is a bare binary Parasolid file, without its text header, which SolidSeas does not read."
    ),
    "user_fields": "This Parasolid file carries user fields, which SolidSeas does not read.",
    "private_schema": (
        "This file is written in a program's own schema (an Alibre Design database), not a STEP model, "
        "so it holds no geometry SolidSeas can read."
    ),
    "archive": "This STEP file is packed in a zip archive, which SolidSeas does not open.",
    "acis_version": (
        "This ACIS file is of a version SolidSeas does not decode; it reads version 2100, the one Alibre "
        "Design writes."
    ),
    "sat_text": "ACIS text files (.sat) are not read yet; SolidSeas reads ACIS binary files (.sab).",
    "encrypted": "The file holds an encrypted part, which SolidSeas does not open.",
}


def not_supported_text(error: dict[str, Any] | None, fmt: str | None = None) -> str:
    """Why a format, or a feature of one file, is not read: the sentence for the rule of a
    ``format_not_supported`` error."""
    detail = (error or {}).get("detail") or {}
    rule, value = detail.get("rule"), str(detail.get("value") or "")
    if rule == "no_reader":
        from solidseas.formats import registry

        spec = registry.FORMATS.get(value)
        value = spec.name if spec is not None else value
    text = _NOT_SUPPORTED.get(rule or "")
    if text is None:
        return (error or {}).get(
            "message"
        ) or "SolidSeas does not read this file's format or one of its features."
    article = "an" if value[:1].upper() in "AEIOU" else "a"
    return text.format(fmt=fmt or "this", value=value or "unknown", article=article)


def error_message(error: dict[str, Any] | None, *, size: int | None = None, path: str | None = None) -> str:
    """The sentence, a retry hint when the error passes, and the technical details. For a
    file of another 3D format (by ``path``'s extension) the sentence names that format."""
    error = error or {}
    code = error.get("code") or ""
    fmt = format_name(path)
    if _empty(error, size):
        sentence = EMPTY_FILE
    elif code == "format_not_supported":
        sentence = not_supported_text(error, fmt)
    elif code == "nothing_to_export" and (error.get("detail") or {}).get("rule") == "no_solid":
        sentence = (
            "The file holds only open surfaces or wires, no solid body, so there is nothing to print or "
            "export as a closed solid. The 3D view still draws the surfaces."
        )
    elif code == "unknown_format" and (error.get("detail") or {}).get("rule") == "unidentified":
        sentence = "SolidSeas could not tell what this file holds: its content matches no 3D format it knows."
    elif fmt and code in _MODEL_LONG:
        sentence = _MODEL_LONG[code].format(fmt=fmt)
    else:
        sentence = _ERROR_LONG.get(code) or error.get("message") or "It could not be read."
    lines = [sentence]
    if error.get("retryable"):
        lines.append(RETRY)
    lines += ["", "Technical details: " + technical(error, path)]
    return "\n".join(lines)


def unusable(error: dict[str, Any] | None) -> bool:
    """Whether a failed read says the file's geometry cannot be read: any error but one
    that passes (a timeout, a stopped worker, a lock) or a cancel."""
    return bool(error) and not error.get("retryable") and error.get("code") != "interrupted"  # type: ignore[union-attr]


def first_sentence(error: dict[str, Any] | None, path: str | None = None) -> str:
    """The first line of what the viewer says of ``error`` (:func:`error_message`)."""
    return error_message(error, path=path).split("\n", 1)[0]


# --------------------------------------------------------------------------- listing entries
_LINKS = {
    "junction": "a junction",
    "symlink": "a symbolic link",
    "name_surrogate": "a link",
    "unreported_tag": "a link of a kind Windows did not name",
    "mount_point": "a mount point (another drive or share mounted here)",
}
_NOT_SOLIDWORKS_SHORT = {"step": "STEP file, wrong extension"}
QUIET_WARNINGS = frozenset({"units_assumed"})  # warnings the Status column does not count


def status_short(entry: dict[str, Any]) -> str:
    """What the Status column says: empty for a document read without trouble."""
    status = entry["status"]
    reason = entry.get("reason")
    size = (entry.get("file") or {}).get("size")
    if status == "ok":
        # A unit an STL or OBJ file cannot state is not news on every row: the Overview says it.
        n = sum(1 for w in entry.get("warnings") or [] if w.get("code") not in QUIET_WARNINGS)
        return plural(n, "warning") if n else ""
    if status == "error":
        return error_short(entry.get("error"), size)
    if status == "not_solidworks":
        return _NOT_SOLIDWORKS_SHORT.get(entry.get("detected") or "", "Not a SOLIDWORKS file")
    if status == "skipped":
        return {
            "lock_file": "SOLIDWORKS lock file",
            "not_regular_file": "Not a regular file",
            "max_depth": "Too deep, not listed",
        }.get(reason or "", "Skipped")
    if status == "link":
        return "Link, not followed"
    if status == "placeholder":
        return "Cloud placeholder"
    if status == "unsupported":
        return "Format not read yet"
    return _words(status).capitalize()


def unread_text(entry: dict[str, Any], path: str | None = None) -> str:
    """The details panel's text for an entry the listing did not read."""
    status = entry["status"]
    reason = entry.get("reason")
    name = entry["path"].rpartition("/")[2]
    size = (entry.get("file") or {}).get("size")
    if status == "error":
        return "This document could not be read.\n\n" + error_message(
            entry.get("error"), size=size, path=path
        )
    if status == "link":
        kind = _LINKS.get(reason or "", "a link")
        text = f"This is {kind}. SolidSeas never follows links, so it was not opened."
    elif status == "placeholder":
        text = (
            "This is a cloud placeholder: its data is in the cloud, not on this machine. SolidSeas never "
            "opens one, so no download was started."
        )
    elif status == "skipped" and reason == "lock_file":
        doc = name[2:] if name.startswith("~$") else name
        text = (
            f"A SOLIDWORKS lock file. SOLIDWORKS keeps it while someone has {doc} open and deletes it "
            "when they close it. Lock files are never read."
        )
    elif status == "skipped" and reason == "not_regular_file":
        text = "This is not a regular file (a pipe, socket or device), so it was never opened."
    elif status == "skipped" and reason == "max_depth":
        text = "This folder is deeper than the listing goes, so it was not listed."
    elif status == "unsupported":
        fmt = (entry.get("model") or {}).get("format_name") or entry.get("detected") or "this"
        article = "an" if fmt[:1].upper() in "AEIOU" else "a"
        text = (
            f"SolidSeas recognises this as {article} {fmt} file, but cannot read that format yet. It is "
            "listed so you can see it is here, and it was not opened. Turn off View > Show > Files "
            "SolidSeas Cannot Read to hide such files."
        )
    elif status == "not_solidworks" and entry.get("detected") == "step":
        text = (
            "This is a STEP file with a SOLIDWORKS extension. It was not opened as a SOLIDWORKS document; "
            "turn on View > Show > All 3D Files to have SolidSeas read it as the STEP file it is."
        )
    elif status == "not_solidworks":
        text = "This file is not a SOLIDWORKS document, although its name says it is."
    else:
        text = f"Not read ({_words(status)})."
    if reason or entry.get("detected"):
        text += f"\n\nTechnical details: {status}: {reason or entry.get('detected')}"
    return text


# --------------------------------------------------------------------------- references
REFERENCE_STATUS = {
    "resolved": "found",
    "moved": "moved",
    "embedded": "inside this document",
    "embedded_not_found": "inside, but missing",
    "embedded_in_subassembly": "inside a sub-assembly",
    "ambiguous": "ambiguous",
    "missing": "missing",
}
RULES = {
    "embedded": "stored inside this document",
    "stored_unmoved": "at its saved location",
    "path_map": "through a path mapping",
    "rebased": "same place relative to this document",
    "same_folder": "in this document's folder",
    "suffix_probe": "the folder search SOLIDWORKS does",
    "stored_path": "at its saved location, this document moved",
    "name_index": "by name in the opened folder",
    "name_index_suffix": "by name and folder names",
    "document_guid": "by its document GUID, in the assembly's folder",
}


def reference_status(status: str | None) -> str:
    return REFERENCE_STATUS.get(status or "", _words(status) or "not resolved")


def rule_text(rule: str | None) -> str:
    return RULES.get(rule or "", _words(rule))


# --------------------------------------------------------------------------- paths report
ROLES = {
    "references": "a referenced file",
    "imported_from": "imported from here",
    "save_location": "where it was saved",
    "resources": "a resource it uses",
    "history": "save history",
    "other": "other",
}
NAME_SOURCES = {
    "path": "stored paths",
    "header2_user": "the file's list of users",
    "core_last_modified_by": "last modified by",
    "core_creator": "creator",
    "sw_author": "the Author property",
    "sw_last_saved_by": "last saved by",
    "summary_author": "the summary's author",
    "summary_last_author": "the summary's last author",
    "file_name_at_save": "file name at save",
}
_STREAMS = (
    (re.compile(r"_MO_VERSION_\d+/Biography"), "save history"),
    (re.compile(r"_MO_VERSION_\d+/History"), "version history"),
    (re.compile(r"Header2"), "file header"),
    (re.compile(r"docProps/core\.xml"), "document properties"),
    (re.compile(r"docProps/app\.xml"), "application properties"),
    (re.compile(r"docProps/ISolidWorksInformation\.xml|ISolidWorksInformation"), "SOLIDWORKS information"),
    (re.compile(r"swXmlContents/COMPINSTANCETREE"), "component tree"),
    (re.compile(r"swXmlContents/KeyWords"), "keywords"),
    (re.compile(r"SwDocContentMgr/SwDocContentMgrInfo"), "content manager"),
    (re.compile(r"Contents/Config-\d+-ModelHeader"), "model header"),
    (re.compile(r"Contents/DisplayLists"), "display lists"),
    (re.compile(r"\x05?SummaryInformation"), "summary information"),
    (re.compile(r"\x05?DocumentSummaryInformation"), "document summary information"),
    (re.compile(r"Preview(PNG)?"), "preview"),
)


def role_text(role: str) -> str:
    return ROLES.get(role, _words(role))


def name_source(source: str) -> str:
    return NAME_SOURCES.get(source, _words(source))


def field_text(field: str) -> str:
    text = name_source(field)
    return text[:1].upper() + text[1:]


def sentence(text: str) -> str:
    """``text`` begun as a sentence: its first letter a capital, unless its first word is a
    name that keeps its own case, one with a capital after its first letter (``glTF
    files hold...``, ``eDrawings``)."""
    first = text.split(" ", 1)[0]
    if any(c.isupper() for c in first[1:]):
        return text
    return text[:1].upper() + text[1:]


def stream_text(stream: str | None) -> str:
    """Where in the file: ``save history`` for ``_MO_VERSION_17000/Biography``. An
    unknown stream keeps its name."""
    if not stream:
        return "-"
    for pattern, text in _STREAMS:
        if pattern.fullmatch(stream):
            return text
    return stream


# --------------------------------------------------------------------------- export refusals
_REFUSALS = {
    "source_folder": (
        "That folder is the folder you opened, the document's own folder, or a folder inside one of them. "
        "SolidSeas never writes where it reads. Choose a folder somewhere else."
    ),
    "exists": (
        "A file with that name is already in the output folder. Tick Overwrite existing files to replace "
        "it, or choose another folder."
    ),
    "solidworks_file": "The output would have a SOLIDWORKS file name, and SolidSeas never writes one.",
    "source_document": "The output would replace the document itself.",
    "hard_link": (
        "A file of that name is in the output folder, and it is a hard link: another name shares its data, "
        "so replacing it could change another file. Choose another folder."
    ),
    "link": (
        "A file of that name is in the output folder, and it is a link to somewhere else. Writing would "
        "follow it, so it is left alone. Choose another folder."
    ),
    "device_path": "That is a device or extended-length path. Choose an ordinary folder.",
    "alternate_stream": "That path names an alternate data stream. Choose an ordinary folder.",
    "no_file_name": "That path has no usable file name.",
}


def refusal_text(error: dict[str, Any] | None) -> str:
    """Why a write guard refused an export, in the window's terms (it has no command-line flags)."""
    rule = ((error or {}).get("detail") or {}).get("rule")
    return _REFUSALS.get(rule or "", "A write guard refused the output location.")


# --------------------------------------------------------------------------- the 3D view of an assembly
NOT_SHOWN = {
    "missing": "file not found",
    "ambiguous": "several files could be its file",
    "no_mesh": "no saved display mesh",
    "no_source": "no saved display mesh",
    "embedded_not_found": "virtual component the assembly does not store",
    "unreadable": "file could not be read",
    "not_part": "not a part",
    "no_placement": "position could not be read",
    "model_missing": "not in the component tree",
    "no_components": "sub-assembly lists no components",
    "cycle": "sub-assembly contains itself",
    "truncated": "past the component tree's limit",
    "max_files": "limit on files read",
    "max_triangles": "triangle limit",
    "max_bytes": "display data limit",
    "max_drawn": "limit on triangles drawn",
    "brep_failed": "geometry could not be tessellated",
    "bodies_not_asked": "no body of a type drawn",
    "max_brep_seconds": "time limit on tessellation",
    "component_not_found": "component file not found or not readable",
    "components_limit": "limit on component files read",
    "non_finite_placement": "position could not be read",
    "out_of_range": "placed impossibly far away",
    "max_seconds": "time limit on tessellation",
}
LIMITS = ("max_triangles", "max_bytes", "max_drawn")  # a higher triangle limit raises each of them
SOURCES = {
    "assembly": "the meshes the assembly stores",
    "subassembly": "the meshes its sub-assemblies store",
    "nested": "the virtual components stored in it",
    "file": "the component files' own meshes",
    "brep": "the parts' own geometry",
    "mesh": "the file's own triangles",
    "bodies": "its B-rep bodies, tessellated",
    "display_mesh": "the display meshes the file stores",
}
# The status line names a few instances for each reason, and only so many in all, so it stays a
# line or two however large the assembly (ids are paths, and can be long); the reasons past them
# are counted. Its tooltip names more, within bounds of its own.
_NAMES_PER_REASON = 3
_NAMES_IN_LINE = 6
_LINE_CHARS = 200  # of names in the line, about
_TIP_NAMES = 60  # for each reason
_TIP_CHARS = 4000  # of names in the tooltip, about
BOXES_SETTING = "Settings > Boxes for Missing Meshes"


def _take(names: list[str], most: int, budget: list[int]) -> list[str]:
    """The first of ``names``, at most ``most``, while ``budget[0]`` characters are left
    (spending them; the last name taken may pass it)."""
    out = []
    for n in names[:most]:
        if budget[0] <= 0:
            break
        out.append(n)
        budget[0] -= len(n) + 2
    return out


def _named(names: list[str], shown: list[str]) -> str:
    more = len(names) - len(shown)
    return ", ".join(shown) + (" and " if shown and more else "") + (f"{more:,} more" if more else "")


def not_shown(reason: str | None) -> str:
    """Why an instance has no mesh drawn, in words: ``file not found`` for ``missing``."""
    return NOT_SHOWN.get(reason or "", _words(reason))


def box_text(ident: str, name: str | None, reason: str | None) -> str:
    """The hover text of an instance drawn as a box."""
    what = f"{ident} ({name})" if name else ident
    return f"{what}: no mesh drawn ({not_shown(reason)}), so it is drawn as the box its assembly stores"


def sources_text(sources: list[str]) -> str:
    """``the meshes the assembly stores and the component files' own meshes``."""
    words = [SOURCES.get(s, _words(s)) for s in sources]
    if len(words) <= 1:
        return words[0] if words else "the saved display meshes"
    return ", ".join(words[:-1]) + " and " + words[-1]


def faces_left_out_text(left: dict[str, Any] | None) -> tuple[str, str]:
    """The status line of a 3D view whose model has faces that could not be tessellated
    (``faces_left_out`` of :func:`.mesh3d.read_model_scene`), and its tooltip, which says
    why for each reason. Both are empty when no face was left out."""
    if not left or not left.get("count"):
        return "", ""
    from solidseas.tessellate import REASONS

    n = left["count"]
    line = (
        f"{plural(n, 'face')} of this model could not be drawn, so the view has "
        f"{'a hole' if n == 1 else 'holes'} there."
    )
    reasons = sorted((left.get("reasons") or {}).items(), key=lambda kv: -kv[1])
    full = [f"{plural(k, 'face')}: {REASONS.get(why, _words(why))}" for why, k in reasons]
    return line, "\n".join(full)


def not_shown_text(info: dict[str, Any], cap: int | None = None, *, boxes: bool = False) -> tuple[str, str]:
    """The status line of an assembly's 3D view, and its tooltip. With ``boxes`` (the view
    draws a box for each instance without a mesh that has a stored one), how many are
    drawn so, counted by reason, which keeps the line short however many there are; then
    which instances are not shown at all and why, grouped by reason, with a few names
    each and only so many in all (:data:`_NAMES_IN_LINE`, :data:`_LINE_CHARS`); which
    limits were reached; and the meshes that show another configuration than the one
    used, in one sentence when there are several. The tooltip names the instances of
    each reason, boxes included, within bounds too (:data:`_TIP_NAMES`,
    :data:`_TIP_CHARS`), as far as the result lists them.
    Without ``boxes``, every instance not drawn from a mesh is not shown, and the line
    says how many could be boxes. Both are empty when there is nothing to say."""
    lines: list[str] = []
    full: list[str] = []
    tip = [_TIP_CHARS]
    count = info.get("skipped_count") or 0
    ph = info.get("placeholders") or {}
    boxed = set(ph.get("ids") or ()) if boxes else set()
    if boxed:
        count -= len(boxed)
        by_why: dict[str, list[str]] = {}
        for ident, reason in zip(ph["ids"], ph["reasons"], strict=True):
            by_why.setdefault(not_shown(reason), []).append(ident)
        ranked = sorted(by_why.items(), key=lambda kv: -len(kv[1]))
        counts = ", ".join(f"{why}: {len(ids):,}" for why, ids in ranked)
        lines.append(f"Drawn as boxes, with no mesh drawn: {plural(len(boxed), 'instance')} ({counts}).")
        for why, ids in ranked:
            full.append(f"drawn as a box, {why}: {_named(ids, _take(ids, _TIP_NAMES, tip))}")
    damaged = ph.get("implausible") or 0
    if boxes and damaged:
        lines.append(
            f"{plural(damaged, 'stored box', 'stored boxes')} reaching far past the assembly's own "
            f"{'is' if damaged == 1 else 'are'} taken as damaged and not drawn."
        )
    if count:
        by_reason: dict[str, list[str]] = {}
        for s in info.get("skipped") or []:
            if s.get("id") in boxed:
                continue
            # The instance's path from the top: a name alone can be another instance's too.
            name = s.get("id") or s["name"]
            by_reason.setdefault(not_shown(s["reason"]), []).append(name)
        listed = sum(len(v) for v in by_reason.values())
        parts = []
        left, chars = _NAMES_IN_LINE, [_LINE_CHARS]
        for why, names in by_reason.items():
            shown = _take(names, min(_NAMES_PER_REASON, left), chars)
            left -= len(shown)
            parts.append(f"{_named(names, shown) if shown else f'{len(names):,}'} ({why})")
            full.append(f"{why}: {_named(names, _take(names, _TIP_NAMES, tip))}")
        if count > listed:
            parts.append(f"{count - listed:,} more")
        lines.append(f"Not shown: {plural(count, 'instance')}: " + "; ".join(parts) + ".")
        if not boxes and ph.get("count"):
            lines.append(f"{BOXES_SETTING} draws {plural(ph['count'], 'of them', 'of them')} as boxes.")
    truncated = info.get("truncated") or []
    cap = cap or info.get("cap")
    if {"max_triangles", "max_bytes"} & set(truncated):
        limit = f" of {cap:,} triangles" if cap else ""
        lines.append(
            f"The 3D view's limit{limit} was reached before every mesh was read. Raise it under "
            "Settings > 3D View to draw the rest."
        )
    if "max_drawn" in truncated:
        drawn = info.get("drawn_cap")
        most = f"at most {drawn:,} triangles" if drawn else "a limited number of triangles"
        lines.append(
            f"The 3D view draws {most} for all the instances together (each instance draws its "
            "mesh again), so the instances past that are not shown. A higher triangle limit under "
            "Settings > 3D View draws more."
        )
    if "max_instances" in truncated:
        lines.append(
            "The assembly reaches the 3D view's limit on instances expanded: those past it are left out, "
            "or drawn without their meshes."
        )
    differs = [
        w.get("file") or "A component"
        for w in info.get("mesh_warnings") or []
        if w.get("code") == "mesh_configuration_differs"
    ]
    if len(differs) == 1:
        lines.append(
            f"{differs[0]} shows the configuration its own file was saved in, which is not the one the "
            "assembly uses, so its shape may differ."
        )
    elif differs:  # one sentence however many, so the line stays short; the tooltip names them all
        named = ", ".join(differs[:_NAMES_PER_REASON])
        more = len(differs) - _NAMES_PER_REASON
        lines.append(
            f"{len(differs):,} components ({named}{f' and {more:,} more' if more > 0 else ''}) show the "
            "configuration their own files were saved in, which is not the one the assembly uses, so their "
            "shapes may differ."
        )
        full.append(f"shape may differ, another configuration: {', '.join(differs)}")
    holes, why = faces_left_out_text(info.get("faces_left_out"))
    if holes:
        lines.append(holes)
        full.append(why)
    return " ".join(lines), "\n".join(full)
