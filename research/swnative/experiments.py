"""Offline candidate parts for the native writer's first experiments.

Every candidate is made from a fixture with no SOLIDWORKS: this module imports
nothing from ``solidseas.swapi`` and loads no COM or Windows library, and
``python -m swnative.experiments`` checks that before it exits.
The SOLIDWORKS check (``scripts/sw-checks/native-writer.py``) runs it in a
process of its own first, then opens each candidate in SolidSeas' own
SOLIDWORKS and hands the report to :func:`judge`.

The candidates answer the questions of ``docs/NATIVE_SLDPRT_WRITER.md``
section 6:

- **X** (container): does SOLIDWORKS open a container this writer laid out?
- **A** (parameters): is a feature's stored parameter authoritative, so that a
  rebuild follows it (the depth ``D1@Boss-Extrude1``, and the sketch's points)?
- **C** (geometry): does SOLIDWORKS rebuild a part whose stored Parasolid
  partition is stale, empty or missing, or whose display lists are missing?
"""

import json
import re
import struct
import sys
import zlib
from dataclasses import asdict, dataclass, field
from pathlib import Path

from solidseas.formats.solidworks.zlb import ZLB_MAGIC, iter_zlb_chain
from solidseas.nativewrite.container import (
    SourceDocument,
    build_container,
    patch_in_place,
    read_document,
    with_changes,
    write_new_file,
)

from . import features as F

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
RECT_SAMPLE = FIXTURES / "solidcraft" / "rect-extrude-40x30x10.solidcraft"
FEATURES = "Contents/Config-0-ResolvedFeatures"
PARTITION = "Contents/Config-0-Partition"
GHOST = "Contents/Config-0-GhostPartition"
KEYWORDS = "swXmlContents/KeyWords"
BBOX_STREAMS = ("Contents/Config-0", "Contents/Config-0-LWDATA", "Contents/Config-0-ModelHeader", "Header2")
DISPLAY = ("Contents/DisplayLists", "Preview", "PreviewPNG")
DEPTH = "D1@Boss-Extrude1"
# o02: a 10 x 20 mm rectangle from the origin on the Front Plane, extruded 30 mm.
BOX = (0.010, 0.020, 0.030)
EDIT_DEPTH = 0.033  # what the check sets D1 to, after the first rebuild
FORBIDDEN_MODULES = ("solidseas.swapi", "win32com", "pythoncom", "pywintypes", "comtypes", "clr")


@dataclass
class Candidate:
    name: str
    question: str
    hypothesis: str
    strategy: str  # "copy", "rebuild" or "patch"
    changed: list[str]
    dropped: list[str]
    box_m: tuple[float, float, float]  # what the features say after the edit
    stale: list[str] = field(default_factory=list)  # what is left as the source had it
    data: bytes = b""
    extra_volume_m3: float = 0.0  # bodies the depth edit does not touch (b1, b2: o12's second box)

    @property
    def expected_volume_m3(self) -> float:
        w, h, d = self.box_m
        return w * h * d + self.extra_volume_m3

    @property
    def expected_edit_volume_m3(self) -> float:
        w, h, _ = self.box_m
        return w * h * EDIT_DEPTH + self.extra_volume_m3

    def manifest(self) -> dict:
        d = asdict(self)
        del d["data"]
        d["file"] = self.name + ".sldprt"
        d["expected_volume_m3"] = self.expected_volume_m3
        d["edit"] = {
            "dimension": DEPTH,
            "value": EDIT_DEPTH,
            "expected_volume_m3": self.expected_edit_volume_m3,
        }
        return d


# ------------------------------------------------------------------ edits
def wrap_zlb(data: bytes) -> bytes:
    """One ZLB block of ``data`` as SOLIDWORKS writes a small one: one zlib level 1 chunk."""
    z = zlib.compress(data, 1)
    return ZLB_MAGIC + struct.pack("<II", len(data), len(z)) + z + b"\0" * 8


def wrap_chain(blocks: list[bytes]) -> bytes:
    out = bytearray()
    for b in blocks:
        blk = wrap_zlb(b)
        out += struct.pack("<I", len(blk)) + blk
    return bytes(out)


def set_depth(features: bytes, depth: float, *, mirrors: bool) -> bytes:
    """The feature stream with D1 of Boss-Extrude1 set; with ``mirrors`` its dimension's copies too.

    The copies are the doubles equal to the old depth, either sign, inside the
    extrusion's span after the parameter: the dimension's witness points and
    the values beside them (o13's two configurations differ in exactly those,
    the parameter and the reference planes' display sizes).
    """
    p = F.parameter(features, DEPTH)
    edits = {p.value_offset: depth}
    if mirrors:
        _start, end = F.feature_span(features, "Boss-Extrude1")
        for sign in (1, -1):
            for off in F.doubles_equal_to(features, sign * p.value, p.value_offset + 8, end):
                edits[off] = sign * depth
    return F.set_doubles(features, edits)


def set_width(features: bytes, old: float, new: float) -> bytes:
    """The rectangle's corners at x = ``old`` moved to x = ``new`` (the sketch has no dimensions)."""
    pts = [p for p in F.sketch_points(features) if p.record == "sgLineHandle" and abs(p.x - old) < 1e-12]
    if len(pts) != 2:
        raise F.FeatureStreamError(f"expected two corners at x = {old}, found {len(pts)}")
    return F.set_doubles(features, {p.offset: new for p in pts})


def keywords_depth(keywords: bytes, depth_mm: float) -> bytes:
    """``swXmlContents/KeyWords`` with Boss-Extrude1's D1 text set (a mirror of the parameter)."""
    head, text = keywords[:1], keywords[1:].decode("utf-8")
    pat = re.compile(
        r'(<Extrusion [^>]*Name="Boss-Extrude1"[^>]*><Dimension Name="D1">)([^<]*)(</Dimension>)'
    )
    if len(pat.findall(text)) != 1:
        raise F.FeatureStreamError("KeyWords: Boss-Extrude1's D1 not found once")
    value = f"{depth_mm:g}"
    return head + pat.sub(lambda m: m.group(1) + value + m.group(3), text).encode("utf-8")


def partition_depth(partition: bytes, old: float, new: float) -> bytes:
    """The partition with every big-endian double ``old`` in its first block set to ``new``.

    o02 and o07 (30 and 31 mm, made in one session) hold 30 and 31 mm at the
    same 17 offsets of block 0; the rest of the two blocks differs only where
    a plain re-save differs too.
    """
    blocks = list(iter_zlb_chain(partition))
    b0 = bytearray(blocks[0])
    old_b, new_b = struct.pack(">d", old), struct.pack(">d", new)
    n = 0
    i = b0.find(old_b)
    while i >= 0:
        b0[i : i + 8] = new_b
        n += 1
        i = b0.find(old_b, i + 8)
    if n == 0:
        raise F.FeatureStreamError("no such value in the partition")
    blocks[0] = bytes(b0)
    return wrap_chain(blocks)


def bbox_depth(stream: bytes, box: tuple[float, float, float], depth: float) -> bytes:
    """A stream's stored box (centre, then far corner, six little-endian doubles) for a new depth.

    o02 and o07 store it once in each of ``BBOX_STREAMS``, at the same offset.
    """
    w, h, d = box
    old = struct.pack("<6d", w / 2, h / 2, d / 2, w, h, d)
    if stream.count(old) != 1:
        raise F.FeatureStreamError("the stored box is not there once")
    return stream.replace(old, struct.pack("<6d", w / 2, h / 2, depth / 2, w, h, depth))


def bbox_centre_depth(features: bytes, box: tuple[float, float, float], depth: float) -> bytes:
    """The feature stream's box centre records (centre, then the full diagonal) for a new depth."""
    w, h, d = box
    old = struct.pack("<4d", w / 2, h / 2, d / 2, (w * w + h * h + d * d) ** 0.5)
    new = struct.pack("<4d", w / 2, h / 2, depth / 2, (w * w + h * h + depth * depth) ** 0.5)
    if features.count(old) == 0:
        raise F.FeatureStreamError("no box centre record")
    return features.replace(old, new)


# ------------------------------------------------------------------ candidates
def candidates(source: SourceDocument | None = None, empty: SourceDocument | None = None) -> list[Candidate]:
    src = source or read_document(FIXTURES / "o02_boxA.SLDPRT")
    blank = empty or read_document(FIXTURES / "o01_empty.SLDPRT")
    w, h, d = BOX
    feats = src.data(FEATURES)
    out: list[Candidate] = []

    def add(name, question, hypothesis, strategy, changes, box, stale=()):
        changed = [k for k, v in changes.items() if v is not None]
        dropped = [k for k, v in changes.items() if v is None]
        if strategy == "copy":
            data = src.raw
        elif strategy == "patch":
            data = patch_in_place(src, changes)
        else:
            data = build_container(with_changes(src.members, changes), key=src.key, signatures=src.signatures)
        out.append(Candidate(name, question, hypothesis, strategy, changed, dropped, box, list(stale), data))

    d31 = 0.031
    add("x0-source", "X", "control: the fixture itself", "copy", {}, BOX)
    add(
        "x1-rebuilt-container",
        "X",
        "a container laid out again from byte 8, no decoys, opens",
        "rebuild",
        {},
        BOX,
    )
    add(
        "x2-patched-container",
        "X",
        "the source with its directory written again after the members opens",
        "patch",
        {},
        BOX,
    )
    a1 = set_depth(feats, d31, mirrors=False)
    a2 = set_depth(feats, d31, mirrors=True)
    kw31 = keywords_depth(src.data(KEYWORDS), 31)
    stale_geo = [PARTITION, GHOST, *DISPLAY, *BBOX_STREAMS]
    add(
        "a1-depth-parameter-only",
        "A",
        "D1's stored value alone drives the rebuild",
        "patch",
        {FEATURES: a1},
        (w, h, d31),
        stale_geo + [KEYWORDS],
    )
    add(
        "a2-depth-with-mirrors",
        "A",
        "D1 and its dimension's copies, with the KeyWords text",
        "patch",
        {FEATURES: a2, KEYWORDS: kw31},
        (w, h, d31),
        stale_geo,
    )
    consistent = {
        FEATURES: bbox_centre_depth(a2, BOX, d31),
        KEYWORDS: kw31,
        PARTITION: partition_depth(src.data(PARTITION), d, d31),
    }
    for s in BBOX_STREAMS:
        consistent[s] = bbox_depth(src.data(s), BOX, d31)
    add(
        "a3-depth-consistent",
        "A",
        "every stored copy of the depth moved, the partition's geometry too",
        "rebuild",
        consistent,
        (w, h, d31),
        [GHOST, *DISPLAY],
    )
    add(
        "c1-no-partition",
        "C",
        "with no partition stream SOLIDWORKS rebuilds the body from the features",
        "rebuild",
        {FEATURES: a2, KEYWORDS: kw31, PARTITION: None, GHOST: None},
        (w, h, d31),
        [*DISPLAY],
    )
    add(
        "c2-empty-partition",
        "C",
        "an empty part's partition is accepted and the body rebuilt",
        "rebuild",
        {FEATURES: a2, KEYWORDS: kw31, PARTITION: blank.data(PARTITION), GHOST: None},
        (w, h, d31),
        [*DISPLAY],
    )
    add(
        "c3-no-display-lists",
        "C",
        "display lists and previews are caches SOLIDWORKS makes again",
        "rebuild",
        {FEATURES: a2, KEYWORDS: kw31, **{s: None for s in DISPLAY}},
        (w, h, d31),
        [PARTITION, GHOST],
    )
    s1 = set_width(feats, w, 0.012)
    add(
        "s1-sketch-width-12",
        "A",
        "the sketch's stored points drive the profile (no sketch dimensions)",
        "patch",
        {FEATURES: s1},
        (0.012, h, d),
        stale_geo,
    )
    s2 = set_width(set_depth(feats, d31, mirrors=True), w, 0.012)
    add(
        "s2-width-and-depth",
        "A",
        "points and depth together",
        "patch",
        {FEATURES: s2, KEYWORDS: kw31},
        (0.012, h, d31),
        stale_geo,
    )
    # The feature definitions of o12 (a second box, (30, 0) to (40, 20) mm, 10 mm, merge off) in o02:
    # does a written part need anything but Config-0 and its feature stream?
    o12 = read_document(FIXTURES / "o12_multibody.SLDPRT")
    second = 0.010 * 0.020 * 0.010
    two = {"Contents/Config-0": o12.data("Contents/Config-0"), FEATURES: o12.data(FEATURES)}
    for name, extra, hyp in (
        (
            "b1-features-from-o12",
            {},
            "Config-0 and the feature stream define the features; every cache is o02's",
        ),
        ("b2-features-from-o12-no-partition", {PARTITION: None, GHOST: None}, "the same with no partition"),
    ):
        changes = {**two, **extra}
        data = build_container(with_changes(src.members, changes), key=src.key, signatures=src.signatures)
        out.append(
            Candidate(
                name,
                "B",
                hyp,
                "rebuild",
                [k for k, v in changes.items() if v is not None],
                [k for k, v in changes.items() if v is None],
                BOX,
                [KEYWORDS, *BBOX_STREAMS[1:], *DISPLAY],
                data,
                second,
            )
        )

    # o02's feature definitions in the empty part o01, whose caches describe no body.
    blank_two = {"Contents/Config-0": src.data("Contents/Config-0"), FEATURES: src.data(FEATURES)}
    b4_feats = set_depth(src.data(FEATURES), 0.010, mirrors=True)
    from .writer import move_rectangle

    b4_feats = move_rectangle(b4_feats, (w, h), (0.040, 0.030))
    for name, feats, box, hyp in (
        (
            "b3-o02-features-in-o01",
            src.data(FEATURES),
            BOX,
            "an empty part's caches with a box's definitions",
        ),
        (
            "b4-o02-features-in-o01-40x30x10",
            b4_feats,
            (0.040, 0.030, 0.010),
            "the same, the box moved to 40 x 30 x 10",
        ),
    ):
        changes = {**blank_two, FEATURES: feats}
        data = build_container(
            with_changes(blank.members, changes), key=blank.key, signatures=blank.signatures
        )
        out.append(
            Candidate(
                name,
                "B",
                hyp,
                "rebuild",
                list(changes),
                [],
                box,
                [PARTITION, KEYWORDS, *BBOX_STREAMS[1:], *DISPLAY],
                data,
            )
        )

    # Experiment M: which members a part must have. Every candidate starts from o02 with no
    # partition (c1 showed SOLIDWORKS builds the body on open) and leaves one more member out;
    # g1 and g2 keep only a guessed core.
    out.extend(member_candidates(src))

    # SolidCraft to the IR to a native part, through the seed writer (left out: the sample's fillet
    # and its two sketch dimensions, which the seed cannot hold; the report lists them).
    from solidseas.nativewrite import solidcraft

    from . import writer

    sample = solidcraft.read_ir(RECT_SAMPLE)
    for name, geometry in (("p1-solidcraft-rect", "stale"), ("p2-solidcraft-rect-no-partition", "drop")):
        data, rep = writer.write_sldprt(sample, allow_partial=True, geometry=geometry, seed=src)
        changed = [FEATURES, KEYWORDS]
        out.append(
            Candidate(
                name,
                "A",
                f"the IR's rectangle and depth written into the seed, geometry {geometry}",
                "patch" if geometry == "stale" else "rebuild",
                changed,
                [PARTITION, GHOST] if geometry == "drop" else [],
                rep.box_m,
                rep.left_out,
                data,
            )
        )
    return out


CORE_G1 = (
    "Contents/Definition",
    "Contents/Config-0",
    FEATURES,
    "Contents/CMgr",
    "Contents/CMgrHdr2",
    "Contents/CnfgObjs",
    "Header2",
    "Contents/Config-0-ModelHeader",
    "_MO_VERSION_17000/History",
)
CORE_G2 = CORE_G1 + (
    "Contents/Config-0-LWDATA",
    "ModelStamps",
    "swXmlContents/Features",
    KEYWORDS,
    "docProps/ISolidWorksInformation.xml",
    "[Content_Types].xml",
    "_rels/.rels",
)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def member_candidates(src: SourceDocument) -> list[Candidate]:
    """o02 with no partition, and the same with each other member, or all but a core, left out."""
    base = {PARTITION: None, GHOST: None}
    names = [m.name for m in src.members if m.name not in base]
    sets = [("m00-no-partition", base)]
    sets += [(f"m-{_slug(n)}", {**base, n: None}) for n in names]
    for label, core in (("g1-core", CORE_G1), ("g2-core", CORE_G2)):
        sets.append((label, {**base, **{n: None for n in names if n not in core}}))
    out = []
    for name, changes in sets:
        data = build_container(with_changes(src.members, changes), key=src.key, signatures=src.signatures)
        dropped = [k for k in changes]
        out.append(
            Candidate(
                name,
                "M",
                "SOLIDWORKS opens and rebuilds o02 without these members",
                "rebuild",
                [],
                dropped,
                BOX,
                [],
                data,
            )
        )
    return out


def write_candidates(out_dir: str | Path) -> Path:
    """Write every candidate and ``manifest.json`` into a new folder; return the manifest's path."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=False)
    cands = candidates()
    for c in cands:
        write_new_file(out / (c.name + ".sldprt"), c.data)
    manifest = {
        "source": "tests/fixtures/o02_boxA.SLDPRT",
        "made_without_solidworks": True,
        "candidates": [c.manifest() for c in cands],
    }
    path = out / "manifest.json"
    write_new_file(path, json.dumps(manifest, indent=2).encode("utf-8"))
    return path


# ------------------------------------------------------------------ verdicts
VOLUME_TOLERANCE = 1e-3  # relative


def _volume(snapshot: dict | None) -> float | None:
    """The solid volume a snapshot measured: the bridge reports it as ``measure.mass.volume_m3``."""
    if not snapshot:
        return None
    m = snapshot.get("measure") or {}
    mass = m.get("mass") or {}
    for v in (mass.get("volume_m3"), m.get("volume_m3"), m.get("volume")):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


def _close(a: float | None, b: float) -> bool:
    return a is not None and abs(a - b) <= VOLUME_TOLERANCE * abs(b)


def _native(snapshot: dict | None) -> dict:
    feats = (snapshot or {}).get("features") or []
    types = {f.get("name"): f.get("type") for f in feats}
    depth = None
    for f in feats:
        if f.get("name") == "Boss-Extrude1":
            depth = (f.get("extrude") or {}).get("depth")
    errors = [f.get("name") for f in feats if f.get("error") and not f.get("error_is_warning")]
    return {
        "sketch": types.get("Sketch1") == "ProfileFeature",
        "extrusion": types.get("Boss-Extrude1") == "Extrusion",
        "imported": any(t in ("MBimport", "BaseBody") for t in types.values()),
        "depth": depth,
        "feature_errors": errors,
    }


def judge(candidate: dict, report: dict) -> dict:
    """A verdict on one candidate from the check's report of it (``native_check`` and the reopen)."""
    v: dict = {"name": candidate["name"], "opened": bool(report.get("opened"))}
    if not v["opened"]:
        v["verdict"] = "refused"
        v["open_error"] = report.get("open_error")
        return v
    check = report.get("check") or {}
    opened, rebuilt = check.get("opened"), check.get("rebuilt")
    nat = _native(rebuilt)
    v.update(
        native=nat["sketch"] and nat["extrusion"] and not nat["imported"],
        depth_after_rebuild=nat["depth"],
        feature_errors=nat["feature_errors"],
        volume_as_opened=_volume(opened),
        volume_after_rebuild=_volume(rebuilt),
        whats_wrong=len((rebuilt or {}).get("whats_wrong") or []),
        open_warnings=report.get("open_warnings", 0),
    )
    v["rebuilds_to_features"] = _close(v["volume_after_rebuild"], candidate["expected_volume_m3"])
    edit = check.get("edit") or {}
    v["edit_found"] = bool(edit.get("found"))
    v["edit_rebuilds"] = _close(_volume(edit.get("snapshot")), candidate["edit"]["expected_volume_m3"])
    reopen = report.get("reopened") or {}
    v["saved"] = bool((check.get("saved") or {}).get("ok"))
    v["reopened_volume"] = _volume((reopen.get("check") or {}).get("rebuilt"))
    v["reopen_keeps_edit"] = _close(v["reopened_volume"], candidate["edit"]["expected_volume_m3"])
    good = (
        v["native"]
        and v["rebuilds_to_features"]
        and v["edit_rebuilds"]
        and v["saved"]
        and v["reopen_keeps_edit"]
        and not v["feature_errors"]
    )
    v["verdict"] = "editable" if good else ("native" if v["native"] else "not-native")
    return v


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="Write the native writer's experiment candidates (no SOLIDWORKS)."
    )
    ap.add_argument("--out", required=True, help="a new folder for the candidates and manifest.json")
    args = ap.parse_args(argv)
    path = write_candidates(args.out)
    loaded = sorted(m for m in sys.modules if m.startswith(FORBIDDEN_MODULES))
    if loaded:
        print(json.dumps({"error": "loaded modules that reach SOLIDWORKS", "modules": loaded}))
        return 3
    print(json.dumps({"manifest": str(path), "solidworks_modules_loaded": []}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
