"""Builders for synthetic documents used by the tests.

* :func:`build_cfb` writes a minimal MS-CFB compound file, version 3 (512-byte
  sectors) or version 4 (4096-byte sectors), with a mini stream for streams
  under 4096 bytes: enough for a legacy SOLIDWORKS-style container. Written
  from the public [MS-CFB] specification.
* :func:`build_propset` writes an MS-OLEPS property set stream.
* :func:`wrap_zlb` and :func:`zlb_chain` write the SOLIDWORKS ZLB framing.
* :func:`build_modern` writes a 2015+ style container without decoys.

None of this is used by the library; it exists so that the legacy and modern
readers can be tested without real customer files.
"""

import struct
import uuid
import zlib

from solidseas.formats.solidworks.modern import encode_name
from solidseas.formats.solidworks.zlb import ZLB_MAGIC

SECTOR, MINI, CUTOFF = 512, 64, 4096
FREESECT, ENDOFCHAIN, FATSECT, NOSTREAM = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFF
PART_CLSID = "{83A33D30-27C5-11CE-BFD4-00400513BB57}"


def guid_bytes(text: str) -> bytes:
    return uuid.UUID(text).bytes_le


# --------------------------------------------------------------------------- ZLB
def wrap_zlb(data: bytes, chunk: int = 1 << 16) -> bytes:
    out = bytearray(ZLB_MAGIC)
    for i in range(0, len(data), chunk):
        part = data[i : i + chunk]
        comp = zlib.compress(part, 1)
        out += struct.pack("<II", len(part), len(comp)) + comp
    out += struct.pack("<II", 0, 0)
    return bytes(out)


def zlb_chain(blocks: list[bytes]) -> bytes:
    out = bytearray()
    for b in blocks:
        z = wrap_zlb(b) if b else b""
        out += struct.pack("<I", len(z)) + z
    return bytes(out)


# --------------------------------------------------------------------------- MS-OLEPS
def _python_codec(codepage: int) -> str:
    return "utf-8" if codepage == 65001 else f"cp{codepage}"


def _typed_value(vt: int, value, codec: str = "utf-8") -> bytes:
    head = struct.pack("<HH", vt, 0)
    if vt == 2:  # VT_I2 (a code page such as 65001 is stored as the same 16 bits)
        body = struct.pack("<HH", value & 0xFFFF, 0)
    elif vt == 3:  # VT_I4
        body = struct.pack("<i", value)
    elif vt == 5:  # VT_R8
        body = struct.pack("<d", value)
    elif vt == 0x0B:  # VT_BOOL
        body = struct.pack("<hH", -1 if value else 0, 0)
    elif vt == 0x1E:  # VT_LPSTR, in the section's code page
        raw = value.encode(codec) + b"\0"
        body = struct.pack("<I", len(raw)) + raw
    elif vt == 0x40:  # VT_FILETIME
        body = struct.pack("<Q", value)
    else:
        raise ValueError(f"unsupported VT {vt}")
    data = head + body
    return data + b"\0" * (-len(data) % 4)


def _dictionary(names: dict[int, str], codec: str = "utf-8") -> bytes:
    out = bytearray(struct.pack("<I", len(names)))
    for pid, name in names.items():
        raw = name.encode(codec) + b"\0"
        out += struct.pack("<II", pid, len(raw)) + raw
    out += b"\0" * (-len(out) % 4)
    return bytes(out)


def _section(props: list[tuple[int, int, object]], names: dict[int, str] | None, codepage: int) -> bytes:
    codec = _python_codec(codepage)
    items: list[tuple[int, bytes]] = [(1, _typed_value(2, codepage))]
    if names:
        items.insert(0, (0, _dictionary(names, codec)))
    items += [(pid, _typed_value(vt, value, codec)) for pid, vt, value in props]
    header_len = 8 + 8 * len(items)
    offsets, body, pos = [], bytearray(), header_len
    for pid, data in items:
        offsets.append((pid, pos))
        body += data
        pos += len(data)
    out = struct.pack("<II", header_len + len(body), len(items))
    out += b"".join(struct.pack("<II", pid, off) for pid, off in offsets)
    return out + bytes(body)


def build_propset(sections: list[tuple], codepage: int = 65001) -> bytes:
    """``sections``: ``[(fmtid, [(pid, vt, value)], names or None[, codepage])]``. A
    section keeps its strings and names in its own code page when it gives one, else in
    ``codepage``: 65001 is UTF-8, any other number the Windows code page ``cp<n>``."""
    head_len = 28 + 20 * len(sections)
    bodies = [_section(s[1], s[2], s[3] if len(s) > 3 else codepage) for s in sections]
    out = bytearray(
        struct.pack("<HHI", 0xFFFE, 0, 0x00020006) + b"\0" * 16 + struct.pack("<I", len(sections))
    )
    pos = head_len
    for (fmtid, *_rest), body in zip(sections, bodies, strict=True):
        out += guid_bytes(fmtid) + struct.pack("<I", pos)
        pos += len(body)
    for body in bodies:
        out += body
    return bytes(out)


# --------------------------------------------------------------------------- MS-CFB
def _cfb_key(name: str) -> tuple[int, str]:
    return (len(name), name.upper())


def build_cfb(streams: dict[str, bytes], root_clsid: str = PART_CLSID, *, sector: int = SECTOR) -> bytes:
    """A compound file holding ``streams`` (``/``-separated storage paths): version 3
    with 512-byte sectors, or version 4 with ``sector=4096``."""
    if sector not in (512, 4096):
        raise ValueError("sector must be 512 (version 3) or 4096 (version 4)")
    root: dict = {"name": "Root Entry", "type": 5, "children": {}, "data": b""}
    for path, data in streams.items():
        parts = path.split("/")
        node = root
        for p in parts[:-1]:
            node = node["children"].setdefault(p, {"name": p, "type": 1, "children": {}, "data": b""})
        node["children"][parts[-1]] = {"name": parts[-1], "type": 2, "children": {}, "data": data}
    entries: list[dict] = []

    def number(node: dict) -> None:
        node["id"] = len(entries)
        entries.append(node)
        for child in sorted(node["children"].values(), key=lambda n: _cfb_key(n["name"])):
            number(child)

    number(root)
    for node in entries:
        kids = sorted(node["children"].values(), key=lambda n: _cfb_key(n["name"]))
        node["child"] = kids[0]["id"] if kids else NOSTREAM
        for k, kid in enumerate(kids):  # a right-sibling chain in CFB order is a valid search tree
            kid["right"] = kids[k + 1]["id"] if k + 1 < len(kids) else NOSTREAM
    root.setdefault("right", NOSTREAM)

    # mini stream for small streams
    mini = bytearray()
    minifat: list[int] = []
    for node in entries:
        if node["type"] == 2 and len(node["data"]) < CUTOFF:
            data = node["data"]
            n = max(1, -(-len(data) // MINI))
            start = len(minifat)
            minifat += [start + k + 1 for k in range(n - 1)] + [ENDOFCHAIN]
            node["start"] = start
            mini += data + b"\0" * (n * MINI - len(data))
    # regular sectors: big streams, mini stream, mini FAT, directory
    sectors: list[bytes] = []
    fat: list[int] = []

    def place(data: bytes, mark: int | None = None) -> int:
        n = max(1, -(-len(data) // sector))
        start = len(sectors)
        for k in range(n):
            sectors.append(data[k * sector : (k + 1) * sector].ljust(sector, b"\0"))
            fat.append(mark if mark is not None else (start + k + 1 if k < n - 1 else ENDOFCHAIN))
        return start

    for node in entries:
        if node["type"] == 2 and len(node["data"]) >= CUTOFF:
            node["start"] = place(node["data"])
    root["start"] = place(bytes(mini)) if mini else ENDOFCHAIN
    root["data"] = bytes(mini)
    minifat_bytes = b"".join(struct.pack("<I", x) for x in minifat)
    minifat_bytes += struct.pack("<I", FREESECT) * (-(len(minifat_bytes) // 4) % (sector // 4))
    first_minifat = place(minifat_bytes) if minifat else ENDOFCHAIN
    n_minifat = -(-len(minifat_bytes) // sector) if minifat else 0
    dir_bytes = bytearray()
    for node in entries:
        name = node["name"].encode("utf-16-le") + b"\0\0"
        size = len(node["data"]) if node["type"] in (2, 5) else 0
        start = node.get("start", 0) if node["type"] != 1 else 0
        clsid = guid_bytes(root_clsid) if node["type"] == 5 else b"\0" * 16
        dir_bytes += struct.pack(
            "<64sHBBIII16sIQQIQ",
            name,
            len(name),
            node["type"],
            1,
            NOSTREAM,
            node.get("right", NOSTREAM),
            node["child"],
            clsid,
            0,
            0,
            0,
            start,
            size,
        )
    dir_bytes += b"\0" * (-len(dir_bytes) % sector)
    n_dir = len(dir_bytes) // sector
    first_dir = place(bytes(dir_bytes))
    # FAT sectors (must cover themselves)
    n_fat = 1
    while (len(sectors) + n_fat) > n_fat * (sector // 4):
        n_fat += 1
    fat_ids = list(range(len(sectors), len(sectors) + n_fat))
    fat += [FATSECT] * n_fat
    fat += [FREESECT] * (n_fat * (sector // 4) - len(fat))
    fat_bytes = b"".join(struct.pack("<I", x) for x in fat)
    for k in range(n_fat):
        sectors.append(fat_bytes[k * sector : (k + 1) * sector])
    if n_fat > 109:
        raise ValueError("too many FAT sectors for a header-only DIFAT")
    header = struct.pack(
        "<8s16sHHHHH6sIIIIIIIII",
        bytes.fromhex("d0cf11e0a1b11ae1"),
        b"\0" * 16,
        0x3E,
        3 if sector == 512 else 4,
        0xFFFE,
        9 if sector == 512 else 12,
        6,
        b"\0" * 6,
        0 if sector == 512 else n_dir,  # version 3 must store 0 here
        n_fat,
        first_dir,
        0,
        CUTOFF,
        first_minifat,
        n_minifat,
        ENDOFCHAIN,
        0,
    )
    difat = fat_ids + [FREESECT] * (109 - len(fat_ids))
    header += b"".join(struct.pack("<I", x) for x in difat)
    assert len(header) == 512  # a version 4 header is padded to its 4096-byte sector
    return header.ljust(sector, b"\0") + b"".join(sectors)


# --------------------------------------------------------------------------- 2015+ container
def build_modern(
    members: dict[str, bytes], *, declared: dict[str, int] | None = None, key: bytes = b"\x10\x20\x30\x40"
) -> bytes:
    """A 2015+ style container (no decoys) with arbitrary record signatures.

    ``declared`` overrides the declared uncompressed size of some members, to
    build inconsistent files for the safety tests.
    """
    sig_l, sig_c, sig_e = b"\x11\x22\x33\x44", b"\x55\x66\x77\x88", b"\x99\xaa\xbb\xcc"
    body = bytearray()
    cd = bytearray()
    for name, data in members.items():
        comp = zlib.compressobj(1, zlib.DEFLATED, -15)
        stored = comp.compress(data) + comp.flush()
        crc = zlib.crc32(data)
        usize = (declared or {}).get(name, len(data))
        raw_name = encode_name(name)
        offset = len(body)
        body += sig_l + struct.pack("<HHHHHIIIHH", 20, 6, 8, 0, 0, crc, len(stored), usize, len(raw_name), 0)
        body += raw_name + stored
        cd += (
            sig_c
            + struct.pack(
                "<HHHHHHIIIHHHHHII",
                0,
                20,
                6,
                8,
                0,
                0,
                crc,
                len(stored),
                usize,
                len(raw_name),
                0,
                0,
                0,
                0,
                0,
                offset,
            )
            + raw_name
        )
    cd_offset = len(body)
    eocd = sig_e + struct.pack("<HHHHIIH", 0, 0, len(members), len(members), len(cd), cd_offset, 0)
    return key + b"\x00\x00\x00\x04" + bytes(body) + bytes(cd) + eocd


def fixture_streams(path) -> dict[str, bytes]:
    """Every decoded stream of a fixture document, in directory order."""
    from solidseas.formats.solidworks import open_container

    with open_container(path) as c:
        return {n: c.read(n) for n in c.names()}


def rebuild(path, changes: dict[str, bytes] | None = None, *, drop: tuple[str, ...] = ()) -> bytes:
    """A fixture's streams as a new 2015+ container, with some streams replaced,
    added (``changes``) or left out (``drop``)."""
    streams = {n: d for n, d in fixture_streams(path).items() if n not in drop}
    streams.update(changes or {})
    return build_modern(streams)


# --------------------------------------------------------------------------- crafted fixtures
def o06_with_active_alt() -> bytes:
    """o06 as if saved with OracleAlt active: the configuration with a property of its
    own (``CfgOnly``), so its effective properties differ from the file-level ones."""
    from support import fixture_path

    o06 = fixture_path("o06_boxA_props_mat_cfg.SLDPRT")
    streams = fixture_streams(o06)
    isw = streams["docProps/ISolidWorksInformation.xml"]
    old = b'name="SW-Configuration Name" pid="8"><vt:lpstr>Default</vt:lpstr>'
    assert isw.count(old) == 1
    isw = isw.replace(old, b'name="SW-Configuration Name" pid="8"><vt:lpstr>OracleAlt</vt:lpstr>')
    tree = streams["swXmlContents/Features"]
    tree = tree.replace(
        b'swName="Default" swID="0" swReference="Part8" swMostRecentConfiguration="YES"',
        b'swName="Default" swID="0" swReference="Part8" swMostRecentConfiguration="NO"',
    )
    tree = tree.replace(
        b'swName="OracleAlt" swID="1" swReference="Part8" swMostRecentConfiguration="NO"',
        b'swName="OracleAlt" swID="1" swReference="Part8" swMostRecentConfiguration="YES"',
    )
    return rebuild(o06, {"docProps/ISolidWorksInformation.xml": isw, "swXmlContents/Features": tree})


def o05_with_ghost_configuration() -> bytes:
    """o05 whose MATERIALTREE names a configuration "Ghost" that no other carrier has:
    the reader warns ``materialtree_unknown_configuration``."""
    from support import fixture_path

    o05 = fixture_path("o05_boxA_props_mat.SLDPRT")
    text = fixture_streams(o05)["swXmlContents/MATERIALTREE"].decode("utf-16")
    ghost = (
        '<configuration name="Ghost" material="SOLIDWORKS Materials|1060 Alloy|14"/>\n</configurationslist>'
    )
    assert text.count("</configurationslist>") == 1
    mt = text.replace("</configurationslist>", ghost).encode("utf-16")
    return rebuild(o05, {"swXmlContents/MATERIALTREE": mt})


# --------------------------------------------------------------------------- component trees
IDENTITY_TRANSFORM = "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"


def transform_text(rotation_rows=((1, 0, 0), (0, 1, 0), (0, 0, 1)), translation=(0, 0, 0), scale=1) -> str:
    """``swTransform`` text for ``p_parent = R p + t``: the columns of ``R`` (the images of
    the X, Y and Z axes) in elements 0-2, 4-6 and 8-10, ``t`` in 12-14, the scale in 15."""
    r = rotation_rows
    cols = [[r[i][j] for i in range(3)] for j in range(3)]
    values = [*cols[0], 0, *cols[1], 0, *cols[2], 0, *translation, scale]
    return " ".join(repr(float(v)) for v in values)


def _attrs(values: dict) -> str:
    from xml.sax.saxutils import quoteattr

    return "".join(f" {k}={quoteattr(str(v))}" for k, v in values.items() if v is not None)


class TreeXml:
    """A ``swXmlContents/COMPINSTANCETREE`` document written from scratch.

    ``file`` adds a ``swFile``, ``model`` a ``swModel`` (a document in one
    configuration), ``ref`` an instance under a model and ``configuration`` an
    assembly configuration whose top model is given. The assembly's own file is
    ``"1"``; ``top`` adds its model for one configuration.
    """

    def __init__(self) -> None:
        self.files: list[dict] = [{"id": "1", "swDocType": "ASSEMBLY", "swPath": "top.sldasm"}]
        self.models: dict[str, dict] = {}
        self.configs: list[tuple[dict, list[tuple[str, str]] | None]] = []
        self._next_ref = 1000

    def file(self, fid: str, path: str, doc_type: str = "PART", **attrs) -> str:
        self.files.append({"id": fid, "swDocType": doc_type, "swPath": path, **attrs})
        return fid

    def model(self, mid: str, file: str, config: str = "Default", *, bbox: str | None = None, **more) -> str:
        """A ``swModel``; ``bbox`` is its ``swBoundingBox`` text (low then high corner, metres),
        and ``more`` further attributes (``swConfigurationAlternateName``...)."""
        attrs = {"id": mid, "swConfigurationName": config, "swFileRef": file, "swBoundingBox": bbox, **more}
        self.models[mid] = {"attrs": attrs, "refs": []}
        return mid

    def top(self, mid: str, config: str = "Default", *, most_recent: bool = True, display=None) -> str:
        """The assembly's own model for ``config``, and the configuration naming it."""
        self.model(mid, "1", config)
        self.configuration(config, mid, most_recent=most_recent, display=display)
        return mid

    def configuration(self, name: str, model: str, *, most_recent: bool = True, display=None) -> None:
        attrs = {
            "id": f"c{len(self.configs)}",
            "swName": name,
            "swID": str(len(self.configs)),
            "swMostRecentConfiguration": "YES" if most_recent else "NO",
            "swModelRef": model,
        }
        self.configs.append((attrs, display))

    def ref(
        self,
        parent: str,
        name: str,
        number,
        model: str,
        *,
        config: str = "Default",
        suppressed: bool = False,
        hidden: bool = False,
        excluded: bool = False,
        virtual: bool = False,
        transform: str | None = IDENTITY_TRANSFORM,
        sw_id=None,
    ) -> None:
        self._next_ref += 1
        self.models[parent]["refs"].append(
            {
                "id": str(self._next_ref),
                "swName": name,
                "swReferenceNumber": str(number) if number is not None else None,
                "swComponentName": name,
                "swID": str(sw_id) if sw_id is not None else None,
                "swIsVirtualComponent": "YES" if virtual else "NO",
                "swConfigurationName": config,
                "swSuppressed": "YES" if suppressed else "NO",
                "swHidden": "YES" if hidden else "NO",
                "swExcludeFromBOM": "YES" if excluded else "NO",
                "swModelRef": model,
                "swTransform": transform,
            }
        )

    def xml(self) -> bytes:
        parts = ['<?xml version="1.0" encoding="UTF-8"?>\r\n']
        parts.append('<swSolidWorks xmlns="http://www.solidworks.com/sw2003/schema" swVersion="17000">')
        parts.append("<swHeader>")
        parts += [f"<swFile{_attrs(f)}/>" for f in self.files]
        parts.append("</swHeader><swModelList>")
        for m in self.models.values():
            refs = "".join(f"<swReference{_attrs(r)}/>" for r in m["refs"])
            parts.append(f"<swModel{_attrs(m['attrs'])}>{refs}</swModel>")
        parts.append("</swModelList><swConfigurationList>")
        for attrs, display in self.configs:
            inner = ""
            if display is not None:
                ids = "".join(f"{i}," for i, _ in display)
                shows = "".join(f"{s}," for _, s in display)
                inner = (
                    f'<swDisplayStateList id="d{attrs["id"]}" swCompNameList="{ids}">'
                    f'<swDisplayState swDisplayStateName="Display State-1" swShowState="{shows}"/>'
                    "</swDisplayStateList>"
                )
            parts.append(f"<swConfiguration{_attrs(attrs)}>{inner}</swConfiguration>")
        parts.append("</swConfigurationList></swSolidWorks>")
        return "".join(parts).encode("utf-8")


def assembly_with_tree(tree: "TreeXml | bytes", members: dict[str, bytes] | None = None, *, drop=()) -> bytes:
    """o08 with its component tree replaced by ``tree`` and ``members`` added (for example
    ``VirtualComp/...`` nested documents). o08's active configuration is ``Default``."""
    from support import ASSEMBLY, fixture_path

    xml = tree.xml() if isinstance(tree, TreeXml) else tree
    changes = {"swXmlContents/COMPINSTANCETREE": xml, **(members or {})}
    return rebuild(fixture_path(ASSEMBLY), changes, drop=drop)


def part_with_creation_time(
    ct: int | None, *, stamps: bool = True, tree: bool = True, keywords: bool = True
) -> bytes:
    """o02 claiming creation time ``ct`` in every carrier resolution reads: ``ModelStamps``
    element 0, its own ``swFile`` in ``Features`` and the ``KeyWords`` root id. A carrier
    switched off loses the value (``ModelStamps`` is dropped; the others hold 0). The
    value replaced is o02's own creation time, read from ``ModelStamps``; each of the
    other two carriers must hold it exactly once."""
    from support import fixture_path

    o02 = fixture_path("o02_boxA.SLDPRT")
    s = fixture_streams(o02)
    own = str(struct.unpack("<I", s["ModelStamps"][:4])[0]).encode()
    value = str(ct if ct is not None else 0).encode()
    feats = s["swXmlContents/Features"]
    old = b'swCreationTime="' + own + b'"'
    assert feats.count(old) == 1
    feats = feats.replace(old, b'swCreationTime="' + (value if tree else b"0") + b'"')
    kw = s["swXmlContents/KeyWords"]
    old = b'<Keywords id="' + own + b'"'
    assert kw.count(old) == 1
    kw = kw.replace(old, b'<Keywords id="' + (value if keywords else b"0") + b'"')
    changes = {"swXmlContents/Features": feats, "swXmlContents/KeyWords": kw}
    drop: tuple[str, ...] = ()
    if stamps and ct is not None:
        changes["ModelStamps"] = struct.pack("<I", ct) + s["ModelStamps"][4:]
    else:
        drop = ("ModelStamps",)
    return rebuild(o02, changes, drop=drop)


def resolving_assembly(
    tree: "TreeXml", *, folder_at_save: str = "", members: dict[str, bytes] | None = None
) -> bytes:
    """An assembly with ``tree`` as its component tree and ``SW-Folder Name`` (the folder
    it was saved in) set to ``folder_at_save``; empty means unknown."""
    from xml.sax.saxutils import escape

    from support import ASSEMBLY, fixture_path

    isw = fixture_streams(fixture_path(ASSEMBLY))["docProps/ISolidWorksInformation.xml"]
    old = b'<property name="SW-Folder Name" pid="5"><vt:lpstr></vt:lpstr></property>'
    assert isw.count(old) == 1
    new = (
        b'<property name="SW-Folder Name" pid="5"><vt:lpstr>'
        + escape(folder_at_save).encode("utf-8")
        + b"</vt:lpstr></property>"
    )
    changes = {"docProps/ISolidWorksInformation.xml": isw.replace(old, new), **(members or {})}
    return assembly_with_tree(tree, changes)


def sheet_names(names: list[str]) -> bytes:
    """``SheetPreviews/SheetNames``: a u16 count, then one MFC CString per sheet."""
    out = bytearray(struct.pack("<H", len(names)))
    for n in names:
        raw = n.encode("utf-16-le")
        out += b"\xff\xfe\xff" + bytes([len(n)]) + raw
    return bytes(out) + b"\0" * 5


def drawing_keywords(sheets: dict[str, list[tuple[str, str, str]]]) -> bytes:
    """``swXmlContents/KeyWords`` as a drawing stores it: ``Sheet`` elements whose ``View``
    children hold ``(view name, configuration, model file name)``."""
    from xml.sax.saxutils import escape, quoteattr

    body = []
    for sheet, views in sheets.items():
        vs = "".join(
            f"<View id=\"0\" Name={quoteattr(v)} Description={quoteattr(c)}>{escape(f)}</View>"
            for v, c, f in views
        )
        body.append(f'<Sheet id="4" Name={quoteattr(sheet)} Type="Sheet">{vs}</Sheet>')
    xml = f'<Keywords id="1" Name="Draw1">{"".join(body)}</Keywords>'
    return b"\x86" + xml.encode("utf-8")
