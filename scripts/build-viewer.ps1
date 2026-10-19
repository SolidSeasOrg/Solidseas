<#
.SYNOPSIS
Build the SolidSeas Viewer preview as one Windows executable, dist\SolidSeasViewer.exe, or
with -OneFolder as a folder, dist\SolidSeasViewer.

.DESCRIPTION
Installs the library's dependencies and the "build" extra of pyproject.toml
(PySide6-Essentials, PyInstaller and truststore) into the virtual environment
you name, at the exact versions and file hashes in requirements\build-windows.txt,
then runs PyInstaller on packaging\SolidSeasViewer.spec from the repository
root. pip refuses any file whose hash is not in that list, so the executable
bundles only what the list names; scripts/lock-build-deps.sh writes the list
(docs/guide/building.md says how to update it). The project itself is not installed into
the environment: the spec reads the sources from src\. Build output goes to build\pyinstaller and dist\, which
Git ignores.

.PARAMETER Venv
The virtual environment to build with, for example .venv. It must exist.

.PARAMETER SkipInstall
Build with what the environment already has.

.PARAMETER OneFolder
Build the one-folder form instead of the single executable: dist\SolidSeasViewer\ holding
SolidSeasViewer.exe, with its libraries and licence texts as plain files in its _internal
folder. It starts faster, and it is what scripts\build-installer.ps1 packs into the installer.
The single executable is not built by the same run.

.PARAMETER WithExtensions
First build the extension packages with scripts\build-extensions.ps1 (into
dist\extensions), so the viewer built here accepts them, and write
dist\SHA256SUMS.txt for the viewer and the packages: what a release publishes.

.PARAMETER FfmpegFolder
With -WithExtensions: the folder holding an LGPL ffmpeg.exe for the video package.

.PARAMETER FfmpegSource
With -WithExtensions: where the exact source of that ffmpeg build is, which the video package
carries (scripts\build-extensions.ps1).

.PARAMETER SolidCraftZip
With -WithExtensions: SolidCraft's portable zip of the release build-extensions.ps1 pins,
already downloaded, so it is not downloaded again.

.PARAMETER WithBridge
Also build the bridge program beside the viewer, dist\SolidSeas.SwBridge.exe,
with scripts\build-bridge.ps1 (needs SOLIDWORKS installed): the layout from
before the CAD Bridge was a package, which the viewer still finds.

.EXAMPLE
scripts\build-viewer.ps1 -Venv .venv
#>
param(
    [Parameter(Mandatory = $true)][string]$Venv,
    [switch]$SkipInstall,
    [switch]$OneFolder,
    [switch]$WithExtensions,
    [string]$FfmpegFolder = '',
    [string]$FfmpegSource = '',
    [string]$SolidCraftZip = '',
    [switch]$WithBridge
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path (Resolve-Path $Venv) "Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "No Python in that environment: $python"
}

Push-Location $root
try {
    # pip and PyInstaller log to standard error. Windows PowerShell turns those lines
    # into errors when output is redirected, so native commands are judged by their
    # exit codes alone.
    $ErrorActionPreference = "Continue"
    if (-not $SkipInstall) {
        # Every package the executable bundles, at an exact version and checked against its
        # recorded hashes, from wheels only, so nothing is built from source on the way.
        $lock = Join-Path $root "requirements\build-windows.txt"
        & $python -m pip install --disable-pip-version-check --require-hashes --no-deps `
            --only-binary ":all:" -r $lock
        if ($LASTEXITCODE -ne 0) { throw "pip could not install the locked requirements in $lock" }
    }
    if ($WithExtensions) {
        $ErrorActionPreference = "Stop"
        & (Join-Path $PSScriptRoot "build-extensions.ps1") -Venv $Venv -FfmpegFolder $FfmpegFolder -FfmpegSource $FfmpegSource -SolidCraftZip $SolidCraftZip
        $ErrorActionPreference = "Continue"
    }
    # The spec reads SOLIDSEAS_ONE_FOLDER to choose the one-folder build.
    $savedOneFolder = $env:SOLIDSEAS_ONE_FOLDER
    if ($OneFolder) { $env:SOLIDSEAS_ONE_FOLDER = '1' } else { $env:SOLIDSEAS_ONE_FOLDER = $null }
    try {
        & $python -m PyInstaller packaging\SolidSeasViewer.spec --noconfirm --clean `
            --distpath dist --workpath build\pyinstaller
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
    }
    finally {
        $env:SOLIDSEAS_ONE_FOLDER = $savedOneFolder
    }
}
finally {
    $ErrorActionPreference = "Stop"
    Pop-Location
}

if ($OneFolder) {
    $folder = Join-Path $root "dist\SolidSeasViewer"
    $exe = Get-Item (Join-Path $folder "SolidSeasViewer.exe")
    if (-not (Test-Path -LiteralPath (Join-Path $folder "_internal\licenses\BUNDLED-FILES.txt"))) {
        throw "The one-folder build has no _internal\licenses\BUNDLED-FILES.txt"
    }
    $size = (Get-ChildItem -LiteralPath $folder -Recurse -File | Measure-Object -Property Length -Sum).Sum
    "Built {0} ({1:N1} MB in all)" -f $folder, ($size / 1MB)
}
else {
    $exe = Get-Item (Join-Path $root "dist\SolidSeasViewer.exe")
    "Built {0} ({1:N1} MB)" -f $exe.FullName, ($exe.Length / 1MB)
}
if ($WithExtensions) {
    $files = @($exe) + @(Get-ChildItem -LiteralPath (Join-Path $root "dist\extensions") -Filter "*.zip" | Sort-Object Name)
    $sums = foreach ($f in $files) {
        $name = if ($f.Name -like "*.zip") { "extensions/" + $f.Name } elseif ($OneFolder) { "SolidSeasViewer/" + $f.Name } else { $f.Name }
        "{0}  {1}" -f (Get-FileHash -Algorithm SHA256 -LiteralPath $f.FullName).Hash.ToLower(), $name
    }
    $sums | Set-Content -LiteralPath (Join-Path $root "dist\SHA256SUMS.txt") -Encoding ASCII
    "Wrote dist\SHA256SUMS.txt for the viewer and {0} package(s)" -f ($files.Count - 1)
}
if ($WithBridge) {
    # Beside the executable, where the viewer looks for it.
    $bridgeFolder = if ($OneFolder) { Join-Path $root "dist\SolidSeasViewer" } else { Join-Path $root "dist" }
    & (Join-Path $PSScriptRoot "build-bridge.ps1") -OutputFolder $bridgeFolder
}
