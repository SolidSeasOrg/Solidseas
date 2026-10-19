"""The trademark notice (``solidseas.trademarks``) where people read it, and SolidSeas' own
names kept free of other companies' trademarks."""

import re
import tomllib
from pathlib import Path

import pytest

from solidseas import cli
from solidseas.trademarks import DISCLAIMER, INDEPENDENT

ROOT = Path(__file__).resolve().parents[1]
# Marks of other companies that no SolidSeas id, package or tool name may be made of.
MARKS = re.compile(r"solidworks|sldworks|parasolid|edrawings|3dexperience|dassault|siemens", re.I)


def _flat(text: str) -> str:
    """Text with Markdown quote marks and line breaks folded into single spaces."""
    return " ".join(line.lstrip("> ").strip() for line in text.splitlines()).replace("  ", " ")


@pytest.mark.parametrize("name", ["README.md", "NOTICE"])
def test_the_readme_and_notice_carry_the_notice_word_for_word(name):
    assert DISCLAIMER in _flat((ROOT / name).read_text(encoding="utf-8"))


def test_the_readme_has_it_near_the_top():
    head = (ROOT / "README.md").read_text(encoding="utf-8").split("\n## ", 1)[0]
    assert INDEPENDENT in _flat(head)


def test_the_parasolid_mark_is_credited_to_its_own_owner():
    assert "Parasolid is a trademark or registered trademark of Siemens Industry Software Inc." in DISCLAIMER
    assert "SOLIDWORKS, eDrawings, 3DEXPERIENCE and ACIS are trademarks" in DISCLAIMER


def test_the_command_line_help_ends_with_it(capsys):
    assert cli.main(["--help"]) == 0
    assert DISCLAIMER in " ".join(capsys.readouterr().out.split())
    assert cli.main(["--version"]) == 0  # still one line, as scripts read it
    assert capsys.readouterr().out.count("\n") == 1


def test_the_package_description_says_it_is_independent():
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert "not affiliated with or endorsed by Dassault Systèmes" in meta["description"]
    assert not MARKS.search(meta["name"])
    assert not any(MARKS.search(s) for s in meta.get("scripts", {}))


def test_no_extension_id_or_chat_tool_name_is_made_of_a_trademark():
    from solidseas_app import extensions as X
    from solidseas_app.assistant import mcp_server

    assert not [i for i in X.CATALOG if MARKS.search(i)]
    assert not [m.name for m in X.CATALOG.values() if MARKS.search(m.name)]
    assert not [n for n in mcp_server.TOOL_NAMES if MARKS.search(n)]
    # their former names still work (tests/test_extensions.py, tests/test_assistant_mcp.py)
    assert X.current_id("solidworks") == X.BRIDGE
    assert mcp_server.RENAMED_TOOLS == {"solidworks_sessions": "cad_sessions"}


def test_the_viewer_parts_carry_it(monkeypatch):
    pytest.importorskip("PySide6")
    from solidseas_app.viewer import app, window

    assert app.build_parser().epilog == DISCLAIMER
    shown = []
    monkeypatch.setattr(window.QMessageBox, "about", lambda parent, title, text: shown.append(text))
    window.MainWindow.about(None)
    assert len(shown) == 1 and DISCLAIMER in shown[0]
