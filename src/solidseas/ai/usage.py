"""Usage, and the token and cost budgets that are enforced, not only checked.

Usage is kept in monthly buckets (calendar months in UTC) in ``usage.json``, in
``%LOCALAPPDATA%\\SolidSeas`` on Windows (the folder ``SOLIDSEAS_CACHE_DIR``
replaces, as for the catalogs). Each bucket counts calls, input and output
tokens and cost, in total and per provider, and the file keeps the last
:data:`KEEP_MONTHS` months.

Two SolidSeas windows can record at once without losing an increment: every
read-modify-write holds a lock on ``usage.json.lock`` (``msvcrt.locking`` on
Windows, ``fcntl.flock`` elsewhere) and replaces the file through a temporary
file beside it. Recording never raises into the call path: a failure is logged
and the call's result stands.

Before every call, :func:`reserve` works out the largest output the budgets
leave: the request and the model summary are capped first (by the prompt
builders), the input is estimated from the prompt, and the call is refused
when the input plus :data:`MIN_OUTPUT_TOKENS` does not fit. The output cap
sent with the call is then no larger than the tokens left in the month and,
in Automatic mode, in the run, and no larger than what the cost budget's
remainder pays for at the configured prices. A cost budget with no prices set
refuses every cloud call (it cannot be checked, so it is not assumed to pass).
The monthly budgets apply to cloud providers; Ollama runs on this machine and
is only counted. The run budget applies to every provider.

The check and the hold are one step. :func:`reserve` sets the input estimate
plus the output cap aside, in the run's budget and, for a cloud provider, in
``usage.json`` under the same lock the check read it under, so calls in
flight at once (in one window or in two) cannot each be granted the whole
remainder. The call ends its :class:`Hold` with the usage it reported, which
replaces what was held, or gives the hold back when the request never reached
the provider. A hold left by a window that closed mid-call lapses after
:data:`HOLD_SECONDS`, longer than any call can last. :meth:`UsageLedger.allow`
makes the same check without holding anything.

A usage file that is not valid JSON is set aside as ``usage.damaged.json`` and
a new month starts from zero; one that cannot be read refuses calls until it
can, because the budget cannot be checked.
"""

from __future__ import annotations

import datetime
import json
import logging
import math
import os
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .errors import BudgetExceededError, InvalidSettingError

log = logging.getLogger("solidseas.ai")

FILE_NAME = "usage.json"
VERSION = 1
KEEP_MONTHS = 24
MIN_OUTPUT_TOKENS = 256
DEFAULT_MONTHLY_TOKENS = 2_000_000
DEFAULT_RUN_TOKENS = 30_000
MAX_FILE_BYTES = 1024 * 1024
HOLD_SECONDS = 600  # longer than any call: four tries of 65 seconds and three 30-second waits
MAX_HOLDS = 64
_MICRO = 1_000_000


def data_dir() -> str:
    """Where SolidSeas keeps its own files (see the module notes). Nothing is made."""
    env = os.environ.get("SOLIDSEAS_CACHE_DIR")
    if env:
        return os.path.abspath(env)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return os.path.join(base, "SolidSeas")
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "solidseas")


def default_path() -> str:
    return os.path.join(data_dir(), FILE_NAME)


def estimate_tokens(text: str) -> int:
    """A deliberately high estimate of the tokens in ``text``: one per three characters,
    plus a little for the message framing. Used only for the checks before a call."""
    return math.ceil(len(text) / 3) + 16


def estimate_image_tokens(width: int, height: int) -> int:
    """A deliberately high estimate of the tokens a picture of ``width`` by ``height``
    pixels costs: one per 750 pixels, as Anthropic counts, which is more than the other
    providers charge for the same picture, plus the framing."""
    return math.ceil(width * height / 750) + 100


def estimate_prompt_tokens(prompt: Any) -> int:
    """:func:`estimate_tokens` of a prompt's system and user parts plus
    :func:`estimate_image_tokens` of each picture it sends."""
    return (
        estimate_tokens(prompt.system)
        + estimate_tokens(prompt.user)
        + sum(estimate_image_tokens(i.width, i.height) for i in getattr(prompt, "images", ()))
    )


@dataclass(frozen=True)
class Pricing:
    """US dollars per million input and output tokens, as the person set them for the model."""

    input_per_mtok: float
    output_per_mtok: float

    def __post_init__(self) -> None:
        for name in ("input_per_mtok", "output_per_mtok"):
            v = getattr(self, name)
            if type(v) not in (int, float) or not (0 <= v <= 10_000):
                raise InvalidSettingError(
                    f"A price per million tokens is a number from 0 to 10,000 ({name})."
                )

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input_per_mtok + output_tokens * self.output_per_mtok) / _MICRO


@dataclass(frozen=True)
class Budget:
    """The monthly limits: tokens (input plus output) and, when set, dollars."""

    monthly_tokens: int = DEFAULT_MONTHLY_TOKENS
    monthly_cost: float | None = None
    pricing: Pricing | None = None

    def __post_init__(self) -> None:
        if type(self.monthly_tokens) is not int or not (0 <= self.monthly_tokens <= 10**10):
            raise InvalidSettingError("The monthly token budget is a whole number from 0 to 10,000,000,000.")
        if self.monthly_cost is not None and (
            type(self.monthly_cost) not in (int, float) or not (0 <= self.monthly_cost <= 1_000_000)
        ):
            raise InvalidSettingError("The monthly cost budget is a number of dollars from 0 to 1,000,000.")


class RunBudget:
    """The token budget of one Automatic run (30,000 by default), shared by its calls.
    ``held`` is what calls in flight have set aside (:func:`reserve`); ``remaining``
    leaves it out."""

    def __init__(self, limit: int = DEFAULT_RUN_TOKENS) -> None:
        if type(limit) is not int or not (0 <= limit <= 1_000_000):
            raise InvalidSettingError("A run's token budget is a whole number from 0 to 1,000,000.")
        self.limit = limit
        self._used = 0
        self._held = 0
        self._lock = threading.Lock()

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    @property
    def held(self) -> int:
        with self._lock:
            return self._held

    @property
    def remaining(self) -> int:
        with self._lock:
            return max(0, self.limit - self._used - self._held)

    def spend(self, tokens: int) -> None:
        with self._lock:
            self._used += max(0, int(tokens))

    def hold(self, input_tokens: int, output_cap: int) -> int:
        """Check and hold in one step: the output cap :func:`check_run` would give, with the
        input plus that cap set aside until :meth:`settle`. Raises
        :class:`BudgetExceededError`, holding nothing."""
        with self._lock:
            granted = _run_cap(self, self.limit - self._used - self._held, input_tokens, output_cap)
            self._held += input_tokens + granted
            return granted

    def settle(self, held: int, spent: int) -> None:
        """Give back ``held`` tokens set aside by :meth:`hold` and count ``spent``."""
        with self._lock:
            self._held = max(0, self._held - max(0, int(held)))
            self._used += max(0, int(spent))


@dataclass(frozen=True)
class MonthUsage:
    month: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def check_run(run: RunBudget, input_tokens: int, output_cap: int) -> int:
    """The largest output an Automatic run's budget leaves for a call, at most ``output_cap``.
    Raises :class:`BudgetExceededError` when that is less than :data:`MIN_OUTPUT_TOKENS`."""
    return _run_cap(run, run.remaining, input_tokens, output_cap)


def _run_cap(run: RunBudget, remaining: int, input_tokens: int, output_cap: int) -> int:
    left = remaining - input_tokens
    if left < MIN_OUTPUT_TOKENS:
        raise BudgetExceededError(
            f"This run's token budget ({run.limit:,}) does not leave room for this request.",
            detail={"limit": run.limit, "usage": run._used},
        )
    return min(output_cap, left)


def month_key(now: float | None = None) -> str:
    when = datetime.datetime.fromtimestamp(time.time() if now is None else now, tz=datetime.UTC)
    return f"{when.year:04d}-{when.month:02d}"


class _FileLock:
    """An exclusive lock on ``path`` held across processes (blocking, with a bound)."""

    def __init__(self, path: str, timeout: float = 10.0) -> None:
        self.path = path
        self.timeout = timeout
        self._fd: int | None = None

    def __enter__(self) -> _FileLock:
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        fd = os.open(self.path, flags, 0o600)
        end = time.monotonic() + self.timeout
        try:
            while True:
                try:
                    if sys.platform == "win32":
                        import msvcrt

                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= end:
                        raise TimeoutError("the usage file stayed locked") from None
                    time.sleep(0.01)
        except BaseException:
            os.close(fd)
            raise
        self._fd = fd
        return self

    def __exit__(self, *exc: Any) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


def _empty() -> dict[str, Any]:
    return {"version": VERSION, "months": {}, "holds": {}}


def _clean_bucket(raw: Any) -> dict[str, int]:
    out = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_micro_usd": 0}
    if isinstance(raw, dict):
        for k in out:
            v = raw.get(k)
            if type(v) is int and 0 <= v < 2**62:
                out[k] = v
    return out


def _clean_holds(raw: Any) -> dict[str, dict[str, int]]:
    holds: dict[str, dict[str, int]] = {}
    if not isinstance(raw, dict):
        return holds
    for key, h in raw.items():
        if len(holds) >= MAX_HOLDS:
            break
        if not (isinstance(key, str) and 0 < len(key) <= 32 and key.isascii() and key.isalnum()):
            continue
        if not isinstance(h, dict):
            continue
        values = [h.get("tokens"), h.get("cost_micro_usd"), h.get("until")]
        if all(type(v) is int and 0 <= v < 2**62 for v in values):
            holds[key] = {"tokens": values[0], "cost_micro_usd": values[1], "until": values[2]}
    return holds


def _live_holds(data: dict[str, Any], now: float) -> dict[str, dict[str, int]]:
    """The holds that have not lapsed. One that claims to last longer than
    :data:`HOLD_SECONDS` from now (a clock set back, or a file edited) is dropped."""
    return {k: h for k, h in data["holds"].items() if now < h["until"] <= now + HOLD_SECONDS}


def _clean(data: Any) -> dict[str, Any] | None:
    """The usage data in its known shape, or None when it is not usage data at all."""
    if not isinstance(data, dict) or not isinstance(data.get("months"), dict):
        return None
    months: dict[str, Any] = {}
    for key, raw in data["months"].items():
        if not (isinstance(key, str) and len(key) == 7 and key[4] == "-" and key.replace("-", "").isdigit()):
            continue
        bucket = _clean_bucket(raw)
        providers = {}
        if isinstance(raw, dict) and isinstance(raw.get("providers"), dict):
            for name, p in raw["providers"].items():
                if isinstance(name, str) and 0 < len(name) <= 32 and name.isascii():
                    providers[name] = _clean_bucket(p)
        bucket["providers"] = providers
        months[key] = bucket
    return {"version": VERSION, "months": months, "holds": _clean_holds(data.get("holds"))}


class UsageLedger:
    """The usage file and the monthly budget checks. ``path`` None means the default file;
    ``clock`` gives the time (tests)."""

    def __init__(
        self,
        path: str | None = None,
        *,
        budget: Budget | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = os.path.abspath(path) if path else default_path()
        self.budget = budget or Budget()
        self.clock = clock
        self._local = threading.Lock()

    # ----------------------------------------------------------------- the file
    def _load(self) -> dict[str, Any]:
        """The file's data, under the lock. A missing file is empty; a damaged one is set aside."""
        try:
            with open(self.path, "rb") as fh:
                raw = fh.read(MAX_FILE_BYTES + 1)
        except FileNotFoundError:
            return _empty()
        data = None
        if len(raw) <= MAX_FILE_BYTES:
            try:
                data = _clean(json.loads(raw.decode("utf-8")))
            except (UnicodeDecodeError, ValueError, RecursionError):
                data = None
        if data is None:
            aside = os.path.join(os.path.dirname(self.path), "usage.damaged.json")
            try:
                os.replace(self.path, aside)
                log.warning("the usage file was damaged; it was kept as usage.damaged.json")
            except OSError:
                pass
            return _empty()
        return data

    def _save(self, data: dict[str, Any]) -> None:
        folder = os.path.dirname(self.path)
        fd, tmp = tempfile.mkstemp(prefix="usage.", suffix=".tmp", dir=folder)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=True, separators=(",", ":"))
                fh.flush()
                os.fsync(fh.fileno())
            for attempt in range(20):  # a reader or a virus scanner can hold the file a moment
                try:
                    os.replace(tmp, self.path)
                    tmp = None
                    break
                except PermissionError:
                    if attempt == 19:
                        raise
                    time.sleep(0.02)
        finally:
            if tmp is not None:
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def _locked(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        return _FileLock(self.path + ".lock")

    # ----------------------------------------------------------------- reading
    def month(self, month: str | None = None) -> MonthUsage:
        """The usage of ``month`` (``YYYY-MM``, this month by default). Raises
        :class:`OSError` when the file cannot be read."""
        key = month or month_key(self.clock())
        with self._local, self._locked():
            data = self._load()
        b = data["months"].get(key) or _clean_bucket(None)
        return MonthUsage(
            key, b["calls"], b["input_tokens"], b["output_tokens"], b["cost_micro_usd"] / _MICRO
        )

    # ----------------------------------------------------------------- the check before a call
    def allow(
        self,
        *,
        input_tokens: int,
        output_cap: int,
        local: bool = False,
        run: RunBudget | None = None,
    ) -> int:
        """The largest output this call may ask for, at most ``output_cap``, counting what
        calls in flight hold. Raises :class:`BudgetExceededError` when the budgets leave
        less than :data:`MIN_OUTPUT_TOKENS` after the input. Holds nothing: a call uses
        :func:`reserve`."""
        allowed = output_cap if run is None else check_run(run, input_tokens, output_cap)
        if local:
            return allowed
        try:
            with self._local, self._locked():
                data = self._load()
        except (OSError, TimeoutError):
            raise BudgetExceededError(
                "The usage file could not be read, so the budget cannot be checked. Try again shortly."
            ) from None
        return self._grant(data, input_tokens, allowed)

    def _grant(self, data: dict[str, Any], input_tokens: int, allowed: int) -> int:
        """What the monthly budgets leave for a call's output, at most ``allowed``, with the
        holds of calls in flight counted as spent."""
        budget = self.budget
        now = self.clock()
        bucket = data["months"].get(month_key(now)) or _clean_bucket(None)
        holds = _live_holds(data, now).values()
        held_tokens = sum(h["tokens"] for h in holds)
        held_cost = sum(h["cost_micro_usd"] for h in holds)
        used_tokens = bucket["input_tokens"] + bucket["output_tokens"]
        in_flight = " Requests still in progress hold part of it until they finish." if held_tokens else ""
        left = budget.monthly_tokens - used_tokens - held_tokens - input_tokens
        if left < MIN_OUTPUT_TOKENS:
            detail = {"limit": budget.monthly_tokens, "usage": used_tokens}
            if held_tokens:
                detail["held"] = held_tokens
            raise BudgetExceededError(
                f"This month's token budget ({budget.monthly_tokens:,}) is used up or too small "
                f"for this request.{in_flight}",
                detail=detail,
            )
        allowed = min(allowed, left)
        if budget.monthly_cost is not None:
            if budget.pricing is None:
                raise BudgetExceededError(
                    "A monthly cost budget is set but the model's prices are not, "
                    "so the cost cannot be checked."
                )
            spent = (bucket["cost_micro_usd"] + held_cost) / _MICRO
            money_left = budget.monthly_cost - spent - budget.pricing.cost(input_tokens, 0)
            if budget.pricing.output_per_mtok > 0:
                affordable = math.floor(money_left * _MICRO / budget.pricing.output_per_mtok)
            else:
                affordable = allowed if money_left >= 0 else -1
            if affordable < MIN_OUTPUT_TOKENS:
                raise BudgetExceededError(
                    f"This month's cost budget (${budget.monthly_cost:,.2f}) is used up or too small for "
                    f"this request.{in_flight}",
                    detail={"usage": round(bucket["cost_micro_usd"] / _MICRO * 100)},
                )
            allowed = min(allowed, affordable)
        return allowed

    def _reserve(self, input_tokens: int, allowed: int) -> tuple[int, str]:
        """:meth:`_grant`, and a hold of the input plus the granted output written under the
        same lock. Returns the grant and the hold's id. Raises :class:`BudgetExceededError`."""
        try:
            with self._local, self._locked():
                data = self._load()
                granted = self._grant(data, input_tokens, allowed)
                now = self.clock()
                holds = _live_holds(data, now)
                if len(holds) >= MAX_HOLDS:
                    raise BudgetExceededError(
                        "Too many AI requests are in progress at once. Try again shortly."
                    )
                pricing = self.budget.pricing
                hold_id = uuid.uuid4().hex
                holds[hold_id] = {
                    "tokens": input_tokens + granted,
                    "cost_micro_usd": round(pricing.cost(input_tokens, granted) * _MICRO) if pricing else 0,
                    "until": math.floor(now) + HOLD_SECONDS,
                }
                data["holds"] = holds
                self._save(data)
        except (OSError, TimeoutError):
            raise BudgetExceededError(
                "The usage file could not be read or written, so the budget cannot be checked. "
                "Try again shortly."
            ) from None
        return granted, hold_id

    def release(self, hold: str | None) -> bool:
        """Drop the hold ``hold`` without counting anything. Never raises; False when the
        file could not be written (the hold then lapses by itself)."""
        if hold is None:
            return True
        try:
            with self._local, self._locked():
                data = self._load()
                holds = _live_holds(data, self.clock())
                holds.pop(hold, None)
                data["holds"] = holds
                self._save(data)
            return True
        except Exception as exc:  # releasing never breaks the call it ends
            log.warning("a usage hold could not be released (%s)", type(exc).__name__)
            return False

    # ----------------------------------------------------------------- recording
    def record(
        self,
        provider: str,
        input_tokens: int,
        output_tokens: int,
        *,
        local: bool = False,
        hold: str | None = None,
    ) -> bool:
        """Add one call's usage to this month, replacing the hold ``hold`` when given. Never
        raises; False when it could not be recorded (the reason is logged)."""
        try:
            input_tokens = max(0, int(input_tokens))
            output_tokens = max(0, int(output_tokens))
            pricing = None if local else self.budget.pricing
            cost = round(pricing.cost(input_tokens, output_tokens) * _MICRO) if pricing else 0
            now = self.clock()
            key = month_key(now)
            with self._local, self._locked():
                data = self._load()
                holds = _live_holds(data, now)
                if hold is not None:
                    holds.pop(hold, None)
                data["holds"] = holds
                months = data["months"]
                bucket = months.setdefault(key, {**_clean_bucket(None), "providers": {}})
                for target in (bucket, bucket["providers"].setdefault(provider[:32], _clean_bucket(None))):
                    target["calls"] += 1
                    target["input_tokens"] += input_tokens
                    target["output_tokens"] += output_tokens
                    target["cost_micro_usd"] += cost
                for old in sorted(months)[:-KEEP_MONTHS]:
                    del months[old]
                self._save(data)
            return True
        except Exception as exc:  # recording usage never breaks the call it records
            log.warning("usage could not be recorded (%s)", type(exc).__name__)
            return False


# --------------------------------------------------------------------------- one call's hold
class Hold:
    """What :func:`reserve` set aside for one call. ``max_output`` is the output cap to send.
    The call ends it once: :meth:`settle` with what it used, or :meth:`release` when the
    request never reached the provider. Neither raises."""

    def __init__(
        self,
        max_output: int,
        *,
        ledger: UsageLedger | None = None,
        hold_id: str | None = None,
        run: RunBudget | None = None,
        run_tokens: int = 0,
        local: bool = False,
    ) -> None:
        self.max_output = max_output
        self.id = hold_id
        self._ledger = ledger
        self._run = run
        self._run_tokens = run_tokens
        self._local = local
        self._ended = False
        self._lock = threading.Lock()

    def _end(self) -> bool:
        with self._lock:
            ended, self._ended = self._ended, True
            return not ended

    def settle(self, provider: str, input_tokens: int, output_tokens: int) -> None:
        """Count what the call used in place of what was held."""
        if not self._end():
            return
        try:
            if self._run is not None:
                self._run.settle(self._run_tokens, int(input_tokens) + int(output_tokens))
        except Exception as exc:
            log.warning("a run's usage could not be counted (%s)", type(exc).__name__)
        if self._ledger is not None:
            self._ledger.record(provider, input_tokens, output_tokens, local=self._local, hold=self.id)

    def release(self) -> None:
        """Give back what was held, counting nothing."""
        if not self._end():
            return
        try:
            if self._run is not None:
                self._run.settle(self._run_tokens, 0)
        except Exception as exc:  # as settle does: the ledger's hold is given back whatever happens
            log.warning("a run's hold could not be given back (%s)", type(exc).__name__)
        if self._ledger is not None:
            self._ledger.release(self.id)


def reserve(
    ledger: UsageLedger | None,
    *,
    input_tokens: int,
    output_cap: int,
    local: bool = False,
    run: RunBudget | None = None,
) -> Hold:
    """Check the budgets for one call and hold what it may use, in one step (see the module
    notes): the run's budget when there is a run, and the monthly budgets of ``ledger``
    for a cloud provider. Raises :class:`BudgetExceededError`, holding nothing, when they
    leave less than :data:`MIN_OUTPUT_TOKENS` after the input."""
    granted = output_cap if run is None else run.hold(input_tokens, output_cap)
    hold_id = None
    if ledger is not None and not local:
        try:
            monthly, hold_id = ledger._reserve(input_tokens, granted)
        except BaseException:
            if run is not None:
                run.settle(input_tokens + granted, 0)
            raise
        if run is not None and monthly < granted:
            run.settle(granted - monthly, 0)  # the month granted less: give the rest back
        granted = monthly
    return Hold(
        granted,
        ledger=ledger,
        hold_id=hold_id,
        run=run,
        run_tokens=input_tokens + granted if run is not None else 0,
        local=local,
    )


__all__ = [
    "DEFAULT_MONTHLY_TOKENS",
    "DEFAULT_RUN_TOKENS",
    "HOLD_SECONDS",
    "MIN_OUTPUT_TOKENS",
    "Budget",
    "Hold",
    "MonthUsage",
    "Pricing",
    "RunBudget",
    "UsageLedger",
    "check_run",
    "data_dir",
    "default_path",
    "estimate_image_tokens",
    "estimate_prompt_tokens",
    "estimate_tokens",
    "month_key",
    "reserve",
]
