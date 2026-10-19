"""Help > Licences: the licence texts the viewer carries (``THIRD_PARTY_NOTICES.txt``).

The executable carries them in ``licenses`` inside itself (``packaging/SolidSeasViewer.spec``
puts them there): the project's ``LICENSE``, ``NOTICE`` and ``THIRD_PARTY_NOTICES.txt``,
every text in the repository's ``licenses`` folder, the licence of the Python it was built
with and ``BUNDLED-FILES.txt``, the list of the libraries inside it. The folder is under
``sys._MEIPASS`` in both builds: that is the unpacked folder of the one-file build, and the
``_internal`` folder beside the executable of the one-folder build the installer installs. From a source
checkout the same files are read from the repository. The window lists them and shows the
one picked; it reads nothing else and writes nothing.
"""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

# The files shown first, in this order; the rest follow by name.
FIRST = ("THIRD_PARTY_NOTICES.txt", "NOTICE", "LICENSE", "BUNDLED-FILES.txt", "Python-LICENSE.txt")
INTRO = (
    "SolidSeas is licensed under the Apache License 2.0. It carries the software below under "
    "the licences shown here, and THIRD_PARTY_NOTICES.txt says what each one is. Qt and "
    "Qt for Python are used under the GNU LGPL version 3: the notices say where their source "
    "is and how to run SolidSeas with another build of them."
)


def licence_files() -> list[str]:
    """The licence texts this viewer carries, as paths, :data:`FIRST` first (module notes).
    Empty where there are none, as in a library installed without the repository."""
    bundle = getattr(sys, "_MEIPASS", None) if getattr(sys, "frozen", False) else None
    if bundle:
        candidates = _in(os.path.join(bundle, "licenses"))
    else:
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        candidates = [os.path.join(root, n) for n in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.txt")]
        candidates += _in(os.path.join(root, "licenses"))
    order = {name: i for i, name in enumerate(FIRST)}

    def key(path: str) -> tuple[int, str]:
        name = os.path.basename(path)
        return order.get(name, len(FIRST)), name.lower()

    return sorted((p for p in candidates if os.path.isfile(p)), key=key)


def _in(folder: str) -> list[str]:
    try:
        return [os.path.join(folder, n) for n in os.listdir(folder)]
    except OSError:
        return []


def read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            return fh.read()
    except OSError as exc:
        return f"This file could not be read: {exc.strerror or exc}"


class LicencesDialog(QDialog):
    """The list of licence texts beside the text of the one picked. ``files`` stands in for
    :func:`licence_files` in tests."""

    def __init__(self, parent: QWidget | None = None, files: list[str] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Licences")
        self.files = licence_files() if files is None else files
        intro = QLabel(INTRO)
        intro.setWordWrap(True)
        self.names = QListWidget()
        self.names.addItems([os.path.basename(p) for p in self.files])
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.names)
        split.addWidget(self.text)
        split.setStretchFactor(1, 1)
        split.setSizes([220, 640])
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(split, 1)
        layout.addWidget(close)
        self.resize(900, 600)
        self.names.currentRowChanged.connect(self.show_file)
        if self.files:
            self.names.setCurrentRow(0)
        else:
            self.text.setPlainText(
                "This copy of SolidSeas carries no licence files. They are in the SolidSeas "
                "repository: LICENSE, NOTICE, THIRD_PARTY_NOTICES.txt and the licenses folder."
            )

    def show_file(self, row: int) -> None:
        if 0 <= row < len(self.files):
            self.text.setPlainText(read_text(self.files[row]))


__all__ = ["FIRST", "LicencesDialog", "licence_files", "read_text"]
