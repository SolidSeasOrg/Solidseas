"""Google's Gemini API (``generateContent``), over :mod:`solidseas.ai.http`. The key goes in
``x-goog-api-key``, never in the URL's query string."""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

from ..base import Completion
from ..errors import InvalidSettingError, ProviderError
from ..prompts import Prompt
from ._common import HttpProvider, image_data, whole

_GEMINI_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")


def _parts(prompt: Prompt) -> list[dict[str, Any]]:
    """The user turn's parts: the text, then each picture inline."""
    return [{"text": prompt.user}] + [
        {"inline_data": {"mime_type": "image/png", "data": image_data(i)}} for i in prompt.images
    ]


class GeminiProvider(HttpProvider):
    name = "gemini"
    default_endpoint = "https://generativelanguage.googleapis.com"
    health_names_model = True

    def __init__(self, *, model: str, **kwargs: Any) -> None:
        if isinstance(model, str) and model.startswith("models/"):
            model = model[len("models/") :]
        if not isinstance(model, str) or not _GEMINI_MODEL.match(model):
            raise InvalidSettingError(
                "A Gemini model name is up to 100 letters, digits and . _ - characters."
            )
        super().__init__(model=model, **kwargs)

    def _model_path(self) -> str:
        return "/v1beta/models/" + urllib.parse.quote(self.model, safe="")

    def _headers(self) -> dict[str, str]:
        assert self._key is not None
        return {"x-goog-api-key": self._key.reveal()}

    def _request(self, prompt: Prompt, max_output: int) -> tuple[str, dict[str, Any]]:
        return self._model_path() + ":generateContent", {
            "systemInstruction": {"parts": [{"text": prompt.system}]},
            "contents": [{"role": "user", "parts": _parts(prompt)}],
            "generationConfig": {"maxOutputTokens": max_output, "responseMimeType": "application/json"},
        }

    def _completion(self, data: Any) -> Completion:
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason")
            shown = reason if isinstance(reason, str) and reason.isidentifier() else "no reason given"
            raise ProviderError(f"Gemini returned no answer ({shown}).")
        first = candidates[0]
        parts = (first.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought"))
        usage = data.get("usageMetadata") or {}
        out = whole(usage.get("candidatesTokenCount"))
        thoughts = whole(usage.get("thoughtsTokenCount"))
        if out is not None and thoughts is not None:
            out += thoughts
        return Completion(
            text,
            input_tokens=whole(usage.get("promptTokenCount")),
            output_tokens=out,
            truncated=first.get("finishReason") == "MAX_TOKENS",
        )

    def _health_path(self) -> str:
        return self._model_path()
