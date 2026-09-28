"""ORM models.

Domain overview:

* ``Student`` - the child being tutored, plus a learning profile (which teaching strategies work for them).
* ``Textbook`` -> ``Chapter`` -> ``Topic`` - the curriculum, extracted from an uploaded book.
  ``TextChunk`` holds the raw page text used to ground every explanation and question.
* ``DailyLesson`` - what was taught at school on a given day (chapter + topics + teacher notes).
* ``TutorSession`` - one tuition sitting; drives the teach -> check -> re-teach -> practice -> test flow.
  ``SessionMessage`` is its transcript, ``Question``/``Attempt`` are the assessment record.
* ``TopicMastery`` - per student per topic knowledge state (BKT), ability (for adaptive difficulty),
  misconceptions and spaced-repetition schedule.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    grade: Mapped[int] = mapped_column(Integer)
    # {"strategy_stats": {"real_world_analogy": {"tried": 3, "succeeded": 2}, ...}}
    learning_profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    textbooks: Mapped[list[Textbook]] = relationship(back_populates="student", cascade="all, delete-orphan")


class Textbook(Base):
    __tablename__ = "textbooks"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(300))
    subject: Mapped[str | None] = mapped_column(String(120))
    grade: Mapped[int | None] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(300))
    stored_path: Mapped[str] = mapped_column(String(600))
    # uploaded | processing | ready | failed
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    status_detail: Mapped[str | None] = mapped_column(Text)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    structure_source: Mapped[str | None] = mapped_column(String(30))  # outline | headings | ai
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    student: Mapped[Student] = relationship(back_populates="textbooks")
    chapters: Mapped[list[Chapter]] = relationship(
        back_populates="textbook", cascade="all, delete-orphan", order_by="Chapter.number"
    )
    chunks: Mapped[list[TextChunk]] = relationship(cascade="all, delete-orphan", order_by="TextChunk.page")


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(primary_key=True)
    textbook_id: Mapped[int] = mapped_column(ForeignKey("textbooks.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str | None] = mapped_column(Text)
    start_page: Mapped[int] = mapped_column(Integer)
    end_page: Mapped[int] = mapped_column(Integer)

    textbook: Mapped[Textbook] = relationship(back_populates="chapters")
    topics: Mapped[list[Topic]] = relationship(
        back_populates="chapter", cascade="all, delete-orphan", order_by="Topic.order"
    )


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    order: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str | None] = mapped_column(Text)
    learning_objectives: Mapped[list[str]] = mapped_column(JSON, default=list)
    key_terms: Mapped[list[str]] = mapped_column(JSON, default=list)
    prerequisites: Mapped[list[str]] = mapped_column(JSON, default=list)
    start_page: Mapped[int | None] = mapped_column(Integer)
    end_page: Mapped[int | None] = mapped_column(Integer)

    chapter: Mapped[Chapter] = relationship(back_populates="topics")


class TextChunk(Base):
    """Text of one textbook page (1-indexed)."""

    __tablename__ = "text_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    textbook_id: Mapped[int] = mapped_column(ForeignKey("textbooks.id", ondelete="CASCADE"), index=True)
    page: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)


class DailyLesson(Base):
    __tablename__ = "daily_lessons"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    textbook_id: Mapped[int] = mapped_column(ForeignKey("textbooks.id", ondelete="CASCADE"))
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    topic_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    lesson_date: Mapped[date] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)  # what the teacher covered / homework
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    chapter: Mapped[Chapter] = relationship()


class TutorSession(Base):
    __tablename__ = "tutor_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    daily_lesson_id: Mapped[int | None] = mapped_column(ForeignKey("daily_lessons.id", ondelete="SET NULL"))
    mode: Mapped[str] = mapped_column(String(20), default="lesson")  # lesson | revision
    topic_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    # teach | check | practice | test_ready | test | complete
    phase: Mapped[str] = mapped_column(String(20), default="teach")
    # What input the engine is waiting for: answer | advance | none
    awaiting: Mapped[str] = mapped_column(String(20), default="none")
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)

    messages: Mapped[list[SessionMessage]] = relationship(
        cascade="all, delete-orphan", order_by="SessionMessage.id"
    )
    questions: Mapped[list[Question]] = relationship(cascade="all, delete-orphan", order_by="Question.id")


class SessionMessage(Base):
    __tablename__ = "session_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("tutor_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # tutor | student
    # lesson | reteach | question | feedback | hint | chat | info | summary | answer
    kind: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("tutor_sessions.id", ondelete="CASCADE"), index=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"))
    phase: Mapped[str] = mapped_column(String(20))  # check | practice | test
    qtype: Mapped[str] = mapped_column(String(20))  # mcq | numeric | short
    prompt: Mapped[str] = mapped_column(Text)
    # For mcq: [{"text": ..., "misconception": ...}, ...]
    options: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    answer: Mapped[str] = mapped_column(Text)
    acceptable_answers: Mapped[list[str]] = mapped_column(JSON, default=list)
    tolerance: Mapped[float | None] = mapped_column(Float)
    explanation: Mapped[str] = mapped_column(Text)
    hint: Mapped[str | None] = mapped_column(Text)
    difficulty: Mapped[int] = mapped_column(Integer)  # 1..5
    hints_used: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    attempts: Mapped[list[Attempt]] = relationship(cascade="all, delete-orphan", order_by="Attempt.id")


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    answer: Mapped[str] = mapped_column(Text)
    verdict: Mapped[str] = mapped_column(String(20))  # correct | partial | incorrect
    score: Mapped[float] = mapped_column(Float)
    feedback: Mapped[str] = mapped_column(Text)
    misconception: Mapped[str | None] = mapped_column(Text)
    graded_by: Mapped[str] = mapped_column(String(10))  # rule | ai
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TopicMastery(Base):
    __tablename__ = "topic_mastery"
    __table_args__ = (UniqueConstraint("student_id", "topic_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    # Bayesian Knowledge Tracing: probability the skill is known.
    p_known: Mapped[float] = mapped_column(Float, default=0.2)
    # Logit-scale ability used to pick question difficulty.
    ability: Mapped[float] = mapped_column(Float, default=0.0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    correct: Mapped[int] = mapped_column(Integer, default=0)
    times_taught: Mapped[int] = mapped_column(Integer, default=0)
    misconceptions: Mapped[list[str]] = mapped_column(JSON, default=list)  # most recent last
    last_practiced_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Spaced repetition (SM-2 variant)
    ease: Mapped[float] = mapped_column(Float, default=2.5)
    interval_days: Mapped[float] = mapped_column(Float, default=0.0)
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime)

    topic: Mapped[Topic] = relationship()
