"""The viewer's own settings (the General, 3D View and 3D Print pages of the Settings window,
:mod:`.settingswindow`), with Restore Defaults.

The dialog edits a copy: OK and Apply hand the new :class:`.settings.Settings`
to the window through ``applied``, which applies what it can at once and saves
them. Cancel changes nothing.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import experimental
from .mesh3d import MAX_TRIANGLE_CAP, MIN_TRIANGLE_CAP
from .settings import DRAWING_MODE_LABELS, LIST_VIEWS, MAX_RECENT, REINDEX_CHOICES, THUMBNAIL_LABELS, Settings
from .viewmath import FREE, MOUSE_STYLES, SOLIDWORKS, STANDARD, TURNTABLE
from .wording import tip

VIEW_3D_TEXT = "Interactive 3D view of parts and assemblies"
VIEW_3D_NOTE = (
    "Off by default because it costs time. Starting OpenGL holds the whole window for about 0.6 seconds "
    "(measured on a desktop graphics card; a slow driver takes longer): when you turn this on, and when "
    "the viewer starts with it on, before its window appears. The first document shown in 3D takes a "
    "moment more for its first picture. Meshes are then read in a separate process, which takes up to a "
    "few seconds for a very large part or assembly while the window keeps responding. While it is off, "
    "the viewer never reads a mesh or starts OpenGL."
)
BOXES_TEXT = "Draw a box where an assembly's instance has no mesh"
BOXES_NOTE = (
    "Where an assembly has no mesh drawn for an instance (its file is not found, it stores no "
    "display data, or a limit of the 3D view was reached), the 3D view draws the box SOLIDWORKS "
    "stored for it, in translucent grey with dark edges, so the assembly is whole. The box picks, "
    "explodes and opens its file like any other instance; the line under the view counts the boxes."
)
VIEW_3D_STATUS = (
    "Rotate, pan and zoom a part's or an assembly's saved display meshes on the Preview tab. Starting it "
    "holds the window for about 0.6 seconds, and a very large model takes a few seconds to read"
)
MOUSE_NOTE = (
    "Click the 3D view, then the arrow keys turn it 15 degrees (Shift: 90), Page Up and Page Down roll "
    "it, Ctrl+arrows pan, Ctrl+1 to Ctrl+7 give the standard views and Home goes home, so a touchpad "
    "without a middle button can turn it too."
)
MOUSE_TIP = (
    "The preview image pans with any button and zooms with the wheel the same way as the 3D view. "
    "Ctrl+1 to Ctrl+7 are Front, Back, Left, Right, Top, Bottom and Isometric, as in SOLIDWORKS. A "
    "touchpad's sideways two-finger swipe turns the model as the Left and Right keys do."
)
NAVIGATION_ROW = "3D view:"
VIEW_CUBE_TEXT = "View cube"
VIEW_CUBE_TIP = (
    "A cube over the 3D view's top-right corner that turns with the model. Click a face, an edge or a "
    "corner to look from there, Home to go back to the view the document opened with, the arrows "
    "beside it to step to the next face or roll the view; drag it to turn the model; right-click it "
    "to set the current view as Home."
)
POINTER_TEXT = "Turn about the point under the pointer"
POINTER_TIP = (
    "A drag that turns the model turns it about the point of the model under the pointer where the "
    "drag starts, as Fusion 360 and SOLIDWORKS do, so that point stays put. Off, or where nothing is "
    "under the pointer, it turns about the point a fit centres the model on (the middle of the view, or "
    "of the part the legend or the view cube leaves free), at the depth of the model's centre."
)
ROTATION_ROW = "3D rotation:"
ROTATION_LABELS = {FREE: "Free: any view, as in SOLIDWORKS", TURNTABLE: "Turntable: stays upright"}
ROTATION_TIPS = {
    FREE: "Turns the model about the screen's own axes: a drag across about the screen's vertical axis, "
    "a drag up or down about its horizontal axis, with no limit, so every view can be reached, upside "
    "down included.",
    TURNTABLE: "Turns the model about its own vertical axis and tilts it up to straight above or below; it "
    "never rolls, so Page Up and Page Down turn it only looking straight down or up. Choosing it sets a "
    "view turned upside down upright again.",
}
REVERSE_WHEEL_TEXT = "Reverse the wheel's zoom direction"
PRINT_NOTE = (
    "Choose it under Settings > 3D Print Program. It is sent in the format chosen beside it, from those "
    "it takes; a STEP that cannot be made (an assembly, or a part STEP cannot hold) goes as 3MF."
)
PRINT_FORMAT_ROW = "Send as:"
PRINT_HERE_TEXT = "Save 3D print files next to the model"
PRINT_HERE_TIP = (
    "On, 3D Print saves its file in the folder of the model it was made from, named with the date: "
    "bracket 2026-10-03.3mf, and bracket 2026-10-03 (2).3mf for a second one that day, the highest number "
    "of a name and format being the newest. A file that is there is never replaced. Where that folder "
    "cannot take it (read-only, a link or a junction or inside one, a cloud placeholder, a network share "
    "outside the opened folder), and with this off, the file goes to a folder of yours in the system's "
    "temporary folder, where exports older than a week are removed; nothing next to a model is ever removed."
)
PRINT_TIP = "Where it saves its file is set by Save 3D print files next to the model, above."
ALL_FORMATS_TEXT = "List every 3D file SolidSeas reads, not only SOLIDWORKS documents"
ALL_FORMATS_TIP = (
    "STEP, Parasolid, STL, 3MF, OBJ, PLY, OFF, glTF, AMF, ACIS and Alibre Design files are listed with the "
    "SOLIDWORKS documents and read in worker processes of the viewer's own. The quick filter's buttons "
    "under the name filter show one format, or several, at a time."
)
UNREADABLE_TEXT = "List files SolidSeas cannot read yet"
UNREADABLE_TIP = (
    "Files of 3D formats SolidSeas recognises but cannot read yet (Inventor, Solid Edge, VRML...) are "
    "listed, greyed, and never opened. An NX .prt is not listed: other programs use that extension too. "
    "IGES and BREP files are listed either way while the OCCT backend extension is off, saying what opens "
    "them."
)
THUMBNAIL_NOTE = "Thumbnails are made at this size when a folder is listed; press F5 to redo them."
AS_IS_PREF_TEXT = "Open 3MF and STL files as they are"
AS_IS_PREF_TIP = (
    "A 3MF or STL file is opened in the program as it is when it would be sent in its own format (a 3MF "
    "when 3MF or STEP is chosen, an STL when STL is), so a slicer project keeps its plates and settings and "
    "nothing is written; but the program then has your own file open, and saving there replaces it. Off "
    "(the default), it is exported to a new file next to the model like any other file."
)
DRAWINGS_TEXT = "Make drawings of parts and assemblies"
DRAWINGS_TIP = (
    "File > New Drawing and Open Drawing, the Drawing button and Make Drawing in the right-click menus. "
    "Off, they are not shown; Drawing Settings and your drawing files are kept."
)
DRAWING_MODE_TIP = (
    "What the Drawing button and Make Drawing start. Express goes straight to the editor with the key "
    "sizes; Guided asks a few plain questions first; Expert opens the New Drawing wizard with every "
    "option. Ask each time shows the choice."
)
SESSION_NOTE = (
    "Off, the viewer also puts back Qt's record of the last folder its folder dialogs showed. "
    "Windows' own folder dialog keeps a recent folder for each program, which the viewer cannot clear."
)
INSIDE_ONLY_TEXT = "Look for referenced files only in the opened folder"
INSIDE_ONLY_NOTE = (
    "An assembly or a drawing names each file it uses by the path it had when it was saved. Off (the "
    "default), when that path is outside the folder you opened but on a drive of this computer, the "
    "viewer looks there too and reads the file it finds, read-only: it is shown as found there, drawn in "
    "3D, and printed, exported and opened from there. On, only the opened folder and its subfolders are "
    "searched, and a file that is not in them is shown as not found. A network path is never looked at "
    "either way."
)


def _note(text: str) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setContentsMargins(22, 0, 0, 4)
    font = label.font()
    font.setPointSizeF(font.pointSizeF() * 0.92)
    label.setFont(font)
    palette = label.palette()
    palette.setColor(QPalette.ColorRole.WindowText, palette.color(QPalette.ColorRole.PlaceholderText))
    label.setPalette(palette)
    return label


class PreferencesDialog(QDialog):
    """``print_text`` says which program 3D Print opens; ``print_formats`` are the formats
    it takes, offered beside it with ``print_format`` chosen, and a format chosen there
    and applied is handed on through ``print_format_chosen``."""

    applied = Signal(object)  # Settings
    print_format_chosen = Signal(str)  # a 3D Print format chosen and applied

    def __init__(
        self,
        parent: QWidget | None,
        settings: Settings,
        location: str | None,
        *,
        print_text: str | None = None,
        print_formats: tuple[str, ...] = (),
        print_format: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self._initial = settings

        # -- 3D view
        self.view_3d = QCheckBox(VIEW_3D_TEXT)
        self.cap = QSpinBox()
        self.cap.setRange(MIN_TRIANGLE_CAP, MAX_TRIANGLE_CAP)
        self.cap.setSingleStep(100_000)
        self.cap.setGroupSeparatorShown(True)
        self.cap.setSuffix(" triangles")
        self.cap.setToolTip(
            "A part whose saved mesh has more triangles is not drawn. An assembly is drawn until its "
            "meshes reach this many triangles together, counting each component file once; the view "
            "names the instances left out."
        )
        cap_row = QFormLayout()
        cap_row.setContentsMargins(22, 0, 0, 0)
        cap_row.addRow("Read meshes up to:", self.cap)
        self.view_3d.toggled.connect(self.cap.setEnabled)
        self.draw_boxes = QCheckBox(BOXES_TEXT)
        self.draw_boxes.setToolTip(BOXES_NOTE)
        boxes_row = QVBoxLayout()
        boxes_row.setContentsMargins(22, 0, 0, 0)
        boxes_row.addWidget(self.draw_boxes)
        self.view_3d.toggled.connect(self.draw_boxes.setEnabled)
        box_3d = QGroupBox("3D view")
        l3 = QVBoxLayout(box_3d)
        l3.addWidget(self.view_3d)
        l3.addWidget(_note(VIEW_3D_NOTE))
        l3.addLayout(cap_row)
        l3.addLayout(boxes_row)

        # -- the mouse
        self.standard = QRadioButton(MOUSE_STYLES[STANDARD])
        self.standard.setToolTip("As most programs and web 3D viewers do.")
        self.solidworks = QRadioButton(MOUSE_STYLES[SOLIDWORKS])
        self.solidworks.setToolTip("As SOLIDWORKS does out of the box.")
        self.styles = QButtonGroup(self)
        self.styles.addButton(self.standard)
        self.styles.addButton(self.solidworks)
        self.invert_wheel = QCheckBox(REVERSE_WHEEL_TEXT)
        self.invert_wheel.setToolTip(
            "Zoom the other way with the wheel, in either style, like the SOLIDWORKS option "
            "Reverse direction of mouse wheel zoom."
        )
        # Rotation in the 3D view: one row, its explanation in the tooltips, so the dialog
        # still fits a 1080p screen at 125 percent scaling.
        self.free = QRadioButton(ROTATION_LABELS[FREE])
        self.free.setToolTip(ROTATION_TIPS[FREE])
        self.turntable = QRadioButton(ROTATION_LABELS[TURNTABLE])
        self.turntable.setToolTip(ROTATION_TIPS[TURNTABLE])
        self.rotations = QButtonGroup(self)
        self.rotations.addButton(self.free)
        self.rotations.addButton(self.turntable)
        rotation_row = QHBoxLayout()
        rotation_row.addWidget(QLabel(ROTATION_ROW))
        rotation_row.addWidget(self.free)
        rotation_row.addWidget(self.turntable)
        rotation_row.addStretch(1)
        # The view cube on one row too, its explanation in its tooltip.
        self.view_cube = QCheckBox(VIEW_CUBE_TEXT)
        self.view_cube.setToolTip(tip(VIEW_CUBE_TIP))
        navigation_row = QHBoxLayout()
        navigation_row.addWidget(QLabel(NAVIGATION_ROW))
        navigation_row.addWidget(self.view_cube)
        self.turn_about_pointer = QCheckBox(POINTER_TEXT)
        self.turn_about_pointer.setToolTip(tip(POINTER_TIP))
        navigation_row.addWidget(self.turn_about_pointer)
        navigation_row.addStretch(1)
        box_mouse = QGroupBox("Mouse and keys in the Preview tab")
        lm = QVBoxLayout(box_mouse)
        lm.addWidget(self.standard)
        lm.addWidget(self.solidworks)
        lm.addWidget(self.invert_wheel)
        lm.addLayout(rotation_row)
        lm.addLayout(navigation_row)
        mouse_note = _note(MOUSE_NOTE)
        mouse_note.setToolTip(tip(MOUSE_TIP))
        lm.addWidget(mouse_note)

        # -- the document list
        self.list_view = QComboBox()
        for key, label in LIST_VIEWS.items():
            self.list_view.addItem(label, key)
        self.thumbnail_size = QComboBox()
        for key, label in THUMBNAIL_LABELS.items():
            self.thumbnail_size.addItem(label, key)
        # Its note is its tooltip, and the lock files and the files SolidSeas cannot read share
        # a row: the lines the other formats take had to come from somewhere for the dialog to
        # keep within 800 pixels.
        self.thumbnail_size.setToolTip(tip(THUMBNAIL_NOTE))
        self.lock_files = QCheckBox("Show SOLIDWORKS lock files (~$ files)")
        self.all_formats = QCheckBox(ALL_FORMATS_TEXT)
        self.all_formats.setToolTip(tip(ALL_FORMATS_TIP))
        self.unreadable = QCheckBox(UNREADABLE_TEXT)
        self.unreadable.setToolTip(tip(UNREADABLE_TIP))
        shown = QHBoxLayout()
        shown.addWidget(self.lock_files)
        shown.addWidget(self.unreadable)
        shown.addStretch(1)
        box_list = QGroupBox("Document list")
        fl = QFormLayout(box_list)
        fl.addRow("Default view:", self.list_view)
        fl.addRow("Thumbnail size:", self.thumbnail_size)
        fl.addRow(self.all_formats)
        fl.addRow(shown)

        # -- the session
        # Its note is its tooltip: the line Save 3D print files next to the model takes below
        # had to come from somewhere for the dialog to keep within 800 pixels.
        self.remember = QCheckBox("Remember the last folder and the window layout")
        self.remember.setToolTip(tip(SESSION_NOTE))
        box_session = QGroupBox("Starting up")
        ls = QVBoxLayout(box_session)
        ls.addWidget(self.remember)

        # -- each folder's index, and the recent folders
        self.keep_index = QCheckBox("Keep each folder's index and show it again at once")
        self.keep_index.setToolTip(
            tip(
                "Opening a folder you opened before shows the list read then, with how old it is, "
                "instead of reading every file again. Reload (F5) or Re-index reads them again."
            )
        )
        self.reindex_after = QComboBox()
        for hours, text in REINDEX_CHOICES.items():
            self.reindex_after.addItem(text, hours)
        self.reindex_after.setToolTip(
            tip("An index older than this is read again in the background when its folder opens")
        )
        self.recent_count = QSpinBox()
        self.recent_count.setRange(0, MAX_RECENT)
        self.recent_count.setToolTip(tip("Folders listed under File > Recent Folders (0: none)"))
        self.keep_index.toggled.connect(self.reindex_after.setEnabled)
        box_index = QGroupBox("Folders and their indexes", self)
        box_index.hide()  # shown where the Settings window places it
        li = QFormLayout(box_index)
        li.addRow(self.keep_index)
        li.addRow("Re-index automatically when older than:", self.reindex_after)
        li.addRow("Recent folders remembered:", self.recent_count)

        # -- where a referenced file is looked for. On the Settings window's General page alone,
        # as the folders are.
        self.inside_only = QCheckBox(INSIDE_ONLY_TEXT)
        box_refs = QGroupBox("Referenced files", self)
        box_refs.hide()  # shown where the Settings window places it
        lr = QVBoxLayout(box_refs)
        lr.addWidget(self.inside_only)
        lr.addWidget(_note(INSIDE_ONLY_NOTE))

        # -- drawings: on or off, with what experimental means for them. Shown on the Settings
        # window's Drawings page alone.
        self.drawings = QCheckBox(DRAWINGS_TEXT)
        self.drawings.setToolTip(tip(DRAWINGS_TIP))
        self.drawings_note = experimental.note_label(experimental.drawings_note())
        box_drawings = QGroupBox(experimental.tagged("Drawings"), self)
        box_drawings.hide()  # shown where the Settings window places it
        ld = QVBoxLayout(box_drawings)
        ld.addWidget(self.drawings_note)
        ld.addWidget(self.drawings)
        self.drawing_mode = QComboBox()
        for key, label in DRAWING_MODE_LABELS.items():
            self.drawing_mode.addItem(label, key)
        self.drawing_mode.setToolTip(tip(DRAWING_MODE_TIP))
        self.drawings.toggled.connect(self.drawing_mode.setEnabled)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("When Drawing is pressed:"))
        mode_row.addWidget(self.drawing_mode)
        mode_row.addStretch(1)
        ld.addLayout(mode_row)

        # -- 3D printing: where its file goes, and the program it opens, chosen in the Settings
        # menu's own submenu. A line each, their explanations in the tooltips: a group box with a
        # note took 132 pixels. Qt opens a window at most two thirds of the screen high: on a 1080p
        # screen at 125 percent (864 pixels) the dialog opens at its minimum, and the long notes
        # above are cut short there with or without these lines.
        self.print_here = QCheckBox(PRINT_HERE_TEXT)
        self.print_here.setToolTip(tip(PRINT_HERE_TIP))
        self.print_as_is = QCheckBox(AS_IS_PREF_TEXT)
        self.print_as_is.setToolTip(tip(AS_IS_PREF_TIP))
        print_row = QWidget()
        pr = QHBoxLayout(print_row)
        pr.setContentsMargins(0, 0, 0, 0)
        pr.addWidget(self.print_here)
        pr.addWidget(self.print_as_is)
        pr.addStretch(1)
        print_rows: list[QWidget] = [print_row]
        self.print_format: QComboBox | None = None
        self._print_format = print_format
        if print_text is not None:
            self.print_program = QLabel(f"3D Print program: {print_text}")
            self.print_program.setTextFormat(Qt.TextFormat.PlainText)
            self.print_program.setWordWrap(True)
            self.print_program.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.print_program.setToolTip(tip(PRINT_NOTE + " " + PRINT_TIP))
            if print_formats:
                # The formats the program takes, on the program's own line.
                from .printing import FORMAT_LABELS

                self.print_format = QComboBox()
                for fmt in print_formats:
                    self.print_format.addItem(FORMAT_LABELS.get(fmt, fmt), fmt)
                self.print_format.setCurrentIndex(max(0, self.print_format.findData(print_format)))
                self.print_format.setToolTip(tip(PRINT_NOTE))
                row = QWidget()
                line = QHBoxLayout(row)
                line.setContentsMargins(0, 0, 0, 0)
                line.addWidget(self.print_program, 1)
                line.addWidget(QLabel(PRINT_FORMAT_ROW))
                line.addWidget(self.print_format)
                print_rows.append(row)
            else:
                print_rows.append(self.print_program)

        where = QLabel(
            f"Settings are kept in {location}" if location else "Settings are kept for this run only."
        )
        where.setTextFormat(Qt.TextFormat.PlainText)
        where.setWordWrap(True)
        where.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self.restore_defaults)
        self.buttons = buttons

        # The groups by the Settings window's page each goes on (:mod:`.settingswindow`).
        self.sections = {
            "general": (box_list, box_session, box_index, box_refs),
            "view3d": (box_3d, box_mouse),
            "print": tuple(print_rows),
            "drawings": (box_drawings,),
        }
        self.where = where
        layout = QVBoxLayout(self)
        # The folder and index settings go on the Settings window's General page alone: the
        # dialog on its own keeps within 800 pixels without them (they keep their values).
        for w in (box_3d, box_mouse, box_list, box_session, *print_rows):
            layout.addWidget(w)
        layout.addWidget(where)
        layout.addWidget(buttons)
        self.set_values(settings)

    def set_values(self, s: Settings) -> None:
        self.view_3d.setChecked(s.view_3d)
        self.cap.setValue(s.triangle_cap)
        self.cap.setEnabled(s.view_3d)
        self.draw_boxes.setChecked(s.draw_boxes)
        self.draw_boxes.setEnabled(s.view_3d)
        (self.solidworks if s.mouse_style == SOLIDWORKS else self.standard).setChecked(True)
        self.invert_wheel.setChecked(s.invert_wheel)
        (self.turntable if s.rotation_mode == TURNTABLE else self.free).setChecked(True)
        self.view_cube.setChecked(s.view_cube)
        self.turn_about_pointer.setChecked(s.turn_about_pointer)
        self.list_view.setCurrentIndex(max(0, self.list_view.findData(s.list_view)))
        self.thumbnail_size.setCurrentIndex(max(0, self.thumbnail_size.findData(s.thumbnail_size)))
        self.lock_files.setChecked(s.show_lock_files)
        self.remember.setChecked(s.remember_session)
        self.print_here.setChecked(s.print_next_to_model)
        self.all_formats.setChecked(s.show_all_formats)
        self.unreadable.setChecked(s.show_unreadable)
        self.print_as_is.setChecked(s.print_as_is)
        self.keep_index.setChecked(s.keep_index)
        index = self.reindex_after.findData(s.reindex_after_hours)
        if index < 0:  # a value typed into the file: offered as it is
            self.reindex_after.addItem(f"{s.reindex_after_hours} hours", s.reindex_after_hours)
            index = self.reindex_after.count() - 1
        self.reindex_after.setCurrentIndex(index)
        self.reindex_after.setEnabled(s.keep_index)
        self.recent_count.setValue(s.recent_count)
        self.inside_only.setChecked(s.references_inside_only)
        self.drawings.setChecked(s.drawings)
        self.drawing_mode.setCurrentIndex(max(0, self.drawing_mode.findData(s.drawing_mode)))
        self.drawing_mode.setEnabled(s.drawings)

    def restore_defaults(self) -> None:
        """Every setting as it comes, and the 3D Print format the program's first."""
        self.set_values(Settings())
        if self.print_format is not None:
            self.print_format.setCurrentIndex(0)

    def chosen_format(self) -> str | None:
        """The 3D Print format chosen here, or None when none is offered."""
        return None if self.print_format is None else self.print_format.currentData()

    def values(self) -> Settings:
        return Settings(
            view_3d=self.view_3d.isChecked(),
            draw_boxes=self.draw_boxes.isChecked(),
            mouse_style=SOLIDWORKS if self.solidworks.isChecked() else STANDARD,
            invert_wheel=self.invert_wheel.isChecked(),
            rotation_mode=TURNTABLE if self.turntable.isChecked() else FREE,
            view_cube=self.view_cube.isChecked(),
            turn_about_pointer=self.turn_about_pointer.isChecked(),
            triangle_cap=self.cap.value(),
            thumbnail_size=self.thumbnail_size.currentData(),
            list_view=self.list_view.currentData(),
            show_lock_files=self.lock_files.isChecked(),
            remember_session=self.remember.isChecked(),
            print_next_to_model=self.print_here.isChecked(),
            show_all_formats=self.all_formats.isChecked(),
            show_unreadable=self.unreadable.isChecked(),
            print_as_is=self.print_as_is.isChecked(),
            keep_index=self.keep_index.isChecked(),
            reindex_after_hours=int(self.reindex_after.currentData()),
            recent_count=self.recent_count.value(),
            references_inside_only=self.inside_only.isChecked(),
            drawings=self.drawings.isChecked(),
            drawing_mode=self.drawing_mode.currentData(),
        )

    def apply(self) -> None:
        """Hand the settings as shown to the window (Apply), and a 3D Print format chosen."""
        self._apply()

    def _apply(self) -> None:
        self.applied.emit(self.values())
        fmt = self.chosen_format()
        if fmt is not None and fmt != self._print_format:  # only a change is remembered
            self._print_format = fmt
            self.print_format_chosen.emit(fmt)

    def _ok(self) -> None:
        self._apply()
        self.accept()
