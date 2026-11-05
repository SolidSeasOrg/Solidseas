"""The Git side of solidseas.versions: a file's history read from the repository's own
files, checked against ``git log`` on repositories git makes (loose and packed objects,
merges, renames, worktrees, SHA-256, shallow and partial clones, Git LFS), and the
reader's refusals. A repository written by hand runs the core without git installed."""

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

from solidseas import model, versions
from solidseas.errors import (
    FormatNotSupportedError,
    LinkRefusedError,
    PathRefusedError,
    VersionNotFoundError,
    VersionUnavailableError,
)
from solidseas.versions import gitrepo

GIT = shutil.which("git")
needs_git = pytest.mark.skipif(GIT is None, reason="git is not installed")
POSIX = os.name != "nt"


def _git_version() -> tuple[int, ...]:
    """The installed git's version, ``(2, 28, 0)`` from "git version 2.28.0.windows.1";
    () when there is no git or it says something else."""
    if GIT is None:
        return ()
    out = subprocess.run([GIT, "--version"], capture_output=True, text=True, timeout=30).stdout
    words = out.split()
    numbers = words[2].split(".")[:3] if len(words) > 2 else []
    return tuple(int(n) for n in numbers if n.isdigit())


GIT_VERSION = _git_version()
# git init --object-format=sha256 came with 2.29; 2.29 also does a partial clone's lazy
# fetches in a subprocess, where 2.28's in-process fetch during checkout reads a bad pack
# header and leaves the clone checked out without its files.
needs_git_2_29 = pytest.mark.skipif(
    GIT_VERSION < (2, 29), reason=f"needs git 2.29 or later (installed: {'.'.join(map(str, GIT_VERSION))})"
)


class Repo:
    """A repository the test makes with the git command line, with no configuration of
    the account's and fixed dates, so the order of commits is known."""

    def __init__(self, root: Path, home: Path, *args: str) -> None:
        self.root = root
        empty = home / "gitconfig"
        empty.write_text("", encoding="utf-8")
        self.env = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(empty),
            "HOME": str(home),
            "GIT_AUTHOR_NAME": "Test Author",
            "GIT_AUTHOR_EMAIL": "author@example.invalid",
            "GIT_COMMITTER_NAME": "Test Committer",
            "GIT_COMMITTER_EMAIL": "committer@example.invalid",
            "GIT_TERMINAL_PROMPT": "0",
        }
        self.day = 0
        root.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q", "-b", "main", *args)
        self.git("config", "core.autocrlf", "false")

    def git(self, *args: str, cwd: Path | None = None) -> str:
        done = subprocess.run(
            [GIT, *args], cwd=cwd or self.root, env=self.env, capture_output=True, text=True, timeout=120
        )
        assert done.returncode == 0, done.stderr
        return done.stdout

    def write(self, rel: str, data: bytes) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            p.chmod(0o644)
        p.write_bytes(data)
        return p

    def commit(self, message: str) -> str:
        self.day += 1
        when = f"2026-09-{self.day:02d}T10:00:00Z"
        env = {**self.env, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
        subprocess.run([GIT, "add", "-A"], cwd=self.root, env=env, check=True, capture_output=True)
        subprocess.run(
            [GIT, "commit", "-q", "--allow-empty", "-m", message],
            cwd=self.root,
            env=env,
            check=True,
            capture_output=True,
        )
        return self.git("rev-parse", "HEAD").strip()

    def log(self, rel: str) -> list[str]:
        return self.git("log", "--format=%H", "--", rel).split()

    def blob(self, oid: str) -> bytes:
        done = subprocess.run(
            [GIT, "cat-file", "blob", oid], cwd=self.root, env=self.env, capture_output=True, timeout=120
        )
        assert done.returncode == 0, done.stderr
        return done.stdout


def content(n: int, size: int = 40_000) -> bytes:
    """Binary content like a CAD file's: NUL bytes, so git never treats it as text."""
    block = bytes(range(256)) * (size // 256)
    return block + bytes([n % 256]) * 997 + f"version {n}".encode()


def commit_ids(data: dict) -> list[str]:
    return [v["id"] for v in data["versions"] if v["kind"] == "commit"]


@pytest.fixture
def make_repo(tmp_path):
    made = []

    def make(name: str = "repo", *args: str) -> Repo:
        home = tmp_path / f"{name}-home"
        home.mkdir(exist_ok=True)
        r = Repo(tmp_path / name, home, *args)
        made.append(r)
        return r

    return make


# --------------------------------------------------------------------------- against git log
@needs_git
def test_history_is_git_logs_for_the_file_loose_and_packed(make_repo):
    r = make_repo()
    for i in range(6):
        r.write("parts/bracket.bin", content(i))
        r.write("notes.txt", f"{i}\n".encode())
        r.commit(f"step {i}")
        if i == 2:
            r.git("gc", "-q")  # the first three versions in a pack, the rest loose
        if i == 4:
            r.write("notes.txt", b"unrelated\n")
            r.commit("unrelated")
    path = r.root / "parts" / "bracket.bin"
    data = versions.history(path)
    assert data["source"] == "git" and commit_ids(data) == r.log("parts/bracket.bin")
    assert [v["number"] for v in data["versions"]] == [6, 5, 4, 3, 2, 1]
    assert [v["status"] for v in data["versions"]] == ["modified"] * 5 + ["added"]
    assert data["versions"][0]["subject"] == "step 5" and data["versions"][0]["author"] == "Test Author"
    assert data["versions"][0]["time_utc"] == "2026-09-07T10:00:00Z"
    assert data["working"]["state"] == "unchanged" and data["git"]["branch"] == "main"
    assert data["git"]["path"] == "parts/bracket.bin" and data["git"]["object_format"] == "sha1"
    assert model.dumps(model.envelope("file_history", data))  # strict JSON
    for v in data["versions"]:
        blob = r.git("rev-parse", f"{v['id']}:parts/bracket.bin").strip()
        assert v["git_blob"] == blob and v["available"]
        assert versions.read_version(path, v["id"][:10]) == r.blob(blob)


@needs_git
def test_every_version_reads_back_byte_for_byte_after_an_aggressive_repack(make_repo):
    r = make_repo()
    sizes = []
    for i in range(8):
        data = content(i, 30_000 + 1000 * i)
        sizes.append(len(data))
        r.write("bracket.bin", data)
        r.commit(f"v{i}")
    r.git("gc", "-q", "--aggressive")  # deltas, chains of them
    path = r.root / "bracket.bin"
    with versions.timeline(path, hashes=True) as t:
        assert len(t.stored) == 8
        for v in t.stored:
            got = t.read(v)
            n = int(v.subject[1:])
            assert got == content(n, 30_000 + 1000 * n)
            assert v.size == len(got) and v.sha256 == hashlib.sha256(got).hexdigest()
    pack = list((r.root / ".git" / "objects" / "pack").glob("*.pack"))
    assert pack, "gc wrote no pack"


@needs_git
def test_merges_follow_gits_default_simplification(make_repo):
    r = make_repo()
    r.write("a.bin", content(1))
    r.commit("add")
    r.git("checkout", "-q", "-b", "side")
    r.write("a.bin", content(2))
    r.commit("side change")
    r.git("checkout", "-q", "main")
    r.write("b.txt", b"other\n")
    r.commit("main: other file")
    r.write("a.bin", content(3))
    r.commit("main change")
    # a merge that keeps main's version: TREESAME to its first parent, the side branch hidden
    r.git("merge", "-q", "-s", "ours", "side", "-m", "merge keeping main")
    data = versions.history(r.root / "a.bin")
    assert commit_ids(data) == r.log("a.bin") and len(commit_ids(data)) == 2
    # a merge that makes a third version: listed, and both sides followed
    r.git("checkout", "-q", "-b", "side2", "HEAD~1")
    r.write("a.bin", content(4))
    r.commit("side2 change")
    r.git("checkout", "-q", "main")
    r.git("merge", "-q", "--no-commit", "-s", "ours", "side2")
    r.write("a.bin", content(5))
    r.commit("evil merge")
    data = versions.history(r.root / "a.bin")
    assert commit_ids(data) == r.log("a.bin")
    assert data["versions"][0]["subject"] == "evil merge" and len(commit_ids(data)) == 4


@needs_git
def test_a_deleted_and_added_again_file_and_a_rename(make_repo):
    r = make_repo()
    r.write("a.bin", content(1))
    r.commit("add")
    (r.root / "a.bin").unlink()
    r.commit("delete")
    r.write("a.bin", content(2))
    r.commit("again")
    data = versions.history(r.root / "a.bin")
    assert commit_ids(data) == r.log("a.bin")
    assert [v["status"] for v in data["versions"]] == ["added", "deleted", "added"]
    assert data["versions"][1]["available"] is False
    with pytest.raises(VersionUnavailableError) as err:
        versions.read_version(r.root / "a.bin", "v2")
    assert err.value.detail["rule"] == "deleted"
    # the newest two versions with content are compared, never the deletion
    with versions.timeline(r.root / "a.bin") as t:
        a, b = t.pair(None, None)
        assert (a.number, b.number) == (1, 3)
    r.git("mv", "a.bin", "b.bin")
    r.commit("rename")
    data = versions.history(r.root / "b.bin")  # not followed past the rename, as git log is not
    assert commit_ids(data) == r.log("b.bin") and data["versions"][0]["status"] == "added"
    old = versions.history(r.root / "a.bin")  # the old name: its history ends with the rename
    assert old["working"]["state"] == "missing" and old["versions"][0]["status"] == "deleted"


@needs_git
def test_the_working_copy_states(make_repo):
    r = make_repo()
    path = r.write("x.bin", content(1))
    r.commit("one")
    assert versions.history(path)["working"]["state"] == "unchanged"
    path.write_bytes(content(2))
    data = versions.history(path)
    top = data["versions"][0]
    assert data["working"]["state"] == "changed" and top["kind"] == "working" and top["number"] == 2
    assert top["sha256"] == hashlib.sha256(content(2)).hexdigest() == data["working"]["sha256"]
    assert versions.read_version(path, "working") == content(2)
    assert versions.read_version(path, "latest") == content(1)
    path.unlink()
    data = versions.history(path)
    assert data["working"]["state"] == "missing" and [v["kind"] for v in data["versions"]] == ["commit"]
    with pytest.raises(VersionNotFoundError):
        versions.read_version(path, "working")
    new = r.write("untracked.bin", content(3))
    data = versions.history(new)
    assert data["source"] == "git" and data["working"]["state"] == "new"
    assert [v["kind"] for v in data["versions"]] == ["working"]
    with pytest.raises(FileNotFoundError):
        versions.history(r.root / "nothing.bin")


@needs_git
def test_versions_are_named_by_number_id_prefix_working_and_latest(make_repo):
    r = make_repo()
    path = r.write("x.bin", content(1))
    first = r.commit("one")
    path.write_bytes(content(2))
    r.commit("two")
    path.write_bytes(content(3))
    with versions.timeline(path) as t:
        assert (
            t.find("v1").id == first
            and t.find(first[:7]).id == first
            and t.find(first.upper()[:8]).id == first
        )
        assert t.find("working").kind == "working" and t.find("latest").number == 2
        for bad in ("v9", "v0", "nope", "abc", "-1", "v01"):
            with pytest.raises(VersionNotFoundError):
                t.find(bad)
        a, b = t.pair(None, None)
        assert (a.number, b.number) == (2, 3)
        a, b = t.pair("v1", None)
        assert (a.number, b.number) == (1, 3)
        a, b = t.pair(None, "v2")
        assert (a.number, b.number) == (1, 2)


@needs_git
def test_a_detached_head_packed_refs_and_a_branch_with_a_slash(make_repo):
    r = make_repo()
    path = r.write("x.bin", content(1))
    r.commit("one")
    r.git("checkout", "-q", "-b", "feature/long-name")
    path.write_bytes(content(2))
    r.commit("two")
    r.git("pack-refs", "--all", "--prune")
    assert not (r.root / ".git" / "refs" / "heads" / "feature").exists()
    data = versions.history(path)
    assert data["git"]["branch"] == "feature/long-name" and len(commit_ids(data)) == 2
    r.git("checkout", "-q", "--detach", "HEAD~1")
    data = versions.history(path)
    assert data["git"]["branch"] is None and commit_ids(data) == r.log("x.bin")


@needs_git
def test_a_linked_worktree_and_a_separate_git_folder(make_repo, tmp_path):
    r = make_repo()
    r.write("x.bin", content(1))
    r.commit("one")
    r.git("worktree", "add", "-q", str(tmp_path / "wt"), "-b", "other")
    wt = tmp_path / "wt"
    (wt / "x.bin").write_bytes(content(2))
    r.git("add", "-A", cwd=wt)
    r.git("commit", "-q", "-m", "in the worktree", cwd=wt)
    assert (wt / ".git").is_file()
    data = versions.history(wt / "x.bin")
    assert data["git"]["work_tree"] == str(wt) and data["git"]["branch"] == "other"
    assert commit_ids(data) == r.git("log", "--format=%H", "--", "x.bin", cwd=wt).split()
    s = make_repo("separate", f"--separate-git-dir={tmp_path / 'separate.git'}")
    s.write("y.bin", content(3))
    s.commit("one")
    assert (s.root / ".git").is_file()
    assert commit_ids(versions.history(s.root / "y.bin")) == s.log("y.bin")


@needs_git
@needs_git_2_29
def test_a_sha256_repository(make_repo):
    r = make_repo("sha256", "--object-format=sha256")
    path = r.write("x.bin", content(1))
    r.commit("one")
    path.write_bytes(content(2))
    r.commit("two")
    r.git("gc", "-q")
    data = versions.history(path)
    assert data["git"]["object_format"] == "sha256" and commit_ids(data) == r.log("x.bin")
    assert all(len(v["id"]) == 64 for v in data["versions"])
    assert versions.read_version(path, "v1") == content(1)
    assert data["working"]["state"] == "unchanged"


@needs_git
def test_a_shallow_clone_says_its_history_is_incomplete(make_repo, tmp_path):
    r = make_repo()
    for i in range(4):
        r.write("x.bin", content(i))
        r.commit(f"v{i}")
    clone = tmp_path / "shallow"
    r.git("clone", "-q", "--depth", "2", r.root.as_uri(), str(clone))
    data = versions.history(clone / "x.bin")
    assert len(commit_ids(data)) == 2 and data["git"]["shallow"]
    assert [w["code"] for w in data["warnings"]] == ["history_incomplete"]
    assert data["versions"][-1]["status"] == "added"  # its parent is not in the clone


@needs_git
@needs_git_2_29
def test_a_partial_clone_lists_versions_whose_content_is_not_here(make_repo, tmp_path):
    r = make_repo()
    for i in range(3):
        r.write("x.bin", content(i))
        r.commit(f"v{i}")
    r.git("config", "uploadpack.allowFilter", "true")
    clone = tmp_path / "partial"
    r.git("clone", "-q", "--filter=blob:none", r.root.as_uri(), str(clone))
    data = versions.history(clone / "x.bin")
    assert data["git"]["partial"] and len(commit_ids(data)) == 3
    assert [v["available"] for v in data["versions"]] == [True, False, False]
    with pytest.raises(VersionUnavailableError) as err:
        versions.read_version(clone / "x.bin", "v1")
    assert err.value.detail["rule"] == "object_missing"
    assert versions.read_version(clone / "x.bin", "v3") == content(2)


@needs_git
def test_git_lfs_pointers_are_read_from_the_local_lfs_objects(make_repo):
    r = make_repo()
    real = [content(10), content(11)]
    for data in real:
        oid = hashlib.sha256(data).hexdigest()
        pointer = f"version https://git-lfs.github.com/spec/v1\noid sha256:{oid}\nsize {len(data)}\n".encode()
        r.write("big.bin", pointer)
        r.commit(f"lfs {oid[:8]}")
    # the first version's object was fetched, the second's was not
    first = hashlib.sha256(real[0]).hexdigest()
    store = r.root / ".git" / "lfs" / "objects" / first[:2] / first[2:4]
    store.mkdir(parents=True)
    (store / first).write_bytes(real[0])
    path = r.root / "big.bin"
    data = versions.history(path)
    v2, v1 = data["versions"]
    assert v1["lfs"] == {"oid": first, "size": len(real[0])} and v1["available"] and v1["sha256"] == first
    assert v2["available"] is False and v1["size"] == len(real[0])
    assert [w["code"] for w in data["warnings"]] == ["lfs_not_fetched"]
    assert data["working"]["state"] == "unchanged"  # the work tree holds the pointer: git-lfs is not here
    assert versions.read_version(path, "v1") == real[0]
    with pytest.raises(VersionUnavailableError) as err:
        versions.read_version(path, "v2")
    assert err.value.detail["rule"] == "lfs_object_missing"
    path.write_bytes(real[1])  # what git-lfs would have checked out
    assert versions.history(path)["working"]["state"] == "unchanged"
    (store / first).write_bytes(real[0][:-1] + b"X")  # the same size, other content
    with pytest.raises(gitrepo.GitObjectError):
        versions.read_version(path, "v1")


@needs_git
def test_nothing_the_repositorys_configuration_names_ever_runs(make_repo, tmp_path):
    """fsmonitor, hooks, a pager, signature checks, filters and textconv all name
    programs git would run for some command; SolidSeas runs none of them."""
    r = make_repo()
    marker = tmp_path / "ran"
    if POSIX:
        script = tmp_path / "evil.sh"
        script.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 0\n", encoding="utf-8")
        script.chmod(0o755)
        command = str(script)
    else:
        command = f"\"{sys.executable}\" -c \"open(r'{marker}', 'w')\""
    r.write("x.bin", content(1))
    r.write(".gitattributes", b"*.bin filter=evil diff=evil\n")
    r.commit("one")
    r.write("x.bin", content(2))
    r.commit("two")
    for key, value in (
        ("core.fsmonitor", command),
        ("core.pager", command),
        ("core.hooksPath", str(tmp_path)),
        ("log.showSignature", "true"),
        ("gpg.program", command),
        ("filter.evil.clean", command),
        ("filter.evil.smudge", command),
        ("filter.evil.process", command),
        ("diff.evil.textconv", command),
        ("diff.external", command),
        ("credential.helper", "!" + command),
        ("core.sshCommand", command),
    ):
        r.git("config", key, value)
    if POSIX:  # the control: git itself runs them for an everyday command (and then fails)
        subprocess.run(
            [GIT, "status", "--porcelain"], cwd=r.root, env=r.env, capture_output=True, timeout=120
        )
        assert marker.exists()
        marker.unlink()
    path = r.root / "x.bin"
    path.write_bytes(content(3))
    data = versions.history(path)
    assert len(commit_ids(data)) == 2 and data["working"]["state"] == "changed"
    assert versions.read_version(path, "v1") == content(1)
    assert not marker.exists()


# --------------------------------------------------------------------------- refusals
@needs_git
def test_reftable_and_unknown_extensions_are_refused(make_repo):
    r = make_repo()
    path = r.write("x.bin", content(1))
    r.commit("one")
    config = r.root / ".git" / "config"
    original = config.read_text(encoding="utf-8")
    config.write_text(original + "[extensions]\n\trefStorage = reftable\n", encoding="utf-8")
    r.git("config", "core.repositoryformatversion", "1")
    with pytest.raises(FormatNotSupportedError) as err:
        versions.history(path)
    assert err.value.detail["rule"] == "reftable"
    assert model.error_info(err.value)["message"] == model.RULE_MESSAGES[("format_not_supported", "reftable")]
    config.write_text(
        original.replace("repositoryformatversion = 0", "repositoryformatversion = 1")
        + "[extensions]\n\tsomethingNew = yes\n",
        encoding="utf-8",
    )
    with pytest.raises(FormatNotSupportedError) as err:
        versions.history(path)
    assert err.value.detail["rule"] == "repository_extension"
    config.write_text(original + "[extensions]\n\tsomethingNew = yes\n", encoding="utf-8")
    assert len(commit_ids(versions.history(path))) == 1  # format 0 ignores extensions, as git does


@needs_git
def test_a_damaged_object_is_damaged_file(make_repo):
    r = make_repo()
    path = r.write("x.bin", content(1))
    head = r.commit("one")
    loose = r.root / ".git" / "objects" / head[:2] / head[2:]
    loose.chmod(0o644)
    loose.write_bytes(zlib.compress(b"commit 99999\0tree nonsense"))
    with pytest.raises(gitrepo.GitObjectError) as err:
        versions.history(path)
    assert model.error_info(err.value)["code"] == "damaged_file" and err.value.detail["rule"] == "git_object"
    loose.write_bytes(b"not zlib at all")
    with pytest.raises(gitrepo.GitObjectError):
        versions.history(path)


@needs_git
def test_a_head_naming_a_path_outside_the_references_is_refused(make_repo):
    r = make_repo()
    path = r.write("x.bin", content(1))
    r.commit("one")
    for target in ("refs/../../config", "refs/heads/../../../etc/passwd", "../config", "refs/heads/x\\..\\y"):
        (r.root / ".git" / "HEAD").write_text(f"ref: {target}\n", encoding="utf-8")
        with pytest.raises(gitrepo.GitObjectError):
            versions.history(path)


@needs_git
@pytest.mark.skipif(not POSIX, reason="symbolic links need a privilege on Windows")
def test_a_git_folder_that_is_a_link_is_never_followed(make_repo, tmp_path):
    r = make_repo()
    r.write("x.bin", content(1))
    r.commit("one")
    elsewhere = tmp_path / "work"
    elsewhere.mkdir()
    (elsewhere / ".git").symlink_to(r.root / ".git")
    shutil.copyfile(r.root / "x.bin", elsewhere / "x.bin")
    with pytest.raises(LinkRefusedError):
        versions.history(elsewhere / "x.bin")
    # a link inside the repository's folder is refused too
    objects = r.root / ".git" / "objects"
    moved = tmp_path / "objects-elsewhere"
    objects.rename(moved)
    objects.symlink_to(moved)
    with pytest.raises(LinkRefusedError):
        versions.history(r.root / "x.bin")


def test_source_git_outside_a_repository_is_an_argument_error(tmp_path):
    path = tmp_path / "x.bin"
    path.write_bytes(content(1))
    with pytest.raises(Exception) as err:
        versions.history(path, source="git")
    assert model.error_code(err.value) == "invalid_argument"
    data = versions.history(path)  # auto: the snapshots, of which there are none yet
    assert data["source"] == "snapshots" and data["working"]["state"] == "new"


# --------------------------------------------------------------------------- without git
def _loose(git_dir: Path, kind: str, body: bytes, hash_name: str = "sha1") -> str:
    raw = f"{kind} {len(body)}".encode() + b"\0" + body
    oid = hashlib.new(hash_name, raw).hexdigest()
    folder = git_dir / "objects" / oid[:2]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / oid[2:]).write_bytes(zlib.compress(raw))
    return oid


def _tree(git_dir: Path, entries: list[tuple[str, str, str]]) -> str:
    body = b"".join(
        mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(oid) for mode, name, oid in entries
    )
    return _loose(git_dir, "tree", body)


def _commit(git_dir: Path, tree: str, parents: list[str], when: int, message: str) -> str:
    lines = [f"tree {tree}", *[f"parent {p}" for p in parents]]
    lines += [
        f"author Hand Made <hand@example.invalid> {when} +0200",
        f"committer Hand Made <hand@example.invalid> {when} +0200",
    ]
    body = ("\n".join(lines) + "\n\n" + message + "\n").encode()
    return _loose(git_dir, "commit", body)


def test_a_repository_written_by_hand_needs_no_git(tmp_path):
    root = tmp_path / "hand"
    git_dir = root / ".git"
    (git_dir / "refs" / "heads").mkdir(parents=True)
    (git_dir / "objects").mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    parent: list[str] = []
    ids = []
    for i in range(3):
        blob = _loose(git_dir, "blob", content(i))
        sub = _tree(git_dir, [("100644", "part.bin", blob)])
        top = _tree(git_dir, [("40000", "сборка", sub)])  # a folder name that is not ASCII
        c = _commit(git_dir, top, parent, 1_790_000_000 + i * 86_400, f"version {i}\n\nmore words")
        ids.append(c)
        parent = [c]
    (git_dir / "refs" / "heads" / "main").write_text(ids[-1] + "\n", encoding="utf-8")
    path = root / "сборка" / "part.bin"
    path.parent.mkdir()
    path.write_bytes(content(2))
    data = versions.history(path)
    assert commit_ids(data) == ids[::-1] and data["working"]["state"] == "unchanged"
    assert data["versions"][0]["subject"] == "version 2" and data["versions"][0]["author"] == "Hand Made"
    assert data["versions"][-1]["time_utc"] == "2026-09-21T14:13:20Z"
    assert versions.read_version(path, "v1") == content(0)


# --------------------------------------------------------------------------- the pieces
def _delta(base: bytes, ops: bytes, out_size: int) -> bytes:
    def varint(n: int) -> bytes:
        out = bytearray()
        while True:
            b = n & 0x7F
            n >>= 7
            out.append(b | (0x80 if n else 0))
            if not n:
                return bytes(out)

    return varint(len(base)) + varint(out_size) + ops


def test_apply_delta_copies_and_inserts_and_refuses_what_does_not_fit():
    base = b"hello world"
    # copy 5 bytes from offset 0, insert "!!", copy 5 bytes from offset 6
    ops = bytes([0x80 | 0x10, 5]) + bytes([2]) + b"!!" + bytes([0x80 | 0x01 | 0x10, 6, 5])
    assert gitrepo.apply_delta(base, _delta(base, ops, 12), 100) == b"hello!!world"
    for bad in (
        _delta(base, bytes([0x80 | 0x01 | 0x10, 8, 5]), 5),  # copies past the end of the base
        _delta(base, bytes([0]), 0),  # a reserved instruction
        _delta(base, bytes([3]) + b"ab", 3),  # an insert cut short
        _delta(base, bytes([0x80 | 0x10, 5]), 6),  # makes less than it says
        _delta(b"other", bytes([0x80 | 0x10, 5]), 5),  # another base's size
    ):
        with pytest.raises(gitrepo.GitObjectError):
            gitrepo.apply_delta(base, bad, 100)
    with pytest.raises(Exception) as err:
        gitrepo.apply_delta(base, _delta(base, bytes([0x80 | 0x10, 5]), 5), 4)
    assert model.error_code(err.value) == "file_too_large"


@pytest.mark.parametrize(
    "target",
    [r"\??\UNC\host\share\repo.git", "/??/UNC/host/share/repo.git", r"\\?\UNC\host\share", r"\\.\pipe\x"],
)
def test_a_device_or_nt_prefix_in_a_git_file_is_refused_by_its_text(tmp_path, target):
    # Windows opens \??\UNC\host\share as the share, whatever abspath makes of the text
    with pytest.raises(PathRefusedError) as err:
        gitrepo._check_target(target, str(tmp_path), "the .git file")
    assert err.value.detail["rule"] == "device_path"


def test_lfs_pointers_config_and_commits_parse_as_git_writes_them():
    oid = "a" * 64
    ok = f"version https://git-lfs.github.com/spec/v1\noid sha256:{oid}\nsize 12345\n".encode()
    assert gitrepo.parse_lfs_pointer(ok) == gitrepo.LfsPointer(oid, 12345)
    for bad in (
        ok.replace(b"git-lfs", b"example"),
        ok.replace(b"sha256:", b"md5:"),
        ok + b" " * 2000,
        b"\0" * 10,
    ):
        assert gitrepo.parse_lfs_pointer(bad) is None
    cfg = gitrepo.parse_config(
        '[core]\n\trepositoryformatversion = 1 ; a comment\n\tbare\n[Extensions]\n\tobjectFormat = "sha256"\n'
        '[remote "origin"]\n\turl = x # another\n'
    )
    assert cfg == {
        "core.repositoryformatversion": "1",
        "core.bare": "true",
        "extensions.objectformat": "sha256",
        "remote.origin.url": "x",
    }
    tree = "b" * 40
    raw = (
        f"tree {tree}\nparent {'c' * 40}\nauthor Ünïcode Name <u@example.invalid> 1790000000 -0530\n"
        "committer Other <o@example.invalid> 1790000100 +0000\ngpgsig -----BEGIN PGP SIGNATURE-----\n"
        " line one\n -----END PGP SIGNATURE-----\n\n\nFirst line of the message\n\nbody\n"
    ).encode()
    c = gitrepo.parse_commit("d" * 40, raw, 20)
    assert (c.tree, c.parents, c.author, c.authored, c.authored_offset) == (
        tree,
        ("c" * 40,),
        "Ünïcode Name",
        1790000000,
        -330,
    )
    assert c.committed == 1790000100 and c.subject == "First line of the message"
    with pytest.raises(gitrepo.GitObjectError):
        gitrepo.parse_commit("d" * 40, b"tree short\n\nx", 20)


@pytest.mark.skipif(not POSIX, reason="file modes")
def test_reading_a_repository_changes_nothing_in_it(tmp_path):
    root = tmp_path / "hand"
    git_dir = root / ".git"
    (git_dir / "refs" / "heads").mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    blob = _loose(git_dir, "blob", content(1))
    c = _commit(git_dir, _tree(git_dir, [("100644", "p.bin", blob)]), [], 1_790_000_000, "one")
    (git_dir / "refs" / "heads" / "main").write_text(c + "\n", encoding="utf-8")
    (root / "p.bin").write_bytes(content(1))

    def snapshot():
        return {
            str(p): (
                p.stat().st_mtime_ns,
                stat.S_IMODE(p.stat().st_mode),
                p.read_bytes() if p.is_file() else None,
            )
            for p in sorted(root.rglob("*"))
        }

    before = snapshot()
    versions.history(root / "p.bin")
    versions.read_version(root / "p.bin", "v1")
    assert snapshot() == before
