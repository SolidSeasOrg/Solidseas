"""Take the em and en dashes out of the text bd writes into this repository.

AGENTS.md allows no em or en dashes, but bd (the beads issue tracker) writes them into
the text it keeps here, and writes them again each time it regenerates that text:

- its block in AGENTS.md and CLAUDE.md, between the BEGIN and END BEADS INTEGRATION
  markers, which bd setup and bd init replace once bd's template has changed;
- its section of each hook in .beads/hooks, between the BEADS INTEGRATION markers,
  which bd hooks install replaces, as bd asks after an upgrade;
- .beads/.gitignore, which bd doctor --fix rewrites, and the other text bd keeps in
  .beads (README.md and config.yaml).

This script turns each of those dashes into a semicolon, or into a hyphen between two
digits, in bd's text only. It leaves alone the repository's own text around bd's, the
marker lines, line endings and file modes. The BEGIN marker of the AGENTS.md and
CLAUDE.md block holds the hash of the template bd wrote the block from, which bd reads
to decide whether the block is out of date, so the marker stays as bd wrote it and bd
keeps the edited block until its own template changes.

    python scripts/undash-beads-text.py           # rewrite bd's text
    python scripts/undash-beads-text.py --check   # exit 1 when bd's text has a dash

Run it after any bd command that rewrote these files: tests/test_beads_text.py fails
until then. When bd added a hook, run scripts/install-git-hooks.sh again too.
"""

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# bd's block in an agent instructions file, and its section of a git hook: (marker, text, marker).
_BLOCK = re.compile(r"(<!-- BEGIN BEADS INTEGRATION[^\n]*\n)(.*?)(<!-- END BEADS INTEGRATION -->)", re.S)
_SECTION = re.compile(r"(# --- BEGIN BEADS INTEGRATION[^\n]*\n)(.*?)(# --- END BEADS INTEGRATION)", re.S)
BLOCK_FILES = ("AGENTS.md", "CLAUDE.md")
WHOLE_FILES = (".beads/.gitignore", ".beads/README.md", ".beads/config.yaml")
HOOKS = ".beads/hooks"
_HOOK_NAME = re.compile(r"[a-z]+(?:-[a-z]+)*")  # pre-commit, not a copy such as pre-commit.old

_RANGE = re.compile(r"(?<=\d)[\u2013\u2014](?=\d)")
_DASH = re.compile(r"[ \t]*[\u2013\u2014][ \t]*")


def undash(text: str) -> str:
    """``text`` with each em or en dash rewritten: a hyphen between two digits, else a semicolon."""
    return _DASH.sub("; ", _RANGE.sub("-", text))


def files(root: Path = ROOT) -> list[str]:
    """The files bd writes text into, as paths relative to ``root``, those that exist there."""
    names = [*BLOCK_FILES, *WHOLE_FILES]
    hooks = root / HOOKS
    if hooks.is_dir():
        names += [f"{HOOKS}/{p.name}" for p in sorted(hooks.iterdir()) if _HOOK_NAME.fullmatch(p.name)]
    return [name for name in names if (root / name).is_file()]


def bd_spans(name: str, text: str) -> list[tuple[int, int]]:
    """Where bd's own text lies in ``text``, the contents of the file ``name`` of :func:`files`."""
    if name in WHOLE_FILES:
        return [(0, len(text))]
    pattern = _BLOCK if name in BLOCK_FILES else _SECTION
    return [m.span(2) for m in pattern.finditer(text)]


def rewrite(name: str, text: str) -> str:
    """``text`` with bd's spans undashed and everything else as it was."""
    out, last = [], 0
    for start, end in bd_spans(name, text):
        out += [text[last:start], undash(text[start:end])]
        last = end
    out.append(text[last:])
    return "".join(out)


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")  # bytes, so CRLF line endings come back unchanged


def pending(root: Path = ROOT) -> list[str]:
    """The files whose bd text still has an em or en dash."""
    return [name for name in files(root) if rewrite(name, _read(root / name)) != _read(root / name)]


def fix(root: Path = ROOT) -> list[str]:
    """Rewrite bd's text in place, and return the files that changed."""
    changed = []
    for name in files(root):
        path = root / name
        text = _read(path)
        new = rewrite(name, text)
        if new != text:
            path.write_bytes(new.encode("utf-8"))  # the same file, so it keeps its mode
            changed.append(name)
    return changed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="change nothing; exit 1 when bd's text has a dash")
    ap.add_argument("--root", type=Path, default=ROOT, help="the checkout (default: this script's)")
    args = ap.parse_args(argv)
    if args.check:
        left = pending(args.root)
        for name in left:
            print(f"{name}: bd's text has an em or en dash; run python scripts/undash-beads-text.py")
        return 1 if left else 0
    for name in fix(args.root):
        print(f"rewrote bd's text in {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
