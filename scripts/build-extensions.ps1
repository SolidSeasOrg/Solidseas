<#
.SYNOPSIS
Build the extension packages, dist\extensions\<id>-<version>.zip, and the list of them the
viewer accepts.

.DESCRIPTION
Each package is a folder built under build\extensions\<id> and zipped by
"python -m solidseas_app.extensions.package build" (docs\EXTENSIONS.md section 8):

  cad-bridge  the CAD Bridge, SolidSeas.SwBridge.exe, from scripts\build-bridge.ps1
              (needs SOLIDWORKS installed for its interop assemblies, which are not copied),
              with SolidSeas' LICENSE and NOTICE. Its id was solidworks
              before it was renamed; -Only still takes that name, and a solidworks-*.zip that
              an earlier build left in dist\extensions is removed.
  video       solidseas-video.exe, the video helper (src\solidseas_app\extensions\video_helper.py
              built by PyInstaller as one console program), beside the ffmpeg.exe in
              -FfmpegFolder. Use an LGPL build of ffmpeg: the package is refused when
              "ffmpeg -version" shows --enable-gpl or --enable-nonfree. The licence files in that
              folder, the output of "ffmpeg -version" (its configure flags) and -FfmpegSource,
              where the exact source of that build is, are carried as the package's notices.
  solidcraft  solidcraft-cli.exe from SolidCraft's portable Windows zip (MIT or Apache-2.0),
              the release pinned below and checked by its SHA-256, with its licence files.
              -SolidCraftZip names a copy already downloaded; otherwise it is downloaded.

The SOLIDWORKS and video packages also carry their licence texts as files, in a licenses
folder inside the package (THIRD_PARTY_NOTICES.txt says what each package holds).

Then it writes src\solidseas_app\extensions\accepted.json from the packages built, so the
viewer built next accepts these packages and no others, and dist\extensions\SHA256SUMS.txt.
scripts\build-viewer.ps1 -WithExtensions runs this before it builds the viewer.

.PARAMETER Venv
The virtual environment to build with, for example .venv. It needs PyInstaller (the "build"
extra of pyproject.toml).

.PARAMETER Only
The extensions to build: cad-bridge, video, solidcraft, or all three (the default).

.PARAMETER FfmpegFolder
The folder holding an LGPL ffmpeg.exe and its licence files, for the video package.

.PARAMETER FfmpegSource
For the video package: where the exact source of that ffmpeg build is, for example the URL
of the source archive the release publishes beside the packages. The LGPL asks that it is
given with the program, so the package is not built without it.

.PARAMETER SolidCraftZip
SolidCraft's portable Windows zip of the pinned release, already downloaded.

.PARAMETER SolidWorksFolder
The SOLIDWORKS installation folder, passed to scripts\build-bridge.ps1.

.EXAMPLE
scripts\build-extensions.ps1 -Venv .venv -FfmpegFolder C:\tools\ffmpeg-lgpl\bin -FfmpegSource https://example.org/ffmpeg-src.tar.xz
#>
param(
    [Parameter(Mandatory = $true)][string]$Venv,
    [string[]]$Only = @('cad-bridge', 'video', 'solidcraft'),
    [string]$FfmpegFolder = '',
    [string]$FfmpegSource = '',
    [string]$SolidCraftZip = '',
    [string]$SolidWorksFolder = 'C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path (Resolve-Path $Venv) 'Scripts\python.exe'
if (-not (Test-Path $python)) { throw "No Python in that environment: $python" }
# The bridge's former id names it still.
$Only = @($Only | ForEach-Object { if ($_ -eq 'solidworks') { 'cad-bridge' } else { $_ } })
foreach ($id in $Only) {
    if ($id -notin @('cad-bridge', 'video', 'solidcraft')) { throw "No extension package named $id (cad-bridge, video or solidcraft)" }
}
if ('video' -in $Only) {
    if (-not $FfmpegFolder -or -not (Test-Path -LiteralPath (Join-Path $FfmpegFolder 'ffmpeg.exe'))) {
        throw 'The video package needs -FfmpegFolder, a folder holding an LGPL ffmpeg.exe'
    }
    if (-not $FfmpegSource.Trim()) {
        throw 'The video package needs -FfmpegSource, where the exact source of that ffmpeg build is (the LGPL asks for it)'
    }
}

# The SolidCraft release a package is built from: its portable zip and that zip's SHA-256, as
# the release's SHA256SUMS.txt lists it. A new release is taken by changing these together.
$solidCraftVersion = '0.11.1'
$solidCraftSha256 = '6c5e285d3d6ee3bbdaa39de9019b5a36fd894c4a335f92de7193e1340996727d'
$solidCraftUrl = "https://github.com/bherbruck/solidcraft/releases/download/v$solidCraftVersion/solidcraft-$solidCraftVersion-windows-x64-portable.zip"
$solidCraftLicences = @('LICENSE-MIT', 'LICENSE-APACHE', 'NOTICE', 'THIRD-PARTY-LICENSES.txt')

$work = Join-Path $root 'build\extensions'
$out = Join-Path $root 'dist\extensions'
New-Item -ItemType Directory -Force -Path $out | Out-Null
# A bridge package from before the rename (solidworks-*.zip) would otherwise be listed as
# accepted and shipped beside the new one.
Get-ChildItem -LiteralPath $out -Filter 'solidworks-*.zip' | Remove-Item -Force
$env:PYTHONPATH = Join-Path $root 'src'

function Invoke-Package([string]$id, [string]$folder, [string[]]$notices, [int]$memoryMb = 2048) {
    # An earlier build's package of this extension goes first, or the list written below would
    # accept an old version beside the new one.
    Get-ChildItem -LiteralPath $out -Filter "${id}-*.zip" | Remove-Item -Force
    $arguments = @('-m', 'solidseas_app.extensions.package', 'build', '--id', $id, '--from', $folder, '--out', $out, '--memory-mb', $memoryMb)
    foreach ($n in $notices) { $arguments += @('--notice', $n) }
    $ErrorActionPreference = 'Continue'
    & $python @arguments
    $code = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($code -ne 0) { throw "The $id package was not built" }
}

function Reset-Folder([string]$path) {
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $path | Out-Null
}

function Copy-Licences([string]$folder, [string[]]$files) {
    # Each file, under its own name, into the package's licenses folder; a missing one stops the build.
    $target = Join-Path $folder 'licenses'
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    foreach ($f in $files) {
        if (-not (Test-Path -LiteralPath $f -PathType Leaf)) { throw "No licence file $f; the package is not built" }
        Copy-Item -LiteralPath $f -Destination $target
    }
}

# SolidSeas' own licence and notices, which every package of SolidSeas' own code carries.
$ownLicences = @('LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.txt') | ForEach-Object { Join-Path $root $_ }

Push-Location $root
try {
    if ('cad-bridge' -in $Only) {
        $folder = Join-Path $work 'cad-bridge'
        Reset-Folder $folder
        & (Join-Path $PSScriptRoot 'build-bridge.ps1') -OutputFolder $folder -SolidWorksFolder $SolidWorksFolder
        # The bridge is SolidSeas' own code alone, so its notices are SolidSeas' licence and NOTICE.
        Copy-Licences $folder $ownLicences
        Invoke-Package 'cad-bridge' $folder @((Join-Path $root 'NOTICE'), (Join-Path $root 'LICENSE'))
    }
    if ('video' -in $Only) {
        $folder = Join-Path $work 'video'
        Reset-Folder $folder
        # PyInstaller logs to standard error, so it is judged by its exit code alone.
        $ErrorActionPreference = 'Continue'
        & $python -m PyInstaller (Join-Path $root 'src\solidseas_app\extensions\video_helper.py') `
            --onefile --console --name solidseas-video --noconfirm --clean `
            --distpath $folder --workpath (Join-Path $work 'pyinstaller-video') --specpath (Join-Path $work 'pyinstaller-video')
        $code = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
        if ($code -ne 0) { throw 'PyInstaller could not build solidseas-video.exe' }
        Copy-Item -LiteralPath (Join-Path $FfmpegFolder 'ffmpeg.exe') -Destination $folder
        $ffmpegLicences = @(Get-ChildItem -LiteralPath $FfmpegFolder -File | Where-Object { $_.Name -match '^(LICEN[CS]E|COPYING|README)' } | ForEach-Object { $_.FullName })
        if (-not $ffmpegLicences) { throw "No licence file beside ffmpeg.exe in ${FfmpegFolder}: the package carries ffmpeg's notices" }
        # What the ffmpeg build is: its version and configure flags, which say its licence.
        $ErrorActionPreference = 'Continue'
        $ffmpegVersion = (& (Join-Path $folder 'ffmpeg.exe') -hide_banner -version 2>&1 | Out-String)
        $code = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
        if ($code -ne 0 -or $ffmpegVersion -notmatch '(?m)^configuration:') { throw "ffmpeg.exe in $FfmpegFolder did not report its configuration" }
        if ($ffmpegVersion -match '--enable-(gpl|nonfree)\b') { throw "ffmpeg.exe in $FfmpegFolder is not an LGPL build (--enable-gpl or --enable-nonfree); the package is not built" }
        $about = Join-Path $work 'ffmpeg-build.txt'
        @(
            'The ffmpeg.exe in this package is FFmpeg, used under the GNU Lesser General Public License',
            'version 2.1 or later (version 3 or later when the configuration below shows --enable-version3):',
            'LGPL-2.1.txt, or LGPL-3.0.txt and GPL-3.0.txt, in the licenses folder of this package.',
            'It is a separate program that the video helper starts; it can be replaced by any other build',
            'of FFmpeg with the same command line, put in its place in the package folder.',
            '',
            'The exact source of this build: ' + $FfmpegSource.Trim(),
            'FFmpeg itself: https://ffmpeg.org/download.html',
            '',
            'ffmpeg -version reports:',
            $ffmpegVersion.TrimEnd()
        ) | Set-Content -LiteralPath $about -Encoding UTF8
        $pythonLicence = Join-Path $work 'Python-LICENSE.txt'
        $ErrorActionPreference = 'Continue'
        $base = (& $python -c 'import sys; print(sys.base_prefix)' | Out-String).Trim()
        $ErrorActionPreference = 'Stop'
        # The helper is a PyInstaller program, so it carries Python and PyInstaller's bootloader.
        Copy-Item -LiteralPath (Join-Path $base 'LICENSE.txt') -Destination $pythonLicence
        $licenceTexts = @('LGPL-2.1.txt', 'LGPL-3.0.txt', 'GPL-3.0.txt', 'PyInstaller-COPYING.txt') | ForEach-Object { Join-Path $root "licenses\$_" }
        Copy-Licences $folder ($ownLicences + $licenceTexts + $ffmpegLicences + @($about, $pythonLicence))
        $pointer = Join-Path $work 'video-licences.txt'
        'The licence texts of everything in this package (SolidSeas, Python, PyInstaller and FFmpeg) are in its licenses folder; THIRD_PARTY_NOTICES.txt there says what each one covers.' |
            Set-Content -LiteralPath $pointer -Encoding UTF8
        Invoke-Package 'video' $folder ($ffmpegLicences + @($about, $pointer))
    }
    if ('solidcraft' -in $Only) {
        $folder = Join-Path $work 'solidcraft'
        Reset-Folder $folder
        $zip = $SolidCraftZip
        if (-not $zip) {
            $zip = Join-Path $work "solidcraft-$solidCraftVersion-windows-x64-portable.zip"
            Invoke-WebRequest -UseBasicParsing -Uri $solidCraftUrl -OutFile $zip
        }
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $zip).Hash.ToLower()
        if ($hash -ne $solidCraftSha256) { throw "$zip is not SolidCraft $solidCraftVersion's portable zip (SHA-256 $hash)" }
        $unpacked = Join-Path $work 'solidcraft-unpacked'
        Reset-Folder $unpacked
        Expand-Archive -LiteralPath $zip -DestinationPath $unpacked
        $top = Join-Path $unpacked "solidcraft-$solidCraftVersion-windows-x64-portable"
        foreach ($name in @('solidcraft-cli.exe') + $solidCraftLicences) {
            $file = Join-Path $top $name
            # A package without its licence texts must not be built (MIT, Apache-2.0 and the
            # third-party licences all travel with the program).
            if (-not (Test-Path -LiteralPath $file)) { throw "SolidCraft's zip has no $name; the package is not built" }
            Copy-Item -LiteralPath $file -Destination $folder
        }
        # The licence texts are notices on the Extensions page; the third-party list, 800 KB, is
        # a file of the package that the notice points to.
        $pointer = Join-Path $work 'solidcraft-third-party.txt'
        'The licences of the third-party code in solidcraft-cli.exe are in THIRD-PARTY-LICENSES.txt in this package.' |
            Set-Content -LiteralPath $pointer -Encoding UTF8
        $notices = @('NOTICE', 'LICENSE-MIT', 'LICENSE-APACHE' | ForEach-Object { Join-Path $folder $_ }) + @($pointer)
        Invoke-Package 'solidcraft' $folder $notices 4096
    }

    $zips = @(Get-ChildItem -LiteralPath $out -Filter '*.zip' | Sort-Object Name | ForEach-Object { $_.FullName })
    $accepted = Join-Path $root 'src\solidseas_app\extensions\accepted.json'
    $ErrorActionPreference = 'Continue'
    & $python -m solidseas_app.extensions.package accept @zips --out $accepted
    $code = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($code -ne 0) { throw 'accepted.json was not written' }
    $sums = foreach ($z in $zips) { '{0}  {1}' -f (Get-FileHash -Algorithm SHA256 -LiteralPath $z).Hash.ToLower(), (Split-Path -Leaf $z) }
    $sums | Set-Content -LiteralPath (Join-Path $out 'SHA256SUMS.txt') -Encoding ASCII
}
finally {
    $ErrorActionPreference = 'Stop'
    Pop-Location
}
"Built {0} package(s) in {1}; the viewer built next accepts them" -f $zips.Count, $out
