"""What the assistant window asks of a live SOLIDWORKS: the sessions it may attach to and
their documents, a part's snapshot for the model summary, the safety copy and undo
entry around an approved script, and the script's named operations.

:class:`Sessions` is the interface. :class:`.live_sessions.BridgeSessions` implements
it over the bridge's live operations (``docs/ASSISTANT.md``, "Attaching to a live
session"); where the bridge cannot run, :class:`NoSessions` answers with the reason, and
the tests use a fake. The window calls every method from a worker thread, never from the
Qt thread, because any of them may wait for SOLIDWORKS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from solidseas.ai.context import PartSnapshot


@dataclass(frozen=True)
class LiveDocument:
    """A document open in a session: ``title`` and ``path`` are shown to the person only,
    never sent to a model; ``kind`` is ``part``, ``assembly`` or ``drawing``."""

    key: str  # the session's own name for it, which the app passes back
    title: str
    kind: str
    path: str = ""
    active: bool = False  # the session's active document when it was listed


@dataclass(frozen=True)
class LiveSession:
    """One SOLIDWORKS process in the person's Windows session."""

    pid: int
    version: str
    documents: tuple[LiveDocument, ...] = ()
    note: str = ""  # why it cannot be used, when it cannot (one started as administrator)


@dataclass(frozen=True)
class SessionList:
    sessions: tuple[LiveSession, ...] = ()
    why_none: str = ""  # said when there are none
    extra: dict = field(default_factory=dict)


class Sessions(Protocol):
    def list(self) -> SessionList:
        """The SOLIDWORKS sessions this person may attach to, with their documents."""

    def snapshot(self, session: LiveSession, document: LiveDocument) -> PartSnapshot:
        """The part's structural snapshot (``solidseas.ai.context``)."""

    def begin_script(self, session: LiveSession, document: LiveDocument) -> str:
        """Before an approved script touches the document: write the safety copy and open
        the one undo entry "SolidSeas script". Returns where the safety copy is."""

    def end_script(self, session: LiveSession, document: LiveDocument) -> None:
        """Close the undo entry, whether the script finished, failed or was stopped."""

    def call(self, session: LiveSession, document: LiveDocument, op: str, args: dict) -> Any:
        """One named operation of a script, on the document."""


LIVE_LATER = (
    "Attaching to a running SOLIDWORKS needs the bridge's live operations, which come in a later "
    "stage. The console still shows a draft, and runs code that does not use SOLIDWORKS."
)


class NoSessions:
    """No live SOLIDWORKS can be reached yet: every list is empty, with the reason."""

    def __init__(self, why: str = LIVE_LATER) -> None:
        self.why = why

    def list(self) -> SessionList:
        return SessionList((), self.why)

    def snapshot(self, session, document) -> PartSnapshot:
        raise RuntimeError(self.why)

    def begin_script(self, session, document) -> str:
        raise RuntimeError(self.why)

    def end_script(self, session, document) -> None:
        return None

    def call(self, session, document, op, args) -> Any:
        raise RuntimeError(self.why)


__all__ = ["LIVE_LATER", "LiveDocument", "LiveSession", "NoSessions", "SessionList", "Sessions"]
