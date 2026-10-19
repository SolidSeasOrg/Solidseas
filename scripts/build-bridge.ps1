<#
.SYNOPSIS
Build the SOLIDWORKS bridge, dist\SolidSeas.SwBridge.exe, from src\solidseas\swapi\SwBridge.

.DESCRIPTION
Compiles the C# sources with the C# compiler of the .NET Framework 4 that ships
with Windows (csc.exe, C# 5), against the SOLIDWORKS interop assemblies in
<SOLIDWORKS>\api\redist. Nothing else needs installing. The interop assemblies
are not copied: the bridge loads them from that folder when it runs (SolidSeas
passes it with --interop). "python -m solidseas.swapi build" runs the same
command.

The program goes to dist\, next to dist\SolidSeasViewer.exe when the viewer is
built there too: SolidSeas looks for the bridge next to its own executable, then
in dist\ of a source checkout, unless SOLIDSEAS_SWBRIDGE names it.

.PARAMETER OutputFolder
Where to write SolidSeas.SwBridge.exe. Default: dist in the repository.

.PARAMETER SolidWorksFolder
The SOLIDWORKS installation folder, the one that holds SLDWORKS.exe.

.EXAMPLE
scripts\build-bridge.ps1
#>
param(
    [string]$OutputFolder = '',
    [string]$SolidWorksFolder = 'C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $OutputFolder) { $OutputFolder = Join-Path $root 'dist' }
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $csc)) { throw "C# compiler not found: $csc" }
$redist = Join-Path $SolidWorksFolder 'api\redist'
$interop = @('SolidWorks.Interop.sldworks.dll', 'SolidWorks.Interop.swconst.dll') | ForEach-Object { Join-Path $redist $_ }
foreach ($r in $interop) {
    if (-not (Test-Path -LiteralPath $r)) { throw "SOLIDWORKS interop assembly not found: $r (set -SolidWorksFolder)" }
}
$init = Get-Content -LiteralPath (Join-Path $root 'src\solidseas\__init__.py') -Raw
if ($init -notmatch '(?m)^__version__ = "(\d+\.\d+\.\d+)"') { throw 'no __version__ in src\solidseas\__init__.py' }
$version = $Matches[1]
$sources = @(Get-ChildItem -LiteralPath (Join-Path $root 'src\solidseas\swapi\SwBridge') -Filter '*.cs' | Sort-Object Name | ForEach-Object { $_.FullName })
New-Item -ItemType Directory -Force -Path $OutputFolder | Out-Null
$exe = Join-Path (Resolve-Path -LiteralPath $OutputFolder) 'SolidSeas.SwBridge.exe'

$stamp = Join-Path ([System.IO.Path]::GetTempPath()) ("swbridge-version-{0}.cs" -f [guid]::NewGuid().ToString('N'))
@(
    '[assembly: System.Reflection.AssemblyTitle("SolidSeas CAD Bridge")]',
    '[assembly: System.Reflection.AssemblyProduct("SolidSeas")]',
    "[assembly: System.Reflection.AssemblyVersion(""$version.0"")]",
    "[assembly: System.Reflection.AssemblyFileVersion(""$version.0"")]",
    "[assembly: System.Reflection.AssemblyInformationalVersion(""$version"")]"
) | Set-Content -LiteralPath $stamp -Encoding UTF8
try {
    $arguments = @('/nologo', '/target:exe', '/platform:anycpu', '/optimize+', '/langversion:5', '/warnaserror+', "/out:$exe")
    $arguments += $interop | ForEach-Object { "/r:$_" }
    $arguments += @('/r:System.Web.Extensions.dll')
    $arguments += $sources
    $arguments += $stamp
    & $csc @arguments
    if ($LASTEXITCODE -ne 0) { throw "csc failed with exit code $LASTEXITCODE" }
}
finally {
    Remove-Item -LiteralPath $stamp -ErrorAction SilentlyContinue
}
"Built {0} (SolidSeas {1})" -f $exe, $version
