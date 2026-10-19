# Installing SolidSeas

SolidSeas comes two ways: SolidSeas Viewer, the desktop app for Windows, and the
`solidseas` Python library with its command line. This page covers both. To
build the executable or the installer yourself, see [Building SolidSeas](building.md).

## SolidSeas Viewer on Windows

Download the installer from https://solidseas.app/download/windows, or take
`SolidSeas-Setup-<version>.exe` from the
[GitHub Releases](https://github.com/SolidSeas/SolidSeas/releases)
page. Each release carries the installer with its SHA-256 in a `.sha256` file
beside it, and the same installer named `SolidSeas-Setup.exe`, so a link to
the latest release's `SolidSeas-Setup.exe` always gets the newest version. GitHub Releases also has the single-file `SolidSeasViewer.exe`,
which runs without installing anything: look for it among a release's files.

What the installer does:

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
