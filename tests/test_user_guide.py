"""The README and the user guide (``docs/guide``): every relative link reaches a file, every
anchor a heading, and the text keeps to the house style."""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "guide"
PAGES = sorted(GUIDE.glob("*.md"))
DOCUMENTS = [ROOT / "README.md", *PAGES]


def _load():
    spec = importlib.util.spec_from_file_location("wiki_sync", ROOT / "scripts" / "wiki_sync.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["wiki_sync"] = module
    spec.loader.exec_module(module)
    return module


wiki_sync = _load()


def anchors(path: Path) -> set[str]:
    """The anchors GitHub gives the headings of the Markdown file ``path``."""
    found: set[str] = set()
    fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
            continue
        m = None if fence else re.match(r"#{1,6}\s+(.*?)\s*#*\s*$", line)
        if not m:
            continue
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", m.group(1)).replace("`", "")
        slug = re.sub(r"[^\w\- ]", "", text.lower()).replace(" ", "-")
        anchor, n = slug, 1
        while anchor in found:
            anchor, n = f"{slug}-{n}", n + 1
        found.add(anchor)
    return found


def test_the_guide_has_its_pages():
    names = {p.name for p in PAGES}
    assert {"index.md", "installing.md", "viewer.md", "formats.md", "building.md"} <= names


@pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_relative_link_reaches_a_file_and_its_anchor(document):
    broken = []
    for link in wiki_sync.links(document.read_text(encoding="utf-8")):
        if wiki_sync.SCHEME.match(link.target):
            continue
        path, _, anchor = link.target.partition("#")
        target = (document.parent / path).resolve() if path else document
        if not target.exists():
            broken.append(f"{link.line}: {link.target} (no such file)")
        elif anchor and target.suffix == ".md" and anchor not in anchors(target):
            broken.append(f"{link.line}: {link.target} (no such heading)")
    assert not broken, broken


def test_the_readme_links_work_on_a_package_index():
    """The README is the package's long description, shown on a package index where a
    relative link leads nowhere: it links into the repository by full URL, and each of
    those reaches a file and its anchor here."""
    blob = wiki_sync.REPOSITORY_URL + "/blob/main/"
    broken = []
    for link in wiki_sync.links((ROOT / "README.md").read_text(encoding="utf-8")):
        if not wiki_sync.SCHEME.match(link.target):
            broken.append(f"{link.line}: {link.target} (relative)")
        elif link.target.startswith(blob):
            path, _, anchor = link.target.removeprefix(blob).partition("#")
            target = ROOT / path
            if not target.is_file():
                broken.append(f"{link.line}: {link.target} (no such file)")
            elif anchor and target.suffix == ".md" and anchor not in anchors(target):
                broken.append(f"{link.line}: {link.target} (no such heading)")
    assert not broken, broken


@pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_the_text_keeps_to_the_house_style(document):
    text = document.read_text(encoding="utf-8")
    assert chr(0x2014) not in text and chr(0x2013) not in text  # em and en dashes
    assert not re.search(r"\b(delve|robust|seamless(ly)?)\b", text, re.I)


def test_every_guide_page_is_in_the_index():
    linked = {
        wiki_sync.resolve(link.target, "docs/guide/index.md")[0]
        for link in wiki_sync.links((GUIDE / "index.md").read_text(encoding="utf-8"))
        if not wiki_sync.is_external(link.target)
    }
    missing = [p.name for p in PAGES if p.name != "index.md" and f"docs/guide/{p.name}" not in linked]
    assert not missing, missing


def test_the_readme_stays_short_and_points_at_the_guide():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 165
    assert "docs/guide/index.md" in text and "https://solidseas.app" in text
    assert "https://solidseas.app/download/windows" in text
    assert "THIRD_PARTY_NOTICES.txt" in text
