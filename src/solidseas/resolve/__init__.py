"""Reference resolution: which file on this machine each stored reference names.

``resolve_references(doc, roots)`` returns a :class:`Resolution` with one
:class:`ResolvedReference` per referenced file key (``docs/API.md`` C7). The
``references`` JSON kind carries the same results when resolution is
requested (``solidseas references FILE --resolve``). ``docs/API.md`` section
3.10 describes the rules and the evidence behind them.

Modules:

* :mod:`.names`: stored Windows paths, name folding and path maps, as strings;
* :mod:`.gateway`: the only module that touches the filesystem;
* :mod:`.index`: the folder index of a root, filled by the gateway;
* :mod:`.identity`: creation times, compared;
* :mod:`.core`: the rules.

The Python API of this package is provisional until 0.2.0.
"""

from .core import (
    CONFIDENCE,
    DOCUMENT_ROOT_ID,
    DOCUMENTED_RULES,
    POSITIONAL_RULES,
    RULES,
    SEARCHES,
    STATUSES,
    Candidate,
    IndexCache,
    InputFile,
    Location,
    Resolution,
    ResolutionInput,
    ResolvedReference,
    RootState,
    resolve_references,
)
from .gateway import Gateway
from .names import fold, parse_path_map, parse_stored

__all__ = [
    "CONFIDENCE",
    "DOCUMENT_ROOT_ID",
    "DOCUMENTED_RULES",
    "POSITIONAL_RULES",
    "RULES",
    "SEARCHES",
    "STATUSES",
    "Candidate",
    "Gateway",
    "IndexCache",
    "InputFile",
    "Location",
    "Resolution",
    "ResolutionInput",
    "ResolvedReference",
    "RootState",
    "fold",
    "parse_path_map",
    "parse_stored",
    "resolve_references",
]
