# SolidSeas user guide

SolidSeas reads, previews and manages SOLIDWORKS files, with or without
SOLIDWORKS. It ships as SolidSeas Viewer, a desktop app for Windows, and as the
`solidseas` Python library with its command line and REST service. This guide
explains how to install and use both. The project's website is
https://solidseas.app.

## Getting started

- [Installing SolidSeas](installing.md): the Windows installer, the single-file
  executable, and the library from source.

## Using the viewer

- [The viewer](viewer.md): the window, opening folders, the file list and its
  quick filter, the details tabs, the preview, opening a component's file and
  opening a file in its own program.
- [Every 3D format](formats.md): STEP, Parasolid, Alibre Design, 3MF, STL and
  the other formats the viewer lists, and what it reads from each.
- [Where Used and bills of materials](where-used-and-bom.md): the folder index,
  which assemblies and drawings use a document, and BOMs.
- [3D Print and STEP export](3d-print.md): sending a part or assembly to your
  slicer, where the file goes and what it is called, and STEP for other CAD
  systems.
- [Drawings](drawings.md): making, editing and releasing drawings of parts.
- [Settings and the 3D view](settings.md): the Settings window, folder indexes,
  the 3D view, exploding, picking and transparency, mouse and keyboard
  controls, the view cube and rotation.
- [The modeling assistant](assistant.md): drafting SOLIDWORKS changes with an AI
  model, running them, and the machine policy with which an administrator
  restricts SolidSeas on a PC.

## Using SolidSeas from another system

- [The command line and the REST service](command-line.md), including
  [a file's versions](command-line.md#a-files-versions) from Git or from snapshots.
- [The Python library](python-library.md).

## Working on SolidSeas

- [Building SolidSeas](building.md): a development checkout, the checks, the
  executable, the installer, the lock file, the self-test and the wiki sync.

## Where the project stands

The library is ready for integrations: Phase 0 (reading the SOLIDWORKS format
without SOLIDWORKS) and Phase 1 (the Python API, the command line and the local
REST service) are built, and from 0.2.0 their public names, JSON, exit codes and
routes change only under the stability policy in [API.md](../API.md) section 9.

- **Stable:** the library's public API, its command line and the REST service,
  since 0.2.0, apart from what API.md marks provisional.
- **Preview:** SolidSeas Viewer, the desktop app.
- **Experimental:** drawings and extensions, which may still change from one
  release to the next (see [Experimental features](viewer.md#experimental-features)).

[ROADMAP.md](../ROADMAP.md) has the phases and [ARCHITECTURE.md](../ARCHITECTURE.md)
how it fits together. [DRAWINGS.md](../DRAWINGS.md) specifies drawings made from
3D parts (a SolidSeas drawing file, a PDF and a DXF), now provisional in the
command line and the viewer ([docs/drawings](../drawings/README.md)),
[VERSIONS.md](../VERSIONS.md) a file's versions and what changed between them, and
[OCCT.md](../OCCT.md) records how SolidSeas uses Open CASCADE.

## Reference documents

| Document | Covers |
|---|---|
| [API.md](../API.md) | the library, the command line and the REST service, with recipes |
| [ARCHITECTURE.md](../ARCHITECTURE.md) | module boundaries and how the pieces fit |
| [DRAWINGS.md](../DRAWINGS.md) | the drawings specification |
| [EXTENSIONS.md](../EXTENSIONS.md) | extension packages for the viewer |
| [MCP.md](../MCP.md) | SolidSeas as an MCP server for Claude Desktop, Claude Code and other chat clients |
| [ASSISTANT.md](../ASSISTANT.md) | the modeling assistant's design and rules |
| [FORMAT.md](../FORMAT.md) | the byte-level specification of the SOLIDWORKS file format |
| [GRIDFINITY.md](../GRIDFINITY.md) | Gridfinity bins made from a photo of your tools |
| [SECURITY_REVIEW.md](../SECURITY_REVIEW.md) | the security review, for whoever approves SolidSeas on a managed PC or server |
