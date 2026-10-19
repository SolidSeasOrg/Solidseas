"""Errors and warnings: the exception tree and its codes, what reading may raise on
crafted input, permission errors on every operating system, coded reader
warnings, the document type without a made-up "unknown(n)", and property type
tokens.

Every crafted input is built from the synthetic fixtures or from scratch.
"""

import copy
import os
import pickle
import random
import shutil
import sys

import pytest

import solidseas
from builders import fixture_streams, o05_with_ghost_configuration, rebuild
from solidseas import cli, model
from solidseas.errors import (
    WARNING_CODES,
    ConfigurationNotFoundError,
    FileTooLargeError,
    InvalidArgumentError,
    LinkRefusedError,
    LockedFileError,
    OutputRefusedError,
    ParasolidError,
    PathRefusedError,
    PlaceholderFileError,
    ReaderWarning,
    SldError,
    SldFormatError,
    SldIntegrityError,
    SldLimitError,
    SolidSeasError,
    StreamNotFoundError,
    UnknownFormatError,
    WorkerCrashedError,
    WorkerTimeoutError,
)
from solidseas.formats import solidworks as sw
from solidseas.formats.solidworks import _io, open_document
from solidseas.formats.solidworks import container as container_mod
from solidseas.formats.solidworks.localbodies import LocalBodiesError
from solidseas.formats.solidworks.metadata import _GUID_RE, PROPERTY_TYPES
from solidseas.formats.solidworks.propset import PropSetError
from support import FIXTURES, NATIVE, fixture_path

O02 = fixture_path("o02_boxA.SLDPRT")
O06 = fixture_path("o06_boxA_props_mat_cfg.SLDPRT")


def _all_subclasses(cls: type) -> list[type]:
    out = []
    for sub in cls.__subclasses__():
        out.append(sub)
        out.extend(_all_subclasses(sub))
    return out


# --------------------------------------------------------------------------- the exception tree
def test_every_01_class_keeps_its_name_and_bases():
    # 0.1 callers import these from the reader package and catch them by these bases.
    assert sw.SldError is SldError and sw.LockedFileError is LockedFileError
    for name in (
        "SldError",
        "UnknownFormatError",
        "LockedFileError",
        "SldFormatError",
        "SldIntegrityError",
        "SldLimitError",
        "ParasolidError",
    ):
        assert getattr(sw, name) is getattr(sw.errors, name) is getattr(solidseas, name)
    assert issubclass(UnknownFormatError, SldError)
    assert issubclass(LockedFileError, SldError) and issubclass(LockedFileError, OSError)
    assert issubclass(SldFormatError, SldError)
    assert issubclass(SldIntegrityError, SldFormatError)
    assert issubclass(SldLimitError, SldFormatError)
    assert issubclass(ParasolidError, SldFormatError)
    assert issubclass(PropSetError, SldFormatError) and issubclass(LocalBodiesError, SldFormatError)
    assert cli.Refused is OutputRefusedError
    assert not issubclass(cli.Refused, SldError)  # a batch still tells a refusal from a bad file


def test_new_classes_and_their_bases():
    assert issubclass(SldError, SolidSeasError)
    assert issubclass(FileTooLargeError, SldLimitError)
    assert issubclass(StreamNotFoundError, KeyError) and issubclass(ConfigurationNotFoundError, KeyError)
    assert issubclass(PathRefusedError, ValueError) and issubclass(InvalidArgumentError, ValueError)
    assert issubclass(LinkRefusedError, PathRefusedError) and issubclass(OutputRefusedError, PathRefusedError)
    assert issubclass(PlaceholderFileError, OSError)
    assert issubclass(WorkerTimeoutError, TimeoutError)
    assert issubclass(WorkerCrashedError, SolidSeasError)


CODES = {
    SolidSeasError: "internal",
    InvalidArgumentError: "invalid_argument",
    SldError: "damaged_file",
    UnknownFormatError: "unknown_format",
    LockedFileError: "locked",
    SldFormatError: "damaged_file",
    SldIntegrityError: "damaged_file",
    ParasolidError: "damaged_file",
    SldLimitError: "limit_exceeded",
    FileTooLargeError: "file_too_large",
    StreamNotFoundError: "stream_not_found",
    ConfigurationNotFoundError: "configuration_not_found",
    PathRefusedError: "path_refused",
    LinkRefusedError: "link_refused",
    OutputRefusedError: "output_refused",
    PlaceholderFileError: "placeholder_file",
    WorkerTimeoutError: "timeout",
    WorkerCrashedError: "worker_crashed",
}


def test_each_class_carries_its_stable_code():
    for cls, code in CODES.items():
        assert cls.code == code, cls.__name__


def test_every_error_class_is_reachable_from_the_package():
    """API.md 9: ``solidseas`` exports the exception classes of 3.3, so ``except
    solidseas.X`` works for every class ``solidseas.errors`` lists."""
    import solidseas.errors as errors_mod

    classes = [n for n in errors_mod.__all__ if isinstance(getattr(errors_mod, n), type)]
    missing = [n for n in classes if getattr(solidseas, n, None) is not getattr(errors_mod, n)]
    assert missing == []
    assert not [n for n in classes if n not in solidseas.__all__]
    assert solidseas.NotRepresentableError.code == "not_representable"


def test_every_library_exception_has_a_known_code():
    classes = [SolidSeasError, *_all_subclasses(SolidSeasError)]
    assert len(classes) >= len(CODES), "the subclass walk found fewer classes than the table lists"
    for cls in classes:
        assert cls.code in model.ERROR_CODES, cls.__name__


def test_locked_file_error_keeps_its_os_error_fields_and_pickles():
    exc = LockedFileError(32, "file is locked by another process", "part.SLDPRT")
    assert (exc.errno, exc.strerror, exc.filename) == (32, "file is locked by another process", "part.SLDPRT")
    assert str(exc) == "[Errno 32] file is locked by another process: 'part.SLDPRT'"
    again = pickle.loads(pickle.dumps(exc))
    assert type(again) is LockedFileError and again.filename == "part.SLDPRT"


def test_detail_survives_pickling_and_key_errors_read_plainly():
    exc = PathRefusedError("refused", detail={"rule": "dot_component", "component_index": 2})
    again = pickle.loads(pickle.dumps(exc))
    assert again.detail == {"rule": "dot_component", "component_index": 2} and str(again) == "refused"
    assert str(StreamNotFoundError("no stream named 'x'")) == "no stream named 'x'"


def test_unknown_stream_is_a_stream_not_found_key_error():
    with open_document(O02) as doc:
        with pytest.raises(StreamNotFoundError) as info:
            doc.read_stream("No/Such/Stream")
        assert isinstance(info.value, KeyError)
        assert info.value.detail == {"stream": "No/Such/Stream"}
        assert "No/Such/Stream" not in doc.container  # membership still answers False
        assert model.error_info(info.value)["code"] == "stream_not_found"


# --------------------------------------------------------------------------- files that cannot be opened
def test_missing_file_and_folder(tmp_path):
    with pytest.raises(FileNotFoundError):
        open_document(tmp_path / "nope.SLDPRT")
    with pytest.raises(IsADirectoryError):  # Windows answers "access denied" for a folder; still mapped
        open_document(tmp_path)
    assert model.error_code(IsADirectoryError()) == "not_found"


def test_a_device_is_refused_before_anything_is_read(capsys):
    """Only regular files are read. The null device stands in for a FIFO, which cannot
    be made on Windows: before the check it opened and read as an empty file."""
    with pytest.raises(PathRefusedError) as info:
        open_document(os.devnull)
    assert info.value.detail == {"rule": "not_regular_file"}
    assert model.error_code(info.value) == "path_refused"
    with pytest.raises(PathRefusedError):
        _io._open_readonly_posix(os.devnull)  # the Linux and macOS path, on every OS
    with open_document(O02) as doc:  # control: a regular file still opens
        assert doc.doc_type == "part"
    assert cli.main(["info", os.devnull, "--json"]) == cli.EXIT_REFUSED
    assert '"code": "path_refused"' in capsys.readouterr().out


def _folder_link(target, link) -> None:
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))  # no extra rights needed
    else:
        os.symlink(target, link, target_is_directory=True)


def test_opening_within_a_folder_never_crosses_a_link_below_it(tmp_path):
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    shutil.copyfile(O02, root / "sub" / "part.SLDPRT")
    outside = tmp_path / "outside"
    outside.mkdir()
    shutil.copyfile(O06, outside / "part.SLDPRT")
    with _io.open_readonly(str(root / "sub" / "part.SLDPRT"), within=str(root)) as fh:
        assert fh.read(64) == O02.read_bytes()[:64]
    with open_document(root / "sub" / "part.SLDPRT", within=root) as doc:
        assert doc.file_info.size == O02.stat().st_size
    _folder_link(outside, root / "jn")
    try:
        with open_document(root / "jn" / "part.SLDPRT") as doc:  # control: without within it leads out
            assert doc.file_info.size == O06.stat().st_size
        with pytest.raises(LinkRefusedError) as info:
            open_document(root / "jn" / "part.SLDPRT", within=root)
        assert info.value.detail == {"rule": "link_in_path"}
        assert model.error_code(info.value) == "link_refused"
        try:
            os.symlink(outside / "part.SLDPRT", root / "sub" / "ln.SLDPRT")
        except OSError:
            pass  # file symbolic links need extra rights on Windows
        else:
            with pytest.raises(LinkRefusedError):
                _io.open_readonly(str(root / "sub" / "ln.SLDPRT"), within=str(root))
    finally:
        if sys.platform == "win32":
            os.rmdir(root / "jn")
        else:
            os.unlink(root / "jn")
    with pytest.raises(PathRefusedError) as info:
        _io.open_readonly(str(O02), within=str(root))
    assert info.value.detail == {"rule": "escapes_root"}
    for missing in (root / "sub" / "nope.SLDPRT", root / "nope" / "part.SLDPRT"):
        with pytest.raises(FileNotFoundError):
            _io.open_readonly(str(missing), within=str(root))
    with pytest.raises(InvalidArgumentError):
        open_document(O02.read_bytes(), within=root)



def test_a_hard_link_is_refused_before_any_byte_is_read(tmp_path, monkeypatch):
    a = tmp_path / "a.SLDPRT"
    shutil.copyfile(O02, a)
    try:
        os.link(a, tmp_path / "b.SLDPRT")
    except OSError:
        pytest.skip("hard links are not supported here")
    with open_document(tmp_path / "b.SLDPRT") as doc:  # control: only the option refuses it
        assert doc.doc_type == "part"

    def no_read(*args, **kwargs):
        raise AssertionError("a byte was read")

    monkeypatch.setattr(container_mod, "pread", no_read)
    for name in ("a.SLDPRT", "b.SLDPRT"):  # both names of the file
        for hold_open in (False, True):
            with pytest.raises(LinkRefusedError) as info:
                open_document(tmp_path / name, refuse_hard_links=True, hold_open=hold_open)
            assert info.value.detail == {"rule": "hard_link"}
            assert model.error_code(info.value) == "link_refused"
    monkeypatch.undo()
    os.unlink(tmp_path / "b.SLDPRT")
    with open_document(a, refuse_hard_links=True) as doc:  # one name again: read as usual
        assert doc.doc_type == "part"


def _deny_open(monkeypatch):
    def denied(path, flags, *args, **kwargs):
        raise PermissionError(13, "Permission denied", path)

    monkeypatch.setattr(_io, "_os_open", denied)


def test_posix_permission_error_is_not_a_lock(monkeypatch):
    # The POSIX open path, exercised on every OS. 0.1 turned this into LockedFileError.
    _deny_open(monkeypatch)
    with pytest.raises(PermissionError) as info:
        _io._open_readonly_posix(str(O02))
    assert not isinstance(info.value, LockedFileError)


def test_posix_permission_error_through_open_document(monkeypatch):
    _deny_open(monkeypatch)
    monkeypatch.setattr(container_mod, "open_readonly", _io._open_readonly_posix)
    with pytest.raises(PermissionError) as info:
        open_document(O02)
    assert not isinstance(info.value, LockedFileError)
    err = model.error_info(info.value)
    assert (err["code"], err["retryable"], err["exception"]) == (
        "permission_denied",
        False,
        "PermissionError",
    )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes; Windows denies access through ACLs")
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root reads files whatever the mode")
def test_unreadable_file_on_posix_is_permission_denied(tmp_path):
    src = tmp_path / "part.SLDPRT"
    shutil.copyfile(O02, src)
    src.chmod(0)
    try:
        with pytest.raises(PermissionError) as info:
            open_document(src)
        assert not isinstance(info.value, LockedFileError)
        assert model.error_code(info.value) == "permission_denied"
    finally:
        src.chmod(0o600)


class _ReadFails:
    def __init__(self, exc: OSError):
        self.exc = exc

    def seek(self, offset: int) -> None:
        pass

    def read(self, n: int) -> bytes:
        raise self.exc


def test_eacces_on_read_is_a_lock_only_on_windows(monkeypatch):
    denied = PermissionError(13, "Permission denied")
    monkeypatch.setattr(_io, "_EACCES_ON_READ_IS_A_LOCK", False)
    with pytest.raises(PermissionError) as info:
        _io.pread(_ReadFails(denied), 0, 8)
    assert not isinstance(info.value, LockedFileError)
    monkeypatch.setattr(_io, "_EACCES_ON_READ_IS_A_LOCK", True)
    with pytest.raises(LockedFileError):
        _io.pread(_ReadFails(denied), 0, 8)
    violation = OSError(13, "lock violation")
    violation.winerror = 33
    monkeypatch.setattr(_io, "_EACCES_ON_READ_IS_A_LOCK", False)
    with pytest.raises(LockedFileError):  # a Windows lock violation is a lock everywhere it appears
        _io.pread(_ReadFails(violation), 0, 8)


# --------------------------------------------------------------------------- hostile input
def _exercise(doc) -> dict:
    """Everything a listing, a summary or a path report does with a document, encoded
    strictly."""
    data = doc.summary()
    doc.references()
    model.dumps(model.envelope("document_summary", data))
    model.dumps(model.envelope("path_report", model.build_path_report(doc)))
    return data


def test_damaged_files_raise_only_library_errors():
    """Whole-file damage: truncation and random byte flips anywhere in the file.
    Opening and summarising may fail, but only with a SolidSeasError."""
    original = O06.read_bytes()
    rng = random.Random(20261001)
    cases = [original[:n] for n in sorted(rng.sample(range(len(original)), 60))]
    for _ in range(60):
        b = bytearray(original)
        for _k in range(rng.randint(1, 6)):
            b[rng.randrange(len(b))] = rng.randrange(256)
        cases.append(bytes(b))
    outcomes = {"ok": 0, "error": 0}
    for data in cases:
        try:
            with open_document(data) as doc:
                _exercise(doc)
            outcomes["ok"] += 1
        except SolidSeasError:
            outcomes["error"] += 1
    assert outcomes["ok"] + outcomes["error"] == len(cases) == 120
    assert outcomes["ok"] > 0 and outcomes["error"] > 0, outcomes


METADATA_STREAMS = (
    "Contents/Definition",
    "Contents/CusProps",
    "Header2",
    "_MO_VERSION_17000/History",
    "docProps/core.xml",
    "docProps/app.xml",
    "docProps/custom.xml",
    "docProps/Config-1-Properties.xml",
    "docProps/ISolidWorksInformation.xml",
    "swXmlContents/KeyWords",
    "swXmlContents/Features",
    "swXmlContents/MATERIALTREE",
    "PreviewPNG",
    "Preview",
)


def test_damaged_metadata_never_stops_the_summary():
    """Damage inside a structurally sound container: every metadata carrier, mutated,
    truncated or replaced with garbage, becomes a warning, never an exception."""
    streams = fixture_streams(O06)
    rng = random.Random(1001)
    seen_codes: set[str] = set()
    cases = 0
    for name in METADATA_STREAMS:
        original = streams[name]
        variants = [original[: len(original) // 2], bytes(rng.randrange(256) for _ in range(64)), b""]
        for _ in range(3):
            b = bytearray(original)
            for _k in range(rng.randint(1, 8)):
                b[rng.randrange(len(b))] = rng.randrange(256)
            variants.append(bytes(b))
        for v in variants:
            with open_document(rebuild(O06, {name: v})) as doc:
                data = _exercise(doc)
                for w in doc.warnings:
                    assert isinstance(w, ReaderWarning) and w.code in WARNING_CODES, repr(w)
            seen_codes.update(w["code"] for w in data["warnings"])
            cases += 1
    assert cases == len(METADATA_STREAMS) * 6
    # the sweep reached the warning paths, not only the happy one
    assert {"xml_parse_error", "version_history_unreadable"} <= seen_codes, seen_codes


def test_undecodable_previews_are_a_warning_in_the_summary():
    garbage = {"PreviewPNG": b"not an image" * 8, "Preview": bytes(80)}
    with open_document(rebuild(O06, garbage)) as doc:
        with pytest.raises(SldFormatError):
            doc.preview()
        summary = _exercise(doc)
    assert summary["preview"]["available"] is False and summary["preview"]["reason"] == "undecodable"
    assert [w["code"] for w in summary["warnings"]] == ["preview_undecodable"]


def _digits(n: int) -> str:
    return "9" * n


def test_numbers_too_long_for_int_never_escape():
    """Python refuses int() on more than 4,300 digits with ValueError. Crafted stream
    names, attributes and property values carrying such numbers stay data."""
    streams = fixture_streams(O06)
    history = streams.pop("_MO_VERSION_17000/History")
    long = _digits(5000)
    kw = streams["swXmlContents/KeyWords"].replace(
        b'Configuration id="1"', f'Configuration id="{long}"'.encode()
    )
    custom = streams["docProps/custom.xml"].replace(b'TypeID="3"', f'TypeID="{long}"'.encode())
    custom = custom.replace(b"<vt:i4>42</vt:i4>", f"<vt:i4>{long}</vt:i4>".encode(), 1)
    changes = {
        f"_MO_VERSION_{long}/History": history,
        f"Config-{long}-PreviewPNG": streams["PreviewPNG"],
        f"docProps/Config-{long}-Properties.xml": streams["docProps/Config-1-Properties.xml"],
        "swXmlContents/KeyWords": kw,
        "docProps/custom.xml": custom,
    }
    data = rebuild(O06, changes, drop=("_MO_VERSION_17000/History",))
    with open_document(data) as doc:
        summary = _exercise(doc)
        qty = next(p for p in doc.properties if p.name == "Qty")
    assert qty.value is None and qty.text == long  # unparseable as an integer: None, text kept
    # the over-long prefix is ignored: Biography still names 17000, whose History is now missing
    assert summary["saved_version"]["format_version"] == 17000
    codes = {w["code"] for w in summary["warnings"]}
    assert {"version_history_missing", "property_value_unreadable"} <= codes, codes


def test_huge_and_unicode_digit_attributes_stay_data():
    streams = fixture_streams(O06)
    huge = b"99999999999999999999"  # beyond 2**53: JSON cannot carry it exactly
    features = streams["swXmlContents/Features"].replace(
        b'swName="OracleAlt" swID="1"', b'swName="OracleAlt" swID="' + huge + b'"'
    )
    kw = streams["swXmlContents/KeyWords"].replace(
        b'Configuration id="1"', b'Configuration id="' + huge + b'"'
    )
    custom = streams["docProps/custom.xml"].replace(b'TypeID="3"', 'TypeID="\u00b2"'.encode())
    changes = {
        "swXmlContents/Features": features,
        "swXmlContents/KeyWords": kw,
        "docProps/custom.xml": custom,
    }
    with open_document(rebuild(O06, changes)) as doc:
        summary = _exercise(doc)
        assert next(p for p in doc.properties if p.name == "Qty").type_id is None  # int("\u00b2") raises
        assert doc.configuration("OracleAlt").id == int(huge)
    alt = next(c for c in summary["configurations"] if c["name"] == "OracleAlt")
    assert alt["id"] is None
    assert [w["code"] for w in summary["warnings"]] == ["value_not_representable"]


def test_xml_character_reference_to_a_surrogate_is_a_parse_warning():
    streams = fixture_streams(O06)
    custom = streams["docProps/custom.xml"].replace(
        b"ORACLE-PN-123</vt:lpstr><FPVals>", b"&#xD800;</vt:lpstr><FPVals>"
    )
    with open_document(rebuild(O06, {"docProps/custom.xml": custom})) as doc:
        summary = _exercise(doc)
    assert summary["properties"] == []
    assert [w["code"] for w in summary["warnings"]] == ["xml_parse_error"]
    assert summary["warnings"][0]["stream"] == "docProps/custom.xml"


# --------------------------------------------------------------------------- document type
def _definition_with_kind(nibble: int) -> bytes:
    d = bytearray(fixture_streams(O02)["Contents/Definition"])
    m = _GUID_RE.search(bytes(d[:256]))
    assert m is not None and d[m.start()] == 0x30  # a part: kind 0
    d[m.start()] = 0x30 + nibble
    return bytes(d)


def test_unknown_document_kind_is_none_with_a_warning():
    data = rebuild(O02, {"Contents/Definition": _definition_with_kind(5)})
    with open_document(data) as doc:
        assert doc.doc_type is None and doc.doc_type_source == "none"
        (w,) = [w for w in doc.warnings if w.code == "unknown_document_kind"]
        assert w.stream == "Contents/Definition" and "5" in w.message
        summary = doc.summary()
    assert summary["doc_type"] is None and summary["doc_type_source"] == "none"
    assert [x["code"] for x in summary["warnings"]] == ["unknown_document_kind"]
    assert "unknown(" not in model.dumps(summary)


def test_unknown_document_kind_falls_back_to_the_extension():
    data = rebuild(O02, {"Contents/Definition": _definition_with_kind(5)})
    with open_document(data, name="bracket.SLDPRT") as doc:
        assert (doc.doc_type, doc.doc_type_source) == ("part", "extension")
        assert [w.code for w in doc.warnings] == ["unknown_document_kind"]


@pytest.mark.parametrize("nibble", range(16))
def test_doc_type_is_never_any_other_string(nibble):
    with open_document(rebuild(O02, {"Contents/Definition": _definition_with_kind(nibble)})) as doc:
        assert doc.doc_type in ("part", "assembly", "drawing", None)
        assert (doc.doc_type is None) == (nibble not in (0, 4, 6))


# --------------------------------------------------------------------------- warnings
def test_reader_warning_is_a_string_with_a_code():
    w = ReaderWarning("xml_parse_error", "XML parse error: not well-formed", "docProps/app.xml")
    assert isinstance(w, str) and w == "docProps/app.xml: XML parse error: not well-formed"
    assert (w.code, w.stream, w.message) == (
        "xml_parse_error",
        "docProps/app.xml",
        "XML parse error: not well-formed",
    )
    assert w.to_dict() == {
        "code": "xml_parse_error",
        "stream": "docProps/app.xml",
        "message": "XML parse error: not well-formed",
    }
    for again in (pickle.loads(pickle.dumps(w)), copy.deepcopy(w)):
        assert (again.code, again.stream, str(again)) == (w.code, w.stream, str(w))
    hidden = ReaderWarning("property_set_error", "bad", "\x05SummaryInformation")
    assert str(hidden) == "'\\x05SummaryInformation': bad"  # a control character never reaches the text raw
    assert str(ReaderWarning("material_mismatch", "no stream")) == "no stream"


def test_every_listed_warning_code_is_emitted_somewhere():
    assert len(WARNING_CODES) >= 20
    files = [p for p in (FIXTURES.parent.parent / "src" / "solidseas").rglob("*.py") if p.name != "errors.py"]
    assert len(files) >= 20, "the source walk found too few modules"
    source = "".join(p.read_text(encoding="utf-8") for p in files)  # without the table itself
    for code in WARNING_CODES:
        assert f'"{code}"' in source, f"{code} is listed but nothing emits it"


def test_the_ghost_material_configuration_warning_keeps_its_text():
    with open_document(o05_with_ghost_configuration()) as doc:
        (w,) = doc.warnings
    assert w.code == "materialtree_unknown_configuration" and w.stream == "swXmlContents/MATERIALTREE"
    assert "Ghost" in w and "Ghost" in w.message


# --------------------------------------------------------------------------- property type tokens
@pytest.mark.parametrize("name", NATIVE)
def test_property_types_are_tokens(name):
    with open_document(fixture_path(name)) as doc:
        props = list(doc.properties) + [p for c in doc.configurations for p in c.properties]
        for p in props:
            assert p.type in PROPERTY_TYPES
            assert p.type_label in ("Text", "Number", "Yes or no", "Date", "Other")


def test_property_scope_and_configuration():
    with open_document(O06) as doc:
        assert {(p.scope, p.configuration) for p in doc.properties} == {("file", None)}
        (cfg_only,) = doc.configuration("OracleAlt").properties
    assert (cfg_only.scope, cfg_only.configuration, cfg_only.type_label) == (
        "configuration",
        "OracleAlt",
        "Text",
    )
