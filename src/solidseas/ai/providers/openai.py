"""OpenAI's Chat Completions API, over :mod:`solidseas.ai.http`. The key goes in
``Authorization: Bearer``."""

from __future__ import annotations

from typing import Any

from ..base import Completion
from ..prompts import Prompt
from ._common import HttpProvider, image_data, path_segment, whole


def _content(prompt: Prompt) -> Any:
    """The user turn: the text alone, or the text then each picture as a data URL."""
    if not prompt.images:
        return prompt.user
    return [{"type": "text", "text": prompt.user}] + [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + image_data(i)}}
        for i in prompt.images
    ]


class OpenAIProvider(HttpProvider):
    name = "openai"
    default_endpoint = "https://api.openai.com"
    health_names_model = True

    def _headers(self) -> dict[str, str]:
        assert self._key is not None
        return {"Authorization": "Bearer " + self._key.reveal()}

    def _request(self, prompt: Prompt, max_output: int) -> tuple[str, dict[str, Any]]:
        return "/v1/chat/completions", {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": _content(prompt)},
            ],
            "max_completion_tokens": max_output,
            "response_format": {"type": "json_object"},
        }

    def _completion(self, data: Any) -> Completion:
        choice = data["choices"][0]
        message = choice["message"]
        text = message.get("content")
        refused = text is None and isinstance(message.get("refusal"), str)
        usage = data.get("usage") or {}
        return Completion(
            "" if refused else text,
            input_tokens=whole(usage.get("prompt_tokens")),
            output_tokens=whole(usage.get("completion_tokens")),
            truncated=choice.get("finish_reason") == "length",
            refused=refused,
        )

    def _health_path(self) -> str:
        return "/v1/models/" + path_segment(self.model)
