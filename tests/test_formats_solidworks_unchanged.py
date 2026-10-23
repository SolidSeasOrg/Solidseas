"""SOLIDWORKS output did not change when model files joined (``docs/API.md`` 3.20 and 9).

Every SOLIDWORKS fixture goes through ``info``, ``export`` (STL and 3MF),
``preview`` and the fixtures folder through ``list``, once with this tree's ``src``
and once with the ``src`` of :data:`BASE`, the last commit before model files joined
this line of history (the tip of the STEP prints, whose export added
``export_result.step``), taken from git into a temporary folder. With the fields the
model-file work added removed (the listing's ``model`` and ``counts.unsupported``,
``export_result.source_format`` and ``file_written.source``, and ``export_result.check`` while
it is null), and a property's
``date`` (its calendar day, 0.2.122) with them, and the parts that
differ from run to run evened out (the package version, output folders, timings),
the JSON is identical. A 3MF names the package version too, so its size is left out
and its members are compared with the version evened out.

Skipped where this is not a git checkout holding :data:`BASE` (a shallow clone in CI).
When SOLIDWORKS output changes on purpose, :data:`BASE` moves to the commit that
changed it.
"""

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from support import FIXTURES

BASE = "61c5c9d004a94a6231d4d90f52fa584e2fce6152"
REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
_VERSION = re.compile(rb"SolidSeas [0-9][0-9.]*")
SCRIPT = r"""
import contextlib, io, json, os, sys
from solidseas import cli

fixtures, out = sys.argv[1], sys.argv[2]
results = {}


def run(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.main([*argv, "--json"])
    return [code, json.loads(buf.getvalue())]


names = sorted(n for n in os.listdir(fixtures) if n.lower().endswith((".sldprt", ".sldasm", ".slddrw")))
for i, n in enumerate(names):
    p = os.path.join(fixtures, n)
    results[f"info {i}"] = run("info", p)
    results[f"export stl {i}"] = run("export", p, "--format", "stl", "-o", os.path.join(out, f"{i}.stl"))
    results[f"export 3mf {i}"] = run("export", p, "--format", "3mf", "-o", os.path.join(out, f"{i}.3mf"))
    results[f"preview {i}"] = run("preview", p, "-o", os.path.join(out, f"{i}.png"))
results["list"] = run("list", fixtures, "--include", "properties,configurations", "--in-process")
with open(os.path.join(out, "results.json"), "w", encoding="utf-8") as fh:
    json.dump(results, fh)
"""


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, timeout=120)


@pytest.fixture(scope="module")
def base_src(tmp_path_factory) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    if _git("cat-file", "-e", f"{BASE}^{{commit}}").returncode != 0:
        pytest.skip("the base commit is not in this checkout (a shallow clone)")
    tar = _git("archive", "--format=tar", BASE, "src")
    if tar.returncode != 0:
        pytest.skip("git archive failed")
    dest = tmp_path_factory.mktemp("base")
    with tarfile.open(fileobj=io.BytesIO(tar.stdout)) as t:
        t.extractall(dest, filter="data")
    return dest / "src"


def _run(src: Path, fixtures: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONPATH": str(src), "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run(
        [sys.executable, "-c", SCRIPT, str(fixtures), str(out)], env=env, capture_output=True, timeout=600
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-2000:]
    return json.loads((out / "results.json").read_text(encoding="utf-8"))


def _even(value, out: str):
    """``value`` with what this work added removed and what differs between runs evened out."""
    if isinstance(value, dict):
        drop = {"model", "source_format", "seconds", "solidseas"}
        if "counts" in value and isinstance(value["counts"], dict):
            value = {**value, "counts": {k: v for k, v in value["counts"].items() if k != "unsupported"}}
        if {"output", "bytes", "mime"} <= set(value):  # file_written
            drop = drop | {"source"}
        if {"expression", "linked"} <= set(value):  # a property: its day was added since
            drop = drop | {"date"}
        if "output" in value and "format" in value and value.get("check") is None:
            # export_result's check (Open CASCADE reading the file back, export --check) was
            # added since; it is null unless asked for
            drop = drop | {"check"}
        if value.get("format") == "3mf" and "bytes" in value:
            # A 3MF names the package version that wrote it, which every commit bumps, so
            # its compressed size moves by a few bytes; its members are compared instead.
            drop = drop | {"bytes"}
        return {k: _even(v, out) for k, v in value.items() if k not in drop}
    if isinstance(value, list):
        return [_even(v, out) for v in value]
    if isinstance(value, str):
        return value.replace(out, "<out>")
    return value


def _members(path: Path) -> dict[str, bytes]:
    """A 3MF's members, the package version it names evened out."""
    with zipfile.ZipFile(path) as z:
        return {n: _VERSION.sub(b"SolidSeas <version>", z.read(n)) for n in z.namelist()}


def test_solidworks_output_is_what_the_base_commit_gives(base_src, tmp_path):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    for p in FIXTURES.iterdir():
        if p.suffix.lower() in (".sldprt", ".sldasm", ".slddrw"):
            shutil.copy2(p, fixtures / p.name)
    base = _run(base_src, fixtures, tmp_path / "base")
    head = _run(SRC, fixtures, tmp_path / "head")
    assert len(base) == len(head) >= 4 * 19 + 1
    for key in base:
        b = _even(base[key], str(tmp_path / "base"))
        h = _even(head[key], str(tmp_path / "head"))
        assert h == b, key
    names = sorted(p.name for p in (tmp_path / "base").glob("*.3mf"))
    assert names and names == sorted(p.name for p in (tmp_path / "head").glob("*.3mf"))
    for name in names:
        assert _members(tmp_path / "head" / name) == _members(tmp_path / "base" / name), name
    # the added fields are there, and only those
    listing = head["list"][1]["data"]
    assert listing["counts"]["unsupported"] == 0 and all(e["model"] is None for e in listing["entries"])
    exported = [v[1]["data"] for k, v in head.items() if k.startswith("export") and v[0] == 0]
    assert exported and all(d["source_format"] == "solidworks" for d in exported)
    previews = [v[1]["data"] for k, v in head.items() if k.startswith("preview") and v[0] == 0]
    assert previews and all(d["source"] == "stored" for d in previews)
    days = [p["date"] for e in listing["entries"] for p in e.get("properties") or [] if p["type"] == "date"]
    assert days and all(len(d) == 10 for d in days)
