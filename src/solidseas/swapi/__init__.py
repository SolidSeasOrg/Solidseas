"""SOLIDWORKS automation through SolidSeas' own SOLIDWORKS instance (Windows only).

Every call into SOLIDWORKS goes through ``SolidSeas.SwBridge.exe``, a small C#
program built from the sources in ``SwBridge/`` (``scripts/build-bridge.ps1``
or ``python -m solidseas.swapi build``). :mod:`solidseas.swapi.bridge` starts
it and keeps every request's timeout; :mod:`solidseas.swapi.batch` converts
documents on it (``python -m solidseas.swapi convert``). ``README.md`` here has
the protocol, the operations, the safety rules and what has been checked.
Importing this package loads nothing from SOLIDWORKS.
"""

from pathlib import Path

HERE = Path(__file__).resolve().parent
BRIDGE_SOURCE = HERE / "SwBridge"
