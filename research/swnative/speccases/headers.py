"""Cases for section 15.2: the binary header streams.

Every case assembles its listing with the one slot dict of :mod:`.full`. This module
holds what section 15.2 contributes to that dict: the readers of its identity and
free slots (times, the installation's appearance path, session counters, the view
at save, the Biography's machine values) and the Header2 form of the bounding
sphere's centre (15.2.2.6). ``read_slots`` walks a listing over the fixture's member
and, at each field whose value is one of the slots it is told to read, takes the
field's value from the member, unless the slot is already bound. Every other field is
assembled as the listing says, so the cases still check every constant, every length
and every design value against SOLIDWORKS' bytes. No value read from a fixture is
stored in this file.
"""

from __future__ import annotations

import math
import struct

from swnative import listing as L

from . import Case, Fixture, slots

HEADER2 = "Header2"
MODELHEADER = "Contents/Config-0-ModelHeader"
CMGR = "Contents/CMgr"
CMGRHDR2 = "Contents/CMgrHdr2"
CUSPROPS = "Contents/CusProps"
DEFINITION = "Contents/Definition"
LWDATA = "Contents/Config-0-LWDATA"
BIOGRAPHY = "_MO_VERSION_17000/Biography"
VISUALSTATES = "ThirdPtyStore/VisualStates"
ANIMATOR = "ThirdPty/Animator"


# ------------------------------------------------------------------ reading slots
def _cstring_at(data: bytes, p: int) -> str:
    if data[p : p + 3] != b"\xff\xfe\xff":
        raise ValueError(f"no CString at {p}")
    n, q = data[p + 3], p + 4
    if n == 0xFF:
        n, q = struct.unpack_from("<H", data, q)[0], q + 2
        if n == 0xFFFF:
            n, q = struct.unpack_from("<I", data, q)[0], q + 4
    return data[q : q + 2 * n].decode("utf-16-le")


def _bind(slots: dict, path: str, value) -> None:
    parts = path.split(".")
    cur = slots
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


class _Reader(L._Assembler):
    """The reference assembler, which also reads the named slots from ``data`` at the
    offset the listing has reached when it meets them."""

    def __init__(self, data: bytes, read: set[str]):
        super().__init__(L.Archive(), L.LISTINGS)
        self.data, self.read = data, read

    def _take(self, head: str, path: str, slots: dict) -> None:
        try:
            L._lookup(slots, path)
            return  # already bound: the listing checks it like any other value
        except KeyError:
            pass
        p = len(self.out)
        if head in L._INTS:
            value = struct.unpack_from(L._INTS[head], self.data, p)[0]
        elif head in L._FLOATS:
            value = struct.unpack_from(L._FLOATS[head], self.data, p)[0]
        elif head == "f64bits":
            value = struct.unpack_from("<Q", self.data, p)[0]
        else:
            value = _cstring_at(self.data, p)
        _bind(slots, path, value)

    def _take_split(self, path: str, slots: dict) -> None:
        """A u64 written as two u32, high word first (``=$x//4294967296`` then
        ``=$x%4294967296``), as SOLIDWORKS stores a FILETIME in these streams."""
        try:
            L._lookup(slots, path)
            return
        except KeyError:
            pass
        hi, lo = struct.unpack_from("<II", self.data, len(self.out))
        _bind(slots, path, hi << 32 | lo)

    def step(self, head, args, line, lines, i, slots):
        if head in L._INTS or head in L._FLOATS or head in ("f64bits", "cstr"):
            for a in args:
                if a.startswith("$") and a[1:] in self.read:
                    self._take(head, a[1:], slots)
                elif (head == "u32" and a.startswith("=$") and a.endswith("//4294967296")
                      and a[2:-12] in self.read):
                    self._take_split(a[2:-12], slots)
                super().step(head, [a], line, lines, i, slots)
            return i
        return super().step(head, args, line, lines, i, slots)


def read_slots(listing: str, data: bytes, slots: dict, read: set[str]) -> dict:
    """``slots`` with the slots named in ``read`` taken from ``data`` (a fixture's member)."""
    r = _Reader(data, read)
    r.run(L.load(L.LISTINGS / listing), slots)
    return slots


# ------------------------------------------------------------------ derived (15.2.2.6)
def header_centre(boxes) -> list[float]:
    """Section 15.2.2.6: the bounding sphere's centre as Header2 stores it. Each box gives
    the sphere through its corners; the spheres are merged in body order, each time into
    the smallest sphere holding both. ``model.sphere`` (15.4.5) carries the merged centre
    from the older sphere's centre; Header2 carries it from the newer one's."""
    (lo, hi), *rest = boxes
    c = [(a + b) / 2 for a, b in zip(lo, hi, strict=True)]
    r = math.sqrt(sum((b - a) ** 2 for a, b in zip(lo, hi, strict=True))) / 2
    hc = c
    for lo, hi in rest:
        c2 = [(a + b) / 2 for a, b in zip(lo, hi, strict=True)]
        r2 = math.sqrt(sum((b - a) ** 2 for a, b in zip(lo, hi, strict=True))) / 2
        d = math.sqrt(sum((b - a) ** 2 for a, b in zip(c, c2, strict=True)))
        if d + r2 <= r:
            continue
        if d + r <= r2:
            c = hc = c2
            r = r2
            continue
        big = (d + r + r2) / 2
        hc = [b - (b - a) / d * (big - r2) for a, b in zip(hc, c2, strict=True)]
        c = [a + (b - a) * (big - r) / d for a, b in zip(c, c2, strict=True)]
        r = big
    return hc


# ------------------------------------------------------------------ reading identity and free slots
# Per listing, the member it gives and the slots read from that member where the listing
# first reaches them. Slots already bound (by section 15.1's readers, or by a listing
# read before) are checked, not read.
READS = (
    ("model-header.srl", HEADER2, {"doc.name", "tpl.unix", "tpl.unix2", "f.created", "f.modified"}),
    ("animator.srl", ANIMATOR, {"anim.guid"}),
    ("config-0-lwdata.srl", LWDATA, {"lw.flag"}),
    ("cmgr.srl", CMGR, {"cmgr.created", "cmgr.texture", "b.time"}),
    ("biography.srl", BIOGRAPHY, {
        "bio.os.platform", "bio.os.major", "bio.os.minor", "bio.os.build", "bio.locale",
        *(f"bio.{g}.{k}" for g in ("made", "open", "save") for k in ("time", "tag", "x")),
        *(f"bio.{g}.{k}" for g in ("made", "open")
          for k in ("system", "windows", "work", "temp", "template")),
        "bio.save.folder", "bio.save.file",
    }),
    ("definition.srl", DEFINITION, {"def.view.zoom", *(f"def.view.r.{k}" for k in range(9)),
                                    *(f"def.view.c.{k}" for k in range(3))}),
)


def read_identity(fx: Fixture, slots: dict) -> None:
    """Bind section 15.2's identity and free slots in ``slots`` from fixture ``fx``."""
    for listing, member, read in READS:
        read_slots(listing, fx[member], slots, read)
        for key in ("_archive", "settings_size", "tail_size"):
            slots.pop(key, None)
    view = slots["def"]["view"]  # read by index into dicts; written as lists
    view["r"] = [view["r"][str(k)] for k in range(9)]
    view["c"] = [view["c"][str(k)] for k in range(3)]


# ------------------------------------------------------------------ cases
PARTS = ("o01", "o02", "o03", "o04", "o07", "o12")
MEMBERS = {
    HEADER2: "header2.srl", MODELHEADER: "config-0-modelheader.srl", CMGRHDR2: "cmgrhdr2.srl",
    CUSPROPS: "cusprops.srl", ANIMATOR: "animator.srl", LWDATA: "config-0-lwdata.srl",
    VISUALSTATES: "visualstates.srl", CMGR: "cmgr.srl", BIOGRAPHY: "biography.srl",
    DEFINITION: "definition.srl",
}

CASES = [Case(p, member, listing, slots) for member, listing in MEMBERS.items() for p in PARTS]
