"""``scripts/wiki_sync.py``: the user guide copied into a wiki checkout, its links rewritten for
the wiki's flat page names (``docs/guide/building.md``, Publishing this guide to the wiki)."""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/SolidSeasOrg/Solidseas"


def _load():
    spec = importlib.util.spec_from_file_location("wiki_sync", ROOT / "scripts" / "wiki_sync.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["wiki_sync"] = module
    spec.loader.exec_module(module)
    return module


W = _load()
PAGES = {"docs/guide/index.md", "docs/guide/3d-print.md", "docs/guide/where-used-and-bom.md"}


def _rewrite(text, page="docs/guide/index.md"):
    return W.rewrite(text, page, PAGES, REPOSITORY, "main", ROOT)


@pytest.mark.parametrize(
    "stem, name",
    [
        ("index", "Home"),
        ("installing", "Installing"),
        ("3d-print", "3D-Print"),
        ("where-used-and-bom", "Where-Used-and-BOM"),
        ("command-line", "Command-Line"),
        ("python-library", "Python-Library"),
    ],
)
def test_page_names(stem, name):
    assert W.wiki_name(stem) == name


def test_links_between_guide_pages_go_to_their_wiki_names_with_their_anchors():
    text = "See [Print](3d-print.md), [where](where-used-and-bom.md#where-used) and [home](index.md)."
    assert _rewrite(text) == "See [Print](3D-Print), [where](Where-Used-and-BOM#where-used) and [home](Home)."


def test_links_to_other_files_go_to_the_repository():
    text = (
        "[API](../API.md#9-stability) [notes](../../THIRD_PARTY_NOTICES.txt) "
        "[pages](../drawings) ![logo](../x.png)"
    )
    assert _rewrite(text) == (
        f"[API]({REPOSITORY}/blob/main/docs/API.md#9-stability) "
        f"[notes]({REPOSITORY}/blob/main/THIRD_PARTY_NOTICES.txt) "
        f"[pages]({REPOSITORY}/tree/main/docs/drawings) "
        f"![logo]({REPOSITORY}/blob/main/docs/x.png)"
    )


def test_urls_anchors_titles_and_code_stay_as_they_are():
    text = "\n".join(
        [
            "[site](https://solidseas.app) [mail](mailto:a@example.com) [here](#the-preview)",
            '[t](3d-print.md "The title")',
            "`[code](3d-print.md)` and [after](3d-print.md)",
            "```",
            "[fenced](3d-print.md)",
            "```",
            "[ref]: ../API.md",
        ]
    )
    assert _rewrite(text).split("\n") == [
        "[site](https://solidseas.app) [mail](mailto:a@example.com) [here](#the-preview)",
        '[t](3D-Print "The title")',
        "`[code](3d-print.md)` and [after](3D-Print)",
        "```",
        "[fenced](3d-print.md)",
        "```",
        f"[ref]: {REPOSITORY}/blob/main/docs/API.md",
    ]


def test_a_link_out_of_the_repository_stops_the_run():
    with pytest.raises(W.SyncError, match="leaves the repository"):
        _rewrite("[x](../../../elsewhere.md)")


def test_the_sidebar_lists_the_index_links_in_order_once():
    index = (
        "# Guide\n\n- [Print](3d-print.md)\n- [Where](where-used-and-bom.md#bom)\n- [Again](3d-print.md)\n"
    )
    index += "[API](../API.md) [site](https://solidseas.app)\n"
    assert (
        W.sidebar(index, PAGES) == "**[Home](Home)**\n\n- [Print](3D-Print)\n- [Where](Where-Used-and-BOM)\n"
    )


def test_the_real_guide_builds_with_every_page_marked():
    files = W.build(ROOT)
    assert "Home.md" in files and "_Sidebar.md" in files and "Building.md" in files
    assert all(W.MARKER_RE.match(text.split("\n", 1)[0]) for text in files.values())
    # no link on the wiki is left pointing at a guide file by its Markdown name
    for name, text in files.items():
        for link in W.links(text):
            assert not (link.target.endswith(".md") and not W.is_external(link.target)), (name, link)


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def identity(monkeypatch):
    for key in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{key}_NAME", "Tester")
        monkeypatch.setenv(f"GIT_{key}_EMAIL", "tester@example.com")


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_a_sync_commits_once_keeps_hand_made_pages_and_removes_stale_ones(tmp_path, identity):
    source = tmp_path / "source"
    (source / "docs" / "guide").mkdir(parents=True)
    (source / "docs" / "API.md").write_text("# API\n", encoding="utf-8")
    (source / "docs" / "guide" / "index.md").write_text("# Guide\n\n- [Old](old-page.md)\n", encoding="utf-8")
    (source / "docs" / "guide" / "old-page.md").write_text("# Old\n\n[API](../API.md)\n", encoding="utf-8")
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    _git(wiki, "init", "--quiet")
    (wiki / "Hand-Made.md").write_text("Written on the wiki.\n", encoding="utf-8")
    _git(wiki, "add", ".")
    _git(wiki, "commit", "--quiet", "-m", "First page")

    changed = W.sync(wiki, source, repository=REPOSITORY)
    assert "wrote Old-Page.md" in changed and "wrote Home.md" in changed
    assert f"]({REPOSITORY}/blob/main/docs/API.md)" in (wiki / "Old-Page.md").read_text(encoding="utf-8")
    assert "- [Old](Old-Page)" in (wiki / "_Sidebar.md").read_text(encoding="utf-8")
    count = _git(wiki, "rev-list", "--count", "HEAD").strip()
    assert count == "2"

    assert W.sync(wiki, source, repository=REPOSITORY) == []
    assert _git(wiki, "rev-list", "--count", "HEAD").strip() == "2"

    (source / "docs" / "guide" / "old-page.md").rename(source / "docs" / "guide" / "new-page.md")
    (source / "docs" / "guide" / "index.md").write_text("# Guide\n\n- [New](new-page.md)\n", encoding="utf-8")
    changed = W.sync(wiki, source, repository=REPOSITORY)
    assert "removed Old-Page.md" in changed and not (wiki / "Old-Page.md").exists()
    assert (wiki / "New-Page.md").is_file() and (wiki / "Hand-Made.md").is_file()
    assert _git(wiki, "status", "--porcelain") == ""


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_a_checkout_with_uncommitted_changes_is_refused(tmp_path, identity):
    source = tmp_path / "source"
    (source / "docs" / "guide").mkdir(parents=True)
    (source / "docs" / "guide" / "index.md").write_text("# Guide\n", encoding="utf-8")
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    _git(wiki, "init", "--quiet")
    (wiki / "Draft.md").write_text("Not committed.\n", encoding="utf-8")
    with pytest.raises(W.SyncError, match="uncommitted"):
        W.sync(wiki, source)
