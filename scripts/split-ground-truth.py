"""Move the template path and name hashes from ground_truth.json to the private overlay.

The fixture kit hashes the paths and user names stored in the SOLIDWORKS templates
with plain SHA-256 of the lower-cased text. Among them are the generating account's
own Desktop and Temp folders and its name, and an unsalted hash of a short name can
be confirmed by one guess. So the public ground_truth.json keeps only the counts, and
the hashes live in tests/fixtures/ground_truth.private.json under "_template_hashes",
which the private fixtures carry.

Run it once on the kit's output, or on an older public copy that still has them:

    python scripts/split-ground-truth.py
    python scripts/split-ground-truth.py --from old-ground_truth.json

It rewrites ground_truth.json without the hashes, merges them into the private
overlay (creating it if needed) and updates ground_truth.json's line in
SHA256SUMS.txt. Running it again changes nothing.
"""

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
KEYS = ("embedded_path_sha256", "name_sha256")


def _dump(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _templates(data: dict) -> dict:
    return (data.get("_generation") or {}).get("templates") or {}


def hashes_of(source: dict) -> dict:
    """The template hashes ``source`` holds, by template."""
    hashes: dict = {}
    for name, entry in _templates(source).items():
        if isinstance(entry, dict):
            found = {k: entry[k] for k in KEYS if entry.get(k)}
            if found:
                hashes[name] = found
    return hashes


def strip(text: str) -> str:
    """The kit's ground_truth.json text without the hash lists, every other line as it was,
    so its diff shows only what left. Checked against the parsed file before it is used."""
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip() in (f'"{k}": [' for k in KEYS):
            depth = len(line) - len(line.lstrip())
            i += 1
            while not (lines[i].strip() in ("]", "],") and len(lines[i]) - len(lines[i].lstrip()) == depth):
                i += 1
            if not lines[i].strip().endswith(","):  # the list was the last member
                out[-1] = out[-1].rstrip(",")
            i += 1
            continue
        out.append(line)
        i += 1
    stripped = "\n".join(out)
    want = json.loads(text)
    for entry in _templates(want).values():
        if isinstance(entry, dict):
            for k in KEYS:
                entry.pop(k, None)
    if json.loads(stripped) != want:
        raise SystemExit("ground_truth.json is not laid out as the kit writes it; nothing changed")
    return stripped


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from", dest="source", help="a ground_truth.json that still has the hashes")
    ap.add_argument("--fixtures", default=str(FIXTURES), help="the fixtures folder (default tests/fixtures)")
    args = ap.parse_args(argv)
    folder = Path(args.fixtures)
    public_path = folder / "ground_truth.json"
    private_path = folder / "ground_truth.private.json"
    hashes = hashes_of(json.loads(Path(args.source or public_path).read_text(encoding="utf-8")))
    text = strip(public_path.read_text(encoding="utf-8"))
    private = json.loads(private_path.read_text(encoding="utf-8")) if private_path.is_file() else {}
    kept = private.setdefault("_template_hashes", {})
    for name, found in hashes.items():
        kept.setdefault(name, {}).update(found)
    public_path.write_bytes(text.encode("utf-8"))
    private_path.write_bytes(_dump(private).encode("utf-8"))
    sums = folder / "SHA256SUMS.txt"
    if sums.is_file():
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        lines = [
            f"{digest}  ground_truth.json" if line.endswith("  ground_truth.json") else line
            for line in sums.read_text(encoding="utf-8").splitlines()
        ]
        sums.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    print(f"moved the hashes of {len(hashes)} templates to {private_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
