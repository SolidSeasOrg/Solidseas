"""Settings > Drawing Settings (``docs/DRAWINGS.md`` 15.2): every Drawing Setting of
7.2 in one dialog, a page a group, saved to ``Drawing.json`` through
:func:`solidseas.drawing.settings.save_settings`.

* **Pages**: Company, People and Approvals, Standard and Units, Sheets, Title Block,
  Tolerances, Geometric Tolerances, Printing, Notes, Materials and Finishes, Default
  Views, Dimensioning, Files, Email and Limits (:data:`PAGES`). Each control is bound
  to one setting; :data:`PAGES` says which, and with what kind of control.
* **Checks.** OK and Apply check every value as loading the file checks it
  (:func:`solidseas.drawing.settings.with_value`), and the webmail address further
  (:func:`.mail.template_problem`). A value that fails is refused with its reason,
  listed at the top, its page shown and its control focused, and nothing is saved.
  Cancel discards what was changed since the last Apply.
* **Fallbacks** the file needed when it was loaded are listed at the top, and so are
  the **first-use prompts** (:meth:`DrawingSettings.first_use`: the unit for parts
  that state none, the company's name, the people who sign); the dialog opens on the
  first page that lacks one.
* **The logo** (7.1): Choose... reads the image through ``QImage``, scales it to at
  most 1,200 pixels on the long side and makes an 8-bit RGB or RGBA, non-interlaced
  PNG of at most 512 KiB, with no text or colour profile carried over from the source
  (:func:`logo_png`). It is written as ``logo.png`` beside ``Drawing.json`` when the
  settings are saved, never before, and the settings record its SHA-256.

Nothing here reads Windows, Office or SOLIDWORKS: people are typed names. The page
table and the conversions between values and the text a control shows import no Qt;
the dialog imports PySide6 when it is made.
"""

import hashlib
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass, fields
from typing import Any

from solidseas.drawing import settings as drawing_settings
from solidseas.drawing import standards
from solidseas.drawing.limits import DEFAULT_LIMITS
from solidseas.errors import InvalidArgumentError, SolidSeasError

from .mail import refusal_reason, template_problem

LOGO_PIXELS = DEFAULT_LIMITS.logo_pixels
LOGO_BYTES = DEFAULT_LIMITS.logo_bytes
LOGO_STEPS = (LOGO_PIXELS, 900, 600, 400)  # long sides tried until the PNG fits LOGO_BYTES
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.gif)"


# --------------------------------------------------------------------------- the pages (no Qt)
@dataclass(frozen=True)
class Column:
    """A part of a setting with several: a column of a list's table, a key of a mapping
    or a value of a per-type group. ``kind`` as :class:`Field`'s."""

    key: str
    label: str
    kind: str
    options: tuple = ()


@dataclass(frozen=True)
class Field:
    """One control, bound to the setting ``group.key``. ``kind`` is the control:
    ``text``, ``multiline``, ``lines`` (one entry a line), ``names`` (entries split by
    ``options[0]``, "; " unless given), ``address``, ``flag``, ``choice`` (``options``
    are (value, label) pairs), ``number``, ``optional_number`` (empty is none),
    ``checks`` (a tick box a choice), ``records`` (a table of :class:`Column`),
    ``block`` (a tolerance block's rows), ``mapping`` and ``per_type`` (a control a
    :class:`Column`), ``logo`` or ``folder`` (empty is next to the part). A setting
    that nothing applies yet is shown but not ``enabled``, its ``tip`` saying so."""

    group: str
    key: str
    label: str
    kind: str
    options: tuple = ()
    tip: str = ""
    enabled: bool = True


@dataclass(frozen=True)
class Page:
    title: str
    note: str
    fields: tuple[Field, ...]


_TYPE_LABELS = {"machined": "Machined", "printed": "3D printed"}
_ROLE_LABELS = {
    "envelope": "Overall sizes",
    "step": "Steps",
    "width": "Widths",
    "hole_size": "Hole sizes",
    "hole_location": "Hole locations",
    "basic": "Basic dimensions",
}
_UNITS = (("part", "The part's own"), ("in", "Inch"), ("mm", "Millimetre"))
_UNSTATED = ((None, "Not chosen yet"), ("in", "Inch"), ("mm", "Millimetre"))
_SCHEMES = (("datum", "Datum-referenced (basic locations, position)"), ("plusminus", "Plus and minus"))
_VIEW_NAMES = tuple((v, v.capitalize()) for v in ("front", "top", "right", "left", "bottom", "back"))
_FRONTS = (("auto", "Automatic"),) + tuple((d, d.upper()) for d in ("+x", "-x", "+y", "-y", "+z", "-z"))
_KINDS = tuple(_TYPE_LABELS)  # the manufacturing types, as a table's column takes them
_TOKENS = ", ".join("{" + t + "}" for t in drawing_settings.NOTE_TOKENS)
METHOD_LABELS = (
    (
        "automatic",
        "Automatic: attach in Outlook or Thunderbird when one is the default mail program, else webmail",
    ),
    ("webmail", "Webmail in the browser"),
    ("show", "Just show me the file"),
)

PAGES: tuple[Page, ...] = (
    Page(
        "Company",
        "Printed in every title block. These details and the logo stay in your settings and in the "
        "drawings that carry them.",
        (
            Field("company", "name", "Legal name", "text"),
            Field("company", "address", "Address", "address"),
            Field("company", "phone", "Phone", "text"),
            Field("company", "web", "Email or web", "text"),
            Field("company", "logo", "Logo", "logo"),
            Field("company", "cage", "CAGE code (optional)", "text"),
            Field(
                "company",
                "proprietary",
                "Proprietary statement",
                "multiline",
                tip="{company} is replaced by the legal name.",
            ),
            Field("company", "do_not_scale", "Print DO NOT SCALE DRAWING", "flag"),
        ),
    ),
    Page(
        "People and Approvals",
        "Names are typed here; nothing is read from Windows, Office or SOLIDWORKS.",
        (
            Field(
                "people",
                "people",
                "People",
                "records",
                (Column("name", "Name", "text"), Column("initials", "Initials", "text")),
            ),
            Field(
                "people",
                "rows",
                "Approval rows",
                "checks",
                tuple((r, r) for r in drawing_settings.APPROVAL_ROWS),
            ),
            Field(
                "people",
                "required",
                "Rows Release needs signed",
                "checks",
                tuple((r, r) for r in drawing_settings.APPROVAL_ROWS),
            ),
            Field("people", "same_person_twice", "One person may sign two rows (with a warning)", "flag"),
            Field(
                "people",
                "date_format",
                "Date format",
                "choice",
                (("iso", "2026-10-04"), ("us", "10/04/2026")),
            ),
            Field("people", "first_revision", "First revision", "text"),
        ),
    ),
    Page(
        "Standard and Units",
        "",
        (
            Field(
                "standard",
                "profile",
                "Standard",
                "choice",
                (("asme", "ASME Y14.5"), ("iso", "ISO (first angle views, ASME sheet)")),
                "ISO so far changes only the projection to first angle. The sheet, title block and "
                "lettering still follow ASME.",
            ),
            Field(
                "standard",
                "projection",
                "Projection",
                "choice",
                (
                    ("standard", "As the standard says (ASME third angle, ISO first angle)"),
                    ("first", "First angle"),
                    ("third", "Third angle"),
                ),
            ),
            Field("standard", "units", "Units", "choice", _UNITS),
            Field(
                "standard",
                "unit_for_unstated",
                "Unit for parts that state none",
                "choice",
                _UNSTATED,
                "A new drawing still shows its guess and asks you to confirm it.",
            ),
            Field("standard", "upper_case_notes", "Notes in capitals", "flag"),
        ),
    ),
    Page(
        "Sheets",
        "",
        (
            Field(
                "sheets",
                "size",
                "Default size",
                "choice",
                (("auto", "Automatic"),) + tuple((s, s) for s in standards.SHEET_ORDER),
            ),
            Field(
                "sheets",
                "orientation",
                "Orientation",
                "choice",
                (("landscape", "Landscape"), ("portrait", "Portrait")),
            ),
            Field("sheets", "zones", "Zones", "flag"),
            Field("sheets", "scales", "Scales offered", "names", (", ",)),
        ),
    ),
    Page(
        "Title Block",
        "The custom properties read for each field, separated by semicolons; the first found is used.",
        (
            Field("title_sources", "part_number", "Part number", "names"),
            Field("title_sources", "number", "Drawing number", "names"),
            Field("title_sources", "title", "Title", "names"),
            Field("title_sources", "revision", "Revision", "names"),
            Field("title_sources", "model_revision", "Model revision", "names"),
            Field("title_sources", "material", "Material", "names"),
            Field("title_sources", "finish", "Finish", "names"),
            Field(
                "title_sources",
                "title_style",
                "Title style",
                "choice",
                (("noun_first", "Noun first: BRACKET, MOUNTING"), ("as_typed", "As typed")),
            ),
            Field("title_sources", "show_weight", "Show the weight", "flag"),
        ),
    ),
    Page(
        "Tolerances",
        "Your company's tolerances.",
        (
            Field("tolerances", "inch_block", "Inch block", "block"),
            Field("tolerances", "mm_block", "Millimetre block", "block"),
            Field("tolerances", "angle", "Angles, plus or minus (degrees)", "number"),
            Field(
                "tolerances",
                "mm_general",
                "Millimetre general tolerance",
                "choice",
                (("block", "The millimetre block"),)
                + tuple((f"iso2768-{c}", f"ISO 2768-{c}") for c in standards.ISO2768_CLASSES),
                "Not available yet: millimetre drawings use the millimetre block above. An ISO 2768 "
                "class will be offered here once drawings apply it.",
                enabled=False,
            ),
            Field(
                "tolerances",
                "precision_in",
                "Decimal places, inch",
                "mapping",
                tuple(Column(r, _ROLE_LABELS[r], "number") for r in drawing_settings.ROLES),
            ),
            Field(
                "tolerances",
                "precision_mm",
                "Decimal places, millimetre",
                "mapping",
                tuple(Column(r, _ROLE_LABELS[r], "number") for r in drawing_settings.ROLES),
            ),
            Field("tolerances", "show_bands", "Show the tolerance bands", "flag"),
        ),
    ),
    Page(
        "Geometric Tolerances",
        "",
        (
            Field(
                "gdt",
                "scheme",
                "Default scheme",
                "mapping",
                tuple(Column(t, _TYPE_LABELS[t], "choice", _SCHEMES) for t in drawing_settings.TYPES),
            ),
            Field(
                "gdt",
                "position_in",
                "Position of holes, inch",
                "mapping",
                (Column("clearance", "Clearance", "number"), Column("tapped", "Tapped", "number")),
            ),
            Field(
                "gdt",
                "position_mm",
                "Position of holes, millimetre",
                "mapping",
                (Column("clearance", "Clearance", "number"), Column("tapped", "Tapped", "number")),
            ),
            Field(
                "gdt",
                "position_modifier",
                "Position modifier",
                "choice",
                (("mmc", "At MMC"), ("lmc", "At LMC"), ("none", "Regardless of feature size")),
            ),
            Field("gdt", "profile_in", "General profile to A, B, C, inch", "number"),
            Field("gdt", "profile_mm", "General profile to A, B, C, millimetre", "number"),
            Field(
                "gdt",
                "undimensioned_in",
                "Profile of undimensioned surfaces, inch (empty: none)",
                "optional_number",
            ),
            Field(
                "gdt",
                "undimensioned_mm",
                "Profile of undimensioned surfaces, millimetre (empty: none)",
                "optional_number",
            ),
            Field("gdt", "runout_in", "Runout, inch", "number"),
            Field("gdt", "runout_mm", "Runout, millimetre", "number"),
        ),
    ),
    Page(
        "Printing",
        "Service bureau figures; replace them with your own. A printed size is held to the fixed "
        "amount plus the rate times the size.",
        (
            Field(
                "printing",
                "processes",
                "Processes",
                "records",
                (
                    Column("name", "Process", "text"),
                    Column("category", "Category", "text"),
                    Column("xy_fixed_mm", "X and Y (mm)", "number"),
                    Column("z_fixed_mm", "Z (mm)", "number"),
                    Column("rate", "Rate", "number"),
                    Column("floor_mm", "Floor (mm)", "number"),
                ),
            ),
            Field("printing", "label", "Label of these figures", "text"),
        ),
    ),
    Page(
        "Notes",
        f"One note a line. A note may hold {_TOKENS}.",
        (
            Field("notes", "machined", "Machined and turned parts", "lines"),
            Field("notes", "printed", "3D printed parts", "lines"),
            Field("notes", "edge_break_in", "Edge break, inch", "text"),
            Field("notes", "edge_break_mm", "Edge break, millimetre", "text"),
            Field("notes", "surface_finish_in", "Surface finish, inch", "text"),
            Field("notes", "surface_finish_mm", "Surface finish, millimetre", "text"),
        ),
    ),
    Page(
        "Materials and Finishes",
        "A model's material matches an entry when its name, in any case and spacing, is one of the "
        "entry's names (separated by semicolons); the first match wins. Types are machined and printed.",
        (
            Field(
                "materials",
                "entries",
                "Materials",
                "records",
                (
                    Column("names", "Names in the model", "names"),
                    Column("callout", "Callout", "text"),
                    Column("specification", "Specification", "text"),
                    Column("density", "Density (kg/m³)", "optional_number"),
                    Column("types", "Types", "kinds"),
                    Column("heat_treatable", "Heat-treatable", "flag"),
                ),
            ),
            Field(
                "materials",
                "finishes",
                "Finishes",
                "records",
                (
                    Column("name", "Name", "text"),
                    Column("callout", "Callout", "text"),
                    Column("types", "Types", "kinds"),
                    Column("after", "Dimensions apply after it", "flag"),
                ),
            ),
        ),
    ),
    Page(
        "Default Views",
        "",
        (
            Field(
                "defaults",
                "views",
                "Views",
                "per_type",
                (
                    Column("views", "Views", "checks", _VIEW_NAMES),
                    Column("isometric", "Isometric view", "flag"),
                    Column("hidden", "Hidden lines", "flag"),
                    Column(
                        "tangent",
                        "Tangent edges",
                        "choice",
                        (("hidden", "Hidden"), ("thin", "Thin lines"), ("phantom", "Phantom lines")),
                    ),
                    Column("front", "Front direction", "choice", _FRONTS),
                ),
            ),
        ),
    ),
    Page(
        "Dimensioning",
        "",
        (
            Field(
                "defaults",
                "detail",
                "Detail level of new drawings",
                "choice",
                (("simplified", "Simplified"), ("complex", "Complex"), ("full", "Fully defined")),
            ),
            Field(
                "defaults",
                "dimensioning",
                "Dimensioning",
                "per_type",
                (
                    Column(
                        "scheme", "Scheme", "choice", (("baseline", "Baseline"), ("ordinate", "Ordinate"))
                    ),
                    Column("ordinate_tracks", "Ordinate above this many tracks", "number"),
                    Column("ordinate_share", "Or this share of the view", "number"),
                    Column("hole_callouts", "Hole callouts", "flag"),
                    Column("thread_suggestions", "Thread suggestions", "flag"),
                    Column(
                        "chamfer_style",
                        "Chamfers",
                        "choice",
                        (("leg_angle", "Leg X angle"), ("two_legs", "Two legs")),
                    ),
                    Column("symbol_words", "Words beside symbols", "flag"),
                ),
            ),
        ),
    ),
    Page(
        "Files",
        "",
        (
            Field("files", "folder", "Save drawings in", "folder"),
            Field(
                "files",
                "name_pattern",
                "File name",
                "text",
                tip="Must hold {number}; may hold {revision}, {title} and {part_number}.",
            ),
            Field(
                "files", "keep_preliminary_current", "Save keeps the preliminary PDF and DXF current", "flag"
            ),
            Field(
                "files",
                "replace_own_files",
                "Save may replace files SolidSeas wrote and nobody changed since",
                "flag",
                tip="Off, every save writes new files.",
            ),
        ),
    ),
    Page(
        "Email",
        "SolidSeas never sends mail and never sees a password: your mail program or webmail does. Only the "
        "PDF is offered, and a webmail address carries only the drawing number and title.",
        (
            Field("email", "method", "Method", "choice", METHOD_LABELS),
            Field(
                "email",
                "webmail_url",
                "Webmail compose address",
                "text",
                tip="An https:// address; {subject} is replaced by the drawing number and title, and {to} is "
                "left empty. Gmail's is the default.",
            ),
            Field("email", "prefill_subject", "Put the drawing number and title in the subject", "flag"),
        ),
    ),
    Page(
        "Limits",
        "",
        (
            Field("limits", "child_memory_mb", "Memory a drawing's process may use (MB)", "number"),
            Field("limits", "draft_faces", "Draft quality above this many faces", "number"),
        ),
    ),
)

# Checks a value must pass beyond the settings' own.
EXTRA_CHECKS: dict[tuple[str, str], Callable[[Any], str | None]] = {
    ("email", "webmail_url"): template_problem
}

FIRST_USE = {
    "standard.unit_for_unstated": "Choose the unit for parts that state none (Standard and Units).",
    "company.name": "Type your company's legal name (Company): it goes in every title block.",
    "people.people": "Add the people who draw, check and approve (People and Approvals).",
}


def page_of(group: str, key: str) -> str | None:
    """The title of the page that holds ``group.key``."""
    for page in PAGES:
        if any(f.group == group and f.key == key for f in page.fields):
            return page.title
    return None


def first_use_prompts(settings: drawing_settings.DrawingSettings) -> list[tuple[str, str]]:
    """The settings still waiting for the user's first answer, as (page, prompt)."""
    out = []
    for name in settings.first_use():
        group, key = name.split(".", 1)
        out.append((page_of(group, key) or "", FIRST_USE.get(name, f"Set {name}.")))
    return out


def number_text(value: Any) -> str:
    """A number as its control shows it: whole numbers without a point, others as
    Python writes them back exactly; none as empty."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    if isinstance(value, float):
        return repr(value)
    return str(value)


def parse_number(text: str, *, optional: bool = False) -> Any:
    """What a number's control holds: a whole number, a number, None when it is empty
    and may be, or the text itself, which the setting's check then refuses."""
    text = text.strip()
    if not text:
        return None if optional else text
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def names_text(values: Any, separator: str = "; ") -> str:
    return separator.join(values)


def parse_names(text: str, separator: str = "; ") -> list[str]:
    return [p.strip() for p in text.split(separator.strip()) if p.strip()]


def lines_text(values: Any) -> str:
    return "\n".join(values)


def parse_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def address_value(lines: list[str]) -> list[str]:
    """The address lines typed, without the empty ones at the end."""
    out = list(lines)
    while out and not out[-1].strip():
        out.pop()
    return out


def cell_text(kind: str, value: Any) -> str:
    """A table cell's text for a value of ``kind``."""
    if kind in ("number", "optional_number"):
        return number_text(value)
    if kind == "names":
        return names_text(value or ())
    if kind == "kinds":
        return ", ".join(value or ())
    return "" if value is None else str(value)


def cell_value(kind: str, text: str) -> Any:
    """A table cell's value from its text."""
    if kind in ("number", "optional_number"):
        return parse_number(text, optional=kind == "optional_number")
    if kind == "names":
        return parse_names(text)
    if kind == "kinds":
        return [p.strip().lower() for p in text.split(",") if p.strip()]
    return text.strip()


def default_value(group: str, key: str) -> Any:
    """The setting's value as it comes."""
    return getattr(getattr(drawing_settings.DrawingSettings(), group), key)


# --------------------------------------------------------------------------- the logo (no Qt)
def logo_path(settings_path: str) -> str:
    """``logo.png`` beside the settings file."""
    return os.path.join(os.path.dirname(os.path.abspath(settings_path)), drawing_settings.LOGO_NAME)


def png_size(png: bytes) -> tuple[int, int]:
    """A PNG's width and height from its header."""
    return int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")


def read_logo(settings_path: str, sha256: str | None) -> tuple[bytes | None, str | None]:
    """The logo the settings record, and why it is not used (None when it is): read
    only to 512 KiB and one byte, and checked as the library checks it."""
    if sha256 is None:
        return None, None
    path = logo_path(settings_path)
    try:
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode):
            return None, "logo.png is not a file"
        with open(path, "rb") as fh:
            png = fh.read(LOGO_BYTES + 1)
    except OSError:
        return None, "logo.png is not beside the settings"
    problem = drawing_settings.logo_problem(png, sha256)
    return (None, problem) if problem else (png, None)


def save_logo(settings_path: str, png: bytes) -> str:
    """Write ``logo.png`` beside the settings through a temporary file and a rename."""
    from solidseas.export import write_new

    def write(fh) -> int:
        fh.write(png)
        return len(png)

    folder = os.path.dirname(os.path.abspath(settings_path))
    os.makedirs(folder, exist_ok=True)
    return write_new(logo_path(settings_path), write, overwrite=True)[0]


def remove_logo(settings_path: str) -> bool:
    """Remove ``logo.png`` beside the settings when it is a plain file; whether one was."""
    path = logo_path(settings_path)
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            return False
        os.remove(path)
    except OSError:
        return False
    return True


class LogoRefused(Exception):
    """The image chosen cannot be the logo; the message says why, in words."""


# --------------------------------------------------------------------------- Qt
def _qt():
    from PySide6 import QtCore, QtGui, QtWidgets

    return QtCore, QtGui, QtWidgets


def _png(image) -> bytes:
    QtCore, _QtGui, _QtWidgets = _qt()
    data = QtCore.QByteArray()
    buffer = QtCore.QBuffer(data)
    buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG", 0):  # quality 0: the most compression
        raise LogoRefused("it could not be written as a PNG")
    buffer.close()
    return bytes(data.data())


def logo_png(source: str) -> bytes:
    """The logo made from the image at ``source`` (see the module notes); LogoRefused
    says why when it cannot be one."""
    QtCore, QtGui, _QtWidgets = _qt()
    keep = QtCore.Qt.AspectRatioMode.KeepAspectRatio
    smooth = QtCore.Qt.TransformationMode.SmoothTransformation
    reader = QtGui.QImageReader(source)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and max(size.width(), size.height()) > LOGO_PIXELS:
        reader.setScaledSize(size.scaled(LOGO_PIXELS, LOGO_PIXELS, keep))
    image = reader.read()
    if image.isNull():
        raise LogoRefused(f"it could not be read as an image ({reader.errorString()})")
    alpha = image.hasAlphaChannel()
    fmt = QtGui.QImage.Format.Format_RGBA8888 if alpha else QtGui.QImage.Format.Format_RGB888
    for side in LOGO_STEPS:
        step = image
        if max(step.width(), step.height()) > side:
            step = step.scaled(side, side, keep, smooth)
        step = step.convertToFormat(fmt)
        # A copy of the pixels alone: no text, colour profile or other metadata of the source.
        pixels = bytes(step.constBits())
        clean = QtGui.QImage(pixels, step.width(), step.height(), step.bytesPerLine(), fmt).copy()
        png = _png(clean)
        if len(png) <= LOGO_BYTES:
            break
    else:
        raise LogoRefused(
            f"even at {LOGO_STEPS[-1]} pixels it is larger than {LOGO_BYTES // 1024} KiB as a PNG; "
            "a simpler image fits"
        )
    problem = drawing_settings.logo_problem(png, hashlib.sha256(png).hexdigest())
    if problem is not None:
        raise LogoRefused(problem)
    return png


@dataclass
class _Binding:
    """A control bound to one setting: its page's index, the widget focused when its
    value is refused, and how its value is read and shown."""

    field: Field
    page: int
    widget: Any
    get: Callable[[], Any]
    put: Callable[[Any], None]


def _plain_label(text: str, *, note: bool = False):
    QtCore, QtGui, QtWidgets = _qt()
    label = QtWidgets.QLabel(text)
    label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    if note:
        palette = label.palette()
        palette.setColor(
            QtGui.QPalette.ColorRole.WindowText, palette.color(QtGui.QPalette.ColorRole.PlaceholderText)
        )
        label.setPalette(palette)
    return label


def _editor(kind: str, options: tuple, label: str = ""):
    """A control for a value of ``kind``: (the widget, read its value, show a value)."""
    _QtCore, _QtGui, QtWidgets = _qt()
    if kind == "flag":
        box = QtWidgets.QCheckBox(label)
        return box, box.isChecked, lambda v: box.setChecked(bool(v))
    if kind == "choice":
        combo = QtWidgets.QComboBox()
        values = [v for v, _ in options]
        for _v, text in options:
            combo.addItem(text)

        def get_choice():
            i = combo.currentIndex()
            return values[i] if 0 <= i < len(values) else None

        def put_choice(v):
            combo.setCurrentIndex(values.index(v) if v in values else -1)

        return combo, get_choice, put_choice
    if kind == "checks":
        holder = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        boxes = []
        for value, text in options:
            box = QtWidgets.QCheckBox(text)
            row.addWidget(box)
            boxes.append((value, box))
        row.addStretch(1)
        shown: list = []  # the order the setting held them in, which the boxes keep

        def get_checks():
            ticked = [v for v, b in boxes if b.isChecked()]
            return [v for v in shown if v in ticked] + [v for v in ticked if v not in shown]

        def put_checks(values):
            shown[:] = list(values or ())
            for v, b in boxes:
                b.setChecked(v in shown)

        return holder, get_checks, put_checks
    if kind in ("multiline", "lines"):
        edit = QtWidgets.QPlainTextEdit()
        edit.setTabChangesFocus(True)
        edit.setFixedHeight(edit.fontMetrics().lineSpacing() * (6 if kind == "lines" else 4) + 12)
        if kind == "lines":
            return edit, lambda: parse_lines(edit.toPlainText()), lambda v: edit.setPlainText(lines_text(v))
        return edit, edit.toPlainText, lambda v: edit.setPlainText(v or "")
    edit = QtWidgets.QLineEdit()
    if kind in ("number", "optional_number"):
        optional = kind == "optional_number"
        return (
            edit,
            lambda: parse_number(edit.text(), optional=optional),
            lambda v: edit.setText(number_text(v)),
        )
    if kind == "names":
        separator = options[0] if options else "; "
        return (
            edit,
            lambda: parse_names(edit.text(), separator),
            lambda v: edit.setText(names_text(v, separator)),
        )
    return edit, edit.text, lambda v: edit.setText("" if v is None else str(v))


class _Table:
    """A list of records, or a tolerance block, as a table with Add Row and Remove Row:
    a row a record, a column a :class:`Column`; a flag a tick box in its cell."""

    def __init__(self, columns: tuple[Column, ...]) -> None:
        QtCore, _QtGui, QtWidgets = _qt()
        self.columns = columns
        self.widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self.widget)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QtWidgets.QTableWidget(0, len(columns))
        self.table.setHorizontalHeaderLabels([c.label for c in columns])
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        self.table.setMinimumHeight(150)
        layout.addWidget(self.table)
        buttons = QtWidgets.QHBoxLayout()
        self.add_button = QtWidgets.QPushButton("Add Row")
        self.remove_button = QtWidgets.QPushButton("Remove Row")
        self.add_button.clicked.connect(lambda: self.append({}))
        self.remove_button.clicked.connect(self.remove_current)
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self._flags = QtCore.Qt.ItemFlag

    def append(self, record: dict) -> int:
        QtCore, _QtGui, QtWidgets = _qt()
        row = self.table.rowCount()
        self.table.insertRow(row)
        for c, column in enumerate(self.columns):
            item = QtWidgets.QTableWidgetItem()
            if column.kind == "flag":
                item.setFlags(
                    self._flags.ItemIsUserCheckable | self._flags.ItemIsEnabled | self._flags.ItemIsSelectable
                )
                checked = bool(record.get(column.key, False))
                item.setCheckState(
                    QtCore.Qt.CheckState.Checked if checked else QtCore.Qt.CheckState.Unchecked
                )
            else:
                item.setText(cell_text(column.kind, record.get(column.key)))
            self.table.setItem(row, c, item)
        return row

    def remove_current(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def set_records(self, records: Any) -> None:
        self.table.setRowCount(0)
        for record in records or ():
            self.append(dict(record))
        self.table.resizeColumnsToContents()

    def records(self) -> list[dict]:
        """Every row that holds any text, as a record."""
        QtCore, _QtGui, _QtWidgets = _qt()
        out = []
        for row in range(self.table.rowCount()):
            record: dict[str, Any] = {}
            filled = False
            for c, column in enumerate(self.columns):
                item = self.table.item(row, c)
                if column.kind == "flag":
                    record[column.key] = (
                        item is not None and item.checkState() == QtCore.Qt.CheckState.Checked
                    )
                    continue
                text = item.text() if item is not None else ""
                filled = filled or bool(text.strip())
                record[column.key] = cell_value(column.kind, text)
            if filled:
                out.append(record)
        return out


_BLOCK = (Column("places", "Decimal places", "number"), Column("plus_minus", "Plus or minus", "number"))


class DrawingSettingsDialog:
    """Settings > Drawing Settings (see the module notes). ``settings`` and ``problems``
    are :func:`load_settings`'s (read from ``path`` when ``settings`` is None); ``path``
    is the settings file, ``Drawing.json`` in the user's settings folder unless given;
    ``page`` is the page to open on (the first first-use page when None). OK and Apply
    save, then call ``on_saved`` with the settings saved. ``dialog`` is the QDialog."""

    def __init__(
        self,
        parent: Any = None,
        settings: drawing_settings.DrawingSettings | None = None,
        problems: Any = (),
        *,
        path: str | os.PathLike | None = None,
        page: str | None = None,
        on_saved: Callable[[drawing_settings.DrawingSettings], None] | None = None,
    ) -> None:
        QtCore, _QtGui, QtWidgets = _qt()
        self.path = os.fspath(path) if path is not None else drawing_settings.settings_path()
        if settings is None:
            settings, problems = drawing_settings.load_settings(self.path)
        self.settings = settings
        self.problems = list(problems)
        self.on_saved = on_saved
        self.refused: list[tuple[str, str, str]] = []  # (page, label, reason) of the last OK or Apply
        self.bindings: list[_Binding] = []
        self._logo_png: bytes | None = None  # chosen, written when the settings are saved
        self._logo_sha: str | None = None
        self._logo_removed = False

        self.dialog = QtWidgets.QDialog(parent)
        self.dialog.setWindowTitle("Drawing Settings")
        self.dialog.resize(940, 680)

        self.problems_label = _plain_label("")
        self.first_use_label = _plain_label("")
        self.errors_label = _plain_label("")
        bold = self.errors_label.font()
        bold.setBold(True)
        self.errors_label.setFont(bold)

        self.page_list = QtWidgets.QListWidget()
        self.page_list.setMaximumWidth(220)
        self.stack = QtWidgets.QStackedWidget()
        for index, spec in enumerate(PAGES):
            self.page_list.addItem(spec.title)
            self.stack.addWidget(self._page(index, spec))
        self.page_list.currentRowChanged.connect(self.stack.setCurrentIndex)
        middle = QtWidgets.QHBoxLayout()
        middle.addWidget(self.page_list)
        middle.addWidget(self.stack, 1)

        where = _plain_label(f"Drawing Settings are kept in {self.path}", note=True)
        where.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
            | QtWidgets.QDialogButtonBox.StandardButton.Apply
            | QtWidgets.QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.accepted.connect(self.ok)
        buttons.rejected.connect(self.dialog.reject)
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply)
        restore = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.RestoreDefaults)
        restore.setToolTip("Restore this page's settings as they come")
        restore.clicked.connect(lambda: self.restore_defaults())
        self.buttons = buttons

        layout = QtWidgets.QVBoxLayout(self.dialog)
        for label in (self.problems_label, self.first_use_label, self.errors_label):
            layout.addWidget(label)
        layout.addLayout(middle, 1)
        layout.addWidget(where)
        layout.addWidget(buttons)

        self.set_values(settings)
        self._show_banners()
        prompts = first_use_prompts(settings)
        self.show_page(page or (prompts[0][0] if prompts else PAGES[0].title))

    # ------------------------------------------------------------------ building
    def _page(self, index: int, spec: Page):
        _QtCore, _QtGui, QtWidgets = _qt()
        body = QtWidgets.QWidget()
        column = QtWidgets.QVBoxLayout(body)
        heading = _plain_label(spec.title)
        font = heading.font()
        font.setPointSizeF(font.pointSizeF() * 1.25)
        font.setBold(True)
        heading.setFont(font)
        column.addWidget(heading)
        if spec.note:
            column.addWidget(_plain_label(spec.note, note=True))
        form = QtWidgets.QFormLayout()
        column.addLayout(form)
        column.addStretch(1)
        for f in spec.fields:
            widget, focus, get, put = self._control(f)
            if f.tip:
                from .wording import tip

                widget.setToolTip(tip(f.tip))
            widget.setEnabled(f.enabled)
            if f.kind == "flag":
                form.addRow(widget)
            elif f.kind in ("records", "per_type"):
                form.addRow(_plain_label(f.label))
                form.addRow(widget)
            else:
                form.addRow(f.label + ":", widget)
            self.bindings.append(_Binding(f, index, focus, get, put))
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        return scroll

    def _control(self, f: Field):
        """The control for ``f``: (the widget laid out, the widget focused, get, put)."""
        _QtCore, _QtGui, QtWidgets = _qt()
        if f.kind in ("records", "block"):
            table = _Table(f.options if f.kind == "records" else _BLOCK)
            if f.kind == "block":

                def get_block():
                    return [[r["places"], r["plus_minus"]] for r in table.records()]

                def put_block(rows):
                    table.set_records({"places": p, "plus_minus": pm} for p, pm in rows)

                return table.widget, table.table, get_block, put_block
            return table.widget, table.table, table.records, table.set_records
        if f.kind == "address":
            holder = QtWidgets.QWidget()
            lines = QtWidgets.QVBoxLayout(holder)
            lines.setContentsMargins(0, 0, 0, 0)
            edits = [QtWidgets.QLineEdit() for _ in range(4)]
            for edit in edits:
                lines.addWidget(edit)

            def put_address(values):
                values = list(values or ())
                for k, edit in enumerate(edits):
                    edit.setText(values[k] if k < len(values) else "")

            return holder, edits[0], lambda: address_value([e.text() for e in edits]), put_address
        if f.kind == "mapping":
            holder = QtWidgets.QWidget()
            row = QtWidgets.QHBoxLayout(holder)
            row.setContentsMargins(0, 0, 0, 0)
            parts = []
            for column in f.options:
                widget, get, put = _editor(column.kind, column.options)
                if column.kind == "number":
                    widget.setMaximumWidth(80)
                row.addWidget(QtWidgets.QLabel(column.label))
                row.addWidget(widget)
                parts.append((column.key, widget, get, put))
            row.addStretch(1)

            def put_mapping(value):
                for key, _w, _get, put in parts:
                    put((value or {}).get(key))

            return holder, parts[0][1], lambda: {k: get() for k, _w, get, _p in parts}, put_mapping
        if f.kind == "per_type":
            holder = QtWidgets.QWidget()
            row = QtWidgets.QHBoxLayout(holder)
            row.setContentsMargins(0, 0, 0, 0)
            groups = []
            for kind in drawing_settings.TYPES:
                box = QtWidgets.QGroupBox(_TYPE_LABELS[kind])
                form = QtWidgets.QFormLayout(box)
                parts = []
                for column in f.options:
                    widget, get, put = _editor(column.kind, column.options, column.label)
                    if column.kind == "flag":
                        form.addRow(widget)
                    else:
                        form.addRow(column.label + ":", widget)
                    parts.append((column.key, widget, get, put))
                row.addWidget(box)
                groups.append((kind, parts))

            def get_per_type():
                return {kind: {k: get() for k, _w, get, _p in parts} for kind, parts in groups}

            def put_per_type(value):
                for kind, parts in groups:
                    for key, _w, _get, put in parts:
                        put(((value or {}).get(kind) or {}).get(key))

            return holder, groups[0][1][0][1], get_per_type, put_per_type
        if f.kind == "logo":
            return self._logo_control()
        if f.kind == "folder":
            holder = QtWidgets.QWidget()
            row = QtWidgets.QHBoxLayout(holder)
            row.setContentsMargins(0, 0, 0, 0)
            edit = QtWidgets.QLineEdit()
            edit.setPlaceholderText("Next to the part")
            choose = QtWidgets.QPushButton("Choose Folder...")
            choose.clicked.connect(lambda: self._choose_folder(edit))
            row.addWidget(edit, 1)
            row.addWidget(choose)
            return (
                holder,
                edit,
                lambda: edit.text().strip() or None,
                lambda v: edit.setText("" if v is None else str(v)),
            )
        widget, get, put = _editor(f.kind, f.options, f.label)
        return widget, widget, get, put

    def _choose_folder(self, edit) -> None:  # pragma: no cover - a system dialog
        _QtCore, _QtGui, QtWidgets = _qt()
        folder = QtWidgets.QFileDialog.getExistingDirectory(self.dialog, "Save Drawings In", edit.text())
        if folder:
            edit.setText(os.path.normpath(folder))

    def _logo_control(self):
        QtCore, _QtGui, QtWidgets = _qt()
        holder = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        self.logo_preview = QtWidgets.QLabel()
        self.logo_preview.setFixedSize(240, 80)
        self.logo_preview.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.logo_status = _plain_label("")
        choose = QtWidgets.QPushButton("Choose...")
        choose.clicked.connect(self._choose_logo_file)
        remove = QtWidgets.QPushButton("Remove")
        remove.clicked.connect(self.remove_logo)
        row.addWidget(self.logo_preview)
        row.addWidget(self.logo_status, 1)
        row.addWidget(choose)
        row.addWidget(remove)
        return holder, choose, lambda: self._logo_sha, self._put_logo

    def _put_logo(self, sha: str | None) -> None:
        """Show the logo ``sha`` names (the one saved); None removes it when saved."""
        self._logo_png = None
        if sha is None:
            self._logo_removed = self._logo_sha is not None or self._logo_removed
            self._logo_sha = None
            self._show_logo(None, "No logo")
            return
        self._logo_sha, self._logo_removed = sha, False
        png, problem = read_logo(self.path, sha)
        if problem is not None:
            self._show_logo(None, f"The logo is not used: {problem}. Choose it again.")
        else:
            w, h = png_size(png)
            self._show_logo(png, f"{w} x {h} pixels, {max(1, len(png) // 1024)} KiB")

    def _show_logo(self, png: bytes | None, text: str) -> None:
        QtCore, QtGui, _QtWidgets = _qt()
        self.logo_status.setText(text)
        self.logo_preview.clear()
        if png is not None:
            pixmap = QtGui.QPixmap()
            if pixmap.loadFromData(png, "PNG"):
                self.logo_preview.setPixmap(
                    pixmap.scaled(
                        self.logo_preview.size(),
                        QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                        QtCore.Qt.TransformationMode.SmoothTransformation,
                    )
                )

    def _choose_logo_file(self) -> None:  # pragma: no cover - a system dialog
        _QtCore, _QtGui, QtWidgets = _qt()
        source, _ = QtWidgets.QFileDialog.getOpenFileName(self.dialog, "Choose the Logo", "", IMAGE_FILTER)
        if source:
            self.choose_logo(source)

    # ------------------------------------------------------------------ the logo
    def choose_logo(self, source: str) -> bool:
        """Make the logo from the image at ``source``; it is written when the settings are
        saved. False, with the reason shown beside it, when it cannot be one."""
        try:
            png = logo_png(source)
        except LogoRefused as exc:
            self.logo_status.setText(f"That image cannot be the logo: {exc}.")
            return False
        self._logo_png, self._logo_sha, self._logo_removed = png, hashlib.sha256(png).hexdigest(), False
        w, h = png_size(png)
        self._show_logo(png, f"{w} x {h} pixels, {max(1, len(png) // 1024)} KiB, saved with the settings")
        return True

    def remove_logo(self) -> None:
        """No logo; logo.png is removed when the settings are saved."""
        self._put_logo(None)

    # ------------------------------------------------------------------ values
    def set_values(self, settings: drawing_settings.DrawingSettings) -> None:
        """Show ``settings`` in every control."""
        for b in self.bindings:
            b.put(getattr(getattr(settings, b.field.group), b.field.key))

    def restore_defaults(self, page: str | None = None) -> None:
        """Show the settings of ``page`` (the one shown when None) as they come."""
        index = self.stack.currentIndex() if page is None else self._page_index(page)
        for b in self.bindings:
            if b.page == index:
                b.put(default_value(b.field.group, b.field.key))

    def collect(self) -> tuple[drawing_settings.DrawingSettings, list[tuple[_Binding, str]]]:
        """The settings the controls hold, each value checked as loading checks it, and
        the values refused with their reasons. Members a newer SolidSeas wrote are kept."""
        new = self.settings
        refused: list[tuple[_Binding, str]] = []
        for b in self.bindings:
            raw = b.get()
            try:
                new = drawing_settings.with_value(new, b.field.group, b.field.key, raw)
            except InvalidArgumentError as exc:
                refused.append((b, refusal_reason(str(exc))))
                continue
            extra = EXTRA_CHECKS.get((b.field.group, b.field.key))
            reason = extra(raw) if extra is not None else None
            if reason is not None:
                refused.append((b, reason))
        return new, refused

    def apply(self) -> bool:
        """Check and save (the logo first, then ``Drawing.json``); whether they were.
        A refused value, or a file that could not be written, saves nothing and says why
        at the top."""
        new, refused = self.collect()
        self.refused = [(PAGES[b.page].title, b.field.label, reason) for b, reason in refused]
        if refused:
            self._mark_pages({b.page for b, _ in refused})
            first = refused[0][0]
            self.page_list.setCurrentRow(first.page)
            first.widget.setFocus()
            lines = [f"{page} > {label}: {reason}" for page, label, reason in self.refused]
            self.errors_label.setText("Nothing was saved. Correct these first:\n" + "\n".join(lines))
            self.errors_label.show()
            return False
        try:
            if self._logo_png is not None:
                save_logo(self.path, self._logo_png)
            elif self._logo_removed and new.company.logo is None:
                remove_logo(self.path)
            drawing_settings.save_settings(new, self.path)
        except (OSError, SolidSeasError) as exc:
            reason = getattr(exc, "strerror", None) or str(exc)
            self.refused = [("", "", f"the settings could not be saved: {reason}")]
            self.errors_label.setText(f"Nothing was saved: {reason}")
            self.errors_label.show()
            return False
        self.settings = new
        self.problems = []
        self.refused = []
        self._logo_png, self._logo_removed = None, False
        self._mark_pages(set())
        self._show_banners()
        if self.on_saved is not None:
            self.on_saved(new)
        return True

    def ok(self) -> None:
        if self.apply():
            self.dialog.accept()

    # ------------------------------------------------------------------ pages and banners
    def _page_index(self, title: str) -> int:
        for index, spec in enumerate(PAGES):
            if spec.title == title:
                return index
        raise InvalidArgumentError(f"there is no page {title!r}", detail={"parameter": "page"})

    def show_page(self, title: str) -> None:
        self.page_list.setCurrentRow(self._page_index(title))

    def current_page(self) -> str:
        return PAGES[self.stack.currentIndex()].title

    def marked_pages(self) -> dict[str, str]:
        """The pages marked in the list: ``refused`` (a value there was refused) or
        ``first use`` (a value there waits for the user's first answer)."""
        return dict(self._marks)

    def _mark_pages(self, refused: set[int]) -> None:
        _QtCore, QtGui, QtWidgets = _qt()
        waiting = {self._page_index(p) for p, _ in first_use_prompts(self.settings) if p}
        style = self.dialog.style()
        self._marks: dict[str, str] = {}
        for index in range(self.page_list.count()):
            item = self.page_list.item(index)
            if index in refused:
                item.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MessageBoxWarning))
                self._marks[PAGES[index].title] = "refused"
            elif index in waiting:
                item.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MessageBoxInformation))
                self._marks[PAGES[index].title] = "first use"
            else:
                item.setIcon(QtGui.QIcon())

    def _show_banners(self) -> None:
        if self.problems:
            self.problems_label.setText(
                "These settings could not be read and use their defaults until you save:\n"
                + "\n".join(self.problems)
            )
        self.problems_label.setVisible(bool(self.problems))
        prompts = first_use_prompts(self.settings)
        if prompts:
            self.first_use_label.setText(
                "Before your first drawing:\n" + "\n".join(text for _p, text in prompts)
            )
        self.first_use_label.setVisible(bool(prompts))
        if not self.refused:
            self.errors_label.clear()
            self.errors_label.hide()
        self._mark_pages(set())

    # ------------------------------------------------------------------ the dialog
    def exec(self) -> int:  # pragma: no cover - modal
        return self.dialog.exec()

    def show(self) -> None:
        self.dialog.show()

    def close(self) -> None:
        self.dialog.close()


def _every_setting() -> set[tuple[str, str]]:
    """Every ``group.key`` of Drawing Settings, for the check that each has a control."""
    return {(group, f.name) for group, cls in drawing_settings.GROUPS.items() for f in fields(cls)}


__all__ = [
    "EXTRA_CHECKS",
    "FIRST_USE",
    "PAGES",
    "Column",
    "DrawingSettingsDialog",
    "Field",
    "LogoRefused",
    "Page",
    "address_value",
    "cell_text",
    "cell_value",
    "default_value",
    "first_use_prompts",
    "logo_path",
    "logo_png",
    "names_text",
    "number_text",
    "page_of",
    "parse_lines",
    "parse_names",
    "parse_number",
    "read_logo",
    "remove_logo",
    "save_logo",
]
