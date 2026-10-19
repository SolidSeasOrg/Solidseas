"""Object-level differences between two SOLIDWORKS parts' feature streams.

The research harness of ``docs/NATIVE_SLDPRT_WRITER.md`` section 5: it splits
a span of ``Config-<n>-ResolvedFeatures`` into class tokens with the archive's
object map (:class:`.features.ObjectMap`), aligns two documents' tokens by
class, and sorts every differing byte run into a kind:

- ``double``: a run inside an 8-byte little-endian double on both sides; the
  values are given in millimetres when they look like lengths;
- ``filetime``: a Windows FILETIME (100 ns since 1601) on both sides, between
  2000 and 2100;
- ``unixtime``: a u32 between 2020 and 2040;
- ``counter``: a small integer that went up or down by less than 4096;
- ``text``: inside a UTF-16 run of printable letters;
- ``other``: anything else.

``python -m swnative.objdiff a.sldprt b.sldprt --from Sketch1 --to Boss-Extrude1``
prints the classified runs as JSON. It reads both files and writes nothing.
"""

import difflib
import json
import math
import struct
from dataclasses import asdict, dataclass

from solidseas.nativewrite.container import read_document

from . import features as F

FILETIME_2000, FILETIME_2100 = 125911584000000000, 157469184000000000
UNIX_2020, UNIX_2040 = 1577836800, 2208988800


@dataclass(frozen=True)
class Token:
    kind: str  # "def", "ref" or "raw"
    offset: int
    data: bytes
    cls: str | None = None
    index: int | None = None  # the class's index in the object map


@dataclass
class Run:
    after: str | None  # the class token the run follows
    kind: str
    a_offset: int
    b_offset: int
    a: str
    b: str
    a_value: object = None
    b_value: object = None


def tokens(
    doc, first: str, last: str | None = None, stream: str = "Contents/Config-0-ResolvedFeatures"
) -> list[Token]:
    """The class and raw tokens from feature ``first``'s named node to the end of ``last``'s span."""
    data = doc.data(stream)
    start, _ = F.feature_span(data, first)
    _, end = F.feature_span(data, last or first)
    config = doc.data(stream.replace("-ResolvedFeatures", ""))
    _, m = F.object_map(config, data)
    marks: dict[int, Token] = {}
    for off, idx in m.references:
        if start <= off < end:
            marks[off] = Token("ref", off, data[off : off + 2], m.classes[idx], idx)
    for r in F.class_records(data):
        if start <= r.offset < end:
            idx = next((k for k, v in m.classes.items() if v == r.name), None)
            marks[r.offset] = Token("def", r.offset, data[r.offset : r.offset + 6 + len(r.name)], r.name, idx)
    out: list[Token] = []
    prev = start
    for off in sorted(marks):
        if off > prev:
            out.append(Token("raw", prev, data[prev:off]))
        t = marks[off]
        out.append(t)
        prev = off + len(t.data)
    if end > prev:
        out.append(Token("raw", prev, data[prev:end]))
    return out


def _windows(buf: bytes, i: int, j: int, size: int):
    """Start offsets of ``size``-byte windows that cover ``buf[i:j]``, the one starting at ``i`` first."""
    starts = [i] + [s for s in range(max(0, j - size), i) if s != i]
    return [s for s in starts if s + size <= len(buf) and s <= i and s + size >= j]


def _pairs(a: bytes, b: bytes, i1: int, i2: int, j1: int, j2: int, size: int):
    for sa in _windows(a, i1, i2, size):
        sb = j1 + (sa - i1)
        if sb + size <= len(b) and sb >= 0:
            yield a[sa : sa + size], b[sb : sb + size]


def classify(a: bytes, b: bytes, i1: int, i2: int, j1: int, j2: int) -> tuple[str, object, object]:
    if (i2 - i1) != (j2 - j1):
        return "other", None, None
    year_s, year_ft = 31_557_600, 31_557_600 * 10_000_000
    for x, y in _pairs(a, b, i1, i2, j1, j2, 8):
        va, vb = int.from_bytes(x, "little"), int.from_bytes(y, "little")
        if (
            FILETIME_2000 <= va <= FILETIME_2100
            and FILETIME_2000 <= vb <= FILETIME_2100
            and abs(va - vb) < year_ft
        ):
            return "filetime", va, vb
    for x, y in _pairs(a, b, i1, i2, j1, j2, 4):
        va, vb = int.from_bytes(x, "little"), int.from_bytes(y, "little")
        if UNIX_2020 <= va <= UNIX_2040 and UNIX_2020 <= vb <= UNIX_2040 and abs(va - vb) < year_s:
            return "unixtime", va, vb
    for x, y in _pairs(a, b, i1, i2, j1, j2, 8):
        (fa,), (fb,) = struct.unpack("<d", x), struct.unpack("<d", y)
        ok = [math.isfinite(v) and (v == 0 or 1e-6 <= abs(v) <= 10) for v in (fa, fb)]
        if all(ok) and (fa != 0 or fb != 0):
            return "double", round(fa * 1000, 6), round(fb * 1000, 6)
    for size in (1, 2, 4):
        for x, y in _pairs(a, b, i1, i2, j1, j2, size):
            va, vb = int.from_bytes(x, "little"), int.from_bytes(y, "little")
            if va < (1 << 20) and vb < (1 << 20) and abs(va - vb) < 4096:
                return "counter", va, vb
    if _is_text(a, i1) and _is_text(b, j1):
        return "text", a[i1:i2].decode("latin-1"), b[j1:j2].decode("latin-1")
    return "other", None, None


def _is_text(buf: bytes, i: int) -> bool:
    lo = i - (i % 2)
    window = buf[max(0, lo - 4) : lo + 6]
    if len(window) < 6:
        return False
    chars = [window[k] for k in range(0, len(window) - 1, 2) if window[k + 1] == 0]
    return len(chars) >= 3 and all(32 <= c < 127 for c in chars)


def compare(ta: list[Token], tb: list[Token]) -> dict:
    """Aligned differences of two token lists: class sequence changes and classified raw runs."""
    ka = [t.cls if t.kind != "raw" else None for t in ta]
    kb = [t.cls if t.kind != "raw" else None for t in tb]
    sm = difflib.SequenceMatcher(None, ka, kb, autojunk=False)
    unaligned, runs = [], []
    after = None
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != "equal" and (i2 - i1) != (j2 - j1):
            unaligned.append(
                {
                    "op": op,
                    "a": [t.cls or len(t.data) for t in ta[i1:i2]],
                    "b": [t.cls or len(t.data) for t in tb[j1:j2]],
                }
            )
            continue
        for x, y in zip(ta[i1:i2], tb[j1:j2], strict=True):
            if x.kind != "raw":
                after = x.cls
                if x.kind != y.kind:
                    runs.append(Run(after, "def-or-ref", x.offset, y.offset, x.kind, y.kind))
                continue
            if x.data == y.data:
                continue
            m2 = difflib.SequenceMatcher(None, x.data, y.data, autojunk=False)
            for op2, a1, a2, b1, b2 in m2.get_opcodes():
                if op2 == "equal":
                    continue
                kind, va, vb = classify(x.data, y.data, a1, a2, b1, b2)
                runs.append(
                    Run(
                        after,
                        kind if op2 == "replace" else f"{op2}",
                        x.offset + a1,
                        y.offset + b1,
                        x.data[a1:a2].hex(),
                        y.data[b1:b2].hex(),
                        va,
                        vb,
                    )
                )
    counts: dict[str, int] = {}
    for r in runs:
        counts[r.kind] = counts.get(r.kind, 0) + 1
    return {"unaligned": unaligned, "counts": counts, "runs": [asdict(r) for r in runs]}


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="Classified object-level differences of two parts' feature streams."
    )
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--from", dest="first", required=True, help="the first feature's name")
    ap.add_argument("--to", dest="last", help="the last feature's name (default: --from)")
    args = ap.parse_args(argv)
    a, b = read_document(args.a), read_document(args.b)
    print(json.dumps(compare(tokens(a, args.first, args.last), tokens(b, args.first, args.last)), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
