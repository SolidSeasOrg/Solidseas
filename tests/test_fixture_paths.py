"""Pins every path, user name and identity string the committed fixtures carry.

SOLIDWORKS writes the saving account's Temp and Desktop folders into every
document, and a document inherits the folder history of the template it was
made from (``docs/FORMAT.md`` section 13). The fixtures were made by the fixture
kit in a development account (``tests/fixtures/README.md``), so they may carry:

* the generating account's name, its bare Temp and Desktop folders, and
  SOLIDWORKS' scratch folders inside that Temp folder, named after a committed
  assembly;
* the kit's output folder under the shared Public profile, and the committed
  file names inside it;
* a short list of exact SOLIDWORKS and Windows paths (the installation's
  templates, materials and BOM template, the part and MBD assembly templates in
  ProgramData, the Windows system folder) and the folders above them;
* in documents made from the two Dassault-shipped templates the kit used, the
  build and test folders and the user names of the Dassault accounts that
  authored those templates.

Anything else fails here:

* **Paths.** Every stream of every document is read, nested documents
  included, as UTF-8 and as UTF-16LE at both byte alignments, and so is every
  string of the kit's JSON record. A path runs over every character a Windows
  file name may hold, whatever its script, and stops only at a character no
  file name holds (a control, format, private-use or unassigned code point, or
  one of ``"*:<>?|``) or where an MFC CString's stored length ends. ``%TEMP%``
  style variables and a leading ``~`` are expanded to the generating account's
  folders and ``..`` is resolved before the rules apply. Another user profile, a
  Desktop subfolder, any other folder of the account, a network path in any
  form, a URL whose host is not on the reviewed list, or a path outside the
  reviewed lists fails.
* **Identity strings.** An e-mail address, an IPv4 address, a host name in the
  Windows default forms, or this machine's own host name, anywhere.
* **Stored user names.** The ``su_CStringArray`` user lists of ``Header2`` and
  ``Config-<n>-ModelHeader`` (read by this module's own parser, not the library),
  core.xml authors and ``SW-Author`` / ``SW-Last Saved By`` must be the
  generating account or a template author.
* **Summary fields.** Title, subject, keywords, comments, category, company and
  manager must be empty (SOLIDWORKS' own vendor in ``app.xml`` excepted).
* **Names in Header2 and ModelHeader.** Every other string there must be a name
  SOLIDWORKS reported for a fixture (``ground_truth.json``), a committed file
  name, a default document name such as ``Part1^Assem1``, or one of SOLIDWORKS'
  own folder names: a template saved inside a project would show up as
  ``Part1^<project>``.
* **Exports.** The Parasolid header's ``USER``, ``SITE`` and ``MC_ID``, the STEP
  author and organisation, and the 3MF metadata must be empty or placeholders.
* **Corpus names**, when ``SOLIDSEAS_CORPUS_MANIFEST`` names the private corpus
  manifest: no file or folder name from it may occur in any fixture.

Plain text outside these places (a feature name, a property value) is reviewed
when the fixtures are regenerated, not enforced here. The planted tests at the
end prove that each rule finds what it is meant to find.
"""

import csv
import functools
import json
import os
import re
import shutil
import socket
import struct
import unicodedata
import zipfile
from pathlib import Path

import pytest

from builders import build_modern, fixture_streams, rebuild
from solidseas import open_document
from solidseas.formats.solidworks import open_container
from support import FIXTURES, ground_truth

GROUND_TRUTH = ground_truth()
GENERATION = GROUND_TRUTH["_generation"]
# The generating account is read from the kit's record, never written down here.
ACCOUNT = GENERATION["profile_folder_name"]
ACCOUNTS = {
    GENERATION[k].casefold() for k in ("profile_folder_name", "profile_folder_short_name", "windows_account")
}
HOME = "C:\\Users\\" + ACCOUNT
OUTPUT_FOLDER = ("documents", "solidseasfixtures", "current-account", "out")

NATIVE = {".SLDPRT", ".SLDASM", ".SLDDRW"}
NO_PATHS = {".x_t", ".x_b", ".step", ".stl", ".3mf"}
RECORDS = {"generation.log", "scrub_report.txt", "ground_truth.json"}

# ground_truth.private.json is the private overlay (support.ground_truth) that lists, by
# design, the names this scan keeps out of everything else.
COMMITTED = sorted(
    p for p in FIXTURES.iterdir() if p.is_file() and p.name not in ("README.md", "ground_truth.private.json")
)
# Documents and exports the kit wrote to its output folder, and the assemblies whose
# virtual parts SOLIDWORKS keeps in its scratch folder.
OUTPUT_FILES = {
    p.name.casefold() for p in COMMITTED if p.suffix.upper() in NATIVE or p.suffix.lower() in NO_PATHS
}
ASSEMBLY_STEMS = sorted(p.stem.casefold() for p in COMMITTED if p.suffix.upper() == ".SLDASM")
_STEMS = "|".join(re.escape(s) for s in ASSEMBLY_STEMS)
_SCRATCH = re.compile(rf"swx\d+(\\vc~~(\\(?P<a>{_STEMS})(\\part\d+\^(?P=a)\.sldprt)?)?)?|~0x[0-9a-f]+\.tmp")

# Exact SOLIDWORKS and Windows paths any fixture may name, lower case. A path is allowed
# when it is one of these or a folder above one.
INSTALL_PATHS = {
    "c:\\program files\\solidworks corp\\solidworks\\data\\graphics\\materials\\color.p2m",
    "c:\\program files\\solidworks corp\\solidworks\\data\\graphics\\materials\\metal\\aluminum"
    "\\satin finish aluminum.p2m",
    "c:\\program files\\solidworks corp\\solidworks\\data\\templates\\ansi.drwdot",
    "c:\\program files\\solidworks corp\\solidworks\\lang\\english\\bom-standard.sldbomtbt",
    "c:\\programdata\\solidworks\\solidworks 2024\\templates\\part.prtdot",
    "c:\\programdata\\solidworks\\solidworks 2024\\templates\\mbd\\assembly 0250mm and smaller.asmdot",
    "c:\\windows\\system32",
}
# The kit's records also name the account's default drawing template, which it did not use.
RECORD_PATHS = {"c:\\programdata\\solidworks\\solidworks 2024\\templates\\drawing.drwdot"}
# Annotations the kit's text records write right after a path.
RECORD_NOTES = (
    " (Dassault-shipped)",
    " (the default part template, made in this account)",
    " (the default part template, checked before the run)",
    " (both put in place by the SOLIDWORKS installer)",
    " -",
    ";",
)
# Hosts of the XML namespaces in documents and 3MF packages, and the price link of the
# SOLIDWORKS material database.
URL_HOSTS = {
    "purl.org",
    "schemas.microsoft.com",
    "schemas.openxmlformats.org",
    "www.metalprices.com",
    "www.solidworks.com",
    "www.w3.org",
}


class Family:
    """What documents made from one shipped template inherit from its history."""

    def __init__(self, roots=(), paths=(), profiles=(), users=()):
        self.roots = set(roots)  # drive and first two folders of Dassault's build machines
        self.paths = set(paths)  # exact install paths on Dassault's machines
        self.profiles = set(profiles)  # profile folders of the template authors
        self.users = set(users)  # user names the template stores

    def __or__(self, other):
        return Family(
            self.roots | other.roots,
            self.paths | other.paths,
            self.profiles | other.profiles,
            self.users | other.users,
        )


# The account names of the Dassault employees who authored the shipped templates, which
# the documents made from them carry: kept with the private fixtures, in
# ground_truth.private.json, so this public file names nobody.
TEMPLATE_ACCOUNTS = GROUND_TRUTH.get("_template_accounts", {})
MBD_AUTHOR = sorted(TEMPLATE_ACCOUNTS.get("mbd", {}).get("profiles", ["?"]))[0]
DRAWING_ONLY_AUTHOR = sorted(
    set(TEMPLATE_ACCOUNTS.get("ansi", {}).get("users", ["?"]))
    - set(TEMPLATE_ACCOUNTS.get("mbd", {}).get("users", ()))
)[0]

# Build and test folders of Dassault's own machines, inherited from the shipped
# templates' Biography records. Reviewed by hand: sample-file conversions,
# baseline builds and toolbox data, nothing of this project.
BOTH_TEMPLATES_ROOTS = {
    "e:\\am3sub\\sldworks",
    "e:\\dj\\may2021",
    "e:\\pr1_samplefiles\\sldworks",
    "e:\\sw2023_pr1_samplefiles\\sldworks",
    "f:\\2020_pr1_samplefiles\\converted",
    "f:\\2020_sp0_samplefiles\\converted",
    "f:\\samplefiles\\2024_pr1_converted",
    "f:\\samplefiles\\2024_sp0_converted",
    "f:\\sw2023_sp0_samplefiles_converted\\sldworks",
    "n:\\am\\samples",
    "q:\\am\\api",
    "z:\\am2sub\\sldworks",
    "z:\\am\\samples",
}
MBD = Family(
    roots=BOTH_TEMPLATES_ROOTS
    | {
        "e:\\2018_b1_samplefiles_reloaded_1\\sldrx",
        "e:\\2018_b1_samplefiles_reloaded_1\\sldworks",
    },
    paths={
        "c:\\programdata\\solidworks\\solidworks 2017\\templates\\assembly 0250mm and smaller.asmdot",
        "c:\\programdata\\solidworks\\solidworks 2017\\templates\\assembly 0250mm and smaller.sldasm",
        "c:\\programdata\\solidworks\\solidworks 2017\\templates\\assembly 250mm and smaller.sldasm",
        "c:\\programdata\\solidworks\\solidworks 2017\\templates\\assembly.asmdot",
        "c:\\programdata\\solidworks\\solidworks 2017\\templates\\mbd\\assembly 0250mm and smaller.asmdot",
        "c:\\program files\\solidworks corp\\solidworks (2)",
    },
    profiles=set(TEMPLATE_ACCOUNTS.get("mbd", {}).get("profiles", ())),
    users=set(TEMPLATE_ACCOUNTS.get("mbd", {}).get("users", ())),
)
ANSI = Family(
    roots=BOTH_TEMPLATES_ROOTS
    | {
        "c:\\2013conv\\sldworks",
        "c:\\2013convoutput\\2013conv",
        "c:\\am2sub\\api",
        "c:\\am2sub\\sldworks",
        "c:\\dev\\am2sub",
        "c:\\solidworks data\\browser",
        "c:\\temp\\baseline",
        "c:\\temp\\converted",
        "d:\\baseline\\api",
        "d:\\baseline\\sldworks",
        "d:\\converted\\baseline",
        "e:\\am2sub\\samples",
        "e:\\am2sub\\sldworks",
        "e:\\am2sub\\thirdpty",
        "e:\\baseline\\sldworks",
        "e:\\converted\\api",
        "e:\\converted\\baseline",
        "e:\\converted\\sldworks",
        "e:\\converted\\solidworks",
        "e:\\pr1_sample_conversion\\sldworks",
        "e:\\solidworks\\2014",
        "e:\\sw2016_b1_converted\\sldworks",
        "f:\\baseline\\samples",
        "f:\\baseline\\sldworks",
        "f:\\converted\\baseline",
        "h:\\baseline\\sldworks",
        "h:\\converted\\baseline",
        "i:\\baseline\\sldworks",
        "i:\\converted\\baseline",
        "v:\\am2sub\\sldworks",
        "z:\\am2sub fixed 2 electric boogaloo\\sldworks",
        "z:\\faucet_broken",
    }
    | set(TEMPLATE_ACCOUNTS.get("ansi", {}).get("roots", ())),
    paths={
        "c:\\program files\\solidautoinstaller\\simulationsmoke\\parts",
        "c:\\program files\\solidworks 2009",
    },
    # Profile folders, with the Windows 8.3 short forms the template stores, All Users,
    # and the short form of a Windows temporary profile folder on one of Dassault's
    # machines; the template authors' account names are kept with the private fixtures.
    profiles=set(TEMPLATE_ACCOUNTS.get("ansi", {}).get("profiles", ())),
    users=set(TEMPLATE_ACCOUNTS.get("ansi", {}).get("users", ())),
)
NONE = Family()
FROM_TEMPLATE = {
    "o08_asm_2x_boxA.SLDASM": MBD,
    "o15_sub_asm.SLDASM": MBD,
    "o16_asm_features.SLDASM": MBD,
    "o18_drw_boxA.SLDDRW": ANSI,
    "o19_drw_asm.SLDDRW": ANSI,
    # The kit's scrub report quotes what the documents carry.
    "scrub_report.txt": MBD | ANSI,
}


# --------------------------------------------------------------------------- extraction
def _views(blob: bytes):
    yield blob.decode("utf-8", "replace")
    yield blob.decode("utf-16-le", "replace")
    yield blob[1:].decode("utf-16-le", "replace")


def _container_blobs(container, label: str):
    with container as c:
        for name in c.names():
            yield f"{label}:{name}", c.read(name)
            if c.is_nested_document(name):
                yield from _container_blobs(c.open_nested(name), f"{label}:{name}")


@functools.lru_cache(maxsize=4)
def _read_blobs(path: Path, _size: int, _mtime_ns: int) -> tuple[tuple[str, bytes], ...]:
    out = [(path.name, path.read_bytes())]
    if path.suffix.upper() in NATIVE:
        out += _container_blobs(open_container(path), path.name)
    elif path.suffix.lower() == ".3mf":
        with zipfile.ZipFile(path) as z:
            out += [(f"{path.name}:{name}", z.read(name)) for name in z.namelist()]
    return tuple(out)


def _blobs(path: Path) -> tuple[tuple[str, bytes], ...]:
    """(where, bytes) for the file itself and every stream in it, nested documents included."""
    st = path.stat()
    return _read_blobs(path, st.st_size, st.st_mtime_ns)


def _json_strings(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from _json_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _json_strings(v)
    elif isinstance(value, str):
        yield value


def texts(path: Path):
    """(where, text, plain) for every view of a fixture file. ``plain`` marks text that is
    text throughout (a JSON string, a text record, an XML stream) rather than a view of
    binary data."""
    if path.suffix.lower() == ".json":
        for s in _json_strings(json.loads(path.read_text(encoding="utf-8"))):
            yield path.name, s, True
        return
    for where, blob in _blobs(path):
        views = _views(blob)
        utf8 = next(views)
        yield where, utf8, b"\0" not in blob and "\ufffd" not in utf8
        for view in views:
            yield where, view, False


# --------------------------------------------------------------------------- paths
_START = re.compile(
    r"(?=[A-Za-z\\/%~])"  # (a quick first test)
    r"(?:(?P<unc>\\\\[?.]\\UNC\\)"  # a long-form network path
    r"|(?P<drive>[A-Za-z]:[\\/])"  # a drive letter
    r"|(?P<net>(?<![\\/:])(?:\\\\|//)(?=[A-Za-z0-9]))"  # a network path, either slash
    r"|(?P<posix>/(?:Users|home)/)"  # a macOS or Linux home folder
    r"|(?P<var>%[A-Za-z_][A-Za-z0-9_]*%[\\/])"  # an environment variable
    r"|(?P<tilde>(?<![\w~.$-])~[\\/]))",  # a home folder (plain text only)
    re.I,
)
_URL = re.compile(r"\b([A-Za-z][A-Za-z0-9+.-]*)://([^/\\\s\"'<>?#]*)[^\s\"'<>]*")
_VAR = re.compile(r"%([A-Za-z_][A-Za-z0-9_]*)%")
_VARIABLES = {
    "temp": HOME + "\\AppData\\Local\\Temp",
    "tmp": HOME + "\\AppData\\Local\\Temp",
    "userprofile": HOME,
    "homepath": HOME,
    "localappdata": HOME + "\\AppData\\Local",
    "appdata": HOME + "\\AppData\\Roaming",
    "username": ACCOUNT,
    "public": "C:\\Users\\Public",
    "programdata": "C:\\ProgramData",
    "allusersprofile": "C:\\ProgramData",
    "programfiles": "C:\\Program Files",
    "systemroot": "C:\\Windows",
    "windir": "C:\\Windows",
}
_NOT_IN_NAMES = frozenset('"*:<>?|\ufffd')
_NAME = re.compile(r"[A-Za-z0-9$][A-Za-z0-9 ._$~&'()-]+")
_VIEW_SUFFIX = re.compile(r"@Drawing View\d+@Sheet\d+$")


def _in_name(ch: str) -> bool:
    """Whether a Windows file name can hold ``ch``: anything but the reserved characters
    and control, format, surrogate, private-use and unassigned code points."""
    return ch not in _NOT_IN_NAMES and unicodedata.category(ch)[0] != "C"


def _cstring_end(text: str, start: int) -> int | None:
    """Where a path ends when a UTF-16 MFC CString header (ff fe ff, then the length in
    one byte or, after ff, in two) sits right before it."""
    if start >= 2 and text[start - 2] == "\ufeff":
        unit = ord(text[start - 1])
        if unit & 0xFF == 0xFF and unit >> 8 != 0xFF:
            return start + (unit >> 8)
    if start >= 3 and text[start - 3] == "\ufeff" and text[start - 2] == "\uffff":
        return start + ord(text[start - 1])
    return None


def _trim(path: str, record: bool) -> str:
    while True:
        before = path
        path = _VIEW_SUFFIX.sub("", path.rstrip(" ."))
        if path.endswith(")") and path.count("(") < path.count(")"):
            path = path[:-1]
        if record:
            for note in RECORD_NOTES:
                if path.endswith(note):
                    path = path[: -len(note)]
        if path == before:
            return path


def expand(path: str) -> tuple[str, list[str]]:
    """``path`` with known environment variables and a leading ``~`` replaced by the
    generating account's folders, and the variables it does not know."""
    unknown: list[str] = []

    def sub(m):
        value = _VARIABLES.get(m.group(1).casefold())
        if value is None:
            unknown.append(m.group(0))
            return m.group(0)
        return value

    path = _VAR.sub(sub, path)
    if path == "~" or path.startswith(("~\\", "~/")):
        path = HOME + path[1:]
    return path, unknown


def _parts(path: str) -> list[str]:
    """Components of a path, with ``.`` and ``..`` resolved (never above the drive or host)."""
    p = path.replace("/", "\\")
    network = p.startswith("\\\\")
    out: list[str] = []
    for x in (p[2:] if network else p).split("\\"):
        if x in ("", "."):
            continue
        if x == "..":
            if len(out) > 1:
                out.pop()
            continue
        out.append(x)
    if network and out:
        out[0] = "\\\\" + out[0]
    return out


def _is_path(path: str) -> bool:
    """Leaves out byte noise that only starts like a path (it occurs in compressed data
    and images): a drive with no folder or with one punctuation character as its
    folder, a forward-slash drive path whose first folder is not a name, and a network
    host without a share."""
    parts = _parts(path)
    if len(parts) < 2:
        return False
    if path.startswith("/") or parts[0].startswith("\\\\"):
        return True
    if "/" in path[:3]:
        return _NAME.fullmatch(parts[1]) is not None
    return len(parts[1]) >= 2 or parts[1].isalnum()


def scan(text: str, *, record: bool = False, plain: bool = False):
    """Every path and URL in ``text``."""
    spans, skip = [], set()
    for m in _URL.finditer(text) if "://" in text else ():
        skip.add(m.end(1) - 1)  # "p:/" in "http://" is not a drive
        if m.group(1).casefold() != "file":
            spans.append((m.start(), m.end()))
            yield m.group(0)
        elif m.group(2).casefold() not in ("", "localhost") or text.startswith("//", m.end(2)):
            yield m.group(0)
    for m in _START.finditer(text):
        s = m.start()
        if s in skip or any(a <= s < b for a, b in spans) or (m.lastgroup == "tilde" and not plain):
            continue
        end = m.end()
        while end < len(text) and _in_name(text[end]):
            end += 1
        bound = _cstring_end(text, s)
        if bound is not None and m.end() <= bound < end:
            end = bound
        candidate = _trim(text[s:end], record)
        if _is_path(expand(candidate)[0]):
            yield candidate


def embedded_paths(path: Path) -> set[tuple[str, str]]:
    """(where, path) for every absolute path and URL in a fixture file."""
    record = path.name in RECORDS
    return {(where, p) for where, text, plain in texts(path) for p in scan(text, record=record, plain=plain)}


def _component_prefix(rest: list[str], full: tuple[str, ...]) -> bool:
    return len(rest) <= len(full) and tuple(rest) == full[: len(rest)]


def _pinned(parts: list[str], pinned: set[str]) -> bool:
    return any(_component_prefix(parts, tuple(p.split("\\"))) for p in pinned)


def _account_path_ok(rest: list[str]) -> bool:
    if _component_prefix(rest, ("appdata", "local", "temp")) or rest == ["desktop"]:
        return True
    return rest[:3] == ["appdata", "local", "temp"] and _SCRATCH.fullmatch("\\".join(rest[3:])) is not None


def _output_folder_ok(rest: list[str]) -> bool:
    if _component_prefix(rest, OUTPUT_FOLDER):
        return True
    return (
        len(rest) == len(OUTPUT_FOLDER) + 1 and tuple(rest[:-1]) == OUTPUT_FOLDER and rest[-1] in OUTPUT_FILES
    )


def path_problems(name: str, path: str) -> list[str]:
    """Why ``path``, found in the fixture file ``name``, is not allowed (empty if it is)."""
    family = FROM_TEMPLATE.get(name, NONE)
    url = _URL.match(path)
    if url:
        scheme, host = url.group(1).casefold(), url.group(2).casefold()
        if scheme == "file":
            return [f"network path {path}"]
        return [] if host in URL_HOSTS else [f"URL host {host} is not allowed in {name}: {path}"]
    full, unknown = expand(path)
    if unknown:
        return [f"unknown variable {unknown[0]} in {name}: {path}"]
    parts = [p.casefold() for p in _parts(full)]
    if parts[0].startswith("\\\\"):
        return [f"network path {path}"]
    if full.startswith("/"):
        return [f"POSIX home folder {path}"]
    if parts[1] in ("users", "documents and settings", "docume~1"):
        if len(parts) == 2:
            return []
        owner, rest = parts[2], parts[3:]
        if owner in ACCOUNTS:
            ok = _account_path_ok(rest)
            return [] if ok else [f"generating account path other than bare Temp or Desktop: {path}"]
        if owner == "public":
            ok = _output_folder_ok(rest)
            return [] if ok else [f"Public profile path other than the kit output: {path}"]
        if owner in family.profiles:
            return []
        return [f"user profile {owner} is not allowed in {name}: {path}"]
    pinned = INSTALL_PATHS | family.paths | (RECORD_PATHS if name in RECORDS else set())
    if _pinned(parts, pinned) or "\\".join(parts[:3]) in family.roots:
        return []
    return [f"path {full.casefold()} is not on the allowlist for {name}: {path}"]


# --------------------------------------------------------------------------- identity strings
_EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b"
)
_IPV4 = re.compile(r"(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?![\d.])")
_HOST = re.compile(r"\b(?:(?:DESKTOP|LAPTOP)-[A-Z0-9]{7}|WIN-[A-Z0-9]{11}|[A-Z0-9]+(?:-[A-Z0-9]+)*-PC)\b")
_HOST_HINTS = ("DESKTOP-", "LAPTOP-", "WIN-", "-PC")
_SW_FILE = re.compile(r"\.(?:sldprt|sldasm|slddrw)$", re.I)


THIS_HOST_NAMES = sorted(
    n
    for n in {h.split(".")[0] for h in (socket.gethostname(), os.environ.get("COMPUTERNAME", "")) if h}
    if len(n) >= 5 and n.casefold() != "localhost"
)  # this machine's own host name, when it is distinctive enough to search for
THIS_HOST = (
    re.compile(rf"(?<![A-Za-z0-9])(?:{'|'.join(map(re.escape, THIS_HOST_NAMES))})(?![A-Za-z0-9])", re.I)
    if THIS_HOST_NAMES
    else None
)


def identity_strings(text: str) -> list[str]:
    found = []
    if "@" in text:
        found += [
            f"e-mail address {m.group()}" for m in _EMAIL.finditer(text) if not _SW_FILE.search(m.group())
        ]
    for m in _IPV4.finditer(text):
        if all(int(octet) <= 255 for octet in m.group().split(".")):
            found.append(f"IPv4 address {m.group()}")
    if any(hint in text for hint in _HOST_HINTS):
        found += [f"host name {m.group()}" for m in _HOST.finditer(text)]
    if THIS_HOST and any(n.casefold() in text.casefold() for n in THIS_HOST_NAMES):
        found += [f"this machine's host name {m.group()}" for m in THIS_HOST.finditer(text)]
    return found


# --------------------------------------------------------------------------- MFC strings
def _cstring_at(blob: bytes, i: int) -> tuple[str | None, int]:
    """The UTF-16 MFC CString at ``i`` (ff fe ff, then the length in units: one byte, or
    ff and two bytes, or ff ff ff and four) and the offset after it."""
    if blob[i : i + 3] != b"\xff\xfe\xff" or i + 4 > len(blob):
        return None, i
    n, j = blob[i + 3], i + 4
    if n == 0xFF:
        if j + 2 > len(blob):
            return None, i
        (n,) = struct.unpack_from("<H", blob, j)
        j += 2
        if n == 0xFFFF:
            if j + 4 > len(blob):
                return None, i
            (n,) = struct.unpack_from("<I", blob, j)
            j += 4
    data = blob[j : j + 2 * n]
    if len(data) != 2 * n:
        return None, i
    return data.decode("utf-16-le", "replace"), j + 2 * n


def cstrings(blob: bytes):
    """Every UTF-16 MFC CString in ``blob``, skipping markers inside a string already read."""
    i = 0
    while (i := blob.find(b"\xff\xfe\xff", i)) >= 0:
        s, j = _cstring_at(blob, i)
        if s is None:
            i += 1
            continue
        yield s
        i = j


def user_array(blob: bytes) -> list[str]:
    """The ``su_CStringArray`` of user names in ``Header2`` or ``Config-<n>-ModelHeader``:
    an MFC count (a two-byte count, or ffff and four bytes), then that many CStrings."""
    i = blob.find(b"su_CStringArray")
    if i < 0:
        return []
    p = i + len(b"su_CStringArray")
    if p + 2 > len(blob):
        return []
    (n,) = struct.unpack_from("<H", blob, p)
    p += 2
    if n == 0xFFFF:
        (n,) = struct.unpack_from("<I", blob, p)
        p += 4
    names = []
    for _ in range(n):
        s, p = _cstring_at(blob, p)
        if s is None:
            break
        names.append(s)
    return names


_USER_STREAMS = re.compile(r"Header2|Contents/Config-\d+-ModelHeader")
_CORE_AUTHORS = re.compile(r"<\w+:(?:lastModifiedBy|creator)>([^<]*)<")
_SW_AUTHORS = re.compile(r'name="SW-(?:Author|Last Saved By)[^"]*"[^>]*><vt:\w+>([^<]*)<')
# Summary fields a person fills in: they must be empty in the fixtures, except that
# SOLIDWORKS writes its own vendor into app.xml's Company.
_VENDOR = "Dassault Systèmes SolidWorks Corporation"
_SUMMARY_FIELDS = {
    "docProps/core.xml": re.compile(r"<(\w+:(?:title|subject|keywords|description|category))>([^<]*)<"),
    "docProps/app.xml": re.compile(r"<((?:\w+:)?(?:Company|Manager))>([^<]*)<"),
    "docProps/ISolidWorksInformation.xml": re.compile(
        r'name="(SW-(?:Title|Subject|Keywords|Comments)[^"]*)"[^>]*><vt:\w+>([^<]*)<'
    ),
}


def _native_streams(path: Path):
    """(stream, data) for every stream of a native fixture, nested documents included."""
    for where, blob in _blobs(path):
        if ":" in where:
            yield where.rsplit(":", 1)[1], blob


def stored_user_names(path: Path) -> list[str]:
    """User names a document stores outside paths, nested documents included: the
    ``Header2`` and ``ModelHeader`` user arrays, core.xml authors and ``SW-Author`` /
    ``SW-Last Saved By``. Read with this module's own parsers, not the library's."""
    if path.suffix.upper() not in NATIVE:
        return []
    names: list[str] = []
    for stream, blob in _native_streams(path):
        if _USER_STREAMS.fullmatch(stream):
            names += user_array(blob)
        elif stream.endswith("core.xml"):
            names += _CORE_AUTHORS.findall(blob.decode("utf-8", "replace"))
        elif stream.endswith("ISolidWorksInformation.xml"):
            names += _SW_AUTHORS.findall(blob.decode("utf-8", "replace"))
    return [n for n in names if n]


def summary_fields(path: Path) -> list[str]:
    """Filled-in title, subject, keywords, comments, company and manager fields, nested
    documents included."""
    if path.suffix.upper() not in NATIVE:
        return []
    found = []
    for stream, blob in _native_streams(path):
        pattern = _SUMMARY_FIELDS.get(stream)
        if pattern:
            text = blob.decode("utf-8", "replace")
            for key, value in pattern.findall(text):
                if value.strip() and not (key.endswith("Company") and value == _VENDOR):
                    found.append(f"{stream} {key} = {value!r}")
    return found


# Names SOLIDWORKS gives its own tree folders and records, lower case; a trailing number
# and the "___EndTag___" suffix are dropped before the comparison.
SOLIDWORKS_NAMES = {
    "", "ambient", "annotations", "axes", "bill of materials", "boss-extrude", "comments", "created",
    "curves", "cut-extrude", "default", "design binder", "detail folder", "directional", "equations",
    "favorites", "fillet", "folder", "front plane", "graphics bodies", "history", "lights and cameras",
    "live section planes", "locallpattern", "markups", "material <not specified>", "mates", "modified",
    "notes", "origin", "plane", "planes", "right plane", "selection sets", "sensors", "sketch", "sketches",
    "solid bodies", "surface bodies", "top plane",
}  # fmt: skip
_BASE = re.compile(r"(?P<base>.*?)\d*(?:___endtag___)?")
_DOCUMENT_STEMS = "|".join(re.escape(p.stem.casefold()) for p in COMMITTED if p.suffix.upper() in NATIVE)
_DOCUMENT_NAME = re.compile(
    r"(?:part|assem|draw)\d+(?:\^(?:part|assem)\d+)?"  # a new document, or one made from a template
    rf"|part\d+\^(?:{_STEMS})"  # a virtual part
    rf"|(?:{_DOCUMENT_STEMS})(?:-\d+|\.step<\d+>)?"  # a fixture, an instance of it, its STEP import
)


def _reported_names() -> set[str]:
    """Names SOLIDWORKS reported for the fixtures: features, configurations, components,
    materials, sheets and views."""
    names: set[str] = set()
    for key, doc in GROUND_TRUTH.items():
        api = doc.get("api") if isinstance(doc, dict) else None
        if key == "_generation" or not isinstance(api, dict):
            continue
        names.update(api.get("configuration_names") or [])
        names.update(f["name"] for f in api.get("features") or [])
        for cfg in (api.get("configurations") or {}).values():
            names.update(m for m in (cfg.get("material"), cfg.get("material_database")) if m)
            for c in cfg.get("components") or []:
                names.add(c["name"].rsplit("/", 1)[-1])
        for sheet in api.get("sheets") or []:
            names.add(sheet["name"])
            names.update(v["name"] for v in sheet["views"])
    return {n.casefold().strip() for n in names}


REPORTED_NAMES = _reported_names()


def unexpected_names(name: str, path: Path) -> list[str]:
    """Strings in ``Header2`` and ``Config-<n>-ModelHeader`` that are none of the names
    the module docstring lists. Paths there are checked by the path rules."""
    if path.suffix.upper() not in NATIVE:
        return []
    found = []
    for stream, blob in _native_streams(path):
        if not _USER_STREAMS.fullmatch(stream):
            continue
        users = set(user_array(blob))  # checked by the user-name rule
        for s in cstrings(blob):
            low = s.casefold().strip()
            if _START.match(s) or s in users or low in REPORTED_NAMES:
                continue
            if _BASE.fullmatch(low).group("base").strip() in SOLIDWORKS_NAMES or _DOCUMENT_NAME.fullmatch(
                low
            ):
                continue
            found.append(f"unexpected name {s!r} in {stream}")
    return sorted(set(found))


# --------------------------------------------------------------------------- exports
_PLACEHOLDERS = {"", "unknown", "unspecified", "none"}


def export_problems(path: Path) -> list[str]:
    """Identity fields of the exports that are not empty or a placeholder."""
    suffix = path.suffix.lower()
    data = path.read_bytes()
    problems = []
    if suffix in (".x_t", ".x_b"):
        head = data.split(b"**END_OF_HEADER", 1)
        assert len(head) == 2, path.name
        fields = dict(re.findall(r"^(\w+)=(.*?);\s*$", head[0].decode("latin-1"), re.M))
        for key in ("USER", "SITE", "MC_ID"):
            assert key in fields, (path.name, key)
            if fields[key].strip().casefold() not in _PLACEHOLDERS:
                problems.append(f"{path.name}: Parasolid header {key}={fields[key]}")
    elif suffix == ".step":
        text = data.decode("latin-1")
        head = re.search(r"FILE_NAME\s*\(\s*'[^']*'\s*,\s*'[^']*'\s*,\s*\(([^)]*)\)\s*,\s*\(([^)]*)\)", text)
        assert head, path.name
        values = re.findall(r"'([^']*)'", head.group(1) + head.group(2))
        for entity in re.findall(r"=\s*(?:PERSON|ORGANIZATION)\s*\((.*?)\)\s*;", text):
            values += re.findall(r"'([^']*)'", entity)
        problems += [
            f"{path.name}: STEP author or organisation {v!r}"
            for v in values
            if v.casefold() not in _PLACEHOLDERS
        ]
    elif suffix == ".3mf":
        with zipfile.ZipFile(path) as z:
            model = z.read("3D/3dmodel.model").decode("utf-8")
        for key, value in re.findall(r'<metadata name="([^"]*)"[^>]*>([^<]*)<', model):
            if key not in ("CreationDate", "ModificationDate") or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}", value
            ):
                problems.append(f"{path.name}: 3MF metadata {key}={value}")
    return problems


# --------------------------------------------------------------------------- all rules
def file_problems(path: Path, name: str | None = None) -> list[str]:
    """Every rule broken by one fixture file; ``name`` is the fixture it stands for."""
    name = name or path.name
    problems = []
    no_paths = path.suffix.lower() in NO_PATHS or name == "SHA256SUMS.txt"
    for where, p in sorted(embedded_paths(path)):
        if no_paths and not _URL.match(p):
            problems.append(f"{name} should hold no path: {p} (in {where})")
        else:
            problems += [f"{why} (in {where})" for why in path_problems(name, p)]
    identities = {(where, s) for where, text, _ in texts(path) for s in identity_strings(text)}
    problems += [f"{s} (in {where})" for where, s in sorted(identities)]
    users = ACCOUNTS | FROM_TEMPLATE.get(name, NONE).users
    for user in sorted(set(stored_user_names(path))):
        if user.casefold() not in users:
            problems.append(f"stored user name {user} is not allowed in {name}")
    problems += [f"summary field filled in: {s}" for s in summary_fields(path)]
    problems += unexpected_names(name, path)
    problems += export_problems(path)
    return problems


# --------------------------------------------------------------------------- the committed fixtures
@pytest.mark.parametrize("path", COMMITTED, ids=lambda p: p.name)
def test_fixture_carries_only_allowed_paths_and_names(path):
    assert file_problems(path) == []


def test_every_fixture_document_was_checked():
    """Guards the sweep above against passing because it read nothing."""
    names = {p.name for p in COMMITTED}
    documents = [p for p in COMMITTED if p.suffix.upper() in NATIVE]
    assert len(documents) == 19
    total = {p.name: len(embedded_paths(p)) for p in documents}
    assert all(count >= 5 for count in total.values()), total
    assert set(FROM_TEMPLATE) <= names
    for path in documents:
        users = {u.casefold() for u in stored_user_names(path)}
        least = {".SLDPRT": 1, ".SLDASM": 3, ".SLDDRW": 9}[path.suffix.upper()]
        assert len(users) >= least and users & ACCOUNTS, (path.name, len(users))
    exports = [p for p in COMMITTED if p.suffix.lower() in NO_PATHS - {".stl"}]
    assert len(exports) == 7 and all(export_problems(p) == [] for p in exports)


def test_header2_users_are_read_the_same_way_by_the_library():
    """The library's Header2 user list (``metadata.summary``) equals this module's own
    parse, nested documents included."""
    for path in COMMITTED:
        if path.suffix.upper() not in NATIVE:
            continue
        with open_document(path) as doc:
            assert doc.metadata.summary["header2_users"] == user_array(doc.read_stream("Header2")), path.name
            for nested in doc.nested_documents():
                with doc.open_nested(nested) as inner:
                    assert inner.metadata.summary["header2_users"] == user_array(inner.read_stream("Header2"))


def test_the_inherited_template_history_is_really_there():
    """The template allowlists are not dead entries: each template family's own roots,
    install paths and authors occur in the documents made from it, and in no other
    document."""
    seen: dict[str, list[list[str]]] = {}
    for path in COMMITTED:
        if path.suffix.upper() in NATIVE:
            found = (x for _, x in embedded_paths(path) if not _URL.match(x))
            seen[path.name] = [[p.casefold() for p in _parts(expand(x)[0])] for x in found]
    family_paths = MBD.paths | ANSI.paths
    for name, found in seen.items():
        family = FROM_TEMPLATE.get(name)
        roots = {"\\".join(x[:3]) for x in found}
        if family is None:
            assert not roots & (MBD.roots | ANSI.roots), name
            assert not [x for x in found if _pinned(x, family_paths) and not _pinned(x, INSTALL_PATHS)], name
        else:
            assert roots & family.roots, name
    for family, members in ((MBD, ("o08", "o15", "o16")), (ANSI, ("o18", "o19"))):
        found = [x for name, paths in seen.items() if name.startswith(members) for x in paths]
        assert family.roots <= {"\\".join(x[:3]) for x in found}
        for pinned in family.paths:
            assert any(_component_prefix(pinned.split("\\"), tuple(x)) for x in found), pinned
        owners = {
            x[2] for x in found if len(x) > 2 and x[1] in ("users", "documents and settings", "docume~1")
        }
        assert family.profiles <= owners, family.profiles - owners


# --------------------------------------------------------------------------- planted paths
def _cstring(text: str) -> bytes:
    """An MFC Unicode CString, as SOLIDWORKS stores paths in Biography and Header2."""
    data = text.encode("utf-16-le")
    assert len(data) // 2 < 0xFF
    return b"\xff\xfe\xff" + bytes([len(data) // 2]) + data


BIOGRAPHY = "_MO_VERSION_17000/Biography"


def _plant(tmp_path: Path, fixture: str, data: bytes | str, stream: str = BIOGRAPHY) -> Path:
    src = FIXTURES / fixture
    streams = fixture_streams(src)
    out = tmp_path / fixture
    extra = _cstring(data) if isinstance(data, str) else data
    out.write_bytes(rebuild(src, {stream: streams[stream] + extra}))
    return out


def test_a_rebuilt_copy_without_a_plant_passes(tmp_path):
    """Control for the planted tests: rebuilding a fixture adds nothing the rules reject."""
    copy = tmp_path / "o02_boxA.SLDPRT"
    copy.write_bytes(rebuild(FIXTURES / "o02_boxA.SLDPRT"))
    assert file_problems(copy) == []


@pytest.mark.parametrize(
    ("planted", "expected"),
    [
        ("C:\\Users\\someone\\AppData\\Local\\Temp", "user profile someone is"),
        ("C:\\Users\\{account}\\Desktop\\Planted Project", "other than bare Temp or Desktop"),
        ("C:\\Users\\{account}\\Documents", "other than bare Temp or Desktop"),
        ("C:\\Users\\{account}\\AppData\\Local\\Temp\\Planted", "other than bare Temp or Desktop"),
        ("C:\\Users\\{account}\\AppData\\Local\\Temp\\swx1\\VC~~\\o99_Planted\\x.SLDPRT", "other than bare"),
        (
            "C:\\Users\\{account}\\AppData\\Local\\Temp\\swx1\\VC~~\\o16_asm_features\\Planted.SLDPRT",
            "other than",
        ),
        ("C:\\Users\\{account}\\AppData\\Local\\Temp\\..\\..\\..\\Desktop\\Planted", "other than bare Temp"),
        ("C:\\Users\\Public\\Documents\\Planted\\x.SLDPRT", "Public profile path"),
        (
            "C:\\Users\\Public\\Documents\\SolidSeasFixtures\\current-account\\out\\o99_Planted.SLDPRT",
            "Public",
        ),
        ("Q:\\Planted\\Projects\\x.SLDPRT", "path q:\\planted\\projects\\x.sldprt is"),
        (
            "C:\\ProgramData\\SolidWorks\\SOLIDWORKS 2024\\templates\\Planted Jobs\\x.prtdot",
            "not on the allowlist",
        ),
        ("C:\\Program Files\\SOLIDWORKS Corp\\Planted\\x.SLDPRT", "not on the allowlist"),
        ("C:\\Windows\\Planted\\x.SLDPRT", "not on the allowlist"),
        ("\\\\planted-host\\share\\x.SLDPRT", "network path"),
        ("//planted-host/share/x.SLDPRT", "network path"),
        ("\\\\?\\UNC\\planted-host\\share\\x.SLDPRT", "network path"),
        ("file://planted-host/share/x.SLDPRT", "network path"),
        ("https://planted-host.example/x", "URL host planted-host.example"),
        ("/Users/someone/Documents/x.SLDPRT", "POSIX home folder"),
        ("E:\\am3sub\\sldworks\\data\\x.prtdot", "not on the allowlist for o02_boxA.SLDPRT"),
        (f"C:\\Users\\{MBD_AUTHOR}\\Desktop", f"user profile {MBD_AUTHOR} is not allowed in o02_boxA.SLDPRT"),
        # A folder name that starts with a character outside the Latin and Cyrillic scripts
        ("C:\\Users\\{account}\\Desktop\\\u65e5\u672c Client\\x.SLDPRT", "other than bare Temp or Desktop"),
        ("C:\\Users\\{account}\\Desktop\\\u2014 Client\\x.SLDPRT", "other than bare Temp or Desktop"),
        ("C:\\Users\\{account}\\Desktop\\\u0395lectra Corp\\x.SLDPRT", "other than bare Temp or Desktop"),
        ("C:\\Users\\{account}\\Desktop\\\u2605 Job\\x.SLDPRT", "other than bare Temp or Desktop"),
        (
            "C:\\Users\\{account}\\Desktop\\\u05e4\u05e8\u05d5\u05d9\u05e7\u05d8\\x.SLDPRT",
            "other than bare Temp",
        ),
        ("C:\\Users\\{account}\\Desktop\\\u201cClient\u201d\\x.SLDPRT", "other than bare Temp or Desktop"),
        ("C:\\Users\\{account}\\Desktop\\\u2116 12 Client job\\x.SLDPRT", "other than bare Temp or Desktop"),
        ("C:\\Users\\{account}\\AppData\\Local\\Temp\\\u2013Client\\x.SLDPRT", "other than bare Temp"),
        (
            "C:\\Users\\\u0395\u03bb\u03ad\u03bd\u03b7\\Desktop",
            "user profile \u03b5\u03bb\u03ad\u03bd\u03b7 is",
        ),
        ("C:\\Users\\\u5c71\u7530\\Documents\\x.SLDPRT", "user profile \u5c71\u7530 is"),
    ],
)
def test_a_planted_path_in_a_part_is_found(tmp_path, planted, expected):
    copy = _plant(tmp_path, "o02_boxA.SLDPRT", planted.replace("{account}", ACCOUNT))
    problems = file_problems(copy)
    assert len(problems) == 1 and expected in problems[0], problems


@pytest.mark.parametrize(
    "data",
    [
        "AC:\\Users\\someone\\Desktop\\x.SLDPRT".encode("utf-16-le"),
        struct.pack("<H", 67) + "C:\\Users\\someone\\Desktop\\x.SLDPRT".encode("utf-16-le"),  # unit "C"
        b"\x43C:\\Users\\someone\\Desktop\\x.SLDPRT\x00",  # an ANSI string after a length byte of "C"
        b"\x001C:\\Users\\someone\\Desktop\x00",
    ],
    ids=["utf16-after-letter", "utf16-after-length-unit", "ansi-after-length-byte", "ansi-after-digit"],
)
def test_a_path_right_after_a_letter_or_digit_is_found(tmp_path, data):
    """A length byte or unit can be an ASCII letter or digit, so nothing before a drive
    letter hides it."""
    problems = file_problems(_plant(tmp_path, "o02_boxA.SLDPRT", data))
    assert problems and all("user profile someone is" in p for p in problems), problems


@pytest.mark.parametrize(
    ("planted", "expected"),
    [
        ("planted DESKTOP-PL4NT3D", "host name DESKTOP-PL4NT3D"),
        ("planted PLANTEDHOST-PC", "host name PLANTEDHOST-PC"),
        ("mail someone@example.com", "e-mail address someone@example.com"),
        ("at 203.0.113.23 today", "IPv4 address 203.0.113.23"),
    ],
)
def test_a_planted_identity_string_is_found(tmp_path, planted, expected):
    problems = file_problems(_plant(tmp_path, "o02_boxA.SLDPRT", planted))
    assert problems and all(expected in p for p in problems), problems


def test_this_machines_host_name_is_searched_for(tmp_path):
    if not THIS_HOST_NAMES:
        pytest.skip("this machine's host name is too short or generic to search for")
    planted = f"saved on {THIS_HOST_NAMES[0].lower()} today"
    problems = file_problems(_plant(tmp_path, "o02_boxA.SLDPRT", planted))
    assert problems and all("this machine's host name" in p for p in problems), problems


def test_a_template_author_path_is_allowed_only_where_the_template_is(tmp_path):
    ok = _plant(tmp_path, "o08_asm_2x_boxA.SLDASM", f"C:\\Users\\{MBD_AUTHOR}\\AppData\\Local\\Temp")
    assert file_problems(ok) == []
    drawing_only = _plant(tmp_path, "o08_asm_2x_boxA.SLDASM", f"C:\\Users\\{DRAWING_ONLY_AUTHOR}\\Desktop")
    assert any(f"user profile {DRAWING_ONLY_AUTHOR} is" in p for p in file_problems(drawing_only))


def test_a_path_planted_in_a_nested_document_is_found(tmp_path):
    """o16's virtual part is a whole document inside the assembly."""
    src = FIXTURES / "o16_asm_features.SLDASM"
    streams = fixture_streams(src)
    nested_name = next(n for n in streams if n.startswith("VirtualComp/"))
    with open_container(streams[nested_name]) as c:
        inner = {n: c.read(n) for n in c.names()}
    inner[BIOGRAPHY] += _cstring("C:\\Users\\someone\\Desktop")
    copy = tmp_path / src.name
    copy.write_bytes(rebuild(src, {nested_name: build_modern(inner)}))
    problems = file_problems(copy)
    assert len(problems) == 1 and "user profile someone is" in problems[0] and nested_name in problems[0]


def _with_header2_user(src: Path, user: str) -> bytes:
    h2 = fixture_streams(src)["Header2"]
    i = h2.index(b"su_CStringArray") + len(b"su_CStringArray")
    (n,) = struct.unpack_from("<H", h2, i)
    return h2[:i] + struct.pack("<H", n + 1) + _cstring(user) + h2[i + 2 :]


def test_a_planted_user_name_is_found(tmp_path):
    src = FIXTURES / "o02_boxA.SLDPRT"
    core = fixture_streams(src)["docProps/core.xml"]
    planted = re.sub(rb"<dc:lastModifiedBy>[^<]*<", b"<dc:lastModifiedBy>someone<", core, count=1)
    assert planted != core
    copy = tmp_path / src.name
    copy.write_bytes(rebuild(src, {"docProps/core.xml": planted}))
    assert file_problems(copy) == ["stored user name someone is not allowed in o02_boxA.SLDPRT"]


def test_a_user_name_planted_in_header2_is_found(tmp_path):
    src = FIXTURES / "o02_boxA.SLDPRT"
    copy = tmp_path / src.name
    copy.write_bytes(rebuild(src, {"Header2": _with_header2_user(src, "someone")}))
    assert file_problems(copy) == ["stored user name someone is not allowed in o02_boxA.SLDPRT"]


def test_a_user_name_planted_in_a_nested_document_is_found(tmp_path):
    src = FIXTURES / "o16_asm_features.SLDASM"
    streams = fixture_streams(src)
    nested = next(n for n in streams if n.startswith("VirtualComp/"))
    with open_container(streams[nested]) as c:
        inner = {n: c.read(n) for n in c.names()}
    core = inner["docProps/core.xml"]
    inner["docProps/core.xml"] = re.sub(
        rb"<dc:lastModifiedBy>[^<]*<", b"<dc:lastModifiedBy>someone<", core, count=1
    )
    assert inner["docProps/core.xml"] != core
    copy = tmp_path / src.name
    copy.write_bytes(rebuild(src, {nested: build_modern(inner)}))
    assert file_problems(copy) == ["stored user name someone is not allowed in o16_asm_features.SLDASM"]


@pytest.mark.parametrize(
    ("stream", "old", "new", "expected"),
    [
        (
            "docProps/core.xml",
            b"</cp:coreProperties>",
            b"<dc:title>Planted Corp bracket</dc:title></cp:coreProperties>",
            "dc:title = 'Planted Corp bracket'",
        ),
        ("docProps/app.xml", _VENDOR.encode(), b"Planted Corp", "Company = 'Planted Corp'"),
    ],
)
def test_a_planted_summary_field_is_found(tmp_path, stream, old, new, expected):
    src = FIXTURES / "o02_boxA.SLDPRT"
    data = fixture_streams(src)[stream]
    assert data.count(old) == 1
    planted = data.replace(old, new)
    copy = tmp_path / src.name
    copy.write_bytes(rebuild(src, {stream: planted}))
    problems = file_problems(copy)
    assert len(problems) == 1 and expected in problems[0], problems


@pytest.mark.parametrize("stream", ["Header2", "Contents/Config-0-ModelHeader"])
def test_a_document_name_planted_in_a_header_is_found(tmp_path, stream):
    """A part template saved inside a project assembly would carry Part1^<project>."""
    problems = file_problems(_plant(tmp_path, "o02_boxA.SLDPRT", "Part1^Planted Project", stream))
    assert problems == [f"unexpected name 'Part1^Planted Project' in {stream}"]


@pytest.mark.parametrize(
    ("fixture", "planted", "expected"),
    [
        ("ground_truth.json", "C:\\Users\\someone\\Desktop", "user profile someone is"),
        (
            "ground_truth.json",
            "%USERPROFILE%/Desktop/Planted Project/x.SLDPRT",
            "other than bare Temp or Desktop",
        ),
        (
            "ground_truth.json",
            "%USERPROFILE%\\Downloads\\Planted\\x.SLDPRT",
            "other than bare Temp or Desktop",
        ),
        ("ground_truth.json", "%TEMP%/../../../Desktop/Planted/x.SLDPRT", "other than bare Temp or Desktop"),
        ("ground_truth.json", "~/Desktop/Planted/x.SLDPRT", "other than bare Temp or Desktop"),
        ("ground_truth.json", "%PLANTED%\\x.SLDPRT", "unknown variable %PLANTED%"),
        ("ground_truth.json", "\\\\?\\UNC\\planted-host\\share\\x.SLDPRT", "network path"),
        ("generation.log", "C:\\Users\\someone\\Desktop", "user profile someone is"),
        (
            "generation.log",
            "%USERPROFILE%\\Desktop\\Planted (Dassault-shipped)",
            "other than bare Temp or Desktop",
        ),
        ("scrub_report.txt", "C:\\Users\\someone\\Desktop", "user profile someone is"),
    ],
)
def test_a_path_planted_in_a_kit_record_is_found(tmp_path, fixture, planted, expected):
    copy = tmp_path / fixture
    shutil.copyfile(FIXTURES / fixture, copy)
    if fixture.endswith(".json"):
        data = json.loads(copy.read_text(encoding="utf-8"))
        data["o02_boxA.SLDPRT"]["planted"] = planted
        copy.write_text(json.dumps(data), encoding="utf-8")
    else:
        with copy.open("a", encoding="utf-8") as fh:
            fh.write(f"planted {planted}\n")
    problems = file_problems(copy)
    assert len(problems) == 1 and expected in problems[0], problems


def test_a_path_in_an_export_is_found(tmp_path):
    copy = tmp_path / "o02_boxA.STL"
    data = bytearray((FIXTURES / "o02_boxA.STL").read_bytes())
    data[:40] = b"C:\\Users\\someone\\Desktop\\x.STL".ljust(40, b" ")
    copy.write_bytes(bytes(data))
    assert struct.unpack_from("<I", data, 80)[0] == 12
    problems = file_problems(copy)
    assert len(problems) == 1 and "should hold no path" in problems[0]


@pytest.mark.parametrize(
    ("fixture", "old", "new", "expected"),
    [
        ("o02_boxA.x_t", b"USER=unknown;", b"USER=someone;", "Parasolid header USER=someone"),
        ("o02_boxA.x_t", b"SITE=;", b"SITE=PLANTED;", "Parasolid header SITE=PLANTED"),
        ("o02_boxA.x_b", b"MC_ID=unknown;", b"MC_ID=PLANTED;", "Parasolid header MC_ID=PLANTED"),
        ("o02_boxA.step", b"( '' )", b"( 'someone' )", "STEP author or organisation 'someone'"),
        (
            "o02_boxA.step",
            b"ORGANIZATION ( 'UNSPECIFIED'",
            b"ORGANIZATION ( 'Planted Corp'",
            "'Planted Corp'",
        ),
    ],
)
def test_an_identity_planted_in_an_export_is_found(tmp_path, fixture, old, new, expected):
    data = (FIXTURES / fixture).read_bytes()
    assert old in data, fixture
    copy = tmp_path / fixture
    copy.write_bytes(data.replace(old, new, 1))
    problems = file_problems(copy)
    assert len(problems) == 1 and expected in problems[0], problems


def test_planted_3mf_metadata_is_found(tmp_path):
    copy = tmp_path / "o02_boxA.3mf"
    with zipfile.ZipFile(FIXTURES / "o02_boxA.3mf") as src, zipfile.ZipFile(copy, "w") as out:
        for item in src.infolist():
            data = src.read(item)
            if item.filename == "3D/3dmodel.model":
                data = data.replace(
                    b"<resources>", b'<metadata name="Designer">someone</metadata><resources>', 1
                )
            out.writestr(item, data)
    assert file_problems(copy) == ["o02_boxA.3mf: 3MF metadata Designer=someone"]


# --------------------------------------------------------------------------- the private corpus
MANIFEST = os.environ.get("SOLIDSEAS_CORPUS_MANIFEST")
# The repository's own documentation, which the scrub rules keep free of corpus names. A
# name it already uses as a plain word (a standard folder, a file extension, an English
# word such as a view or feature name) says nothing about the corpus.
_REPOSITORY = Path(__file__).resolve().parents[1]
_DOCUMENTATION = [_REPOSITORY / n for n in ("AGENTS.md", "README.md", "CHANGELOG.md")] + sorted(
    [*(_REPOSITORY / "docs").glob("*.md"), *(_REPOSITORY / "docs" / "guide").glob("*.md")]
)
_WORD = re.compile(r"[^\W_]+")


def _whole_words(name: str, text: str, words: set[str]) -> bool:
    """Whether ``name`` stands in ``text`` as whole words (``words`` is ``text``'s word set)."""
    if not set(_WORD.findall(name)) <= words:
        return False
    return re.search(rf"(?<![^\W_]){re.escape(name)}(?![^\W_])", text) is not None


def _corpus_names(manifest: str) -> dict[str, int]:
    """Every file stem and folder name in the manifest that is long enough to be
    specific and is not a plain word of the documentation, lower case, with the first
    manifest row that has it."""
    plain = "\n".join(p.read_text(encoding="utf-8") for p in _DOCUMENTATION).casefold()
    plain_words = set(_WORD.findall(plain))
    out: dict[str, int] = {}
    with open(manifest, encoding="utf-8-sig", newline="") as fh:
        for row, rec in enumerate(csv.DictReader(fh), 2):
            for i, part in enumerate(re.split(r"[\\/]", rec["path"])):
                part = part.strip()
                if i == 0 or not part:
                    continue
                for name in {part, part.rsplit(".", 1)[0]}:
                    low = name.casefold().strip()
                    if len(low) < 6 or low in ACCOUNTS or low.isdigit() or not _WORD.search(low):
                        continue
                    if low in out or _whole_words(low, plain, plain_words):
                        continue
                    # A default document name, also with one more letter or digit: in a binary
                    # view "Assem1" runs into whatever byte follows it.
                    if re.fullmatch(r"(?:part|assem|draw)\d+[^\W_]?", low):
                        continue
                    out.setdefault(low, row)
    return out


def corpus_hits(names: dict[str, int], paths) -> set[str]:
    """Where a name stands as whole words in any view of the files: manifest rows and
    streams only, never the name."""
    by_word: dict[str, set[str]] = {}
    for name in names:
        for word in _WORD.findall(name):
            by_word.setdefault(word, set()).add(name)
    hits = set()
    for path in paths:
        for where, view, _ in texts(path):
            text = view.casefold()
            words = set(_WORD.findall(text))
            for name in set().union(*(by_word[w] for w in words & by_word.keys())):
                if _whole_words(name, text, words):
                    hits.add(f"a name from manifest row {names[name]} occurs in {where}")
    return hits


@pytest.mark.skipif(not MANIFEST, reason="SOLIDSEAS_CORPUS_MANIFEST is not set")
def test_no_corpus_name_occurs_in_any_fixture():
    names = _corpus_names(MANIFEST)
    assert len(names) > 100
    assert sorted(corpus_hits(names, COMMITTED)) == []


def test_a_planted_corpus_name_is_found(tmp_path):
    """The corpus rule on a made-up manifest, so it runs without the private corpus."""
    manifest = tmp_path / "manifest.csv"
    rows = [
        "C:\\Users\\someone\\Documents\\Planted Widget Works\\gizmo bracket 77.SLDPRT",
        "C:\\Users\\someone\\Documents\\Planted Widget Works\\Configuration.SLDPRT",
    ]
    manifest.write_text("path\n" + "".join(f'"{r}"\n' for r in rows), encoding="utf-8-sig")
    names = _corpus_names(str(manifest))
    assert names["planted widget works"] == names["gizmo bracket 77"] == 2
    assert "configuration" not in names and "documents" not in names  # plain words of the documentation
    assert corpus_hits(names, [FIXTURES / "o02_boxA.SLDPRT"]) == set()  # control
    copy = _plant(tmp_path, "o02_boxA.SLDPRT", "Gizmo Bracket 77 rev B")
    assert corpus_hits(names, [copy]) == {f"a name from manifest row 2 occurs in {copy.name}:{BIOGRAPHY}"}
