"""A typed reading of an undecoded run of archive bytes.

The first level of decoding ``docs/NATIVE_SLDPRT_WRITER.md`` 4.9 asks for:
before a field's meaning is known, its type and value usually are. This walks
a run and takes, at each position, the first reading that fits:

- a ``CString`` (MFC's Unicode form, ``FF FE FF``, a length, UTF-16);
- a class record (``FF FF``, schema, name) or a run of ``FF``;
- a double that looks deliberate: a length of whole hundredths of a
  millimetre up to 10 m, an angle that is a whole number of degrees, or one of
  0.5, 1, 2;
- a u32 that is zero, small (under 65,536) or ``FFFFFFFF``;
- otherwise one byte.

It reads offsets inside a run only, so a reading is a guess about alignment
as much as about type: two readings of the same bytes can both fit. Its use is
to make a block readable enough to compare across parts and to plan which
SOLIDWORKS setting to change to learn a field's meaning.

``python -m swnative.typedump part.sldprt --stream Contents/Config-0 --from 3980 --to 4926``
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from .layouts import _cstring_at


@dataclass(frozen=True)
class Item:
    offset: int
    size: int
    kind: str  # cstring, class, ff, length, angle, f64, u32, byte
    value: object

    def text(self) -> str:
        if self.kind == "length":
            return f"{self.offset:6d} f64    {self.value:g} mm"
        if self.kind == "angle":
            return f"{self.offset:6d} f64    {self.value:g} deg"
        if self.kind == "cstring":
            return f"{self.offset:6d} str    {self.value!r}"
        if self.kind == "byte":
            return f"{self.offset:6d} byte   {self.value:02x}"
        return f"{self.offset:6d} {self.kind:6s} {self.value}"


def _double(data: bytes, i: int) -> Item | None:
    if i + 8 > len(data):
        return None
    (v,) = struct.unpack_from("<d", data, i)
    if not math.isfinite(v) or v == 0:
        return None
    mm = v * 1000
    if 1e-6 < abs(v) <= 10 and abs(mm * 100 - round(mm * 100)) < 1e-6:
        return Item(i, 8, "length", round(mm, 4))
    deg = math.degrees(v)
    if 1e-3 < abs(v) <= 2 * math.pi + 1e-9 and abs(deg - round(deg)) < 1e-6 and round(deg) % 5 == 0:
        return Item(i, 8, "angle", round(deg))
    if v in (0.5, 1.0, 2.0, -1.0):
        return Item(i, 8, "f64", v)
    return None


def items(data: bytes, start: int = 0, end: int | None = None) -> list[Item]:
    end = len(data) if end is None else end
    out: list[Item] = []
    i = start
    while i < end:
        if data[i] == 0xFF:
            found = _cstring_at(data, i)
            if found:
                out.append(Item(i, found[1] - i, "cstring", found[0]))
                i = found[1]
                continue
            if data[i + 1 : i + 2] == b"\xff" and i + 6 <= end:
                n = struct.unpack_from("<H", data, i + 4)[0]
                name = data[i + 6 : i + 6 + n]
                if 3 <= n <= 64 and name.isascii() and name.decode().isidentifier():
                    out.append(Item(i, 6 + n, "class", name.decode()))
                    i += 6 + n
                    continue
            j = i
            while j < end and data[j] == 0xFF:
                j += 1
            if j - i >= 4:
                out.append(Item(i, j - i, "ff", j - i))
                i = j
                continue
        d = _double(data, i)
        if d:
            out.append(d)
            i += 8
            continue
        if i + 4 <= end:
            (u,) = struct.unpack_from("<I", data, i)
            if u == 0 and data[i : i + 8] == bytes(8) and i + 8 <= end:
                j = i
                while j < end and data[j] == 0:
                    j += 1
                out.append(Item(i, j - i, "zeros", j - i))
                i = j
                continue
            if 0 < u < 65536 and i % 2 == 0:
                out.append(Item(i, 4, "u32", u))
                i += 4
                continue
        out.append(Item(i, 1, "byte", data[i]))
        i += 1
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    from solidseas.nativewrite.container import read_document

    ap = argparse.ArgumentParser(description="A typed reading of a run of a member's bytes.")
    ap.add_argument("path")
    ap.add_argument("--stream", default="Contents/Config-0")
    ap.add_argument("--from", dest="start", type=int, default=0)
    ap.add_argument("--to", dest="end", type=int)
    args = ap.parse_args(argv)
    data = read_document(args.path).data(args.stream)
    for it in items(data, args.start, args.end):
        print(it.text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
