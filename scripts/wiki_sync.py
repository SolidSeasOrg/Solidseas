#!/usr/bin/env python3
"""Copy the user guide (``docs/guide/*.md``) into a checkout of the GitHub wiki.

Standard library only, Python 3.11 or later. ``scripts/sync-wiki.sh`` is the usual way in;
``docs/guide/building.md`` describes it.

The wiki keeps every page in one flat folder, named after the page's title, so each guide
page is written under a wiki name made from its file name (``where-used-and-bom.md`` becomes
``Where-Used-and-BOM.md``), with ``index.md`` as ``Home.md``. Links are rewritten to match:

* a link to another guide page goes to its wiki name, keeping any ``#anchor``;
* a link to any other file of the repository goes to it on GitHub, as
  ``<repository>/blob/<branch>/<path>`` (``tree`` for a folder);
* absolute URLs, ``mailto:`` links and links to an anchor on the same page are left alone,
  and so is anything inside code.

``_Sidebar.md`` is made from the links to guide pages in ``index.md``, in their order.

Every page written starts with a marker comment naming its source. Running again rewrites
the pages, removes a marked page whose source is gone, and leaves every page without the
marker alone, so pages made by hand on the wiki stay. It commits only when something
changed, as the repository's configured author, and pushes only with ``--push``.

Exit codes: 0 done (also when nothing changed); 1 a git command failed; 2 usage, or a link
that leaves the repository.
"""

from __future__ import annotations

import argparse
import posixpath
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GUIDE = "docs/guide"
WIKI_URL = "https://github.com/SolidSeas/SolidSeas.wiki.git"
REPOSITORY_URL = "https://github.com/SolidSeas/SolidSeas"
MARKER = "<!-- Generated from {source} by scripts/wiki_sync.py. Edit that file, not this page. -->"
MARKER_RE = re.compile(r"<!-- Generated from (\S+) by scripts/wiki_sync\.py\.")

# Words kept as written in a wiki page name, and short words left in lower case.
UPPER = {"3d": "3D", "bom": "BOM", "api": "API", "cli": "CLI", "step": "STEP", "ai": "AI"}
LOWER = {"and", "or", "of", "the", "a", "an", "in", "on", "to", "for"}

# An inline link or image, [text](target) or [text](target "title"), and a reference
# definition, [label]: target. The text may hold one level of brackets.
INLINE = re.compile(r"(!?\[(?:[^\[\]]|\[[^\[\]]*\])*\]\()(\s*<?)([^\s()<>]+)(>?(?:\s+\"[^\"]*\")?\s*\))")
REFERENCE = re.compile(r"^(\s{0,3}\[[^\]]+\]:\s*<?)([^\s<>]+)(.*)$")
SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


class SyncError(Exception):
    """A problem with the guide itself, such as a link that leaves the repository."""


@dataclass(frozen=True)
class Link:
    """One link target found in a Markdown text, with the line it is on (from 1)."""

    line: int
    target: str


def wiki_name(stem: str) -> str:
    """The wiki page name for a guide page's file name without ``.md``."""
    if stem == "index":
        return "Home"
    words = stem.split("-")
    out = []
    for i, word in enumerate(words):
        low = word.lower()
        if low in UPPER:
            out.append(UPPER[low])
        elif i and low in LOWER:
            out.append(low)
        else:
            out.append(low[:1].upper() + low[1:])
    return "-".join(out)


def _split_code(line: str) -> list[tuple[bool, str]]:
    """``line`` cut into (is_code, text) pieces at inline code spans."""
    pieces: list[tuple[bool, str]] = []
    pos = 0
    for m in re.finditer(r"(`+)(.+?)\1", line):
        if m.start() > pos:
            pieces.append((False, line[pos : m.start()]))
        pieces.append((True, m.group(0)))
        pos = m.end()
    if pos < len(line):
        pieces.append((False, line[pos:]))
    return pieces


def _map_links(text: str, change) -> str:
    """``text`` with every link target outside code replaced by ``change(target, line, label)``.

    ``line`` counts from 1, and ``label`` is the link's text (``None`` for an image)."""
    out = []
    fence = None
    for number, line in enumerate(text.split("\n"), 1):
        stripped = line.lstrip()
        if fence:
            if stripped.startswith(fence):
                fence = None
            out.append(line)
            continue
        if stripped.startswith(("```", "~~~")):
            fence = stripped[:3]
            out.append(line)
            continue
        ref = REFERENCE.match(line)
        if ref:
            out.append(ref.group(1) + change(ref.group(2), number, None) + ref.group(3))
            continue

        def inline(m, number=number):
            opening = m.group(1)
            label = None if opening.startswith("!") else opening[1:-2]
            return opening + m.group(2) + change(m.group(3), number, label) + m.group(4)

        out.append("".join(piece if code else INLINE.sub(inline, piece) for code, piece in _split_code(line)))
    return "\n".join(out)


def links(text: str) -> list[Link]:
    """Every link target in ``text`` outside code, in order."""
    found: list[Link] = []

    def keep(target, line, label):
        found.append(Link(line, target))
        return target

    _map_links(text, keep)
    return found


def is_external(target: str) -> bool:
    """Whether ``target`` is a URL, a mail link or an anchor on the same page."""
    return target.startswith("#") or bool(SCHEME.match(target))


def resolve(target: str, page: str) -> tuple[str, str]:
    """The repository path a relative link ``target`` on ``page`` names, and its ``#anchor``."""
    path, _, anchor = target.partition("#")
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(page), path)) if path else page
    if joined == ".." or joined.startswith("../") or posixpath.isabs(joined):
        raise SyncError(f"{page}: the link {target} leaves the repository")
    return joined, anchor


def rewrite_target(target: str, page: str, pages: set[str], repository: str, branch: str, root: Path) -> str:
    """The wiki form of one link ``target`` found on guide page ``page`` (a repository path).

    ``pages`` holds the repository paths of every guide page being synced."""
    if is_external(target):
        return target
    joined, anchor = resolve(target, page)
    anchor = f"#{anchor}" if anchor else ""
    if joined in pages:
        return wiki_name(posixpath.splitext(posixpath.basename(joined))[0]) + anchor
    if joined == ".":
        return f"{repository}{anchor}"
    kind = "tree" if (root / joined).is_dir() else "blob"
    return f"{repository}/{kind}/{branch}/{joined}{anchor}"


def rewrite(text: str, page: str, pages: set[str], repository: str, branch: str, root: Path) -> str:
    """Guide page ``page``'s text with every link rewritten for the wiki."""
    return _map_links(text, lambda t, _line, _label: rewrite_target(t, page, pages, repository, branch, root))


def sidebar(index_text: str, pages: set[str]) -> str:
    """``_Sidebar.md``: Home, then each guide page ``index.md`` links to, in its order."""
    index = f"{GUIDE}/index.md"
    entries: list[str] = []
    seen = {index}

    def collect(target, _line, label):
        if label is not None and not is_external(target):
            joined, _ = resolve(target, index)
            if joined in pages and joined not in seen:
                seen.add(joined)
                entries.append(f"- [{label}]({wiki_name(posixpath.splitext(posixpath.basename(joined))[0])})")
        return target

    _map_links(index_text, collect)
    return "\n".join(["**[Home](Home)**", "", *entries]) + "\n"


def build(root: Path, repository: str = REPOSITORY_URL, branch: str = "main") -> dict[str, str]:
    """Every wiki file to write, by file name, made from ``root``'s guide."""
    guide = root / GUIDE
    sources = sorted(guide.glob("*.md"))
    if not any(p.name == "index.md" for p in sources):
        raise SyncError(f"{GUIDE}/index.md is missing")
    pages = {f"{GUIDE}/{p.name}" for p in sources}
    files: dict[str, str] = {}
    for source in sources:
        page = f"{GUIDE}/{source.name}"
        text = source.read_text(encoding="utf-8")
        body = rewrite(text, page, pages, repository, branch, root)
        files[wiki_name(source.stem) + ".md"] = MARKER.format(source=page) + "\n\n" + body
        if source.name == "index.md":
            files["_Sidebar.md"] = MARKER.format(source=page) + "\n\n" + sidebar(text, pages)
    return files


def _git(wiki: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(wiki), *args], check=check, capture_output=True, text=True)


def _identity(root: Path) -> list[str]:
    """``-c user.name=... -c user.email=...`` for the repository's configured author, if set."""
    out = []
    for key in ("user.name", "user.email"):
        value = subprocess.run(
            ["git", "-C", str(root), "config", key], capture_output=True, text=True
        ).stdout.strip()
        if value:
            out += ["-c", f"{key}={value}"]
    return out


def write(wiki: Path, files: dict[str, str]) -> list[str]:
    """Write ``files`` into ``wiki`` and remove marked pages no longer made; what changed."""
    changed = []
    for old in sorted(wiki.glob("*.md")):
        if old.name in files:
            continue
        head = old.read_text(encoding="utf-8", errors="replace").split("\n", 1)[0]
        if MARKER_RE.match(head):
            old.unlink()
            changed.append(f"removed {old.name}")
    for name, text in files.items():
        target = wiki / name
        if target.is_file() and target.read_text(encoding="utf-8") == text:
            continue
        target.write_text(text, encoding="utf-8", newline="\n")
        changed.append(f"wrote {name}")
    return changed


def sync(
    wiki: Path,
    root: Path = REPO,
    *,
    push: bool = False,
    wiki_url: str = WIKI_URL,
    repository: str = REPOSITORY_URL,
    branch: str = "main",
) -> list[str]:
    """Bring the wiki checkout ``wiki`` up to date with ``root``'s guide and commit it."""
    files = build(root, repository, branch)
    if not wiki.exists():
        subprocess.run(["git", "clone", "--quiet", wiki_url, str(wiki)], check=True)
    if not (wiki / ".git").exists():
        raise SyncError(f"{wiki} is not a git checkout")
    if _git(wiki, "status", "--porcelain").stdout.strip():
        raise SyncError(f"{wiki} has uncommitted changes; commit or discard them first")
    if push and _git(wiki, "remote").stdout.strip():
        _git(wiki, "pull", "--ff-only", "--quiet")
    changed = write(wiki, files)
    _git(wiki, "add", "--all", "--", ".")
    if _git(wiki, "diff", "--cached", "--quiet", check=False).returncode == 0:
        changed = []
    else:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
        message = "Sync the user guide" + (f" from {head}" if head else "")
        _git(wiki, *_identity(root), "commit", "--quiet", "-m", message)
    if push:
        _git(wiki, "push", "--quiet")
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Copy docs/guide into a checkout of the GitHub wiki.")
    parser.add_argument("wiki", type=Path, help="the wiki checkout; cloned there when it does not exist")
    parser.add_argument("--push", action="store_true", help="push the commit to the wiki")
    parser.add_argument("--wiki-url", default=WIKI_URL, help="where to clone the wiki from")
    parser.add_argument("--repository", default=REPOSITORY_URL, help="the repository's web address")
    parser.add_argument("--branch", default="main", help="the branch links to other files point at")
    args = parser.parse_args(argv)
    try:
        changed = sync(
            args.wiki, push=args.push, wiki_url=args.wiki_url, repository=args.repository, branch=args.branch
        )
    except SyncError as error:
        print(f"wiki_sync: {error}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or "").strip()
        print(
            f"wiki_sync: git failed: {' '.join(error.cmd[3:5])}{': ' + detail if detail else ''}",
            file=sys.stderr,
        )
        return 1
    for line in changed:
        print(line)
    print("Committed." if changed else "The wiki is already up to date.")
    if changed and not args.push:
        print(f"Not pushed. Review it in {args.wiki}, then run again with --push.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
