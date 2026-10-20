"""Compile the listings of docs/sldprt-spec into src/solidseas/nativewrite/generate/_listings.py.

The generator ships the listings as data and never reads docs/ while it runs
(docs/CLEANROOM.md section 2). This script reads the member table of section
15.0.1 (docs/sldprt-spec/README.md) and every listing it names, parses each
with the generator's own reader (generate/listing.py), and writes one Python
module holding the operations, every line citing its section, file and line.

    python scripts/compile-sldprt-spec.py           # write the module
    python scripts/compile-sldprt-spec.py --check   # exit 1 when it is out of date

The output depends only on the specification, so running it twice gives the
same bytes.
"""

import argparse
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs" / "sldprt-spec"
GENERATE = ROOT / "src" / "solidseas" / "nativewrite" / "generate"
OUTPUT = GENERATE / "_listings.py"
_ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*`([^`]+)`\s*\|\s*([\d.]+)\s*\|\s*`([^`]+\.srl)`\s*\|\s*$")


def _listing_module():
    """generate/listing.py, loaded by path so the package (and its compiled data) is not needed."""
    name = "_sldprt_listing_compiler"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, GENERATE / "listing.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def member_table(root: Path = ROOT) -> list[tuple[str, str, str]]:
    """The rows of the member table of section 15.0.1: (member, section, listing), in order."""
    rows = []
    for line in (root / "docs" / "sldprt-spec" / "README.md").read_text(encoding="utf-8").splitlines():
        m = _ROW.match(line)
        if m:
            if int(m.group(1)) != len(rows) + 1:
                raise SystemExit(f"member table: row {m.group(1)} out of order")
            rows.append((m.group(2), m.group(3), m.group(4)))
    if not rows:
        raise SystemExit("member table not found in docs/sldprt-spec/README.md")
    return rows


def _render_ops(ops: tuple, indent: int, out: list[str]) -> None:
    pad = "    " * indent
    for op in ops:
        kind, loc = op[0], op[-1]
        cite = f"  # spec {loc}"
        if kind == "if":
            out.append(f"{pad}({kind!r}, {op[1]!r}, ({cite}")
            _render_ops(op[2], indent + 1, out)
            out.append(f"{pad}), ({cite}")
            _render_ops(op[3], indent + 1, out)
            out.append(f"{pad}), {loc!r}),{cite}")
        elif kind in ("for", "sized", "zlb"):
            head = ", ".join(repr(x) for x in op[1:-2])
            out.append(f"{pad}({kind!r}, {head}, ({cite}")
            _render_ops(op[-2], indent + 1, out)
            out.append(f"{pad}), {loc!r}),{cite}")
        elif kind == "text":
            head = ", ".join(repr(x) for x in op[1:5])
            out.append(f"{pad}({kind!r}, {head}, ({cite}")
            for line in op[5]:
                out.append(f"{pad}    {line!r},{cite}")
            out.append(f"{pad}), {loc!r}),{cite}")
        else:
            out.append(f"{pad}{op!r},{cite}")


def render(root: Path = ROOT) -> str:
    """The text of _listings.py for the specification under ``root``."""
    listing = _listing_module()
    folder = root / "docs" / "sldprt-spec" / "listings"

    def loader(name: str) -> str:
        if "/" in name or "\\" in name or not name.endswith(".srl"):
            raise listing.ListingError(f"@include {name}: not a listing of the folder")
        return (folder / name).read_text(encoding="utf-8")

    rows = member_table(root)
    out = [
        '"""The listings of section 15 (docs/sldprt-spec/listings), compiled into operations.',
        "",
        "Written by scripts/compile-sldprt-spec.py; do not edit, run the script again.",
        "Each operation is one line of a listing (generate/listing.py says how to read",
        "them) and cites its section, file and line. MEMBERS is the member table of",
        "section 15.0.1, in order: (member, section, listing).",
        '"""',
        "",
        "# ruff: noqa: E501",
        "",
        "MEMBERS = (",
    ]
    for member, section, file in rows:
        out.append(f"    ({member!r}, {section!r}, {file!r}),  # spec 15.0.1 {file}")
    out += [")", "", "LISTINGS = {"]
    for member, section, file in rows:
        parsed = listing.parse(file, loader, section=section)
        if parsed.member != member:
            raise SystemExit(f"{file}: @member {parsed.member!r}, the table says {member!r}")
        out.append(f"    {member!r}: (  # spec {section} {file}")
        _render_ops(parsed.ops, 2, out)
        out.append(f"    ),  # spec {section} {file}")
    out += ["}", ""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="only check that the module is up to date")
    args = ap.parse_args(argv)
    text = render()
    current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else None
    if args.check:
        if current != text:
            print(f"{OUTPUT.relative_to(ROOT)} is out of date: run scripts/compile-sldprt-spec.py")
            return 1
        print(f"{OUTPUT.relative_to(ROOT)} is up to date")
        return 0
    if current != text:
        OUTPUT.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {OUTPUT.relative_to(ROOT)}")
    else:
        print(f"{OUTPUT.relative_to(ROOT)} unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
