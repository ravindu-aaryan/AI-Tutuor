"""Choose the tutor brain from the user's settings (offline rules, local model, or Claude)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .. import llm as llm_mod
from ..config import get_settings
from ..runtime_settings import AISettings, get_ai_settings
from .base import CurriculumBrain, MissedQuestion, TopicContext, TutorBrain

__all__ = ["CurriculumBrain", "MissedQuestion", "TopicContext", "TutorBrain", "brain_status", "get_curriculum_brain", "get_tutor_brain"]

# A local 7-8B model has a much smaller useful context than Claude, so send it less text per call.
LOCAL_CONTEXT_SCALE = 0.5
LOCAL_CHAPTER_CHARS = 24000


def _model(ai: AISettings):
    """The LLMClient for an AI provider (``None`` for the offline brain). Tests may install an override."""
    if llm_mod._override is not None:
        return llm_mod._override
    if ai.provider == "claude":
        return llm_mod.get_llm()  # raises LLMNotConfigured without credentials
    if ai.provider == "local":
        from ..llm.ollama_client import OllamaLLM

        return OllamaLLM(base_url=ai.local_url, model=ai.local_model)
    return None


def get_tutor_brain(db: Session) -> TutorBrain:
    from .llm_brain import LLMTutorBrain
    from .rules.tutor import RuleTutorBrain

    ai = get_ai_settings(db)
    model = _model(ai)
    if model is None:
        return RuleTutorBrain()
    if ai.provider == "local" and llm_mod._override is None:
        return LLMTutorBrain(model, name="local", context_scale=LOCAL_CONTEXT_SCALE)
    return LLMTutorBrain(model, name="claude")


def get_curriculum_brain(db: Session) -> CurriculumBrain:
    from .llm_brain import LLMCurriculumBrain
    from .rules.curriculum import RuleCurriculumBrain

    ai = get_ai_settings(db)
    model = _model(ai)
    s = get_settings()
    if model is None:
        return RuleCurriculumBrain()
    if ai.provider == "local" and llm_mod._override is None:
        return LLMCurriculumBrain(model, name="local", chapter_chars=LOCAL_CHAPTER_CHARS, effort=s.llm_effort_analysis)
    return LLMCurriculumBrain(model, name="claude", chapter_chars=s.context_chars_per_chapter, effort=s.llm_effort_analysis)


def brain_status(db: Session) -> dict[str, Any]:
    """Which brains are usable right now, for the settings screen."""
    from ..llm.anthropic_client import credentials_available
    from ..llm.ollama_client import ollama_status

    ai = get_ai_settings(db)
    local_ok, local_detail = ollama_status(ai.local_url, ai.local_model)
    claude_ok = credentials_available()
    return {
        "settings": ai.model_dump(),
        "providers": {
            "rules": {"available": True, "detail": "Always available - works offline, no cost."},
            "local": {"available": local_ok, "detail": local_detail},
            "claude": {
                "available": claude_ok,
                "detail": f"Ready: {get_settings().llm_model}" if claude_ok else "Set ANTHROPIC_API_KEY on the server and restart it.",
            },
        },
    }
