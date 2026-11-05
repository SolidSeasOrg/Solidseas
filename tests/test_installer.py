"""The Windows installer and the one-folder build it installs, checked on any platform: the
viewer's spec makes the one-folder build when asked (run here with PyInstaller's parts
stood in for, so nothing is built), packaging/SolidSeas.iss has what a per-user installer
needs and nothing that needs an administrator, scripts/build-installer.ps1 builds and checks
what it says, and .github/workflows/release.yml runs only for a release, on GitHub's Windows
runner, with every action pinned to a commit."""

import ast
import hashlib
import importlib.metadata
import os
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "SolidSeasViewer.spec"
ISS = ROOT / "packaging" / "SolidSeas.iss"
BUILD_VIEWER = ROOT / "scripts" / "build-viewer.ps1"
BUILD_INSTALLER = ROOT / "scripts" / "build-installer.ps1"
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
PWSH = shutil.which("pwsh") or shutil.which("pwsh", path=os.path.expanduser("~/.local/bin"))


# -- the spec, run with stand-ins for PyInstaller -------------------------------------------


class _Analysis:
    def __init__(self, scripts, **options):
        self.options = options
        self.pure = [("solidseas", "x.py", "PYMODULE"), ("os", "x.py", "PYMODULE")]
        self.scripts = [("pyi_rth_inspect", "x.py", "PYSOURCE"), ("__main__", "x.py", "PYSOURCE")]
        self.binaries = [
            ("PySide6/Qt6Core.dll", "x.dll", "BINARY"),
            ("PySide6/QtCore.pyd", "x.pyd", "EXTENSION"),
            ("PySide6/plugins/platforms/qwindows.dll", "x.dll", "BINARY"),
            ("PySide6/plugins/imageformats/qjpeg.dll", "x.dll", "BINARY"),
            ("PySide6/opengl32sw.dll", "x.dll", "BINARY"),
            ("shiboken6/shiboken6.abi3.dll", "x.dll", "BINARY"),
            ("python312.dll", "x.dll", "BINARY"),
            ("libcrypto-3.dll", "x.dll", "BINARY"),
            ("vcruntime140.dll", "x.dll", "BINARY"),
        ]
        self.datas = [("PySide6/translations/qt_de.qm", "x.qm", "DATA")]


def run_spec(tmp_path, monkeypatch, one_folder: bool, collect=lambda name: []) -> dict:
    """Execute the spec as PyInstaller would, with its classes recorded instead of building.
    ``collect`` stands in for PyInstaller's ``collect_submodules``."""
    calls: dict = {"EXE": [], "COLLECT": [], "Analysis": []}
    base = tmp_path / "python"
    base.mkdir()
    # A Python licence naming every library the stand-in build carries.
    (base / "LICENSE.txt").write_text("PSF openssl libffi sqlite bzip2 xz mpdec microsoft", encoding="utf-8")
    work = tmp_path / "work"
    hooks = types.ModuleType("PyInstaller.utils.hooks")
    hooks.collect_submodules = collect
    versioninfo = types.ModuleType("PyInstaller.utils.win32.versioninfo")
    for name in ("FixedFileInfo", "StringFileInfo", "StringStruct", "StringTable", "VarFileInfo"):
        setattr(versioninfo, name, lambda *a, **k: (a, k))
    versioninfo.VarStruct = versioninfo.VSVersionInfo = lambda *a, **k: (a, k)
    icon = types.ModuleType("solidseas_app.viewer.icon")
    icon.write_ico = lambda path: Path(path).write_bytes(b"\0\0\1\0")
    for name, module in {
        "PyInstaller": types.ModuleType("PyInstaller"),
        "PyInstaller.utils": types.ModuleType("PyInstaller.utils"),
        "PyInstaller.utils.hooks": hooks,
        "PyInstaller.utils.win32": types.ModuleType("PyInstaller.utils.win32"),
        "PyInstaller.utils.win32.versioninfo": versioninfo,
        "solidseas_app.viewer.icon": icon,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "base_prefix", str(base))
    monkeypatch.setattr(importlib.metadata, "version", lambda dist: "6.12.0")
    if one_folder:
        monkeypatch.setenv("SOLIDSEAS_ONE_FOLDER", "1")
    else:
        monkeypatch.delenv("SOLIDSEAS_ONE_FOLDER", raising=False)

    def record(kind):
        def make(*args, **kwargs):
            calls[kind].append((args, kwargs))
            return kind

        return make

    def analysis(scripts, **options):
        a = _Analysis(scripts, **options)
        calls["Analysis"].append(a)
        return a

    spec_globals = {
        "__name__": "__main__",
        "SPECPATH": str(SPEC.parent),
        "workpath": str(work),
        "Analysis": analysis,
        "PYZ": lambda pure: "PYZ",
        "EXE": record("EXE"),
        "COLLECT": record("COLLECT"),
    }
    exec(compile(SPEC.read_text(encoding="utf-8"), str(SPEC), "exec"), spec_globals)
    calls["bundled"] = (work / "BUNDLED-FILES.txt").read_text(encoding="utf-8")
    calls["globals"] = spec_globals
    return calls


def _dests(entries) -> set[str]:
    return {e[0] for e in entries}


def test_the_spec_makes_one_file_by_default(tmp_path, monkeypatch):
    calls = run_spec(tmp_path, monkeypatch, one_folder=False)
    assert calls["COLLECT"] == []
    [(args, kwargs)] = calls["EXE"]
    assert kwargs["name"] == "SolidSeasViewer" and kwargs["console"] is False
    assert "exclude_binaries" not in kwargs and kwargs["runtime_tmpdir"] is None
    pyz, scripts, binaries, datas, *_ = args
    assert pyz == "PYZ"
    assert "PySide6/Qt6Core.dll" in _dests(binaries)
    assert {"licenses/BUNDLED-FILES.txt", "licenses/LGPL-3.0.txt", "licenses/LICENSE"} <= _dests(datas)
    assert "_MEI" in calls["bundled"] and "_internal" not in calls["bundled"]


def test_the_spec_makes_the_one_folder_build_when_asked(tmp_path, monkeypatch):
    calls = run_spec(tmp_path, monkeypatch, one_folder=True)
    [(args, kwargs)] = calls["EXE"]
    assert args[0] == "PYZ" and args[2] == []
    assert kwargs["exclude_binaries"] is True and kwargs["contents_directory"] == "_internal"
    assert kwargs["name"] == "SolidSeasViewer" and kwargs["upx"] is False
    [(cargs, ckwargs)] = calls["COLLECT"]
    exe, binaries, datas = cargs
    assert exe == "EXE" and ckwargs["name"] == "SolidSeasViewer" and ckwargs["upx"] is False
    # The same filtered libraries and the same licence texts as the one-file build.
    assert "PySide6/Qt6Core.dll" in _dests(binaries) and "shiboken6/shiboken6.abi3.dll" in _dests(binaries)
    assert not {"PySide6/opengl32sw.dll", "PySide6/plugins/imageformats/qjpeg.dll"} & _dests(binaries)
    assert "PySide6/translations/qt_de.qm" not in _dests(datas)
    licences = {d for d in _dests(datas) if d.startswith("licenses/")}
    # every text in licenses/ but those only an extension package or the library carries
    not_in_viewer = {"LGPL-2.1.txt", "OCCT_LGPL_EXCEPTION.txt", "OCP-LICENSE.txt", "OCP-third-party.txt"}
    not_in_viewer.add("three.js-LICENSE.txt")
    expected = {f"licenses/{p.name}" for p in (ROOT / "licenses").iterdir() if p.name not in not_in_viewer}
    expected |= {f"licenses/{n}" for n in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.txt")}
    expected |= {"licenses/Python-LICENSE.txt", "licenses/BUNDLED-FILES.txt"}
    assert licences == expected


def test_bundled_files_describe_the_one_folder_layout(tmp_path, monkeypatch):
    text = run_spec(tmp_path, monkeypatch, one_folder=True)["bundled"]
    head = text.split("\n\n", 1)[0]
    assert "one-folder build" in head and "_internal folder beside SolidSeasViewer.exe" in head
    assert "may be replaced" in head and "_MEI" not in text and "unpacked" not in head
    assert "  PySide6/Qt6Core.dll" in text
    assert "Qt, Qt for Python and shiboken6, under the LGPL version 3: these may be replaced" in text


def test_the_spec_still_refuses_a_package_the_notices_do_not_cover(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _Analysis, "__init__", _wrap_init(lambda a: a.pure.append(("requests", "x.py", "PYMODULE")))
    )
    with pytest.raises(SystemExit, match="requests"):
        run_spec(tmp_path, monkeypatch, one_folder=True)


def _source_submodules(name: str) -> list[str]:
    """What ``collect_submodules(name)`` finds, read from src/ without importing anything."""
    folder = ROOT / "src" / Path(*name.split("."))
    found = [name]
    for path in sorted(folder.rglob("*.py")):
        parts = path.relative_to(folder).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            found.append(".".join((name, *parts)))
    return found


def test_the_spec_carries_the_command_line_the_service_and_every_module_named_in_a_string(
    tmp_path, monkeypatch
):
    """The executable runs the library's command line (--cli), with the REST service, its
    OpenAPI description and the MCP connector, and imports some modules by name only, from
    "module:function" strings PyInstaller's analysis cannot follow: each must be a hidden
    import, or the executable fails only when that path runs."""
    calls = run_spec(tmp_path, monkeypatch, one_folder=True, collect=_source_submodules)
    [analysis] = calls["Analysis"]
    hidden = set(analysis.options["hiddenimports"])
    needed = {
        "solidseas.cli",
        "solidseas.mcpwire",
        "solidseas.serve",
        "solidseas.serve.server",
        "solidseas.serve.openapi",
        "solidseas.serve.mcp",
        "solidseas.serve.config",
        "solidseas.catalog",
        "solidseas.jobs",
    }
    by_name = set()
    for path in (ROOT / "src").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                m = re.fullmatch(r"(solidseas(?:_app)?(?:\.\w+)+):\w+", node.value)
                if m:
                    by_name.add(m.group(1))
    assert {"solidseas.jobs", "solidseas.formats.stl", "solidseas.drawing.pdf"} <= by_name
    excluded = set(analysis.options["excludes"])
    assert not (needed | by_name) - hidden, sorted((needed | by_name) - hidden)
    assert not (needed | by_name) & excluded


def _wrap_init(change):
    original = _Analysis.__init__

    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        change(self)

    return init


def test_the_spec_parses_and_builds_both_forms_from_one_branch():
    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    branches = [n for n in tree.body if isinstance(n, ast.If) and getattr(n.test, "id", None) == "ONE_FOLDER"]
    assert len(branches) == 2, "ONE_FOLDER chooses the BUNDLED-FILES text and the build"
    build = branches[-1]
    called = {n.func.id for n in ast.walk(build) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert {"EXE", "COLLECT"} <= called


def test_build_viewer_passes_one_folder_to_the_spec():
    script = BUILD_VIEWER.read_text(encoding="utf-8")
    assert "[switch]$OneFolder" in script
    assert "$env:SOLIDSEAS_ONE_FOLDER = '1'" in script
    assert "SOLIDSEAS_ONE_FOLDER" in SPEC.read_text(encoding="utf-8")
    assert "_internal\\licenses\\BUNDLED-FILES.txt" in script


# -- the Inno Setup script ------------------------------------------------------------------


def iss_sections() -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = ""
    for raw in ISS.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        heading = re.fullmatch(r"\[(\w+)\]", line)
        if heading:
            current = heading.group(1)
            sections.setdefault(current, [])
        else:
            sections.setdefault(current, []).append(line)
    return sections


def iss_setup() -> dict[str, str]:
    setup = {}
    for line in iss_sections()["Setup"]:
        if line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        setup[key.strip()] = value.strip()
    return setup


def test_the_installer_script_is_ascii():
    ISS.read_text(encoding="ascii")


def test_the_installer_has_the_required_setup_keys():
    setup = iss_setup()
    assert re.fullmatch(r"\{\{[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}\}", setup["AppId"])
    expected = {
        "AppName": "{#AppName}",
        "AppVersion": "{#AppVersion}",
        "AppPublisher": "SolidSeas",
        "DefaultDirName": "{autopf}\\SolidSeas",
        "PrivilegesRequired": "lowest",
        "PrivilegesRequiredOverridesAllowed": "dialog",
        "LicenseFile": "..\\LICENSE",
        "OutputBaseFilename": "SolidSeas-Setup-{#AppVersion}",
        "UninstallDisplayIcon": "{app}\\{#AppExe}",
        "CloseApplications": "yes",
        "ChangesAssociations": "no",
        "ChangesEnvironment": "no",
    }
    for key, value in expected.items():
        assert setup.get(key) == value, key
    text = ISS.read_text(encoding="utf-8")
    assert '#define AppName "SolidSeas Viewer"' in text
    assert '#define AppExe "SolidSeasViewer.exe"' in text
    assert "SetupIconFile={#IconFile}" in text
    assert (ROOT / "LICENSE").is_file()


def test_the_installer_needs_no_administrator_and_keeps_user_data():
    text = ISS.read_text(encoding="utf-8")
    sections = iss_sections()
    # Nothing an administrator would have to allow, nothing outside the program's folder. The
    # one [Code] section only closes the viewer it installed (see the test below).
    for section in ("Registry", "UninstallDelete", "UninstallRun", "Dirs", "INI"):
        assert section not in sections, f"[{section}] is not wanted"
    assert not re.search(r"PrivilegesRequired\s*=\s*admin", text, re.I)
    # [Code] reads {sys} only to start Windows PowerShell; no file goes there.
    outside_code = text.split("\n[Code]\n")[0]
    assert not re.search(
        r"\{(sys|syswow64|win|commonpf\w*|commonappdata|userappdata|localappdata)\}", outside_code
    )
    assert "{sys}\\WindowsPowerShell\\v1.0\\powershell.exe" in text.split("\n[Code]\n")[1]
    assert not re.search(r"\b(netsh|sc\.exe|regsvr32|icacls|HKLM|HKEY_LOCAL_MACHINE)\b", text, re.I)
    assert not re.search(r"ChangesAssociations\s*=\s*yes", text, re.I)
    assert not re.search(r"Flags:[^\n]*\b(regserver|sharedfile|restartreplace|uninsneveruninstall)\b", text)
    # Install deletes only the program's own files from the version before.
    for line in sections["InstallDelete"]:
        if not line.startswith("#"):
            assert re.search(r'Name: "\{app\}\\(_internal|SolidSeas extensions\\\*\.zip)"', line), line
    assert all(not line.startswith("Source:") or 'DestDir: "{app}' in line for line in sections["Files"])


def test_the_installer_adds_a_start_menu_entry_and_an_optional_desktop_icon():
    sections = iss_sections()
    icons = sections["Icons"]
    assert any(i.startswith('Name: "{autoprograms}\\{#AppName}"') for i in icons)
    desktop = [i for i in icons if "{autodesktop}" in i]
    assert desktop and all("Tasks: desktopicon" in i for i in desktop)
    assert any(t.startswith('Name: "desktopicon"') and "Flags: unchecked" in t for t in sections["Tasks"])


def test_the_installer_carries_extension_packages_only_when_given_some():
    text = ISS.read_text(encoding="utf-8")
    from solidseas_app.extensions import BESIDE_FOLDERS

    folder = BESIDE_FOLDERS[0]
    block = text[text.index("[Files]") :]
    extensions = re.search(r"#ifdef ExtensionsDir\n(.*?)#endif", block, re.S).group(1)
    assert f'DestDir: "{{app}}\\{folder}"' in extensions and "{#ExtensionsDir}\\*.zip" in extensions


# -- the build script -----------------------------------------------------------------------


def test_build_installer_builds_the_one_folder_viewer_and_checks_iscc():
    script = BUILD_INSTALLER.read_text(encoding="utf-8")
    assert "build-viewer.ps1" in script and "OneFolder = $true" in script
    assert "Inno Setup 6" in script and "${env:ProgramFiles(x86)}" in script and "ISCC.exe" in script
    assert "$compiled = $LASTEXITCODE" in script and "if ($compiled -ne 0)" in script
    assert "SolidSeas-Setup-$version.exe" in script and "Get-FileHash -Algorithm SHA256" in script
    assert '.sha256"' in script
    for define in ("/DAppVersion=", "/DViewerDir=", "/DIconFile=", "/DOutputDir=", "/DExtensionsDir="):
        assert define in script, define
        assert define[2:-1] in ISS.read_text(encoding="utf-8"), define
    # No package is installed outside the hash-locked list build-viewer.ps1 installs.
    assert "pip install" not in script


def test_build_installer_runs_on_windows_powershell_5():
    script = BUILD_INSTALLER.read_text(encoding="utf-8")
    script.encode("ascii")
    # PowerShell 7 only: the ternary, the null-coalescing operators and pipeline chains.
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
    assert not re.search(r"\?\?|\?\.|&&|\|\|", code)
    assert not re.search(r"\s\?\s[^:]+\s:\s", code)


# -- the release workflow -------------------------------------------------------------------


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_every_workflow_action_is_pinned_to_a_commit(workflow):
    text = workflow.read_text(encoding="utf-8")
    uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)(.*)$", text, re.M)
    assert uses
    for action, rest in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+(/[\w./-]+)?@[0-9a-f]{40}", action), action
        assert re.search(r"#\s*v\d+\.\d+\.\d+", rest), f"{action} has no version comment"


def test_the_workflows_pin_each_action_to_the_same_commit():
    pins: dict[str, set[str]] = {}
    for workflow in WORKFLOWS:
        for action in re.findall(r"^\s*-?\s*uses:\s*(\S+)", workflow.read_text(encoding="utf-8"), re.M):
            name, _, commit = action.partition("@")
            pins.setdefault(name, set()).add(commit)
    assert {"actions/checkout", "actions/setup-python"} <= set(pins)
    for name, commits in pins.items():
        assert len(commits) == 1, f"{name} is pinned to {sorted(commits)}"


def without_comments(text: str) -> str:
    """A workflow's YAML without its comments, whose prose may name what the code must not."""
    return "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in text.splitlines())


def test_the_release_workflow_runs_only_for_releases_on_a_hosted_windows_runner():
    text = RELEASE.read_text(encoding="utf-8")
    code = without_comments(text)
    assert "pull_request" not in code and "self-hosted" not in code and "solidseas-vm" not in code
    assert re.search(r"^\s*runs-on: windows-latest$", text, re.M)
    assert re.search(r"^permissions:\n  contents: write\n\n", text, re.M)
    assert "types: [published]" in text and "workflow_dispatch:" in text
    assert re.search(r"choco install innosetup --version \$env:INNO_SETUP_VERSION", text)
    assert re.search(r'INNO_SETUP_VERSION: "6\.\d+\.\d+"', text)
    assert "scripts\\build-installer.ps1" in text
    assert "gh release upload $env:TAG $setup \"$setup.sha256\" 'dist\\SolidSeas-Setup.exe' `" in text
    assert "'dist\\SolidSeasViewer.exe.sha256' 'dist\\BUNDLED-FILES.txt' `" in text
    assert "QT_QPA_PLATFORM: offscreen" in text and "--self-test" in text
    # The tag reaches commands only through the environment, never pasted into a script.
    for line in text.splitlines():
        if "${{" in line and "inputs.tag" in line:
            assert re.match(r"\s*(TAG|group):", line), line


def test_the_release_workflow_loads_as_yaml():
    yaml = pytest.importorskip("yaml")
    data = yaml.safe_load(RELEASE.read_text(encoding="utf-8"))
    triggers = data.get("on", data.get(True))
    assert set(triggers) == {"release", "workflow_dispatch"}
    assert triggers["release"] == {"types": ["published"]}
    assert data["permissions"] == {"contents": "write"}
    [job] = data["jobs"].values()
    assert job["runs-on"] == "windows-latest" and "permissions" not in job
    for step in job["steps"]:
        if "uses" in step:
            assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", step["uses"]), step["uses"]


def _release_steps() -> list[tuple[str, str]]:
    """The release job's steps as (name, script), read as text so that no YAML library is
    needed: each step starts at a line "      - " and its name is on its "name:" line."""
    job = RELEASE.read_text(encoding="utf-8").split("\n    steps:\n", 1)[1]
    steps = re.split(r"^      - ", job, flags=re.M)
    out = []
    for step in steps[1:]:
        name = re.search(r"^(?:name|uses): (.+)$", step, re.M)
        out.append((name.group(1).strip() if name else "", step))
    return out


def _step(name: str) -> str:
    [found] = [script for n, script in _release_steps() if n == name]
    return found


def test_the_release_accepts_its_own_extension_packages_before_it_builds_the_viewer():
    names = [n for n, _ in _release_steps()]
    fetch, check, accept = (
        "Fetch the release's extension packages",
        "Check the extension packages against SHA256SUMS.txt",
        "Accept the extension packages",
    )
    build = "Build the installer"
    assert names.index(fetch) < names.index(check) < names.index(accept) < names.index(build)
    assert names.index(build) < names.index("Build the single-file viewer and run its self-test")
    assert (
        "gh release download $env:TAG --pattern '*.zip' --pattern SHA256SUMS.txt --dir dist\\extensions"
        in _step(fetch)
    )
    # a release with no packages still builds, and says so in the job summary
    assert "GITHUB_STEP_SUMMARY" in _step(fetch) and "EXTENSIONS=false" in _step(fetch)
    assert "if: env.EXTENSIONS == 'true'" in _step(check) and "if: env.EXTENSIONS == 'true'" in _step(accept)
    assert '"-$env:VERSION.zip"' in _step(check) and "Get-FileHash" in _step(check)
    assert "-m solidseas_app.extensions.package accept @zips --out $accepted" in _step(accept)
    assert "$accepted = 'src\\solidseas_app\\extensions\\accepted.json'" in _step(accept)
    assert "PYTHONPATH: src" in _step(accept)
    assert "$options.ExtensionsFolder = 'dist\\extensions'" in _step(build)
    # the hand-attached packages are never uploaded over, and their list is replaced by the
    # release's own, never sent back as it was downloaded
    upload = without_comments(_step("Attach the installer and the single-file viewer to the release"))
    assert ".zip" not in upload and "extensions" not in upload
    assert "'dist\\SHA256SUMS.txt' 'licenses\\SOURCE.txt' --clobber" in upload


def test_the_release_s_package_check_runs_against_a_real_package(tmp_path):
    """The Python the accept step writes to a file and runs, run here on a package built
    the way scripts/build-extensions.ps1 builds one."""
    from solidseas_app.extensions import package

    script = _step("Accept the extension packages")
    body = script.split("-Value @'\n", 1)[1].split("\n          '@\n", 1)[0]
    code = "\n".join(line[10:] for line in body.splitlines())
    (tmp_path / "check.py").write_text(code, encoding="utf-8")
    folder = tmp_path / "bridge"
    folder.mkdir()
    (folder / "SolidSeas.SwBridge.exe").write_bytes(b"MZ the bridge")
    zip_path = package.build_package("cad-bridge", str(folder), str(tmp_path / "out"))
    accepted = tmp_path / "accepted.json"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), os.environ.get("PYTHONPATH", "")])}

    def run(*args):
        return subprocess.run([sys.executable, *args], env=env, capture_output=True, text=True)

    made = run("-m", "solidseas_app.extensions.package", "accept", zip_path, "--out", str(accepted))
    assert made.returncode == 0, made.stderr
    done = run(str(tmp_path / "check.py"), str(accepted), zip_path)
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["cad-bridge", "accepted"]
    accepted.write_text('{"version": 1, "accepted": {}}', encoding="utf-8")
    refused = run(str(tmp_path / "check.py"), str(accepted), zip_path)
    assert refused.returncode != 0 and "not one this version of SolidSeas accepts" in refused.stderr


def _run_block(step: str) -> str:
    """The PowerShell a release step runs, its "run: |" block without the indent."""
    lines = []
    for line in step.split("        run: |\n", 1)[1].splitlines():
        if line.strip() and not line.startswith(" " * 10):
            break
        lines.append(line[10:])
    return "\n".join(lines) + "\n"


def _run_step(tmp_path, name: str, **env) -> subprocess.CompletedProcess:
    """Run the release step ``name`` in ``tmp_path`` as the runner's pwsh shell does, stopping
    at the first error. PowerShell on Linux reads the step's backslash paths as folders."""
    script = tmp_path / "step.ps1"
    script.write_text("$ErrorActionPreference = 'Stop'\n" + _run_block(_step(name)), encoding="utf-8")
    return subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-File", str(script)],
        cwd=tmp_path,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.skipif(PWSH is None, reason="no pwsh (PowerShell 7) here")
@pytest.mark.parametrize("extensions", [True, False], ids=["with-packages", "without-packages"])
def test_the_release_writes_one_sha256sums_for_everything_it_attaches(tmp_path, extensions):
    write = "Write SHA256SUMS.txt for the release"
    names = [n for n, _ in _release_steps()]
    assert names.index("Build the single-file viewer and run its self-test") < names.index(write)
    assert names.index(write) < names.index("Attach the installer and the single-file viewer to the release")
    dist = tmp_path / "dist"
    (dist / "extensions").mkdir(parents=True)
    built = {"SolidSeas-Setup-1.2.3.exe": b"MZ the installer", "SolidSeasViewer.exe": b"MZ the viewer"}
    packages = {"cad-bridge-1.2.3.zip": b"PK the bridge", "video-1.2.3.zip": b"PK the video"}
    for name, data in built.items():
        (dist / name).write_bytes(data)
    for name, data in packages.items():
        (dist / "extensions" / name).write_bytes(data)
    # the list attached by hand, as scripts/build-extensions.ps1 writes it
    by_hand = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in packages.items())
    (dist / "extensions" / "SHA256SUMS.txt").write_bytes(by_hand.encode("ascii"))

    done = _run_step(tmp_path, write, VERSION="1.2.3", EXTENSIONS="true" if extensions else "false")
    assert done.returncode == 0, done.stderr
    listed = {
        "SolidSeas-Setup-1.2.3.exe": built["SolidSeas-Setup-1.2.3.exe"],
        "SolidSeas-Setup.exe": built["SolidSeas-Setup-1.2.3.exe"],
        "SolidSeasViewer.exe": built["SolidSeasViewer.exe"],
        **(packages if extensions else {}),
    }
    # the form sha256sum -c reads: ASCII, two spaces, LF line ends, a newline after the last
    want = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in listed.items())
    assert (dist / "SHA256SUMS.txt").read_bytes() == want.encode("ascii")
    assert (dist / "SolidSeas-Setup.exe").read_bytes() == built["SolidSeas-Setup-1.2.3.exe"]
    # the list the packages were checked against stays in dist\extensions as it was
    assert (dist / "extensions" / "SHA256SUMS.txt").read_bytes() == by_hand.encode("ascii")
    if extensions:
        # A run by hand later downloads this list in its place; the check still passes.
        (dist / "extensions" / "SHA256SUMS.txt").write_bytes(want.encode("ascii"))
        check = _run_step(tmp_path, "Check the extension packages against SHA256SUMS.txt", VERSION="1.2.3")
        assert check.returncode == 0, check.stderr
        assert check.stdout.split() == [part for line in by_hand.splitlines() for part in line.split()]


def test_ci_tests_the_viewer_on_the_hosted_windows_runner_only():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert re.search(r"- os: windows-latest\n\s+extras: dev,app\n", text)
    assert re.search(r"- os: ubuntu-latest\n\s+extras: dev\n", text)
    assert 'pip install -e ".[${{ matrix.extras }}]"' in text and "QT_QPA_PLATFORM: offscreen" in text
    own = text.split("\n  own-linux:\n", 1)[1].split("\n  hosted:\n", 1)[0]
    assert '-e ".[dev]"' in own, "the self-hosted machine installs no Qt"


def test_no_workflow_gives_a_pull_request_write_access_or_the_release_job():
    for workflow in WORKFLOWS:
        text = without_comments(workflow.read_text(encoding="utf-8"))
        assert "pull_request_target" not in text, workflow.name
        if "contents: write" in text:
            assert "pull_request" not in text, workflow.name


def test_the_installer_closes_only_its_own_running_viewer_through_its_window():
    iss = (ROOT / "packaging" / "SolidSeas.iss").read_text(encoding="utf-8")
    code = iss[iss.index("\n[Code]\n") :]
    for needed in (
        "function PrepareToInstall",
        "function InitializeUninstall",
        "CloseMainWindow",
        "StartsWith(",
    ):
        assert needed in code, needed
    for forbidden in ("Stop-Process", "taskkill", "Kill("):
        assert forbidden not in code, forbidden
