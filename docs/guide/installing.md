# Installing SolidSeas

SolidSeas comes two ways: SolidSeas Viewer, the desktop app for Windows, and the
`solidseas` Python library with its command line. This page covers both. To
build the executable or the installer yourself, see [Building SolidSeas](building.md).

## SolidSeas Viewer on Windows

Download the installer from https://solidseas.app/download/windows, or take
`SolidSeas-Setup-<version>.exe` from the
[GitHub Releases](https://github.com/SolidSeasOrg/Solidseas/releases)
page. Each release carries the installer with its SHA-256 in a `.sha256` file
beside it, and the same installer named `SolidSeas-Setup.exe`, so a link to
the latest release's `SolidSeas-Setup.exe` always gets the newest version.
GitHub Releases also has the single-file `SolidSeasViewer.exe`, which runs
without installing anything: look for it among a release's files. Each release
also has `SHA256SUMS.txt`, one list of the SHA-256 of every file you can
download from it.

### Check your download first

The installer and `SolidSeasViewer.exe` are not code signed yet, so Windows
cannot tell you who made them. Before you run one, check that it is exactly the
file the release published. The SHA-256 is a long code worked out from the
file's contents: any change to the file gives a different code.

1. Open the Start menu, type PowerShell and open Windows PowerShell.
2. Type `Get-FileHash` and a space, drag the downloaded file into the
   PowerShell window, and press Enter.
3. Open `SHA256SUMS.txt` from the same release page and find the line that
   ends with your file's name. The long code at the start of that line must be
   the same as the Hash that PowerShell shows. Capital and small letters do not
   matter.

If the codes differ, do not run the file: delete it and download it again from
the releases page.

### When Windows SmartScreen warns you

The first time you run the installer or `SolidSeasViewer.exe`, Windows may
show a blue window titled "Windows protected your PC", saying that Microsoft
Defender SmartScreen prevented an unrecognized app from starting. It shows
this for programs that are not signed and not yet widely downloaded; it does
not mean anything harmful was found. Once you have checked the file as above:

1. Click More info. The window then shows the file's name and "Unknown
   publisher".
2. Check that the name is the file you downloaded, then click Run anyway.

Windows remembers the choice for that file. Your browser may also say the file
is not commonly downloaded and ask whether to keep it; choose to keep it only
after it came from the releases page or https://solidseas.app.

On a PC where Smart App Control is turned on (in Windows Security, under App &
browser control), Windows blocks programs that are not signed and offers no Run
anyway. SolidSeas cannot be installed there until a signed release is
published, so use another PC, or ask whoever looks after that PC.

### What the installer does

- It installs the one-folder build of SolidSeas Viewer for you alone by
  default, in `%LOCALAPPDATA%\Programs\SolidSeas`, with no administrator
  rights. An administrator can choose to install it for every user of the PC
  instead.
- It adds a Start menu entry and, if you ask, a desktop shortcut.
- It adds no file associations, services or firewall rules.
- Installing a newer version over an older one closes the viewer if it is
  running and keeps your settings.

To remove it, use Settings > Apps in Windows. Uninstalling removes the
program's files and leaves your settings (`%APPDATA%\SolidSeas`) and caches
alone.

The single-file `SolidSeasViewer.exe` (about 25 MB, no console window) unpacks
itself into a temporary folder each time it starts. The installed one-folder
form starts faster, and its Qt and Qt for Python libraries can be replaced in
place, as `THIRD_PARTY_NOTICES.txt` section 2.2 explains.

## Extension packages

Some features, such as video export and the CAD Bridge, come as extension
packages: zip files attached to each release beside the installer. Download
the ones you want from the same release as your SolidSeas Viewer, open Tools >
Extensions, choose Add from file, pick the zip and switch the extension on.
SolidSeas accepts only the packages of its own release, so after you upgrade,
download the packages again from the new release. Get extensions on that page
opens the releases page for you. When the installer carries packages, they are
already listed there, switched off. The OCCT backend's package is not offered
yet.

## The library and command line, from source

The library needs Python 3.11 or newer, on Linux or Windows. SOLIDWORKS is not
needed. SolidSeas is not on PyPI yet, so install it from a checkout:

```bash
python -m pip install /path/to/SolidSeas
```

That gives you the `solidseas` command and the `solidseas` package. See
[The command line](command-line.md) and [The Python library](python-library.md)
for what to do next.

## The viewer, from source

From a checkout, with PySide6 installed through the `app` extra:

```bash
pip install -e ".[app]"
python -m solidseas_app [FOLDER]
```

`pyproject.toml` lists the other extras, such as `image` for Pillow. For a
development setup with the tests and the linter, see
[Building SolidSeas](building.md).

## Where SolidSeas keeps its files

| What | Where |
|---|---|
| Viewer settings | `%APPDATA%\SolidSeas\Viewer.ini` |
| AI assistant settings (never the key) | `AI.json`, beside `Viewer.ini` |
| AI provider key | Windows Credential Manager |
| Folder indexes | `%LOCALAPPDATA%\SolidSeas\catalogs`, in your cache folder |
| 3D print files that cannot go next to the model | a `SolidSeas Print` folder in the system's temporary folder |

SolidSeas never keeps settings or indexes next to your files.
