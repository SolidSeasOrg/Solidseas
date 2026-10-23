"""Extensions (``solidseas_app.extensions``, ``docs/EXTENSIONS.md``): the catalog, the
on/off state, the machine policy, and packages checked before anything is unpacked."""

import hashlib
import json
import os
import stat
import zipfile
from pathlib import Path

import pytest

from solidseas import policy
from solidseas_app import extensions as X

HELPER = b"MZ a stand-in helper program"


def _manifest(mid: str = "video", **changes) -> dict:
    core = X.CATALOG[mid]
    raw = core.to_json()
    raw["helper"] = {
        "program": core.helper["program"],
        "protocol": 1,
        "memory_mb": 512,
        "seconds": 300,
        "files": {core.helper["program"]: hashlib.sha256(HELPER).hexdigest()},
    }
    raw["notices"] = ["FFmpeg is licensed under the LGPL 2.1."]
    raw.update(changes)
    return raw


def _zip(tmp_path, entries, name="video-1.zip"):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for entry in entries:
            if isinstance(entry, zipfile.ZipInfo):
                z.writestr(entry, b"target")
            else:
                n, data = entry
                z.writestr(n, data)
    return path


def _package(tmp_path, manifest=None, extra=(), helper=HELPER):
    m = manifest or _manifest()
    program = m["helper"]["program"]
    return _zip(tmp_path, [("extension.json", json.dumps(m)), (program, helper), *extra])


def _accept(path, mid="video"):
    return {mid: [hashlib.sha256(path.read_bytes()).hexdigest()]}


def test_the_catalog_holds_the_first_four_and_each_is_checked():
    assert list(X.CATALOG) == ["gridfinity", "cad-bridge", "video", "solidcraft", "occt"]
    assert X.CATALOG["gridfinity"].kind == "built_in" and X.CATALOG["gridfinity"].network == "ssh"
    assert {X.CATALOG[i].kind for i in ("cad-bridge", "video", "occt")} == {"packaged"}
    assert all(X.CATALOG[i].network == "none" for i in ("cad-bridge", "video", "occt"))
    assert X.manifest(_manifest()).helper["memory_mb"] == 512


def test_a_package_this_core_accepts_is_added_and_removed(tmp_path):
    pkg = _package(tmp_path)
    checked = X.check_package(str(pkg), accepted=_accept(pkg))
    assert checked.manifest.id == "video" and set(checked.files) == {"extension.json", "solidseas-video.exe"}
    root = tmp_path / "extensions"
    target = X.add_package(checked, root=str(root))
    assert (root / "video" / "solidseas-video.exe").read_bytes() == HELPER
    assert X.added_manifest("video", str(root)).notices == ("FFmpeg is licensed under the LGPL 2.1.",)
    assert sorted(os.listdir(root)) == ["video"], "no temporary folder is left"
    again = X.add_package(checked, root=str(root))  # an update over it
    assert again == target and sorted(os.listdir(root)) == ["video"]
    assert X.remove_package("video", root=str(root)) and not (root / "video").exists()
    assert not X.remove_package("video", root=str(root))


def test_a_package_from_another_release_or_changed_is_refused(tmp_path):
    pkg = _package(tmp_path)
    with pytest.raises(X.ExtensionError, match="not one this version of SolidSeas accepts"):
        X.check_package(str(pkg), accepted={})
    with pytest.raises(X.ExtensionError, match="not one this version"):
        X.check_package(str(pkg), accepted={"video": ["0" * 64]})


@pytest.mark.parametrize(
    "extra, why",
    [
        ([("../outside.txt", b"x")], "not a path inside the package"),
        ([("C:/Windows/evil.dll", b"x")], "not a path inside the package"),
        ([("bin/con.txt", b"x")], "not a path inside the package"),
        ([("SOLIDSEAS-VIDEO.EXE", b"x")], "twice"),
        ([("readme.txt", b"x")], "not listed"),
    ],
)
def test_a_package_whose_entries_leave_its_folder_or_differ_is_refused(tmp_path, extra, why):
    pkg = _package(tmp_path, extra=extra)
    with pytest.raises(X.ExtensionError, match=why):
        X.check_package(str(pkg), accepted=_accept(pkg))


def test_a_link_a_bomb_a_wrong_file_or_a_manifest_that_differs_is_refused(tmp_path):
    link = zipfile.ZipInfo("link")
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    pkg = _package(tmp_path, extra=[link])
    with pytest.raises(X.ExtensionError, match="is a link"):
        X.check_package(str(pkg), accepted=_accept(pkg))
    bomb = _package(tmp_path, extra=[("big.bin", b"\0" * 5_000_000)])
    with pytest.raises(X.ExtensionError, match="larger than SolidSeas unpacks"):
        X.check_package(str(bomb), accepted=_accept(bomb))
    wrong = _package(tmp_path, helper=b"MZ something else")
    with pytest.raises(X.ExtensionError, match="not the file its manifest names"):
        X.check_package(str(wrong), accepted=_accept(wrong))
    reaches = _package(tmp_path, _manifest(reaches={"network": "loopback", "folders": []}))
    with pytest.raises(X.ExtensionError, match="does not match this SolidSeas"):
        X.check_package(str(reaches), accepted=_accept(reaches))
    other = _package(tmp_path, _manifest(publisher="Someone"))
    with pytest.raises(X.ExtensionError, match="only SolidSeas' own"):
        X.check_package(str(other), accepted=_accept(other))
    not_zip = tmp_path / "x.zip"
    not_zip.write_bytes(b"not a zip")
    with pytest.raises(X.ExtensionError, match="not a zip"):
        X.check_package(str(not_zip), accepted=_accept(not_zip))


def test_the_state_keeps_what_was_there_and_survives_a_damaged_file(tmp_path):
    path = str(tmp_path / "SolidSeas" / X.STATE_FILE)
    assert X.read_state(path).on == X.DEFAULT_ON == {"gridfinity"}, "what was already there stays on"
    state = X.switched(X.read_state(path), "gridfinity", True)
    X.write_state(path, state)
    assert X.read_state(path).on == {"gridfinity"}
    with open(path, "w") as fh:
        fh.write('{"version": 1, "on": ["gridfinity", "unknown", 3]}')
    assert X.read_state(path).on == {"gridfinity"}, "unknown ids are dropped"
    with open(path, "w") as fh:
        fh.write("{damaged")
    assert X.read_state(path).on == X.DEFAULT_ON
    X.write_state(path, X.switched(X.read_state(path), "gridfinity", False))
    assert X.read_state(path).on == frozenset(), "switched off, it stays off"
    with pytest.raises(X.ExtensionError):
        X.switched(state, "plugin", True)


def test_an_extension_is_on_only_when_switched_on_allowed_and_added(tmp_path):
    root = str(tmp_path / "extensions")
    state = X.ExtensionState(frozenset({"gridfinity", "video"}))
    free = policy.Policy()
    assert X.on_ids(state, pol=free, root=root) == {"gridfinity"}, "video's package is not added"
    by_id = {s.manifest.id: s for s in X.statuses(state, pol=free, root=root)}
    assert by_id["video"].blocked == "Add its package first" and not by_id["video"].on
    assert by_id["gridfinity"].on and by_id["gridfinity"].added
    pkg = _package(tmp_path)
    X.add_package(X.check_package(str(pkg), accepted=_accept(pkg)), root=root)
    assert X.on_ids(state, pol=free, root=root) == {"gridfinity", "video"}
    assert X.statuses(state, pol=free, root=root)[2].added_version == X.CATALOG["video"].version
    only = policy.Policy(allowed_extensions=("video",), locked=True)
    assert X.on_ids(state, pol=only, root=root) == {"video"}
    off = policy.Policy(extensions_disabled=True, locked=True)
    assert X.on_ids(state, pol=off, root=root) == frozenset()
    assert {s.blocked for s in X.statuses(state, pol=off, root=root)} == {"Set by your administrator"}


def test_the_package_folder_is_never_a_link_followed(tmp_path):
    root = tmp_path / "extensions"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    try:
        os.symlink(outside, root / "video", target_is_directory=True)
    except OSError:
        pytest.skip("this system cannot make a link")
    with pytest.raises(X.ExtensionError, match="link"):
        X.remove_package("video", root=str(root))
    pkg = _package(tmp_path)
    with pytest.raises(X.ExtensionError, match="not a folder SolidSeas made"):
        X.add_package(X.check_package(str(pkg), accepted=_accept(pkg)), root=str(root))
    assert (outside / "keep.txt").read_text() == "keep" and sorted(os.listdir(root)) == ["video"]


STANDIN = b"""import json, sys
print(json.dumps({"event": "ready", "protocol": 1, "helper": "video"}), flush=True)
for line in sys.stdin:
    msg = json.loads(line)
    if msg["op"] == "shutdown":
        print(json.dumps({"id": msg["id"], "ok": True, "result": {}}), flush=True)
        break
    print(json.dumps({"id": msg["id"], "ok": True, "result": {"echo": msg.get("args", {})}}), flush=True)
"""


def test_a_packaged_extension_s_helper_runs_only_while_on_and_unchanged(tmp_path):
    import sys

    m = _manifest()
    m["helper"]["files"] = {"solidseas-video.exe": hashlib.sha256(STANDIN).hexdigest()}
    pkg = _package(tmp_path, m, helper=STANDIN)
    root = str(tmp_path / "extensions")
    X.add_package(X.check_package(str(pkg), accepted=_accept(pkg)), root=root)
    on = X.ExtensionState(frozenset({"video"}))
    launch = lambda program: [sys.executable, "-I", program]  # noqa: E731
    with pytest.raises(X.HelperRefused, match="is off"):
        X.start_helper("video", X.ExtensionState(), pol=policy.Policy(), root=root, launcher=launch)
    with pytest.raises(X.HelperRefused, match="built in"):
        X.start_helper("gridfinity", on, pol=policy.Policy(), root=root, launcher=launch)
    helper = X.start_helper("video", on, pol=policy.Policy(), root=root, launcher=launch)
    try:
        assert helper.ready["helper"] == "video" and helper.label == "the Video export helper"
        assert helper.request("encode", {"frames": 3})["echo"] == {"frames": 3}
        assert helper.hard_limit == 300.0
    finally:
        helper.close(timeout=10)
    with open(os.path.join(root, "video", "solidseas-video.exe"), "ab") as fh:
        fh.write(b"\n# changed after it was added\n")
    with pytest.raises(X.HelperRefused, match="not the file it was added with"):
        X.start_helper("video", on, pol=policy.Policy(), root=root, launcher=launch)


def test_a_package_built_from_a_folder_is_the_same_bytes_and_the_core_accepts_it(tmp_path):
    from solidseas_app.extensions import package

    folder = tmp_path / "bridge"
    (folder / "lib").mkdir(parents=True)
    (folder / "SolidSeas.SwBridge.exe").write_bytes(b"MZ the bridge")
    (folder / "lib" / "Interop.dll").write_bytes(b"MZ interop")
    one = package.build_package("cad-bridge", str(folder), str(tmp_path / "a"), memory_mb=4096, seconds=86400)
    # the former id builds the same package, under the current id
    two = package.build_package("solidworks", str(folder), str(tmp_path / "b"), memory_mb=4096, seconds=86400)
    assert os.path.basename(one) == f"cad-bridge-{X.CATALOG['cad-bridge'].version}.zip"
    assert open(one, "rb").read() == open(two, "rb").read(), "the same files, the same bytes"
    listed = package.write_accepted([one], str(tmp_path / "accepted.json"))
    assert listed == {"cad-bridge": [hashlib.sha256(open(one, "rb").read()).hexdigest()]}
    assert package.read_accepted(str(tmp_path / "accepted.json")) == {
        "cad-bridge": frozenset(listed["cad-bridge"])
    }
    checked = X.check_package(one, accepted=listed)
    assert set(checked.files) == {"extension.json", "SolidSeas.SwBridge.exe", "lib/Interop.dll"}
    assert checked.manifest.helper["memory_mb"] == 4096
    with pytest.raises(X.ExtensionError, match="is not a packaged extension"):
        package.build_package("gridfinity", str(folder), str(tmp_path / "c"))
    (folder / "SolidSeas.SwBridge.exe").unlink()
    with pytest.raises(X.ExtensionError, match="has no SolidSeas.SwBridge.exe"):
        package.build_package("cad-bridge", str(folder), str(tmp_path / "d"))


def test_a_source_checkout_accepts_no_package():
    assert X.ACCEPTED == {} or set(X.ACCEPTED) <= set(X.CATALOG)


def test_the_solidworks_bridge_comes_from_the_bridge_s_package_while_it_is_on(tmp_path, monkeypatch):
    from solidseas.swapi import bridge

    monkeypatch.delenv(bridge.ENV_BRIDGE, raising=False)
    monkeypatch.setattr(bridge, "find_bridge", lambda explicit=None: None)
    root = str(tmp_path / "extensions")
    free = policy.Policy()
    path, why = X.solidworks_bridge(X.ExtensionState(), pol=free, root=root)
    assert path is None and "not added" in why
    folder = tmp_path / "bridge"
    folder.mkdir()
    (folder / "SolidSeas.SwBridge.exe").write_bytes(b"MZ")
    from solidseas_app.extensions import package

    pkg = package.build_package("cad-bridge", str(folder), str(tmp_path / "out"))
    X.add_package(
        X.check_package(pkg, accepted=_accept(__import__("pathlib").Path(pkg), "cad-bridge")), root=root
    )
    assert X.solidworks_bridge(X.ExtensionState(), pol=free, root=root) == (None, X.ENGINE_OFF)
    on = X.ExtensionState(frozenset({"cad-bridge"}))
    assert X.solidworks_bridge(on, pol=free, root=root)[0] == os.path.join(
        root, "cad-bridge", "SolidSeas.SwBridge.exe"
    )
    locked = policy.Policy(extensions_disabled=True, locked=True)
    assert X.solidworks_bridge(on, pol=locked, root=root)[0] is None
    monkeypatch.setenv(bridge.ENV_BRIDGE, str(folder / "SolidSeas.SwBridge.exe"))
    assert X.solidworks_bridge(X.ExtensionState(), pol=free, root=root)[0] == str(
        folder / "SolidSeas.SwBridge.exe"
    )
    # a developer's build is a bridge too: an administrator's policy holds for it
    path, why = X.solidworks_bridge(X.ExtensionState(), pol=locked, root=root)
    assert path is None and "administrator" in why
    monkeypatch.delenv(bridge.ENV_BRIDGE)
    # a bridge changed since its package was added is never run, as for every helper
    (tmp_path / "extensions" / "cad-bridge" / "SolidSeas.SwBridge.exe").write_bytes(b"MZ changed")
    path, why = X.solidworks_bridge(on, pol=free, root=root)
    assert path is None and "not the file it was added with" in why


def test_an_install_from_before_the_bridge_was_renamed_keeps_working_and_is_migrated(tmp_path, monkeypatch):
    """The extension ``solidworks`` became ``cad-bridge``. Its switch in Extensions.json, an
    administrator's AllowedExtensions, a release's accepted.json and a package added under
    the old id all still count, and adding the new package replaces the old folder."""
    from solidseas.swapi import bridge
    from solidseas_app.extensions import package

    monkeypatch.delenv(bridge.ENV_BRIDGE, raising=False)
    monkeypatch.setattr(bridge, "find_bridge", lambda explicit=None: None)
    assert X.current_id("solidworks") == "cad-bridge" and X.former_ids("cad-bridge") == ("solidworks",)
    state_file = tmp_path / "Extensions.json"
    state_file.write_text(json.dumps({"version": 1, "on": ["solidworks", "video"]}), encoding="utf-8")
    state = X.read_state(str(state_file))
    assert state.on == {"cad-bridge", "video"}
    X.write_state(str(state_file), state)
    assert json.loads(state_file.read_text(encoding="utf-8"))["on"] == ["cad-bridge", "video"]
    assert X.switched(state, "solidworks", False).on == {"video"}

    old_policy = policy.Policy(allowed_extensions=("solidworks",))
    assert policy.extension_allowed(old_policy, "cad-bridge") and policy.extension_allowed(
        old_policy, "solidworks"
    )
    assert not policy.extension_allowed(policy.Policy(allowed_extensions=("video",)), "cad-bridge")
    assert policy.extension_allowed(policy.Policy(allowed_extensions=("cad-bridge",)), "solidworks")

    accepted = tmp_path / "accepted.json"
    accepted.write_text(json.dumps({"version": 1, "accepted": {"solidworks": ["a" * 64]}}), encoding="utf-8")
    assert package.read_accepted(str(accepted)) == {"cad-bridge": frozenset({"a" * 64})}

    # a package added by a release from before the rename, in its own folder and manifest
    root = tmp_path / "extensions"
    legacy = root / "solidworks"
    legacy.mkdir(parents=True)
    exe = b"MZ the old bridge"
    (legacy / "SolidSeas.SwBridge.exe").write_bytes(exe)
    raw = X.CATALOG["cad-bridge"].to_json()
    raw.update(id="solidworks", version="0.0.1", name="SOLIDWORKS engine")
    raw["helper"] = {
        "program": "SolidSeas.SwBridge.exe",
        "protocol": 1,
        "memory_mb": 4096,
        "seconds": 86400,
        "files": {"SolidSeas.SwBridge.exe": hashlib.sha256(exe).hexdigest()},
    }
    (legacy / "extension.json").write_text(json.dumps(raw), encoding="utf-8")
    assert X.installed_dir("solidworks", str(root)) == str(root / "cad-bridge")
    assert X.added_manifest("cad-bridge", str(root)).version == "0.0.1"
    assert X.is_on("cad-bridge", state, pol=old_policy, root=str(root))
    assert X.solidworks_bridge(state, pol=old_policy, root=str(root))[0] == str(
        legacy / "SolidSeas.SwBridge.exe"
    )
    found = {s.manifest.id: s for s in X.statuses(state, pol=old_policy, root=str(root))}
    assert found["cad-bridge"].added and found["cad-bridge"].added_version == "0.0.1"

    folder = tmp_path / "bridge"
    folder.mkdir()
    (folder / "SolidSeas.SwBridge.exe").write_bytes(b"MZ the new bridge")
    pkg = package.build_package("cad-bridge", str(folder), str(tmp_path / "out"))
    added = X.add_beside([str(tmp_path / "out")], root=str(root), accepted=_accept(Path(pkg), "cad-bridge"))
    assert added == ["cad-bridge"] and not legacy.exists()
    assert X.solidworks_bridge(state, pol=old_policy, root=str(root))[0] == str(
        root / "cad-bridge" / "SolidSeas.SwBridge.exe"
    )
    # removing it removes a former id's folder too, should one be left
    legacy.mkdir()
    (legacy / "extension.json").write_text(json.dumps(raw), encoding="utf-8")
    assert X.remove_package("solidworks", root=str(root)) and not legacy.exists()
    assert not (root / "cad-bridge").exists()


def test_a_package_that_still_says_the_former_id_is_refused(tmp_path):
    """An old ``solidworks`` zip is not the core's own manifest for ``cad-bridge``."""
    raw = _manifest("cad-bridge", id="solidworks")
    pkg = _package(tmp_path, raw)
    with pytest.raises(X.ExtensionError, match="says it is 'solidworks'"):
        X.check_package(str(pkg), accepted=_accept(pkg, "cad-bridge"))


FAKE_FFMPEG = """import sys, json, os
args = sys.argv[1:]
if "-encoders" in args:
    print(" V....D h264_mf              H264 via MediaFoundation")
    print(" V....D mpeg4                MPEG-4 part 2")
    sys.exit(0)
out = args[-1]
if os.path.exists(out) and "-n" in args:
    sys.exit(1)
with open(out, "w") as fh:
    json.dump(args, fh)
"""


@pytest.mark.skipif(os.name == "nt", reason="the stand-in ffmpeg is a script started through its #! line")
def test_the_video_helper_encodes_frames_through_its_ffmpeg_and_never_over_a_file(tmp_path, monkeypatch):
    import sys

    from solidseas_app.extensions import video_helper as V

    fake = tmp_path / "ffmpeg"
    fake.write_text("#!" + sys.executable + "\n" + FAKE_FFMPEG)
    fake.chmod(0o755)
    monkeypatch.setenv("SOLIDSEAS_FFMPEG", str(fake))
    frames, out = tmp_path / "frames", tmp_path / "out"
    frames.mkdir()
    out.mkdir()
    got = V.encode(
        {"frames": str(frames), "out_dir": str(out), "name": "spin.mp4", "fps": 30, "format": "mp4"}
    )
    assert got["encoder"] == "h264_mf" and got["path"] == str(out / "spin.mp4")
    args = json.loads((out / "spin.mp4").read_text())
    assert (
        args[args.index("-c:v") + 1] == "h264_mf" and "-n" in args and str(frames / "frame%05d.png") in args
    )
    gif = V.encode(
        {"frames": str(frames), "out_dir": str(out), "name": "spin.gif", "fps": 15, "format": "gif"}
    )
    assert "paletteuse" in " ".join(json.loads(open(gif["path"]).read()))
    for bad in (
        {"name": "spin.mp4"},  # already there
        {"name": "../spin2.mp4"},
        {"name": "spin2.avi", "format": "mp4"},
        {"name": "spin2.mp4", "format": "gif"},
        {"name": "spin2.mp4", "fps": 120},
    ):
        args = {
            "frames": str(frames),
            "out_dir": str(out),
            "name": "x.mp4",
            "fps": 30,
            "format": "mp4",
            **bad,
        }
        with pytest.raises(V.Refused):
            V.encode(args)


def test_the_viewer_build_carries_the_extensions_and_the_list_it_accepts():
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    text = (root / "packaging" / "SolidSeasViewer.spec").read_text(encoding="utf-8")
    hidden = text[text.index("hiddenimports=[") : text.index("excludes=EXCLUDES")]
    for needed in (
        '"solidseas.helpers"',
        '"solidseas_app.extensions"',
        '"solidseas_app.viewer.extensionsdialog"',
        '"solidseas_app.viewer.animationaction"',
    ):
        assert needed in hidden, needed
    assert '"solidseas_app/extensions") for p in [ACCEPTED]' in text
    excludes = text[text.index("EXCLUDES = ") : text.index("# The only Qt plugins")]
    for needed in ("zipfile", "hashlib", "_hashlib", "zlib", "json"):  # the package checks need them
        assert not re.search(rf'"{needed}"', excludes), needed
    build = (root / "scripts" / "build-extensions.ps1").read_text(encoding="utf-8")
    assert "accepted.json" in build and "SHA256SUMS.txt" in build and "solidseas-video" in build
    for ext in ("video", "cad-bridge", "occt"):
        assert ext in X.CATALOG
    assert X.CATALOG["video"].helper["program"] == "solidseas-video.exe"


def test_a_notice_is_a_licence_s_whole_text_line_breaks_and_all(tmp_path):
    from solidseas_app.extensions import package

    licence = "GNU LESSER GENERAL PUBLIC LICENSE\r\n\tVersion 3, 29 June 2007\n\nCopyright (C) 2007\n"
    assert X.manifest(_manifest(notices=[licence])).notices == (licence,)
    with pytest.raises(X.ExtensionError, match="notices is not text"):
        X.manifest(_manifest(notices=["a bell\x07 in a licence"]))
    with pytest.raises(X.ExtensionError, match="on one line"):
        X.manifest(_manifest(description="two\nlines"))
    folder = tmp_path / "video"
    folder.mkdir()
    (folder / "solidseas-video.exe").write_bytes(HELPER)
    built = package.build_package("video", str(folder), str(tmp_path / "out"), notices=[licence])
    checked = X.check_package(built, accepted=_accept(__import__("pathlib").Path(built)))
    assert checked.manifest.notices == (licence,)


def test_a_notice_file_with_a_byte_order_mark_is_carried_without_it(tmp_path):
    from solidseas_app.extensions import package

    folder = tmp_path / "video"
    folder.mkdir()
    (folder / "solidseas-video.exe").write_bytes(HELPER)
    pointer = tmp_path / "pointer.txt"  # as Windows PowerShell's Set-Content -Encoding UTF8 writes it
    pointer.write_bytes(b"\xef\xbb\xbfThe licences are in THIRD-PARTY-LICENSES.txt in this package.\r\n")
    out = tmp_path / "out"
    built_ok = package.main(
        ["build", "--id", "video", "--from", str(folder), "--out", str(out), "--notice", str(pointer)]
    )
    assert built_ok == 0
    built = next(out.glob("video-*.zip"))
    notices = X.check_package(str(built), accepted=_accept(built)).manifest.notices
    assert notices == ("The licences are in THIRD-PARTY-LICENSES.txt in this package.\n",)


def test_the_lgpl_text_is_carried_as_a_notice_without_its_form_feeds(tmp_path):
    from pathlib import Path

    from solidseas_app.extensions import package

    lgpl = Path(__file__).resolve().parents[1] / "licenses" / "LGPL-2.1.txt"
    assert "\f" in lgpl.read_text(encoding="utf-8")  # the FSF's text breaks pages with them
    folder = tmp_path / "video"
    folder.mkdir()
    (folder / "solidseas-video.exe").write_bytes(HELPER)
    out = tmp_path / "out"
    built_ok = package.main(
        ["build", "--id", "video", "--from", str(folder), "--out", str(out), "--notice", str(lgpl)]
    )
    assert built_ok == 0
    built = next(out.glob("video-*.zip"))
    (notice,) = X.check_package(str(built), accepted=_accept(built)).manifest.notices
    assert "\f" not in notice and "GNU LESSER GENERAL PUBLIC LICENSE" in notice


def test_packages_that_came_beside_the_viewer_are_added_once_and_left_off(tmp_path):
    from pathlib import Path

    from solidseas_app.extensions import package

    folder = tmp_path / "video"
    folder.mkdir()
    (folder / "solidseas-video.exe").write_bytes(HELPER)
    beside = tmp_path / "SolidSeas extensions"
    pkg = package.build_package("video", str(folder), str(beside))
    (beside / "stranger.zip").write_bytes(b"not a package")
    root = str(tmp_path / "root")
    accepted = _accept(Path(pkg), "video")
    free = policy.Policy()
    assert X.add_beside([str(beside)], root=root, accepted=accepted, pol=free) == ["video"]
    assert X.added_manifest("video", root) is not None
    assert not X.is_on("video", X.ExtensionState(), pol=free, root=root), "added, and off until switched on"
    assert X.add_beside([str(beside)], root=root, accepted=accepted, pol=free) == [], "once"
    locked = policy.Policy(extensions_disabled=True, locked=True)
    assert X.add_beside([str(beside)], root=str(tmp_path / "r2"), accepted=accepted, pol=locked) == []
    assert X.add_beside([str(tmp_path / "missing")], root=root, accepted=accepted, pol=free) == []
    assert X.beside_folders() == [], "a source checkout has none"
