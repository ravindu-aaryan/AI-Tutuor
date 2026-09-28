"""Local-model implementation of :class:`app.llm.base.LLMClient` using an Ollama server.

Ollama (https://ollama.com) runs open models such as Qwen or Llama on the user's own computer, so there is no
per-call cost. Replies are constrained to the Pydantic schema with Ollama's JSON-schema ``format`` option.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .base import LLMError

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class OllamaLLM:
    def __init__(self, *, base_url: str, model: str, timeout: float = 600.0, num_ctx: int = 16384) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.num_ctx = num_ctx

    def generate(
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        purpose: str,
        effort: str | None = None,
    ) -> T:
        body = {
            "model": self.model,
            "stream": False,
            "format": schema.model_json_schema(),
            "options": {"temperature": 0.4, "num_ctx": self.num_ctx},
            "messages": [
                {"role": "system", "content": system + "\n\nReply only with JSON matching the requested schema."},
                {"role": "user", "content": prompt},
            ],
        }
        last_error: Exception | None = None
        for attempt in range(2):  # small models occasionally emit invalid JSON; one retry is usually enough
            started = time.monotonic()
            try:
                res = httpx.post(f"{self.base_url}/api/chat", json=body, timeout=self.timeout)
            except httpx.ConnectError as exc:
                raise LLMError(
                    f"Can't reach the local AI at {self.base_url}. Is Ollama installed and running?"
                ) from exc
            except httpx.TimeoutException as exc:
                raise LLMError("The local AI took too long to answer. Try a smaller model.") from exc
            if res.status_code == 404:
                raise LLMError(f"The local model '{self.model}' isn't installed. Run: ollama pull {self.model}")
            if res.status_code >= 400:
                raise LLMError(f"Local AI error ({res.status_code}): {res.text[:300]}")
            data = res.json()
            content = data.get("message", {}).get("content", "")
            log.info(
                "local llm purpose=%s model=%s in=%s out=%s %.1fs",
                purpose,
                self.model,
                data.get("prompt_eval_count"),
                data.get("eval_count"),
                time.monotonic() - started,
            )
            try:
                return schema.model_validate_json(content)
            except (ValidationError, json.JSONDecodeError) as exc:
                last_error = exc
                log.warning("local model returned invalid JSON for %s (attempt %s)", purpose, attempt + 1)
        raise LLMError("The local AI gave an answer that couldn't be understood. Try again or use a larger model.") from last_error


def ollama_status(base_url: str, model: str) -> tuple[bool, str]:
    """(available, human-readable detail)."""
    try:
        res = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=3.0)
        res.raise_for_status()
    except httpx.HTTPError:
        return False, f"Ollama isn't reachable at {base_url}. Install it from ollama.com and start it."
    names = {m.get("name", "") for m in res.json().get("models", [])}
    if model in names or f"{model}:latest" in names:
        return True, f"Ready: {model}"
    return False, f"Ollama is running but '{model}' isn't installed. Run: ollama pull {model}"
