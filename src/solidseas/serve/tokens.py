"""The service's bearer tokens (``secrets-and-credentials`` and
``authentication-and-trust``).

Every route but ``/v1/health`` needs ``Authorization: Bearer <token>``, on
loopback too: loopback is shared by every program and account on the machine,
and a page in a browser can reach it. The tokens live in one file, a
``name:token`` line per client, so each client has its own credential and one
can be revoked alone by deleting its line. Lines starting with ``#`` are
comments.

* **Created on first start** when the file does not exist, holding one token
  named ``default`` from ``secrets.token_urlsafe(32)``. It is never printed:
  clients read it from the file. It is created with its final permissions
  from the first byte: on Linux and macOS ``O_CREAT | O_EXCL`` with mode
  0600 in a 0700 folder; on Windows ``CREATE_NEW`` with a protected access list
  that grants the current user alone.
* **Checked on every start, failing closed.** A file that cannot be read, is
  empty or malformed, or that other accounts can read (a group or other mode
  bit on Linux and macOS; on Windows an allow entry for anyone but the user,
  SYSTEM and Administrators) refuses the start with
  :class:`~solidseas.errors.TokenFileError` (exit 3), naming the rule. So does
  a file or folder that another account owns (``not_owner``: an owner can
  always rewrite the access list), and a folder another account may add to,
  delete from or re-permission (``folder_writable``), because whoever can do
  that can swap the file for one of their own while the service is stopped.
* **Compared in constant time** (``hmac.compare_digest``) against every
  configured token, and taken only from the header, never from the URL.
* **Proved before it is sent.** Whenever the service is stopped, any program
  can listen on its port and collect the token a client sends (security review
  finding 15). ``/v1/identity`` answers a client's nonce with
  :func:`identity_proof`, an HMAC under that client's token of the nonce and of
  the address and port the connection reached, so a client can tell the real
  service from an impostor, or from a program that forwards its question to the
  real service from another address, before the token leaves it
  (``docs/API.md`` 8.16). Behind a port mapping, which the service sees as a
  connection from elsewhere, ``--identity-address`` names the address clients
  call (:func:`parse_identity_address`), and a request whose ``Host`` header
  names it gets its proof for that address. An unknown client name gets a
  proof no token matches, under a stand-in key derived from the service's
  identity key, so it stays as stable as a real name's proof, across restarts
  and edits of the token file alike. Since anyone may ask, a proof lets
  guesses at a token be tested offline: every token must come from
  :func:`new_token` (``secrets.token_urlsafe(32)``), never from a person.
* **The identity key** is the service's own secret, kept in a file of its own
  beside the token file (:func:`default_identity_key_file`), created on the
  first start that finds none and checked on every start by the same rules as
  the token file (:class:`~solidseas.errors.IdentityKeyError`, exit 3). Nobody
  edits it, so the stand-in proofs it keys do not change when tokens are added
  or revoked.

The default file is ``%LOCALAPPDATA%\\SolidSeas\\serve-tokens`` on Windows and
``$XDG_CONFIG_HOME/solidseas/serve-tokens`` (``~/.config/solidseas/serve-tokens``)
elsewhere.
"""

import hashlib
import hmac
import ipaddress
import os
import re
import secrets
import stat
import sys
from collections.abc import Mapping
from urllib.parse import urlsplit

from ..errors import IdentityKeyError, InvalidArgumentError, TokenFileError

TOKEN_NAME = re.compile(r"[a-z0-9_-]{1,32}\Z")
TOKEN_TEXT = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")
# /v1/identity: the label that starts the proved message, and the client's nonce.
IDENTITY_SCHEME = "solidseas-identity-v1"
# The label of the stand-in key that proves for names the token file does not hold.
_UNKNOWN_LABEL = b"solidseas-identity-unknown-v1"
NONCE_TEXT = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")
MAX_TOKEN_FILE = 64 << 10
MAX_TOKENS = 256
MAX_IDENTITY_KEY_FILE = 4 << 10
HEADER = (
    "# SolidSeas service tokens: one name:token line per client. Keep this file private.\n"
    "# Make each token with secrets.token_urlsafe(32), never by hand (docs/API.md 8.3).\n"
)
IDENTITY_KEY_HEADER = (
    "# SolidSeas service identity key: the service's own secret for /v1/identity (docs/API.md 8.16).\n"
    "# Keep this file private and leave it as it is: it is not a client token.\n"
)
IDENTITY_KEY_SUFFIX = ".identity"
# An identity address's port, as --port takes one: digits, no sign, no leading zero.
_PORT_TEXT = re.compile(r":[1-9][0-9]{0,4}\Z")
# Windows SIDs that may own a token file or its folder besides the user's own: SYSTEM and
# Administrators. An allow entry may also name OWNER RIGHTS, which then means one of them.
# Entries are compared as S-1-... text, after SDDL aliases (SY, BA, OW, and LS or NS for a
# service account) are read as SIDs.
_TRUSTED_OWNERS = {"S-1-5-18", "S-1-5-32-544"}
_OWNER_RIGHTS = "S-1-3-4"
_TRUSTED_SIDS = _TRUSTED_OWNERS | {_OWNER_RIGHTS}
# Rights on a folder that let an account put another file in the token file's place:
# add a file or a folder, delete a child, delete or rename the folder, change its access
# list or its owner, and the generic and maximum rights that include them.
_FOLDER_WRITE = 0x2 | 0x4 | 0x40 | 0x10000 | 0x40000 | 0x80000 | 0x40000000 | 0x10000000 | 0x02000000
# Rights on a file that let an account change what it says: write or append data, delete
# it, change its access list or its owner, and the generic and maximum rights.
_FILE_WRITE = 0x2 | 0x4 | 0x10000 | 0x40000 | 0x80000 | 0x40000000 | 0x10000000 | 0x02000000
# SDDL's two-letter rights, as Windows writes them for files and folders.
_SDDL_RIGHTS = {
    "GA": 0x10000000,
    "GR": 0x80000000,
    "GW": 0x40000000,
    "GX": 0x20000000,
    "RC": 0x20000,
    "SD": 0x10000,
    "WD": 0x40000,
    "WO": 0x80000,
    "CC": 0x1,
    "DC": 0x2,
    "LC": 0x4,
    "SW": 0x8,
    "RP": 0x10,
    "WP": 0x20,
    "DT": 0x40,
    "LO": 0x80,
    "CR": 0x100,
    "FA": 0x1F01FF,
    "FR": 0x120089,
    "FW": 0x120116,
    "FX": 0x1200A0,
}


def sddl_mask(text: str) -> int | None:
    """The access mask an SDDL rights field holds (``FA``, ``0x1301bf``, ``DCLC``...), or
    None when it holds anything this module does not know."""
    text = text.strip()
    if text[:2].lower() == "0x":
        try:
            return int(text, 16)
        except ValueError:
            return None
    if not text or len(text) % 2:
        return None
    mask = 0
    for i in range(0, len(text), 2):
        bit = _SDDL_RIGHTS.get(text[i : i + 2].upper())
        if bit is None:
            return None
        mask |= bit
    return mask


def _refuse(rule: str, message: str, error: type = TokenFileError) -> TokenFileError | IdentityKeyError:
    """A refusal of the token file (or, with ``error``, of the identity key file)."""
    return error(message, detail={"rule": rule})


def default_token_file() -> str:
    """Where ``solidseas serve`` keeps its tokens unless ``--token-file`` says otherwise."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return os.path.join(base, "SolidSeas", "serve-tokens")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "solidseas", "serve-tokens")


def new_token() -> str:
    return secrets.token_urlsafe(32)


# --------------------------------------------------------------------------- Windows access lists
if sys.platform == "win32":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    _advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _SecurityAttributes(ctypes.Structure):
        _fields_ = [
            ("nLength", wintypes.DWORD),
            ("lpSecurityDescriptor", wintypes.LPVOID),
            ("bInheritHandle", wintypes.BOOL),
        ]

    _k32.GetCurrentProcess.restype = wintypes.HANDLE
    _advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    _advapi.OpenProcessToken.restype = wintypes.BOOL
    _advapi.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _advapi.GetTokenInformation.restype = wintypes.BOOL
    _advapi.ConvertSidToStringSidW.argtypes = [wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)]
    _advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
    _advapi.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.LPVOID)]
    _advapi.ConvertStringSidToSidW.restype = wintypes.BOOL
    _advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.ULONG),
    ]
    _advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    _advapi.GetFileSecurityW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _advapi.GetFileSecurityW.restype = wintypes.BOOL
    _advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(wintypes.ULONG),
    ]
    _advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
    _k32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _k32.CreateFileW.restype = wintypes.HANDLE
    _k32.LocalFree.argtypes = [wintypes.HLOCAL]
    _k32.LocalFree.restype = wintypes.HLOCAL
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _INVALID_HANDLE = wintypes.HANDLE(-1).value
    _TOKEN_QUERY = 0x0008
    _TOKEN_USER = 1
    _SDDL_REVISION_1 = 1
    _OWNER_SECURITY_INFORMATION = 0x1
    _DACL_SECURITY_INFORMATION = 0x4
    _GENERIC_WRITE = 0x40000000
    _CREATE_NEW = 1
    _FILE_ATTRIBUTE_NORMAL = 0x80
    _ERROR_FILE_EXISTS = 80

    def _oserror(what: str) -> OSError:
        err = ctypes.get_last_error()
        return OSError(err, f"{what} failed: {ctypes.FormatError(err).strip()}")

    def current_user_sid() -> str:
        """The current user's SID as text (``S-1-5-21-...``)."""
        token = wintypes.HANDLE()
        if not _advapi.OpenProcessToken(_k32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)):
            raise _oserror("OpenProcessToken")
        try:
            size = wintypes.DWORD(0)
            _advapi.GetTokenInformation(token, _TOKEN_USER, None, 0, ctypes.byref(size))
            buf = ctypes.create_string_buffer(size.value)
            if not _advapi.GetTokenInformation(token, _TOKEN_USER, buf, size, ctypes.byref(size)):
                raise _oserror("GetTokenInformation")
            sid = ctypes.cast(buf, ctypes.POINTER(wintypes.LPVOID))[0]  # TOKEN_USER.User.Sid
            text = wintypes.LPWSTR()
            if not _advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
                raise _oserror("ConvertSidToStringSidW")
            try:
                return text.value
            finally:
                _k32.LocalFree(ctypes.cast(text, wintypes.HLOCAL))
        finally:
            _k32.CloseHandle(token)

    def _create_private(path: str, data: bytes) -> None:
        sddl = f"D:P(A;;FA;;;{current_user_sid()})"  # protected: nothing inherited, the user alone
        psd = wintypes.LPVOID()
        if not _advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, _SDDL_REVISION_1, ctypes.byref(psd), None
        ):
            raise _oserror("ConvertStringSecurityDescriptorToSecurityDescriptorW")
        try:
            sa = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), psd, False)
            handle = _k32.CreateFileW(
                path, _GENERIC_WRITE, 0, ctypes.byref(sa), _CREATE_NEW, _FILE_ATTRIBUTE_NORMAL, None
            )
            if handle is None or handle == _INVALID_HANDLE:
                err = ctypes.get_last_error()
                if err == _ERROR_FILE_EXISTS:
                    raise FileExistsError(17, "the token file already exists", path)
                raise OSError(err, ctypes.FormatError(err).strip(), path)
            fd = msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY)
            with open(fd, "wb", closefd=True) as fh:
                fh.write(data)
        finally:
            _k32.LocalFree(ctypes.cast(psd, wintypes.HLOCAL))

    def _sddl(path: str, info: int) -> str:
        size = wintypes.DWORD(0)
        _advapi.GetFileSecurityW(path, info, None, 0, ctypes.byref(size))
        if not size.value:
            raise _oserror("GetFileSecurityW")
        buf = ctypes.create_string_buffer(size.value)
        if not _advapi.GetFileSecurityW(path, info, buf, size, ctypes.byref(size)):
            raise _oserror("GetFileSecurityW")
        text = wintypes.LPWSTR()
        if not _advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            buf, _SDDL_REVISION_1, info, ctypes.byref(text), None
        ):
            raise _oserror("ConvertSecurityDescriptorToStringSecurityDescriptorW")
        try:
            return text.value
        finally:
            _k32.LocalFree(ctypes.cast(text, wintypes.HLOCAL))

    def access_list(path: str) -> str:
        """The file's access list as SDDL (``D:P(A;;FA;;;S-1-5-21-...)``)."""
        return _sddl(path, _DACL_SECURITY_INFORMATION)

    def security_descriptor(path: str) -> str:
        """A file's or folder's owner and access list as SDDL
        (``O:S-1-5-21-...D:P(A;;FA;;;S-1-5-21-...)``)."""
        return _sddl(path, _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION)

    # (type;flags;rights;object guid;inherited object guid;account)
    _ACE = re.compile(r"\(([A-Z]{1,2});([^;]*);([^;]*);[^;]*;[^;]*;([^;)]*)[^)]*\)")
    _OWNER = re.compile(r"O:(.+?)(?=[GDS]:|\Z)")

    def canonical_sid(text: str) -> str | None:
        """A SID as ``S-1-...`` text, whether an access list wrote it that way or as an
        SDDL alias: Windows writes LOCAL SERVICE as ``LS``, NETWORK SERVICE as ``NS``
        and the built-in Administrator account as ``LA``, so a service running as one
        of them would not recognise its own entry by text. None when Windows cannot
        read it as a SID."""
        psid = wintypes.LPVOID()
        if not _advapi.ConvertStringSidToSidW(text, ctypes.byref(psid)):
            return None
        try:
            out = wintypes.LPWSTR()
            if not _advapi.ConvertSidToStringSidW(psid, ctypes.byref(out)):
                return None
            try:
                return out.value
            finally:
                _k32.LocalFree(ctypes.cast(out, wintypes.HLOCAL))
        finally:
            _k32.LocalFree(ctypes.cast(psid, wintypes.HLOCAL))

    def _owner_and_entries(
        sddl: str, what: str, error: type = TokenFileError
    ) -> tuple[str | None, list[tuple[str, str, str, str]]]:
        if "D:" not in sddl or "D:NO_ACCESS_CONTROL" in sddl:
            raise _refuse("shared_access", f"the {what} has no access list, so anyone can use it", error)
        owner = _OWNER.match(sddl)
        entries = _ACE.findall(sddl.split("D:", 1)[1].split("S:", 1)[0])
        return (canonical_sid(owner.group(1)) if owner else None), entries

    def _check_private(path: str, what: str = "token file", error: type = TokenFileError) -> None:
        me = canonical_sid(current_user_sid())
        trusted = _TRUSTED_OWNERS | {me}
        owner, entries = _owner_and_entries(security_descriptor(path), what, error)
        # An owner can always rewrite the access list, whatever it says now, and an OWNER
        # RIGHTS entry grants that owner: both are only as safe as the owner is.
        if owner is None or owner not in trusted:
            raise _refuse("not_owner", f"the {what} belongs to another account", error)
        for kind, _flags, _rights, text in entries:
            if kind not in ("A", "OA", "XA", "ZA"):
                continue
            sid = canonical_sid(text)  # an entry Windows cannot read as a SID fails closed
            if sid is None or (sid not in _TRUSTED_SIDS and sid != me):
                raise _refuse("shared_access", f"another account can read the {what}", error)
        # The folder: whoever may add to it, delete from it or re-permission it can swap the
        # file for one of their own while the service is stopped.
        folder = os.path.dirname(os.path.abspath(path))
        owner, entries = _owner_and_entries(security_descriptor(folder), f"{what}'s folder", error)
        if owner is None or owner not in trusted:
            raise _refuse("not_owner", f"the {what}'s folder belongs to another account", error)
        for kind, flags, rights, text in entries:
            if kind not in ("A", "OA", "XA", "ZA") or "IO" in flags.upper():
                continue  # an inherit-only entry grants nothing on the folder itself
            sid = canonical_sid(text)
            if sid is not None and (sid in _TRUSTED_SIDS or sid == me):
                continue
            mask = sddl_mask(rights)
            if sid is None or mask is None or mask & _FOLDER_WRITE:
                raise _refuse(
                    "folder_writable", f"another account can replace files in the {what}'s folder", error
                )

    def unwritable_problem(path: str, what: str) -> tuple[str, str] | None:
        """``(rule, message)`` when an account other than this one, SYSTEM and
        Administrators may change the file at ``path``, owns it or its folder, or may put
        another file in its place; None when none may. Readers are not checked."""
        me = canonical_sid(current_user_sid())
        trusted = _TRUSTED_OWNERS | {me}
        folder = os.path.dirname(os.path.abspath(path))
        checks = (
            (path, what, _FILE_WRITE, "shared_write"),
            (folder, f"{what}'s folder", _FOLDER_WRITE, "folder_writable"),
        )
        for target, name, rights_that_write, rule in checks:
            sddl = security_descriptor(target)
            if "D:" not in sddl or "D:NO_ACCESS_CONTROL" in sddl:
                return rule, f"the {name} has no access list, so anyone can change it"
            owner = _OWNER.match(sddl)
            if owner is None or canonical_sid(owner.group(1)) not in trusted:
                return "not_owner", f"the {name} belongs to another account"
            for kind, flags, mask_text, text in _ACE.findall(sddl.split("D:", 1)[1].split("S:", 1)[0]):
                if kind not in ("A", "OA", "XA", "ZA") or "IO" in flags.upper():
                    continue  # an inherit-only entry grants nothing on the object itself
                sid = canonical_sid(text)
                if sid is not None and (sid in _TRUSTED_SIDS or sid == me):
                    continue
                mask = sddl_mask(mask_text)
                if sid is None or mask is None or mask & rights_that_write:
                    return rule, f"another account can change the {name}"
        return None

else:  # pragma: no cover - exercised on Linux and macOS

    def _create_private(path: str, data: bytes) -> None:
        flags = (
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        )
        fd = os.open(path, flags, 0o600)
        with open(fd, "wb", closefd=True) as fh:
            fh.write(data)

    def _check_private(path: str, what: str = "token file", error: type = TokenFileError) -> None:
        st = os.stat(path)
        if st.st_mode & 0o077:
            raise _refuse("shared_access", f"the {what}'s mode lets other accounts read it; use 0600", error)
        if hasattr(os, "geteuid") and st.st_uid != os.geteuid():
            raise _refuse("not_owner", f"the {what} belongs to another account", error)
        folder = os.stat(os.path.dirname(os.path.abspath(path)))
        if hasattr(os, "geteuid") and folder.st_uid not in (os.geteuid(), 0):
            raise _refuse("not_owner", f"the {what}'s folder belongs to another account", error)
        # group or other write lets another account rename the file away and put its own
        # there, unless the sticky bit keeps each file to its owner (as in /tmp)
        if folder.st_mode & 0o022 and not folder.st_mode & stat.S_ISVTX:
            raise _refuse(
                "folder_writable", f"another account can replace files in the {what}'s folder", error
            )

    def unwritable_problem(path: str, what: str) -> tuple[str, str] | None:
        """``(rule, message)`` when an account other than this one and root may change the
        file at ``path``, owns it or its folder, or may put another file in its place;
        None when none may. Readers are not checked."""
        euid = os.geteuid() if hasattr(os, "geteuid") else None
        st = os.stat(path)
        if euid is not None and st.st_uid not in (euid, 0):
            return "not_owner", f"the {what} belongs to another account"
        if st.st_mode & 0o022:
            message = f"other accounts may change the {what}: clear its group and other write bits"
            return "shared_write", message
        folder = os.stat(os.path.dirname(os.path.abspath(path)))
        if euid is not None and folder.st_uid not in (euid, 0):
            return "not_owner", f"the {what}'s folder belongs to another account"
        if folder.st_mode & 0o022 and not folder.st_mode & stat.S_ISVTX:
            return "folder_writable", f"another account can replace files in the {what}'s folder"
        return None


# --------------------------------------------------------------------------- the file
def create_token_file(path: str | os.PathLike, *, name: str = "default") -> None:
    """Create the token file with one new token, readable by the current user alone.
    Raises ``FileExistsError`` when it exists (never overwritten)."""
    path = os.fspath(path)
    if not TOKEN_NAME.match(name):
        raise _refuse("malformed", "a token name matches [a-z0-9_-]{1,32}")
    _create_private(path, (HEADER + f"{name}:{new_token()}\n").encode("ascii"))


def load_tokens(path: str | os.PathLike) -> dict[str, str]:
    """``{name: token}`` from the token file, after checking that only the user can read
    it. Raises :class:`~solidseas.errors.TokenFileError` with ``detail["rule"]``:
    ``missing``, ``unreadable``, ``shared_access``, ``not_owner``, ``folder_writable``,
    ``too_large``, ``malformed`` or ``empty`` (and from :func:`ensure_token_file`,
    ``folder_missing``)."""
    path = os.fspath(path)
    try:
        st = os.stat(path)
    except FileNotFoundError:
        raise _refuse("missing", "the token file does not exist") from None
    except OSError:
        raise _refuse("unreadable", "the token file cannot be read") from None
    if not stat.S_ISREG(st.st_mode):
        raise _refuse("unreadable", "the token file is not a regular file")
    if st.st_size > MAX_TOKEN_FILE:
        raise _refuse("too_large", "the token file is too large")
    try:
        _check_private(path)
        with open(path, "rb") as fh:
            raw = fh.read(MAX_TOKEN_FILE + 1)
    except TokenFileError:
        raise
    except OSError:
        raise _refuse("unreadable", "the token file cannot be read") from None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _refuse("malformed", "the token file is not UTF-8 text") from None
    tokens: dict[str, str] = {}
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, token = line.partition(":")
        if not sep or not TOKEN_NAME.match(name) or not TOKEN_TEXT.match(token) or name in tokens:
            raise _refuse("malformed", f"line {n} of the token file is not name:token")
        tokens[name] = token
        if len(tokens) > MAX_TOKENS:
            raise _refuse("malformed", "the token file holds too many tokens")
    if not tokens:
        raise _refuse("empty", "the token file holds no token")
    return tokens


def ensure_token_file(path: str | os.PathLike | None = None) -> tuple[str, dict[str, str], bool]:
    """The token file's path, its tokens, and whether it was created now: the file is
    created on first start (with its folder, for the default location) and checked
    on every start. Raises :class:`~solidseas.errors.TokenFileError`."""
    default = path is None
    path = default_token_file() if default else os.path.abspath(os.fspath(path))
    created = False
    if not os.path.lexists(path):
        folder = os.path.dirname(path)
        if not default and not os.path.isdir(folder):
            # only the default folder is created: a folder made elsewhere would take whatever
            # access its parent passes on, which the checks would then refuse anyway
            raise _refuse("folder_missing", "the token file's folder does not exist; create it first")
        try:
            if default:
                os.makedirs(folder, mode=0o700, exist_ok=True)
            create_token_file(path)
            created = True
        except FileExistsError:
            pass  # another start created it a moment ago: check it like any other
        except OSError:
            raise _refuse("unreadable", "the token file could not be created there") from None
    return path, load_tokens(path), created


# --------------------------------------------------------------------------- the identity key
def default_identity_key_file(token_file: str | os.PathLike) -> str:
    """Where the service keeps its identity key unless ``--identity-key-file`` says
    otherwise: beside the token file, under its name with ``.identity`` added."""
    return os.fspath(token_file) + IDENTITY_KEY_SUFFIX


def create_identity_key_file(path: str | os.PathLike) -> None:
    """Create the identity key file with a new key, readable by the current user alone.
    Raises ``FileExistsError`` when it exists (never overwritten)."""
    _create_private(os.fspath(path), (IDENTITY_KEY_HEADER + new_token() + "\n").encode("ascii"))


def load_identity_key(path: str | os.PathLike) -> bytes:
    """The key in the identity key file, after the checks the token file gets (only the
    service's account, SYSTEM and Administrators may read it or own it and its folder).
    Raises :class:`~solidseas.errors.IdentityKeyError` with ``detail["rule"]``: ``missing``,
    ``unreadable``, ``shared_access``, ``not_owner``, ``folder_writable``, ``too_large``,
    ``malformed`` (anything but one line of 32 to 128 URL-safe characters besides the
    comments) or ``empty``."""
    path = os.fspath(path)

    def refuse(rule: str, message: str) -> IdentityKeyError:
        return _refuse(rule, message, IdentityKeyError)

    try:
        st = os.stat(path)
    except FileNotFoundError:
        raise refuse("missing", "the identity key file does not exist") from None
    except OSError:
        raise refuse("unreadable", "the identity key file cannot be read") from None
    if not stat.S_ISREG(st.st_mode):
        raise refuse("unreadable", "the identity key file is not a regular file")
    if st.st_size > MAX_IDENTITY_KEY_FILE:
        raise refuse("too_large", "the identity key file is too large")
    try:
        _check_private(path, "identity key file", IdentityKeyError)
        with open(path, "rb") as fh:
            raw = fh.read(MAX_IDENTITY_KEY_FILE + 1)
    except IdentityKeyError:
        raise
    except OSError:
        raise refuse("unreadable", "the identity key file cannot be read") from None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise refuse("malformed", "the identity key file is not UTF-8 text") from None
    lines = [line.strip() for line in text.splitlines()]
    keys = [line for line in lines if line and not line.startswith("#")]
    if not keys:
        raise refuse("empty", "the identity key file holds no key")
    if len(keys) > 1 or not TOKEN_TEXT.match(keys[0]):
        raise refuse("malformed", "the identity key file holds one line of 32 to 128 URL-safe characters")
    return keys[0].encode("ascii")


def ensure_identity_key(path: str | os.PathLike) -> tuple[str, bytes, bool]:
    """The identity key file's path, its key, and whether it was created now: created on
    the first start that finds none, never replaced, and checked on every start. Its
    folder must exist (``folder_missing``); one the service may not write to, as in a
    folder only administrators change, refuses the start until an administrator creates
    the file (``unreadable``). Raises :class:`~solidseas.errors.IdentityKeyError`."""
    path = os.path.abspath(os.fspath(path))
    created = False
    if not os.path.lexists(path):
        if not os.path.isdir(os.path.dirname(path)):
            message = "the identity key file's folder does not exist; create it first"
            raise _refuse("folder_missing", message, IdentityKeyError)
        try:
            create_identity_key_file(path)
            created = True
        except FileExistsError:
            pass  # another start created it a moment ago: check it like any other
        except OSError:
            message = "the identity key file could not be created there; create it as the token file was"
            raise _refuse("unreadable", message, IdentityKeyError) from None
    return path, load_identity_key(path), created


def identity_proof(token: str, *, client: str, nonce: str, address: str, port: int) -> str:
    """The proof ``/v1/identity`` answers with (``docs/API.md`` 8.16): the lowercase hex
    HMAC-SHA256, keyed with the client's token, of five lines joined by ``\\n``: the
    scheme (:data:`IDENTITY_SCHEME`), the client's name, its nonce, and the address
    (:func:`proof_address`) and port of the connection. A client computes the same with
    its own token and the address it connected to, and sends the token only on a match."""
    message = "\n".join((IDENTITY_SCHEME, client, nonce, address, str(port)))
    return hmac.new(token.encode("ascii"), message.encode("ascii"), hashlib.sha256).hexdigest()


def proof_address(host: str) -> str:
    """An IP address as the identity proof covers it: IPv4 dotted, IPv6 compressed and
    without a zone, and an IPv4-mapped IPv6 address as the IPv4 address it maps."""
    addr = ipaddress.ip_address(host.split("%", 1)[0])
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return str(addr)


def parse_identity_address(text: str) -> tuple[str, int]:
    """``ADDRESS:PORT`` (``127.0.0.1:8765``, ``[::1]:8765``) as ``--identity-address``
    gives it: an address clients call that is not the one the service listens on, such
    as a published container port. Returns the address as the proof covers it
    (:func:`proof_address`) and the port. A host name, a missing port, an address no
    client can call (``0.0.0.0``, ``::``, multicast) or a zone is refused with
    :class:`~solidseas.errors.InvalidArgumentError`."""
    bad = InvalidArgumentError(
        "an identity address is an IP address and a port, as 127.0.0.1:8765 or [::1]:8765",
        detail={"parameter": "identity_address"},
    )
    if not isinstance(text, str) or not 1 <= len(text) <= 64 or not text.isprintable():
        raise bad
    if any(c in text for c in "/\\@?#% ") or not _PORT_TEXT.search(text):
        raise bad
    try:
        parts = urlsplit("//" + text)
        host, port = parts.hostname, parts.port
        address = ipaddress.ip_address(host or "")
    except ValueError:
        raise bad from None
    if port is None or not 1 <= port <= 65535 or address.is_unspecified or address.is_multicast:
        raise bad
    return proof_address(str(address)), port


class TokenChecker:
    """Checks an ``Authorization`` header against every configured token, and proves the
    service holds a client's token without sending it (:meth:`identity`). ``identity_key``
    is the service's own secret (:func:`ensure_identity_key`), which keys the proofs for
    names the token file does not hold."""

    def __init__(self, tokens: Mapping[str, str], identity_key: bytes | None = None) -> None:
        items = [(n, t) for n, t in tokens.items()]
        if not items:
            raise _refuse("empty", "the service needs at least one token")
        for name, token in items:
            if not isinstance(name, str) or not TOKEN_NAME.match(name):
                raise _refuse("malformed", "a token name matches [a-z0-9_-]{1,32}")
            if not isinstance(token, str) or not TOKEN_TEXT.match(token):
                raise _refuse("malformed", "a token is 32 to 128 URL-safe characters")
        if identity_key is not None and (not isinstance(identity_key, bytes) or len(identity_key) < 32):
            raise _refuse("malformed", "the identity key is at least 32 bytes", IdentityKeyError)
        self._tokens = [(n, t.encode("ascii")) for n, t in items]
        self._by_name = dict(items)
        # Keys the stand-in proofs for unknown names: no one without it can compute them,
        # and it lasts, so an unknown name's proof is the same after a restart, as a real
        # name's is (a key made new at each start would change it, which would tell the two
        # apart). The identity key outlasts edits of the token file too: a stand-in made
        # from the tokens changed for every unknown name when one line was added or deleted
        # while every kept name's proof stayed, so asking before and after an edit told
        # which names were kept. Without an identity key (a caller of the Python API that
        # gives none), it still comes from every configured token, as it did before.
        if identity_key is None:
            identity_key = "\n".join(f"{n}:{t}" for n, t in sorted(items)).encode("ascii")
        self._unknown = hmac.new(identity_key, _UNKNOWN_LABEL, hashlib.sha256).digest()

    def identity(self, client: str, nonce: str, address: str, port: int) -> str:
        """The :func:`identity_proof` for ``client``'s token. An unknown name gets a proof
        under a stand-in key derived from the service's identity key, computed the same way
        and as stable as a real name's proof, so the answer does not say which names
        exist."""
        stand_in = hmac.new(self._unknown, client.encode("ascii"), hashlib.sha256).hexdigest()
        token = self._by_name.get(client, stand_in)
        return identity_proof(token, client=client, nonce=nonce, address=address, port=port)

    def check(self, header: str | None) -> str | None:
        """The name of the client whose token the header carries, or None."""
        if not header:
            return None
        scheme, _, value = header.strip().partition(" ")
        if scheme.lower() != "bearer":
            return None
        presented = value.strip().encode("utf-8", "replace")
        found = None
        for name, token in self._tokens:  # every token is compared, so timing says nothing
            if hmac.compare_digest(presented, token) and found is None:
                found = name
        return found


__all__ = [
    "IDENTITY_SCHEME",
    "NONCE_TEXT",
    "TOKEN_NAME",
    "TokenChecker",
    "create_identity_key_file",
    "create_token_file",
    "default_identity_key_file",
    "default_token_file",
    "ensure_identity_key",
    "ensure_token_file",
    "identity_proof",
    "load_identity_key",
    "load_tokens",
    "new_token",
    "parse_identity_address",
    "proof_address",
]
