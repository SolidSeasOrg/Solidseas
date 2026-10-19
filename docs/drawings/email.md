# Email PDF

The code this page describes is
`src/solidseas_app/viewer/mail.py`, `mailproc.py` and `drawingsettings.py`. The
design is `docs/DRAWINGS.md` section 15.5 (the user's answer to Q7: Gmail or other
webmail in a browser), 15.2 for the settings dialog and 18 for privacy. Everything
here is provisional until the first release.

SolidSeas never sends mail, never sees or stores a password, and opens no network
connection of its own for Email PDF. It hands the drawing's PDF, and only the PDF,
to the user's own mail program or webmail, which does the rest after the user
presses its Send.

## The three routes

Drawing Settings > Email > Method picks the route, and it is chosen before anything
is called (`mail.choose_route`).

**Automatic** (the default) attaches the PDF in the user's mail program when the
default Simple MAPI client is classic Outlook or Thunderbird and is really there, and
uses webmail otherwise. The check (`mail.mail_client`) reads the registry and nothing
else, never loads a library, and fails closed to webmail:

1. `HKCU\SOFTWARE\Clients\Mail` (default value) names the client; when the user's
   key names none, `HKLM\SOFTWARE\Clients\Mail` does. A user's key that names a
   client decides, even when that client is not there.
2. For `Microsoft Outlook`, classic Outlook's `OUTLOOK.EXE` must be found: through
   `App Paths\OUTLOOK.EXE` (the user's, then the machine's) or Office's install
   root (`SOFTWARE\Microsoft\Office\<16.0, 15.0, 14.0>\Outlook\InstallRoot`,
   `Path`), as an absolute path to a file named `OUTLOOK.EXE` that exists. New
   Outlook has no Simple MAPI, so a machine with only new Outlook gets webmail.
3. For `Mozilla Thunderbird`, its registered MAPI library
   (`SOFTWARE\Clients\Mail\Mozilla Thunderbird`, `DLLPath`) must be an absolute
   path to a `.dll` that exists.
4. Anything else is webmail: another client, no client, a value that is not text, a
   relative path, a reader that raises. Outside Windows, Automatic is webmail.

Each value is read from the registry's 64-bit view, then its 32-bit one
(`mail.registry_value`). On the user's PC today Automatic gives webmail, which is how
the user sends mail.

**Webmail** is webmail always. **Just show me the file** selects the PDF in File
Explorer and does nothing more.

### The attach route

Simple MAPI runs in a child process of its own (`mailproc.send_in_process`): a mail
program's library is loaded into the process that calls it and can crash or hang it,
and the packaged viewer would otherwise search its own bundle's libraries first. The
child:

- restores the default library search order (`SetDllDirectoryW(NULL)`) and loads
  `mapi32.dll` from the system folder by its full path;
- calls `MAPISendMailW` with `MAPI_DIALOG | MAPI_LOGON_UI`: the compose window opens
  with the PDF attached (a `MapiFileDescW` with `nPosition` -1, the full path and
  the file's name), the drawing number and title as the subject (none with
  pre-filling off), no body and no recipient, which the user types;
- when the wide function is missing or fails, calls `MAPISendMail` with a copy of
  the PDF under a plain ASCII name in a temporary folder of its own, removed when
  the call returns (a temporary folder whose own path is not ASCII gives up and
  keeps the first code);
- writes the return code to its pipe as JSON and exits.

The window waits on a worker thread, since the call blocks while the compose window
is open, for at most an hour (`mailproc.TIME_LIMIT`); then, or when the window
cancels, the child is ended. Return code 0 means the message went to the mail
program to send, and the status line says so; 1 means the user closed the compose
window, and nothing is said. Any other code, a child that ended without answering (a
crash), the time limit, or a system without Simple MAPI falls to the webmail route,
and the status line says why first: "Outlook could not attach the PDF (the mail
program reported a failure, Simple MAPI code 2). Gmail opened a new message ...".

The child is not put in a job object, unlike the mesh reader: a mail program that the
call starts (Outlook or Thunderbird, when not running) would join the job, take its
memory limit and priority, and be ended with it.

### The webmail route

The PDF is shown selected in File Explorer, then the compose page opens in the
default browser (`QDesktopServices.openUrl`, given the address only after it is
checked again as a strict `https://` URL). The status line says what to do next:
"Gmail opened a new message in your browser. Drag the selected PDF from the folder
window into it." For another webmail it says "Your webmail opened ...". Outside
Windows the PDF's folder is opened instead, and the line names the file to drag.

File Explorer gets its full path and one argument, `/select,` with the PDF's path in
quotation marks (`mail.explorer_command`), so neither a space nor a comma in a name
can split it; a Windows path cannot hold a quotation mark, and one that does is
refused, as are a relative path and a control character. It is started with no shell,
standard handles to nothing, and without the packaged viewer's environment and
library directory, as 3D Print starts a slicer.

## What reaches the browser

Only the compose address, built from the template the user saved
(`email.webmail_url`, Gmail's `https://mail.google.com/mail/?view=cm&fs=1&su={subject}`
by default):

- `{subject}` becomes the drawing number and the title, joined by a space, on one
  line, without control characters, at most 200 characters, and percent-encoded
  (`D-1001 BRACKET, MOUNTING & BASE #2` is
  `D-1001%20BRACKET%2C%20MOUNTING%20%26%20BASE%20%232`; other scripts go as UTF-8).
  With "Put the drawing number and title in the subject" off it is empty.
- `{to}` is always empty: SolidSeas knows no address.
- No path, folder or file name, company, customer, body or other field is ever put
  in it.

A template is checked when the settings are saved and again before it is used
(`mail.template_problem`): the settings' own check (`https://`, at most 2,000
characters, no control characters, `{subject}` and `{to}` its only tokens), and
further no other brace (a `{Subject}` or a stray `{`), no space, a host, no user name
or password before the host, the tokens after the host, and a port that is a number.

## Before anything is sent

Only a drawing's PDF is offered (`mail.pdf_problem`): an absolute path to a plain
file named `.pdf`, never a link, and never the `.ssdrw`, DXF or SLDDRW, which can
carry folder names. A drawing that is not RELEASED asks "This drawing is PRELIMINARY.
Send it anyway?" (`mail.preliminary_question`), and its stamped PDF is the one sent.
Making the PDF current first is the editor's part.

## How the window uses it

The viewer stage wires Email PDF; these modules are usable on their own:

1. `mail.preliminary_question(drawing.status)`, and the PDF made current.
2. `mail.choose_route(settings.email.method)` on the UI thread.
3. For the attach route, `mail.attach_pdf(pdf, name, subject)` on a worker thread.
4. `mail.email_pdf(pdf, number, title, settings, route=route, attached=result)` on
   the UI thread: it shows the file and opens the browser as the route says and
   returns a `Delivery` with the route taken, the status line and the address.

The system calls (`mail.start_explorer`, `mail.open_in_browser`, `mail.open_folder`)
are looked up when they are needed, so the tests and the self-test's dry run replace
them and start nothing.

## The Drawing Settings dialog

`drawingsettings.DrawingSettingsDialog` is Settings > Drawing Settings (15.2): a page
for each group of 7.2 (Company, People and Approvals, Standard and Units, Sheets,
Title Block, Tolerances, Geometric Tolerances, Printing, Notes, Materials and
Finishes, Default Views, Dimensioning, Files, Email, and Limits), with OK, Apply,
Cancel, and Restore Defaults for the page shown. `drawingsettings.PAGES` binds each
control to one setting, and a test checks that every setting has exactly one.

- OK and Apply check every value with `settings.with_value`, as loading the file
  checks it, and the webmail address with `mail.template_problem`. A value that
  fails is refused with its reason ("Tolerances > Angles, plus or minus (degrees):
  it is not a number"; a list entry by its row), its page is shown and marked, its
  control focused, and nothing is saved. Cancel discards what changed since the
  last Apply. Members a newer SolidSeas wrote are kept.
- The fallbacks loading needed are listed at the top until the settings are saved,
  and so are the first-use prompts (the unit for parts that state none, the
  company's name, the people who sign); the dialog opens on the first page that
  lacks one, or on the page asked for.
- The logo: Choose... reads the image through `QImage`, scales it to at most 1,200
  pixels on the long side, and makes an 8-bit RGB or RGBA (with alpha), non-interlaced
  PNG from its pixels alone, so no text, colour profile or other metadata of the
  source is carried over. An image that is still over 512 KiB is made smaller (900,
  600, then 400 pixels), and refused with the reason when even that is too large. It
  is written as `logo.png` beside `Drawing.json` when the settings are saved, never
  before, through a temporary file and a rename, and the settings record its
  SHA-256. Remove takes it out of the settings and removes the file on save.

Section 7.1 puts the logo at `Drawing\logo.png`; `settings.py` and this dialog put it
beside `Drawing.json`, as `settings.LOGO_NAME` says.

## Privacy (section 18)

- Email attaches or offers only the PDF, which holds no folder path or user name.
- A webmail address carries only the drawing number and title, or nothing with
  pre-filling off. It goes to the browser, not to a server of SolidSeas'.
- SolidSeas never handles a mail password; the mail program or webmail signs in.
- The registry is only read, and only the keys above.
- Company details, people and the logo live in the user's roaming settings and in the
  drawings that carry them. People are typed names; nothing is read from Windows,
  Office or SOLIDWORKS.

## Tests

`tests/test_viewer_drawing_mail.py` (no Qt): the route from a made-up registry for
each answer (no client, classic Outlook through App Paths and through the install
root, new Outlook, Thunderbird with and without its library, another client, the
user's key over the machine's, values of the wrong type and readers that raise); the
webmail address with spaces, `&`, `#`, commas and text outside ASCII, templates
refused (`http://`, other tokens, stray braces, a user before the host, a token in
the host); the status lines and the PRELIMINARY question; File Explorer's command
line; Email PDF through each route with stand-ins; and the attach route's child with
a stub for the library call (sent, closed, a failure code, the request it got, a
crash, an exception, the time limit, the window cancelling), plus `MAPI.H`'s
structure layout. An autouse fixture makes every system call fail the test.

`tests/test_viewer_drawing_settings.py`: the page table, the conversions and the
logo file without Qt; with PySide6 (offscreen), the dialog's round trip through the
file, refused values and their reasons, OK, Apply, Cancel and Restore Defaults,
first-use prompts, fallbacks, and the logo from images the test writes (scaled, RGBA
and RGB, metadata dropped, too large, not an image, a record that does not match).

## What needs the PC

With the user present (`docs/DRAWINGS.md` section 24, item 7):

- **Gmail's compose page.** Email PDF on the webmail route opens Gmail with the
  subject filled in (the default template's `view=cm&fs=1&su=` is marked
  **verify** in 15.5), File Explorer shows the PDF selected, and the PDF dragged
  into the message attaches. Try a drawing whose name holds a space and a comma, and
  a title outside ASCII.
- **Automatic on the PC** gives webmail (no classic Outlook or Thunderbird), from
  the real registry.
- **The attach route**, if a classic Outlook or Thunderbird is ever installed: the
  compose window opens in front with the PDF attached, Send gives code 0, closing it
  gives 1, and a mail program that is ended while the window is open falls to
  webmail. The child's real `MAPISendMailW` call, its ANSI fallback, and whether the
  compose window comes to the front are tested only there.
- **The packaged viewer**: the child process starts from the frozen executable,
  and File Explorer and the browser start without the bundle's environment.
