"""The Windows build's lock, requirements/build-windows.txt: every package in it is pinned
to one version and carries the hashes pip checks with --require-hashes, it covers every
dependency pyproject.toml gives the library and the "build" extra, at versions those
accept, and scripts/build-viewer.ps1 installs from it that way."""

import re
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "requirements" / "build-windows.txt"
# The build runs on 64-bit Windows, so markers are judged there.
WINDOWS = {"sys_platform": "win32", "platform_system": "Windows", "os_name": "nt", "extra": "build"}


def locked():
    """{name: (version, [hashes])} from the lock, its continuation lines joined."""
    text = re.sub(r"\\\s*\n", " ", LOCK.read_text(encoding="utf-8"))
    pins = {}
    for line in text.splitlines():
        line = line.split(" #", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        spec, *options = line.split()
        name, sep, version = spec.partition("==")
        assert sep and version, f"not pinned to one version: {spec}"
        hashes = [o.removeprefix("--hash=") for o in options if o.startswith("--hash=")]
        assert len(hashes) == len(options), f"{name} has options other than hashes: {options}"
        pins[canonicalize_name(name)] = (version, hashes)
    return pins


def build_requirements():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    wanted = [Requirement(r) for r in project["dependencies"] + project["optional-dependencies"]["build"]]
    return [r for r in wanted if r.marker is None or r.marker.evaluate(WINDOWS)]


def test_every_locked_package_has_an_exact_version_and_sha256_hashes():
    pins = locked()
    assert pins
    for name, (version, hashes) in pins.items():
        assert re.fullmatch(r"[0-9][0-9A-Za-z.!+]*", version), f"{name}=={version}"
        assert hashes, f"{name} has no hash"
        for h in hashes:
            assert re.fullmatch(r"sha256:[0-9a-f]{64}", h), f"{name}: {h}"


def test_the_lock_covers_every_dependency_the_build_installs():
    pins = locked()
    for requirement in build_requirements():
        name = canonicalize_name(requirement.name)
        assert name in pins, f"{requirement} is not in {LOCK.name}: run scripts/lock-build-deps.sh"
        version = pins[name][0]
        assert requirement.specifier.contains(version, prereleases=True), (
            f"{name}=={version} does not satisfy {requirement}: run scripts/lock-build-deps.sh"
        )


def test_the_build_installs_from_the_lock_with_hashes_required():
    script = (ROOT / "scripts" / "build-viewer.ps1").read_text(encoding="utf-8")
    install = re.search(r"pip install([^\n]*`\n)*[^\n]*", script)
    assert install, "build-viewer.ps1 runs no pip install"
    command = install.group(0)
    for option in ("--require-hashes", "--no-deps", "-r $lock"):
        assert option in command, f"the build's pip install lacks {option}"
    assert "requirements\\build-windows.txt" in script
    assert script.count("pip install") == 1, "the build installs something outside the lock"


def test_the_lock_names_the_script_that_writes_it():
    assert "scripts/lock-build-deps.sh" in LOCK.read_text(encoding="utf-8")
    assert (ROOT / "scripts" / "lock-build-deps.sh").is_file()
