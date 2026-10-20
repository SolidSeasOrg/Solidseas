"""Each folder's index kept between runs (``solidseas_app.viewer.savedindex``)."""

import os
import sqlite3

from solidseas_app.viewer import savedindex as SI

ROWS = [
    ({"path": f"p{n}.SLDPRT", "type": "file", "status": "ok"}, b"\x89PNG" + n.to_bytes(2, "big"))
    for n in range(600)
]


def test_a_saved_index_comes_back_in_order_with_its_age(tmp_path):
    root = str(tmp_path / "idx")
    folder = str(tmp_path / "Jobs")
    SI.save(folder, "all", (128, 96), ROWS, counts={"files": 600}, read_at=1000.0, root=root)
    got = SI.load(folder, "all", (128, 96), root=root)
    assert got is not None and got.rows == 600 and got.counts == {"files": 600}
    assert got.age_seconds(now=1000.0 + 3 * 3600 + 12 * 60) == 3 * 3600 + 12 * 60
    back = [row for batch in got.entries(batch=100) for row in batch]
    assert back == ROWS
    # another choice of what the list shows, or of the thumbnail size, is another index
    assert SI.load(folder, "solidworks", (128, 96), root=root) is None
    assert SI.load(folder, "all", (96, 72), root=root) is None
    # saved again: replaced whole, no temporary file left beside it
    SI.save(folder, "all", (128, 96), ROWS[:3], read_at=2000.0, root=root)
    assert SI.load(folder, "all", (128, 96), root=root).rows == 3
    assert [n for n in os.listdir(root) if n.startswith(".index-")] == []
    SI.forget(folder, "all", (128, 96), root=root)
    assert SI.load(folder, "all", (128, 96), root=root) is None


def test_an_index_is_kept_for_the_extension_formats_that_were_readable(tmp_path):
    """A folder read while the OCCT backend was on (IGES and BREP readable) is not shown once
    it is off, nor the other way round; a list of SOLIDWORKS documents alone is not
    affected, and with no extension format on an index keeps the name it had before."""
    root = str(tmp_path / "idx")
    folder = str(tmp_path / "Jobs")
    on = ("iges", "occt_brep")
    SI.save(folder, "all", (128, 96), ROWS[:2], read_at=1000.0, root=root, extensions=())
    SI.save(folder, "all", (128, 96), ROWS[:3], read_at=2000.0, root=root, extensions=on)
    assert SI.load(folder, "all", (128, 96), root=root, extensions=()).rows == 2
    assert SI.load(folder, "all", (128, 96), root=root, extensions=on).rows == 3
    assert SI.load(folder, "all", (128, 96), root=root, extensions=("iges",)) is None
    assert SI.load(folder, "all", (128, 96), root=root).rows == 2, "none is on in the tests"
    # an index saved before extensions read formats (no such entry) is good while none is on
    path = SI.index_path(folder, "all", (128, 96), root=root, extensions=())
    con = sqlite3.connect(path)
    con.execute("DELETE FROM meta WHERE key = 'extensions'")
    con.commit()
    con.close()
    assert SI.load(folder, "all", (128, 96), root=root, extensions=()).rows == 2
    SI.save(folder, "solidworks", (128, 96), ROWS[:4], root=root, extensions=on)
    assert SI.load(folder, "solidworks", (128, 96), root=root, extensions=()).rows == 4


def test_a_damaged_index_is_none_never_an_empty_folder(tmp_path):
    root = str(tmp_path / "idx")
    folder = str(tmp_path / "Jobs")
    path = SI.save(folder, "all", (128, 96), ROWS[:5], root=root)
    with open(path, "r+b") as fh:
        fh.write(b"not sqlite at all" * 10)
    assert SI.load(folder, "all", (128, 96), root=root) is None


def test_the_age_reads_as_hours_and_minutes():
    assert SI.age_text(30) == "less than a minute"
    assert SI.age_text(12 * 60) == "12 min"
    assert SI.age_text(3 * 3600 + 12 * 60) == "3 h 12 min"
    assert SI.age_text(5 * 3600) == "5 h"
    assert SI.age_text(26 * 3600) == "1 day 2 h"
    assert SI.age_text(3 * 86400) == "3 days"
