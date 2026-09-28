"""Claude implementation of :class:`app.llm.base.LLMClient` using structured outputs."""

from __future__ import annotations

import logging
import time
from typing import TypeVar

import anthropic
from pydantic import BaseModel

from .base import LLMError, LLMNotConfigured

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicLLM:
    def __init__(
        self,
        *,
        model: str,
        effort: str = "medium",
        max_tokens: int = 16000,
        fallbacks: str = "default",
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.fallbacks = fallbacks
        self._client = client or anthropic.Anthropic()

    def generate(
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        purpose: str,
        effort: str | None = None,
    ) -> T:
        extra_headers: dict[str, str] = {}
        extra_body: dict[str, object] = {}
        if self.fallbacks and self.fallbacks != "off":
            extra_headers["anthropic-beta"] = FALLBACK_BETA
            extra_body["fallbacks"] = self.fallbacks

        started = time.monotonic()
        try:
            response = self._client.messages.parse(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                thinking={"type": "adaptive"},
                output_config={"effort": effort or self.effort},
                output_format=schema,
                extra_headers=extra_headers or None,
                extra_body=extra_body or None,
            )
        except anthropic.AuthenticationError as exc:
            raise LLMNotConfigured("The Anthropic API key was rejected. Check ANTHROPIC_API_KEY.") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("The AI service is busy (rate limited). Please try again in a moment.") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"AI service error ({exc.status_code}): {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Could not reach the AI service. Check the network connection.") from exc

        log.info(
            "llm call purpose=%s model=%s stop=%s in=%s out=%s %.1fs",
            purpose,
            response.model,
            response.stop_reason,
            response.usage.input_tokens,
            response.usage.output_tokens,
            time.monotonic() - started,
        )
        if response.stop_reason == "refusal":
            raise LLMError("The AI declined to answer this request.")
        if response.stop_reason == "max_tokens":
            raise LLMError("The AI response was too long and got cut off.")
        parsed = response.parsed_output
        if parsed is None:
            raise LLMError("The AI returned a response that could not be understood.")
        return parsed


def credentials_available() -> bool:
    """Best-effort check whether the SDK can find credentials (API key, auth token or CLI profile)."""
    try:
        client = anthropic.Anthropic()
    except anthropic.AnthropicError:
        return False
    return bool(client.api_key or client.auth_token or client.credentials)
