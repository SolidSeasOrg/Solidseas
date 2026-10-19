"""Drawing Settings: the file, every value checked on its own, fallbacks, first-use
prompts and the logo (docs/DRAWINGS.md 7)."""

import hashlib
import json
import os
import struct
import zlib

import pytest

from solidseas.drawing import settings as S
from solidseas.errors import InvalidArgumentError, OutputRefusedError, SldLimitError


def data(**changes):
    d = json.loads(S.dumps(S.DrawingSettings()))
    for path, value in changes.items():
        group, key = path.split("__")
        d[group][key] = value
    return d


def test_the_defaults_round_trip_through_the_file(tmp_path):
    target = tmp_path / "Drawing.json"
    defaults = S.DrawingSettings()
    S.save_settings(defaults, target)
    loaded, problems = S.load_settings(target)
    assert loaded == defaults and problems == []
    assert json.loads(target.read_text("utf-8"))["schema"] == S.SCHEMA
    assert target.read_bytes().endswith(b"\n")


def test_a_missing_file_gives_the_defaults_without_a_problem(tmp_path):
    loaded, problems = S.load_settings(tmp_path / "none.json")
    assert loaded == S.DrawingSettings() and problems == []


def test_a_bad_value_falls_back_alone_and_says_so():
    d = data(
        company__name="Example Engineering Co.",
        company__phone=5,
        sheets__size="F",
        files__replace_own_files="yes",
    )
    loaded, problems = S.from_dict(d)
    assert loaded.company.name == "Example Engineering Co."
    assert loaded.company.phone == "" and loaded.sheets.size == "auto"
    assert loaded.files.replace_own_files is True  # Q14: on by default
    assert len(problems) == 3
    assert any(p.startswith("company.phone:") and "default" in p for p in problems)


def test_bad_records_are_dropped_one_by_one():
    people = [
        {"name": "Ann Bee", "initials": "AB"},
        {"name": ""},
        "x",
        {"initials": "Q"},
        {"name": "C D", "x": 1},
    ]
    loaded, problems = S.from_dict(data(people__people=people))
    assert loaded.people.people == ({"name": "Ann Bee", "initials": "AB"},)
    assert len(problems) == 4 and all("left out" in p for p in problems)


def test_members_a_newer_version_wrote_are_kept_and_written_back():
    d = data()
    d["future_group"] = {"a": [1, 2]}
    d["sheets"]["future_key"] = True
    loaded, problems = S.from_dict(d)
    assert problems == []
    out = S.to_dict(loaded)
    assert out["future_group"] == {"a": [1, 2]} and out["sheets"]["future_key"] is True


def test_a_newer_schema_is_read_as_far_as_it_goes_and_another_is_refused():
    d = data(company__name="Example Engineering Co.")
    d["schema"] = "solidseas.drawing-settings/2"
    loaded, problems = S.from_dict(d)
    assert loaded.company.name == "Example Engineering Co." and "newer" in problems[0]
    d["schema"] = "something-else/1"
    loaded, problems = S.from_dict(d)
    assert loaded == S.DrawingSettings() and "not Drawing Settings" in problems[0]
    assert S.from_dict([1, 2])[1]


@pytest.mark.parametrize(
    "raw, words",
    [
        (b'{"schema": "solidseas.drawing-settings/1", "a": 1, "a": 2}', "twice"),
        (b'{"schema": "solidseas.drawing-settings/1", "limits": {"draft_faces": NaN}}', "not a number"),
        (b"\xff\xfe{}", "not valid"),
        (b"[" * 40 + b"]" * 40, "nested"),
        (b"{", "not valid"),
    ],
)
def test_the_strict_json_rules_hold(tmp_path, raw, words):
    target = tmp_path / "Drawing.json"
    target.write_bytes(raw)
    loaded, problems = S.load_settings(target)
    assert loaded == S.DrawingSettings()
    assert len(problems) == 1 and words in problems[0]


def test_a_file_over_256_kib_is_not_read(tmp_path):
    target = tmp_path / "Drawing.json"
    target.write_bytes(b" " * (S.MAX_BYTES + 1))
    loaded, problems = S.load_settings(target)
    assert loaded == S.DrawingSettings() and "256 KiB" in problems[0]


def test_settings_over_256_kib_are_not_written(tmp_path):
    big = S.DrawingSettings(unknown=(("future", None, "x" * S.MAX_BYTES),))
    with pytest.raises(SldLimitError):
        S.save_settings(big, tmp_path / "Drawing.json")
    assert not (tmp_path / "Drawing.json").exists()


def test_save_replaces_through_a_rename_and_never_through_a_link(tmp_path):
    target = tmp_path / "Drawing.json"
    S.save_settings(S.DrawingSettings(), target)
    changed = S.with_value(S.DrawingSettings(), "company", "name", "Example Engineering Co.")
    S.save_settings(changed, target)
    assert S.load_settings(target)[0].company.name == "Example Engineering Co."
    assert [p.name for p in tmp_path.iterdir()] == ["Drawing.json"]  # no temporary file left
    if hasattr(os, "symlink"):
        real = tmp_path / "real.json"
        real.write_text("{}")
        link = tmp_path / "link.json"
        try:
            os.symlink(real, link)
        except OSError:
            pytest.skip("this system makes no links")
        with pytest.raises(OutputRefusedError):
            S.save_settings(changed, link)
        assert real.read_text() == "{}"


def test_first_use_lists_what_still_needs_the_users_answer():
    s = S.DrawingSettings()
    assert s.first_use() == ("standard.unit_for_unstated", "company.name", "people.people")
    s = S.with_value(s, "standard", "unit_for_unstated", "mm")
    s = S.with_value(s, "company", "name", "Example Engineering Co.")
    s = S.with_value(s, "people", "people", [{"name": "Ann Bee", "initials": "AB"}])
    assert s.first_use() == ()


def test_with_value_checks_as_loading_does():
    with pytest.raises(InvalidArgumentError):
        S.with_value(S.DrawingSettings(), "sheets", "size", "Z")
    with pytest.raises(InvalidArgumentError):
        S.with_value(S.DrawingSettings(), "nope", "size", "A")
    with pytest.raises(InvalidArgumentError):
        S.with_value(S.DrawingSettings(), "sheets", "nope", "A")


def test_note_templates_hold_only_known_tokens():
    loaded, problems = S.from_dict(data(notes__machined=["BREAK EDGES {edge_break}", "{secret_path}"]))
    assert loaded.notes.machined == S.DrawingSettings().notes.machined
    assert "secret_path" in problems[0]


def test_the_webmail_template_is_https_and_names_only_the_subject():
    loaded, problems = S.from_dict(data(email__webmail_url="http://example.invalid/?s={subject}"))
    assert loaded.email.webmail_url.startswith("https://") and problems
    loaded, problems = S.from_dict(data(email__webmail_url="https://example.invalid/?s={subject}&p={path}"))
    assert problems


def test_the_name_pattern_must_hold_the_number():
    loaded, problems = S.from_dict(data(files__name_pattern="{revision}"))
    assert loaded.files.name_pattern == "{number} {revision}" and problems


def test_materials_match_folded_with_spaces_collapsed():
    s = S.DrawingSettings()
    assert s.material("6061-T6   (SS)")["callout"] == "ALUMINUM 6061-T6"
    assert s.material("AISI 304")["density"] == 8000.0
    assert s.material("Unobtainium") is None and s.material(None) is None


def test_the_tolerance_block_and_precisions_come_from_the_settings():
    s = S.DrawingSettings()
    rows = s.block("in")
    assert [(r.places, float(r.plus_minus)) for r in rows] == [(1, 0.03), (2, 0.01), (3, 0.005)]
    assert s.precision("in", "hole_size") == 3 and s.precision("mm", "envelope") == 1
    loaded, problems = S.from_dict(data(tolerances__inch_block=[[2, 0.01], [2, 0.02]]))
    assert problems and loaded.tolerances.inch_block == s.tolerances.inch_block


def test_the_folder_follows_the_system():
    assert S.settings_folder({"APPDATA": r"D:\Settings\Roaming"}, "win32").endswith("SolidSeas")
    assert S.settings_folder({"XDG_CONFIG_HOME": "/cfg"}, "linux") == os.path.join("/cfg", "solidseas")
    assert "Application Support" in S.settings_folder({}, "darwin")


def png(width=10, height=10, depth=8, colour=6, interlace=0):
    ihdr = struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0, interlace)
    chunk = struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr))
    return b"\x89PNG\r\n\x1a\n" + chunk + b"\x00\x00\x00\x00IEND\xaeB`\x82"


def test_the_logo_must_be_the_narrow_png_whose_hash_was_recorded():
    good = png()
    assert S.logo_problem(good, hashlib.sha256(good).hexdigest()) is None
    assert "match" in S.logo_problem(good, "0" * 64)
    for bad, words in [
        (png(depth=16), "8-bit"),
        (png(colour=3), "8-bit"),
        (png(interlace=1), "interlacing"),
        (png(width=1201), "1,200"),
        (b"GIF89a" + b"\x00" * 40, "not a PNG"),
    ]:
        assert words in S.logo_problem(bad, hashlib.sha256(bad).hexdigest())
    assert S.logo_problem(good, None) == "no logo is set"


def test_the_detail_level_of_new_drawings_is_a_setting():
    assert S.DrawingSettings().defaults.detail == "full"
    schema = "solidseas.drawing-settings/1"
    made, problems = S.from_dict({"schema": schema, "defaults": {"detail": "simplified"}})
    assert made.defaults.detail == "simplified" and not problems
    made, problems = S.from_dict({"schema": schema, "defaults": {"detail": "rough"}})
    assert made.defaults.detail == "full" and problems
