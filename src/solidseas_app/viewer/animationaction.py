"""Save Animation: a clip of the model turning, exploding and collapsing (the video
extension, ``docs/EXTENSIONS.md`` section 9).

The 3D view's menu has Save Animation... while the video extension is on
(:func:`available`). :class:`AnimationDialog` asks for the clip's options
(:class:`.animation.AnimationOptions`); :class:`SaveAnimation` then

1. asks where to save it (a ``.mp4`` or ``.gif``),
2. renders every frame offscreen into a temporary folder of its own
   (:meth:`.view3d.ModelView.render_frames`), with a progress box that can cancel,
3. has the video extension's helper encode them (:func:`solidseas_app.extensions.start_helper`,
   the ``encode`` request) on a worker thread, into another folder of its own,
4. moves the clip to where the person chose (:func:`solidseas.export.write_new`: never
   over a SOLIDWORKS file or through a link), and removes the temporary folders.

``start_helper``, ``ask_path``, ``say`` and ``run_in_background`` stand in for the helper,
the dialogs and the thread pool in tests.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import extensions as X
from .animation import SIZES, AnimationOptions, OptionsError, frames, with_format

MENU_TEXT = "Save Animation..."
MENU_TIP = "Save a clip of the model turning, exploding and collapsing, as MP4 or an animated GIF"


def available(view: Any) -> bool:
    """Whether Save Animation is offered: the video extension is on and the view draws."""
    try:
        on = X.is_on("video", X.read_state())
    except X.ExtensionError:
        on = False
    return on and view is not None and hasattr(view, "render_frames")


class AnimationDialog(QDialog):
    """The clip's options, with the defaults of :class:`.animation.AnimationOptions`."""

    def __init__(self, parent: QWidget | None = None, *, assembly: bool = True) -> None:
        super().__init__(parent)
        self.setWindowTitle("Save Animation")
        d = AnimationOptions()
        self.seconds = QDoubleSpinBox()
        self.seconds.setRange(0.5, 60)
        self.seconds.setValue(d.seconds)
        self.seconds.setSuffix(" s")
        self.fps = QSpinBox()
        self.fps.setRange(5, 60)
        self.fps.setValue(d.fps)
        self.size = QComboBox()
        self.size.addItems(list(SIZES))
        self.size.setCurrentText(d.size)
        self.orbit = QSpinBox()
        self.orbit.setRange(0, 1440)
        self.orbit.setValue(int(d.orbit_degrees))
        self.orbit.setSuffix(" degrees")
        self.clockwise = QCheckBox("Clockwise")
        self.clockwise.setChecked(d.clockwise)
        self.zoom = QDoubleSpinBox()
        self.zoom.setRange(0.25, 4.0)
        self.zoom.setSingleStep(0.1)
        self.zoom.setValue(d.zoom)
        self.zoom.setSuffix(" x by the end")
        self.explode = QSpinBox()
        self.explode.setRange(0, 100)
        self.explode.setValue(int(d.explode * 100) if assembly else 0)
        self.explode.setSuffix(" %")
        self.explode.setEnabled(assembly)
        self.background = QLineEdit(d.background)
        self.format = QComboBox()
        self.format.addItem("MP4 video", "mp4")
        self.format.addItem("Animated GIF", "gif")
        form = QFormLayout()
        form.addRow("Length:", self.seconds)
        form.addRow("Frames a second:", self.fps)
        form.addRow("Size:", self.size)
        form.addRow("Camera circles:", self.orbit)
        form.addRow("", self.clockwise)
        form.addRow("Zoom:", self.zoom)
        form.addRow("Explode:", self.explode)
        form.addRow("Background:", self.background)
        form.addRow("Format:", self.format)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def options(self) -> AnimationOptions:
        """The options as filled in; :class:`.animation.OptionsError` when one is refused."""
        return AnimationOptions(
            seconds=round(self.seconds.value(), 2),
            fps=self.fps.value(),
            size=self.size.currentText(),
            orbit_degrees=float(self.orbit.value()),
            clockwise=self.clockwise.isChecked(),
            zoom=round(self.zoom.value(), 2),
            explode=self.explode.value() / 100,
            background=self.background.text().strip(),
            format=self.format.currentData(),
        )


class SaveAnimation:
    """One Save Animation run (module notes)."""

    def __init__(
        self,
        parent: QWidget,
        view: Any,
        name: str,
        *,
        start_helper: Callable[[], Any] | None = None,
        ask_path: Callable[[str, str], str] | None = None,
        say: Callable[[str, str], Any] | None = None,
        run_in_background: Callable[[Callable[[], Any], Callable[[Any], None]], None] | None = None,
    ) -> None:
        self.parent, self.view, self.name = parent, view, name
        self.start_helper = start_helper or (lambda: X.start_helper("video", X.read_state()))
        self.ask_path = ask_path or self._ask_path
        self.say = say or (lambda title, text: QMessageBox.information(parent, title, text))
        self.run_in_background = run_in_background or _thread
        self.result: dict[str, Any] | None = None

    def _ask_path(self, start: str, filters: str) -> str:
        chosen, _f = QFileDialog.getSaveFileName(self.parent, "Save Animation", start, filters)
        return chosen

    def run(self, options: AnimationOptions) -> bool:
        """Ask where, render and encode (module notes); False when nothing was started."""
        ext = options.format
        filters = (
            "MP4 video (*.mp4);;Animated GIF (*.gif)"
            if ext == "mp4"
            else "Animated GIF (*.gif);;MP4 video (*.mp4)"
        )
        target = self.ask_path(os.path.join(os.path.expanduser("~"), f"{self.name}.{ext}"), filters)
        if not target:
            return False
        if not target.lower().endswith((".mp4", ".gif")):
            target += "." + ext
        options = with_format(options, target)
        planned = frames(options, self.view.camera_state())
        work = tempfile.mkdtemp(prefix="solidseas-animation-", dir=_temp_root())
        frames_dir, out_dir = os.path.join(work, "frames"), os.path.join(work, "out")
        os.mkdir(frames_dir)
        os.mkdir(out_dir)
        progress = QProgressDialog("Drawing the frames...", "Cancel", 0, len(planned), self.parent)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(300)

        def step(index: int) -> bool:
            progress.setValue(index + 1)
            QApplication.processEvents()
            return not progress.wasCanceled()

        try:
            drawn = self.view.render_frames(planned, options.pixels, options.background, frames_dir, step)
        except Exception as exc:  # the view says why it cannot draw
            progress.close()
            shutil.rmtree(work, ignore_errors=True)
            self.say("Save Animation", f"The frames could not be drawn: {exc}")
            return False
        progress.close()
        if drawn < len(planned):
            shutil.rmtree(work, ignore_errors=True)
            return False
        name = "clip." + options.format

        def encode() -> dict[str, Any]:
            helper = self.start_helper()
            try:
                return helper.request(
                    "encode",
                    {
                        "frames": frames_dir,
                        "out_dir": out_dir,
                        "name": name,
                        "fps": options.fps,
                        "format": options.format,
                    },
                )
            finally:
                helper.close(timeout=10)

        def finished(got: Any) -> None:
            try:
                if isinstance(got, BaseException):
                    self.say("Save Animation", f"The clip was not made: {got}")
                    return
                from solidseas.export import write_new

                source = got["path"]
                if os.path.dirname(os.path.abspath(source)) != os.path.abspath(out_dir):
                    self.say(
                        "Save Animation",
                        "The video helper wrote somewhere it was not given; nothing was saved.",
                    )
                    return

                def copy(fh) -> int:
                    with open(source, "rb") as src:
                        shutil.copyfileobj(src, fh, 1 << 20)
                    return os.path.getsize(source)

                try:
                    # the save dialog has asked before a file there is replaced
                    written, size = write_new(target, copy, overwrite=True)
                except (OSError, ValueError) as exc:
                    self.say("Save Animation", f"The clip was not saved: {exc}")
                    return
                self.result = {"path": written, "bytes": size, "frames": drawn, "encoder": got.get("encoder")}
                self.say("Save Animation", f"Saved {os.path.basename(written)}: {drawn} frames.")
            finally:
                shutil.rmtree(work, ignore_errors=True)

        self.run_in_background(encode, finished)
        return True


def _temp_root() -> str:
    root = os.path.join(X.data_dir(), "temp")
    os.makedirs(root, exist_ok=True)
    return root


def _thread(work: Callable[[], Any], done: Callable[[Any], None]) -> None:
    """Run ``work`` on a thread of its own and ``done`` with its result (or the exception)
    back on the Qt thread."""
    from PySide6.QtCore import QTimer

    box: dict[str, Any] = {}

    def body() -> None:
        try:
            box["got"] = work()
        except BaseException as exc:  # said to the person, never raised into Qt
            box["got"] = exc

    thread = threading.Thread(target=body, name="save-animation", daemon=True)
    thread.start()

    def poll() -> None:
        if thread.is_alive():
            QTimer.singleShot(100, poll)
        else:
            done(box.get("got"))

    QTimer.singleShot(100, poll)


__all__ = ["MENU_TEXT", "MENU_TIP", "AnimationDialog", "OptionsError", "SaveAnimation", "available"]
