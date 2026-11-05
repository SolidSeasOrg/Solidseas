# SolidSeas

Read, preview and manage SOLIDWORKS files, with or without SOLIDWORKS.

> SolidSeas is an independent project. It is not affiliated with, endorsed by,
> sponsored by or connected to Dassault Systèmes, Dassault Systèmes SolidWorks
> Corporation or Siemens Industry Software Inc. SOLIDWORKS, eDrawings,
> 3DEXPERIENCE and ACIS are trademarks or registered trademarks of Dassault
> Systèmes or its subsidiaries in the US and other countries. Parasolid is a
> trademark or registered trademark of Siemens Industry Software Inc. or its
> subsidiaries or affiliates. Other product names are trademarks of their
> owners. They are used here only to name the files and programs SolidSeas
> works with.

SolidSeas is a Python toolkit that ships two ways:

- **A library** that ERP, invoicing and project-tracking systems import to show
  previews and pull metadata from `.sldprt` and `.sldasm` files. It needs no
  SOLIDWORKS installation and runs on Linux and Windows.
- **A desktop app** that manages a folder of CAD files: project structure,
  previews, properties, bills of materials, conversion to Parasolid, STEP, STL
  and 3MF, a one-click 3D Print button for your slicer, and a modeling
  assistant that works alongside your own SOLIDWORKS installation. A file's
  versions are on the command line for now (`solidseas history`, `snapshot`
  and `diff`).

Website: https://solidseas.app

## Status

- **Stable:** the library's public API, its command line and the REST service,
  since 0.2.0, apart from what [docs/API.md](https://github.com/SolidSeas/SolidSeas/blob/main/docs/API.md) marks provisional.
  Their names, JSON, exit codes and routes change only under its stability
  policy (section 9).
- **Preview:** SolidSeas Viewer, the desktop app.
- **Experimental:** drawings and extensions, which may still change from one
  release to the next.
- **Provisional:** writing native `.sldprt` files without SOLIDWORKS.
  `solidseas sldprt` writes a part from a SolidCraft design, a SolidSeas design
  file or a recorded CadQuery model: corner rectangles on the Front Plane
  extruded blind, one round hole through a single box, and fillets on the box's
  edges along its depth and on the hole's far edge. Parts without fillets open
  in SOLIDWORKS 2024 with their feature tree; parts with a fillet have not been
  opened in SOLIDWORKS yet. It is not in the viewer.
  [The command line](https://github.com/SolidSeas/SolidSeas/blob/main/docs/guide/command-line.md#solidworks-parts-from-a-design)
  says what it writes, and
  [docs/NATIVE_SLDPRT_WRITER.md](https://github.com/SolidSeas/SolidSeas/blob/main/docs/NATIVE_SLDPRT_WRITER.md) has the research.

[docs/ROADMAP.md](https://github.com/SolidSeas/SolidSeas/blob/main/docs/ROADMAP.md) has the phases.

## Install

**Windows:** download the installer from https://solidseas.app/download/windows,
or `SolidSeas-Setup-<version>.exe` from
[GitHub Releases](https://github.com/SolidSeas/SolidSeas/releases).
It installs for you alone by default, with no administrator rights, and keeps
your settings when you upgrade. GitHub Releases also has the single-file
`SolidSeasViewer.exe`, which runs without installing.

**Python, from source:** Python 3.11 or newer, on Linux or Windows; SOLIDWORKS
is not needed. SolidSeas is not on PyPI yet, so install it from a checkout:

```bash
python -m pip install /path/to/SolidSeas
pip install -e ".[app]"          # add the viewer (PySide6) to a checkout
```

[Installing SolidSeas](https://github.com/SolidSeas/SolidSeas/blob/main/docs/guide/installing.md) has the details.

## Quick start

Open a folder in the viewer, from the Start menu or from a checkout:

```bash
python -m solidseas_app D:\Jobs\Example
```

From the command line (every command prints JSON with `--json`):

```bash
solidseas list D:\Jobs\Example --include properties --json
solidseas bom D:\Jobs\Example\frame.SLDASM --type indented --format csv -o frame.csv
solidseas export D:\Jobs\Example\bracket.SLDPRT --format step -o bracket.step
solidseas serve --root jobs=D:\Jobs      # the REST service, on 127.0.0.1
```

From Python:

```python
from solidseas import open_document

with open_document("D:/Jobs/Example/frame.SLDASM") as doc:
    print(doc.doc_type, doc.active_configuration, doc.property_values())
    bom = doc.bom(bom_type="indented")       # its bill of materials, as SOLIDWORKS numbers it
```

## Experimental features

Some features of the viewer are on but not finished, and say so with a small
Experimental or In development tag beside their menu entries. Their results may
be incomplete or wrong, and they may change between versions. Experimental:
drawings (check every drawing before you use it; until one is released its PDF
and DXF carry the PRELIMINARY stamp), the modeling assistant, and the
Gridfinity, video export, SolidCraft and CAD Bridge extensions. In
development: the OCCT backend extension. Please report problems at
https://github.com/SolidSeas/SolidSeas/issues.
[The viewer](https://github.com/SolidSeas/SolidSeas/blob/main/docs/guide/viewer.md#experimental-features) has the full list.

## Documentation

The [user guide](https://github.com/SolidSeas/SolidSeas/blob/main/docs/guide/index.md):

- [Installing](https://github.com/SolidSeas/SolidSeas/blob/main/docs/guide/installing.md) and [the viewer](https://github.com/SolidSeas/SolidSeas/blob/main/docs/guide/viewer.md)
- [Every 3D format](https://github.com/SolidSeas/SolidSeas/blob/main/docs/guide/formats.md),
  [Where Used and BOMs](https://github.com/SolidSeas/SolidSeas/blob/main/docs/guide/where-used-and-bom.md),
  [3D Print and STEP export](https://github.com/SolidSeas/SolidSeas/blob/main/docs/guide/3d-print.md),
  [Drawings](https://github.com/SolidSeas/SolidSeas/blob/main/docs/guide/drawings.md)
- [Settings and the 3D view](https://github.com/SolidSeas/SolidSeas/blob/main/docs/guide/settings.md),
  [the modeling assistant](https://github.com/SolidSeas/SolidSeas/blob/main/docs/guide/assistant.md)
- [The command line and REST service](https://github.com/SolidSeas/SolidSeas/blob/main/docs/guide/command-line.md),
  [the Python library](https://github.com/SolidSeas/SolidSeas/blob/main/docs/guide/python-library.md)
- [Building SolidSeas](https://github.com/SolidSeas/SolidSeas/blob/main/docs/guide/building.md)

Reference:

| Document | Covers |
|---|---|
| [API.md](https://github.com/SolidSeas/SolidSeas/blob/main/docs/API.md) | the library, the command line and the REST service |
| [ARCHITECTURE.md](https://github.com/SolidSeas/SolidSeas/blob/main/docs/ARCHITECTURE.md) | how the pieces fit together |
| [DRAWINGS.md](https://github.com/SolidSeas/SolidSeas/blob/main/docs/DRAWINGS.md) | the drawings specification |
| [EXTENSIONS.md](https://github.com/SolidSeas/SolidSeas/blob/main/docs/EXTENSIONS.md) | extension packages |
| [MCP.md](https://github.com/SolidSeas/SolidSeas/blob/main/docs/MCP.md) | SolidSeas as an MCP server |
| [ASSISTANT.md](https://github.com/SolidSeas/SolidSeas/blob/main/docs/ASSISTANT.md) | the modeling assistant's design |
| [FORMAT.md](https://github.com/SolidSeas/SolidSeas/blob/main/docs/FORMAT.md) | the SOLIDWORKS file format |
| [NATIVE_SLDPRT_WRITER.md](https://github.com/SolidSeas/SolidSeas/blob/main/docs/NATIVE_SLDPRT_WRITER.md) | research: writing native parts without SOLIDWORKS |
| [GRIDFINITY.md](https://github.com/SolidSeas/SolidSeas/blob/main/docs/GRIDFINITY.md) | Gridfinity bins from photos |
| [SECURITY_REVIEW.md](https://github.com/SolidSeas/SolidSeas/blob/main/docs/SECURITY_REVIEW.md) | the security review |

## Contributing

Want to help? See [CONTRIBUTING.md](https://github.com/SolidSeas/SolidSeas/blob/main/CONTRIBUTING.md), and read
[AGENTS.md](https://github.com/SolidSeas/SolidSeas/blob/main/AGENTS.md) before your first change. To report a security problem,
see [SECURITY.md](https://github.com/SolidSeas/SolidSeas/blob/main/SECURITY.md). What changed in each release is in
[CHANGELOG.md](https://github.com/SolidSeas/SolidSeas/blob/main/CHANGELOG.md).

## Licence

SolidSeas is licensed under the Apache License 2.0. See [LICENSE](https://github.com/SolidSeas/SolidSeas/blob/main/LICENSE) and
[NOTICE](https://github.com/SolidSeas/SolidSeas/blob/main/NOTICE).

SolidSeas Viewer and the extension packages also carry third-party software
under their own licences, among them Qt and Qt for Python under the GNU LGPL
version 3 and, in the video package, an LGPL build of FFmpeg.
[THIRD_PARTY_NOTICES.txt](https://github.com/SolidSeas/SolidSeas/blob/main/THIRD_PARTY_NOTICES.txt) lists each one, what its
licence asks and where its source is, and how to run the viewer with your own
build of Qt. The licence texts are in `licenses/`, and the viewer shows them
under Help > Licences.
