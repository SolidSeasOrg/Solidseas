"""What the chat providers share: the two tasks, and requests over :mod:`solidseas.ai.http`."""

from __future__ import annotations

import base64
import json
import re
import time
import urllib.parse
from collections.abc import Callable
from typing import Any

from ...policy import Policy
from .. import prompts
from ..base import CallOptions, Completion, HealthResult, ModelProvider, TaskResult, host_is_local
from ..context import ModelSummary, PreparedRequest
from ..credentials import Secret
from ..errors import AIError, InvalidSettingError, NoKeyError, ProviderError
from ..http import CLOUD_READ_TIMEOUT, HttpClient
from ..usage import UsageLedger

HEALTH_SECONDS = 20.0
_MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_KEY_SHAPES = re.compile(r"(sk-[A-Za-z0-9_*-]{6,}|AIza[0-9A-Za-z_-]{10,}|[A-Za-z0-9_-]{40,})")


def image_data(image: prompts.PartImage) -> str:
    """A picture's PNG as base64 text, as every provider takes it inside the JSON."""
    return base64.b64encode(image.png).decode("ascii")


def check_model_name(model: Any) -> str:
    if not isinstance(model, str) or not _MODEL_NAME.match(model):
        raise InvalidSettingError("A model name is up to 128 letters, digits and . _ : / - characters.")
    return model


def whole(value: Any) -> int | None:
    """A token count from a reply, or None when it is not a non-negative whole number."""
    return value if type(value) is int and 0 <= value < 2**53 else None


def path_segment(model: str) -> str:
    """A checked model name as one URL path segment: a ``/`` in it cannot start another."""
    return urllib.parse.quote(model, safe=":")


class ChatProvider(ModelProvider):
    """A provider that does both tasks with the shared prompts and parsers."""

    def __init__(self, *, limits: prompts.PlanLimits | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.limits = limits or prompts.PlanLimits()

    def draft_change(
        self,
        context: ModelSummary | None,
        request: str | PreparedRequest,
        *,
        call: CallOptions | None = None,
        image: prompts.PartImage | None = None,
    ) -> TaskResult[prompts.Draft]:
        prompt = prompts.draft_prompt(request, context, image=image)
        return self._run(prompt, prompts.parse_draft, output_cap=prompts.DRAFT_OUTPUT_TOKENS, call=call)

    def plan_steps(
        self,
        goal: str | PreparedRequest,
        model_summary: ModelSummary,
        *,
        call: CallOptions | None = None,
        image: prompts.PartImage | None = None,
    ) -> TaskResult[prompts.Plan]:
        prompt = prompts.plan_prompt(goal, model_summary, limits=self.limits, image=image)
        said = goal.text if isinstance(goal, PreparedRequest) else goal

        def parse(text: str) -> prompts.Plan:
            return prompts.parse_plan(text, model_summary, goal=said, limits=self.limits)

        return self._run(prompt, parse, output_cap=prompts.PLAN_OUTPUT_TOKENS, call=call)


class HttpProvider(ChatProvider):
    """A provider reached over HTTP. Subclasses give the endpoint, the headers, the request
    body and how to read the reply."""

    default_endpoint = ""
    read_timeout = CLOUD_READ_TIMEOUT
    needs_key = True
    health_names_model = False  # True when the health check asks for the model itself (404: no such model)

    def __init__(
        self,
        *,
        model: str,
        key: Secret | None = None,
        endpoint: str | None = None,
        ledger: UsageLedger | None = None,
        guard: Callable[[], None] | None = None,
        limits: prompts.PlanLimits | None = None,
        http_options: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(model=check_model_name(model), ledger=ledger, guard=guard, limits=limits)
        if self.needs_key and not isinstance(key, Secret):
            raise NoKeyError(f"No API key is stored for {self.name}.")
        self._key = key
        options = {"read_timeout": self.read_timeout, "scrub": self._scrub}
        options.update(self._http_defaults(endpoint or self.default_endpoint))
        options.update(http_options or {})
        try:
            self._http = HttpClient(endpoint or self.default_endpoint, **options)
        except ValueError as exc:
            raise InvalidSettingError(f"The {self.name} address is not valid: {exc}.") from None

    def _http_defaults(self, endpoint: str) -> dict[str, Any]:
        return {}

    @property
    def endpoint(self) -> str:
        return self._http.endpoint.display()

    def _allowed_by(self, pol: Policy) -> bool:
        return not pol.local_only or (self.local and host_is_local(self._http.endpoint.host, pol))

    def _scrub(self, text: str) -> str:
        if self._key is not None:
            text = text.replace(self._key.reveal(), "[key]")
        return _KEY_SHAPES.sub("[hidden]", text)

    # subclasses ------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {}

    def _request(self, prompt: prompts.Prompt, max_output: int) -> tuple[str, dict[str, Any]]:
        raise NotImplementedError

    def _completion(self, data: Any) -> Completion:
        raise NotImplementedError

    def _health_path(self) -> str:
        raise NotImplementedError

    def _health_reply(self, data: Any) -> HealthResult:
        if self.health_names_model:
            return HealthResult(True, f"{self.endpoint} answered and has {self.model}.")
        return HealthResult(True, f"{self.endpoint} answered.")

    # the call --------------------------------------------------------------
    def _send(self, prompt: prompts.Prompt, *, max_output: int, call: CallOptions) -> Completion:
        path, body = self._request(prompt, max_output)
        reply = self._http.send(
            "POST",
            path,
            headers=self._headers(),
            body=json.dumps(body, ensure_ascii=True, allow_nan=False).encode("ascii"),
            cancel=call.cancel,
            deadline=call.deadline,
        )
        # A successful status: the provider had the request and may bill for it, so a reply
        # that cannot be read is marked delivered and the call path charges for it.
        try:
            completion = self._completion(reply.json())
        except AIError as exc:
            exc.delivered = True
            raise
        except (KeyError, IndexError, TypeError, AttributeError, ValueError):
            raise ProviderError(
                f"{self.endpoint} sent a reply SolidSeas does not understand.", delivered=True
            ) from None
        if not isinstance(completion.text, str):
            raise ProviderError(f"{self.endpoint} sent a reply with no text.", delivered=True)
        return completion

    def health_check(self) -> HealthResult:
        try:
            self._check_policy()
            reply = self._http.send(
                "GET",
                self._health_path(),
                headers=self._headers(),
                deadline=time.monotonic() + HEALTH_SECONDS,
            )
            return self._health_reply(reply.json())
        except AIError as exc:
            if self.health_names_model and exc.detail.get("value") == 404:
                return HealthResult(
                    False,
                    f"{self.endpoint} answered, but has no model {self.model}. "
                    "Check the model name in settings.",
                )
            return HealthResult(False, str(exc))
        except Exception as exc:  # a health check reports; it never raises
            return HealthResult(False, f"The check failed ({type(exc).__name__}).")
