from fastapi import HTTPException

from ..llm import LLMClient, LLMNotConfigured, get_llm


def require_llm() -> LLMClient:
    try:
        return get_llm()
    except LLMNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
