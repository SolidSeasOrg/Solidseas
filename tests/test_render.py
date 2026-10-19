"""Rendered previews (``docs/API.md`` 3.21): a known model from the Home view gives a known
silhouette, the bounds hold, and the thumbnail cache keys, bounds and repairs itself."""

import sqlite3
import struct
import zlib

import pytest

from model_writers import Item, Scene, box, holed_block, scene_document, two_object_assembly
from solidseas.errors import InvalidArgumentError, NoPreviewError
from solidseas.formats import Limits, open_model
from solidseas.render import APPLICATION_ID, ThumbnailCache, render_preview
from support import fixture_path


def _pixels(png: bytes) -> tuple[int, int, list[tuple[int, int, int, int]]]:
    """Decode an RGBA PNG SolidSeas wrote (filters None and Up only)."""
    w, h = struct.unpack(">II", png[16:24])
    data = b""
    pos = 8
    while pos < len(png):
        (n,) = struct.unpack(">I", png[pos : pos + 4])
        tag = png[pos + 4 : pos + 8]
        if tag == b"IDAT":
            data += png[pos + 8 : pos + 8 + n]
        pos += 12 + n
    raw = zlib.decompress(data)
    stride = 4 * w
    rows = []
    prev = bytes(stride)
    for y in range(h):
        f = raw[y * (stride + 1)]
        line = raw[y * (stride + 1) + 1 : (y + 1) * (stride + 1)]
        if f == 2:
            line = bytes((a + b) & 0xFF for a, b in zip(line, prev, strict=True))
        else:
            assert f == 0
        rows.append(line)
        prev = line
    flat = b"".join(rows)
    return w, h, [tuple(flat[i : i + 4]) for i in range(0, len(flat), 4)]


def test_a_box_renders_a_centred_shaded_silhouette():
    with open_model(fixture_path("o02_boxA.STL")) as doc:
        r = render_preview(doc)
    assert (r.width, r.height, r.mime, r.drawn, r.total, r.partial) == (256, 192, "image/png", 12, 12, False)
    w, h, px = _pixels(r.data)
    covered = [i for i, p in enumerate(px) if p[3]]
    assert 0.15 < len(covered) / (w * h) < 0.6
    assert px[0][3] == 0 and px[-1][3] == 0  # transparent corners
    centre = px[(h // 2) * w + w // 2]
    assert centre[3] == 255 and 60 < centre[0] < 255
    xs = [i % w for i in covered]
    ys = [i // w for i in covered]
    assert abs((min(xs) + max(xs)) / 2 - w / 2) < 3 and abs((min(ys) + max(ys)) / 2 - h / 2) < 3
    # three faces in three shades, and a dark outline
    shades = {px[i][:3] for i in covered}
    assert len(shades) >= 4 and min(sum(s) for s in shades) < max(sum(s) for s in shades) * 0.5
    again = render_preview(open_model(fixture_path("o02_boxA.STL")))
    assert again.data == r.data  # the same model gives the same bytes


def test_colours_up_axis_and_background():
    doc = scene_document(two_object_assembly())
    r = render_preview(doc, width=128, height=96, background=(255, 255, 255))
    _w, _h, px = _pixels(r.data)
    assert all(p[3] == 255 for p in px)
    assert any(p[0] > 2 * p[2] for p in px if p[:3] != (255, 255, 255))  # red boxes
    assert any(p[2] > 2 * p[0] for p in px if p[:3] != (255, 255, 255))  # the blue block
    y_up = render_preview(doc, width=128, height=96, up_axis="y")
    assert y_up.data != render_preview(doc, width=128, height=96).data


def test_render_bounds_and_arguments():
    doc = scene_document(
        Scene([holed_block()], [Item(0, translation_mm=(40.0 * i, 0.0, 0.0)) for i in range(10)])
    )
    r = render_preview(doc, limits=Limits(render_triangles=50))
    assert r.partial and r.drawn <= 64 and r.total == 320
    slow = render_preview(doc, limits=Limits(render_seconds=1e-9))
    assert slow.partial
    for bad in ({"width": 0}, {"height": 5000}, {"view": "top"}, {"background": (1, 2)}, {"up_axis": "x"}):
        with pytest.raises(InvalidArgumentError):
            render_preview(doc, **bad)
    with pytest.raises(NoPreviewError):
        render_preview(scene_document(Scene([box(1, 1, 1)], [])))


def test_the_thumbnail_cache(tmp_path):
    path = tmp_path / "cache" / "thumbnails.sqlite"
    cache = ThumbnailCache(str(path), max_bytes=1000)
    assert cache.get("a.stl", 10, 5) is None
    cache.put("a.stl", 10, 5, b"x" * 300)
    assert cache.get("a.stl", 10, 5) == b"x" * 300
    assert cache.get("a.stl", 11, 5) is None and cache.get("a.stl", 10, 6) is None
    assert cache.get("a.stl", 10, 5, settings="256x192") is None
    for i in range(5):
        cache.put(f"f{i}.stl", 1, 1, b"y" * 300)
    assert cache.size() <= 1000
    assert cache.get("f4.stl", 1, 1) is not None and cache.get("a.stl", 10, 5) is None  # oldest dropped
    cache.put("big.stl", 1, 1, b"z" * 5000)  # larger than the whole cache: not kept
    assert cache.get("big.stl", 1, 1) is None
    cache.close()
    con = sqlite3.connect(path)
    assert con.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
    con.close()


def test_a_damaged_cache_is_made_again_and_another_programs_file_is_left_alone(tmp_path):
    path = tmp_path / "thumbnails.sqlite"
    path.write_bytes(b"not a database at all")
    cache = ThumbnailCache(str(path))
    cache.put("a.stl", 1, 1, b"png")
    assert cache.get("a.stl", 1, 1) == b"png"
    for i in range(50):
        cache.put(f"b{i}.stl", 1, 1, b"q" * 2000)
    cache.close()
    data = bytearray(path.read_bytes())
    data[1024:] = b"\xa5" * (len(data) - 1024)  # every page after the first is garbage
    path.write_bytes(bytes(data))
    cache = ThumbnailCache(str(path))
    assert cache.get("b3.stl", 1, 1) is None  # damaged: made again
    cache.put("a.stl", 1, 1, b"png")
    assert cache.get("a.stl", 1, 1) == b"png"
    cache.close()
    other = tmp_path / "other.sqlite"
    con = sqlite3.connect(other)
    con.execute("PRAGMA application_id = 1234")
    con.execute("CREATE TABLE t (x)")
    con.commit()
    con.close()
    before = other.read_bytes()
    cache = ThumbnailCache(str(other))
    cache.put("a.stl", 1, 1, b"png")
    assert cache.get("a.stl", 1, 1) is None
    cache.close()
    assert other.read_bytes() == before
