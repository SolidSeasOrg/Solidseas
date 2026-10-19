"""Anthropic's Messages API, over :mod:`solidseas.ai.http`. The key goes in ``x-api-key``."""

from __future__ import annotations

from typing import Any

from ..base import Completion
from ..prompts import Prompt
from ._common import HttpProvider, image_data, path_segment, whole

API_VERSION = "2023-06-01"


def _content(prompt: Prompt) -> Any:
    """The user turn: the text alone, or the text then each picture."""
    if not prompt.images:
        return prompt.user
    return [{"type": "text", "text": prompt.user}] + [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_data(i)}}
        for i in prompt.images
    ]


class AnthropicProvider(HttpProvider):
    name = "anthropic"
    default_endpoint = "https://api.anthropic.com"
    health_names_model = True

    def _headers(self) -> dict[str, str]:
        assert self._key is not None
        return {"x-api-key": self._key.reveal(), "anthropic-version": API_VERSION}

    def _request(self, prompt: Prompt, max_output: int) -> tuple[str, dict[str, Any]]:
        return "/v1/messages", {
            "model": self.model,
            "max_tokens": max_output,
            "system": prompt.system,
            "messages": [{"role": "user", "content": _content(prompt)}],
        }

    def _completion(self, data: Any) -> Completion:
        blocks = data["content"]
        text = "".join(b["text"] for b in blocks if isinstance(b, dict) and b.get("type") == "text")
        usage = data.get("usage") or {}
        return Completion(
            text,
            input_tokens=whole(usage.get("input_tokens")),
            output_tokens=whole(usage.get("output_tokens")),
            truncated=data.get("stop_reason") == "max_tokens",
        )

    def _health_path(self) -> str:
        return "/v1/models/" + path_segment(self.model)  # takes an alias as well as an id
