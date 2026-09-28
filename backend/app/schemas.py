"""API request/response models."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- students ----------


class StudentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    grade: int = Field(ge=1, le=12)


class StudentOut(ORM):
    id: int
    name: str
    grade: int
    created_at: datetime


# ---------- curriculum ----------


class TopicOut(ORM):
    id: int
    order: int
    title: str
    summary: str | None
    learning_objectives: list[str]
    key_terms: list[str]
    prerequisites: list[str]
    start_page: int | None
    end_page: int | None


class ChapterOut(ORM):
    id: int
    number: int
    title: str
    summary: str | None
    start_page: int
    end_page: int
    topics: list[TopicOut]


class TextbookOut(ORM):
    id: int
    student_id: int
    title: str
    subject: str | None
    grade: int | None
    filename: str
    status: str
    status_detail: str | None
    progress: float
    page_count: int
    structure_source: str | None
    analysis_mode: str | None
    created_at: datetime


class TextbookDetail(TextbookOut):
    chapters: list[ChapterOut]


# ---------- lessons & sessions ----------


class LessonCreate(BaseModel):
    student_id: int
    chapter_id: int
    topic_ids: list[int] = Field(min_length=1)
    lesson_date: date | None = None
    notes: str | None = Field(default=None, max_length=4000)


class LessonOut(ORM):
    id: int
    student_id: int
    textbook_id: int
    chapter_id: int
    topic_ids: list[int]
    lesson_date: date
    notes: str | None
    created_at: datetime


class SessionCreate(BaseModel):
    student_id: int
    lesson_id: int | None = None
    topic_ids: list[int] | None = None
    mode: str = Field(default="lesson", pattern="^(lesson|revision)$")


class AnswerIn(BaseModel):
    question_id: int
    answer: str = Field(max_length=4000)


class HintIn(BaseModel):
    question_id: int


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class MessageOut(ORM):
    id: int
    role: str
    kind: str
    content: str
    payload: dict[str, Any]
    created_at: datetime


class PendingQuestion(BaseModel):
    id: int
    topic_id: int
    phase: str
    qtype: str
    prompt: str
    options: list[str]
    difficulty: int
    hints_available: bool


class TopicProgress(BaseModel):
    topic_id: int
    title: str
    status: str
    p_known: float


class SessionOut(BaseModel):
    id: int
    student_id: int
    mode: str
    phase: str
    awaiting: str
    started_at: datetime
    ended_at: datetime | None
    topics: list[TopicProgress]
    practice_done: int
    practice_total: int
    test_answered: int
    test_total: int
    pending_question: PendingQuestion | None
    messages: list[MessageOut]
    report: dict[str, Any] | None


class SessionListItem(BaseModel):
    id: int
    mode: str
    phase: str
    started_at: datetime
    ended_at: datetime | None
    topic_titles: list[str]
    test_score: float | None
