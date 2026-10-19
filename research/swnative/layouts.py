"""Field layouts of the archive's classes, inferred from every instance in the fixtures.

The analysis side of ``docs/NATIVE_SLDPRT_WRITER.md`` section 15. A part's
``Config-<n>`` and ``Config-<n>-ResolvedFeatures`` are one MFC ``CArchive``
(section 4.6); :func:`instances` splits both into class tokens with the
archive's object map and takes, for each token, the bytes up to the next one:
the object's own leading fields, before its first child object.

:func:`layout` lines up the instances of one class that have the same length
and marks each byte constant or variable; variable runs are named by what
they hold on every instance (a double, a FILETIME, a Unix time, a small
counter, UTF-16 text). Instances whose length differs are grouped by length,
which is how a variable field (a name, a list) shows itself. The result is
evidence for the specification, not the specification: two instances agreeing
on a byte does not make it a constant SOLIDWORKS requires.

``python -m swnative.layouts tests/fixtures/*.SLDPRT [--class NAME] [--json]``
prints the catalog. It reads the files and writes nothing.
"""

from __future__ import annotations

import json
import math
import struct
from collections import defaultdict
from dataclasses import asdict, dataclass, field

from solidseas.nativewrite.container import read_document

from . import features as F
from .objdiff import FILETIME_2000, FILETIME_2100, UNIX_2020, UNIX_2040


@dataclass(frozen=True)
class Instance:
    source: str  # file name and stream
    stream: str  # "config" or "features"
    offset: int  # of the class token
    cls: str
    kind: str  # "def" (a new-class record) or "ref" (a class reference)
    raw: bytes  # from the end of the token to the next token
    strings: tuple[str, ...] = ()  # the CStrings in raw, in order

    @property
    def body(self) -> bytes:
        """``raw`` with each CString emptied, so instances with other names line up."""
        return _blank_strings(self.raw)[0]


_CSTRING = b"\xff\xfe\xff"


def _cstring_at(data: bytes, i: int) -> tuple[str, int] | None:
    """MFC's Unicode CString at ``i``: FF FE FF, a length (a byte, or FF and a u16), UTF-16."""
    if data[i : i + 3] != _CSTRING or i + 4 > len(data):
        return None
    n, at = data[i + 3], i + 4
    if n == 0xFF:
        if at + 2 > len(data):
            return None
        n, at = struct.unpack_from("<H", data, at)[0], at + 2
    raw = data[at : at + 2 * n]
    if len(raw) != 2 * n:
        return None
    try:
        text = raw.decode("utf-16-le")
    except UnicodeDecodeError:
        return None
    if not text.isprintable():
        return None
    return text, at + 2 * n


def _blank_strings(data: bytes) -> tuple[bytes, tuple[str, ...]]:
    out, texts, i = bytearray(), [], 0
    while i < len(data):
        found = _cstring_at(data, i) if data[i] == 0xFF else None
        if found:
            texts.append(found[0])
            out += _CSTRING + b"\x00"
            i = found[1]
            continue
        out.append(data[i])
        i += 1
    return bytes(out), tuple(texts)


@dataclass
class Field:
    start: int
    end: int
    kind: str  # const, f64, filetime, unixtime, counter, text, bytes
    values: list = field(default_factory=list)  # distinct values seen, at most a few


@dataclass
class Layout:
    cls: str
    length: int
    count: int  # instances of this length
    sources: int  # distinct files
    fields: list[Field]
    strings: list[list[str]] = field(default_factory=list)  # per CString slot, the texts seen

    def constant_fraction(self) -> float:
        if not self.length:
            return 1.0
        return sum(f.end - f.start for f in self.fields if f.kind == "const") / self.length


def _tokens(data: bytes, start: int, refs: list[tuple[int, int]], classes: dict[int, str]):
    marks: dict[int, tuple[str, str, int]] = {}
    for off, idx in refs:
        if off >= start:
            marks[off] = ("ref", classes[idx], 2)
    for r in F.class_records(data):
        if r.offset >= start:
            marks[r.offset] = ("def", r.name, 6 + len(r.name))
    offs = sorted(marks)
    for i, o in enumerate(offs):
        kind, cls, n = marks[o]
        nxt = offs[i + 1] if i + 1 < len(offs) else len(data)
        yield o, cls, kind, data[o + n : nxt]


def instances(paths, configuration: int = 0) -> list[Instance]:
    """Every class token of ``Config-<n>`` and its feature stream in each part that maps cleanly."""
    out: list[Instance] = []
    name = f"Contents/Config-{configuration}"
    for path in paths:
        doc = read_document(path)
        names = {m.name for m in doc.members}
        if name not in names or f"{name}-ResolvedFeatures" not in names:
            continue
        config, feats = doc.data(name), doc.data(f"{name}-ResolvedFeatures")
        try:
            after_config, after_feats = F.object_map(config, feats)
        except F.FeatureStreamError:
            continue  # the imported-body parts, whose scan is 8 short (section 4.6)
        start_map = F.ObjectMap({}, F.name_tag(feats)[0] - 2).walk(config)
        label = str(path).rsplit("/", 1)[-1]
        for off, cls, kind, body in _tokens(config, 0, start_map.references, after_config.classes):
            out.append(
                Instance(
                    f"{label}:Config-{configuration}", "config", off, cls, kind, body, _blank_strings(body)[1]
                )
            )
        for off, cls, kind, body in _tokens(feats, 6, after_feats.references, after_feats.classes):
            out.append(
                Instance(
                    f"{label}:ResolvedFeatures", "features", off, cls, kind, body, _blank_strings(body)[1]
                )
            )
    return out


def _kind(columns: list[bytes]) -> tuple[str, list]:
    """What a variable run holds on every instance, judged on the run's own bytes."""
    n = len(columns[0])
    if n == 8:
        ft = [int.from_bytes(c, "little") for c in columns]
        if all(FILETIME_2000 <= v <= FILETIME_2100 for v in ft):
            return "filetime", sorted(set(ft))[:4]
        fs = [struct.unpack("<d", c)[0] for c in columns]
        if all(math.isfinite(v) and (v == 0 or 1e-9 <= abs(v) <= 1e4) for v in fs):
            return "f64", sorted(set(round(v, 9) for v in fs))[:6]
    if n == 4:
        us = [int.from_bytes(c, "little") for c in columns]
        if all(UNIX_2020 <= v <= UNIX_2040 for v in us):
            return "unixtime", sorted(set(us))[:4]
    if n in (1, 2, 4):
        vs = [int.from_bytes(c, "little") for c in columns]
        if max(vs) < (1 << 20):
            return "counter", sorted(set(vs))[:8]
    if n % 2 == 0 and all(_utf16(c) for c in columns):
        return "text", sorted(set(c.decode("utf-16-le") for c in columns))[:4]
    return "bytes", sorted(set(c.hex() for c in columns))[:3]


def _utf16(b: bytes) -> bool:
    try:
        s = b.decode("utf-16-le")
    except UnicodeDecodeError:
        return False
    return s.isprintable()


def layout(group: list[Instance]) -> Layout:
    """The constant and variable runs of instances of one class with one body length."""
    body = [i.body for i in group]
    length = len(body[0])
    varying = [len({b[k] for b in body}) > 1 for k in range(length)]
    fields: list[Field] = []
    k = 0
    while k < length:
        j = k
        while j < length and varying[j] == varying[k]:
            j += 1
        if not varying[k]:
            fields.append(Field(k, j, "const", [body[0][k:j].hex()]))
        else:
            fields.extend(_classify_run(body, k, j))
        k = j
    slots = max((len(i.strings) for i in group), default=0)
    strings = [sorted({i.strings[k] for i in group if k < len(i.strings)})[:6] for k in range(slots)]
    return Layout(
        group[0].cls, length, len(group), len({i.source.split(":")[0] for i in group}), fields, strings
    )


def _classify_run(body: list[bytes], k: int, j: int) -> list[Field]:
    """Name a run of varying bytes, trying the widths a field is likely to have.

    A double whose high bytes agree on every instance varies only in its low bytes, so the
    run is tried as the 8 bytes that end where it ends, and as the 4 that do, before it is
    taken as it stands. A longer run is tried as whole doubles ending where it ends."""
    length = len(body[0])
    if j - k > 8:
        cells = -(-(j - k) // 8)
        s = j - 8 * cells
        if s >= 0:
            found = [_kind([b[c : c + 8] for b in body]) for c in range(s, j, 8)]
            if all(kind in ("f64", "filetime") for kind, _ in found):
                return [Field(s + 8 * n, s + 8 * n + 8, kind, v) for n, (kind, v) in enumerate(found)]
    for width in (8, 4):
        s = j - width
        if s <= k and s >= 0 and j - k <= width:
            kind, values = _kind([b[s:j] for b in body])
            if kind in ("f64", "filetime", "unixtime") or (width == 4 and kind == "counter"):
                return [Field(s, j, kind, values)]
        s = k
        if s + width <= length and j - k <= width:
            kind, values = _kind([b[s : s + width] for b in body])
            if kind in ("f64", "filetime", "unixtime"):
                return [Field(s, s + width, kind, values)]
    kind, values = _kind([b[k:j] for b in body])
    return [Field(k, j, kind, values)]


def catalog(insts: list[Instance]) -> dict[str, list[Layout]]:
    """Each class's layouts, one per body length, the most common length first."""
    by: dict[str, dict[int, list[Instance]]] = defaultdict(lambda: defaultdict(list))
    for i in insts:
        by[i.cls][len(i.body)].append(i)
    out: dict[str, list[Layout]] = {}
    for cls, lengths in by.items():
        out[cls] = [layout(g) for _, g in sorted(lengths.items(), key=lambda kv: (-len(kv[1]), kv[0]))]
    return out


def _merge_overlaps(fields: list[Field]) -> list[Field]:
    """Fields from :func:`_classify_run` may reach back over a constant run; trim those."""
    out: list[Field] = []
    for f in fields:
        while out and out[-1].end > f.start:
            last = out.pop()
            if last.start < f.start:
                out.append(Field(last.start, f.start, last.kind, last.values))
        out.append(f)
    return out


def describe(lay: Layout) -> str:
    parts = []
    for f in _merge_overlaps(lay.fields):
        if f.kind == "const":
            hexs = f.values[0]
            shown = hexs if len(hexs) <= 48 else hexs[:44] + ".."
            parts.append(f"  {f.start:4d}..{f.end:<4d} const {shown}")
        else:
            parts.append(f"  {f.start:4d}..{f.end:<4d} {f.kind:8s} {f.values}")
    head = (
        f"{lay.cls}  {lay.length} bytes  {lay.count} instances in {lay.sources} files  "
        f"{lay.constant_fraction():.0%} constant"
    )
    texts = [f"  string {k + 1}: {v}" for k, v in enumerate(lay.strings)]
    return "\n".join([head, *texts, *parts])


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Inferred field layouts of the archive's classes.")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--class", dest="cls", action="append", help="only these classes")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    cat = catalog(instances(args.paths))
    if args.cls:
        cat = {k: v for k, v in cat.items() if k in args.cls}
    if args.json:
        print(json.dumps({k: [asdict(x) for x in v] for k, v in cat.items()}, indent=1, default=str))
        return 0
    for cls in sorted(cat):
        for lay in cat[cls]:
            print(describe(lay))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
