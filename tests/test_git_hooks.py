"""scripts/install-git-hooks.sh: the version bump chained onto the active pre-commit hook,
without editing a hooks folder the repository tracks (beads keeps its hooks in
.beads/hooks, where core.hooksPath points)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
needs_shell = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None or shutil.which("git") is None,
    reason="the installer is a bash script, run from Git Bash on Windows",
)


def _git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com"}
    env |= {"GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env
    ).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    """A repository laid out as this one: the version, the bump scripts and a tracked
    hooks folder whose pre-commit leaves a mark, which core.hooksPath names."""
    repo = tmp_path / "repo"
    (repo / "src" / "solidseas").mkdir(parents=True)
    (repo / "src" / "solidseas" / "__init__.py").write_text('__version__ = "1.2.3"\n', encoding="utf-8")
    (repo / "scripts" / "git-hooks").mkdir(parents=True)
    for rel in (
        "scripts/install-git-hooks.sh",
        "scripts/bump-version.sh",
        "scripts/git-hooks/pre-commit-version",
    ):
        shutil.copy2(ROOT / rel, repo / rel)
    hooks = repo / ".beads" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "pre-commit").write_text('#!/bin/sh\ntouch "$(git rev-parse --git-dir)/tracked-ran"\n')
    (hooks / "pre-push").write_text("#!/bin/sh\nexit 0\n")
    for hook in hooks.iterdir():
        hook.chmod(0o755)
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "Start")
    _git(repo, "config", "core.hooksPath", ".beads/hooks")
    return repo


def _install(repo: Path) -> str:
    return subprocess.run(
        ["bash", str(repo / "scripts" / "install-git-hooks.sh")], check=True, capture_output=True, text=True
    ).stdout


@needs_shell
def test_a_tracked_hooks_folder_is_wrapped_never_edited(tmp_path):
    repo = _repo(tmp_path)
    tracked = {p.name: p.read_bytes() for p in (repo / ".beads" / "hooks").iterdir()}
    _install(repo)
    assert {p.name: p.read_bytes() for p in (repo / ".beads" / "hooks").iterdir()} == tracked
    assert _git(repo, "status", "--porcelain") == ""  # nothing tracked changed
    own = Path(_git(repo, "config", "--get", "core.hooksPath"))
    assert own.name == "solidseas-hooks" and own.parent == (repo / ".git").resolve()
    assert sorted(p.name for p in own.iterdir()) == ["pre-commit", "pre-push"]
    # a commit runs the tracked hook, then bumps the version
    (repo / "a.txt").write_text("a\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "Add a")
    assert (repo / ".git" / "tracked-ran").exists()
    assert _git(repo, "show", "HEAD:src/solidseas/__init__.py") == '__version__ = "1.2.4"'
    # run again after the tracked folder gains a hook: the wrappers follow, nothing tracked moves
    (repo / ".beads" / "hooks" / "post-merge").write_text("#!/bin/sh\nexit 0\n")
    _git(repo, "add", ".beads/hooks/post-merge")
    _git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "Add a hook")
    _install(repo)
    assert sorted(p.name for p in own.iterdir()) == ["post-merge", "pre-commit", "pre-push"]
    assert (own / "pre-commit").read_text().count("BEGIN SOLIDSEAS VERSION BUMP") == 1
    assert _git(repo, "status", "--porcelain") == ""
