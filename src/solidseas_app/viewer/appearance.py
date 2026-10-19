"""How the 3D view shows each component of an assembly, as the user set it: hidden or
shown, and how transparent.

A choice is made on a scope: one instance or a sub-assembly by its component tree id
(:data:`ID`, which covers every instance under that id), every instance of a
component file by its file key (:data:`FILE`), the instances drawn as boxes for want
of a mesh (:data:`BOXES`), or every instance (:data:`ALL`). Each choice sets one of
two properties, whether the instances are hidden and how transparent they are (a
percentage, :data:`TRANSPARENCY_STEPS` in the menus, at most
:data:`MAX_TRANSPARENCY`), and is numbered as it is made. Of the choices that cover
an instance, the latest decides each property: a part made opaque after its
housing's whole file was made transparent stays opaque, and the file made
transparent again afterwards takes it along. Isolate is two choices, every instance
hidden and then the scope shown. Show all drops every choice of the hidden property,
and :meth:`Looks.reset` every choice.

The choices are kept by id and file key, not by the view's numbering, so they hold
while the assembly is drawn again in another configuration, for whatever ids and
files are there, and Back puts them back with :meth:`Looks.state`. Nothing here
imports Qt, so it is tested on its own.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

ID, FILE, BOXES, ALL = "id", "file", "boxes", "all"
KINDS = (ID, FILE, BOXES, ALL)
HIDDEN, TRANSPARENCY = "hidden", "transparency"
TRANSPARENCY_STEPS = (0, 25, 50, 75, 90)  # percent, offered by the menus
MAX_TRANSPARENCY = 90  # percent: more would leave a component hard to see at all

Scope = tuple[str, str]


@dataclass(frozen=True)
class Look:
    """What one instance shows: ``hidden``, and ``transparency`` in percent."""

    hidden: bool = False
    transparency: int = 0

    @property
    def opacity(self) -> float:
        return 1.0 - self.transparency / 100.0


SHOWN = Look()


def clamp_transparency(percent: float) -> int:
    return int(min(max(round(percent), 0), MAX_TRANSPARENCY))


class Looks:
    """The choices made in one document's 3D view (see the module docstring)."""

    def __init__(self) -> None:
        self._choices: dict[Scope, dict[str, tuple[Any, int]]] = {}
        self._seq = 0

    # -- making choices ----------------------------------------------------------------
    def set(self, scope: Scope, prop: str, value: Any) -> None:
        """Choose ``value`` for ``prop`` (:data:`HIDDEN` or :data:`TRANSPARENCY`) on
        ``scope``, a ``(kind, value)`` pair of :data:`KINDS`."""
        kind, _ = scope
        if kind not in KINDS or prop not in (HIDDEN, TRANSPARENCY):
            raise ValueError(f"no such choice: {scope!r} {prop!r}")
        if prop == TRANSPARENCY:
            value = clamp_transparency(value)
        else:
            value = bool(value)
        self._seq += 1
        self._choices.setdefault(scope, {})[prop] = (value, self._seq)

    def hide(self, scope: Scope, hidden: bool = True) -> None:
        self.set(scope, HIDDEN, hidden)

    def transparent(self, scope: Scope, percent: float) -> None:
        self.set(scope, TRANSPARENCY, percent)

    def isolate(self, scope: Scope) -> None:
        """Hide everything else: every instance hidden, then ``scope`` shown."""
        self.set((ALL, ""), HIDDEN, True)
        self.set(scope, HIDDEN, False)

    def show_all(self) -> None:
        """Every instance shown again; transparency stays as chosen."""
        for props in self._choices.values():
            props.pop(HIDDEN, None)
        self._choices = {s: p for s, p in self._choices.items() if p}

    def reset(self) -> None:
        """Every instance shown and opaque, as the file draws it."""
        self._choices = {}

    # -- reading them --------------------------------------------------------------------
    @property
    def changed(self) -> bool:
        """Whether any choice is held."""
        return bool(self._choices)

    @property
    def any_hidden(self) -> bool:
        """Whether a choice hides something (Show all has something to undo)."""
        return any(props.get(HIDDEN, (False, 0))[0] for props in self._choices.values())

    def look(self, ident: str, files: Iterable[str] = (), *, box: bool = False) -> Look:
        """The look of the instance ``ident``, an instance of the component files
        ``files`` (its keys), drawn as a box or not."""
        scopes: list[Scope] = [(ALL, "")]
        if box:
            scopes.append((BOXES, ""))
        scopes.extend((FILE, f) for f in files if f)
        names = ident.split("/")
        scopes.extend((ID, "/".join(names[: k + 1])) for k in range(len(names)))
        best: dict[str, tuple[Any, int]] = {}
        for scope in scopes:
            props = self._choices.get(scope)
            if not props:
                continue
            for prop, (value, seq) in props.items():
                if prop not in best or seq > best[prop][1]:
                    best[prop] = (value, seq)
        if not best:
            return SHOWN
        return Look(
            hidden=bool(best.get(HIDDEN, (False, 0))[0]),
            transparency=int(best.get(TRANSPARENCY, (0, 0))[0]),
        )

    # -- for Back ------------------------------------------------------------------------
    def state(self) -> dict[str, Any]:
        """The choices as plain data, to put back with :meth:`from_state`."""
        return {
            "seq": self._seq,
            "choices": [
                [kind, value, prop, v, seq]
                for (kind, value), props in self._choices.items()
                for prop, (v, seq) in props.items()
            ],
        }

    @classmethod
    def from_state(cls, state: dict[str, Any] | None) -> "Looks":
        looks = cls()
        if not state:
            return looks
        for kind, value, prop, v, seq in state.get("choices") or ():
            if kind in KINDS and prop in (HIDDEN, TRANSPARENCY):
                looks._choices.setdefault((kind, value), {})[prop] = (v, int(seq))
        made = [seq for props in looks._choices.values() for _, seq in props.values()]
        looks._seq = max([int(state.get("seq") or 0), *made])
        return looks
