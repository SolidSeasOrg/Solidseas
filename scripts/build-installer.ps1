<#
.SYNOPSIS
Build the SolidSeas Viewer installer: dist\SolidSeas-Setup-<version>.exe and its SHA-256.

.DESCRIPTION
Builds the one-folder viewer with scripts\build-viewer.ps1 -OneFolder, which installs the
exact packages and file hashes in requirements\build-windows.txt into the virtual
environment (pip --require-hashes) and runs PyInstaller, then compiles
packaging\SolidSeas.iss with Inno Setup 6's ISCC.exe. The installer installs that folder,
whose libraries, the LGPL ones included, are plain files that can be replaced
(THIRD_PARTY_NOTICES.txt section 2.2).

Writes dist\SolidSeas-Setup-<version>.exe and dist\SolidSeas-Setup-<version>.exe.sha256,
which holds the installer's SHA-256 in the form sha256sum -c reads. The version is the one
in src\solidseas\__init__.py.

.PARAMETER Venv
The virtual environment to build with. It is made with -Python when it does not exist.

.PARAMETER Python
The Python that makes the environment when it does not exist: 64-bit CPython 3.12, the
version requirements\build-windows.txt is locked for.

.PARAMETER SkipInstall
Build with what the environment already has (scripts\build-viewer.ps1 -SkipInstall).

.PARAMETER ExtensionsFolder
A folder of extension packages (.zip, as scripts\build-extensions.ps1 writes them into
dist\extensions) for the installer to carry. They are installed into the "SolidSeas
extensions" folder beside the viewer, which adds them, switched off, when it next starts.
The viewer accepts only the packages its own build was told to accept, so build those
packages first (scripts\build-viewer.ps1 -WithExtensions does both). By default the
installer carries none.

.PARAMETER InnoSetupFolder
Where Inno Setup 6 is installed. By default its usual folder under Program Files (x86).

.EXAMPLE
scripts\build-installer.ps1

.EXAMPLE
scripts\build-installer.ps1 -Venv .venv-installer -Python "py -3.12"
#>
param(
    [string]$Venv = '.venv-installer',
    [string]$Python = 'python',
    [switch]$SkipInstall,
    [string]$ExtensionsFolder = '',
    [string]$InnoSetupFolder = (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6')
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root 'dist'

$init = Get-Content -LiteralPath (Join-Path $root 'src\solidseas\__init__.py') -Raw
$match = [regex]::Match($init, '(?m)^__version__ = "(\d+\.\d+\.\d+)"')
if (-not $match.Success) { throw 'No __version__ in src\solidseas\__init__.py' }
$version = $match.Groups[1].Value

$iscc = Join-Path $InnoSetupFolder 'ISCC.exe'
if (-not (Test-Path -LiteralPath $iscc)) {
    throw "Inno Setup 6 is not installed: there is no $iscc"
}

$extensions = ''
if ($ExtensionsFolder) {
    $extensions = (Resolve-Path -LiteralPath $ExtensionsFolder).Path
    $zips = @(Get-ChildItem -LiteralPath $extensions -Filter '*.zip' -File)
    if ($zips.Count -eq 0) { throw "There are no .zip packages in $extensions" }
    "The installer carries {0} extension package(s) from {1}" -f $zips.Count, $extensions
}

$venvPath = if ([System.IO.Path]::IsPathRooted($Venv)) { $Venv } else { Join-Path $root $Venv }
if (-not (Test-Path -LiteralPath (Join-Path $venvPath 'Scripts\python.exe'))) {
    "Making the build environment $venvPath"
    $words = @($Python -split ' ' | Where-Object { $_ })  # an array even for one word
    $exeName = $words[0]
    $exeArgs = @($words | Select-Object -Skip 1)
    # pip and venv may write to standard error; judge them by the exit code alone.
    $ErrorActionPreference = 'Continue'
    & $exeName @exeArgs -m venv $venvPath
    $made = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($made -ne 0) { throw "Could not make the environment $venvPath with $Python" }
}

$viewerArgs = @{ Venv = $venvPath; OneFolder = $true }
if ($SkipInstall) { $viewerArgs.SkipInstall = $true }
& (Join-Path $PSScriptRoot 'build-viewer.ps1') @viewerArgs

$viewer = Join-Path $dist 'SolidSeasViewer'
if (-not (Test-Path -LiteralPath (Join-Path $viewer 'SolidSeasViewer.exe'))) {
    throw "The one-folder build is not in $viewer"
}
# Drawn by the spec from solidseas_app.viewer.icon, the same icon the program carries.
# PyInstaller's work folder (where the spec writes it) is build\pyinstaller\SolidSeasViewer.
$icon = Get-ChildItem -LiteralPath (Join-Path $root 'build\pyinstaller') -Filter 'SolidSeasViewer.ico' -Recurse -File |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
if (-not $icon) { throw "The build wrote no SolidSeasViewer.ico under build\pyinstaller" }

$setupName = "SolidSeas-Setup-$version.exe"
$setup = Join-Path $dist $setupName
if (Test-Path -LiteralPath $setup) { Remove-Item -LiteralPath $setup -Force }

$isccArgs = @(
    "/DAppVersion=$version",
    "/DViewerDir=$viewer",
    "/DIconFile=$icon",
    "/DOutputDir=$dist"
)
if ($extensions) { $isccArgs += "/DExtensionsDir=$extensions" }
$isccArgs += (Join-Path $root 'packaging\SolidSeas.iss')

# ISCC does not throw when it fails, and it writes its progress to standard output: the exit
# code is what says whether it worked.
$ErrorActionPreference = 'Continue'
& $iscc @isccArgs
$compiled = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($compiled -ne 0) { throw "ISCC.exe failed with exit code $compiled" }
if (-not (Test-Path -LiteralPath $setup)) { throw "ISCC.exe reported success but wrote no $setup" }

$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $setup).Hash.ToLower()
"{0}  {1}" -f $hash, $setupName | Set-Content -LiteralPath "$setup.sha256" -Encoding ASCII
$item = Get-Item -LiteralPath $setup
"Built {0} ({1:N1} MB)" -f $item.FullName, ($item.Length / 1MB)
"SHA-256 {0}, in {1}.sha256" -f $hash, $setupName
