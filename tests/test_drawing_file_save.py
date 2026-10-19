"""Saving drawings and their exports: what Save may replace, names, and folders
(docs/DRAWINGS.md 12.5, 12.6, Q8 and Q14; dwg-file)."""

import hashlib
import json
import os
from dataclasses import replace

import pytest

from solidseas.drawing import document as doc
from solidseas.drawing import settings as S
from solidseas.drawing import types as T
from solidseas.errors import InvalidArgumentError, OutputRefusedError
from test_drawing_file import NOW, hand_drawing, people_settings

PDF = b"%PDF-1.7\n1 0 obj << /Producer (SolidSeas 0.2.85) >> endobj\n%%EOF\n"
DXF = b"999\nSolidSeas 0.2.85\n  0\nSECTION\n  0\nEOF\n"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def drawing_with(**files):
    """The hand-built drawing with its files settings changed."""
    s = people_settings()
    for key, value in files.items():
        s = S.with_value(s, "files", key, value)
    return hand_drawing(settings=s)


# --------------------------------------------------------------------------- save


def test_save_writes_a_new_file_and_its_hash(tmp_path):
    target = tmp_path / "1234-001.ssdrw"
    saved = doc.save(hand_drawing(), target, now="2026-10-05T09:00:00-04:00")
    data = target.read_bytes()
    assert saved.path == str(target) and saved.sha256 == sha(data) and saved.size == len(data)
    assert saved.drawing.modified == "2026-10-05T09:00:00-04:00" and saved.drawing.created == NOW
    loaded = doc.read(target)
    assert loaded.sha256 == saved.sha256 and loaded.problems == () and loaded.drawing == saved.drawing
    assert doc.load(target) == saved.drawing
    assert not [p for p in tmp_path.iterdir() if p.name != "1234-001.ssdrw"]  # no temporary left


def test_save_refuses_a_path_that_exists_unless_replaces_is_its_hash(tmp_path):
    target = tmp_path / "1234-001.ssdrw"
    first = doc.save(hand_drawing(), target, now=NOW)
    before = target.read_bytes()
    with pytest.raises(OutputRefusedError) as info:
        doc.save(hand_drawing(), target, now=NOW)
    assert info.value.detail["rule"] == "exists"
    with pytest.raises(OutputRefusedError) as info:
        doc.save(hand_drawing(), target, replaces="0" * 64, now=NOW)
    assert info.value.detail["rule"] == "changed"
    assert target.read_bytes() == before
    edited = hand_drawing(notes=())
    second = doc.save(edited, target, replaces=first.sha256, now=NOW)
    assert second.sha256 != first.sha256 and target.read_bytes() != before
    assert doc.load(target).notes == ()
    # the hash recorded before is stale now: a third save must give the new one
    with pytest.raises(OutputRefusedError):
        doc.save(hand_drawing(), target, replaces=first.sha256, now=NOW)


def test_save_never_writes_through_a_link_or_onto_something_else(tmp_path):
    real = tmp_path / "real.ssdrw"
    real.write_bytes(b"{}")
    link = tmp_path / "link.ssdrw"
    try:
        link.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("this system makes no symbolic links here")
    with pytest.raises(OutputRefusedError) as info:
        doc.save(hand_drawing(), link, replaces=sha(b"{}"), now=NOW)
    assert info.value.detail["rule"] == "link"
    assert real.read_bytes() == b"{}"
    folder = tmp_path / "folder.ssdrw"
    folder.mkdir()
    with pytest.raises(OutputRefusedError) as info:
        doc.save(hand_drawing(), folder, replaces="0" * 64, now=NOW)
    assert info.value.detail["rule"] == "not_a_file"


@pytest.mark.parametrize(
    "call",
    [
        lambda p: doc.save(hand_drawing(), p / "drawing.json", now=NOW),
        lambda p: doc.save("not a drawing", p / "x.ssdrw", now=NOW),
        lambda p: doc.save(hand_drawing(), p / "x.ssdrw", replaces="ABC", now=NOW),
        lambda p: doc.save(hand_drawing(), p / "x.ssdrw", now="tomorrow"),
    ],
)
def test_save_checks_its_arguments(tmp_path, call):
    with pytest.raises(InvalidArgumentError):
        call(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_read_takes_only_a_plain_file(tmp_path):
    with pytest.raises(InvalidArgumentError) as info:
        doc.read(tmp_path)
    assert info.value.detail["rule"] == "not_a_file"
    if hasattr(os, "mkfifo"):
        fifo = tmp_path / "pipe.ssdrw"
        os.mkfifo(fifo)
        with pytest.raises(InvalidArgumentError):
            doc.read(fifo)  # refused, never opened (which would wait for a writer)


def test_load_lists_problems_as_warnings(tmp_path):
    obj = json.loads(doc.dumps(hand_drawing()))
    obj["status"] = "SHIPPED"
    target = tmp_path / "x.ssdrw"
    target.write_bytes(json.dumps(obj).encode("utf-8"))
    d = doc.load(target)
    assert d.status == "PRELIMINARY" and any(w.startswith("status:") for w in d.warnings)


# --------------------------------------------------------------------------- what Save may replace (Q14)


def test_with_replace_own_files_on_save_replaces_only_the_drawings_own_unchanged_file(tmp_path):
    d = drawing_with(replace_own_files=True)
    path = tmp_path / "1234-001.ssdrw"
    assert doc.save_target(d, path) == doc.Target(str(path))
    first = doc.save(d, path, now=NOW)
    t = doc.save_target(d, path, loaded_sha256=first.sha256)
    assert t.path == str(path) and t.replaces == first.sha256 and not t.renamed
    doc.save(replace(d, notes=()), t.path, replaces=t.replaces, now=NOW)
    # without the recorded hash, or with a stale one, Save takes a new name
    for loaded in (None, first.sha256):
        t = doc.save_target(d, path, loaded_sha256=loaded)
        assert t.path == str(tmp_path / "1234-001 (2).ssdrw") and t.replaces is None and t.renamed
        assert "1234-001 (2).ssdrw" in t.words


def test_save_never_replaces_another_drawing_or_a_file_solidseas_did_not_write(tmp_path):
    d = drawing_with(replace_own_files=True)
    path = tmp_path / "1234-001.ssdrw"
    other = doc.save(replace(d, id="another-drawing"), path, now=NOW)
    t = doc.save_target(d, path, loaded_sha256=other.sha256)
    assert t.renamed and t.replaces is None  # same hash, another drawing's id
    foreign = tmp_path / "notes.ssdrw"
    foreign.write_bytes(b"my own notes")
    t = doc.save_target(d, foreign, loaded_sha256=sha(b"my own notes"))
    assert t.renamed and t.path == str(tmp_path / "notes (2).ssdrw")


def test_with_replace_own_files_off_every_save_is_a_new_file(tmp_path):
    d = drawing_with(replace_own_files=False)
    path = tmp_path / "1234-001.ssdrw"
    first = doc.save(d, path, now=NOW)
    t = doc.save_target(d, path, loaded_sha256=first.sha256)
    assert t.path == str(tmp_path / "1234-001 (2).ssdrw") and t.replaces is None
    assert "every save is a new file" in t.words
    doc.save(d, t.path, replaces=t.replaces, now=NOW)
    t3 = doc.save_target(d, t.path, loaded_sha256=None)
    assert t3.path == str(tmp_path / "1234-001 (3).ssdrw")
    assert path.read_bytes()  # the earlier one stays as it was


# --------------------------------------------------------------------------- names (12.5)


def test_exports_are_named_by_the_pattern_through_safe_stem_rules():
    d = hand_drawing()
    assert doc.export_name(d, "pdf") == "1234-001 A PRELIMINARY.pdf"
    assert doc.export_name(d, "dxf") == "1234-001 A PRELIMINARY.dxf"
    assert doc.export_name(replace(d, status="RELEASED"), "pdf") == "1234-001 A.pdf"
    assert doc.export_name(replace(d, status="CHECKED"), "pdf").endswith(" PRELIMINARY.pdf")
    assert doc.drawing_file_name(d) == "1234-001.ssdrw"
    s = S.with_value(d.settings, "files", "name_pattern", "{number} {title} rev {revision}")
    assert (
        doc.export_name(replace(d, settings=s), "pdf")
        == "1234-001 BRACKET, MOTOR MOUNT rev A PRELIMINARY.pdf"
    )
    b = replace(d, revisions=(*d.revisions, T.Revision("B", "MOVED HOLE")))
    assert doc.export_name(b, "pdf", released=True) == "1234-001 B.pdf"
    with pytest.raises(InvalidArgumentError):
        doc.export_name(d, "svg")


@pytest.mark.parametrize(
    "name, stem",
    [
        ("1234/001: <A>", "1234_001_ _A_"),
        ("..hidden..", "hidden"),
        ("", "drawing"),
        ("CON", "_CON"),
        ("nul.txt", "_nul.txt"),
        ("COM\u00b9", "_COM\u00b9"),
        ("Кронштейн 1", "Кронштейн 1"),
        ("a" * 200, "a" * 80),
        ("x\x00y\u2014z", "x_y_z"),
    ],
)
def test_safe_stem_mirrors_the_viewers_rules(name, stem):
    assert doc.safe_stem(name) == stem


def test_the_number_falls_back_to_the_part_number_then_the_model():
    d = hand_drawing(title=(("part_number", T.TitleField("P-77", "part")),))
    assert doc.export_name(d, "pdf") == "P-77 A PRELIMINARY.pdf"
    d = hand_drawing(title=())
    assert doc.drawing_file_name(d) == "bracket.ssdrw"
    long = hand_drawing(title=(("number", T.TitleField("N" * 120, "typed")),))
    assert len(doc.export_stem(long)) == 80 and doc.export_stem(long).endswith(" PRELIMINARY")


def test_the_next_free_name_counts_up(tmp_path):
    (tmp_path / "1234-001 A.pdf").write_bytes(b"x")
    (tmp_path / "1234-001 A (2).pdf").write_bytes(b"x")
    assert doc.next_free_name(tmp_path, "1234-001 A", ".pdf") == str(tmp_path / "1234-001 A (3).pdf")
    assert doc.next_free_name(tmp_path, "free", ".pdf") == str(tmp_path / "free.pdf")
    with pytest.raises(OutputRefusedError) as info:
        doc.next_free_name(tmp_path, "x", ".pdf", exists=lambda p: True)
    assert info.value.detail["rule"] == "exists"
    names = list(doc.candidate_names("s", ".dxf"))
    assert names[:3] == ["s.dxf", "s (2).dxf", "s (3).dxf"] and len(names) == doc.MAX_TRIES


# --------------------------------------------------------------------------- exports (12.5, 12.6)


def write_export(d, folder, kind, data):
    t = doc.export_target(d, folder, kind)
    saved = doc.write_output(t.path, lambda fh: fh.write(data), replaces=t.replaces)
    return t, saved, doc.record_output(d, kind, os.path.basename(saved.path), saved.sha256)


def test_preliminary_exports_are_kept_current_when_they_are_solidseas_own(tmp_path):
    d = drawing_with()
    t, saved, d = write_export(d, tmp_path, "pdf", PDF)
    assert t.replaces is None and os.path.basename(t.path) == "1234-001 A PRELIMINARY.pdf"
    assert d.outputs[-1] == T.Output("pdf", "1234-001 A PRELIMINARY.pdf", sha(PDF), "A", False)
    newer = PDF.replace(b"%%EOF", b"% newer\n%%EOF")
    t2, saved2, d2 = write_export(d, tmp_path, "pdf", newer)
    assert t2.path == t.path and t2.replaces == sha(PDF) and not t2.renamed
    assert (tmp_path / "1234-001 A PRELIMINARY.pdf").read_bytes() == newer
    assert [o.sha256 for o in d2.outputs if o.name == "1234-001 A PRELIMINARY.pdf"] == [sha(newer)]
    t3, _s, _d = write_export(d2, tmp_path, "dxf", DXF)
    t4 = doc.export_target(_d, tmp_path, "dxf")
    assert t4.replaces == sha(DXF)


def test_an_export_changed_or_not_written_by_solidseas_is_never_replaced(tmp_path):
    d = drawing_with()
    _t, _saved, d = write_export(d, tmp_path, "pdf", PDF)
    target = tmp_path / "1234-001 A PRELIMINARY.pdf"
    target.write_bytes(PDF + b"% edited by hand\n")
    t = doc.export_target(d, tmp_path, "pdf")
    assert t.renamed and t.path.endswith("1234-001 A PRELIMINARY (2).pdf") and t.replaces is None
    # the same hash as recorded, but no SolidSeas producer: not ours
    foreign = b"%PDF-1.7\n/Producer (Other Tool)\n%%EOF\n"
    target.write_bytes(foreign)
    d = doc.record_output(d, "pdf", "1234-001 A PRELIMINARY.pdf", sha(foreign))
    assert doc.export_target(d, tmp_path, "pdf").renamed
    dxf = tmp_path / "1234-001 A PRELIMINARY.dxf"
    dxf.write_bytes(b"0\nSECTION\n")
    d = doc.record_output(d, "dxf", dxf.name, sha(dxf.read_bytes()))
    assert doc.export_target(d, tmp_path, "dxf").renamed


@pytest.mark.parametrize("files", [{"replace_own_files": False}, {"keep_preliminary_current": False}])
def test_with_the_setting_off_every_export_is_a_new_file(tmp_path, files):
    d = drawing_with(**files)
    _t, _saved, d = write_export(d, tmp_path, "pdf", PDF)
    t = doc.export_target(d, tmp_path, "pdf")
    assert t.renamed and t.replaces is None and t.path.endswith(" PRELIMINARY (2).pdf")


def test_released_exports_are_written_once_and_never_replaced(tmp_path):
    d = replace(drawing_with(), status="RELEASED")
    t, saved, d = write_export(d, tmp_path, "pdf", PDF)
    assert os.path.basename(t.path) == "1234-001 A.pdf" and d.outputs[-1].released
    again = doc.export_target(d, tmp_path, "pdf")
    assert again.renamed and again.replaces is None and again.path.endswith("1234-001 A (2).pdf")
    assert "released files are never replaced" in again.words
    with pytest.raises(OutputRefusedError) as info:
        doc.write_output(t.path, lambda fh: fh.write(b"x"))
    assert info.value.detail["rule"] == "exists"
    with pytest.raises(OutputRefusedError) as info:
        doc.record_output(d, "pdf", "1234-001 A.pdf", "0" * 64)
    assert info.value.detail["rule"] == "released"
    assert (tmp_path / "1234-001 A.pdf").read_bytes() == PDF


def test_write_output_is_bounded_and_checked(tmp_path):
    from solidseas.drawing.limits import DrawingLimits
    from solidseas.errors import SldLimitError

    with pytest.raises(SldLimitError):
        doc.write_output(
            tmp_path / "big.pdf", lambda fh: fh.write(b"x" * 2048), limits=DrawingLimits(output_bytes=1024)
        )
    assert list(tmp_path.iterdir()) == []  # a failed write leaves nothing
    with pytest.raises(InvalidArgumentError):
        doc.write_output(tmp_path / "x.exe", lambda fh: fh.write(b"x"))
    with pytest.raises(InvalidArgumentError):
        doc.record_output(hand_drawing(), "pdf", "../x.pdf", "0" * 64)
    with pytest.raises(InvalidArgumentError):
        doc.record_output(hand_drawing(revisions=()), "pdf", "x.pdf", "0" * 64)


def test_solidseas_files_are_recognised_by_what_they_say(tmp_path):
    p = tmp_path / "a.pdf"
    p.write_bytes(PDF)
    assert doc.says_solidseas(str(p), "pdf")
    p.write_bytes(b"%PDF-1.7\n/Producer (SolidSeasonal)\n")
    assert not doc.says_solidseas(str(p), "pdf")
    big = b"%PDF-1.7\n" + b"x" * (doc.HASH_CHUNK - 10) + b"/Producer (SolidSeas 1)"
    p.write_bytes(big)
    assert doc.says_solidseas(str(p), "pdf")  # found across a chunk boundary
    x = tmp_path / "a.dxf"
    x.write_bytes(DXF.replace(b"\n", b"\r\n"))
    assert doc.says_solidseas(str(x), "dxf")
    x.write_bytes(b"  0\nSECTION\n999\nSolidSeas\n")
    assert not doc.says_solidseas(str(x), "dxf")
    assert not doc.says_solidseas(str(tmp_path / "none.pdf"), "pdf")


# --------------------------------------------------------------------------- folders (12.6, Q8)


def test_a_plain_local_folder_is_fine_and_odd_ones_are_refused(tmp_path):
    assert doc.folder_problem(tmp_path, tmp_path) is None
    assert doc.folder_problem(tmp_path / "none") is not None
    f = tmp_path / "file"
    f.write_bytes(b"x")
    assert doc.folder_problem(f) == doc.FOLDER_NOT_A_FOLDER
    assert doc.folder_problem("") == doc.FOLDER_ODD
    real = tmp_path / "real"
    real.mkdir()
    (real / "sub").mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        return
    assert doc.folder_problem(link) == doc.FOLDER_LINKED
    assert doc.folder_problem(link / "sub") == doc.FOLDER_LINKED  # below a link


def test_windows_network_and_device_folders_are_refused_from_their_text():
    def kinds(root):
        return {"C:\\": doc.DRIVE_FIXED, "Z:\\": doc.DRIVE_REMOTE}.get(root, 0)

    win = {"windows": True, "drive_type": kinds}
    assert doc.folder_problem("\\\\server\\share\\parts", **win) == doc.FOLDER_NETWORK
    assert doc.folder_problem("Z:\\parts", **win) == doc.FOLDER_NETWORK
    # inside the folder opened, a share is not refused for being one (on Windows it is then looked at)
    assert doc.folder_problem("Z:\\parts\\a", "Z:\\parts", **win) != doc.FOLDER_NETWORK
    assert doc.folder_problem("\\\\?\\C:\\parts", **win) == doc.FOLDER_ODD
    assert doc.folder_problem("C:\\parts\\x.pdf:stream", **win) == doc.FOLDER_ODD
    assert doc.is_local("C:\\parts", **win) and not doc.is_local("Z:\\parts", **win)
    assert not doc.is_local("\\\\server\\share", **win)
