"""Email PDF (``solidseas_app.viewer.mail`` and ``.mailproc``; ``docs/DRAWINGS.md`` 15.5).

No test here opens a browser, a mail program or File Explorer. ``no_system_calls``
replaces the three functions that would (:func:`mail.start_explorer`,
:func:`mail.open_in_browser`, :func:`mail.open_folder`) with ones that fail the test,
for every test of this module, and conftest's guard refuses :func:`printing.launch`
for the whole run. The registry is a dictionary handed to the route's check, so what
is installed on the machine running the tests never decides a result. The attach
route's child process runs for real, with a stub in place of the Simple MAPI call:
the stubs are this module's functions, which the child imports. The real call is a
check on the PC with the user present (``docs/DRAWINGS.md`` 24, item 7).
"""

import ctypes
import os
import struct
import time
import urllib.parse

import pytest

from solidseas.drawing import settings as drawing_settings
from solidseas.errors import InvalidArgumentError
from solidseas_app.viewer import mail, mailproc

GMAIL = drawing_settings.Email().webmail_url
OUTLOOK_WEB = "https://outlook.office.com/mail/deeplink/compose?to={to}&subject={subject}"
OUTLOOK_EXE = r"C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE"
THUNDERBIRD_DLL = r"C:\Program Files\Mozilla Thunderbird\mozMapi32_InUse.dll"
APP_PATH_KEY = mail.APP_PATHS + r"\OUTLOOK.EXE"
THUNDERBIRD_KEY = mail.MAIL_CLIENTS + "\\" + mail.THUNDERBIRD_KEY
NUMBER, TITLE = "D-1001", "BRACKET, MOUNTING"


# --------------------------------------------------------------------------- stand-ins
@pytest.fixture(autouse=True)
def no_system_calls(monkeypatch):
    """Every system call Email PDF makes fails the test unless the test stands in for it."""

    def refuse(what):
        def call(*args, **kwargs):
            raise AssertionError(f"a test tried to {what}: {args}")

        return call

    monkeypatch.setattr(mail, "start_explorer", refuse("start File Explorer"))
    monkeypatch.setattr(mail, "open_in_browser", refuse("open a browser"))
    monkeypatch.setattr(mail, "open_folder", refuse("open a folder"))


def registry(values: dict, *, fail: BaseException | None = None):
    """A registry reader over ``values``: {(hive, key, name): value}, keys in any case."""
    folded = {(h, k.lower(), n.lower()): v for (h, k, n), v in values.items()}
    asked = []

    def read(hive, key, name):
        asked.append((hive, key, name))
        if fail is not None:
            raise fail
        return folded.get((hive, key.lower(), name.lower()))

    read.asked = asked
    return read


def present(*paths):
    return lambda path: path in paths


def never(*_args):
    raise AssertionError("the registry was read")


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "Drawings" / "D-1001 A.pdf"
    path.parent.mkdir()
    path.write_bytes(b"%PDF-1.7\n%stand-in\n")
    return str(path)


class Recorder:
    """Stands in for the system calls of one Email PDF, in the order they come."""

    def __init__(self, selected=True):
        self.calls = []
        self.selected = selected

    def show(self, path):
        self.calls.append(("show", path))
        return self.selected

    def open_url(self, url):
        self.calls.append(("open", url))

    def attach(self, path, name, subject):
        self.calls.append(("attach", path, name, subject))
        return mailproc.AttachResult(0)


def email(**changes):
    group = drawing_settings.Email()
    settings = drawing_settings.DrawingSettings(email=group)
    for key, value in changes.items():
        settings = drawing_settings.with_value(settings, "email", key, value)
    return settings.email


# --------------------------------------------------------------------------- the route
def test_webmail_and_show_are_taken_as_set_without_reading_the_registry():
    assert mail.choose_route("webmail", windows=True, read=never) == mail.Route(mail.WEBMAIL)
    assert mail.choose_route("show", windows=True, read=never) == mail.Route(mail.SHOW)


def test_an_unknown_method_is_refused():
    with pytest.raises(InvalidArgumentError) as info:
        mail.choose_route("outlook", windows=True, read=never)
    assert info.value.detail == {"parameter": "method"}


def test_automatic_is_webmail_outside_windows_without_reading_the_registry():
    route = mail.choose_route("automatic", windows=False, read=never)
    assert route.kind == mail.WEBMAIL and route.reason == mail.NOT_WINDOWS


OUTLOOK = mail.MailClient("outlook", "Outlook", OUTLOOK_EXE)
THUNDERBIRD = mail.MailClient("thunderbird", "Thunderbird", THUNDERBIRD_DLL)
CASES = {
    "nothing registered": ({}, (), None, mail.NO_CLIENT),
    "the user's default is classic Outlook": (
        {("HKCU", mail.MAIL_CLIENTS, ""): "Microsoft Outlook", ("HKLM", APP_PATH_KEY, ""): OUTLOOK_EXE},
        (OUTLOOK_EXE,),
        OUTLOOK,
        None,
    ),
    "the machine's default is Outlook, found through Office's install root": (
        {
            ("HKLM", mail.MAIL_CLIENTS, ""): "Microsoft Outlook",
            ("HKLM", r"SOFTWARE\Microsoft\Office\16.0\Outlook\InstallRoot", "Path"): (
                "C:\\Program Files\\Microsoft Office\\root\\Office16\\"
            ),
        },
        (OUTLOOK_EXE,),
        OUTLOOK,
        None,
    ),
    "the name in another case, the path in quotation marks": (
        {
            ("HKCU", mail.MAIL_CLIENTS, ""): "microsoft outlook",
            ("HKCU", APP_PATH_KEY, ""): f'"{OUTLOOK_EXE}"',
        },
        (OUTLOOK_EXE,),
        OUTLOOK,
        None,
    ),
    "Outlook registered, but no OUTLOOK.EXE (new Outlook)": (
        {("HKCU", mail.MAIL_CLIENTS, ""): "Microsoft Outlook", ("HKLM", APP_PATH_KEY, ""): OUTLOOK_EXE},
        (),
        None,
        mail.NO_OUTLOOK,
    ),
    "App Paths naming another program": (
        {
            ("HKCU", mail.MAIL_CLIENTS, ""): "Microsoft Outlook",
            ("HKLM", APP_PATH_KEY, ""): r"C:\Tools\mail.exe",
        },
        (r"C:\Tools\mail.exe",),
        None,
        mail.NO_OUTLOOK,
    ),
    "App Paths giving a relative path": (
        {("HKCU", mail.MAIL_CLIENTS, ""): "Microsoft Outlook", ("HKLM", APP_PATH_KEY, ""): "OUTLOOK.EXE"},
        ("OUTLOOK.EXE",),
        None,
        mail.NO_OUTLOOK,
    ),
    "Thunderbird with its MAPI library": (
        {
            ("HKCU", mail.MAIL_CLIENTS, ""): "Mozilla Thunderbird",
            ("HKLM", THUNDERBIRD_KEY, "DLLPath"): THUNDERBIRD_DLL,
        },
        (THUNDERBIRD_DLL,),
        THUNDERBIRD,
        None,
    ),
    "Thunderbird without its library": (
        {
            ("HKCU", mail.MAIL_CLIENTS, ""): "Mozilla Thunderbird",
            ("HKLM", THUNDERBIRD_KEY, "DLLPath"): THUNDERBIRD_DLL,
        },
        (),
        None,
        mail.NO_THUNDERBIRD,
    ),
    "Thunderbird's library path not a DLL": (
        {
            ("HKCU", mail.MAIL_CLIENTS, ""): "Mozilla Thunderbird",
            ("HKLM", THUNDERBIRD_KEY, "DLLPath"): r"C:\Program Files\Mozilla Thunderbird\thunderbird.exe",
        },
        (r"C:\Program Files\Mozilla Thunderbird\thunderbird.exe",),
        None,
        mail.NO_THUNDERBIRD,
    ),
    "the user's choice over the machine's": (
        {
            ("HKCU", mail.MAIL_CLIENTS, ""): "Microsoft Outlook",
            ("HKLM", mail.MAIL_CLIENTS, ""): "Mozilla Thunderbird",
            ("HKLM", APP_PATH_KEY, ""): OUTLOOK_EXE,
            ("HKLM", THUNDERBIRD_KEY, "DLLPath"): THUNDERBIRD_DLL,
        },
        (OUTLOOK_EXE, THUNDERBIRD_DLL),
        OUTLOOK,
        None,
    ),
    "the user's choice missing is not made up from the machine's": (
        {
            ("HKCU", mail.MAIL_CLIENTS, ""): "Microsoft Outlook",
            ("HKLM", mail.MAIL_CLIENTS, ""): "Mozilla Thunderbird",
            ("HKLM", THUNDERBIRD_KEY, "DLLPath"): THUNDERBIRD_DLL,
        },
        (THUNDERBIRD_DLL,),
        None,
        mail.NO_OUTLOOK,
    ),
    "another mail program": (
        {("HKCU", mail.MAIL_CLIENTS, ""): "Mailbird"},
        (),
        None,
        "the default mail program, Mailbird, is not one SolidSeas attaches files in",
    ),
    "a value of the wrong type": (
        {("HKCU", mail.MAIL_CLIENTS, ""): 7, ("HKLM", mail.MAIL_CLIENTS, ""): "Microsoft Outlook"},
        (OUTLOOK_EXE,),
        None,
        mail.UNREADABLE,
    ),
}


@pytest.mark.parametrize("case", list(CASES))
def test_automatic_attaches_only_through_a_client_that_is_there(case):
    values, files, client, reason = CASES[case]
    route = mail.choose_route("automatic", windows=True, read=registry(values), is_file=present(*files))
    if client is None:
        assert route == mail.Route(mail.WEBMAIL, reason=reason)
    else:
        assert route == mail.Route(mail.ATTACH, client=client)


@pytest.mark.parametrize("error", [OSError("access denied"), RuntimeError("damaged"), MemoryError()])
def test_a_registry_that_cannot_be_read_is_webmail(error):
    route = mail.choose_route("automatic", windows=True, read=registry({}, fail=error), is_file=present())
    assert route == mail.Route(mail.WEBMAIL, reason=mail.UNREADABLE)


def test_a_file_check_that_fails_is_webmail():
    def broken(_path):
        raise OSError("the drive is gone")

    values = {("HKCU", mail.MAIL_CLIENTS, ""): "Microsoft Outlook", ("HKLM", APP_PATH_KEY, ""): OUTLOOK_EXE}
    route = mail.choose_route("automatic", windows=True, read=registry(values), is_file=broken)
    assert route == mail.Route(mail.WEBMAIL, reason=mail.UNREADABLE)


def test_a_client_name_is_quoted_without_control_characters_and_cut():
    values = {("HKCU", mail.MAIL_CLIENTS, ""): "Mail\x07 " + "x" * 100}
    _client, reason = mail.mail_client(registry(values), present())
    assert "\x07" not in reason and "..." in reason and len(reason) < 140


@pytest.mark.skipif(os.name == "nt", reason="reads the real registry on Windows")
def test_the_real_reader_reads_nothing_outside_windows():
    assert mail.registry_value("HKCU", mail.MAIL_CLIENTS, "") is None


# --------------------------------------------------------------------------- the webmail address
def test_the_subject_is_percent_encoded_in_gmails_address():
    url = mail.webmail_url(GMAIL, "D-1001", "BRACKET, MOUNTING & BASE #2")
    assert url == (
        "https://mail.google.com/mail/?view=cm&fs=1&su=D-1001%20BRACKET%2C%20MOUNTING%20%26%20BASE%20%232"
    )
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    assert query == {"view": ["cm"], "fs": ["1"], "su": ["D-1001 BRACKET, MOUNTING & BASE #2"]}


def test_a_subject_outside_ascii_is_sent_as_utf8():
    url = mail.webmail_url(GMAIL, "D-2002", "\u00d810 FLANSCH F\u00dcR WELLE \u2116 3")
    assert "su=D-2002%20%C3%9810%20FLANSCH%20F%C3%9CR%20WELLE%20%E2%84%96%203" in url
    assert url.isascii()
    assert urllib.parse.unquote(url.split("su=")[1]) == "D-2002 \u00d810 FLANSCH F\u00dcR WELLE \u2116 3"


def test_the_subject_is_one_line_of_the_number_and_title_only():
    assert (
        mail.subject_text(" D-1001\t", "BRACKET,\nMOUNTING\u2028PLATE\x00")
        == "D-1001 BRACKET, MOUNTING PLATE"
    )
    assert mail.subject_text("", "BRACKET") == "BRACKET"
    assert mail.subject_text("D-1", "") == "D-1"
    assert len(mail.subject_text("D-1", "X" * 1000)) == mail.MAX_SUBJECT
    with pytest.raises(InvalidArgumentError) as info:
        mail.subject_text(None, "BRACKET")
    assert info.value.detail == {"parameter": "number"}


def test_without_prefilling_the_address_carries_no_subject():
    url = mail.webmail_url(GMAIL, NUMBER, TITLE, prefill=False)
    assert url == "https://mail.google.com/mail/?view=cm&fs=1&su="
    assert NUMBER not in url and "BRACKET" not in url


def test_the_to_token_is_left_empty():
    url = mail.webmail_url(OUTLOOK_WEB, NUMBER, TITLE)
    assert (
        url == "https://outlook.office.com/mail/deeplink/compose?to=&subject=D-1001%20BRACKET%2C%20MOUNTING"
    )


def test_a_subject_holding_a_token_is_not_filled_in_again():
    url = mail.webmail_url(OUTLOOK_WEB, "{to}", "{subject}")
    assert url.endswith("subject=%7Bto%7D%20%7Bsubject%7D")


@pytest.mark.parametrize(
    "template, words",
    [
        ("http://mail.example.com/compose?su={subject}", "it must start with https://"),
        ("javascript:alert(1)//{subject}", "it must start with https://"),
        ("ftp://mail.example.com/{subject}", "it must start with https://"),
        ("https://mail.example.com/compose?su={subject}&body={body}", "only {subject} and {to}"),
        ("https://mail.example.com/compose?su={Subject}", "only {subject} and {to}"),
        ("https://mail.example.com/compose?su={path}", "only {subject} and {to}"),
        ("https://mail.example.com/compose?su={subject", "braces"),
        ("https://mail.example.com/compose?su={}", "only {subject} and {to}"),
        ("https://mail.example.com/compose?su= {subject}", "space"),
        ("https://user:secret@mail.example.com/?su={subject}", "user or a password"),
        ("https://{subject}.example.com/", "after the host"),
        ("https:///compose?su={subject}", "a host"),
        ("https://mail.example.com:port/?su={subject}", "port"),
        ("https://mail.example.com/\n?su={subject}", "control characters"),
        ("https://mail.example.com/?su=" + "x" * 2000, "longer than 2000"),
        (42, "not text"),
    ],
)
def test_a_template_that_is_not_a_compose_address_is_refused(template, words):
    assert words in mail.template_problem(template)
    with pytest.raises(InvalidArgumentError) as info:
        mail.webmail_url(template, NUMBER, TITLE)
    assert info.value.detail == {"parameter": "template"}


def test_good_templates_pass():
    for template in (GMAIL, OUTLOOK_WEB, "https://mail.example.com:8443/compose#subject={subject}"):
        assert mail.template_problem(template) is None


def test_a_settings_refusal_keeps_only_its_reason():
    assert mail.refusal_reason("email.webmail_url: it must start with https://; the default is used") == (
        "it must start with https://"
    )
    assert mail.refusal_reason("people.people[1]: it is empty; the entry is left out") == "row 2: it is empty"
    assert mail.refusal_reason("something else") == "something else"


# --------------------------------------------------------------------------- what is asked and said
def test_a_drawing_not_released_is_asked_about_first():
    assert mail.preliminary_question("PRELIMINARY") == "This drawing is PRELIMINARY. Send it anyway?"
    assert mail.preliminary_question("CHECKED") == mail.PRELIMINARY_QUESTION
    assert mail.preliminary_question("RELEASED") is None
    with pytest.raises(InvalidArgumentError) as info:
        mail.preliminary_question("released")
    assert info.value.detail == {"parameter": "status"}


def test_the_status_lines():
    gmail = mail.webmail_url(GMAIL, NUMBER, TITLE)
    assert mail.webmail_status(gmail, "D-1001 A.pdf") == (
        "Gmail opened a new message in your browser. Drag the selected PDF from the folder window into it."
    )
    other = mail.webmail_url(OUTLOOK_WEB, NUMBER, TITLE)
    assert mail.webmail_status(other, "D-1001 A.pdf", selected=False) == (
        "Your webmail opened a new message in your browser. Drag D-1001 A.pdf from the folder window into it."
    )
    assert (
        mail.sent_status(OUTLOOK, "D-1001 A.pdf")
        == "The message with D-1001 A.pdf attached went to Outlook to send."
    )
    assert mail.show_status("D-1001 A.pdf") == "D-1001 A.pdf is selected in File Explorer."
    assert mail.show_status("D-1001 A.pdf", selected=False) == "The folder that holds D-1001 A.pdf is open."
    assert mail.fallback_status(THUNDERBIRD, "the PDF was not found", "Gmail opened.") == (
        "Thunderbird could not attach the PDF (the PDF was not found). Gmail opened."
    )


# --------------------------------------------------------------------------- the PDF and File Explorer
def test_only_a_plain_pdf_is_offered(tmp_path, pdf):
    assert mail.pdf_problem(pdf) is None
    for name in ("D-1001 A.ssdrw", "D-1001 A.dxf", "D-1001 A.SLDDRW"):
        other = tmp_path / name
        other.write_bytes(b"x")
        assert mail.pdf_problem(str(other)) == "only a drawing's PDF is ever sent"
    assert mail.pdf_problem(str(tmp_path / "gone.pdf")) == "it is not there any more"
    assert mail.pdf_problem("D-1001 A.pdf") == "its place is not known"
    assert mail.pdf_problem(None) == "its place is not known"
    assert mail.pdf_problem(str(tmp_path / "a\nb.pdf")) == "its place is not known"
    folder = tmp_path / "folder.pdf"
    folder.mkdir()
    assert mail.pdf_problem(str(folder)) == "it is not a file"


def test_a_link_to_a_pdf_is_not_offered(tmp_path, pdf):
    link = tmp_path / "link.pdf"
    try:
        os.symlink(pdf, link)
    except (OSError, NotImplementedError):
        pytest.skip("this system cannot make a symbolic link here")
    assert mail.pdf_problem(str(link)) == "it is a link, which SolidSeas never follows"


def test_explorer_gets_select_and_the_pdf_as_one_argument():
    command = mail.explorer_command(r"D:\Drawings\D-1001 A, rev 2.pdf", r"C:\Windows")
    assert command == r'"C:\Windows\explorer.exe" /select,"D:\Drawings\D-1001 A, rev 2.pdf"'
    assert mail.explorer_command("C:/Drawings/\u00d810.pdf", r"C:\Windows").endswith(
        r'/select,"C:\Drawings\Ø10.pdf"'
    )
    assert mail.explorer_command(r"\\server\share\D-1.pdf", r"C:\Windows").endswith(
        r'/select,"\\server\share\D-1.pdf"'
    )
    for bad in ("D-1.pdf", r"C:relative.pdf", 'C:\\a"b.pdf', "C:\\a\nb.pdf", None):
        with pytest.raises(InvalidArgumentError) as info:
            mail.explorer_command(bad, r"C:\Windows")
        assert info.value.detail == {"parameter": "path"}


def test_the_windows_folder_comes_from_the_system_root():
    assert mail.windows_folder({"SystemRoot": r"D:\WINDOWS"}) == r"D:\WINDOWS"
    assert mail.windows_folder({"SystemRoot": "relative"}) == "C:\\Windows"
    assert mail.windows_folder({}) == "C:\\Windows"


def test_the_guards_refuse_every_system_call(pdf):
    with pytest.raises(AssertionError, match="start File Explorer"):
        mail.show_pdf(pdf, windows=True)
    with pytest.raises(AssertionError, match="open a folder"):
        mail.show_pdf(pdf, windows=False)
    with pytest.raises(AssertionError, match="open a browser"):
        mail.email_pdf(pdf, NUMBER, TITLE, email(method="webmail"), show=lambda path: True)


def test_show_selects_the_pdf_on_windows_and_opens_its_folder_elsewhere(monkeypatch, pdf):
    shown = []
    monkeypatch.setattr(mail, "start_explorer", lambda path: shown.append(("explorer", path)))
    monkeypatch.setattr(mail, "open_folder", lambda folder: shown.append(("folder", folder)))
    assert mail.show_pdf(pdf, windows=True) is True
    assert mail.show_pdf(pdf, windows=False) is False
    assert shown == [("explorer", pdf), ("folder", os.path.dirname(pdf))]


# --------------------------------------------------------------------------- Email PDF
def test_just_show_me_the_file_shows_it_and_nothing_more(pdf):
    calls = Recorder()
    done = mail.email_pdf(
        pdf,
        NUMBER,
        TITLE,
        email(method="show"),
        show=calls.show,
        open_url=calls.open_url,
        attach=calls.attach,
    )
    assert done == mail.Delivery(mail.SHOW, "D-1001 A.pdf is selected in File Explorer.")
    assert calls.calls == [("show", pdf)]


def test_webmail_shows_the_pdf_then_opens_the_compose_page(pdf):
    calls = Recorder()
    done = mail.email_pdf(
        pdf,
        NUMBER,
        TITLE,
        drawing_settings.DrawingSettings(),
        show=calls.show,
        open_url=calls.open_url,
        windows=False,
    )
    url = "https://mail.google.com/mail/?view=cm&fs=1&su=D-1001%20BRACKET%2C%20MOUNTING"
    assert done == mail.Delivery(
        mail.WEBMAIL,
        "Gmail opened a new message in your browser. Drag the selected PDF from the folder window into it.",
        url,
    )
    assert calls.calls == [("show", pdf), ("open", url)]
    # Nothing of the PDF's place reaches the browser: not its folder, not its name.
    words = urllib.parse.unquote(done.url)
    assert "Drawings" not in words and ".pdf" not in words.lower() and "pytest" not in words


def test_webmail_without_prefilling_names_the_pdf_when_not_selected(pdf):
    calls = Recorder(selected=False)
    done = mail.email_pdf(
        pdf,
        NUMBER,
        TITLE,
        email(method="webmail", prefill_subject=False),
        show=calls.show,
        open_url=calls.open_url,
    )
    assert done.url == "https://mail.google.com/mail/?view=cm&fs=1&su="
    assert done.status.endswith("Drag D-1001 A.pdf from the folder window into it.")


def test_a_template_that_is_not_valid_opens_nothing(pdf):
    calls = Recorder()
    settings = drawing_settings.with_value(
        drawing_settings.DrawingSettings(), "email", "webmail_url", "https://mail.example.com/?su={Subject}"
    )
    with pytest.raises(InvalidArgumentError):
        mail.email_pdf(
            pdf,
            NUMBER,
            TITLE,
            settings,
            route=mail.Route(mail.WEBMAIL),
            show=calls.show,
            open_url=calls.open_url,
        )
    assert calls.calls == []


def test_only_a_pdf_is_ever_sent(tmp_path):
    drawing = tmp_path / "D-1001 A.ssdrw"
    drawing.write_bytes(b"{}")
    calls = Recorder()
    with pytest.raises(InvalidArgumentError) as info:
        mail.email_pdf(str(drawing), NUMBER, TITLE, email(method="show"), show=calls.show)
    assert info.value.detail == {"parameter": "pdf"} and calls.calls == []


def test_the_attach_route_gets_the_pdf_its_name_and_the_subject(pdf):
    calls = Recorder()
    route = mail.Route(mail.ATTACH, client=OUTLOOK)
    done = mail.email_pdf(
        pdf,
        NUMBER,
        TITLE,
        email(),
        route=route,
        attach=calls.attach,
        show=calls.show,
        open_url=calls.open_url,
    )
    assert done == mail.Delivery(
        mail.ATTACH, "The message with D-1001 A.pdf attached went to Outlook to send."
    )
    assert calls.calls == [("attach", pdf, "D-1001 A.pdf", "D-1001 BRACKET, MOUNTING")]
    calls.calls.clear()
    mail.email_pdf(
        pdf, NUMBER, TITLE, email(prefill_subject=False), route=route, attach=calls.attach, show=calls.show
    )
    assert calls.calls == [("attach", pdf, "D-1001 A.pdf", "")]


@pytest.mark.parametrize(
    "result",
    [mailproc.AttachResult(1), mailproc.AttachResult(None, cancelled=True)],
    ids=["closed", "cancelled"],
)
def test_closing_the_compose_window_says_and_opens_nothing(pdf, result):
    calls = Recorder()
    route = mail.Route(mail.ATTACH, client=THUNDERBIRD)
    done = mail.email_pdf(
        pdf, NUMBER, TITLE, email(), route=route, attached=result, show=calls.show, open_url=calls.open_url
    )
    assert done == mail.Delivery(mail.NOTHING, "") and calls.calls == []


def test_an_attach_that_fails_falls_to_webmail_and_says_why(pdf):
    calls = Recorder()
    route = mail.Route(mail.ATTACH, client=OUTLOOK)
    failed = mailproc._result({"code": 2})
    done = mail.email_pdf(
        pdf, NUMBER, TITLE, email(), route=route, attached=failed, show=calls.show, open_url=calls.open_url
    )
    assert done.route == mail.WEBMAIL and calls.calls == [("show", pdf), ("open", done.url)]
    assert done.status == (
        "Outlook could not attach the PDF (the mail program reported a failure, Simple MAPI code 2). "
        "Gmail opened a new message in your browser. Drag the selected PDF from the folder window into it."
    )
    crashed = mail.email_pdf(
        pdf,
        NUMBER,
        TITLE,
        email(),
        route=route,
        attached=mailproc.AttachResult(None, mailproc.STOPPED),
        show=calls.show,
        open_url=calls.open_url,
    )
    assert crashed.status.startswith(f"Outlook could not attach the PDF ({mailproc.STOPPED}).")


# --------------------------------------------------------------------------- the attach route's child
def stub_sent(path, name, subject):
    return 0


def stub_closed(path, name, subject):
    return 1


def stub_failure(path, name, subject):
    return 2


def stub_crash(path, name, subject):
    os._exit(3)


def stub_hang(path, name, subject):
    time.sleep(60)
    return 0


def stub_raises(path, name, subject):
    raise RuntimeError("the library failed")


def stub_echo(path, name, subject):
    """0 when the child got the request the window sent, else 99."""
    good = os.path.isabs(path) and path.endswith("D-1001 A.pdf") and name == "D-1001 A.pdf"
    return 0 if good and subject == "D-1001 BRACKET, MOUNTING" else 99


@pytest.mark.parametrize(
    "stub, expected",
    [
        (stub_sent, mailproc.AttachResult(0)),
        (stub_closed, mailproc.AttachResult(1)),
        (stub_failure, mailproc.AttachResult(2, "the mail program reported a failure, Simple MAPI code 2")),
        (stub_echo, mailproc.AttachResult(0)),
        (stub_crash, mailproc.AttachResult(None, mailproc.STOPPED)),
        (stub_raises, mailproc.AttachResult(None, "the call failed (RuntimeError)")),
    ],
    ids=["sent", "closed", "failure", "request", "crash", "raises"],
)
def test_the_child_answers_with_the_return_code(pdf, stub, expected):
    assert mailproc.send_in_process(pdf, "D-1001 A.pdf", "D-1001 BRACKET, MOUNTING", send=stub) == expected


def test_a_child_that_does_not_answer_in_time_is_ended(pdf):
    start = time.monotonic()
    result = mailproc.send_in_process(pdf, "D-1001 A.pdf", time_limit=1.0, send=stub_hang)
    assert result == mailproc.AttachResult(
        None, "the mail program did not answer within 1 second, and the call was ended"
    )
    assert time.monotonic() - start < 20


def test_the_window_can_stop_waiting(pdf):
    start = time.monotonic()
    result = mailproc.send_in_process(
        pdf, "D-1001 A.pdf", send=stub_hang, cancelled=lambda: time.monotonic() - start > 0.5
    )
    assert result == mailproc.AttachResult(None, cancelled=True) and time.monotonic() - start < 20
    assert mailproc.send_in_process(pdf, "D-1001 A.pdf", send=stub_hang, cancelled=lambda: True) == (
        mailproc.AttachResult(None, cancelled=True)
    )


def test_the_child_refuses_a_request_that_is_not_a_pdf(tmp_path):
    result = mailproc.send_in_process("D-1001 A.pdf", "D-1001 A.pdf", send=stub_sent)
    assert result == mailproc.AttachResult(None, "the request's path is not a PDF's")


@pytest.mark.skipif(
    os.name == "nt", reason="the real Simple MAPI call is a check on the PC with the user present"
)
def test_outside_windows_the_route_is_not_available(pdf):
    assert mailproc.send_in_process(pdf, "D-1001 A.pdf") == mailproc.AttachResult(None, mailproc.UNAVAILABLE)


def test_answers_the_window_does_not_read_are_no_answer():
    for answer in (None, [], {}, {"code": True}, {"code": -1}, {"code": 1 << 40}, {"code": "0"}):
        assert mailproc._result(answer) == mailproc.AttachResult(None, mailproc.NO_ANSWER)
    assert mailproc._result({"unavailable": "no mapi32.dll"}) == mailproc.AttachResult(None, "no mapi32.dll")
    assert mailproc.code_text(26) == "the mail program does not support this"
    assert mailproc.code_text(77) == "Simple MAPI error 77"


def test_the_message_holds_the_pdf_alone_at_the_end():
    message, attachment = mailproc.build_message(
        r"C:\Drawings\D-1001 A.pdf", "D-1001 A.pdf", "D-1001 BRACKET"
    )
    assert message.nFileCount == 1 and message.nRecipCount == 0 and not message.lpRecips
    assert message.lpszSubject == "D-1001 BRACKET" and message.lpszNoteText is None
    assert message.lpFiles.contents.nPosition == 0xFFFFFFFF
    assert (
        attachment.lpszPathName == r"C:\Drawings\D-1001 A.pdf" and attachment.lpszFileName == "D-1001 A.pdf"
    )
    plain, _ = mailproc.build_message("C:\\D.pdf", "D.pdf", "", wide=False)
    assert plain.lpszSubject is None and plain.lpFiles.contents.lpszPathName == b"C:\\D.pdf"


def test_the_structures_have_mapi_h_layout():
    pointer = struct.calcsize("P")
    # Three ULONGs then three pointers; the message: a ULONG, five strings, then flags,
    # originator, recipients and files, each ULONG aligned to the pointer that follows.
    expected = (40, 96) if pointer == 8 else (24, 48)
    for file_desc, message in (
        (mailproc.MapiFileDescW, mailproc.MapiMessageW),
        (mailproc.MapiFileDesc, mailproc.MapiMessage),
    ):
        assert (ctypes.sizeof(file_desc), ctypes.sizeof(message)) == expected


def test_an_ascii_copy_is_named_plainly():
    assert mailproc._ascii_name("D-1001 A.pdf") == "D-1001 A.pdf"
    assert mailproc._ascii_name("\u00d810 Flansch f\u00fcr Welle.PDF") == "_10 Flansch f_r Welle.pdf"
    assert mailproc._ascii_name("\u00d8.pdf") == "_.pdf"
    assert mailproc._ascii_name("...pdf") == "drawing.pdf"
