"""Copy the private SOLIDWORKS fixtures into tests/fixtures.

The documents the fixture kit made through SOLIDWORKS, and its two logs, carry the name
of the Windows account that ran it, so they are kept in the private repository
SolidSeas/SolidSeas-fixtures rather than this one. With a clone of it:

    python scripts/fetch-fixtures.py --from ../SolidSeas-fixtures

Every file is checked against tests/fixtures/SHA256SUMS.txt before it is copied, and
nothing already in tests/fixtures is replaced unless it is the same file. Git ignores
the copies (.gitignore), so they cannot be committed here by accident.
"""

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
PATTERNS = (
    "*.SLDPRT", "*.SLDASM", "*.SLDDRW", "generation.log", "scrub_report.txt", "ground_truth.private.json",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from", dest="source", required=True, help="a clone of SolidSeas/SolidSeas-fixtures")
    args = ap.parse_args(argv)
    src = Path(args.source).resolve()
    sums = {}
    for line in (FIXTURES / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        digest, _, name = line.partition("  ")
        sums[name.strip()] = digest.strip()
    files = sorted({p for pat in PATTERNS for p in src.glob(pat) if p.is_file()})
    if not files:
        print(f"no fixtures in {src}", file=sys.stderr)
        return 2
    copied = 0
    for p in files:
        want = sums.get(p.name)
        if want is not None and _sha(p) != want:
            print(f"{p.name}: SHA-256 does not match SHA256SUMS.txt", file=sys.stderr)
            return 3
        dest = FIXTURES / p.name
        if dest.exists():
            if _sha(dest) == _sha(p):
                continue
            print(f"{dest.name} exists and differs; not replaced", file=sys.stderr)
            return 4
        shutil.copyfile(p, dest)
        copied += 1
    print(f"{copied} fixtures copied, {len(files) - copied} already there")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
