"""The only place a provider is built, and one of the two places the machine policy is
enforced (the other is ``solidseas_app.assistant.automatic.start_run``).

:func:`get_provider` reads the policy fresh (:func:`solidseas.policy.current`)
and refuses any provider but a local Ollama under ``LocalProviderOnly``,
serving :class:`~solidseas.ai.providers.NoopProvider` with the reason instead.
Local means the Ollama base URL's host is ``localhost``, a loopback address, or
exactly one of ``AllowedProviderHosts``. Every provider it builds also carries
a guard that reads the policy again before every model call and every health
check, so a policy Group Policy pushes while the app is open applies to the
next call even through a cached provider. A provider also makes the same check
itself, from its own kind and address, so one built some other way would
still be refused (:meth:`solidseas.ai.base.ModelProvider._check_policy`).

The provider is cached; :func:`reset` drops it, and the app calls it after any
change to the AI settings or a key. Keys come from the credential store and
are passed to the provider explicitly.

The search in ``docs/SECURITY_REVIEW.md`` section 2 shows there is no other
path: outside this module and the providers' own package, nothing in ``src``
names a provider class, the provider tables or the package, except the package
notes and ``fake.py``'s import of the shared base class.
``tests/test_ai_factory.py`` repeats it on every run.
"""

from __future__ import annotations

import math
import threading
from dataclasses import asdict, dataclass, fields
from typing import Any

from .. import policy
from ..policy import Policy
from . import credentials as _credentials
from .base import LOCAL_ONLY_MESSAGE, ModelProvider, host_is_local
from .credentials import CredentialStore
from .errors import CredentialStoreError, InvalidSettingError, PolicyRefusedError
from .prompts import PlanLimits
from .providers import CLOUD_PROVIDERS, NoopProvider, OllamaProvider
from .providers._common import check_model_name
from .providers.ollama import DEFAULT_URL, endpoint_host
from .usage import DEFAULT_MONTHLY_TOKENS, DEFAULT_RUN_TOKENS, Budget, Pricing, UsageLedger

PROVIDER_CHOICES = ("none", *CLOUD_PROVIDERS, "ollama")
DISPLAY_NAMES = {"anthropic": "Anthropic", "openai": "OpenAI", "gemini": "Gemini", "ollama": "Ollama"}


@dataclass(frozen=True)
class AISettings:
    """The AI settings the factory builds from. Every field is checked when it is made;
    :meth:`from_dict` gives :class:`InvalidSettingError` for a value that is not valid."""

    provider: str = "none"
    model: str = ""
    ollama_url: str = DEFAULT_URL
    monthly_tokens: int = DEFAULT_MONTHLY_TOKENS
    monthly_cost: float | None = None
    price_input_per_mtok: float | None = None
    price_output_per_mtok: float | None = None
    run_tokens: int = DEFAULT_RUN_TOKENS
    max_steps: int = 20
    max_new_instances: int = 200
    length_factor: float = 10.0
    no_body_length_mm: float = 1000.0
    min_length_mm: float = 0.001
    protected_properties: tuple[str, ...] = ()
    always_confirm: bool = False

    def __post_init__(self) -> None:
        if self.provider not in PROVIDER_CHOICES:
            raise InvalidSettingError(f"The provider must be one of {', '.join(PROVIDER_CHOICES)}.")
        if self.model:
            check_model_name(self.model)
        if not isinstance(self.ollama_url, str) or len(self.ollama_url) > 2048:
            raise InvalidSettingError("The Ollama address is not valid.")
        if type(self.always_confirm) is not bool:
            raise InvalidSettingError("Always confirm the plan is on or off.")
        if not isinstance(self.protected_properties, tuple) or not all(
            isinstance(p, str) and 0 < len(p) <= 64 for p in self.protected_properties
        ):
            raise InvalidSettingError("Protected property names are text of at most 64 characters.")
        self.budget()
        self.limits()
        if type(self.run_tokens) is not int or not 0 <= self.run_tokens <= 1_000_000:
            raise InvalidSettingError("A run's token budget is a whole number from 0 to 1,000,000.")

    def pricing(self) -> Pricing | None:
        if self.price_input_per_mtok is None and self.price_output_per_mtok is None:
            return None
        if self.price_input_per_mtok is None or self.price_output_per_mtok is None:
            raise InvalidSettingError("Set both the input and the output price, or neither.")
        return Pricing(self.price_input_per_mtok, self.price_output_per_mtok)

    def budget(self) -> Budget:
        return Budget(self.monthly_tokens, self.monthly_cost, self.pricing())

    def limits(self) -> PlanLimits:
        try:
            return PlanLimits(
                max_steps=self.max_steps,
                max_new_instances=self.max_new_instances,
                length_factor=self.length_factor,
                no_body_length_mm=self.no_body_length_mm,
                min_length_mm=self.min_length_mm,
                protected_properties=self.protected_properties,
            )
        except Exception as exc:
            raise InvalidSettingError(str(exc)) from None

    @classmethod
    def from_dict(cls, data: Any) -> AISettings:
        if not isinstance(data, dict):
            raise InvalidSettingError("The AI settings must be an object.")
        known = {f.name for f in fields(cls)}
        values = {k: v for k, v in data.items() if k in known}
        if "protected_properties" in values and isinstance(values["protected_properties"], list):
            values["protected_properties"] = tuple(values["protected_properties"])
        for name in (
            "monthly_cost",
            "price_input_per_mtok",
            "price_output_per_mtok",
            "length_factor",
            "no_body_length_mm",
            "min_length_mm",
        ):
            v = values.get(name)
            if type(v) is float and not math.isfinite(v):
                raise InvalidSettingError(f"{name} must be a finite number.")
        try:
            return cls(**values)
        except TypeError:
            raise InvalidSettingError("The AI settings hold a value of the wrong type.") from None

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["protected_properties"] = list(self.protected_properties)
        return out


# --------------------------------------------------------------------------- the policy check
def refusal(settings: AISettings, pol: Policy) -> str | None:
    """Why ``pol`` does not allow ``settings``'s provider, or None when it does."""
    if not pol.local_only or settings.provider in ("none",):
        return None
    if settings.provider != "ollama":
        return LOCAL_ONLY_MESSAGE
    return None if host_is_local(endpoint_host(settings.ollama_url), pol) else LOCAL_ONLY_MESSAGE


def _guard(settings: AISettings):
    def guard() -> None:
        reason = refusal(settings, policy.current())
        if reason is not None:
            raise PolicyRefusedError(reason)

    return guard


# --------------------------------------------------------------------------- building
_lock = threading.Lock()
_cache: tuple[AISettings, Any, Any, ModelProvider] | None = None


def reset() -> None:
    """Drop the cached provider. Call after any change to the AI settings or a key."""
    global _cache
    with _lock:
        _cache = None


def _build(
    settings: AISettings, credentials: CredentialStore | None, ledger: UsageLedger | None
) -> ModelProvider:
    kind = settings.provider
    name = DISPLAY_NAMES.get(kind, kind)
    if not settings.model:
        return NoopProvider("not_configured", f"Choose a model for {name} in settings.")
    ledger = ledger if ledger is not None else UsageLedger(budget=settings.budget())
    common = {
        "model": settings.model,
        "ledger": ledger,
        "guard": _guard(settings),
        "limits": settings.limits(),
    }
    try:
        if kind == "ollama":
            return OllamaProvider(endpoint=settings.ollama_url, **common)
        store = credentials if credentials is not None else _credentials.default_store()
        try:
            key = store.get(kind)
        except CredentialStoreError as exc:
            return NoopProvider("credential_store", str(exc))
        if key is None:
            return NoopProvider("no_key", f"No API key is stored for {name}. Add one in settings.")
        return CLOUD_PROVIDERS[kind](key=key, **common)
    except InvalidSettingError as exc:
        return NoopProvider("invalid_setting", str(exc))


def get_provider(
    settings: AISettings,
    *,
    credentials: CredentialStore | None = None,
    ledger: UsageLedger | None = None,
) -> ModelProvider:
    """The provider ``settings`` name, allowed by the machine policy read now; otherwise a
    :class:`NoopProvider` with the reason. Never raises for a refusal."""
    global _cache
    if not isinstance(settings, AISettings):
        raise InvalidSettingError("get_provider needs AISettings.")
    if settings.provider == "none":
        return NoopProvider("not_configured")
    reason = refusal(settings, policy.current())
    if reason is not None:
        return NoopProvider("policy_refused", reason)
    with _lock:
        cached = _cache
    if cached is not None and cached[0] == settings and cached[1] is credentials and cached[2] is ledger:
        return cached[3]
    provider = _build(settings, credentials, ledger)
    if not isinstance(provider, NoopProvider):
        with _lock:
            _cache = (settings, credentials, ledger, provider)
    return provider


__all__ = ["LOCAL_ONLY_MESSAGE", "PROVIDER_CHOICES", "AISettings", "get_provider", "refusal", "reset"]
