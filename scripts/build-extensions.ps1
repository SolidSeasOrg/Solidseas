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
  occt        solidseas-occt.exe, the OCCT backend's helper (src\solidseas_app\extensions\occt_helper.py
              built by PyInstaller as a one-folder console program) with OCP, the Python bindings
              of Open CASCADE Technology, from the cadquery-ocp-novtk wheel that
              requirements\occt-helper.txt pins by its SHA-256. Built only when -Only names it.
              The package is refused when the wheel carries a DLL that packaging\occt\libraries.tsv
              does not name with its licence, or when the helper it built does not start and name
              its Open CASCADE. Open CASCADE's LGPL 2.1 and its exception, OCP's Apache License,
              the licences of the wheel's other libraries and -OcctSource, where the exact source
              of that Open CASCADE, OCP and those libraries is, are carried as its notices.

The SOLIDWORKS, video and OCCT packages also carry their licence texts as files, in a
licenses folder inside the package (THIRD_PARTY_NOTICES.txt says what each package holds).

Then it writes src\solidseas_app\extensions\accepted.json from the packages built, so the
viewer built next accepts these packages and no others, and dist\extensions\SHA256SUMS.txt.
scripts\build-viewer.ps1 -WithExtensions runs this before it builds the viewer.

.PARAMETER Venv
The virtual environment to build with, for example .venv. It needs PyInstaller (the "build"
extra of pyproject.toml).

.PARAMETER Only
The extensions to build: cad-bridge, video, solidcraft and occt. The default is the first
three; the OCCT package is built only when named, until its first Windows build is checked.

.PARAMETER FfmpegFolder
The folder holding an LGPL ffmpeg.exe and its licence files, for the video package.

.PARAMETER FfmpegSource
For the video package: where the exact source of that ffmpeg build is, for example the URL
of the source archive the release publishes beside the packages. The LGPL asks that it is
given with the program, so the package is not built without it.

.PARAMETER SolidCraftZip
SolidCraft's portable Windows zip of the pinned release, already downloaded.

.PARAMETER OcctSource
For the OCCT package: where the exact source of Open CASCADE Technology 7.9.3, OCP 7.9.3.1 and
the other libraries the OCP wheel carries is, for example the URL of the release that
publishes it beside the packages. The LGPL asks that it is given with the program, so the
package is not built without it.

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
    [string]$OcctSource = '',
    [string]$SolidWorksFolder = 'C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path (Resolve-Path $Venv) 'Scripts\python.exe'
if (-not (Test-Path $python)) { throw "No Python in that environment: $python" }
# The bridge's former id names it still.
$Only = @($Only | ForEach-Object { if ($_ -eq 'solidworks') { 'cad-bridge' } else { $_ } })
foreach ($id in $Only) {
    if ($id -notin @('cad-bridge', 'video', 'solidcraft', 'occt')) { throw "No extension package named $id (cad-bridge, video, solidcraft or occt)" }
}
if ('occt' -in $Only -and -not $OcctSource.Trim()) {
    throw 'The OCCT package needs -OcctSource, where the exact source of Open CASCADE, OCP and the libraries the OCP wheel carries is (the LGPL asks for it)'
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
            ('The exact source of this build: ' + $FfmpegSource.Trim()),
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
    if ('occt' -in $Only) {
        $folder = Join-Path $work 'occt'
        Reset-Folder $folder
        # OCP from its hash-pinned wheel, into a folder of its own and never into the build
        # environment, whose packages the viewer carries.
        $site = Join-Path $work 'occt-site'
        Reset-Folder $site
        $ErrorActionPreference = 'Continue'
        & $python -m pip install --require-hashes --no-deps --only-binary ':all:' --target $site -r (Join-Path $root 'requirements\occt-helper.txt')
        $code = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
        if ($code -ne 0) { throw 'OCP could not be installed from requirements\occt-helper.txt' }
        $libs = Join-Path $site 'cadquery_ocp_novtk.libs'
        if (-not (Test-Path -LiteralPath $libs)) { throw "The OCP wheel put no cadquery_ocp_novtk.libs folder in $site" }
        # Every DLL the wheel carries needs its licence named first (packaging\occt\libraries.tsv,
        # with the texts in licenses\OCP-third-party.txt). A delvewheel name ends in a hash.
        $patterns = @(Get-Content -LiteralPath (Join-Path $root 'packaging\occt\libraries.tsv') |
            Where-Object { $_ -and -not $_.StartsWith('#') } | ForEach-Object { ($_ -split "`t")[0] })
        foreach ($dll in Get-ChildItem -LiteralPath $libs -Filter '*.dll') {
            $stem = $dll.BaseName -replace '-[0-9a-f]{32}$', ''
            if (-not @($patterns | Where-Object { $stem -like $_ })) {
                throw "The OCP wheel carries $($dll.Name), which packaging\occt\libraries.tsv does not name; add it there with its licence text in licenses\OCP-third-party.txt"
            }
        }
        $dist = Join-Path $work 'occt-dist'
        Reset-Folder $dist
        # A one-folder program: a one-file one would unpack about 200 MB at every start.
        $ErrorActionPreference = 'Continue'
        & $python -m PyInstaller (Join-Path $root 'src\solidseas_app\extensions\occt_helper.py') `
            --onedir --console --name solidseas-occt --noconfirm --clean --paths $site `
            --hidden-import OCP --add-binary "$libs\*.dll;cadquery_ocp_novtk.libs" `
            --exclude-module solidseas --exclude-module solidseas_app --exclude-module tkinter `
            --distpath $dist --workpath (Join-Path $work 'pyinstaller-occt') --specpath (Join-Path $work 'pyinstaller-occt')
        $code = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
        if ($code -ne 0) { throw 'PyInstaller could not build solidseas-occt.exe' }
        Get-ChildItem -LiteralPath (Join-Path $dist 'solidseas-occt') | Move-Item -Destination $folder
        # PyInstaller collects the wheel's DLLs beside the program as well as where --add-binary
        # puts them; the helper loads the cadquery_ocp_novtk.libs copies, so drop the others.
        $libsIn = Join-Path $folder '_internal\cadquery_ocp_novtk.libs'
        Get-ChildItem -LiteralPath $libsIn -Filter '*.dll' | ForEach-Object {
            Remove-Item -LiteralPath (Join-Path $folder "_internal\$($_.Name)") -Force -ErrorAction SilentlyContinue
        }
        # The helper must start on its own and name the Open CASCADE it carries.
        $ErrorActionPreference = 'Continue'
        $ready = ('{"id": 1, "op": "shutdown"}' | & (Join-Path $folder 'solidseas-occt.exe') | Out-String)
        $code = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
        if ($code -ne 0 -or $ready -notmatch '"helper": "occt"' -or $ready -notmatch '"occt": "7\.9\.3"') {
            throw "solidseas-occt.exe did not start and name Open CASCADE 7.9.3: $ready"
        }
        $wheels = @(Get-ChildItem -LiteralPath $site -Directory -Filter '*.dist-info' | ForEach-Object { $_.Name -replace '\.dist-info$', '' })
        $about = Join-Path $work 'occt-build.txt'
        @(
            'The OCCT backend package of SolidSeas makes use of facilities provided by the Open CASCADE',
            'Technology software.',
            '',
            'solidseas-occt.exe is the OCCT backend''s helper, SolidSeas'' own code (Apache-2.0), built by',
            'PyInstaller with Python and OCP 7.9.3.1, the Python bindings of Open CASCADE Technology 7.9.3,',
            'from the cadquery-ocp-novtk 7.9.3.1.1 wheel, pinned by its SHA-256 in requirements\occt-helper.txt.',
            '',
            'Open CASCADE Technology (the TK*.dll libraries in _internal\cadquery_ocp_novtk.libs) is used under',
            'the GNU Lesser General Public License version 2.1 with the Open CASCADE exception version 1.0:',
            'LGPL-2.1.txt and OCCT_LGPL_EXCEPTION.txt in the licenses folder of this package. OCP',
            '(_internal\OCP) is used under the Apache License 2.0: OCP-LICENSE.txt. The other libraries the',
            'wheel carries, each under its own licence, are listed with their licence texts in',
            'OCP-third-party.txt.',
            '',
            'Each of these libraries is a separate file in this package''s folder and can be replaced by',
            'another build of it with the same interface, put in its place.',
            '',
            ('The exact source of Open CASCADE Technology 7.9.3, OCP 7.9.3.1 and the other libraries: ' + $OcctSource.Trim()),
            'Open CASCADE Technology: https://github.com/Open-Cascade-SAS/OCCT/releases/tag/V7_9_3',
            'OCP: https://github.com/CadQuery/OCP/releases/tag/7.9.3.1',
            '',
            ('The wheels this package was built from: ' + ($wheels -join ', '))
        ) | Set-Content -LiteralPath $about -Encoding UTF8
        $pythonLicence = Join-Path $work 'Python-LICENSE.txt'
        $ErrorActionPreference = 'Continue'
        $base = (& $python -c 'import sys; print(sys.base_prefix)' | Out-String).Trim()
        $ErrorActionPreference = 'Stop'
        # The helper is a PyInstaller program, so it carries Python and PyInstaller's bootloader.
        Copy-Item -LiteralPath (Join-Path $base 'LICENSE.txt') -Destination $pythonLicence -Force
        $licenceTexts = @('LGPL-2.1.txt', 'OCCT_LGPL_EXCEPTION.txt', 'OCP-LICENSE.txt', 'OCP-third-party.txt', 'PyInstaller-COPYING.txt') | ForEach-Object { Join-Path $root "licenses\$_" }
        Copy-Licences $folder ($ownLicences + $licenceTexts + @($about, $pythonLicence))
        $pointer = Join-Path $work 'occt-licences.txt'
        'The licence texts of everything in this package (SolidSeas, Python, PyInstaller, OCP, Open CASCADE Technology and the other libraries the OCP wheel carries) are in its licenses folder; THIRD_PARTY_NOTICES.txt there says what each one covers.' |
            Set-Content -LiteralPath $pointer -Encoding UTF8
        $notices = @($about) + (@('OCCT_LGPL_EXCEPTION.txt', 'LGPL-2.1.txt') | ForEach-Object { Join-Path $root "licenses\$_" }) + @($pointer)
        Invoke-Package 'occt' $folder $notices 3072
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
