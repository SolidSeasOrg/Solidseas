"""The project's own text holds no control characters but tabs and line ends.

A scripted rename once wrote ``"\\1"``, an octal escape, where it meant a regular
expression's group, and fourteen skill names in the docs and docstrings became a 0x01
character. Nothing showed it: Markdown renders the character as nothing and a docstring
keeps it. This finds any such character in the docs, the code, the tests, the scripts and
the research tools. Third-party license texts are left out (the LGPL's own text has form
feeds between its pages), and so are the fixtures.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def own_text_files() -> list[Path]:
    files = [*ROOT.glob("*.md"), *(ROOT / "docs").rglob("*.md")]
    for folder, patterns in (
        ("src", ("*.py", "*.md")),
        ("research", ("*.py", "*.md")),
        ("scripts", ("*.py", "*.ps1", "*.md")),
    ):
        for pattern in patterns:
            files += (ROOT / folder).rglob(pattern)
    files += (ROOT / "tests").glob("*.py")
    return sorted(set(files))


def test_the_projects_own_text_holds_no_control_characters():
    files = own_text_files()
    assert any(p.name == "ASSISTANT.md" for p in files) and any(p.suffix == ".py" for p in files)
    found = []
    for path in files:
        # split on line feeds only: str.splitlines would take a form feed or a vertical tab
        # for a line end and hide it
        for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
            if CONTROL.search(line):
                found.append(f"{path.relative_to(ROOT).as_posix()}:{number}")
    assert found == []


def test_the_search_sees_what_the_rename_left():
    assert CONTROL.search("It follows the `\x01` pattern:")
    assert CONTROL.search("page\x0cbreak") and CONTROL.search("\x7f")
    assert not CONTROL.search("a\ttab and a line end\r")
