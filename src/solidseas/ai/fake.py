"""A scripted provider for tests and self-tests: it answers from a queue and records every
prompt, and never touches a network.

It takes the same call path as a real provider (the policy guard, the budget
check, usage recording, the run budget and the shared parsers), so a test of
what reaches a model, or of what a reply may do, holds for every provider.

Queue items: a string (the reply text), a :class:`~solidseas.ai.base.Completion`,
an exception (raised as the call's failure; set its ``delivered`` to say the
request had reached the provider), a callable taking the prompt and returning
either, or :data:`WAIT_FOR_CANCEL`, which blocks until the call's cancellation
token is set and then fails as a delivered request that was stopped.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from typing import Any

from .base import CallOptions, Completion, HealthResult
from .errors import CancelledError, ProviderError
from .prompts import Prompt
from .providers._common import ChatProvider
from .usage import estimate_prompt_tokens, estimate_tokens

WAIT_FOR_CANCEL = object()


class ScriptedProvider(ChatProvider):
    name = "scripted"

    def __init__(self, replies: Any = (), *, local: bool = True, **kwargs: Any) -> None:
        kwargs.setdefault("model", "scripted")
        super().__init__(**kwargs)
        self.local = local
        self.prompts: list[Prompt] = []
        self.output_caps: list[int] = []
        self._queue: deque[Any] = deque(replies)
        self._lock = threading.Lock()

    def push(self, *items: Any) -> None:
        with self._lock:
            self._queue.extend(items)

    def sent_text(self) -> str:
        """Everything every prompt sent, joined: for asserting what never left."""
        return "\n".join(p.text() for p in self.prompts)

    def health_check(self) -> HealthResult:
        return HealthResult(True, "scripted")

    def _send(self, prompt: Prompt, *, max_output: int, call: CallOptions) -> Completion:
        with self._lock:
            self.prompts.append(prompt)
            self.output_caps.append(max_output)
            if not self._queue:
                raise ProviderError("The scripted provider has no reply queued.")
            item = self._queue.popleft()
        if item is WAIT_FOR_CANCEL:
            if call.cancel is None:
                raise ProviderError("WAIT_FOR_CANCEL needs a cancellation token.")
            call.cancel.wait(60.0)
            raise CancelledError(delivered=True)  # the prompt reached the "provider", as a real call's would
        if callable(item) and not isinstance(item, BaseException):
            item = item(prompt)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, Completion):
            return item
        if isinstance(item, str):
            return Completion(
                item,
                input_tokens=estimate_prompt_tokens(prompt),
                output_tokens=estimate_tokens(item),
            )
        raise ProviderError(f"The scripted provider cannot reply with {type(item).__name__}.")


ReplyFunction = Callable[[Prompt], "str | Completion"]

__all__ = ["WAIT_FOR_CANCEL", "ScriptedProvider"]
