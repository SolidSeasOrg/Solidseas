"""File > Export STEP: the Qt side of :mod:`.stepexport`.

Export STEP writes the part or assembly the details panel shows, in the configuration
it shows, to a file the user picks in a save dialog: a SOLIDWORKS part or assembly (its
component files found in the opened folder) or a Parasolid file's part or assembly. A
drawing or a 3D file of another format is not offered (the action is off, its tooltip saying why:
:func:`.printing.step_unavailable`). The dialog adds ``.step`` to a name typed
without an extension and asks itself whether to replace a file of that name; when
the name still lacks one, ``.step`` is added here and a file of that name is
replaced only after asking. The export runs in the export's own process
(:func:`.printing.export_in_process`, job ``step``), waited on from a pool of the
controller's own while a progress dialog offers Cancel, which ends that process at
once, as closing the window does. When the document holds geometry STEP cannot
hold without loss, or an assembly components it cannot write, the export writes
nothing and the window says which bodies or components and why, and asks whether to
write the file without them; yes runs it again with ``allow_partial``. Every message
is plain text.
"""

import os
from typing import Any

from PySide6.QtCore import QObject, QStandardPaths, QThreadPool, Signal
from PySide6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog

from . import printing, reading, stepexport
from .wording import error_message, refusal_text
from .workers import Job

TITLE = stepexport.TITLE
TEXT = "Export &STEP..."
TIP = "Write the part or assembly as a STEP file (AP214), its exact geometry, to a file you choose"
ASK_PARTIAL = "Write the file without these bodies?"
ASK_LEFT_OUT = "Write the file without these components?"


class StepController(QObject):
    """The Export STEP action's work. ``ask_path`` (the save dialog: a path or ""),
    ``confirm`` (a yes or no question), ``export`` (None: :func:`.printing.export_in_process`)
    and ``message`` are attributes so tests can stand in for them."""

    finished = Signal(object)  # what an export did

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self._job: Job | None = None
        self._progress: QProgressDialog | None = None
        self.busy = False
        self.export = None
        self.ask_path = self._ask_path
        self.confirm = self._confirm
        self.message = self._message
        self.last_folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)

    # -- dialogs -------------------------------------------------------------------------
    def _ask_path(self, suggested: str) -> str:
        dialog = QFileDialog(self.window, TITLE, suggested, stepexport.FILTER)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setDefaultSuffix("step")  # added before the dialog asks about replacing a file
        if not dialog.exec():
            return ""
        files = dialog.selectedFiles()
        return files[0] if files else ""

    def _confirm(self, text: str) -> bool:
        box = QMessageBox(QMessageBox.Icon.Question, TITLE, text, parent=self.window)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        from PySide6.QtCore import Qt

        box.setTextFormat(Qt.TextFormat.PlainText)
        return box.exec() == QMessageBox.StandardButton.Yes

    def _message(self, icon: QMessageBox.Icon, text: str) -> None:
        from .window import show_message

        show_message(self.window, icon, TITLE, text)

    # -- the export ----------------------------------------------------------------------
    def cancel(self) -> None:
        if self._job is not None:
            self._job.cancel()

    def shutdown(self) -> None:
        self.cancel()
        self.pool.clear()

    def start(self) -> None:
        """Ask where, then export what the details panel shows."""
        if self.busy:
            return
        target = self.window.print_target()
        if target is None:
            return
        self.busy = True  # while its dialogs are open too: the action never runs twice at once
        try:
            request = self._ask(target)
        finally:
            self.busy = False
        if request is not None:
            self._run(request)
        else:
            self.window._update_actions()

    def _ask(self, target) -> dict[str, Any] | None:
        """Where to write, from the save dialog: the export's request, or None."""
        source, folder, configuration = target.source, target.folder, target.configuration
        stem = reading.export_stem(source.path, source.nested)
        path = self.ask_path(os.path.join(self.last_folder or "", stem + ".step"))
        if not path:
            return None
        path = os.path.normpath(path)
        # The save dialog asked whether to replace the file it returned; a name it returned
        # without an extension gets ".step" here, and a file of that name is a new question.
        overwrite = os.path.lexists(path)
        if not os.path.splitext(path)[1]:
            path += ".step"
            overwrite = os.path.lexists(path)
            if overwrite and not self.confirm(f"{os.path.basename(path)} already exists.\n\nReplace it?"):
                return None
        self.last_folder = os.path.dirname(path)
        return {
            "job": "step",
            "path": source.path,
            "folder": folder,
            "within": source.within,
            "nested": tuple(source.nested),
            "configuration": configuration,
            "target": path,
            "overwrite": overwrite,
            "allow_partial": False,
        }

    def _run(self, request: dict[str, Any]) -> None:
        export = self.export or printing.export_in_process

        def work(_emit, cancelled):
            return export(request, cancelled)

        self.busy = True
        self._job = Job(work)
        progress = QProgressDialog("Writing the STEP file...", "Cancel", 0, 0, self.window)
        progress.setWindowTitle(TITLE)
        progress.setMinimumDuration(400)
        progress.canceled.connect(self.cancel)
        self._progress = progress
        self.window._start(self.pool, self._job, on_finished=lambda r: self._done(request, r))
        self.window._update_actions()

    def _close_progress(self) -> None:
        if self._progress is not None:
            self._progress.canceled.disconnect(self.cancel)
            self._progress.close()
            self._progress.deleteLater()
            self._progress = None

    def _done(self, request: dict[str, Any], result: dict[str, Any]) -> None:
        self._close_progress()
        self.busy = False
        self._job = None
        self.window._update_actions()
        warn, info = QMessageBox.Icon.Warning, QMessageBox.Icon.Information
        if result.get("cancelled"):
            self.window.statusBar().showMessage("Export STEP cancelled: nothing was written.", 6000)
            self.finished.emit({"ok": False, "cancelled": True})
            return
        if not result.get("ok"):
            err = result.get("error") or {}
            code = err.get("code")
            if code == "not_representable" and not request["allow_partial"]:
                if (err.get("detail") or {}).get("rule") == "instances_left_out":  # an assembly's parts
                    text = (
                        "Nothing was written: some of the assembly's components cannot be written as "
                        "STEP.\n\n"
                        + stepexport.refused_bodies(err)
                        + f"\n\n{ASK_LEFT_OUT} The file will say it is incomplete."
                    )
                else:
                    text = (
                        "Nothing was written: STEP cannot hold some of the geometry without loss.\n\n"
                        + stepexport.refused_bodies(err)
                        + f"\n\n{ASK_PARTIAL} The file will say it is incomplete."
                    )
                if self.confirm(text):
                    # replaces a file only as the first try was allowed to: one that has
                    # appeared since is refused, not replaced unasked
                    self._run({**request, "allow_partial": True})
                    return
                self.finished.emit({"ok": False, "error": err, "declined": True})
                return
            if code == "output_refused":
                text = f"Nothing was written.\n\n{refusal_text(err)}"
            else:
                text = "The STEP export failed.\n\n" + error_message(err, path=request["path"])
            self.message(warn, text)
            self.finished.emit({"ok": False, "error": err})
            return
        data = result["data"]
        lines = [
            f"Wrote {data['file']}  ({reading.size_text(data['bytes'])})",
            f"{data['solids']} solid(s), {data['sheets']} sheet(s), {data['faces']:,} faces",
        ]
        if data["exact"]:
            holder = "the Parasolid file" if data.get("source_format") == "parasolid" else "SOLIDWORKS"
            lines.append(f"Exact: every face and edge as {holder} holds it.")
        else:
            lines.append(
                f"Approximated where STEP has no exact form, at most {data['max_deviation_mm']:.3g} mm from "
                f"the geometry; the file's uncertainty is {data['uncertainty_mm']:.3g} mm."
            )
        lines += stepexport.left_out_lines(data["left_out"])
        lines += [
            f"Note: {w['message']}"
            for w in data["warnings"]
            if w["code"] not in ("step_approximated", "bodies_left_out", "step_bodies_left_out")
        ]
        self.message(info, "\n".join(lines))
        self.finished.emit({"ok": True, **data})
