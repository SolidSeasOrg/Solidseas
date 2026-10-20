"""Cases for section 15.1: the XML and text members and the small fixed members.

Every case assembles its listing with the one slot dict of :mod:`.full`. This module
holds what section 15.1 contributes to that dict: the readers of its identity and free
slots (times, the saving account, the file name at save, the change stamps, the saving
machine's offset from UTC), which run on each fixture when a case runs, and the rules
of 15.1.2 that derive the date texts and the keyword lists. No value read from a
fixture is stored in this file.
"""

from __future__ import annotations

import re
import struct
from datetime import UTC, datetime, timedelta

from . import Case, Fixture, slots

PARTS = ("o01", "o02", "o03", "o04", "o07", "o12")


# ------------------------------------------------------------------ derived (15.1.2)
def depth_text(mm: float) -> str:
    """A depth in millimetres as KeyWords writes it: the shortest decimal, no trailing zeros."""
    text = f"{round(mm, 8):.8f}".rstrip("0").rstrip(".")
    return text or "0"


def kw_sketches(features: list[dict]) -> list[dict]:
    out = [{"id": 5, "name": "Origin", "origin": True}]
    out += [{"id": f["id"], "name": f["name"], "origin": False} for f in features if f["sketch"]]
    return sorted(out, key=lambda s: str(s["id"]))


def kw_extrusions(features: list[dict]) -> list[dict]:
    return sorted((f for f in features if not f["sketch"]), key=lambda f: str(f["id"]))


# ------------------------------------------------------------------ dates (15.1.4)
_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December")


def short_date(t: datetime) -> str:
    return f"{t.month}/{t.day}/{t.year}"


def long_date(t: datetime) -> str:
    return f"{_DAYS[t.weekday()]}, {_MONTHS[t.month - 1]} {t.day}, {t.year}"


def long_date_time(t: datetime) -> str:
    h = t.hour % 12 or 12
    return f"{long_date(t)} {h}:{t.minute:02d}:{t.second:02d} {'AM' if t.hour < 12 else 'PM'}"


def iso(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def date_texts(unix: int, created_iso: str, utc_offset: int) -> dict:
    """The four date texts of ISolidWorksInformation (15.1.2.1)."""
    shift = timedelta(minutes=utc_offset)
    saved = datetime.fromtimestamp(unix, UTC) + shift
    created = iso(created_iso) + shift
    return {"short_date": short_date(saved), "long_date": long_date(saved),
            "created_text": long_date_time(created), "saved_text": long_date_time(saved)}


# ------------------------------------------------------------------ reading identity and free slots
def _xml_text(data: bytes, pattern: str) -> str:
    m = re.search(pattern.encode(), data)
    if not m:
        raise ValueError(f"{pattern} not found")
    return m.group(1).decode("utf-8")


def _utc_offset(fx: Fixture, saved: datetime) -> int:
    """The saving machine's offset from UTC in minutes, from the local clock time it wrote
    beside the save instant (only the hour and minute are used; the rest is checked by the
    listing)."""
    info = fx["docProps/ISolidWorksInformation.xml"]
    local = _xml_text(info, r'name="SW-Last Saved Date" pid="\d+"><vt:lpstr>[^<]* (\d+:\d+):\d+ [AP]M<')
    pm = re.search(rb'name="SW-Last Saved Date" pid="\d+"><vt:lpstr>[^<]* (AM|PM)<', info).group(1) == b"PM"
    h, m = (int(x) for x in local.split(":"))
    minutes = (h % 12 + (12 if pm else 0)) * 60 + m
    diff = (minutes - (saved.hour * 60 + saved.minute)) % 1440
    if diff > 720:
        diff -= 1440
    return diff


def read_identity(fx: Fixture) -> dict:
    """The identity and free slots section 15.1 reads, from fixture ``fx``."""
    created, stamp, stamp2 = struct.unpack("<3I", fx["ModelStamps"])
    info = fx["SwDocContentMgr/SwDocContentMgrInfo"]
    p = info.index(b"su_CStringArray") + len(b"su_CStringArray") + 2  # after the empty array's count
    changed = struct.unpack_from("<I", info, p)[0]
    core = fx["docProps/core.xml"]
    app = fx["docProps/app.xml"]
    saved = iso(_xml_text(core, r"<dcterms:modified>([^<]*)<"))
    return {
        "doc": {
            "unix": int(saved.timestamp()), "created": created, "changed": changed,
            "stamp": stamp, "stamp2": stamp2,
            "author": _xml_text(core, r"<dc:lastModifiedBy>([^<]*)<"),
        },
        "meta": {
            "created_iso": _xml_text(core, r"<dcterms:created>([^<]*)<"),
            "file_stem": _xml_text(fx["swXmlContents/Features"], r'<swModel id="2" swName="([^"]*)"'),
            "company": _xml_text(app, r"<Company>([^<]*)<"),
            "total_time": _xml_text(app, r"<TotalTime>([^<]*)<"),
            "utc_offset": _utc_offset(fx, saved),
        },
    }


# ------------------------------------------------------------------ cases
MEMBERS = {
    "[Content_Types].xml": "content-types.srl",
    "_rels/.rels": "rels.srl",
    "docProps/Config-0-Properties.xml": "config-0-properties.srl",
    "docProps/ISolidWorksInformation.xml": "isolidworksinformation.srl",
    "docProps/OpenTime.xml": "opentime.srl",
    "docProps/app.xml": "app.srl",
    "docProps/core.xml": "core.srl",
    "docProps/custom.xml": "custom.srl",
    "swXmlContents/Features": "features-xml.srl",
    "swXmlContents/KeyWords": "keywords.srl",
    "SwDocContentMgr/SwDocContentMgrInfo": "swdoccontentmgrinfo.srl",
    "Contents/CnfgObjs": "cnfgobjs.srl",
    "Contents/OleItems": "oleitems.srl",
    "Contents/eModelLic": "emodellic.srl",
    "ModelStamps": "modelstamps.srl",
    "OleItemInformation/OLE_Item_Data": "ole-item-data.srl",
    "ThirdPty/CMMotionLoadMapU": "cmmotionloadmapu.srl",
    "ThirdPty/CM_MOTION_LOAD_1": "cm-motion-load-1.srl",
    "ThirdPty/SWA_Schedules": "swa-schedules.srl",
    "_DL_VERSION_17000/DLUpdateStamp": "dlupdatestamp.srl",
    "_MO_VERSION_17000/History": "history.srl",
}

CASES = [Case(p, member, listing, slots) for member, listing in MEMBERS.items() for p in PARTS]
