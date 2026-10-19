"""Finding a drawing's model (docs/DRAWINGS.md 13.6; dwg-file): the relative path kept
within the drawing's folder, the stored path only on a local drive, the catalog by
hash then name, and a changed file offered but never taken. Windows paths are judged
from their text with ``windows=True`` on any system."""

import hashlib
import os

import pytest

from solidseas.drawing import locate as L
from solidseas.errors import InvalidArgumentError
from test_drawing_file import hand_drawing

PART = b"a part's bytes"
CHANGED_PART = b"a part's bytes, saved again"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def model(**kw):
    out = {"name": "bracket.SLDPRT", "relative": "bracket.SLDPRT", "stored": None, "sha256": sha(PART)}
    out.update(kw)
    return out


def test_the_relative_path_next_to_the_drawing_is_found(tmp_path):
    (tmp_path / "bracket.SLDPRT").write_bytes(PART)
    found = L.find_model(tmp_path / "1234.ssdrw", model())
    assert found.found == L.Candidate(
        str(tmp_path / "bracket.SLDPRT"), "relative", sha(PART), True, L.MATCHES
    )
    (tmp_path / "parts").mkdir()
    (tmp_path / "parts" / "bracket.SLDPRT").write_bytes(PART)
    below = L.find_model(tmp_path / "1234.ssdrw", model(relative="parts/bracket.SLDPRT"))
    assert below.found.path == str(tmp_path / "parts" / "bracket.SLDPRT")


def test_a_changed_file_is_offered_and_never_taken(tmp_path):
    (tmp_path / "bracket.SLDPRT").write_bytes(CHANGED_PART)
    found = L.find_model(tmp_path / "1234.ssdrw", model())
    assert found.found is None
    assert found.changed == (
        L.Candidate(str(tmp_path / "bracket.SLDPRT"), "relative", sha(CHANGED_PART), False, L.CHANGED),
    )
    assert L.CHANGED == "this file has changed since the drawing was made"


@pytest.mark.parametrize(
    "relative",
    [
        "../bracket.SLDPRT",
        "parts/../../bracket.SLDPRT",
        "/etc/bracket.SLDPRT",
        "C:/x/bracket.SLDPRT",
        "a//b.SLDPRT",
        "con.SLDPRT",
        "x:y.SLDPRT",
    ],
)
def test_a_relative_path_that_leaves_the_folder_is_not_looked_at(tmp_path, relative):
    (tmp_path / "drawings").mkdir()
    (tmp_path / "bracket.SLDPRT").write_bytes(PART)
    found = L.find_model(tmp_path / "drawings" / "1234.ssdrw", model(relative=relative))
    assert found.candidates == () and found.skipped[0][0] == "relative"


def test_a_relative_path_through_a_link_is_not_followed(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "bracket.SLDPRT").write_bytes(PART)
    drawings = tmp_path / "drawings"
    drawings.mkdir()
    try:
        (drawings / "parts").symlink_to(elsewhere, target_is_directory=True)
        (drawings / "bracket.SLDPRT").symlink_to(elsewhere / "bracket.SLDPRT")
    except (OSError, NotImplementedError):
        pytest.skip("this system makes no symbolic links here")
    found = L.find_model(drawings / "1234.ssdrw", model(relative="parts/bracket.SLDPRT"))
    assert found.candidates == () and "link" in found.skipped[0][1]
    assert L.find_model(drawings / "1234.ssdrw", model()).candidates == ()  # the file itself is a link


def test_the_stored_path_is_looked_at_after_the_relative_one(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "bracket.SLDPRT").write_bytes(PART)
    found = L.find_model(tmp_path / "1234.ssdrw", model(relative=None, stored=str(other / "bracket.SLDPRT")))
    assert found.found.how == "stored" and found.found.path == str(other / "bracket.SLDPRT")
    (tmp_path / "bracket.SLDPRT").write_bytes(CHANGED_PART)
    both = L.find_model(tmp_path / "1234.ssdrw", model(stored=str(other / "bracket.SLDPRT")))
    assert [c.how for c in both.candidates] == ["relative", "stored"] and both.found.how == "stored"


def test_a_windows_stored_path_is_not_a_path_of_another_system(tmp_path):
    found = L.find_model(
        tmp_path / "x.ssdrw", model(relative=None, stored="C:\\parts\\bracket.SLDPRT"), windows=False
    )
    assert found.candidates == () and found.skipped == (
        ("stored", "the stored path is not a path of this computer"),
    )


def windows_files(*paths):
    """A stand-in file system for Windows paths: path to hash."""
    table = {p.lower(): h for p, h in paths}
    return lambda path: table.get(path.lower())


def drives(root):
    return {"C:\\": L.DRIVE_FIXED, "D:\\": L.DRIVE_REMOVABLE, "Z:\\": L.DRIVE_REMOTE}.get(root.upper(), 1)


def test_windows_paths_relative_stored_unc_and_mapped_drives():
    win = {"windows": True, "drive_type": drives}
    files = windows_files(
        ("C:\\work\\drawings\\parts\\bracket.SLDPRT", sha(PART)),
        ("D:\\archive\\bracket.SLDPRT", sha(PART)),
    )
    drawing = "C:\\work\\drawings\\1234.ssdrw"
    found = L.find_model(drawing, model(relative="parts\\bracket.SLDPRT"), file_hash=files, **win)
    assert found.found.path == "C:\\work\\drawings\\parts\\bracket.SLDPRT"
    leaves = L.find_model(drawing, model(relative="..\\parts\\bracket.SLDPRT"), file_hash=files, **win)
    assert leaves.candidates == () and leaves.skipped[0][0] == "relative"
    local = L.find_model(
        drawing, model(relative=None, stored="D:\\archive\\bracket.SLDPRT"), file_hash=files, **win
    )
    assert local.found.path == "D:\\archive\\bracket.SLDPRT" and local.found.how == "stored"
    cases = {
        "\\\\server\\share\\bracket.SLDPRT": "UNC",
        "Z:\\parts\\bracket.SLDPRT": "mapped network drive",
        "Q:\\parts\\bracket.SLDPRT": "not on a drive of this computer",
        "C:\\parts\\con.SLDPRT": "not one SolidSeas looks at",
        "\\\\?\\C:\\parts\\bracket.SLDPRT": "not one SolidSeas looks at",
        "C:\\parts\\bracket.SLDPRT:stream": "not one SolidSeas looks at",
        "parts\\bracket.SLDPRT": "not one SolidSeas looks at",
    }
    looked = []

    def counting(path):
        looked.append(path)
        return sha(PART)

    for stored, why in cases.items():
        found = L.find_model(drawing, model(relative=None, stored=stored), file_hash=counting, **win)
        assert found.candidates == () and why in found.skipped[0][1], stored
    assert looked == []  # nothing on a share or a mapped drive was ever touched


def test_the_catalog_is_asked_by_hash_then_by_name():
    win = {"windows": True, "drive_type": drives}
    files = windows_files(
        ("C:\\vault\\a\\bracket.SLDPRT", sha(PART)),
        ("C:\\vault\\b\\bracket.SLDPRT", sha(CHANGED_PART)),
    )
    catalog = L.catalog_lookup(
        {sha(PART): ["C:\\vault\\a\\bracket.SLDPRT"]},
        {"BRACKET.sldprt": ["C:\\vault\\b\\bracket.SLDPRT", "C:\\vault\\a\\bracket.SLDPRT"]},
    )
    found = L.find_model(
        "C:\\work\\1234.ssdrw", model(relative=None), catalog=catalog, file_hash=files, **win
    )
    assert [(c.path, c.matches) for c in found.candidates] == [
        ("C:\\vault\\a\\bracket.SLDPRT", True),
        ("C:\\vault\\b\\bracket.SLDPRT", False),
    ]
    assert found.found.how == "catalog" and len(found.changed) == 1
    # the catalog's answers are bounded
    many = L.find_model(
        "C:\\work\\1234.ssdrw",
        model(relative=None),
        catalog=lambda kind, value: [f"C:\\v\\{k}\\bracket.SLDPRT" for k in range(1000)],
        file_hash=lambda p: sha(CHANGED_PART),
        limit=5,
        **win,
    )
    assert len(many.candidates) == 5 and many.found is None


def test_a_missing_model_finds_nothing(tmp_path):
    found = L.find_model(tmp_path / "x.ssdrw", model(stored=str(tmp_path / "none.SLDPRT")))
    assert found.candidates == () and found.found is None
    with pytest.raises(InvalidArgumentError):
        L.find_model(tmp_path / "x.ssdrw", "not a model")


def test_the_model_reference_is_relative_inside_the_folder_else_absolute(tmp_path):
    drawing_path = tmp_path / "1234.ssdrw"
    assert L.model_reference(tmp_path / "bracket.SLDPRT", drawing_path) == {
        "relative": "bracket.SLDPRT",
        "stored": None,
    }
    assert L.model_reference(tmp_path / "parts" / "b.SLDPRT", drawing_path)["relative"] == "parts/b.SLDPRT"
    outside = tmp_path.parent / "b.SLDPRT"
    assert L.model_reference(outside, drawing_path) == {"relative": None, "stored": os.path.abspath(outside)}
    win = L.model_reference("C:\\work\\parts\\b.SLDPRT", "C:\\work\\1234.ssdrw", windows=True)
    assert win == {"relative": "parts/b.SLDPRT", "stored": None}
    away = L.model_reference("D:\\other\\b.SLDPRT", "C:\\work\\1234.ssdrw", windows=True)
    assert away == {"relative": None, "stored": "D:\\other\\b.SLDPRT"}


def test_saving_elsewhere_and_sending_set_the_paths(tmp_path):
    d = L.with_model_path(
        hand_drawing(), tmp_path / "parts" / "bracket.SLDPRT", tmp_path / "drawings" / "1234.ssdrw"
    )
    assert d.model["relative"] is None and d.model["stored"] == str(tmp_path / "parts" / "bracket.SLDPRT")
    assert d.model["name"] == "bracket.SLDPRT"
    sent = L.for_sending(d)
    assert sent.model["stored"] is None and sent.model["sha256"] == d.model["sha256"]
