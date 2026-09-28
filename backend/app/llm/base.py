"""LLM abstraction.

All AI work in the app goes through :class:`LLMClient.generate`, which returns a validated Pydantic
object. This keeps prompts/business logic independent of the provider and lets tests substitute a
scripted client (see ``tests/fakes.py``). The production implementation is
:class:`app.llm.anthropic_client.AnthropicLLM`.
"""

from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """The model call failed or returned something unusable."""


class LLMNotConfigured(LLMError):
    """No credentials are available for the model provider."""


class LLMClient(Protocol):
    def generate(
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        purpose: str,
        effort: str | None = None,
    ) -> T:
        """Run one model call and parse the reply into ``schema``.

        ``purpose`` is a short machine-readable label (e.g. ``"teach"``) used for logging.
        """
        ...
