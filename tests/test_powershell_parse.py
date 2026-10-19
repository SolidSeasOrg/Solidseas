"""Every PowerShell script in ``scripts/`` parses: the Windows machine runs them, and a
script that does not parse runs none of its steps. Uses PowerShell's own parser through
``pwsh`` (PowerShell 7, on Linux as well); skips where there is none."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = sorted((ROOT / "scripts").rglob("*.ps1"))
PWSH = shutil.which("pwsh") or shutil.which("pwsh", path=os.path.expanduser("~/.local/bin"))
PARSE = (
    "$e = $null; $t = $null; "
    "[void][System.Management.Automation.Language.Parser]::ParseFile("
    "$env:SOLIDSEAS_PS_FILE, [ref]$t, [ref]$e); "
    "ConvertTo-Json -Compress @($e | ForEach-Object { "
    "'{0}:{1} {2}' -f $_.Extent.StartLineNumber, $_.Extent.StartColumnNumber, $_.Message })"
)


@pytest.mark.skipif(PWSH is None, reason="no pwsh (PowerShell 7) here")
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_the_script_parses(script):
    done = subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-Command", PARSE],
        env={**os.environ, "SOLIDSEAS_PS_FILE": str(script)},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    errors = json.loads(done.stdout or "[]")
    errors = [errors] if isinstance(errors, str) else errors
    assert errors == [], f"{script.name} does not parse: {errors}"


def test_there_are_scripts_to_parse():
    assert any(p.name == "build-extensions.ps1" for p in SCRIPTS)
