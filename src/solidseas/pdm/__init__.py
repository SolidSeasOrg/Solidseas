"""SolidSeas' PDM: a library folder's history, check-ins and restores (provisional,
``docs/PDM.md``).

```python
from solidseas import pdm

vault = pdm.init("D:/CAD")                   # make D:/CAD a library (writes only D:/CAD/.solidseas)
vault = pdm.open("D:/CAD/Jobs/1042")         # the library that holds a path
st = vault.status()                          # new, changed and gone files
vault.checkin(["D:/CAD/Jobs/1042"], "sent for quote", revision="A")
vault.scan()                                 # store every changed file, no note
vault.log("D:/CAD/Jobs/1042/bracket.sldprt") # versions newest first, with check-in notes
vault.restore("D:/CAD/Jobs/1042/bracket.sldprt", "v2", as_name="bracket v2.sldprt")
```

The vault writes only its own ``.solidseas`` folder in the library and the file a
restore puts back, never through a link (``docs/PDM.md`` 7).
"""

from __future__ import annotations

from .checkins import Checkin, CheckinFile, parse_checkin
from .settings import Section, Settings
from .vault import (
    CheckinResult,
    FileState,
    Project,
    SectionInfo,
    Status,
    Vault,
    VaultStore,
    find_library,
    init,
    open_vault,
)

open = open_vault  # noqa: A001 (pdm.open, as the design names it)

__all__ = [
    "Checkin",
    "CheckinFile",
    "CheckinResult",
    "FileState",
    "Project",
    "Section",
    "SectionInfo",
    "Settings",
    "Status",
    "Vault",
    "VaultStore",
    "find_library",
    "init",
    "open",
    "open_vault",
    "parse_checkin",
]
