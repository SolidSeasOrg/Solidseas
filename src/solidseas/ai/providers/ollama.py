"""Ollama, a model server on this machine or an approved local server, over
:mod:`solidseas.ai.http`.

Its client never uses a proxy, resolves the host on every call and connects to
the address it resolved (``localhost`` must resolve only to loopback), and may
use plain HTTP to the host the person configured. Whether that host is allowed
at all is the factory's decision under the machine policy. No key is sent.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

from ..base import Completion, HealthResult
from ..http import LOCAL_READ_TIMEOUT
from ..prompts import Prompt
from ._common import HttpProvider, image_data, whole

DEFAULT_URL = "http://127.0.0.1:11434"


def endpoint_host(url: str) -> str:
    """The host of an Ollama base URL, lower case, as the policy compares it; "" when there
    is none. The URL itself is checked when the client is made."""
    try:
        host = urllib.parse.urlsplit(url).hostname or ""
    except ValueError:
        return ""
    return host.lower().rstrip(".")


def _user_message(prompt: Prompt) -> dict[str, Any]:
    """The user turn, with each picture in the message's ``images`` (a model that cannot
    see ignores them)."""
    message: dict[str, Any] = {"role": "user", "content": prompt.user}
    if prompt.images:
        message["images"] = [image_data(i) for i in prompt.images]
    return message


class OllamaProvider(HttpProvider):
    name = "ollama"
    local = True
    needs_key = False
    default_endpoint = DEFAULT_URL
    read_timeout = LOCAL_READ_TIMEOUT

    def _http_defaults(self, endpoint: str) -> dict[str, Any]:
        host = endpoint_host(endpoint)
        return {"use_proxies": False, "pin": True, "plain_http_hosts": (host,) if host else ()}

    def _request(self, prompt: Prompt, max_output: int) -> tuple[str, dict[str, Any]]:
        return "/api/chat", {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt.system},
                _user_message(prompt),
            ],
            "stream": False,
            "format": "json",
            "options": {"num_predict": max_output},
        }

    def _completion(self, data: Any) -> Completion:
        return Completion(
            data["message"]["content"],
            input_tokens=whole(data.get("prompt_eval_count")),
            output_tokens=whole(data.get("eval_count")),
            truncated=data.get("done_reason") == "length",
        )

    def _health_path(self) -> str:
        return "/api/tags"

    def _health_reply(self, data: Any) -> HealthResult:
        names = []
        for m in (data or {}).get("models") or []:
            if isinstance(m, dict) and isinstance(m.get("name"), str):
                names.append(m["name"])
        wanted = self.model if ":" in self.model else self.model + ":latest"
        if self.model in names or wanted in names:
            return HealthResult(True, f"Ollama at {self.endpoint} has {self.model}.")
        return HealthResult(
            False, f"Ollama at {self.endpoint} answered, but does not have {self.model}. Pull it first."
        )
