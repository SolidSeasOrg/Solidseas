"""Cases for sections 15.4 and 15.5: ``Contents/Config-0`` and its feature stream.

Every case assembles its listing with the one slot dict of :mod:`.full`. This module
holds what sections 15.4 and 15.5 contribute to that dict: the rules that derive the
bounding sphere (15.4.5) and the planes' display (15.5.5, 15.2.5.3), and the reader of
their identity and free slots (times, session counters, caches whose values the
specification does not derive). :func:`extract` assembles the two listings with
placeholder values, notes where each such slot's first field lands, and reads that
field from the fixture's member; the case then assembles again and the test compares
every byte, so a slot that is used twice is checked against the fixture at every other
place it appears. No value read from a fixture is stored in this file.
"""

from __future__ import annotations

import copy
import fnmatch
import math
import re
import struct

from .. import listing as L
from . import Case, Fixture, slots

CONFIG = "Contents/Config-0"
FEATURES = "Contents/Config-0-ResolvedFeatures"

# Slots read from the fixture (identity and free kinds), as patterns over the slot path a
# listing line names. Slots the other sections' readers bind first (doc.name, tpl.unix,
# cmgr.texture, the features' created) are checked here, not read.
READ = (
    "config0.length_memo",
    "config0.curvature_time",
    "config0.sketch_blocks_time",
    "config0.mass.*",
    "*.regen",
    "fixed.*.time",
    "f.time",
    "f.counter*",
    "f.cache*",
)

_INT = {"u8": "<B", "u16": "<H", "u32": "<I", "u64": "<Q", "i8": "<b", "i16": "<h", "i32": "<i", "i64": "<q"}
_FLT = {"f32": "<f", "f64": "<d"}
_SIMPLE = re.compile(r"=\$([\w.]+)([+-]\d+)?\Z")
_HI = re.compile(r"=\$([\w.]+)//4294967296\Z")
_LO = re.compile(r"=\$([\w.]+)%4294967296\Z")


class _Probe(L._Assembler):
    """An assembler that notes, for every field a slot or expression gives, its offset,
    type, token and the slot dict it was assembled with."""

    def __init__(self, archive, base, notes):
        super().__init__(archive, base)
        self.notes = notes

    def step(self, head, args, line, lines, i, slots):
        if head in _INT or head in _FLT:
            fmt = _INT.get(head) or _FLT[head]
            at = len(self.out)
            for a in args:
                if a.startswith(("$", "=")):
                    self.notes.append((self.member, at, head, a, slots))
                at += struct.calcsize(fmt)
        elif head == "cstr" and args[0].startswith("$"):
            self.notes.append((self.member, len(self.out), head, args[0], slots))
        return super().step(head, args, line, lines, i, slots)


def _assemble(listings, slots, notes):
    archive = None
    out = {}
    for name, member in listings:
        a = _Probe(archive or L.Archive(), L.LISTINGS, notes)
        a.member = member
        a.run(L.load(L.LISTINGS / name), dict(slots))
        archive = a.archive
        out[member] = bytes(a.out)
    return out


def _walk(slots, path):
    """The container holding ``path``'s last part, and that part (a key or an index)."""
    parts = path.split(".")
    cur = slots
    for p in parts[:-1]:
        cur = cur[int(p)] if isinstance(cur, list) else cur[p]
    last = parts[-1]
    return cur, (int(last) if isinstance(cur, list) else last)


def _cstring(data: bytes, at: int) -> str:
    assert data[at:at + 3] == b"\xff\xfe\xff", "no CString where the listing has one"
    n, k = data[at + 3], at + 4
    if n == 0xFF:
        (n,) = struct.unpack_from("<H", data, k)
        k += 2
    return data[k:k + 2 * n].decode("utf-16-le")


def extract(fx: Fixture, slots: dict, listings: list[tuple[str, str]]) -> dict:
    """``slots`` with every identity and free slot of ``READ`` read from ``fx``."""
    slots = copy.deepcopy(slots)
    for _ in range(20):  # a string changes the layout after it: read it, assemble again
        notes: list = []
        _assemble(listings, slots, notes)
        done: set = set()
        changed = False
        halves: dict = {}
        for member, at, head, tok, env in notes:
            data = fx[member]
            m_hi, m_lo, m_s = _HI.match(tok), _LO.match(tok), _SIMPLE.match(tok)
            if head == "cstr":
                path, k = tok[1:], 0
            elif m_hi or m_lo:
                path, k = (m_hi or m_lo).group(1), None
            elif m_s:
                path, k = m_s.group(1), int(m_s.group(2) or 0)
            elif tok.startswith("$"):
                path, k = tok[1:], 0
            else:
                continue
            if not any(fnmatch.fnmatchcase(path, p) for p in READ):
                continue
            box, key = _walk(env, path)
            ident = (id(box), key)
            if head == "cstr":
                value = _cstring(data, at)
            elif head in _FLT:
                (value,) = struct.unpack_from(_FLT[head], data, at)
            else:
                (value,) = struct.unpack_from(_INT[head], data, at)
            if k is None:  # a FILETIME written high word first
                h = halves.setdefault(ident, {})
                h["hi" if m_hi else "lo"] = value
                if len(h) < 2:
                    continue
                value = (h["hi"] << 32) | h["lo"]
            elif k:
                value = value - k
            if ident in done:
                continue
            done.add(ident)
            if box[key] != value:
                box[key] = value
                changed = True
                if head == "cstr":
                    break
        if not changed:
            break
    return slots


# ------------------------------------------------------------------ derived (15.4.5, 15.5.5, 15.2.5.3)
def sphere(boxes) -> list[float]:
    """15.4.5: the bounding sphere, box by box: each box's centre and half diagonal,
    then each next sphere merged into the one so far. Centre (three), then radius."""
    c = r = None
    for lo, hi in boxes:
        bc = [(a + b) / 2 for a, b in zip(lo, hi, strict=True)]
        br = math.sqrt(sum((b - a) ** 2 for a, b in zip(lo, hi, strict=True))) / 2
        if c is None:
            c, r = bc, br
            continue
        d = math.sqrt(sum((q - p) ** 2 for p, q in zip(c, bc, strict=True)))
        if d + br <= r:
            continue
        if d + r <= br:
            c, r = bc, br
            continue
        nr = (d + r + br) / 2
        c = [p + (q - p) * (nr - r) / d for p, q in zip(c, bc, strict=True)]
        r = nr
    return c + [r]


# Each plane's two axes in model coordinates (indices of x, y, z), 15.5.5.
PLANE_AXES = {"front": (0, 1), "top": (0, 2), "right": (2, 1)}
EMPTY_HALVES = (0.08899, 0.05500000000000001)


def planes(lo, hi, centre, solid: bool) -> dict:
    """15.5.5 and 15.2.5.3: each plane's display rectangle: half sizes ``hu``, ``hv``, and
    in model space its centre, far corner ``max``, near corner ``min`` and half diagonal
    ``radius``."""

    def half(k):
        e = hi[k] - lo[k]
        return e / 2 + e / 2 * 0.1

    out = {}
    for name, (u, v) in PLANE_AXES.items():
        hu, hv = (half(u), half(v)) if solid else EMPTY_HALVES
        mn, mx = [0.0] * 3, [0.0] * 3
        mn[u], mx[u] = centre[u] - hu, centre[u] + hu
        mn[v], mx[v] = centre[v] - hv, centre[v] + hv
        out[name] = {
            "hu": hu, "hv": hv,
            "centre": [(a + b) / 2 for a, b in zip(mn, mx, strict=True)], "min": mn, "max": mx,
            "radius": math.sqrt(sum((b - a) ** 2 for a, b in zip(mn, mx, strict=True))) / 2,
        }
    return out


# The template records whose time is a slot (15.5.3, 15.4.8).
FIXED_TIMES = (
    "comments", "favorites", "history", "selsets", "sensors", "binder", "annotations", "notes",
    "notes_end", "surface", "solid", "lights", "markups", "material", "front", "top", "right", "origin",
)


def read_identity(fx: Fixture, slots: dict) -> dict:
    """``slots`` with the identity and free slots of 15.4 and 15.5 read from ``fx``."""
    slots = copy.deepcopy(slots)
    c0 = fx[CONFIG]
    at = c0.find(b"moCThreadRefMgr_c") + len("moCThreadRefMgr_c") + 23
    # 15.4.11: whether SOLIDWORKS kept evaluated mass properties (free).
    config0 = slots.setdefault("config0", {})
    config0.update(mass_block=struct.unpack_from("<I", c0, at)[0] != 0, length_memo=0.0,
                   curvature_time=0, sketch_blocks_time=0, mass=[0.0] * 12)
    fixed = slots.setdefault("fixed", {})
    for key in FIXED_TIMES:
        fixed.setdefault(key, {})["time"] = 0
    fixed["origin"]["regen"] = 0
    for f in slots["features"]:  # placeholders the reader replaces
        f.update(time=0, cache_memo=0.0)
        if f["sketch"]:
            f.update(regen=0)
        else:
            f.update(cache_text=0.0, counter_marks=0, counter_favorite=0, counter_face1=0, counter_face2=0)
    for b in slots["bodies"]:
        b["regen"] = 0
    return extract(fx, slots, [("config-0.srl", CONFIG), ("config-0-resolvedfeatures.srl", FEATURES)])


PARTS = ("o01", "o02", "o03", "o04", "o07", "o12")
CASES = [Case(p, CONFIG, "config-0.srl", slots) for p in PARTS] + [
    Case(p, FEATURES, "config-0-resolvedfeatures.srl", slots, before="config-0.srl") for p in PARTS
]
