"""The AI connector's exceptions.

Every one derives from :class:`AIError` and carries ``code``, a stable
machine-readable code from :data:`AI_ERROR_CODES`, and a message written for
the person at the keyboard. They are not :class:`solidseas.SolidSeasError`
subclasses: they never reach the integration surfaces (the command line, the
REST service and their error table in ``docs/API.md`` section 5.6), only the
desktop app, which shows the message as plain text.

No message ever holds an API key, a request header or a URL with a query
string. Text a provider sent back is quoted only for errors other than 401 and
403 (a 401 body can echo part of the key): the key and anything shaped like one
are removed from the whole text first, and only then is it cut short.

``delivered`` is True on an error that came after the request reached the
provider (a timeout or Stop once the request was sent, or a successful reply
SolidSeas could not read), so the provider may bill for it; the call path then
charges the budgets for it (:meth:`solidseas.ai.base.ModelProvider._run`).
"""

from __future__ import annotations

from typing import Any

AI_ERROR_CODES: dict[str, str] = {
    "not_configured": "No AI provider is set up.",
    "policy_refused": "Set by your administrator: the machine policy does not allow this.",
    "no_key": "No API key is stored for this provider.",
    "credential_store": "Windows Credential Manager could not be read or written.",
    "unauthorized": "The provider refused the API key. Check or replace the key in settings.",
    "rate_limited": "The provider is limiting requests. Try again in a minute.",
    "unavailable": "The provider is overloaded or down. Try again later.",
    "network": "The provider could not be reached.",
    "timeout": "The provider did not answer in time.",
    "cancelled": "The request was stopped.",
    "budget_exceeded": "The token or cost budget does not allow this request.",
    "input_too_large": "The request or the part is too large to send.",
    "reply_invalid": "The model's reply was not a valid answer.",
    "provider_error": "The provider returned an error.",
    "invalid_setting": "An AI setting is not valid.",
}


class AIError(Exception):
    """Base class of the AI connector's errors. ``str(exc)`` is the message for the person;
    ``detail`` holds safe structured facts (a limit, a status code, a field)."""

    code = "provider_error"
    delivered = False

    def __init__(
        self, message: str | None = None, *, detail: dict[str, Any] | None = None, delivered: bool = False
    ) -> None:
        super().__init__(message or AI_ERROR_CODES.get(self.code, "The AI request failed."))
        self.detail: dict[str, Any] = dict(detail or {})
        self.delivered = bool(delivered)

    @property
    def message(self) -> str:
        return str(self)


class NotConfiguredError(AIError):
    code = "not_configured"


class PolicyRefusedError(AIError):
    code = "policy_refused"


class NoKeyError(AIError):
    code = "no_key"


class CredentialStoreError(AIError):
    code = "credential_store"


class UnauthorizedError(AIError):
    """401 or 403: the key is wrong, revoked or not allowed. Never retried."""

    code = "unauthorized"


class RateLimitedError(AIError):
    """429 still failing after the retries, or a Retry-After longer than SolidSeas waits."""

    code = "rate_limited"


class UnavailableError(AIError):
    code = "unavailable"


class NetworkError(AIError):
    code = "network"


class ProviderTimeoutError(AIError):
    code = "timeout"


class CancelledError(AIError):
    code = "cancelled"


class BudgetExceededError(AIError):
    code = "budget_exceeded"


class InputTooLargeError(AIError):
    code = "input_too_large"


class ReplyInvalidError(AIError):
    """The reply did not parse, or failed the schema, the allowlists or a bound. Nothing
    from it is used."""

    code = "reply_invalid"


class ProviderError(AIError):
    code = "provider_error"


class InvalidSettingError(AIError, ValueError):
    code = "invalid_setting"


__all__ = [
    "AI_ERROR_CODES",
    "AIError",
    "BudgetExceededError",
    "CancelledError",
    "CredentialStoreError",
    "InputTooLargeError",
    "InvalidSettingError",
    "NetworkError",
    "NoKeyError",
    "NotConfiguredError",
    "PolicyRefusedError",
    "ProviderError",
    "ProviderTimeoutError",
    "RateLimitedError",
    "ReplyInvalidError",
    "UnauthorizedError",
    "UnavailableError",
]
