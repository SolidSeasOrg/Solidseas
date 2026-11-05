"""File > Convert: the Qt side of :mod:`.convertfile`.

Convert writes the part or assembly the details panel shows, or the IGES, BREP or STEP
file it shows, as another of those formats through the OCCT backend extension
(``docs/EXTENSIONS.md`` section 9), to a file the user picks in a save dialog whose file
types are the formats that document converts to (:func:`.convertfile.targets`). It is
that extension's front: the window shows the menu item only while the backend is
available (:meth:`.MainWindow.extensions_changed` asks again when a switch changes),
and the action is off, its tooltip saying why, for a drawing or a file of a format it
does not convert (:func:`.convertfile.unavailable`).

It works as File > Export STEP does (:class:`.stepaction.StepController`, which this
controller is with its own dialog, words and result): the name typed decides the format
when its extension is one of them, else the file type chosen does, and a name without an
extension gets that format's; the conversion runs in the export's own process
(:func:`.printing.export_in_process`, job ``convert``), whose Cancel ends it at once;
and a SOLIDWORKS part whose bodies STEP cannot hold without loss asks whether to write
the file without them. Every message is plain text.
"""

import os
from typing import Any

from PySide6.QtWidgets import QFileDialog

from . import convertfile, experimental, reading
from .stepaction import StepController

TITLE = convertfile.TITLE
TEXT = experimental.tagged("Con&vert...", experimental.extension_stage("occt"))
TIP = (
    "Write the model as IGES, BREP or STEP through the OCCT backend extension (Open CASCADE), "
    "to a file you choose"
)


class ConvertController(StepController):
    """The Convert action's work (module notes). ``ask_path`` takes the suggested path and
    the formats offered and gives the path chosen ("" for none) and the format of the file
    type chosen; tests stand in for it, as for the other dialogs."""

    title = TITLE
    working = "Converting the file..."
    failed = "The conversion failed."
    lossy = "Nothing was written: some of the geometry cannot be written without loss."

    def _ask_path(self, suggested: str, formats: tuple[str, ...]) -> tuple[str, str]:
        filters = [convertfile.FILTERS[f] for f in formats]
        dialog = QFileDialog(self.window, self.title, suggested, ";;".join(filters))
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)

        def suffix(text: str) -> None:
            if text in filters:  # the extension a name typed without one gets
                dialog.setDefaultSuffix(convertfile.extensions(formats[filters.index(text)])[0].lstrip("."))

        dialog.filterSelected.connect(suffix)
        suffix(filters[0])
        if not dialog.exec():
            return "", ""
        files = dialog.selectedFiles()
        chosen = dialog.selectedNameFilter()
        fmt = formats[filters.index(chosen)] if chosen in filters else formats[0]
        return (files[0] if files else ""), fmt

    def _ask(self, target) -> dict[str, Any] | None:
        """Where to write and as what, from the save dialog: the conversion's request, or None."""
        source, folder, configuration = target.source, target.folder, target.configuration
        formats = convertfile.targets(target.content_format)
        if not formats:
            return None
        stem = reading.export_stem(source.path, source.nested)
        first = convertfile.extensions(formats[0])[0]
        path, fmt = self.ask_path(os.path.join(self.last_folder or "", stem + first), formats)
        if not path:
            return None
        path = os.path.normpath(path)
        fmt = convertfile.format_of_name(path, formats) or fmt or formats[0]
        # The save dialog asked whether to replace the file it returned; a name it returned
        # without an extension gets the format's here, and a file of that name is a new question.
        overwrite = os.path.lexists(path)
        if not os.path.splitext(path)[1]:
            path += convertfile.extensions(fmt)[0]
            overwrite = os.path.lexists(path)
            if overwrite and not self.confirm(f"{os.path.basename(path)} already exists.\n\nReplace it?"):
                return None
        self.last_folder = os.path.dirname(path)
        request = {
            "job": "convert",
            "format": fmt,
            "path": source.path,
            "folder": folder,
            "within": source.within,
            "nested": tuple(source.nested),
            "configuration": configuration,
            "target": path,
            "overwrite": overwrite,
            "allow_partial": False,
        }
        if self.window.settings.references_inside_only:  # an assembly's files: the opened folder's
            request["outside"] = False
        return request

    def _written(self, data: dict[str, Any]) -> list[str]:
        return convertfile.written_lines(data)
