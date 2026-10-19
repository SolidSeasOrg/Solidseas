"""The provider the factory serves when no real one can be used, with the reason.

Its tasks return None, a capability gap. ``reason`` tells the app what to show:
``not_configured`` hides every AI control; ``policy_refused`` keeps the affected
controls visible, disabled, with "Set by your administrator"; ``no_key``,
``credential_store`` and ``invalid_setting`` point the person at settings.
"""

from __future__ import annotations

from ..base import HealthResult, ModelProvider
from ..errors import AI_ERROR_CODES


class NoopProvider(ModelProvider):
    name = "noop"

    def __init__(self, reason: str = "not_configured", message: str | None = None) -> None:
        super().__init__(model="")
        self.reason = reason if reason in AI_ERROR_CODES else "not_configured"
        self.message = message or AI_ERROR_CODES[self.reason]

    def __repr__(self) -> str:
        return f"NoopProvider(reason={self.reason!r})"

    @property
    def set_by_administrator(self) -> bool:
        return self.reason == "policy_refused"

    def health_check(self) -> HealthResult:
        return HealthResult(False, self.message)
