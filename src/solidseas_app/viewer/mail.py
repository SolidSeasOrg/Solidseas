"""Email PDF (``docs/DRAWINGS.md`` 15.5, the user's answer to Q7): which way the PDF
goes to the user's mail, the webmail address, the question asked first and the words
the status line says. No Qt is needed for any of it; the two system calls that need
Qt (the browser, a folder) import it when they run.

SolidSeas never sends mail, never sees or stores a password and opens no network
connection of its own. It hands the PDF, and only the PDF, to the user's own mail:

* **The route** (:func:`choose_route`) is chosen before anything is called, from
  Drawing Settings > Email > Method. *Automatic* attaches the PDF in the user's mail
  program when the default Simple MAPI client is classic Outlook or Thunderbird and
  is really there (:func:`mail_client`), and uses webmail otherwise. The check reads
  the registry only, through a function a test replaces, and fails closed to
  webmail: ``Software\\Clients\\Mail``'s default (the user's, else the machine's)
  names the client; classic Outlook's ``OUTLOOK.EXE`` must be found through App
  Paths or Office's install root (new Outlook has no Simple MAPI); Thunderbird's
  registered MAPI library must exist. Anything else, an error or a value of the
  wrong type included, is webmail. *Webmail* is webmail always, and *Just show me
  the file* selects the PDF in File Explorer and does nothing more. Outside Windows
  Automatic is webmail.
* **The attach route** runs Simple MAPI in a child process
  (:mod:`.mailproc`), so a mail program's library that crashes or hangs takes only
  that child with it. Return code 0 is sent and 1 the user closing the compose
  window (nothing is said); anything else falls to webmail with a line saying why.
* **The webmail route** selects the PDF in File Explorer (``explorer.exe`` with
  ``/select,`` and the PDF as one argument, :func:`explorer_command`) and opens the
  compose page in the default browser. The page's address comes from the template
  the user saved (:func:`webmail_url`): ``https://`` only, ``{subject}`` and
  ``{to}`` its only tokens, checked again here (:func:`template_problem`). The
  subject is the drawing number and title only, percent-encoded; ``{to}`` is left
  empty, since SolidSeas knows no address; with pre-filling off the address carries
  no subject either. No path, company, customer or body ever reaches it.
* **A drawing that is not RELEASED** is asked about first
  (:func:`preliminary_question`), and the stamped PDF is the one offered.

The window wires it: :func:`choose_route` on the UI thread, the attach route's
:func:`attach_pdf` on a worker thread (it blocks while the compose window is open),
then :func:`email_pdf` on the UI thread with that result. The system calls,
:func:`start_explorer`, :func:`open_in_browser` and :func:`open_folder`, are looked
up when they are needed, so tests and the self-test's dry run replace them and
nothing is ever started by them.
"""

import ntpath
import os
import re
import stat
import sys
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from solidseas.errors import InvalidArgumentError

METHODS = ("automatic", "webmail", "show")  # Drawing Settings > Email > Method
ATTACH, WEBMAIL, SHOW, NOTHING = "attach", "webmail", "show", "nothing"
STATUSES = ("PRELIMINARY", "CHECKED", "RELEASED")  # solidseas.drawing.types.STATUSES
PRELIMINARY_QUESTION = "This drawing is PRELIMINARY. Send it anyway?"
GMAIL_HOST = "mail.google.com"
TOKENS = ("subject", "to")  # the only placeholders a webmail template holds
MAX_SUBJECT = 200  # characters of the subject, before percent-encoding
MAX_TEMPLATE = 2000  # the settings' own bound on the template
MAX_PATH_TEXT = 1024  # a path read from the registry
MAX_CLIENT_NAME = 64  # a client's name, as a reason quotes it

# The registry, read only. Simple MAPI's stub reads the default client from the user's key
# first, then the machine's.
HKCU, HKLM = "HKCU", "HKLM"
MAIL_CLIENTS = r"SOFTWARE\Clients\Mail"
APP_PATHS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
OFFICE_VERSIONS = ("16.0", "15.0", "14.0")  # Office 2016 and later, 2013, 2010
OUTLOOK_KEY = "Microsoft Outlook"
THUNDERBIRD_KEY = "Mozilla Thunderbird"

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")
_TOKEN = re.compile(r"\{([A-Za-z_]*)\}")


# --------------------------------------------------------------------------- the route
@dataclass(frozen=True)
class MailClient:
    """A mail program the attach route can use: its key (``outlook`` or
    ``thunderbird``), the name the status line gives it, and the file that shows it is
    there (``OUTLOOK.EXE``, or Thunderbird's MAPI library)."""

    key: str
    name: str
    path: str


@dataclass(frozen=True)
class Route:
    """The way Email PDF goes: ``attach`` (with its ``client``), ``webmail`` or
    ``show``; ``reason`` says why Automatic chose webmail, for the log."""

    kind: str
    client: MailClient | None = None
    reason: str | None = None


NOT_WINDOWS = "Simple MAPI is a Windows interface, so Automatic uses webmail here"
NO_CLIENT = "no default mail program is registered for Simple MAPI"
UNREADABLE = "the registry could not be read, so Automatic uses webmail"
NO_OUTLOOK = (
    "Outlook is the default mail program, but classic Outlook's OUTLOOK.EXE was not found "
    "(new Outlook cannot take an attachment this way)"
)
NO_THUNDERBIRD = "Thunderbird is the default mail program, but its MAPI library was not found"


class _Unreadable(Exception):
    """A registry value of a type the check does not read: the check fails closed."""


def registry_value(hive: str, key: str, name: str = "") -> str | None:
    """The text value ``name`` of ``key`` in ``hive`` (``HKCU`` or ``HKLM``), in the
    registry's 64-bit view, then its 32-bit one; None when there is none. Only read,
    never written. Outside Windows always None."""
    if os.name != "nt":
        return None
    import winreg

    root = {HKCU: winreg.HKEY_CURRENT_USER, HKLM: winreg.HKEY_LOCAL_MACHINE}[hive]
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(root, key, 0, winreg.KEY_READ | view) as handle:
                value, kind = winreg.QueryValueEx(handle, name)
        except OSError:
            continue
        if kind not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) or not isinstance(value, str):
            continue
        value = value[:MAX_PATH_TEXT]
        if kind == winreg.REG_EXPAND_SZ:
            value = winreg.ExpandEnvironmentStrings(value)
        if value.strip():
            return value
    return None


def _text(value: Any) -> str | None:
    """A value the reader gave, as text: None for none, else it must be text."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise _Unreadable
    value = value.strip()
    return value or None


def _windows_path(value: Any) -> str | None:
    """A registry value as an absolute Windows path, or None when it is not one."""
    text = _text(value)
    if text is None:
        return None
    text = text.strip('"')
    if len(text) > MAX_PATH_TEXT or _CONTROL.search(text) or not _absolute(text):
        return None
    return ntpath.normpath(text)


def _absolute(path: str) -> bool:
    """A drive path (``C:\\...``) or a UNC one (``\\\\server\\share\\...``)."""
    drive, rest = ntpath.splitdrive(path)
    return bool(drive) and rest.startswith(("\\", "/"))


def _outlook(read, is_file) -> str | None:
    """Classic Outlook's ``OUTLOOK.EXE``: from App Paths (the user's, then the
    machine's), then from Office's install root."""
    for hive in (HKCU, HKLM):
        path = _windows_path(read(hive, APP_PATHS + r"\OUTLOOK.EXE", ""))
        if path and ntpath.basename(path).lower() == "outlook.exe" and is_file(path):
            return path
    for version in OFFICE_VERSIONS:
        root = _windows_path(read(HKLM, rf"SOFTWARE\Microsoft\Office\{version}\Outlook\InstallRoot", "Path"))
        if root:
            path = ntpath.join(root, "OUTLOOK.EXE")
            if is_file(path):
                return path
    return None


def _thunderbird(read, is_file) -> str | None:
    """Thunderbird's registered MAPI library (``DLLPath``), the user's then the machine's."""
    for hive in (HKCU, HKLM):
        path = _windows_path(read(hive, MAIL_CLIENTS + "\\" + THUNDERBIRD_KEY, "DLLPath"))
        if path and path.lower().endswith(".dll") and is_file(path):
            return path
    return None


def _shown_name(name: str) -> str:
    name = _CONTROL.sub("", name)
    return name if len(name) <= MAX_CLIENT_NAME else name[: MAX_CLIENT_NAME - 3] + "..."


def mail_client(
    read: Callable[[str, str, str], Any] | None = None, is_file: Callable[[str], bool] | None = None
) -> tuple[MailClient | None, str | None]:
    """The default Simple MAPI client when it is classic Outlook or Thunderbird and is
    there, else None and the reason. ``read(hive, key, name)`` reads one registry value
    (:func:`registry_value`); ``is_file`` says whether a file is there. Fails closed:
    a reader that raises, or gives anything but text, means no client."""
    read = registry_value if read is None else read
    is_file = os.path.isfile if is_file is None else is_file
    try:
        name = _text(read(HKCU, MAIL_CLIENTS, "")) or _text(read(HKLM, MAIL_CLIENTS, ""))
        if name is None:
            return None, NO_CLIENT
        if name.casefold() == OUTLOOK_KEY.casefold():
            path = _outlook(read, is_file)
            return (MailClient("outlook", "Outlook", path), None) if path else (None, NO_OUTLOOK)
        if name.casefold() == THUNDERBIRD_KEY.casefold():
            path = _thunderbird(read, is_file)
            return (MailClient("thunderbird", "Thunderbird", path), None) if path else (None, NO_THUNDERBIRD)
        return None, f"the default mail program, {_shown_name(name)}, is not one SolidSeas attaches files in"
    except Exception:  # fail closed: any error reading is webmail
        return None, UNREADABLE


def choose_route(
    method: str,
    *,
    windows: bool | None = None,
    read: Callable[[str, str, str], Any] | None = None,
    is_file: Callable[[str], bool] | None = None,
) -> Route:
    """The route for Drawing Settings' ``method`` (:data:`METHODS`), decided before
    anything is called. ``windows`` is whether this is Windows (the system's answer
    when None); ``read`` and ``is_file`` are :func:`mail_client`'s."""
    if method not in METHODS:
        raise InvalidArgumentError(
            f"method must be one of {', '.join(METHODS)}", detail={"parameter": "method"}
        )
    if method == "show":
        return Route(SHOW)
    if method == "webmail":
        return Route(WEBMAIL)
    windows = os.name == "nt" if windows is None else windows
    if not windows:
        return Route(WEBMAIL, reason=NOT_WINDOWS)
    client, reason = mail_client(read, is_file)
    if client is None:
        return Route(WEBMAIL, reason=reason)
    return Route(ATTACH, client=client)


# --------------------------------------------------------------------------- the webmail address
def _clean(text: Any, parameter: str) -> str:
    if not isinstance(text, str):
        raise InvalidArgumentError(f"{parameter} must be text", detail={"parameter": parameter})
    return " ".join(_CONTROL.sub(" ", text).split())


def subject_text(number: str, title: str) -> str:
    """The subject: the drawing number and the title, nothing else, on one line
    without control characters, at most :data:`MAX_SUBJECT` characters."""
    words = " ".join(p for p in (_clean(number, "number"), _clean(title, "title")) if p)
    return words[:MAX_SUBJECT].rstrip()


def template_problem(template: Any) -> str | None:
    """Why ``template`` cannot be a webmail compose address, or None: the settings'
    own check (``https://``, at most 2,000 characters, no control characters,
    ``{subject}`` and ``{to}`` only), and further: no other brace, no space, a host,
    no user name or password before it, and the tokens after it."""
    from solidseas.drawing import settings as drawing_settings

    try:
        drawing_settings.with_value(drawing_settings.DrawingSettings(), "email", "webmail_url", template)
    except InvalidArgumentError as exc:
        return refusal_reason(str(exc))
    for token in _TOKEN.findall(template):
        if token not in TOKENS:
            return "it may hold only {subject} and {to}"
    if "{" in _TOKEN.sub("", template) or "}" in _TOKEN.sub("", template):
        return "its braces do not pair as {subject} or {to}"
    if any(c.isspace() for c in template):
        return "it holds a space"
    parts = urllib.parse.urlsplit(template)
    if parts.scheme != "https" or not parts.netloc:
        return "it must start with https:// and a host"
    if "@" in parts.netloc:
        return "it names a user or a password before the host"
    if "{" in parts.netloc:
        return "{subject} and {to} belong after the host, not in it"
    try:
        parts.port  # noqa: B018 (raises on a port that is not a number)
    except ValueError:
        return "its port is not a number"
    return None


_REFUSAL = re.compile(
    r"^[a-z_]+\.[a-z_]+(?:\[(\d+)\])?: (.*?)(?:; the default is used|; the entry is left out)?$"
)


def refusal_reason(message: str) -> str:
    """The reason in a settings refusal (``email.webmail_url: it must start with
    https://; the default is used``), without the setting's name and the fallback
    that loading would take: ``it must start with https://``. A list entry is named
    by its row, counted from 1."""
    match = _REFUSAL.match(message)
    if not match:
        return message
    row, reason = match.groups()
    return f"row {int(row) + 1}: {reason}" if row is not None else reason


def webmail_url(template: str, number: str, title: str, *, prefill: bool = True) -> str:
    """The compose page's address: ``template`` with ``{subject}`` the drawing number
    and title percent-encoded (empty with ``prefill`` off) and ``{to}`` empty.
    InvalidArgumentError when the template is not one (:func:`template_problem`)."""
    problem = template_problem(template)
    if problem is not None:
        raise InvalidArgumentError(
            f"the webmail address is not valid: {problem}", detail={"parameter": "template"}
        )
    subject = urllib.parse.quote(subject_text(number, title), safe="") if prefill else ""
    return _TOKEN.sub(lambda m: subject if m.group(1) == "subject" else "", template)


# --------------------------------------------------------------------------- what is asked and said
def preliminary_question(status: str) -> str | None:
    """The question asked before a drawing that is not RELEASED is sent (13.2), or None
    for a RELEASED one: its stamped PDF is the one sent."""
    if status not in STATUSES:
        raise InvalidArgumentError(
            f"status must be one of {', '.join(STATUSES)}", detail={"parameter": "status"}
        )
    return None if status == "RELEASED" else PRELIMINARY_QUESTION


def webmail_name(url: str) -> str:
    """What the status line calls the webmail: Gmail for Gmail's address, else "Your
    webmail"."""
    host = urllib.parse.urlsplit(url).hostname or ""
    return "Gmail" if host.lower() == GMAIL_HOST else "Your webmail"


def webmail_status(url: str, pdf_name: str, *, selected: bool = True) -> str:
    """What the status line says once the compose page and the folder are open."""
    opened = f"{webmail_name(url)} opened a new message in your browser."
    if selected:
        return f"{opened} Drag the selected PDF from the folder window into it."
    return f"{opened} Drag {pdf_name} from the folder window into it."


def sent_status(client: MailClient, pdf_name: str) -> str:
    """What the status line says when the mail program took the message (code 0)."""
    return f"The message with {pdf_name} attached went to {client.name} to send."


def fallback_status(client: MailClient, reason: str, webmail: str) -> str:
    """The attach route failed: why, then what the webmail route did."""
    return f"{client.name} could not attach the PDF ({reason}). {webmail}"


def show_status(pdf_name: str, *, selected: bool = True) -> str:
    """What the status line says on Just show me the file."""
    if selected:
        return f"{pdf_name} is selected in File Explorer."
    return f"The folder that holds {pdf_name} is open."


# --------------------------------------------------------------------------- the PDF and the folder
def pdf_problem(path: Any) -> str | None:
    """Why ``path`` is not a PDF Email PDF offers, or None: an absolute path to a plain
    file, not a link, named ``.pdf``. Never the ``.ssdrw``, DXF or SLDDRW, which can
    carry folder names. Only ``lstat`` looks at it; the file is not read."""
    if not isinstance(path, str) or not path or not os.path.isabs(path) or _CONTROL.search(path):
        return "its place is not known"
    if '"' in path:
        return "its path holds a quotation mark"
    if not path.lower().endswith(".pdf"):
        return "only a drawing's PDF is ever sent"
    try:
        st = os.lstat(path)
    except OSError:
        return "it is not there any more"
    from solidseas.walk import reparse_link

    # The walker's rule: a symbolic link, a junction or another name surrogate is a link; a
    # cloud file (OneDrive's) is a file.
    attrs = int(getattr(st, "st_file_attributes", 0) or 0)
    if stat.S_ISLNK(st.st_mode) or reparse_link(attrs, int(getattr(st, "st_reparse_tag", 0) or 0)):
        return "it is a link, which SolidSeas never follows"
    if not stat.S_ISREG(st.st_mode):
        return "it is not a file"
    return None


def windows_folder(env: dict[str, str] | None = None) -> str:
    """The Windows folder, which holds ``explorer.exe``: the system's answer on
    Windows, else ``SystemRoot`` from ``env``, else ``C:\\Windows``."""
    if env is None and os.name == "nt":  # pragma: no cover - Windows
        import ctypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetSystemWindowsDirectoryW.argtypes = (ctypes.c_wchar_p, ctypes.c_uint)
        k32.GetSystemWindowsDirectoryW.restype = ctypes.c_uint
        buf = ctypes.create_unicode_buffer(260)
        n = k32.GetSystemWindowsDirectoryW(buf, 260)
        if 0 < n < 260:
            return buf.value
    env = os.environ if env is None else env
    folder = env.get("SystemRoot") or env.get("SYSTEMROOT") or ""
    return folder if _absolute(folder) else "C:\\Windows"


def explorer_command(path: str, folder: str | None = None) -> str:
    """The command line that shows ``path`` selected in File Explorer: Explorer by its
    full path, ``/select,`` and the path in quotation marks as its one argument, which
    a space or a comma in the name cannot split. A Windows path cannot hold a quotation
    mark, and one that does is refused, as is a relative path or a control character."""
    if not isinstance(path, str) or not _absolute(path) or '"' in path or _CONTROL.search(path):
        raise InvalidArgumentError(
            "the PDF's path is not one Explorer can show", detail={"parameter": "path"}
        )
    explorer = ntpath.join(windows_folder() if folder is None else folder, "explorer.exe")
    return f'"{explorer}" /select,"{ntpath.normpath(path)}"'


def start_explorer(path: str) -> None:  # pragma: no cover - Windows; tests replace it
    """Show ``path`` selected in File Explorer (:func:`explorer_command`): no shell, the
    command line passed as it is to the system, standard handles to nothing, and the
    viewer's packaging left behind (:func:`.printing.launch_environment`), as 3D
    Print's launcher starts a program. Windows only."""
    import subprocess

    from .printing import _DefaultDllDirectory, launch_environment

    frozen = bool(getattr(sys, "frozen", False))
    options: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        "shell": False,
        "env": launch_environment(bundle=getattr(sys, "_MEIPASS", None) if frozen else None),
        "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
    }
    with _DefaultDllDirectory(frozen):
        subprocess.Popen(explorer_command(path), **options)


class _CleanStart:
    """In the packaged viewer, for the instant of a start through the system: the
    environment without the viewer's packaging and the default DLL search order, put
    back afterwards. Elsewhere nothing changes."""

    def __enter__(self):
        from .printing import _DefaultDllDirectory, launch_environment

        self.frozen = bool(getattr(sys, "frozen", False))
        self.saved: dict[str, str] | None = None
        self.dlls = _DefaultDllDirectory(self.frozen)
        if self.frozen:
            self.saved = dict(os.environ)
            clean = launch_environment(bundle=getattr(sys, "_MEIPASS", None))
            for key in [k for k in os.environ if k not in clean]:
                del os.environ[key]
            os.environ.update(clean)
        self.dlls.__enter__()
        return self

    def __exit__(self, *exc: Any) -> None:
        try:
            self.dlls.__exit__(*exc)
        finally:
            if self.saved is not None:
                for key in [k for k in os.environ if k not in self.saved]:
                    del os.environ[key]
                os.environ.update(self.saved)


def open_in_browser(url: str) -> None:  # pragma: no cover - tests replace it
    """Open ``url``, an ``https://`` address, in the default browser
    (``QDesktopServices.openUrl``). Raises OSError when the system could not."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    address = QUrl(url, QUrl.ParsingMode.StrictMode)
    if not address.isValid() or address.scheme() != "https":
        raise OSError("the webmail address is not one the browser is given")
    with _CleanStart():
        ok = QDesktopServices.openUrl(address)
    if not ok:
        raise OSError("the system could not open the browser")


def open_folder(folder: str) -> None:  # pragma: no cover - tests replace it
    """Open ``folder`` in the system's file manager (``QDesktopServices.openUrl``).
    Raises OSError when the system could not."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    with _CleanStart():
        ok = QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
    if not ok:
        raise OSError("the system could not open the folder")


def show_pdf(path: str, *, windows: bool | None = None) -> bool:
    """Show the PDF: selected in File Explorer on Windows (:func:`start_explorer`),
    its folder opened elsewhere (:func:`open_folder`). Whether it is selected."""
    windows = os.name == "nt" if windows is None else windows
    if windows:
        start_explorer(path)
        return True
    open_folder(os.path.dirname(path))
    return False


# --------------------------------------------------------------------------- Email PDF
@dataclass(frozen=True)
class Delivery:
    """What Email PDF did: the route it took (``attach``, ``webmail``, ``show``, or
    ``nothing`` when the user closed the compose window), the status line (empty when
    there is nothing to say), and the webmail address opened."""

    route: str
    status: str
    url: str | None = None


def attach_pdf(path: str, name: str, subject: str = "", **options: Any):
    """The attach route: :func:`.mailproc.send_in_process`, which blocks while the
    compose window is open, so the window calls it from a worker thread."""
    from . import mailproc

    return mailproc.send_in_process(path, name, subject, **options)


def email_pdf(
    pdf: str,
    number: str,
    title: str,
    email: Any,
    *,
    route: Route | None = None,
    attached: Any = None,
    attach: Callable[..., Any] | None = None,
    show: Callable[..., bool] | None = None,
    open_url: Callable[[str], None] | None = None,
    windows: bool | None = None,
) -> Delivery:
    """Email PDF for the PDF at ``pdf``, made current and asked about
    (:func:`preliminary_question`) by the caller. ``email`` is Drawing Settings'
    Email group (or the settings that hold it). ``route`` is :func:`choose_route`'s
    (chosen here when None); for the attach route, ``attached`` is the result the
    window's worker thread got from :func:`attach_pdf` (called here when None, which
    blocks). ``attach``, ``show`` and ``open_url`` stand in for :func:`attach_pdf`,
    :func:`show_pdf` and :func:`open_in_browser`. OSError when the system could not
    show the file or open the browser."""
    email = getattr(email, "email", email)
    problem = pdf_problem(pdf)
    if problem is not None:
        raise InvalidArgumentError(f"the PDF cannot be sent: {problem}", detail={"parameter": "pdf"})
    route = choose_route(email.method, windows=windows) if route is None else route
    name = os.path.basename(pdf)
    subject = subject_text(number, title) if email.prefill_subject else ""
    show = show or (lambda path: show_pdf(path, windows=windows))
    if route.kind == SHOW:
        return Delivery(SHOW, show_status(name, selected=show(pdf)))
    failed = None
    if route.kind == ATTACH and route.client is not None:
        result = (attach or attach_pdf)(pdf, name, subject) if attached is None else attached
        if getattr(result, "cancelled", False) or result.code == 1:
            return Delivery(NOTHING, "")
        if result.code == 0:
            return Delivery(ATTACH, sent_status(route.client, name))
        failed = result.reason or "the mail program gave no reason"
    url = webmail_url(email.webmail_url, number, title, prefill=email.prefill_subject)
    selected = show(pdf)
    (open_url or open_in_browser)(url)
    status = webmail_status(url, name, selected=selected)
    if failed is not None and route.client is not None:
        status = fallback_status(route.client, failed, status)
    return Delivery(WEBMAIL, status, url)


__all__ = [
    "ATTACH",
    "METHODS",
    "NOTHING",
    "PRELIMINARY_QUESTION",
    "SHOW",
    "WEBMAIL",
    "Delivery",
    "MailClient",
    "Route",
    "attach_pdf",
    "choose_route",
    "email_pdf",
    "explorer_command",
    "fallback_status",
    "mail_client",
    "open_folder",
    "open_in_browser",
    "pdf_problem",
    "preliminary_question",
    "refusal_reason",
    "registry_value",
    "sent_status",
    "show_pdf",
    "show_status",
    "start_explorer",
    "subject_text",
    "template_problem",
    "webmail_name",
    "webmail_status",
    "webmail_url",
    "windows_folder",
]
