"""``solidseas serve --config FILE``: the service's settings in a TOML file (``docs/API.md`` 8.17).

The file holds what the command line takes, one key per option, with ``_`` for
``-`` and the repeatable options as lists or tables::

    port = 8765
    token_file = "/var/lib/solidseas/serve-tokens"
    allow_origins = ["https://intranet.example"]

    [roots]
    jobs = "/srv/cad/jobs"

    [libraries]
    std = "/srv/cad/library"

A path in it that is not absolute is taken from the file's own folder. An option
given on the command line replaces that setting of the file, and the file's
other settings stay.

The file decides what the service serves and to whom (its roots, its address,
the hosts and origins it answers), so it is read failing closed, as the token
file is: a file that another account may change or owns, or whose folder another
account may change or owns, refuses the start (``path_refused``, exit 3, with
``detail["rule"]`` ``shared_write``, ``not_owner`` or ``folder_writable`` and
``detail["parameter"]`` ``config``), and so does a key the service does not know
or a value of the wrong type (``invalid_argument``, exit 2). Other accounts may
read it: it holds no secret, only where the token file is.
"""

import os
import re
import stat
import tomllib
from typing import Any

from ..errors import InvalidArgumentError, PathRefusedError
from ..roots import ROOT_ID, Root
from .tokens import unwritable_problem

MAX_CONFIG_BYTES = 64 << 10
_KEY_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
# Every key the file may hold, with the kind of value it takes.
KEYS: dict[str, str] = {
    "roots": "roots",
    "libraries": "roots",
    "port": "port",
    "bind": "text",
    "token_file": "path",
    "identity_key_file": "path",
    "workers": "count",
    "allow_remote": "bool",
    "allowed_hosts": "texts",
    "identity_addresses": "texts",
    "allow_origins": "texts",
    "catalog": "bool",
    "catalog_rescan": "seconds",
    "formats": "formats",
}


def _bad(message: str, key: str | None = None) -> InvalidArgumentError:
    detail: dict[str, Any] = {"parameter": "config"}
    if key is not None and _KEY_NAME.match(key):
        detail["value"] = key
    return InvalidArgumentError(f"the configuration file: {message}", detail=detail)


def _text(key: str, value: Any, limit: int = 1024) -> str:
    if not isinstance(value, str) or not value or len(value) > limit or not value.isprintable():
        raise _bad(f"{key} is a text of 1 to {limit} printable characters", key)
    return value


def _path(key: str, value: Any, folder: str) -> str:
    return os.path.normpath(os.path.join(folder, _text(key, value, 4096)))


def _convert(key: str, kind: str, value: Any, folder: str) -> Any:
    if kind == "bool":
        if not isinstance(value, bool):
            raise _bad(f"{key} is true or false", key)
        return value
    if kind in ("port", "count"):
        low, high = (0, 65535) if kind == "port" else (1, 1024)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise _bad(f"{key} is a whole number from {low} to {high}", key)
        return value
    if kind == "seconds":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 31_536_000:
            raise _bad(f"{key} is a number of seconds above 0", key)
        return float(value)
    if kind == "text":
        return _text(key, value)
    if kind == "path":
        return _path(key, value, folder)
    if kind == "texts":
        if not isinstance(value, list) or len(value) > 64:
            raise _bad(f"{key} is a list of at most 64 texts", key)
        return [_text(key, v, 300) for v in value]
    if kind == "formats":
        if isinstance(value, list):
            value = ",".join(_text(key, v, 64) for v in value)
        return _text(key, value, 1000)
    if kind == "roots":
        if not isinstance(value, dict) or not value or len(value) > 64:
            raise _bad(f"{key} is a table of 1 to 64 id = folder lines", key)
        out = []
        for root_id, folder_text in value.items():
            if not ROOT_ID.match(root_id):
                raise _bad(f"a root id in {key} matches [a-z0-9_-]{{1,32}}", key)
            role = "library" if key == "libraries" else "project"
            out.append(Root(root_id, _path(key, folder_text, folder), True, role))
        return out
    raise ValueError(f"unknown setting kind {kind!r}")  # a bug in KEYS


def load_serve_config(path: str | os.PathLike) -> dict[str, Any]:
    """The settings in the configuration file at ``path``, checked and converted: paths
    absolute (taken from the file's folder when relative), ``roots`` and ``libraries``
    as lists of :class:`~solidseas.roots.Root`. Raises ``FileNotFoundError`` when there
    is no such file, :class:`~solidseas.errors.PathRefusedError` when another account
    may change it, and :class:`~solidseas.errors.InvalidArgumentError` for anything it
    holds that is not a setting of the right type."""
    given = os.path.abspath(os.fspath(path))
    real = os.path.realpath(given)  # a link's target is what is read, so it is what is checked
    try:
        st = os.stat(real)
    except FileNotFoundError:
        raise FileNotFoundError(2, "the configuration file does not exist", given) from None
    if not stat.S_ISREG(st.st_mode):
        raise PathRefusedError(
            "the configuration file is not a regular file",
            detail={"rule": "not_regular_file", "parameter": "config"},
        )
    if st.st_size > MAX_CONFIG_BYTES:
        raise _bad(f"it is larger than {MAX_CONFIG_BYTES} bytes")
    problem = unwritable_problem(real, "configuration file")
    if problem is not None:
        rule, message = problem
        raise PathRefusedError(message, detail={"rule": rule, "parameter": "config"})
    with open(real, "rb") as fh:
        raw = fh.read(MAX_CONFIG_BYTES + 1)
    try:
        document = tomllib.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        raise _bad("it is not UTF-8 text") from None
    except tomllib.TOMLDecodeError as exc:
        raise _bad(f"it is not TOML ({exc})") from None
    folder = os.path.dirname(given)
    settings: dict[str, Any] = {}
    for key, value in document.items():
        kind = KEYS.get(key)
        if kind is None:
            raise _bad(f"there is no setting {key[:64]!r}", key)
        settings[key] = _convert(key, kind, value, folder)
    return settings


__all__ = ["KEYS", "MAX_CONFIG_BYTES", "load_serve_config"]
