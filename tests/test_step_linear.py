"""Crafted STEP text that used to cost time quadratic in its size, and the write guard
that keeps the library from writing a SOLIDWORKS file. The time bounds are loose on
purpose: the quadratic versions took minutes on these inputs, the linear ones well under
a second."""

import time

import pytest

from solidseas.errors import OutputRefusedError
from solidseas.export import write_new
from solidseas.formats import Limits
from solidseas.formats._source import Source
from solidseas.formats.step.part21 import decode_string
from solidseas.formats.step.schema import census


def test_escapes_still_decode():
    assert decode_string(b"caf\\X2\\00E9\\X0\\") == "café"
    assert decode_string(b"\\X4\\0001F600\\X0\\") == "\U0001f600"
    assert decode_string(b"\\X2\\00e9\\X0\\") == "é"  # lower-case hex is accepted


@pytest.mark.parametrize(
    ("raw", "kept"),
    [
        (b"a\\X2\\00E9", "a\\X2\\00E9"),  # never closed
        (b"\\X2\\00E\\X0\\", "\\X2\\00E\\X0\\"),  # not a whole code unit
        (b"\\X2\\00G9\\X0\\", "\\X2\\00G9\\X0\\"),  # not hex
    ],
)
def test_an_invalid_escape_is_kept_as_stored(raw, kept):
    assert decode_string(raw) == kept


def test_many_unclosed_escapes_decode_in_linear_time():
    raw = b"\\X2\\A" * 200_000  # 1 MB of escapes, none closed
    started = time.monotonic()
    assert decode_string(raw) == "\\X2\\A" * 200_000
    assert time.monotonic() - started < 10


def test_a_record_full_of_unit_words_is_read_once():
    record = b"#1=FOO(" + b"SI_UNIT " * 500_000 + b");\n"  # 4 MB, one record
    text = b"#2=SI_UNIT(.MILLI.,.METRE.);\n" + record
    started = time.monotonic()
    out = census(Source(text), 0, Limits())
    assert time.monotonic() - started < 10
    assert out.complete


def test_the_library_never_writes_a_solidworks_file(tmp_path):
    source = tmp_path / "part.SLDPRT"
    source.write_bytes(b"original")
    for name in ("part.SLDPRT", "new.sldasm", "tmpl.prtdot"):
        with pytest.raises(OutputRefusedError) as caught:
            write_new(tmp_path / name, lambda fh: fh.write(b"x"), overwrite=True)
        assert caught.value.detail == {"rule": "solidworks_file"}
    assert source.read_bytes() == b"original"
    assert not (tmp_path / "new.sldasm").exists()
