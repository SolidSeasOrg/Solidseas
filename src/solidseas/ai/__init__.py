"""The AI connector (provisional; ``docs/API.md`` section 3.23, ``docs/ASSISTANT.md``).

It follows the provider seam the project family shares:

- :mod:`solidseas.ai.base`: the :class:`ModelProvider` interface. It imports no
  provider SDK; a task a provider does not support returns None.
- :mod:`solidseas.ai.prompts`: every prompt, every reply parser
  (:func:`parse_json_response`, :func:`parse_plan`, :func:`parse_draft`) and the
  Automatic mode vocabulary.
- :mod:`solidseas.ai.context`: :func:`build_model_summary`, the only way
  document data reaches a prompt, and the request redaction.
- :mod:`solidseas.ai.providers`: Anthropic, OpenAI, Gemini and Ollama on the
  standard library's HTTP (:mod:`solidseas.ai.http`), and ``noop``.
- :mod:`solidseas.ai.factory`: the only place a provider is built, and one of
  the two places the machine policy (:mod:`solidseas.policy`) is enforced.
- :mod:`solidseas.ai.credentials`: keys in Windows Credential Manager.
- :mod:`solidseas.ai.usage`: the usage file and the enforced budgets.
- :mod:`solidseas.ai.fake`: a scripted provider for tests.

Everything here is the standard library; ``truststore`` is used when installed
(the ``[ai]`` extra). Importing the package builds no provider and reaches no
network.
"""

from .base import CallOptions, Completion, HealthResult, ModelProvider, TaskResult
from .context import ModelSummary, PartSnapshot, build_model_summary, prepare_request, redact
from .credentials import MemoryCredentialStore, Secret, WindowsCredentialStore, default_store
from .errors import AI_ERROR_CODES, AIError
from .factory import AISettings, get_provider, reset
from .http import Cancel
from .prompts import Draft, Plan, PlanLimits, Prompt, parse_draft, parse_json_response, parse_plan
from .usage import Budget, Pricing, RunBudget, UsageLedger

__all__ = [
    "AI_ERROR_CODES",
    "AIError",
    "AISettings",
    "Budget",
    "CallOptions",
    "Cancel",
    "Completion",
    "Draft",
    "HealthResult",
    "MemoryCredentialStore",
    "ModelProvider",
    "ModelSummary",
    "PartSnapshot",
    "Plan",
    "PlanLimits",
    "Pricing",
    "Prompt",
    "RunBudget",
    "Secret",
    "TaskResult",
    "UsageLedger",
    "WindowsCredentialStore",
    "build_model_summary",
    "default_store",
    "get_provider",
    "parse_draft",
    "parse_json_response",
    "parse_plan",
    "prepare_request",
    "redact",
    "reset",
]
