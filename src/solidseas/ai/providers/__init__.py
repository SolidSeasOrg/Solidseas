"""The providers: Anthropic, OpenAI, Gemini, Ollama and ``noop``.

Each is a module of its own on the standard library's HTTP, with no SDK. They
are constructed only by :mod:`solidseas.ai.factory`; importing this package
builds nothing.
"""

from .anthropic import AnthropicProvider
from .gemini import GeminiProvider
from .noop import NoopProvider
from .ollama import OllamaProvider
from .openai import OpenAIProvider

CLOUD_PROVIDERS = {"anthropic": AnthropicProvider, "openai": OpenAIProvider, "gemini": GeminiProvider}
LOCAL_PROVIDERS = {"ollama": OllamaProvider}

__all__ = [
    "CLOUD_PROVIDERS",
    "LOCAL_PROVIDERS",
    "AnthropicProvider",
    "GeminiProvider",
    "NoopProvider",
    "OllamaProvider",
    "OpenAIProvider",
]
