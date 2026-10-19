"""Seeded mutation fuzzing for the readers (bead ddi).

A case is a seed file and a numbered mutation of it, made by a ``random.Random`` seeded
from both, so a failure names the case and repeats exactly. The suite runs a few
seconds of cases; ``SOLIDSEAS_FUZZ_SECONDS`` runs longer and ``SOLIDSEAS_FUZZ_SEED``
starts elsewhere.

Every case must end in a read or in a documented exception (``SolidSeasError`` and its
subclasses) within its time bound, and its Python allocations must stay under
:data:`PEAK_BYTES`. Any other exception, a hang or a memory blow-up is a bug.
"""

from __future__ import annotations

import os
import random
import struct
import time
import tracemalloc
from collections.abc import Callable, Iterator

from solidseas.errors import SolidSeasError
from support import within

SECONDS_PER_CASE = 10.0  # what one mutated file may cost, at most
PEAK_BYTES = 512 * 1024 * 1024  # Python allocations one read may reach
LIMITS = (0, 1, 0x7F, 0x80, 0xFF, 0x7FFF, 0xFFFF, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF)


def budget(default: float) -> float:
    """Seconds of cases for this run: ``SOLIDSEAS_FUZZ_SECONDS``, else ``default``."""
    try:
        return max(0.0, float(os.environ.get("SOLIDSEAS_FUZZ_SECONDS", default)))
    except ValueError:
        return default


def start() -> int:
    try:
        return int(os.environ.get("SOLIDSEAS_FUZZ_SEED", "0"))
    except ValueError:
        return 0


def mutate(data: bytes, rng: random.Random) -> tuple[bytes, str]:
    """One mutation of ``data`` and what it was, in words."""
    if not data:
        return bytes(rng.randrange(256) for _ in range(rng.randrange(1, 64))), "random bytes"
    buf = bytearray(data)
    n = len(buf)
    kind = rng.randrange(7)
    if kind == 0:
        flips = rng.randrange(1, 9)
        for _ in range(flips):
            i = rng.randrange(n)
            buf[i] ^= 1 << rng.randrange(8)
        return bytes(buf), f"{flips} bit flips"
    if kind == 1:
        cut = rng.randrange(n)
        return bytes(buf[:cut]), f"truncated at {cut}"
    if kind == 2:
        i = rng.randrange(max(1, n - 3))
        value = rng.choice(LIMITS)
        struct.pack_into("<I", buf, i, value) if i + 4 <= n else None
        return bytes(buf), f"u32 {value:#x} at {i}"
    if kind == 3:
        i = rng.randrange(max(1, n - 1))
        value = rng.choice(LIMITS) & 0xFFFF
        struct.pack_into("<H", buf, i, value) if i + 2 <= n else None
        return bytes(buf), f"u16 {value:#x} at {i}"
    if kind == 4:
        i, size = rng.randrange(n), rng.randrange(1, 4097)
        j = rng.randrange(n)
        chunk = bytes(buf[i : i + size])
        buf[j : j + len(chunk)] = chunk
        return bytes(buf[:n]), f"{len(chunk)} bytes from {i} copied to {j}"
    if kind == 5:
        i, size = rng.randrange(n), rng.randrange(1, 513)
        buf[i : i + size] = bytes(min(size, n - i))
        return bytes(buf), f"{min(size, n - i)} bytes zeroed at {i}"
    i, size = rng.randrange(n), rng.randrange(1, 257)
    filler = bytes([rng.choice((0x00, 0xFF))]) * size
    return bytes(buf[:i] + filler + buf[i:]), f"{size} bytes inserted at {i}"


def cases(seeds: dict[str, bytes], seconds: float, first: int) -> Iterator[tuple[str, int, bytes, str]]:
    """``(seed name, case number, mutated bytes, what was done)`` round the seeds until
    ``seconds`` have passed (at least one case per seed)."""
    names = sorted(seeds)
    end = time.monotonic() + seconds
    k = first
    while True:
        for name in names:
            rng = random.Random(f"{name}:{k}")
            data, what = mutate(seeds[name], rng)
            yield name, k, data, what
        k += 1
        if time.monotonic() >= end:
            return


def check(read: Callable[[bytes], object], data: bytes, label: str) -> str | None:
    """Run ``read`` on ``data``; None when it read or raised a documented exception within
    its bounds, else what went wrong."""
    tracemalloc.start()
    t0 = time.monotonic()
    try:
        read(data)
        outcome = None
    except SolidSeasError:
        outcome = None
    except Exception as exc:  # noqa: BLE001 - any other exception is the finding
        outcome = f"{label}: {type(exc).__name__}: {exc}"[:500]
    finally:
        _now, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    took = time.monotonic() - t0
    if outcome is None and took > within(SECONDS_PER_CASE):
        outcome = f"{label}: took {took:.1f} s"
    if outcome is None and peak > PEAK_BYTES:
        outcome = f"{label}: allocated {peak / 2**20:.0f} MiB"
    return outcome
