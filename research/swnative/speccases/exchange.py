"""Cases for section 15.3: the two 3DEXPERIENCE exchange members (UnQLite databases).

Every case assembles its listing with the one slot dict of :mod:`.full`. The members
hold no design value. Their identity slots (the records' GUIDs) and the free order of
the table of contents are read from each fixture by :func:`read_identity`; the key
hashes are derived from the GUIDs by the rule of section 15.3.3. The database time
(15.3.2) is an identity slot of its own, read from the header like the GUIDs.
"""

from __future__ import annotations

import struct

from . import Case, Fixture, slots

EXCHANGE2 = "Contents/3DExperienceExchange2"
CONFIGHEADER = "Contents/3DExperienceExchange_ConfigHeader"
PAGE = 4096


def key_hash(key: bytes) -> int:
    """Section 15.3.3: UnQLite's default key hash, h = h * 33 + byte from 5381, modulo 2**32."""
    h = 5381
    for b in key:
        h = (h * 33 + b) & 0xFFFFFFFF
    return h


def _cells(data: bytes):
    """(key, value) of every cell on page 2, following the chain from its head."""
    page = data[2 * PAGE : 3 * PAGE]
    off = struct.unpack_from(">H", page, 0)[0]
    while off:
        _h, klen, dlen, nxt, _ovf = struct.unpack_from(">IIQHQ", page, off)
        start = off + 26
        yield page[start : start + klen], page[start + klen : start + klen + dlen]
        off = nxt


def _guids(fx: Fixture) -> dict:
    out = {}
    for key, value in _cells(fx[EXCHANGE2]):
        for name, marker in (("front", b"Front Plane"), ("top", b"Top Plane"), ("right", b"Right Plane"),
                             ("doc", b"uiPartDoc_c")):
            if marker in value:
                out[name] = key.decode("ascii")
    for key, value in _cells(fx[CONFIGHEADER]):
        if b"dmConfigHeader_c" in value:
            out["config"] = key.decode("ascii")
    return out


def _toc_order(fx: Fixture) -> list[str]:
    """The plane GUIDs in the order the TOC record lists them (free, 15.3.6)."""
    toc = dict(_cells(fx[EXCHANGE2]))[b"TOC"]
    marker = b"\xa4guid\xd9\x24"
    out, at = [], toc.find(marker)
    while at >= 0:
        out.append(toc[at + len(marker) : at + len(marker) + 36].decode("ascii"))
        at = toc.find(marker, at + 1)
    return out


def _db_time(fx: Fixture) -> dict:
    """The database creation time of the page 0 header (15.3.2), month counted from 0."""
    d, t = struct.unpack_from(">HH", fx[EXCHANGE2], 11)
    return {"year": 1980 + (d >> 9), "month": ((d >> 5) & 15) + 1, "day": d & 31,
            "hour": t >> 11, "minute": (t >> 5) & 63, "second": (t & 31) * 2}


def read_identity(fx: Fixture) -> dict:
    """The identity slots (the five GUIDs and the database time) and the free slot
    ``exch.toc`` of fixture ``fx``."""
    out = _guids(fx)
    out["toc"] = _toc_order(fx)
    out["time"] = _db_time(fx)
    return {"exch": out}


def derive(exch: dict) -> None:
    """The derived slots of 15.3: the key hashes."""
    exch["hash"] = {k: key_hash(exch[k].encode("ascii")) for k in ("front", "top", "right", "doc", "config")}


PARTS = ("o01", "o02", "o03", "o04", "o07", "o12")

CASES = [Case(p, EXCHANGE2, "3dexperience-exchange2.srl", slots) for p in PARTS] + [
    Case(p, CONFIGHEADER, "3dexperience-configheader.srl", slots) for p in PARTS
]
