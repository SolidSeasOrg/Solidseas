"""Reference resolution never touches what it must not (``docs/API.md`` C2).

* A planted UNC path or mapped network drive in a document is never ``stat``'d,
  opened or passed to ``realpath``: every filesystem entry point is trapped for
  the planted host, the trap is shown to work, and the gateway is shown to have
  received the path and refused it, so the test cannot pass by never asking.
* A junction or symbolic link inside a root leads nowhere (with a control that
  proves it really leads outside).
* Point lookups decide links and cloud placeholders by reparse tag and
  attribute, and a placeholder is never opened.
* No module of ``solidseas.resolve`` but the gateway calls the filesystem.
"""

import builtins
import io
import os
import pathlib
import re
import sys
from pathlib import Path

import pytest

from builders import TreeXml, part_with_creation_time, resolving_assembly
from fakefs import ARCHIVE, DIRECTORY, REPARSE, FakeStat
from solidseas import open_document
from solidseas.formats.solidworks import _io
from solidseas.resolve import Gateway, resolve_references
from solidseas.resolve import gateway as gateway_mod
from solidseas.resolve.names import host_split
from solidseas.walk import FILE_ATTRIBUTE_OFFLINE, FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS

CT = 1_700_000_000
WINDOWS = sys.platform == "win32"
RESOLVE_DIR = Path(gateway_mod.__file__).parent


def _assembly(stored: str, folder_at_save: str = "") -> bytes:
    t = TreeXml()
    t.top("m1")
    t.file("2", stored, swCreationTime=str(CT))
    t.model("m2", "2")
    t.ref("m1", "p", 1, "m2")
    return resolving_assembly(t, folder_at_save=folder_at_save)


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _trap(monkeypatch, needle: str) -> list[str]:
    """Make every filesystem entry point fail the test when called with a path that
    contains ``needle``. Returns the list the traps append to."""
    hits: list[str] = []

    def guard(name, real):
        def wrapper(*args, **kwargs):
            for a in args[:1]:
                text = os.fspath(a) if isinstance(a, (str, os.PathLike)) else ""
                if needle.casefold() in str(text).casefold():
                    hits.append(f"{name}({text})")
                    raise AssertionError(f"{name} was called with the planted path {text!r}")
            return real(*args, **kwargs)

        return wrapper

    for mod, attr in [
        (os, "stat"),
        (os, "lstat"),
        (os, "open"),
        (os, "scandir"),
        (os, "listdir"),
        (os, "access"),
        (os.path, "exists"),
        (os.path, "lexists"),
        (os.path, "isfile"),
        (os.path, "isdir"),
        (os.path, "realpath"),
        (builtins, "open"),
        (io, "open"),
        (_io, "open_readonly"),
        (gateway_mod, "_lstat"),
        (gateway_mod, "_open_document"),
        (gateway_mod, "_Walk"),
    ]:
        monkeypatch.setattr(mod, attr, guard(f"{getattr(mod, '__name__', mod)}.{attr}", getattr(mod, attr)))
    for attr in ("stat", "lstat", "exists", "is_file", "open", "resolve"):
        real = getattr(pathlib.Path, attr)

        def method(self, *a, _real=real, _attr=attr, **k):
            if needle.casefold() in str(self).casefold():
                hits.append(f"Path.{_attr}({self})")
                raise AssertionError(f"Path.{_attr} was called with the planted path {self}")
            return _real(self, *a, **k)

        monkeypatch.setattr(pathlib.Path, attr, method)
    return hits


@pytest.fixture
def no_fake_drives(monkeypatch):
    real = gateway_mod._drive_type
    monkeypatch.setattr(
        gateway_mod, "_drive_type", lambda root: 1 if root.upper().startswith("Q:") else real(root)
    )


def test_a_planted_unc_path_is_never_touched(tmp_path, monkeypatch, no_fake_drives):
    planted = "\\\\evilhost\\share\\proj\\p.SLDPRT"
    folder = tmp_path / "Doc"
    _write(folder / "p.SLDPRT", part_with_creation_time(CT))
    doc = _write(folder / "asm.SLDASM", _assembly(planted, "\\\\evilhost\\share\\proj\\"))
    with open_document(doc) as d:
        hits = _trap(monkeypatch, "evilhost")
        with pytest.raises(AssertionError):
            os.lstat(planted)  # the trap works
        with pytest.raises(AssertionError):
            os.path.realpath(planted)
        hits.clear()
        gw = Gateway()
        (r,) = resolve_references(d, gateway=gw).results.values()
    assert hits == []
    # resolved from where the document is, and the share was never asked
    assert (r.status, r.rule, r.match.path) == ("moved", "rebased", "p.SLDPRT")
    assert "stored_unc_not_checked" in [w.code for w in r.warnings]
    planted_calls = [c for c in gw.calls if "evilhost" in c[1]]
    if WINDOWS:  # the stored path reached the gateway, which refused it on its anchor alone
        assert planted_calls == [("point", planted, "refused:unc")]
    else:  # a stored Windows path is never a path on this machine
        assert planted_calls == [] and any(op == "walk" for op, _p, _o in gw.calls)


@pytest.mark.skipif(not WINDOWS, reason="drive letters exist only on Windows")
def test_a_mapped_network_drive_is_never_touched(tmp_path, monkeypatch):
    monkeypatch.setattr(gateway_mod, "_drive_type", lambda root: 4 if root.upper().startswith("Z:") else 3)
    planted = "Z:\\proj\\p.SLDPRT"
    doc = _write(tmp_path / "Doc" / "asm.SLDASM", _assembly(planted))
    with open_document(doc) as d:
        hits = _trap(monkeypatch, "Z:\\")
        gw = Gateway()
        (r,) = resolve_references(d, gateway=gw).results.values()
    assert hits == [] and r.status == "missing"
    assert "stored_network_drive_not_checked" in [w.code for w in r.warnings]
    assert ("point", planted, "refused:network_drive") in gw.calls


@pytest.mark.skipif(not WINDOWS, reason="junctions are Windows")
def test_a_junction_inside_a_root_leads_nowhere(tmp_path, no_fake_drives):
    import _winapi

    root, outside = tmp_path / "Root", tmp_path / "Outside"
    _write(outside / "p.SLDPRT", part_with_creation_time(CT))
    root.mkdir()
    _winapi.CreateJunction(str(outside), str(root / "link"))
    assert (root / "link" / "p.SLDPRT").is_file()  # control: the junction really leads outside
    doc = _write(root / "asm.SLDASM", _assembly("Q:\\Old\\link\\p.SLDPRT", "Q:\\Old\\"))
    gw = Gateway()
    with open_document(doc) as d:
        (r,) = resolve_references(d, gateway=gw).results.values()
    assert r.status == "missing" and r.candidates == ()
    # nothing below the root was looked up or opened, the junction's file included
    assert [c for c in gw.calls if c[0] != "walk"] == [("point", "Q:\\Old\\link\\p.SLDPRT", "absent_drive")]
    os.rmdir(root / "link")


@pytest.mark.skipif(WINDOWS, reason="symbolic links need a privilege on Windows")
def test_a_symbolic_link_inside_a_root_leads_nowhere(tmp_path, no_fake_drives):  # pragma: no cover - POSIX
    root, outside = tmp_path / "Root", tmp_path / "Outside"
    _write(outside / "p.SLDPRT", part_with_creation_time(CT))
    root.mkdir()
    os.symlink(outside, root / "link")
    assert (root / "link" / "p.SLDPRT").is_file()  # control
    doc = _write(root / "asm.SLDASM", _assembly("Q:\\Old\\link\\p.SLDPRT", "Q:\\Old\\"))
    gw = Gateway()
    with open_document(doc) as d:
        (r,) = resolve_references(d, gateway=gw).results.values()
    assert r.status == "missing" and [c for c in gw.calls if c[0] != "walk"] == []


# --------------------------------------------------------------------------- point lookups
_LINKS = [
    ("junction", 0xA0000003),
    ("symlink", 0xA000000C),
    ("wsl symlink", 0xA000001D),
    ("global reparse", 0xA0000019),
    ("unreported tag", 0),
]


def test_point_lookups_decide_links_and_placeholders_by_tag(tmp_path, monkeypatch):
    host = host_split(str(tmp_path / "x.SLDPRT"))
    cases = [
        ("dedup file", FakeStat(ARCHIVE | REPARSE, 0x80000013, 123), "file"),
        ("cloud folder", FakeStat(DIRECTORY | REPARSE, 0x9000701A), "not_a_document"),
        *[(n, FakeStat(ARCHIVE | REPARSE, tag), "not_a_document") for n, tag in _LINKS],
        ("folder link", FakeStat(DIRECTORY | REPARSE, 0xA0000003), "not_a_document"),
        (
            "recall on access",
            FakeStat(ARCHIVE | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS, 0x9000601A, 9),
            "placeholder",
        ),
        ("offline", FakeStat(ARCHIVE | FILE_ATTRIBUTE_OFFLINE, 0, 9), "placeholder"),
        ("plain file", FakeStat(ARCHIVE, 0, 5), "file"),
    ]
    seen = []
    for name, st, expected in cases:
        monkeypatch.setattr(gateway_mod, "_lstat", lambda path, _st=st: _st)
        got = Gateway().point_lookup(host)
        kind = got if isinstance(got, str) else ("placeholder" if got.placeholder else "file")
        assert kind == expected, name
        if not isinstance(got, str):
            assert got.size == st.st_size, name
        seen.append(kind)
    assert seen.count("not_a_document") == 7 and seen.count("placeholder") == 2 and seen.count("file") == 2


def test_a_placeholder_is_never_opened(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(gateway_mod, "_open_document", lambda *a, **k: opened.append(a) or None)
    monkeypatch.setattr(
        gateway_mod, "_lstat", lambda path: FakeStat(ARCHIVE | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS, 0, 7)
    )
    gw = Gateway()
    hit = gw.point_lookup(host_split(str(tmp_path / "cloud.SLDPRT")))
    assert hit.placeholder is True
    ident = gw.read_identity(hit.path, within=str(tmp_path), placeholder=True)
    assert ident.placeholder and ident.creation_time is None and opened == []
    assert gw.calls[-1] == ("identity", hit.path, "placeholder_not_read")


def test_the_gateway_opens_only_what_it_found(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(gateway_mod, "_open_document", lambda *a, **k: opened.append(a))
    real = _write(tmp_path / "p.SLDPRT", part_with_creation_time(CT))
    gw = Gateway()
    ident = gw.read_identity(str(real), within=str(tmp_path), placeholder=False)
    assert ident.error == "path_refused" and opened == []
    assert gw.calls == [("identity", str(real), "refused:not_found_by_gateway")]


def test_point_lookups_outside_the_roots_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setattr(gateway_mod, "_lstat", lambda path: pytest.fail("lstat was called"))
    gw = Gateway(allow_outside_roots=False)
    path = str(tmp_path / "p.SLDPRT")
    assert gw.point_lookup(host_split(path)) == "outside_roots"
    assert gw.calls == [("point", path, "refused:outside_roots")]


@pytest.mark.skipif(not WINDOWS, reason="anchors are Windows")
def test_anchor_classes_are_decided_from_the_text(monkeypatch):
    types = {"C:\\": 3, "E:\\": 2, "Z:\\": 4, "Y:\\": 1, "R:\\": 5}
    monkeypatch.setattr(gateway_mod, "_drive_type", lambda root: types[root.upper()])
    gw = Gateway()
    got = {
        p: gw.anchor_class(host_split(p))
        for p in (
            "C:\\a",
            "e:\\a",
            "Z:\\a",
            "Y:\\a",
            "R:\\a",
            "\\\\h\\s\\a",
            "\\\\?\\C:\\a",
            "\\\\.\\pipe\\a",
        )
    }
    assert got == {
        "C:\\a": "local",
        "e:\\a": "local",
        "Z:\\a": "network_drive",
        "Y:\\a": "absent_drive",
        "R:\\a": "other_drive",
        "\\\\h\\s\\a": "unc",
        "\\\\?\\C:\\a": "device_path",
        "\\\\.\\pipe\\a": "device_path",
    }


# --------------------------------------------------------------------------- one gateway
_FORBIDDEN = [
    r"\bos\.(stat|lstat|scandir|listdir|walk|open|access|readlink|getcwd|chdir|replace|remove)\b",
    r"\b(os\.path|ntpath|posixpath|_host)\.(exists|lexists|isfile|isdir|islink|isjunction|ismount|realpath"
    r"|abspath|getsize|getmtime|samefile|expanduser)\b",
    r"(?<![\w.])open\(",
    r"\b(pathlib|shutil|ctypes|subprocess|socket|glob|tempfile)\b",
    r"\bio\.",
    r"\b(open_document|open_container|open_readonly|scandir|Walk|_lstat)\b",
]


def _code_only(source: str) -> str:
    q = chr(34) * 3
    without_docstrings = re.sub(q + ".*?" + q, "", source, flags=re.S)
    return "\n".join(line.split("#", 1)[0] for line in without_docstrings.split("\n"))


def test_only_the_gateway_touches_the_filesystem():
    modules = sorted(RESOLVE_DIR.glob("*.py"))
    others = [p for p in modules if p.name != "gateway.py"]
    assert len(modules) >= 6 and len(others) >= 5, "the source scan found too few modules"
    gateway = _code_only((RESOLVE_DIR / "gateway.py").read_text(encoding="utf-8"))
    for anchor in ("_lstat(", "_open_document(", "_Walk(", "_drive_type(", "_abspath("):
        assert anchor in gateway, anchor  # the gateway is where the calls are
    core = _code_only((RESOLVE_DIR / "core.py").read_text(encoding="utf-8"))
    calls = ("self.gateway.build_index(", "self.gateway.point_lookup(", "self.gateway.read_identities(")
    for anchor in calls:
        assert anchor in core, anchor  # and the rules reach the filesystem through it
    found = []
    for p in others:
        code = _code_only(p.read_text(encoding="utf-8"))
        for rx in _FORBIDDEN:
            found += [f"{p.name}: {m.group()}" for m in re.finditer(rx, code)]
    assert found == []
    # the check itself notices a call: the gateway's own code is full of them
    assert sum(len(re.findall(rx, gateway)) for rx in _FORBIDDEN) >= 4
