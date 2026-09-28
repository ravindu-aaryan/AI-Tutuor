"""Settings the user can change from the app (stored in the database), e.g. which tutor brain to use."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .models import AppSetting

Provider = Literal["rules", "local", "claude"]


class AISettings(BaseModel):
    # rules = offline, no AI at all (free); local = open model via Ollama (free); claude = Anthropic API (paid)
    provider: Provider = "rules"
    local_url: str = Field(default="http://localhost:11434", max_length=300)
    local_model: str = Field(default="qwen2.5:7b", max_length=120)


KEY = "ai"


def get_ai_settings(db: Session) -> AISettings:
    row = db.get(AppSetting, KEY)
    return AISettings.model_validate(row.value) if row else AISettings()


def save_ai_settings(db: Session, value: AISettings) -> AISettings:
    row = db.get(AppSetting, KEY)
    data: dict[str, Any] = value.model_dump()
    if row is None:
        db.add(AppSetting(key=KEY, value=data))
    else:
        row.value = data
    db.commit()
    return value
