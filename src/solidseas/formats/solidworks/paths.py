"""Absolute file-system paths stored inside a document: the byte scan.

SOLIDWORKS writes absolute paths into several streams: the saving account's
temp folder, its Desktop or another working folder, recently used folders and
the template path in ``_MO_VERSION_<n>/Biography`` (one record per save
session, inherited from the template the document was created from), the
folder at save in ``ISolidWorksInformation``, and the absolute paths of
referenced documents in ``Header2``, ``swXmlContents/COMPINSTANCETREE``,
``SwDocContentMgr/SwDocContentMgrInfo``, ``Contents/Config-<n>-ModelHeader`` and
``Contents/DisplayLists``. Anyone who receives the file can read them.

:func:`scan_bytes` finds the absolute Windows paths (a drive letter or a UNC
prefix) in one stream's bytes, in four passes:

1. MFC Unicode CStrings (``FF FE FF``, a length, then UTF-16LE). Each one is
   decoded to its stored length, so a path ends exactly where SOLIDWORKS ended
   it and never runs on into the binary that follows. Every UTF-16 path in the
   fixtures sits in a CString, and all but 16 of about 691,000 on the
   development corpus do. A "string" holding control characters, a byte-order
   mark or unpaired surrogates is ``FF FE FF`` inside binary data, not a
   string, and is skipped, so its length never hides the real strings it would
   cover.
2. UTF-16LE text outside those CStrings, from each drive or UNC prefix to the
   first character that cannot be part of a path. Letters of any script count.
3. Counted 8-bit strings with a byte above ASCII that either are not UTF-8 or
   sit in a property set section that declares an 8-bit code page: a u32 byte
   count, the text, then a NUL (and at most three NULs of padding the count may
   include), the layout of an MS-OLEPS ``CodePageString``. Legacy documents
   keep their property sets, ``ISolidWorksInformation`` with the folder at save
   among them, this way. The string is decoded whole in the code page its property
   set section declares (cp1252 for a section that declares none), even where
   its bytes would also be valid UTF-8, as :mod:`.propset` decodes it; or in
   cp1252 outside a property set (or where the string is not valid in the
   declared code page). So a path is read past an accented or non-Latin
   character, and it ends at the NUL. Only the count and the NUL say where 8-bit
   text ends: without them 8-bit text is left to pass 4, so binary noise never
   runs into a path.
4. UTF-8 text (which includes ASCII) outside those strings, from each drive or
   UNC prefix to the first character that cannot be part of a path. XML
   streams such as the component tree hold their paths this way.

A match outside a stored string whose rest has no two letters or digits in a
row (``f:\\!`` in compressed bytes) is noise and is dropped. :mod:`.pathreport`
merges this scan with the structured carriers; :func:`find_embedded_paths` is
the 0.1 interface to the scan alone.
"""

import re
import struct
import unicodedata
from dataclasses import dataclass

from .container import Container
from .errors import SldError
from .metadata import MAX_CSTRING_CHARS, read_cstring
from .propset import codepage_codec

DEFAULT_MAX_SCAN_BYTES = 16 << 20
MAX_PATH_CHARS = 32_767  # the longest path Windows accepts

_CSTRING = re.compile(rb"\xff\xfe\xff")
_U16_ANCHOR = re.compile(rb"[A-Za-z]\x00:\x00\\\x00|\\\x00\\\x00")
# UTF-16LE units that may be text: printable ASCII and Latin-1, or any unit above 0xFF.
# The per-character check below then refuses controls, surrogates and unassigned code points.
_U16_TEXT = re.compile(rb"(?:[\x20-\x7e\xa0-\xff]\x00|[\x00-\xff][\x01-\xff])+")
_U8_ANCHOR = re.compile(rb"[A-Za-z]:\\|\\\\")
_U8_TEXT = re.compile(
    rb"(?:[\x20-\x7e]|[\xc2-\xdf][\x80-\xbf]|\xe0[\xa0-\xbf][\x80-\xbf]|[\xe1-\xec\xee\xef][\x80-\xbf]{2}"
    rb"|\xed[\x80-\x9f][\x80-\xbf]|\xf0[\x90-\xbf][\x80-\xbf]{2}|[\xf1-\xf3][\x80-\xbf]{3}"
    rb"|\xf4[\x80-\x8f][\x80-\xbf]{2})+"
)
# What _U8_ANCHOR matches but faster to find: the ":\" of "X:\" or a "\\". Letters are
# common in binary data, so a search led by them is several times slower.
_ANCHOR_HINT = re.compile(rb"[:\\]\\")
_CONTROL = re.compile(rb"[\x00-\x1f]")
_HIGH = re.compile(rb"[\x80-\xff]")
_TEXT_BYTE = bytes(0 if b < 0x20 else 1 for b in range(256))  # translate table: control 0, text 1
MAX_COUNTED_BYTES = 4 * MAX_PATH_CHARS  # a counted 8-bit string longer than this is not read
_ABS = re.compile(r"(?:[A-Za-z]:\\|\\\\[^\\\s]+\\)[^\x00-\x1f\"<>|*?]*")
_PREFIX = re.compile(r"^(?:[A-Za-z]:\\|\\\\[^\\]*\\?)")
_NOT_IN_PATH = frozenset('"<>|*?')
# What a stored string never holds: control characters other than tab and line breaks,
# surrogates, private-use and special code points, the byte-order mark and U+FFFD (what an
# unpaired surrogate decodes to). Its presence means FF FE FF was not a string's start.
_NOT_TEXT = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ue000-\uf8ff\ufeff\ufff0-\uffff]")


@dataclass(frozen=True)
class EmbeddedPath:
    stream: str
    path: str
    kind: str  # "temp", "desktop", "user-profile", "program-data", "unc" or "other"


def classify(path: str) -> str:
    """The 0.1 classifier, kept for :class:`EmbeddedPath`. :mod:`.pathreport` has the finer
    ``category``."""
    low = path.lower().replace("/", "\\")
    if (
        "\\appdata\\local\\temp" in low
        or "\\local settings\\temp" in low
        or low.rstrip("\\").endswith("\\temp")
    ):
        return "temp"
    if re.search(r"\\(users|documents and settings)\\[^\\]+\\desktop(\\|$)", low):
        return "desktop"
    if re.search(r"\\(users|documents and settings)\\[^\\]+", low):
        return "user-profile"
    if "\\programdata\\" in low or "\\program files" in low:
        return "program-data"
    if low.startswith("\\\\"):
        return "unc"
    return "other"


def _path_char(ch: str) -> bool:
    if ch in _NOT_IN_PATH:
        return False
    cat = unicodedata.category(ch)
    return cat[0] != "C" and cat not in ("Zl", "Zp")


def _cut(text: str) -> str:
    """``text`` up to the first character that cannot be part of a path."""
    for i, ch in enumerate(text):
        if (ch < " " or ch > "~") and not _path_char(ch):
            return text[:i]
    return text


def is_noise(path: str) -> bool:
    """True for a match with no name in it, such as ``f:\\!`` inside compressed bytes:
    what follows the drive or UNC prefix needs at least three characters with two
    letters or digits in a row."""
    rest = _PREFIX.sub("", path.replace("/", "\\"), count=1)
    if len(rest) < 3:
        return True
    return not any(a.isalnum() and b.isalnum() for a, b in zip(rest, rest[1:], strict=False))


def _is_text(s: str) -> bool:
    """True when ``s`` reads as a stored string: none of :data:`_NOT_TEXT` and no
    unassigned code point."""
    if _NOT_TEXT.search(s):
        return False
    return s.isascii() or all(unicodedata.category(ch) != "Cn" for ch in s if ch > "\x7f")


def _paths_in(text: str, *, cstring: bool = False) -> list[tuple[str, int]]:
    """The paths in ``text`` with their offsets. Outside a CString, where the text is cut
    from bytes that may be compressed, matches with no name in them are noise
    (:func:`is_noise`)."""
    out = []
    for m in _ABS.finditer(text):
        p = m.group().rstrip()
        if len(p) >= 4 and (cstring or not is_noise(p)):
            out.append((p, m.start()))
    return out


def _u16_len(text: str) -> int:
    return len(text.encode("utf-16-le", "surrogatepass"))


def _masked(data: bytes, spans: list[tuple[int, int]]) -> bytes:
    """``data`` with the bytes of each span set to zero, so a later pass cannot find
    them again."""
    if not spans:
        return data
    out = bytearray(data)
    for a, b in spans:
        out[a:b] = bytes(b - a)
    return bytes(out)


def _section_codecs(data: bytes) -> list[tuple[int, int, str | None]]:
    """``(start, end, codec)`` of each section of an MS-OLEPS property set stream, where
    ``codec`` is the Python codec of the code page the section declares (property 1;
    1252 when it declares none, as :mod:`.propset` reads it) and None for UTF-16 (1200).
    Empty for any other stream, and for a header that does not hold together."""
    if len(data) < 28 or data[:2] != b"\xfe\xff":
        return []
    (count,) = struct.unpack_from("<I", data, 24)
    if not 1 <= count <= 16 or 28 + 20 * count > len(data):
        return []
    out: list[tuple[int, int, str | None]] = []
    for i in range(count):
        (off,) = struct.unpack_from("<I", data, 44 + 20 * i)
        if off + 8 > len(data):
            return []
        size, nprop = struct.unpack_from("<II", data, off)
        end = min(len(data), off + size)
        if nprop > 100_000 or off + 8 + 8 * nprop > end:
            return []
        cp = 1252
        for k in range(nprop):
            pid, po = struct.unpack_from("<II", data, off + 8 + 8 * k)
            if pid == 1 and off + po + 6 <= end:
                cp = struct.unpack_from("<H", data, off + po + 4)[0]
                break
        codec = codepage_codec(cp)
        out.append((off, end, None if codec == "utf-16-le" else codec))
    return out


def _counted_start(view: bytes, p: int, e: int, floor: int) -> int | None:
    """The first byte of the counted 8-bit string that holds ``view[p:e]`` and ends with
    the NUL at ``e``, or None. Its count is a u32 under 16 MiB, whose top byte is zero, so
    the string starts right after the last control byte before ``p``; the count before
    it must cover the text and the NUL, plus at most three NULs of padding. ``floor`` is
    a control byte already known to lie before ``p`` (or 0), so the search for the last
    one never reads the same bytes twice."""
    lo = max(floor, e - MAX_COUNTED_BYTES)
    i = view[lo:p].translate(_TEXT_BYTE).rfind(b"\x00")
    if i < 0:
        return None  # longer than a counted string is read, or no room for a count
    s = lo + i + 1
    if s < 4:
        return None
    (n,) = struct.unpack_from("<I", view, s - 4)
    if e - s < n <= e - s + 4 and view[e : s + n] == bytes(s + n - e):
        return s
    return None


def _decode_counted(raw: bytes, codec: str | None) -> str | None:
    """A counted 8-bit string as text: in ``codec`` when its section declares an 8-bit
    code page, else (or when that code page cannot decode it) in cp1252. None when the
    string is valid UTF-8 and nothing declares another code page, since pass 4 reads it
    the same way, and when no code page decodes it."""
    if codec in (None, "utf-8"):
        try:
            raw.decode("utf-8")
            return None
        except UnicodeDecodeError:
            pass
    for name in dict.fromkeys((codec or "cp1252", "cp1252")):
        if name == "utf-8":
            continue
        try:
            return raw.decode(name)
        except UnicodeDecodeError:
            continue
    return None


def _counted_paths(view: bytes, sections: list[tuple[int, int, str | None]]):
    """Pass 3: ``(paths, spans)`` from the counted 8-bit strings in ``view`` with a byte
    above ASCII that are not UTF-8, or whose section declares an 8-bit code page. Each
    anchor's string ends at its first control byte, and every anchor before that byte
    shares the string, so each run of text is looked at once."""
    paths: list[tuple[str, str]] = []
    spans: list[tuple[int, int]] = []
    done = last_end = 0  # last_end: the previous string's end, a control byte (or 0)
    while (m := _ANCHOR_HINT.search(view, done)) is not None:
        q = m.start()
        p = q - 1 if view[q] == 0x3A else q  # X:\ starts at its drive letter
        if p < done or (p < q and not 0x61 <= (view[p] | 0x20) <= 0x7A):
            done = q + 1
            continue
        c = _CONTROL.search(view, p)
        if c is None:
            break  # no string from here on ends with a NUL
        floor, last_end = last_end, c.start()
        e = done = c.start()
        if view[e] != 0 or _HIGH.search(view, p, e) is None:
            continue  # not NUL-terminated, or ASCII: pass 4 reads it the same way
        s = _counted_start(view, p, e, floor)
        if s is None:
            continue
        declared = next((codec for a, b, codec in sections if a <= s < b), None)
        text = _decode_counted(view[s:e], declared)
        if text is None or not _is_text(text):
            continue
        found = _paths_in(text, cstring=True)
        if found:
            spans.append((s, e))
            paths += [(path, "ansi") for path, _at in found]
    return paths, spans


def scan_bytes(data: bytes) -> list[tuple[str, str]]:
    """Every absolute path in ``data`` as ``(path, encoding)``, ``encoding`` being
    ``"cstring"``, ``"utf16"``, ``"ansi"`` (a counted 8-bit string read in a code page)
    or ``"utf8"``, in the order of the four passes and then by offset. A path found
    twice in different places is listed twice."""
    found: list[tuple[str, str]] = []
    spans: list[tuple[int, int]] = []
    done = 0
    for m in _CSTRING.finditer(data):
        if m.start() < done:
            continue
        s, end = read_cstring(data, m.start(), MAX_CSTRING_CHARS)
        if s is None or not _is_text(s):
            # FF FE FF inside binary data: its "length" can run over real strings, which
            # must still be read from their own markers
            continue
        paths = _paths_in(s, cstring=True)
        if not paths:
            continue
        done = end
        base = end - _u16_len(s)
        for p, at in paths:
            # Only the path's own bytes are hidden from the other passes, so that they
            # cannot find it again with a tail. FF FE FF in binary data can look like a
            # CString whose length covers text in another encoding, which stays visible.
            a = base + _u16_len(s[:at])
            spans.append((a, a + _u16_len(p)))
            found.append((p, "cstring"))
    view = _masked(data, spans)
    done = 0
    for m in _U16_ANCHOR.finditer(view):
        p = m.start()
        if p < done:
            continue
        t = _U16_TEXT.match(view, p, min(len(view), p + 2 * MAX_PATH_CHARS))
        if t is None:
            continue
        text = _cut(t.group().decode("utf-16-le", "surrogatepass"))
        done = p + len(text.encode("utf-16-le", "surrogatepass"))
        found += [(q, "utf16") for q, _at in _paths_in(text)]
    counted, counted_spans = _counted_paths(view, _section_codecs(data))
    found += counted
    # the whole counted string is hidden from pass 4, which would read it cut short
    view = _masked(view, counted_spans)
    done = 0
    for m in _U8_ANCHOR.finditer(view):
        p = m.start()
        if p < done:
            continue
        t = _U8_TEXT.match(view, p, min(len(view), p + 4 * MAX_PATH_CHARS))
        if t is None:
            continue
        text = _cut(t.group().decode("utf-8"))
        done = p + len(text.encode("utf-8"))
        found += [(q, "utf8") for q, _at in _paths_in(text)]
    return found


def find_embedded_paths(
    container: Container, *, max_stream_bytes: int = DEFAULT_MAX_SCAN_BYTES
) -> tuple[list[EmbeddedPath], list[str]]:
    """``(paths, skipped_streams)``: every distinct (stream, path) pair the byte scan
    finds in this container's own streams, and the streams that were too large to scan
    or could not be read. Nested documents are scanned as stored bytes, not opened:
    ``Document.path_report()`` opens them and adds the structured carriers."""
    found: list[EmbeddedPath] = []
    seen: set[tuple[str, str]] = set()
    skipped: list[str] = []
    for info in container.streams():
        if info.size > max_stream_bytes:
            skipped.append(info.name)
            continue
        try:
            data = container.read(info.name, max_bytes=max_stream_bytes)
        except SldError:
            skipped.append(info.name)
            continue
        for p, _enc in scan_bytes(data):
            if (info.name, p) in seen:
                continue
            seen.add((info.name, p))
            found.append(EmbeddedPath(info.name, p, classify(p)))
    return found, skipped
