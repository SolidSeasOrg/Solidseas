"""The words for features that are not finished: one tag and one note, the same everywhere.

A feature that ships switched on but is still being worked on carries a short tag next to
its menu entries and titles, "Experimental" or "In development", and its Settings page has a
note saying what that means for the person using it. Both come from here, so the wording
never drifts between the menus, the wizard, the drawing editor and the Settings pages.

* **Experimental**: it works and is on, but its results may be incomplete or wrong and it
  may change between versions. Drawings, the modeling assistant and the extensions whose
  front and package are built.
* **In development**: parts of it are not built yet. The OCCT backend, whose package has
  not yet been built and checked on Windows.

Released drawings are not marked here: a drawing's own PRELIMINARY stamp, on every PDF and
DXF until it is released, is the drawing library's (``docs/DRAWINGS.md``).

The text functions import no Qt; :func:`note_label` makes the quiet label the Settings pages
and the wizard show the note in.
"""

from __future__ import annotations

from typing import Any

EXPERIMENTAL = "Experimental"
IN_DEVELOPMENT = "In development"
STAGES = (EXPERIMENTAL, IN_DEVELOPMENT)
ISSUES_URL = "https://github.com/SolidSeas/SolidSeas/issues"

# The features of the viewer that carry a tag, and their stage.
DRAWINGS = "drawings"
ASSISTANT = "assistant"
FEATURES: dict[str, str] = {DRAWINGS: EXPERIMENTAL, ASSISTANT: EXPERIMENTAL}

# Each first-party extension's stage (``solidseas_app.extensions.CATALOG``). An extension
# not named here is taken as experimental.
EXTENSIONS: dict[str, str] = {
    "gridfinity": EXPERIMENTAL,
    "cad-bridge": EXPERIMENTAL,
    "video": EXPERIMENTAL,
    "solidcraft": EXPERIMENTAL,
    "occt": IN_DEVELOPMENT,
}

_MEANS = {
    EXPERIMENTAL: "{Stage}: results may be incomplete or wrong{check}, and it may change between versions.",
    IN_DEVELOPMENT: (
        "{Stage}: some of it is not finished yet, what is here may be incomplete or wrong{check}, and it "
        "may change between versions."
    ),
}


def _stage(stage: str) -> str:
    if stage not in STAGES:
        raise ValueError(f"not a stage: {stage!r}")
    return stage


def extension_stage(extension_id: str) -> str:
    """The stage of the extension ``extension_id``."""
    return EXTENSIONS.get(extension_id, EXPERIMENTAL)


def tag(stage: str = EXPERIMENTAL) -> str:
    """The tag itself: ``Experimental`` or ``In development``."""
    return _stage(stage)


def tagged(text: str, stage: str = EXPERIMENTAL) -> str:
    """``text`` with the tag after it, as a menu entry or a title shows it:
    ``New &Drawing... (Experimental)``."""
    return f"{text} ({_stage(stage)})"


def note(stage: str = EXPERIMENTAL, *, check: str | None = None) -> str:
    """What the tag means, in a line for a Settings page: ``check`` names what to check
    before use ("every drawing"), and the line ends with where to report a problem."""
    stage = _stage(stage)
    checked = f", so check {check} before you use it" if check else ""
    means = _MEANS[stage].format(Stage=stage, check=checked)
    return f"{means} Report problems at {ISSUES_URL}"


def drawings_note() -> str:
    """The note of the Drawings page and the New Drawing wizard."""
    return note(FEATURES[DRAWINGS], check="every drawing")


def assistant_note() -> str:
    """The note of the AI Assistant page."""
    return note(FEATURES[ASSISTANT], check="the code it drafts")


def extensions_note() -> str:
    """The note of the Extensions page, which tags each extension with its own stage."""
    return (
        "Extensions are experimental or still in development, as each one's tag says: results may be "
        "incomplete or wrong, and they may change between versions. Report problems at " + ISSUES_URL
    )


def note_label(text: str) -> Any:
    """A quiet, wrapping label for ``text`` (a note above), selectable so its address can be
    copied."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QLabel

    label = QLabel(text)
    label.setObjectName("experimental-note")
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    font = label.font()
    font.setPointSizeF(font.pointSizeF() * 0.92)
    label.setFont(font)
    palette = label.palette()
    palette.setColor(QPalette.ColorRole.WindowText, palette.color(QPalette.ColorRole.PlaceholderText))
    label.setPalette(palette)
    return label


__all__ = [
    "ASSISTANT",
    "DRAWINGS",
    "EXPERIMENTAL",
    "EXTENSIONS",
    "FEATURES",
    "IN_DEVELOPMENT",
    "ISSUES_URL",
    "STAGES",
    "assistant_note",
    "drawings_note",
    "extension_stage",
    "extensions_note",
    "note",
    "note_label",
    "tag",
    "tagged",
]
