"""Exceptions raised by the SOLIDWORKS format readers.

Every error raised by :mod:`solidseas.formats.solidworks` derives from
:class:`SldError`, so a caller that only wants "this file could not be read"
catches that one class. ``LockedFileError`` also derives from ``OSError``.

The classes live in :mod:`solidseas.errors`, where they also derive from
:class:`~solidseas.errors.SolidSeasError` and carry a stable ``code``. They are
re-exported here under the names and bases they had in 0.1.
"""

from ...errors import (
    FileTooLargeError,
    LockedFileError,
    ParasolidError,
    ReaderWarning,
    SldError,
    SldFormatError,
    SldIntegrityError,
    SldLimitError,
    StreamNotFoundError,
    UnknownFormatError,
)

__all__ = [
    "FileTooLargeError",
    "LockedFileError",
    "ParasolidError",
    "ReaderWarning",
    "SldError",
    "SldFormatError",
    "SldIntegrityError",
    "SldLimitError",
    "StreamNotFoundError",
    "UnknownFormatError",
]
