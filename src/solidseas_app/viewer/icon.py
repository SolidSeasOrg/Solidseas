"""The viewer's icon, drawn in code: a block over two waves on a blue tile.

The same drawing is the window icon at run time and, through
:func:`write_ico`, the executable's icon at build time, so the repository
carries no binary image. It draws no text, so it needs no fonts and no
running application.
"""

import struct

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 256, size / 256)
    tile = QLinearGradient(0, 0, 0, 256)
    tile.setColorAt(0, QColor("#2a6fbe"))
    tile.setColorAt(1, QColor("#0e3a70"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(tile)
    p.drawRoundedRect(QRectF(8, 8, 240, 240), 44, 44)

    def face(points, color: str) -> None:
        p.setBrush(QColor(color))
        p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in points]))

    # An isometric block: top, left and right faces.
    face([(128, 40), (196, 76), (128, 112), (60, 76)], "#ffffff")
    face([(60, 76), (128, 112), (128, 178), (60, 142)], "#c9dcf2")
    face([(128, 112), (196, 76), (196, 142), (128, 178)], "#9dbde3")

    pen = QPen(QColor("#ffffff"), 12, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    for y in (196, 224):
        wave = QPainterPath(QPointF(40, y))
        for i, x in enumerate((40, 96, 152)):
            dy = -16 if i % 2 == 0 else 16
            wave.cubicTo(QPointF(x + 18, y + dy), QPointF(x + 38, y + dy), QPointF(x + 56, y))
        p.drawPath(wave)
    p.end()
    return img


def png(size: int) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    draw(size).save(buf, "PNG")
    return bytes(buf.data())


def write_ico(path: str) -> None:
    """A Windows .ico holding the icon at every size in :data:`ICO_SIZES`, each as a PNG
    (the form Windows has read since Vista), written without Qt's ICO plugin."""
    images = [(s, png(s)) for s in ICO_SIZES]
    offset = 6 + 16 * len(images)
    header = struct.pack("<HHH", 0, 1, len(images))
    entries = b""
    for s, data in images:
        side = 0 if s >= 256 else s  # 0 means 256
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    with open(path, "wb") as fh:
        fh.write(header + entries + b"".join(data for _, data in images))
