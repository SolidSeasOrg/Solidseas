"""Settings > Drawing Settings (``solidseas_app.viewer.drawingsettings``;
``docs/DRAWINGS.md`` 7 and 15.2).

The page table, the conversions between values and what a control shows, the
first-use prompts and the logo file are tested everywhere, without Qt. The dialog
needs PySide6 and is skipped without it; it runs offscreen
(``QT_QPA_PLATFORM=offscreen``), on settings files under each test's own
temporary folder, never the user's, and never opens a system dialog: the logo is
chosen from an image the test writes there. The people and company are the fictional
"Example Engineering Co." and its staff.
"""

import hashlib
import json
import os
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

from solidseas.drawing import settings as drawing_settings
from solidseas_app.viewer import drawingsettings as ds

try:
    import PySide6.QtWidgets  # noqa: F401
except ImportError:  # the dialog's tests need the [app] extra
    HAVE_QT = False
else:
    HAVE_QT = True

needs_qt = pytest.mark.skipif(not HAVE_QT, reason="PySide6 is not installed: the dialog is not tested")
COMPANY = "Example Engineering Co."
PAGE_TITLES = [
    "Company",
    "People and Approvals",
    "Standard and Units",
    "Sheets",
    "Title Block",
    "Tolerances",
    "Geometric Tolerances",
    "Printing",
    "Notes",
    "Materials and Finishes",
    "Default Views",
    "Dimensioning",
    "Files",
    "Email",
    "Limits",
]


def png_bytes(width: int, height: int, depth: int = 8, colour: int = 6, interlace: int = 0) -> bytes:
    """A small PNG made by hand: one IHDR, one IDAT of zeros, IEND."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0, interlace)
    channels = {2: 3, 6: 4}.get(colour, 1)
    rows = b"".join(b"\x00" + bytes(width * channels) for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def change(settings, **values):
    for path, value in values.items():
        group, key = path.split("__")
        settings = drawing_settings.with_value(settings, group, key, value)
    return settings


# --------------------------------------------------------------------------- the pages (no Qt)
def test_every_setting_has_one_control():
    bound = [(f.group, f.key) for page in ds.PAGES for f in page.fields]
    assert len(bound) == len(set(bound))
    assert set(bound) == ds._every_setting()


def test_the_pages_are_those_of_the_design():
    assert [page.title for page in ds.PAGES] == PAGE_TITLES
    assert ds.page_of("email", "webmail_url") == "Email" and ds.page_of("email", "nothing") is None
    assert "Your company's tolerances" in ds.PAGES[PAGE_TITLES.index("Tolerances")].note
    assert (
        "Service bureau figures; replace them with your own" in ds.PAGES[PAGE_TITLES.index("Printing")].note
    )


def _choices():
    for page in ds.PAGES:
        for f in page.fields:
            if f.kind in ("choice", "checks"):
                yield f.group, f.key, f.kind, f.options
            for column in f.options if f.kind in ("mapping", "per_type") else ():
                if column.kind in ("choice", "checks"):
                    yield f.group, f.key, column.key, column.options


def test_every_choice_offered_is_one_the_setting_takes():
    base = drawing_settings.DrawingSettings()
    for group, key, part, options in _choices():
        current = ds.default_value(group, key)
        for value, _label in options:
            if part == "choice":
                candidate = value
            elif part == "checks":
                candidate = [value]
            elif group == "defaults":  # one value of a per-type group
                candidate = {
                    t: {**current[t], part: [value] if isinstance(current[t][part], tuple) else value}
                    for t in current
                }
            else:  # one key of a mapping
                candidate = {**current, part: value}
            if (group, key, part) == ("people", "required", "checks"):
                continue  # any approval row may be required
            drawing_settings.with_value(base, group, key, candidate)


def test_numbers_show_as_typed_and_read_back_equal():
    for value in (0, 3, 0.01, 0.25, 1240.0, 1e-05, 0.005, 25000.0, 2.5):
        text = ds.number_text(value)
        assert ds.parse_number(text) == value
    assert ds.number_text(1240.0) == "1240" and ds.number_text(0.01) == "0.01" and ds.number_text(None) == ""
    assert ds.parse_number(" 2 ") == 2 and isinstance(ds.parse_number("2"), int)
    assert ds.parse_number("") == "" and ds.parse_number("", optional=True) is None
    assert ds.parse_number("0,5") == "0,5"  # the setting's check refuses it with its reason


def test_lists_show_as_text_and_read_back():
    assert ds.parse_names("PartNo; Part Number;;  PartNumber ") == ["PartNo", "Part Number", "PartNumber"]
    assert ds.names_text(("1:1", "1:2"), ", ") == "1:1, 1:2"
    assert ds.parse_names("1:1, 1:2,", ", ") == ["1:1", "1:2"]
    assert ds.parse_lines("A.\n\n  B. \n") == ["A.", "B."]
    assert ds.address_value(["1 Main St", "", "Anytown", ""]) == ["1 Main St", "", "Anytown"]
    assert ds.cell_value("kinds", "Machined, printed") == ["machined", "printed"]
    assert ds.cell_text("kinds", ("machined",)) == "machined"
    assert ds.cell_value("optional_number", "") is None and ds.cell_text("optional_number", None) == ""
    assert ds.cell_value("names", "pla; PLA+") == ["pla", "PLA+"]


def test_first_use_prompts_name_their_pages():
    prompts = ds.first_use_prompts(drawing_settings.DrawingSettings())
    assert [page for page, _ in prompts] == ["Standard and Units", "Company", "People and Approvals"]
    assert all(text for _, text in prompts)
    done = change(
        drawing_settings.DrawingSettings(),
        standard__unit_for_unstated="in",
        company__name=COMPANY,
        people__people=[{"name": "Ann Bee", "initials": "AB"}],
    )
    assert ds.first_use_prompts(done) == []


def test_the_logo_file_is_read_written_and_removed_beside_the_settings(tmp_path):
    settings_file = str(tmp_path / "SolidSeas" / "Drawing.json")
    good = png_bytes(4, 2)
    sha = hashlib.sha256(good).hexdigest()
    assert ds.read_logo(settings_file, None) == (None, None)
    assert ds.read_logo(settings_file, sha) == (None, "logo.png is not beside the settings")
    written = ds.save_logo(settings_file, good)
    assert written == str(tmp_path / "SolidSeas" / "logo.png") == ds.logo_path(settings_file)
    assert ds.read_logo(settings_file, sha) == (good, None)
    assert ds.png_size(good) == (4, 2)
    assert "match" in ds.read_logo(settings_file, "0" * 64)[1]
    ds.save_logo(settings_file, png_bytes(4, 2, interlace=1))  # replaced through a rename
    assert (
        "interlacing"
        in ds.read_logo(settings_file, hashlib.sha256(Path(written).read_bytes()).hexdigest())[1]
    )
    assert ds.remove_logo(settings_file) is True and not os.path.exists(written)
    assert ds.remove_logo(settings_file) is False


def test_a_link_at_the_logo_is_not_removed(tmp_path):
    settings_file = str(tmp_path / "Drawing.json")
    target = tmp_path / "elsewhere.png"
    target.write_bytes(png_bytes(1, 1))
    try:
        os.symlink(target, ds.logo_path(settings_file))
    except (OSError, NotImplementedError):
        pytest.skip("this system cannot make a symbolic link here")
    assert ds.remove_logo(settings_file) is False and target.exists()
    assert (
        ds.read_logo(settings_file, hashlib.sha256(target.read_bytes()).hexdigest())[1]
        == "logo.png is not a file"
    )


def test_the_modules_import_without_qt():
    src = str(Path(__file__).resolve().parent.parent / "src")
    code = (
        "import sys\n"
        "import solidseas_app.viewer.drawingsettings\n"
        "import solidseas_app.viewer.mail\n"
        "import solidseas_app.viewer.mailproc\n"
        "assert 'PySide6' not in sys.modules, 'Qt was imported'\n"
    )
    env = {**os.environ, "PYTHONPATH": src + os.pathsep + os.environ.get("PYTHONPATH", "")}
    done = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr


# --------------------------------------------------------------------------- the dialog
@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from solidseas_app.viewer.app import use_system_fonts

    use_system_fonts()
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings_file(tmp_path) -> Path:
    return tmp_path / "SolidSeas" / "Drawing.json"


def _binding(dialog, group, key):
    return next(b for b in dialog.bindings if (b.field.group, b.field.key) == (group, key))


def _shown(label) -> bool:
    return not label.isHidden()


def _filled():
    """Settings past their first use, with a member a newer SolidSeas wrote."""
    settings = change(
        drawing_settings.DrawingSettings(),
        company__name=COMPANY,
        company__address=["1 Example Way", "Anytown"],
        people__people=[{"name": "Ann Bee", "initials": "AB"}, {"name": "Cy Dee", "initials": "CD"}],
        standard__unit_for_unstated="mm",
        email__method="webmail",
    )
    data = drawing_settings.to_dict(settings)
    data["company"]["fax"] = "555-0100"
    data["future"] = {"x": 1}
    loaded, problems = drawing_settings.from_dict(data)
    assert problems == [] and loaded.unknown
    return loaded


@needs_qt
def test_the_dialog_round_trips_the_settings(app, settings_file):
    settings = _filled()
    saved = []
    dialog = ds.DrawingSettingsDialog(None, settings, path=settings_file, on_saved=saved.append)
    try:
        assert dialog.collect() == (settings, [])  # every control shows its setting as it is
        assert dialog.current_page() == "Company" and dialog.marked_pages() == {}
        assert not _shown(dialog.first_use_label) and not _shown(dialog.problems_label)

        _binding(dialog, "company", "phone").widget.setText("555-0199")
        _binding(dialog, "company", "do_not_scale").widget.setChecked(False)
        unit = _binding(dialog, "standard", "units").widget
        unit.setCurrentIndex(unit.findText("Inch"))
        people = _binding(dialog, "people", "people")
        table = people.widget
        assert table.rowCount() == 2
        row = table.rowCount()
        table.insertRow(row)
        from PySide6.QtWidgets import QTableWidgetItem

        table.setItem(row, 0, QTableWidgetItem("Eve Fox"))
        table.setItem(row, 1, QTableWidgetItem("EF"))
        _binding(dialog, "tolerances", "angle").widget.setText("1")
        _binding(dialog, "sheets", "scales").widget.setText("1:1, 1:2, 2:1")
        precision = _binding(dialog, "tolerances", "precision_in")
        values = precision.get()
        precision.put({**values, "hole_size": 4})
        views = _binding(dialog, "defaults", "views")
        views.put(
            {
                **views.get(),
                "machined": {**views.get()["machined"], "hidden": True, "views": ["front", "top"]},
            }
        )
        _binding(dialog, "email", "prefill_subject").widget.setChecked(False)
        assert _binding(dialog, "files", "folder").get() is None  # empty: next to the part
        _binding(dialog, "notes", "machined").widget.setPlainText("REMOVE ALL BURRS.\n\nFINISH: {finish}.")

        assert dialog.apply() is True
        loaded, problems = drawing_settings.load_settings(settings_file)
        assert problems == [] and loaded == dialog.settings == saved[-1]
        assert loaded.company.phone == "555-0199" and loaded.company.do_not_scale is False
        assert loaded.standard.units == "in"
        assert [p["name"] for p in loaded.people.people] == ["Ann Bee", "Cy Dee", "Eve Fox"]
        assert loaded.tolerances.angle == 1.0 and loaded.tolerances.precision_in["hole_size"] == 4
        assert loaded.sheets.scales == ("1:1", "1:2", "2:1")
        assert loaded.defaults.views["machined"]["hidden"] is True
        assert loaded.defaults.views["machined"]["views"] == ("front", "top")
        assert loaded.defaults.views["printed"] == settings.defaults.views["printed"]
        assert loaded.email.prefill_subject is False and loaded.email.method == "webmail"
        assert loaded.notes.machined == ("REMOVE ALL BURRS.", "FINISH: {finish}.")
        assert loaded.files.folder is None
        # Everything else as it was, and what a newer SolidSeas wrote kept.
        assert loaded.materials == settings.materials and loaded.printing == settings.printing
        raw = json.loads(settings_file.read_text("utf-8"))
        assert raw["company"]["fax"] == "555-0100" and raw["future"] == {"x": 1}

        reopened = ds.DrawingSettingsDialog(None, path=settings_file)  # read from the file
        try:
            assert reopened.collect() == (loaded, [])
        finally:
            reopened.close()
    finally:
        dialog.close()


@needs_qt
def test_a_value_that_fails_its_check_is_refused_with_its_reason(app, settings_file):
    dialog = ds.DrawingSettingsDialog(None, _filled(), path=settings_file)
    try:
        _binding(dialog, "tolerances", "angle").widget.setText("abc")
        _binding(dialog, "email", "webmail_url").widget.setText("http://mail.example.com/?su={subject}")
        assert dialog.apply() is False
        assert not settings_file.exists()  # nothing saved
        assert dialog.refused == [
            ("Tolerances", "Angles, plus or minus (degrees)", "it is not a number"),
            ("Email", "Webmail compose address", "it must start with https://"),
        ]
        assert dialog.current_page() == "Tolerances"
        assert dialog.marked_pages() == {"Tolerances": "refused", "Email": "refused"}
        text = dialog.errors_label.text()
        assert (
            text.startswith("Nothing was saved.") and "Email > Webmail compose address: it must start" in text
        )
        assert _shown(dialog.errors_label)

        # The address passes the settings' own check but not Email PDF's.
        _binding(dialog, "tolerances", "angle").widget.setText("0.25")
        _binding(dialog, "email", "webmail_url").widget.setText("https://mail.example.com/?su={Subject}")
        assert dialog.apply() is False
        assert dialog.refused == [("Email", "Webmail compose address", "it may hold only {subject} and {to}")]
        assert dialog.current_page() == "Email"

        # A list entry is named by its row; a scale and a file name pattern by their reasons.
        _binding(dialog, "email", "webmail_url").widget.setText("https://mail.example.com/?su={subject}")
        table = _binding(dialog, "people", "people").widget
        from PySide6.QtWidgets import QTableWidgetItem

        table.setItem(0, 0, QTableWidgetItem(""))
        _binding(dialog, "sheets", "scales").widget.setText("1:1, 1-2")
        _binding(dialog, "files", "name_pattern").widget.setText("{title}")
        assert dialog.apply() is False
        assert dialog.refused == [
            ("People and Approvals", "People", "row 1: it is empty"),
            ("Sheets", "Scales offered", "it is not a scale such as 1:2"),
            (
                "Files",
                "File name",
                "it must hold {number} and may hold {revision}, {title} and {part_number}",
            ),
        ]
        table.setItem(0, 0, QTableWidgetItem("Ann Bee"))
        _binding(dialog, "sheets", "scales").widget.setText("1:1, 1:2")
        _binding(dialog, "files", "name_pattern").widget.setText("{number} {revision}")
        assert dialog.apply() is True and settings_file.exists()
        assert dialog.refused == [] and not _shown(dialog.errors_label) and dialog.marked_pages() == {}
        assert (
            drawing_settings.load_settings(settings_file)[0].email.webmail_url
            == "https://mail.example.com/?su={subject}"
        )
    finally:
        dialog.close()


@needs_qt
def test_cancel_discards_and_restore_defaults_acts_on_one_page(app, settings_file):
    from PySide6.QtWidgets import QDialog, QDialogButtonBox

    settings = _filled()
    dialog = ds.DrawingSettingsDialog(None, settings, path=settings_file)
    try:
        _binding(dialog, "company", "name").widget.setText("Another Name")
        dialog.show_page("Email")
        method = _binding(dialog, "email", "method").widget
        method.setCurrentIndex(2)
        assert dialog.collect()[0].email.method == "show"
        dialog.restore_defaults()  # the page shown: Email
        new = dialog.collect()[0]
        assert new.email == drawing_settings.Email() and new.company.name == "Another Name"
        dialog.restore_defaults("Company")
        assert dialog.collect()[0].company == drawing_settings.Company()
        dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel).click()
        assert dialog.dialog.result() == QDialog.DialogCode.Rejected
        assert not settings_file.exists() and dialog.settings == settings
    finally:
        dialog.close()
    saved = []
    dialog = ds.DrawingSettingsDialog(None, settings, path=settings_file, on_saved=saved.append)
    try:
        _binding(dialog, "people", "rows").put(["CHECKED", "DRAWN"])  # a hand-edited order is kept
        dialog.buttons.button(QDialogButtonBox.StandardButton.Apply).click()
        assert dialog.settings.people.rows == ("CHECKED", "DRAWN") and len(saved) == 1
        _binding(dialog, "company", "name").widget.setText("")
        dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).click()
        assert dialog.dialog.result() == QDialog.DialogCode.Accepted and len(saved) == 2
        assert drawing_settings.load_settings(settings_file)[0] == saved[-1]
        assert saved[-1].company.name == "" and saved[-1].first_use() == ("company.name",)
    finally:
        dialog.close()


@needs_qt
def test_first_use_prompts_open_the_missing_page(app, settings_file):
    dialog = ds.DrawingSettingsDialog(None, drawing_settings.DrawingSettings(), path=settings_file)
    try:
        assert dialog.current_page() == "Standard and Units"
        text = dialog.first_use_label.text()
        assert text.startswith("Before your first drawing:") and _shown(dialog.first_use_label)
        for _page, prompt in ds.first_use_prompts(dialog.settings):
            assert prompt in text
        assert dialog.marked_pages() == {
            "Company": "first use",
            "People and Approvals": "first use",
            "Standard and Units": "first use",
        }
        unstated = _binding(dialog, "standard", "unit_for_unstated").widget
        assert unstated.currentText() == "Not chosen yet"
        unstated.setCurrentIndex(unstated.findText("Inch"))
        _binding(dialog, "company", "name").widget.setText(COMPANY)
        assert dialog.apply() is True
        assert dialog.marked_pages() == {"People and Approvals": "first use"}
        assert (
            "People and Approvals" in dialog.first_use_label.text()
            and "Company)" not in dialog.first_use_label.text()
        )
        _binding(dialog, "people", "people").put([{"name": "Ann Bee", "initials": "AB"}])
        assert dialog.apply() is True
        assert not _shown(dialog.first_use_label) and dialog.marked_pages() == {}
        assert drawing_settings.load_settings(settings_file)[0].first_use() == ()
    finally:
        dialog.close()
    on_page = ds.DrawingSettingsDialog(
        None, drawing_settings.DrawingSettings(), path=settings_file, page="Email"
    )
    try:
        assert on_page.current_page() == "Email"
    finally:
        on_page.close()


@needs_qt
def test_fallbacks_are_listed_until_saved(app, settings_file):
    settings_file.parent.mkdir(parents=True)
    data = drawing_settings.to_dict(_filled())
    data["company"]["phone"] = 5
    settings_file.write_text(json.dumps(data), "utf-8")
    dialog = ds.DrawingSettingsDialog(None, path=settings_file)
    try:
        assert _shown(dialog.problems_label)
        assert "company.phone: it is not text; the default is used" in dialog.problems_label.text()
        assert dialog.apply() is True
        assert not _shown(dialog.problems_label)
        assert drawing_settings.load_settings(settings_file)[1] == []
    finally:
        dialog.close()


def _image(
    path: Path, width: int, height: int, *, alpha: bool, fmt: str = "PNG", text: str | None = None
) -> Path:
    from PySide6.QtGui import QColor, QImage, QPainter

    image = QImage(width, height, QImage.Format.Format_ARGB32 if alpha else QImage.Format.Format_RGB32)
    image.fill(QColor(255, 255, 255, 0 if alpha else 255))
    painter = QPainter(image)
    painter.fillRect(
        width // 8, height // 8, width // 2, height // 2, QColor(20, 60, 160, 200 if alpha else 255)
    )
    painter.end()
    if text:
        image.setText("Author", text)
    assert image.save(str(path), fmt)
    return path


@needs_qt
def test_a_logo_is_scaled_written_beside_the_settings_and_recorded(app, settings_file, tmp_path):
    source = _image(tmp_path / "logo source.png", 2400, 1200, alpha=True, text="Somebody Private")
    dialog = ds.DrawingSettingsDialog(None, _filled(), path=settings_file)
    try:
        assert dialog.choose_logo(str(source)) is True
        assert "1200 x 600 pixels" in dialog.logo_status.text()
        assert not (settings_file.parent / "logo.png").exists()  # written only when saved
        assert dialog.apply() is True
        logo = settings_file.parent / "logo.png"
        png = logo.read_bytes()
        loaded = drawing_settings.load_settings(settings_file)[0]
        assert loaded.company.logo == hashlib.sha256(png).hexdigest()
        assert drawing_settings.logo_problem(png, loaded.company.logo) is None
        assert ds.png_size(png) == (1200, 600) and png[24:29] == bytes(
            (8, 6, 0, 0, 0)
        )  # 8-bit RGBA, no interlace
        assert len(png) <= ds.LOGO_BYTES
        assert b"Somebody" not in png and b"tEXt" not in png and b"iCCP" not in png
    finally:
        dialog.close()
    # Opened again, the logo shows; a photograph without alpha becomes RGB; Remove takes it away.
    again = ds.DrawingSettingsDialog(None, path=settings_file)
    try:
        assert "1200 x 600 pixels" in again.logo_status.text()
        photo = _image(tmp_path / "tall.jpg", 600, 1800, alpha=False, fmt="JPG")
        assert again.choose_logo(str(photo)) is True and again.apply() is True
        png = (settings_file.parent / "logo.png").read_bytes()
        assert ds.png_size(png) == (400, 1200) and png[25] == 2  # RGB
        again.remove_logo()
        assert again.apply() is True
        assert not (settings_file.parent / "logo.png").exists()
        assert drawing_settings.load_settings(settings_file)[0].company.logo is None
    finally:
        again.close()


@needs_qt
def test_a_logo_cancelled_is_never_written(app, settings_file, tmp_path):
    source = _image(tmp_path / "logo.png", 300, 100, alpha=False)
    dialog = ds.DrawingSettingsDialog(None, _filled(), path=settings_file)
    try:
        assert dialog.choose_logo(str(source)) is True
        dialog.dialog.reject()
        assert not settings_file.parent.exists()
    finally:
        dialog.close()


@needs_qt
def test_an_image_that_cannot_be_a_logo_is_refused_with_its_reason(app, settings_file, tmp_path):
    from PySide6.QtGui import QImage

    not_image = tmp_path / "notes.png"
    not_image.write_bytes(b"this is not an image")
    dialog = ds.DrawingSettingsDialog(None, _filled(), path=settings_file)
    try:
        assert dialog.choose_logo(str(not_image)) is False
        assert dialog.logo_status.text().startswith("That image cannot be the logo: it could not be read")
        # Noise does not compress: in RGB it fits only once made smaller, in RGBA not even then.
        noise = QImage(os.urandom(1600 * 1600 * 3), 1600, 1600, 1600 * 3, QImage.Format.Format_RGB888)
        assert noise.save(str(tmp_path / "noise.png"))
        png = ds.logo_png(str(tmp_path / "noise.png"))
        assert len(png) <= ds.LOGO_BYTES and max(ds.png_size(png)) < ds.LOGO_PIXELS
        noisy = QImage(os.urandom(1600 * 1600 * 4), 1600, 1600, 1600 * 4, QImage.Format.Format_RGBA8888)
        assert noisy.save(str(tmp_path / "noisy.png"))
        assert dialog.choose_logo(str(tmp_path / "noisy.png")) is False
        assert "larger than 512 KiB" in dialog.logo_status.text()
        assert dialog.collect()[0].company.logo is None
        assert dialog.apply() is True and not (settings_file.parent / "logo.png").exists()
    finally:
        dialog.close()


@needs_qt
def test_a_logo_that_does_not_match_its_record_is_said(app, settings_file):
    settings_file.parent.mkdir(parents=True)
    (settings_file.parent / "logo.png").write_bytes(png_bytes(4, 2))
    settings = change(_filled(), company__logo="0" * 64)
    dialog = ds.DrawingSettingsDialog(None, settings, path=settings_file)
    try:
        assert dialog.logo_status.text() == (
            "The logo is not used: the logo file does not match the one the settings recorded. "
            "Choose it again."
        )
    finally:
        dialog.close()
