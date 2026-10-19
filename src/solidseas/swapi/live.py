"""The typed interface a Review mode script has to the person's open SOLIDWORKS document
(provisional).

A script the person approved runs in a child process of SolidSeas
(``solidseas_app.assistant.runner``), never in the app, and reaches SOLIDWORKS only
through this module: each function sends one named operation to the app, which checks
it against :data:`OPERATIONS` and forwards it to the bridge for the document the
person picked. The script never names a document, a path or a SOLIDWORKS object, and
nothing here imports win32com, comtypes or pythonnet. Outside a script run there is
no app to answer, and every function raises :class:`LiveUnavailableError`.

The queries read; the vocabulary operations (the same ones Automatic mode plans,
``solidseas.ai.prompts.OPERATIONS``) change the part, inside the one undo entry
"SolidSeas script" the app opens before the script runs::

    from solidseas.swapi import live

    info = live.document()
    for f in live.features():
        print(f["name"], f["type"])
    live.operation("fillet", edges=["E12"], radius={"value": 2, "unit": "mm"})
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from typing import Any

# Read-only queries: what each function sends, and the arguments it takes.
QUERIES = {
    "document_info": (),
    "list_features": ("limit",),
    "list_dimensions": ("limit",),
    "list_properties": (),
    "mass_properties": ("configuration",),
}
MAX_REQUEST_BYTES = 256 * 1024


class LiveError(RuntimeError):
    """SOLIDWORKS, the bridge or the app refused or failed an operation; ``code`` says
    which (``unknown_operation``, ``not_supported``, ``refused``, ``failed``...)."""

    def __init__(self, message: str, code: str = "failed") -> None:
        super().__init__(message)
        self.code = code


class LiveUnavailableError(LiveError):
    """No app is there to answer: the module is used outside a Review mode run."""

    def __init__(self) -> None:
        super().__init__(
            "solidseas.swapi.live works only inside a script SolidSeas runs for you", "unavailable"
        )


_lock = threading.Lock()
_transport: Callable[[str, dict], Any] | None = None


def _connect(transport: Callable[[str, dict], Any] | None) -> None:
    """Set how requests reach the app (the runner's child does this before the script
    runs; tests use it too). None disconnects."""
    global _transport
    with _lock:
        _transport = transport


def _request(op: str, args: dict) -> Any:
    with _lock:
        send = _transport
    if send is None:
        raise LiveUnavailableError()
    try:
        size = len(json.dumps(args, allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise LiveError(f"the arguments of {op} are not plain JSON values: {exc}", "refused") from None
    if size > MAX_REQUEST_BYTES:
        raise LiveError(f"the arguments of {op} are longer than {MAX_REQUEST_BYTES:,} bytes", "refused")
    return send(op, args)


# --------------------------------------------------------------------------- queries
def document() -> dict:
    """The open document: ``title``, ``type``, ``dirty``, ``active_configuration``,
    ``configurations`` and ``feature_count``."""
    return _request("document_info", {})


def features(limit: int = 10_000) -> list[dict]:
    """The features in tree order, each ``name``, ``type`` and ``id``."""
    return _request("list_features", {"limit": limit}).get("features", [])


def dimensions(limit: int = 10_000) -> list[dict]:
    """The dimensions, each ``name``, ``value`` (metres or radians) and ``feature``."""
    return _request("list_dimensions", {"limit": limit}).get("dimensions", [])


def properties() -> dict:
    """The custom properties, by name."""
    return _request("list_properties", {}).get("properties", {})


def mass_properties(configuration: str | None = None) -> dict:
    """The mass properties of the configuration named, or of the active one, in SI units."""
    args = {} if configuration is None else {"configuration": configuration}
    return _request("mass_properties", args)


# --------------------------------------------------------------------------- changes
def operation(name: str, **args: Any) -> dict:
    """Carry out one operation of the vocabulary (``solidseas.ai.prompts.OPERATIONS``)
    with its arguments, as a plan's step would; entities by their handles (``E12``,
    ``Fa3``, ``F2``), lengths as ``{"value": ..., "unit": "mm"}``. The app refuses an
    operation that is not in the vocabulary."""
    if not isinstance(name, str):
        raise LiveError("an operation is named by its vocabulary name", "refused")
    return _request(name, dict(args))


OPERATIONS = ("document", "features", "dimensions", "properties", "mass_properties", "operation")

__all__ = [
    "OPERATIONS",
    "QUERIES",
    "LiveError",
    "LiveUnavailableError",
    "dimensions",
    "document",
    "features",
    "mass_properties",
    "operation",
    "properties",
]
