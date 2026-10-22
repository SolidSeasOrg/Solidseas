"""The text bd (beads) writes into this repository keeps the house style: no em or en dash.

bd writes dashes into its block in AGENTS.md and CLAUDE.md, its section of each hook in
.beads/hooks and the text files it keeps in .beads, and writes them again whenever it
regenerates that text. ``scripts/undash-beads-text.py`` takes them out of bd's text only,
so these tests tell bd's text apart from the repository's own around it: a dash in bd's
text means bd rewrote it and the script has to run again, and a dash in the
repository's own text is a sentence to rewrite by hand.
"""

import hashlib
import importlib.util
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("undash_beads_text", ROOT / "scripts" / "undash-beads-text.py")
undash = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(undash)

EM = "\u2014"
DASHES = ("\u2013", "\u2014")

# bd 1.0.4's block for AGENTS.md and CLAUDE.md, as it writes it, dashes and all.
BD_BLOCK = (
    "<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:7510c1e2 -->\n"
    "## Beads Issue Tracker\n\n"
    "This project uses **bd (beads)** for issue tracking. "
    "Run `bd prime` to see full workflow context and commands.\n\n"
    "### Quick Reference\n\n"
    "```bash\n"
    "bd ready              # Find available work\n"
    "bd show <id>          # View issue details\n"
    "bd update <id> --claim  # Claim work\n"
    "bd close <id>         # Complete work\n"
    "```\n\n"
    "### Rules\n\n"
    f"- Use `bd` for ALL task tracking {EM} do NOT use TodoWrite, TaskCreate, or markdown TODO lists\n"
    "- Run `bd prime` for detailed command reference and session close protocol\n"
    f"- Use `bd remember` for persistent knowledge {EM} do NOT use MEMORY.md files\n\n"
    "**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git "
    "remote; `.beads/issues.jsonl` is a passive export. See "
    "https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.\n\n"
    "## Session Completion\n\n"
    "**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until "
    "`git push` succeeds.\n\n"
    "**MANDATORY WORKFLOW:**\n\n"
    "1. **File issues for remaining work** - Create issues for anything that needs follow-up\n"
    "2. **Run quality gates** (if code changed) - Tests, linters, builds\n"
    "3. **Update issue status** - Close finished work, update in-progress items\n"
    "4. **PUSH TO REMOTE** - This is MANDATORY:\n"
    "   ```bash\n"
    "   git pull --rebase\n"
    "   git push\n"
    '   git status  # MUST show "up to date with origin"\n'
    "   ```\n"
    "5. **Clean up** - Clear stashes, prune remote branches\n"
    "6. **Verify** - All changes committed AND pushed\n"
    "7. **Hand off** - Provide context for next session\n\n"
    "**CRITICAL RULES:**\n"
    "- Work is NOT complete until `git push` succeeds\n"
    "- NEVER stop before pushing - that leaves work stranded locally\n"
    '- NEVER say "ready to push when you are" - YOU must push\n'
    "- If push fails, resolve and retry until it succeeds\n"
    "<!-- END BEADS INTEGRATION -->\n"
)

# bd 1.0.4's pre-commit hook, as it writes it, with a section of the repository's own after it.
BD_HOOK = (
    "#!/usr/bin/env sh\n"
    "# --- BEGIN BEADS INTEGRATION v1.0.4 ---\n"
    "# This section is managed by beads. Do not remove these markers.\n"
    "if command -v bd >/dev/null 2>&1; then\n"
    "  export BD_GIT_HOOK=1\n"
    "  _bd_timeout=${BEADS_HOOK_TIMEOUT:-300}\n"
    "  if command -v timeout >/dev/null 2>&1; then\n"
    '    timeout "$_bd_timeout" bd hooks run pre-commit "$@"\n'
    "    _bd_exit=$?\n"
    "    if [ $_bd_exit -eq 124 ]; then\n"
    "      echo >&2 \"beads: hook 'pre-commit' timed out after ${_bd_timeout}s "
    f'{EM} continuing without beads"\n'
    "      _bd_exit=0\n"
    "    fi\n"
    "  else\n"
    '    bd hooks run pre-commit "$@"\n'
    "    _bd_exit=$?\n"
    "  fi\n"
    "  if [ $_bd_exit -eq 3 ]; then\n"
    f"    echo >&2 \"beads: database not initialized {EM} skipping hook 'pre-commit'\"\n"
    "    _bd_exit=0\n"
    "  fi\n"
    "  if [ $_bd_exit -ne 0 ]; then exit $_bd_exit; fi\n"
    "fi\n"
    "# --- END BEADS INTEGRATION v1.0.4 ---\n"
    "\n"
    "# --- BEGIN AN EXAMPLE OF THE REPOSITORY'S OWN ---\n"
    f"# Kept as it is {EM} this is not bd's text.\n"
    "# --- END AN EXAMPLE OF THE REPOSITORY'S OWN ---\n"
)
OWN_TEXT = f"# AGENTS.md\n\nThe repository's own words {EM} a person rewrites these.\n\n"


def _hits(root: Path) -> list[tuple[str, int, str]]:
    """(file, line, whose) for every em or en dash in the files bd writes text into."""
    hits = []
    for name in undash.files(root):
        text = (root / name).read_bytes().decode("utf-8")
        spans = undash.bd_spans(name, text)
        for i, ch in enumerate(text):
            if ch in DASHES:
                whose = "bd" if any(start <= i < end for start, end in spans) else "repository"
                hits.append((name, text.count("\n", 0, i) + 1, whose))
    return hits


def _tree(tmp_path: Path) -> Path:
    """A checkout's bd text as bd 1.0.4 writes it, with the repository's own text beside it."""
    root = tmp_path / "checkout"
    hooks = root / ".beads" / "hooks"
    hooks.mkdir(parents=True)
    (root / "AGENTS.md").write_bytes((OWN_TEXT + BD_BLOCK).encode("utf-8"))
    # A Windows checkout (core.autocrlf true) has CRLF line endings.
    claude = "Follow AGENTS.md.\n\n" + BD_BLOCK
    (root / "CLAUDE.md").write_bytes(claude.replace("\n", "\r\n").encode("utf-8"))
    gitignore = f"# Credential key (encryption key for federation peer auth {EM} never commit)\n"
    (root / ".beads" / ".gitignore").write_bytes((gitignore + ".beads-credential-key\n").encode("utf-8"))
    data = f'{{"title": "data, not bd\'s prose {EM} kept"}}\n'
    (root / ".beads" / "issues.jsonl").write_bytes(data.encode("utf-8"))
    for name in ("pre-commit", "pre-commit.old"):  # a copy that is not a hook stays as it is
        (hooks / name).write_bytes(BD_HOOK.encode("utf-8"))
        (hooks / name).chmod(0o755)
    return root


def test_the_text_bd_wrote_here_has_no_dash():
    advice = {
        "bd": "bd rewrote its text; run python scripts/undash-beads-text.py",
        "repository": "the repository's own text; rewrite the sentence by hand",
    }
    hits = _hits(ROOT)
    assert not hits, "\n".join(f"{name}:{line}: {advice[whose]}" for name, line, whose in hits)
    assert undash.main(["--check"]) == 0


def test_the_files_bd_writes_into_are_all_found():
    assert set(undash.files(ROOT)) >= {
        "AGENTS.md",
        "CLAUDE.md",
        ".beads/.gitignore",
        ".beads/hooks/pre-commit",
        ".beads/hooks/post-checkout",
    }
    for name in undash.BLOCK_FILES:
        text = (ROOT / name).read_text(encoding="utf-8")
        assert len(undash.bd_spans(name, text)) == 1, f"{name} has no single bd block"
    for name in undash.files(ROOT):
        if name.startswith(".beads/hooks/"):
            text = (ROOT / name).read_text(encoding="utf-8")
            assert len(undash.bd_spans(name, text)) == 1, f"{name} has no single bd section"


def test_the_markers_hash_names_the_template_bd_wrote():
    # bd's marker holds the first 8 hex digits of the SHA-256 of the block's text, which
    # bd reads to tell whether the block is out of date. The script keeps the marker.
    body = BD_BLOCK.split("-->\n", 1)[1].rsplit("<!-- END", 1)[0]
    assert hashlib.sha256(body.strip().encode("utf-8")).hexdigest()[:8] == "7510c1e2"
    fixed = undash.rewrite("AGENTS.md", BD_BLOCK)
    assert fixed.splitlines()[0] == BD_BLOCK.splitlines()[0]
    assert fixed.splitlines()[-1] == BD_BLOCK.splitlines()[-1]


def _changed_lines(before: str, after: str) -> list[tuple[str, str]]:
    assert len(before.splitlines()) == len(after.splitlines())
    return [(a, b) for a, b in zip(before.splitlines(), after.splitlines(), strict=True) if a != b]


def test_bd_text_is_rewritten_and_everything_else_left_alone(tmp_path):
    root = _tree(tmp_path)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    expected = ["AGENTS.md", "CLAUDE.md", ".beads/.gitignore", ".beads/hooks/pre-commit"]
    assert undash.pending(root) == expected
    assert undash.main(["--check", "--root", str(root)]) == 1
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before  # --check changes nothing

    assert undash.fix(root) == expected
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith(OWN_TEXT)  # the repository's own words keep their dash
    assert _changed_lines(OWN_TEXT + BD_BLOCK, agents) == [
        (
            f"- Use `bd` for ALL task tracking {EM} do NOT use TodoWrite, TaskCreate, or markdown TODO lists",
            "- Use `bd` for ALL task tracking; do NOT use TodoWrite, TaskCreate, or markdown TODO lists",
        ),
        (
            f"- Use `bd remember` for persistent knowledge {EM} do NOT use MEMORY.md files",
            "- Use `bd remember` for persistent knowledge; do NOT use MEMORY.md files",
        ),
    ]
    claude = (root / "CLAUDE.md").read_bytes()
    assert claude.count(b"\r\n") == BD_BLOCK.count("\n") + 2  # CRLF kept, and no bare LF added
    assert b"\n" not in claude.replace(b"\r\n", b"") and b"tracking; do NOT use" in claude
    gitignore = (root / ".beads" / ".gitignore").read_text(encoding="utf-8")
    assert gitignore.startswith("# Credential key (encryption key for federation peer auth; never commit)\n")
    hook = (root / ".beads" / "hooks" / "pre-commit").read_text(encoding="utf-8")
    changed = _changed_lines(BD_HOOK, hook)
    assert [b.strip() for _a, b in changed] == [
        "echo >&2 \"beads: hook 'pre-commit' timed out after ${_bd_timeout}s; continuing without beads\"",
        "echo >&2 \"beads: database not initialized; skipping hook 'pre-commit'\"",
    ]
    assert all(a.replace(f" {EM} ", "; ") == b for a, b in changed)
    assert f"# Kept as it is {EM} this is not bd's text." in hook  # outside bd's markers
    if os.name != "nt":
        assert stat.S_IMODE((root / ".beads" / "hooks" / "pre-commit").stat().st_mode) == 0o755
    for name in (".beads/hooks/pre-commit.old", ".beads/issues.jsonl"):
        assert (root / name).read_bytes() == before[root / name]

    # Only the repository's own dashes are left, and each is reported as the repository's.
    assert {(name, whose) for name, _line, whose in _hits(root)} == {
        ("AGENTS.md", "repository"),
        (".beads/hooks/pre-commit", "repository"),
    }
    assert undash.fix(root) == [] and undash.pending(root) == []
    assert undash.main(["--check", "--root", str(root)]) == 0


def test_a_dash_between_digits_becomes_a_hyphen():
    assert undash.undash(f"pages 3\u20135 {EM} then more\u2013and more") == "pages 3-5; then more; and more"
    assert undash.undash("no dash here") == "no dash here"


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
def test_the_hooks_still_parse_as_shell(tmp_path):
    hooks = {"sample": undash.rewrite(".beads/hooks/pre-commit", BD_HOOK)}
    for name in undash.files(ROOT):
        if name.startswith(".beads/hooks/"):
            hooks[name] = (ROOT / name).read_bytes().decode("utf-8")
    for i, (name, text) in enumerate(hooks.items()):
        copy = tmp_path / f"hook{i}"  # with LF endings: a Windows checkout gives the hooks CRLF
        copy.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))
        run = subprocess.run(["sh", "-n", str(copy)], capture_output=True, text=True)
        assert run.returncode == 0, f"{name}: {run.stderr}"
