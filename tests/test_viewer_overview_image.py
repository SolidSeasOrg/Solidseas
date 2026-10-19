"""The preview image on the SolidSeas Viewer's Overview tab.

The Overview shows the image the Preview tab shows, when the document has one,
and hides it when it has none. A click, Enter or Space on it shows the Preview
tab with the image, never the 3D view, for that document only: the next one
opens as the Image and 3D buttons last chose. It follows the selection. Every test
that reads files checks that none of them changed.
"""

import os
import shutil
from pathlib import Path

import pytest

from builders import rebuild
from support import fixture_path
from test_viewer import Viewer, _state, _stub_view_factory, _wait, needs_qt

PART = "o02_boxA.SLDPRT"
OTHER = "o07_boxB_h31.SLDPRT"
DRAWING = "o18_drw_boxA.SLDDRW"
NO_PREVIEW = "no_preview.SLDPRT"


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from solidseas_app.viewer.app import use_system_fonts

    use_system_fonts()
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def viewer(app):
    v = Viewer(app)
    yield v
    v.close()


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    """Two parts and a drawing with stored previews, and a part saved without one."""
    docs = tmp_path / "docs"
    docs.mkdir()
    for name in (PART, OTHER, DRAWING):
        shutil.copy2(fixture_path(name), docs / name)
    (docs / NO_PREVIEW).write_bytes(rebuild(fixture_path(PART), drop=("Preview", "PreviewPNG")))
    return docs


def _overview(viewer):
    from solidseas_app.viewer.details import TABS

    details = viewer.window.details
    details.tabs.setCurrentIndex(TABS.index("Overview"))
    viewer.app.processEvents()
    return details.overview_image


@needs_qt
def test_the_overview_shows_the_preview_and_follows_the_selection(viewer, folder):
    before = _state(folder)
    viewer.window.resize(1300, 850)
    viewer.open(folder)
    image = _overview(viewer)
    pane = viewer.window.details.preview

    viewer.select(PART)
    assert viewer.page("Overview").showing_content
    assert image.isVisible() and image.has_image
    assert image.accessibleName() == f"Preview of {PART}"
    assert image.toolTip() == "Show in the Preview tab"
    assert image.cursor().shape().name == "PointingHandCursor"
    assert image._source.cacheKey() == pane.image.pixmap.cacheKey()  # the Preview tab's own image
    longest = max(image.sizeHint().width(), image.sizeHint().height()) - 2 * image.MARGIN
    assert 0 < longest <= image.LONGEST
    first = image._source.cacheKey()

    viewer.select(NO_PREVIEW)
    assert viewer.page("Overview").showing_content
    assert image.isHidden() and not image.has_image and image.accessibleName() == ""

    viewer.select(OTHER)
    assert image.isVisible() and image.accessibleName() == f"Preview of {OTHER}"
    assert image._source.cacheKey() not in (first, None)

    viewer.select(DRAWING)
    assert image.isVisible() and image.accessibleName() == f"Preview of {DRAWING}"

    viewer.window.details.clear("Open a folder, then select a document to see its details.")
    assert image.isHidden() and not image.has_image

    viewer.app.processEvents()
    image.parentWidget().resize(120, 400)  # a narrow panel: the image shrinks to fit
    viewer.select(PART)
    assert image.heightForWidth(120) < image.heightForWidth(400)
    assert _state(folder) == before


@needs_qt
@pytest.mark.parametrize("how", ["click", "enter", "space"])
def test_activating_the_overview_image_shows_the_preview_tab_in_image_mode(viewer, folder, how):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from solidseas_app.viewer.details import TABS
    from solidseas_app.viewer.preview import IMAGE, MODEL

    w = viewer.window
    pane = w.details.preview
    made: list = []
    pane.view_factory = _stub_view_factory(made)
    pane.gl_check = lambda: (True, "test")
    viewer.open(folder)
    w.change_settings(view_3d=True)  # the Preview tab would open in 3D
    viewer.select(PART)
    assert pane.preferred == MODEL
    image = _overview(viewer)
    history = list(w.history)
    assert image.isVisible()

    if how == "click":
        QTest.mouseClick(image, Qt.MouseButton.LeftButton)
    else:
        image.setFocus()
        assert image.focusPolicy() == Qt.FocusPolicy.StrongFocus
        QTest.keyClick(image, Qt.Key.Key_Return if how == "enter" else Qt.Key.Key_Space)
    viewer.app.processEvents()
    assert w.details.tabs.currentIndex() == TABS.index("Preview")
    assert pane.mode == IMAGE and pane.image_button.isChecked()
    assert pane.stack.currentIndex() == 0 and pane.image.pixmap is not None
    assert w.history == history  # switching tabs adds no Back entry
    assert pane.preferred == MODEL  # the buttons' choice is left alone

    # The next part opens as the buttons last chose: in 3D again.
    viewer.select(OTHER)
    assert pane.mode == MODEL and pane.model_button.isChecked() and pane.stack.currentIndex() == 1
    _wait(viewer.app, lambda: not w.busy)

    # The 3D button still works on a document whose image the Overview asked for.
    _overview(viewer)
    QTest.mouseClick(image, Qt.MouseButton.LeftButton)
    assert pane.mode == IMAGE
    pane.model_button.click()
    assert pane.mode == MODEL and pane.preferred == MODEL
    _wait(viewer.app, lambda: not w.busy)
