"""The provider interface. It imports no provider SDK, and no provider module.

:class:`ModelProvider` has one abstract method, :meth:`~ModelProvider.health_check`,
whose result :meth:`~ModelProvider.health` caches for an hour. Every task
method returns None by default, meaning the provider does not support that
task; a caller treats None as a capability gap and says so plainly, never as
an error. The tasks:

``draft_change(context, request)``
    Review mode: code and an explanation (:class:`~solidseas.ai.prompts.Draft`).
``plan_steps(goal, model_summary)``
    Automatic mode: one validated plan (:class:`~solidseas.ai.prompts.Plan`).
``check_step(goal, step, index, count, image)``
    Automatic mode, when the person asked for it: a look at a picture of the part after
    one step (:class:`~solidseas.ai.prompts.Look`), which can only stop the run.

A provider that supports the tasks runs each through :meth:`ModelProvider._run`,
the one path a model call takes: the machine policy check, a cancellation
check, the budget check, which sets the output cap and holds that much of the
budgets for the call (:func:`~solidseas.ai.usage.reserve`), the call, charging
the budgets what it used (which never raises), a second cancellation check,
and parsing the reply with the parsers in :mod:`solidseas.ai.prompts`. A call
that fails after the request reached the provider (the error is
``delivered``) is charged its input estimate plus its output cap, because the
provider may bill for it and reported nothing; one that fails before gives
its hold back. Prompts are built in :mod:`~solidseas.ai.prompts` too, so the
"What the AI sees" panel can show exactly what a call sends.

The machine policy is checked twice before every call and every health check,
cached or not: by the provider itself, from its own kind and address, so a
provider built any other way still obeys it, and by the guard the factory
gives it. Providers are built only by :mod:`solidseas.ai.factory`.
"""

from __future__ import annotations

import abc
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from .. import policy
from ..policy import Policy, normalize_host
from .errors import AIError, CancelledError, PolicyRefusedError, ProviderTimeoutError, ReplyInvalidError
from .http import Cancel, is_loopback_host
from .usage import RunBudget, UsageLedger, estimate_prompt_tokens, estimate_tokens, reserve

HEALTH_CACHE_SECONDS = 3600.0
LOCAL_ONLY_MESSAGE = (
    "Set by your administrator: only an Ollama server on this PC, or one your administrator approved, "
    "may be used."
)
IMAGES_MESSAGE = "Set by your administrator: pictures of the part may not be sent to the AI."
T = TypeVar("T")


def host_is_local(host: str, pol: Policy) -> bool:
    """Whether ``host`` counts as local under ``pol``: ``localhost``, a loopback address, or
    exactly one of ``AllowedProviderHosts``."""
    normal = normalize_host(host)
    return normal is not None and (is_loopback_host(normal) or normal in pol.allowed_hosts)


@dataclass(frozen=True)
class HealthResult:
    ok: bool
    message: str = ""
    checked_at: float = field(default_factory=time.time)


@dataclass
class CallOptions:
    """What one call carries besides its prompt: a cancellation token (Stop), a deadline
    (``time.monotonic()``, an Automatic run's), and the run's token budget."""

    cancel: Cancel | None = None
    deadline: float | None = None
    run_budget: RunBudget | None = None


@dataclass(frozen=True)
class Completion:
    """A provider's reply: the text and the usage it reported (None when it did not).
    ``refused`` is True when the model declined to answer; its usage still counts."""

    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    truncated: bool = False
    refused: bool = False


@dataclass(frozen=True)
class TaskResult(Generic[T]):
    """A task's validated answer, with the prompt that was sent (for the run journal), the
    model's raw text (for the log, shown as plain text) and the tokens counted."""

    value: T
    prompt: Any
    raw: str
    input_tokens: int
    output_tokens: int


class ModelProvider(abc.ABC):
    """The interface every provider implements (see the module notes)."""

    name = "base"
    local = False  # True when the model runs on this machine or an approved local server

    def __init__(
        self,
        *,
        model: str = "",
        ledger: UsageLedger | None = None,
        guard: Callable[[], None] | None = None,
    ) -> None:
        self.model = model
        self.ledger = ledger
        self._guard = guard
        self._health: HealthResult | None = None
        self._health_lock = threading.Lock()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(model={self.model!r})"

    # ----------------------------------------------------------------- health
    @abc.abstractmethod
    def health_check(self) -> HealthResult:
        """Check the provider now (the key, the server, the model). Never raises."""

    def health(self, *, refresh: bool = False, now: float | None = None) -> HealthResult:
        """:meth:`health_check`, at most once an hour unless ``refresh``. The machine policy
        is read first, every time, so a cached result never outlives a policy change."""
        try:
            self._check_policy()
        except Exception as exc:
            with self._health_lock:
                self._health = None
            shown = str(exc) if isinstance(exc, AIError) else f"The check failed ({type(exc).__name__})."
            return HealthResult(False, shown)
        now = time.time() if now is None else now
        with self._health_lock:
            cached = self._health
            if not refresh and cached is not None and now - cached.checked_at < HEALTH_CACHE_SECONDS:
                return cached
        result = self.health_check()
        with self._health_lock:
            self._health = result
        return result

    # ----------------------------------------------------------------- tasks
    def draft_change(
        self, context: Any, request: Any, *, call: CallOptions | None = None, image: Any = None
    ) -> TaskResult | None:
        """Review mode: draft code for ``request`` about the part ``context`` (a model
        summary, or None), with ``image`` (a :class:`~solidseas.ai.prompts.PartImage`) when
        the person chose to send a picture. None: this provider does not draft."""
        return None

    def plan_steps(
        self, goal: Any, model_summary: Any, *, call: CallOptions | None = None, image: Any = None
    ) -> TaskResult | None:
        """Automatic mode: plan ``goal`` for the part ``model_summary``, with ``image`` as
        for :meth:`draft_change`. None: this provider does not plan."""
        return None

    def check_step(
        self, goal: Any, step: str, index: int, count: int, image: Any, *, call: CallOptions | None = None
    ) -> TaskResult | None:
        """Automatic mode: look at ``image`` (a :class:`~solidseas.ai.prompts.PartImage` of
        the part after step ``index`` of ``count``, which ``step`` shows as the Plan panel
        does) and say whether the part looks as the step should leave it. None: this
        provider does not look."""
        return None

    # ----------------------------------------------------------------- the one call path
    def _send(self, prompt: Any, *, max_output: int, call: CallOptions) -> Completion:
        """Send ``prompt`` with ``max_output`` as the output cap. Implemented by a provider
        that supports the tasks."""
        raise NotImplementedError

    def _allowed_by(self, pol: Policy) -> bool:
        """Whether ``pol`` allows this provider, judged from the provider itself: under
        ``LocalProviderOnly`` only one that runs on this machine (an HTTP provider also
        checks its address)."""
        return not pol.local_only or self.local

    def _check_policy(self) -> None:
        """The machine policy, read now: the provider's own check, which holds however the
        provider was built, then the factory's guard. Raises :class:`PolicyRefusedError`."""
        if not self._allowed_by(policy.current()):
            raise PolicyRefusedError(LOCAL_ONLY_MESSAGE)
        if self._guard is not None:
            self._guard()

    def _run(
        self, prompt: Any, parse: Callable[[str], T], *, output_cap: int, call: CallOptions | None
    ) -> TaskResult[T]:
        call = call or CallOptions()
        self._check_policy()
        if getattr(prompt, "images", ()) and policy.current().images_disabled:
            raise PolicyRefusedError(IMAGES_MESSAGE)
        _stop_if_cancelled(call)
        if call.deadline is not None and time.monotonic() >= call.deadline:
            raise ProviderTimeoutError("The run's time limit was reached before the model was asked.")
        estimate = estimate_prompt_tokens(prompt)
        hold = reserve(
            self.ledger, input_tokens=estimate, output_cap=output_cap, local=self.local, run=call.run_budget
        )
        max_output = hold.max_output
        try:
            completion = self._send(prompt, max_output=max_output, call=call)
        except BaseException as exc:
            if getattr(exc, "delivered", False):
                # the provider had the request and reported nothing: charge what it could have cost
                hold.settle(self.name, estimate, max_output)
            else:
                hold.release()
            raise
        used_in = completion.input_tokens if completion.input_tokens is not None else estimate
        used_out = (
            completion.output_tokens
            if completion.output_tokens is not None
            else estimate_tokens(completion.text)
        )
        hold.settle(self.name, used_in, used_out)
        if completion.refused:
            raise ReplyInvalidError("The model declined to answer.")
        _stop_if_cancelled(call)  # Stop pressed as the reply came in: it is not used
        try:
            value = parse(completion.text)
        except ReplyInvalidError as exc:
            if completion.truncated:
                raise ReplyInvalidError(
                    f"{exc} The reply was cut off at the output cap ({max_output:,} tokens).",
                    detail=exc.detail,
                ) from None
            raise
        _stop_if_cancelled(call)
        return TaskResult(value, prompt, completion.text, used_in, used_out)


def _stop_if_cancelled(call: CallOptions) -> None:
    if call.cancel is not None and call.cancel.cancelled:
        raise CancelledError()


__all__ = [
    "LOCAL_ONLY_MESSAGE",
    "CallOptions",
    "Completion",
    "HealthResult",
    "ModelProvider",
    "TaskResult",
    "host_is_local",
]
