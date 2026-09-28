"""Application settings, loaded from environment variables (prefix ``TUTOR_``) or a ``.env`` file."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TUTOR_", env_file=".env", extra="ignore")

    data_dir: Path = BACKEND_DIR / "data"
    database_url: str | None = None  # defaults to sqlite in data_dir

    # Claude model used for all tutoring / curriculum work.
    llm_model: str = "claude-opus-5"
    # Thinking depth. "medium" keeps tutoring turns responsive; curriculum analysis uses llm_effort_analysis.
    llm_effort: str = "medium"
    llm_effort_analysis: str = "high"
    llm_max_tokens: int = 16000
    # Server-side refusal fallback ("default" = Anthropic-routed fallback, "off" = disabled).
    llm_fallbacks: str = "default"

    max_upload_mb: int = 100
    # How much textbook text (characters) to ground a single teaching turn on.
    context_chars_per_topic: int = 24000
    # How much of a chapter (characters) to send when extracting its topics.
    context_chars_per_chapter: int = 120000

    # Session shape.
    check_questions_to_pass: int = Field(2, description="Correct check answers needed to finish a topic")
    max_reteach_per_topic: int = 3
    practice_questions: int = 5
    test_questions: int = 5

    frontend_dist: Path = BACKEND_DIR.parent / "frontend" / "dist"

    @property
    def sqlalchemy_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir / 'tutor.db'}"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"


@lru_cache
def get_settings() -> Settings:
    return Settings()
