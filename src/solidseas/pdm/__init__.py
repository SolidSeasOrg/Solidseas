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
vault.library.add("D:/CAD/Jobs/1042/bolt.sldprt", description="M6 bolt")  # item SS-00001
vault.library.use("SS-00001", "D:/CAD/Jobs/1043")  # a copy in the project, and a link record
vault.library.updates()                      # copies behind their item, or edited since
vault.check("D:/CAD/Jobs/1043", fix=True)    # copy in what the project references from outside
```

The vault writes only its own ``.solidseas`` folder in the library, the file a restore
puts back and the library's copies, never through a link (``docs/PDM.md`` 7).
"""

from __future__ import annotations

from .checkins import Checkin, CheckinFile, parse_checkin
from .library import Item, ItemEdit, Library, Link, parse_edit, parse_item, parse_link
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
    "Item",
    "ItemEdit",
    "Library",
    "Link",
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
    "parse_edit",
    "parse_item",
    "parse_link",
]
