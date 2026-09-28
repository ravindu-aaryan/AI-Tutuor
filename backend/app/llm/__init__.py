from .base import LLMClient, LLMError, LLMNotConfigured

__all__ = ["LLMClient", "LLMError", "LLMNotConfigured", "get_llm", "set_llm"]

_override: LLMClient | None = None
_default: LLMClient | None = None


def set_llm(client: LLMClient | None) -> None:
    """Install a specific client (used by tests)."""
    global _override
    _override = client


def get_llm() -> LLMClient:
    global _default
    if _override is not None:
        return _override
    if _default is None:
        from ..config import get_settings
        from .anthropic_client import AnthropicLLM, credentials_available

        if not credentials_available():
            raise LLMNotConfigured(
                "No Anthropic credentials found. Set ANTHROPIC_API_KEY (or run `ant auth login`) "
                "and restart the server."
            )
        s = get_settings()
        _default = AnthropicLLM(
            model=s.llm_model, effort=s.llm_effort, max_tokens=s.llm_max_tokens, fallbacks=s.llm_fallbacks
        )
    return _default


def llm_status() -> dict[str, object]:
    from ..config import get_settings

    if _override is not None:
        return {"configured": True, "model": "override"}
    from .anthropic_client import credentials_available

    return {"configured": credentials_available(), "model": get_settings().llm_model}
