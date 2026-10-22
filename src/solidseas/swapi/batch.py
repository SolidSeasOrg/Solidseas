"""Batch conversion through SolidSeas' own SOLIDWORKS, on the bridge (Windows).

:func:`convert` starts a bridge, which starts a hidden ``SLDWORKS.exe`` of its
own inside a Job Object, and for each document: opens it read-only, writes one
copy per format with ``IModelDocExtension.SaveAs3`` and the Copy option, and
closes it. Every step is a request with its own timeout. When one runs out, the
bridge and that SOLIDWORKS are ended, the rest of that document is reported as
not attempted, and the next document gets a fresh bridge and SOLIDWORKS, up to
``max_restarts`` times. Nothing is ever written to a source document, and no
SOLIDWORKS option is changed, so a STEP file uses the application protocol the
account's SOLIDWORKS options name (the row records which).

Starting that SOLIDWORKS takes the foreground of the user's desktop for 6 to
7 s, so a long job the user did not start runs off-hours: given an
:class:`OffHours` window (02:00 to 07:00 local time by default), :func:`convert`
runs SOLIDWORKS only inside it. It starts SOLIDWORKS, the first time and after
a timeout, only when local time is inside the window, waiting otherwise, and it
looks again before every document it opens and every export it asks for: once
the window has closed it closes the document, ends that SOLIDWORKS through its
job and goes on in the next window. A SOLIDWORKS the user starts while
SolidSeas' instance runs alone would be the second session on the machine and
run without auto-recover, which is why the instance never runs on into the
day. A job the user starts runs at once, and to its end.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, fields
from pathlib import Path

from . import hkcu
from .bridge import (
    DEFAULT_SOLIDWORKS_EXE,
    MAX_TIMEOUT_S,
    Bridge,
    BridgeError,
    BridgeRequestError,
)

FORMATS: dict[str, str] = {
    "step": ".step",
    "x_t": ".x_t",
    "x_b": ".x_b",
    "stl": ".stl",
    "3mf": ".3mf",
    "gltf": ".gltf",
    "glb": ".glb",
}
DEFAULT_FORMATS = ("step", "x_t", "stl", "3mf")
DOCUMENT_SUFFIXES = (".sldprt", ".sldasm")
# Bridge error codes after which the SOLIDWORKS instance is not trusted with another request.
_FATAL = {"busy", "cancelled", "disconnected", "not_started", "timeout", "bridge_exited", "internal"}
# Start failures that starting again cannot get past: a person has to act first.
_NEEDS_A_PERSON = {"solidworks_not_activated"}
REPORT_COLUMNS = (
    "input", "status", "format", "output", "code", "errors", "warnings", "seconds", "step_ap", "message",
)


@dataclass(frozen=True)
class Timeouts:
    """Seconds each step may take before the bridge and its SOLIDWORKS are ended.

    Each is more than 0 and at most a day (``MAX_TIMEOUT_S``), the range the
    bridge accepts; anything else raises ``ValueError`` here, before a
    SOLIDWORKS is started for it.
    """

    start: float = 360.0
    open: float = 300.0
    export: float = 600.0
    close: float = 120.0
    exit: float = 180.0

    def __post_init__(self) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            finite = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            if not finite or not 0 < value <= MAX_TIMEOUT_S:
                raise ValueError(f"the {f.name} timeout must be more than 0 and at most {MAX_TIMEOUT_S:g} s")


@dataclass(frozen=True)
class OffHours:
    """The hours of the day, in local time, in which a batch job may start SolidSeas' own SOLIDWORKS.

    Starting it takes the foreground of the user's desktop for 6 to 7 s, so a
    long job that the user did not start runs in this window, 02:00 to 07:00 by
    default. ``start`` is in the window and ``end`` is not; a window may pass
    midnight (22:00 to 06:00). :meth:`parse` reads ``"HH:MM-HH:MM"``.
    """

    start: dt.time = dt.time(2, 0)
    end: dt.time = dt.time(7, 0)

    def __post_init__(self) -> None:
        for name in ("start", "end"):
            value = getattr(self, name)
            if not isinstance(value, dt.time) or value.tzinfo is not None:
                raise ValueError(f"the off-hours {name} must be a local time of day")
        if self.start == self.end:
            raise ValueError("the off-hours window must not be empty")

    @classmethod
    def parse(cls, text: str) -> OffHours:
        """A window written ``HH:MM-HH:MM``, such as ``02:00-07:00``."""
        m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*", text)
        if not m:
            raise ValueError(f"not a window of hours (HH:MM-HH:MM): {text!r}")
        h1, m1, h2, m2 = (int(g) for g in m.groups())
        if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59:
            raise ValueError(f"not a time of day: {text!r}")
        return cls(dt.time(h1, m1), dt.time(h2, m2))

    def contains(self, moment: dt.datetime) -> bool:
        t = moment.time().replace(tzinfo=None)
        if self.start < self.end:
            return self.start <= t < self.end
        return t >= self.start or t < self.end

    def seconds_until(self, moment: dt.datetime) -> float:
        """Seconds from ``moment`` until the window next opens; 0 inside it."""
        if self.contains(moment):
            return 0.0
        opens = moment.replace(hour=self.start.hour, minute=self.start.minute, second=0, microsecond=0)
        if opens <= moment:
            opens += dt.timedelta(days=1)
        return (opens - moment).total_seconds()

    def __str__(self) -> str:
        return f"{self.start:%H:%M} to {self.end:%H:%M}"


# The clock and the sleep the off-hours wait uses; tests replace them.
_now = dt.datetime.now
_sleep = time.sleep
_WAIT_STEP_S = 60.0  # the clock is read again at least this often, so a clock change is noticed
# How often SolidSeas asks again to end its SOLIDWORKS while that shows documents SolidSeas did not open.
_FOREIGN_POLL_S = 30.0
# What puts back the registry values each SOLIDWORKS of SolidSeas' changed (hkcu), or None where
# none is started; tests replace it.
_registry_restore: Callable[[], hkcu.RegistryRestore | None] = hkcu.RegistryRestore.for_this_system


def _wait_for(window: OffHours, say: Callable[[str], None]) -> None:
    """Return once local time is inside the window, sleeping until it is."""
    told = False
    while True:
        now = _now()
        wait = window.seconds_until(now)
        if wait <= 0:
            if told:
                say(f"the off-hours window ({window}) has begun")
            return
        if not told:
            hours, rest = divmod(int(wait + 59) // 60, 60)
            say(f"waiting {hours} h {rest:02d} min for the off-hours window ({window}) "
                "to start SolidSeas' SOLIDWORKS")
            told = True
        _sleep(min(wait, _WAIT_STEP_S))


def _ended_message(ended: dict) -> str:
    """A log line for the answer to ``exit_solidworks``."""
    text = f"SolidSeas' SOLIDWORKS ended: {ended.get('ended')}, PID {ended.get('pid')}"
    if "exit_code" in ended:
        text += f", exit code {ended.get('exit_code')}"
    if ended.get("documents_open"):
        text += f"; {ended.get('documents_open')} document(s) it had not opened went with it, unsaved"
    return text


def _foreign_message(details: object) -> str:
    """A log line for the bridge's refusal to end SolidSeas' SOLIDWORKS while it shows documents
    SolidSeas did not open (``foreign_documents``)."""
    titles = details.get("documents") if isinstance(details, dict) else None
    titles = [str(t) for t in titles] if isinstance(titles, list) else []
    count = len(titles)
    what = "1 document" if count == 1 else f"{count} documents" if count else "documents"
    named = ""
    if titles:
        named = " (" + ", ".join(titles[:5]) + (", and more" if count > 5 else "") + ")"
    one = count == 1
    return (f"SolidSeas' SOLIDWORKS has {what} open that SolidSeas did not open{named}: it is not ended "
            f"but shown on the screen, so you can save and close {'it' if one else 'them'} there. "
            f"SolidSeas ends its SOLIDWORKS once {'it is' if one else 'they are'} closed.")


def _window_message(event: dict) -> str | None:
    """A log line for a window event of the bridge, or None for any other event."""
    if not isinstance(event, dict) or event.get("event") != "window":
        return None
    pid = event.get("pid")
    if event.get("action") == "hidden":
        again = " again" if event.get("again") else ""
        return f"hid{again} the journal file message box of SolidSeas' SOLIDWORKS (PID {pid})"
    title = str(event.get("title") or "")
    text = str(event.get("text") or "")
    if event.get("kind") == "activation":
        return (f"SOLIDWORKS Product Activation (PID {pid}) is asking: {title}: {text}"
                "; SolidSeas never answers it, and SOLIDWORKS does not start until it is activated")
    process = str(event.get("process") or "")
    whose = (f"{process} (PID {pid}), which SolidSeas' SOLIDWORKS started,"
             if process and process.lower() != "sldworks.exe" else f"SolidSeas' SOLIDWORKS (PID {pid})")
    return (f"{whose} shows a dialog, left as it is: {title}: {text}"
            "; a request it holds up ends at its timeout")


@dataclass(frozen=True)
class ConversionRow:
    """One line of a conversion report.

    ``status`` is ``ok``, ``fail`` or ``skip``; ``format`` is a format name, or
    ``*`` for a row about the whole document; ``code`` is the bridge's error
    code for a failure; ``errors`` and ``warnings`` are SOLIDWORKS' own codes
    from ``OpenDoc6`` or ``SaveAs3``.
    """

    input: str
    status: str
    format: str
    output: str = ""
    code: str = ""
    errors: int = 0
    warnings: int = 0
    seconds: float = 0.0
    message: str = ""
    step_ap: int | None = None


def find_documents(paths: Iterable[str | os.PathLike], *, recurse: bool = False) -> list[Path]:
    """The ``.sldprt`` and ``.sldasm`` files named, or found in the folders named (lock files left out)."""
    found: list[Path] = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            walker = path.rglob("*") if recurse else path.iterdir()
            for f in sorted(walker):
                if f.is_file() and f.suffix.lower() in DOCUMENT_SUFFIXES and not f.name.startswith("~$"):
                    found.append(f)
        elif path.is_file():
            if path.suffix.lower() not in DOCUMENT_SUFFIXES:
                raise ValueError(f"not a .sldprt or .sldasm file: {path}")
            found.append(path)
        else:
            raise FileNotFoundError(f"no such file or folder: {path}")
    unique: dict[str, Path] = {}
    for f in found:
        unique.setdefault(os.path.normcase(str(f.resolve())), f.resolve())
    return list(unique.values())


def _message(e: BridgeError) -> str:
    """The error's text, with the names of SOLIDWORKS' error bits when the bridge gave them."""
    details = e.details if isinstance(e.details, dict) else {}
    names = details.get("error_names") or []
    return f"{e} ({', '.join(str(n) for n in names)})" if names else str(e)


def _network(path: object) -> bool:
    r"""A network path (``\\server\share\...``), which the bridge takes only when a request allows it.

    The documents and the output folder the user names may be on a share, so
    batch conversion allows it for exactly those paths.
    """
    text = str(path)
    return text[:2] in ("\\\\", "//")


def _within(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False


class _Session:
    """One bridge and the SOLIDWORKS it started.

    The registry values that SOLIDWORKS changes are read just before it starts and put back
    once it has ended, however it ended, when no other SOLIDWORKS ran meanwhile
    (:mod:`.hkcu`); the log says what was put back, or why nothing was.
    """

    def __init__(
        self,
        factory: Callable[[], Bridge],
        solidworks_exe: Path,
        timeouts: Timeouts,
        say: Callable[[str], None] = lambda _msg: None,
    ) -> None:
        self.say = say
        self.info: dict = {}
        self.bridge = factory()
        if self.bridge.on_event is None:
            # The journal file message box the bridge hid, and any dialog it left, go to the log.
            def on_event(event: dict) -> None:
                line = _window_message(event)
                if line is not None:
                    say(line)

            self.bridge.on_event = on_event
        self.restore = self._begin_restore()
        try:
            self.info = self.bridge.request(
                "start_solidworks", {"exe": str(solidworks_exe)}, timeout=timeouts.start
            )
        except BaseException:
            try:
                self.bridge.kill("SOLIDWORKS did not start")
            finally:
                self._put_back()
            raise

    def _begin_restore(self) -> hkcu.RegistryRestore | None:
        """Read the registry values SOLIDWORKS may change, and watch for any other SOLIDWORKS."""
        try:
            restore = _registry_restore()
            if restore is not None:
                restore.begin()
            return restore
        except Exception as e:  # the conversion goes on; nothing is put back afterwards
            self.say(f"could not read the registry values SolidSeas' SOLIDWORKS may change ({e}); "
                     "they will not be put back after it")
            return None

    def _put_back(self) -> None:
        """Put back what SOLIDWORKS changed in the registry, once, now that it has ended."""
        restore, self.restore = self.restore, None
        if restore is None:
            return
        try:
            outcome = restore.finish(self.info.get("pid"))
        except Exception as e:
            self.say(f"could not put back the registry values SolidSeas' SOLIDWORKS changed ({e})")
            return
        line = outcome.message()
        if line is not None:
            self.say(line)

    def end(self, timeouts: Timeouts) -> dict | None:
        """End SOLIDWORKS through its job (``exit_solidworks``), then the bridge, and log how it ended.

        While SOLIDWORKS shows documents SolidSeas did not open (a person opened
        them in it), the bridge does not end it but shows it on the screen
        (``foreign_documents``). Then this says so, asks again every
        :data:`_FOREIGN_POLL_S` seconds for as long as it takes, a busy
        SOLIDWORKS included, and ends it once they are closed.

        Returns the bridge's answer, or None when it gave none; closing the
        bridge then ends the job, and SOLIDWORKS with it, all the same.
        """
        ended = None
        try:
            try:
                if self.bridge.alive:
                    ended = self._exit(timeouts)
            except BridgeError as e:
                self.say(f"exit_solidworks failed ({e}); closing the bridge ends SOLIDWORKS through its job")
            finally:
                self.bridge.close(timeout=timeouts.exit)
            if isinstance(ended, dict):
                self.say(_ended_message(ended))
        finally:
            self._put_back()
        return ended

    def _exit(self, timeouts: Timeouts) -> dict:
        """``exit_solidworks``, asked again until no document SolidSeas did not open is left."""
        waiting = False
        while True:
            try:
                ended = self.bridge.request("exit_solidworks", timeout=timeouts.exit)
            except BridgeRequestError as e:
                if e.code == "foreign_documents":
                    if not waiting:
                        self.say(_foreign_message(e.details))
                        waiting = True
                elif not (waiting and e.code == "busy"):  # busy: someone is working in it
                    raise
                _sleep(_FOREIGN_POLL_S)
                continue
            if waiting:
                self.say("the documents SolidSeas did not open are closed; ending SolidSeas' SOLIDWORKS")
            return ended

    def kill(self, reason: str) -> None:
        try:
            self.bridge.kill(reason)
        finally:
            self._put_back()


def convert(
    inputs: Iterable[str | os.PathLike],
    output_folder: str | os.PathLike,
    formats: Iterable[str] = DEFAULT_FORMATS,
    *,
    recurse: bool = False,
    overwrite: bool = False,
    allow_source_folder: bool = False,
    solidworks_exe: str | os.PathLike | None = None,
    bridge_exe: str | os.PathLike | None = None,
    timeouts: Timeouts | None = None,
    max_restarts: int = 3,
    log: Callable[[str], None] | None = None,
    bridge_factory: Callable[[], Bridge] | None = None,
    off_hours: OffHours | None = None,
) -> list[ConversionRow]:
    """Convert documents with SolidSeas' own SOLIDWORKS and return one row per document and format.

    ``output_folder`` may not be, or lie in, the folder of an input document
    unless ``allow_source_folder``; an existing output is kept (a ``skip`` row)
    unless ``overwrite``. Raises ``ValueError`` for an unknown format or a
    refused output folder and ``FileNotFoundError`` for a missing input, before
    anything starts; everything after that is reported in the rows.

    ``off_hours``, for a job the user did not start, is the window in which
    SOLIDWORKS may run: each start, the first and any after a timeout, waits
    for it, and once it has closed, before the next document or export, the
    document in hand is closed, SOLIDWORKS is ended through its job and the
    work goes on, with that document's remaining formats, in the next window.
    That pause is not a restart. ``None``, for a job the user started, starts
    SOLIDWORKS at once and runs to the end.

    A start that only a person can get past (``solidworks_not_activated``: the
    SOLIDWORKS on this PC needs product activation) is not tried again in the
    run; the documents after it are not attempted, and their rows say why.

    When the work is done, or the off-hours window closes, SOLIDWORKS is not
    ended while it shows a document SolidSeas did not open, which a person
    opened in it: it is shown on the screen instead, the log says so, and it is
    ended once they have closed the document, however long that takes. A
    timeout, or a failure after which SOLIDWORKS is not trusted, still ends it
    at once.
    """
    t = timeouts or Timeouts()
    wanted = []
    for f in formats:
        name = str(f).strip().lower()
        if name not in FORMATS:
            raise ValueError(f"unknown format {f!r}; known: {', '.join(FORMATS)}")
        if name not in wanted:
            wanted.append(name)
    if not wanted:
        raise ValueError("no format asked for")
    docs = find_documents(inputs, recurse=recurse)
    out = Path(output_folder).resolve()
    if not allow_source_folder:
        for d in docs:
            if _within(out, d.parent):
                raise ValueError(
                    f"refusing to write into a folder that holds a source document ({d.parent}); "
                    "choose another output folder or allow it explicitly"
                )
    out.mkdir(parents=True, exist_ok=True)
    exe = Path(solidworks_exe) if solidworks_exe else DEFAULT_SOLIDWORKS_EXE
    factory = bridge_factory or (lambda: Bridge(bridge_exe, solidworks_exe=exe))
    say = log or (lambda _msg: None)

    rows: list[ConversionRow] = []
    written: set[str] = set()
    session: _Session | None = None
    restarts = 0
    # Set when SOLIDWORKS cannot start until a person acts (it needs product activation):
    # starting it again for each document would only show its wizard again.
    blocked: str | None = None

    def lose_session(reason: str) -> None:
        nonlocal session, restarts
        if session is not None:
            session.kill(reason)
            session = None
        restarts += 1
        say(f"SOLIDWORKS ended: {reason}")

    def closed() -> bool:
        """The off-hours window, when there is one, has closed."""
        return off_hours is not None and not off_hours.contains(_now())

    try:
        for doc in docs:
            name = str(doc)
            todo: list[tuple[str, Path]] = []
            for fmt in wanted:
                target = out / (doc.stem + FORMATS[fmt])
                key = os.path.normcase(str(target))
                if key in written:
                    rows.append(ConversionRow(name, "fail", fmt, str(target), "refused", message=(
                        "another document in this run already wrote this output")))
                elif _output_exists(target, fmt) and not overwrite:
                    rows.append(ConversionRow(name, "skip", fmt, str(target), message="output exists"))
                else:
                    todo.append((fmt, target))
            # More than one round only when the off-hours window closes during the document.
            while todo:
                if session is not None and closed():
                    say(f"the off-hours window ({off_hours}) has closed; ending SolidSeas' SOLIDWORKS "
                        "until it opens again")
                    session.end(t)
                    session = None
                if session is None:
                    if blocked is not None:
                        rows.append(ConversionRow(name, "fail", "*", code="not_attempted", message=(
                            f"not attempted: {blocked}")))
                        break
                    if restarts > max_restarts:
                        rows.append(ConversionRow(name, "fail", "*", code="not_attempted", message=(
                            f"not attempted: SOLIDWORKS was restarted {restarts} times")))
                        break
                    if off_hours is not None:
                        _wait_for(off_hours, say)
                    try:
                        session = _Session(factory, exe, t, say)
                        info = session.info
                        say(f"SOLIDWORKS {info.get('revision')} started, PID {info.get('pid')}")
                    except BridgeError as e:
                        rows.append(ConversionRow(
                            name, "fail", "*", code=e.code, message=f"SOLIDWORKS did not start: {e}"))
                        session = None
                        restarts += 1
                        if e.code in _NEEDS_A_PERSON:
                            blocked = "SOLIDWORKS needs product activation on this PC"
                            say(f"{blocked}; not starting it again in this run")
                        break
                started = time.monotonic()
                try:
                    opened = session.bridge.request(
                        "open_document",
                        {"path": name, "read_only": True, "allow_network": _network(name)},
                        timeout=t.open,
                    )
                except BridgeError as e:
                    details = e.details if isinstance(e.details, dict) else {}
                    rows.append(ConversionRow(
                        name, "fail", "*", code=e.code, errors=int(details.get("errors") or 0),
                        warnings=int(details.get("warnings") or 0),
                        seconds=round(time.monotonic() - started, 3), message=_message(e)))
                    if not isinstance(e, BridgeRequestError) or e.code in _FATAL:
                        lose_session(str(e))
                    break
                handle = opened["doc"]
                broken = False
                later: list[tuple[str, Path]] = []
                for i, (fmt, target) in enumerate(todo):
                    if broken:
                        rows.append(ConversionRow(name, "fail", fmt, str(target), "not_attempted", message=(
                            "not attempted: SOLIDWORKS was ended after the failure above")))
                        continue
                    if i > 0 and closed():
                        later = todo[i:]  # the rest waits for the next window
                        break
                    started = time.monotonic()
                    try:
                        r = session.bridge.request(
                            "save_copy",
                            {"doc": handle, "path": str(target), "overwrite": overwrite,
                             "allow_network": _network(target)},
                            timeout=t.export,
                        )
                    except BridgeError as e:
                        details = e.details if isinstance(e.details, dict) else {}
                        rows.append(ConversionRow(
                            name, "fail", fmt, str(target), e.code, int(details.get("errors") or 0),
                            int(details.get("warnings") or 0), round(time.monotonic() - started, 3),
                            _message(e)))
                        if not isinstance(e, BridgeRequestError) or e.code in _FATAL:
                            broken = True
                            lose_session(str(e))
                        continue
                    written.add(os.path.normcase(str(target)))
                    rows.append(ConversionRow(
                        name, "ok", fmt, str(r.get("path") or target), "", int(r.get("errors") or 0),
                        int(r.get("warnings") or 0),
                        round(time.monotonic() - started, 3), step_ap=r.get("step_ap")))
                    say(f"{doc.name} {fmt} ok")
                if broken:
                    break
                try:
                    session.bridge.request("close_document", {"doc": handle}, timeout=t.close)
                except BridgeError as e:
                    lose_session(f"close_document: {e}")
                todo = later
    finally:
        if session is not None:
            session.end(t)
    return rows


def _output_exists(target: Path, fmt: str) -> bool:
    """Whether ``target`` is there already. SOLIDWORKS writes a glTF into a folder named after
    it (``out/part/part.gltf`` with its ``.bin``, the name lowercased), so for glTF that folder
    counts as the output."""
    if target.exists():
        return True
    if fmt != "gltf" or not target.parent.is_dir():
        return False
    stem = target.stem.lower()
    return any(p.is_dir() and p.name.lower() == stem for p in target.parent.iterdir())


def _cell(value: object) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\t", " ").replace("\r", " ").replace("\n", " ")
    # A spreadsheet must never run a value as a formula.
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


def write_report(rows: Iterable[ConversionRow], path: str | os.PathLike, *, overwrite: bool = False) -> Path:
    """Write the rows as a tab-separated report with a header line."""
    target = Path(path)
    if target.exists() and not overwrite:
        raise FileExistsError(f"{target} exists")
    lines = ["\t".join(REPORT_COLUMNS)]
    for r in rows:
        lines.append("\t".join(_cell(getattr(r, c)) for c in REPORT_COLUMNS))
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target
