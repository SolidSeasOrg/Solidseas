"""Compile ``SolidSeas.SwBridge.exe`` from the C# sources in ``SwBridge/`` (Windows).

It uses the C# compiler that ships with the .NET Framework 4 in Windows
(``csc.exe``, C# 5) and references the SOLIDWORKS interop assemblies where the
SOLIDWORKS installer put them (``<install>\\api\\redist``). Nothing is copied
next to the program: the bridge loads those assemblies from that folder when it
runs (its ``--interop`` option, which :class:`~solidseas.swapi.bridge.Bridge`
passes). ``scripts/build-bridge.ps1`` runs the same command without Python.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from .bridge import DEFAULT_SOLIDWORKS_EXE, EXE_NAME, interop_folder

SOURCE_DIR = Path(__file__).resolve().parent / "SwBridge"
FRAMEWORK_REFERENCES = ("System.Web.Extensions.dll",)
INTEROP_REFERENCES = ("SolidWorks.Interop.sldworks.dll", "SolidWorks.Interop.swconst.dll")
CSC_OPTIONS = ("/nologo", "/target:exe", "/platform:anycpu", "/optimize+", "/langversion:5", "/warnaserror+")


class BridgeBuildError(RuntimeError):
    """The bridge could not be compiled; the message holds the compiler's output."""


def default_csc() -> Path:
    windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows"
    return Path(windir) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"


def _version() -> str:
    from .. import __version__

    if not re.fullmatch(r"\d+\.\d+\.\d+", __version__):
        raise BridgeBuildError(f"unexpected version {__version__!r}")
    return __version__


def build_bridge(
    out_dir: str | os.PathLike,
    *,
    solidworks_exe: str | os.PathLike | None = None,
    interop: str | os.PathLike | None = None,
    csc: str | os.PathLike | None = None,
    timeout: float = 300.0,
) -> Path:
    """Compile the bridge into ``out_dir`` and return the path of the program."""
    compiler = Path(csc) if csc else default_csc()
    if not compiler.is_file():
        raise BridgeBuildError(f"C# compiler not found: {compiler}")
    folder = Path(interop) if interop else interop_folder(solidworks_exe or DEFAULT_SOLIDWORKS_EXE)
    refs = [folder / name for name in INTEROP_REFERENCES]
    missing = [str(r) for r in refs if not r.is_file()]
    if missing:
        raise BridgeBuildError("SOLIDWORKS interop assemblies not found: " + ", ".join(missing))
    sources = sorted(SOURCE_DIR.glob("*.cs"))
    if not sources:
        raise BridgeBuildError(f"no C# sources in {SOURCE_DIR}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    exe = out / EXE_NAME
    version = _version()
    with tempfile.TemporaryDirectory(prefix="swbridge-") as tmp:
        stamp = Path(tmp) / "Version.cs"
        stamp.write_text(
            '[assembly: System.Reflection.AssemblyTitle("SolidSeas CAD Bridge")]\n'
            '[assembly: System.Reflection.AssemblyProduct("SolidSeas")]\n'
            f'[assembly: System.Reflection.AssemblyVersion("{version}.0")]\n'
            f'[assembly: System.Reflection.AssemblyFileVersion("{version}.0")]\n'
            f'[assembly: System.Reflection.AssemblyInformationalVersion("{version}")]\n',
            encoding="utf-8",
        )
        command = [
            str(compiler),
            *CSC_OPTIONS,
            f"/out:{exe}",
            *(f"/r:{r}" for r in refs),
            *(f"/r:{r}" for r in FRAMEWORK_REFERENCES),
            *(str(s) for s in sources),
            str(stamp),
        ]
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    if proc.returncode != 0 or not exe.is_file():
        raise BridgeBuildError((proc.stdout + proc.stderr).strip() or f"csc exited with {proc.returncode}")
    return exe
