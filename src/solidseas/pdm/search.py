"""Finding a project by a few letters of its name, its customer or its section.

The search is forgiving on purpose, because it is typed while looking for a job:

- Case, accents and the punctuation between words do not matter ("smith-co" finds
  "Smith Co", and "cafe" finds "Café").
- Every word typed has to match somewhere in the project's name, its section or
  its path, in any order, so "bracket smith" finds a Smith project with "bracket"
  in its name.
- A word matches as the start of a word, anywhere inside one, or with letters left
  out ("brkt" finds "bracket"), in that order of preference.

The best matches come first. Among equal matches, the project worked on most recently
comes first. An empty search lists every project, most recent first.
"""

from __future__ import annotations

import datetime
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

_SPLIT = re.compile(r"[^0-9a-z]+")
_OLDEST = datetime.datetime.min.replace(tzinfo=datetime.UTC)


def words(text: str) -> list[str]:
    """``text`` as lower-case words without accents, split at anything not a letter or
    a digit."""
    plain = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return [w for w in _SPLIT.split(plain) if w]


def _in_order(token: str, word: str) -> bool:
    """Whether the letters of ``token`` appear in ``word`` in order (some left out)."""
    it = iter(word)
    return all(c in it for c in token)


def _token_score(token: str, name: list[str], other: list[str]) -> float:
    """How well one typed word matches: best in the name, then in the section or path."""
    best = 0.0
    for ws, weight in ((name, 2.0), (other, 1.0)):
        for w in ws:
            if w == token:
                s = 4.0
            elif w.startswith(token):
                s = 3.0
            elif token in w:
                s = 2.0
            elif len(token) >= 3 and w[:1] == token[:1] and _in_order(token, w):
                s = 1.0
            else:
                continue
            best = max(best, s * weight)
    joined = "".join(name)
    if best == 0.0 and len(token) >= 3 and token in joined:  # typed across a word break: "smithco"
        best = 2.0
    return best


def score(query: str, name: str, section: str = "", path: str = "") -> float:
    """How well ``query`` matches a project: 0 when one of its words matches nothing."""
    tokens = words(query)
    if not tokens:
        return 0.0
    nw = words(name)
    ow = words(section) + words(path)
    total = 0.0
    for t in tokens:
        s = _token_score(t, nw, ow)
        if s == 0.0:
            return 0.0
        total += s
    if " ".join(tokens) == " ".join(nw):
        total += 4.0  # the whole name typed
    return total


@dataclass(frozen=True)
class Found:
    """One project a search found: the entry it was given and how well it matched."""

    entry: Any
    score: float


def search(
    entries: Iterable[Any],
    query: str,
    *,
    key: Any = None,
    limit: int | None = None,
) -> list[Found]:
    """The entries that match ``query``, best first, then the most recently worked on.

    Each entry is a :class:`~solidseas.pdm.vault.ProjectActivity` or anything ``key``
    turns into ``(name, section, path, last_activity)``; ``last_activity`` is a
    datetime or None. An empty query keeps every entry, most recent first."""

    def fields(e: Any) -> tuple[str, str, str, datetime.datetime | None]:
        if key is not None:
            return key(e)
        p = e.project
        return p.name, p.section, p.path, e.last_activity

    blank = not words(query)
    found: list[tuple[float, datetime.datetime, str, Any]] = []
    for e in entries:
        name, section, path, when = fields(e)
        s = 0.0 if blank else score(query, name, section, path)
        if not blank and s == 0.0:
            continue
        found.append((s, when or _OLDEST, path.casefold(), e))
    found.sort(key=lambda f: (-f[0], -f[1].timestamp(), f[2]))
    if limit is not None:
        found = found[:limit]
    return [Found(e, s) for s, _w, _p, e in found]


def search_projects(activity: Sequence[Any], query: str, limit: int | None = None) -> list[Any]:
    """The projects of ``activity`` (from :meth:`Vault.project_activity`) that match
    ``query``, best first; every project, most recent first, for an empty query."""
    return [f.entry for f in search(activity, query, limit=limit)]
