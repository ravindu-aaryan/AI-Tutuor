"""The "tutor brain": everything in tutoring that needs judgement or language.

The session engine and the textbook pipeline only talk to these two interfaces, so the whole app works with
any of the three implementations:

* ``rules``  - :mod:`app.brain.rules` - fully offline, no AI, zero cost.
* ``local``  - :class:`app.brain.llm_brain.LLMTutorBrain` over a local Ollama model - free, runs on the user's PC.
* ``claude`` - the same class over the Anthropic API - best quality, paid per use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..ingestion.curriculum import BookOverview, ChapterAnalysis
from ..ingestion.extract import ExtractedDocument
from ..ingestion.structure import ChapterSpan
from ..tutor.prompts import AnswerEvaluation, ChatReply, QuestionDraft, ReteachOutput, SessionSummary, TeachOutput


@dataclass
class TopicContext:
    """Everything known about the topic being tutored and the learner, for one brain call."""

    title: str
    chapter_title: str
    summary: str
    learning_objectives: list[str]
    key_terms: list[str]
    start_page: int | None
    end_page: int | None
    topic_desc: str  # the same information rendered as text (for AI brains)
    learner_desc: str
    excerpt: str  # textbook text with [[Page N]] markers
    grade: int
    student_name: str
    lesson_notes: str | None = None
    misconceptions: list[str] = field(default_factory=list)
    #: Key terms of neighbouring topics (used by the offline brain for plausible wrong options).
    related_terms: list[str] = field(default_factory=list)


@dataclass
class MissedQuestion:
    prompt: str
    answer: str
    qtype: str
    explanation: str


class TutorBrain(Protocol):
    name: str
    #: Teaching strategies this brain can actually carry out (subset of ``prompts.STRATEGIES``).
    strategies: list[str]
    #: Multiplier for how much textbook text to send per call (smaller context for small local models).
    context_scale: float

    def teach(self, ctx: TopicContext, *, recap: bool, difficulty: int, previous: list[str]) -> TeachOutput: ...

    def reteach(
        self,
        ctx: TopicContext,
        *,
        missed: MissedQuestion | None,
        student_answer: str,
        strategy: str,
        difficulty: int,
        previous: list[str],
        reason: str,
    ) -> ReteachOutput: ...

    def question(self, ctx: TopicContext, *, difficulty: int, previous: list[str]) -> QuestionDraft: ...

    def test_paper(
        self, sections: list[tuple[TopicContext, list[int]]], *, learner_desc: str, previous: list[str]
    ) -> list[QuestionDraft]:
        """Questions in plan order: for each section, one question per requested difficulty."""
        ...

    def evaluate(
        self, ctx: TopicContext, *, question: str, model_answer: str, acceptable: list[str], student_answer: str
    ) -> AnswerEvaluation: ...

    def chat(self, ctx: TopicContext, *, transcript: str, pending_question: str | None, message: str) -> ChatReply: ...

    def summary(self, *, learner_desc: str, student_name: str, grade: int, facts: str, report: dict[str, Any]) -> SessionSummary: ...


class CurriculumBrain(Protocol):
    name: str
    #: Largest amount of chapter text (characters) to analyse in one go.
    chapter_chars: int

    def segment(self, doc: ExtractedDocument) -> list[ChapterSpan]: ...

    def overview(self, doc: ExtractedDocument, chapters: list[ChapterSpan], filename: str) -> BookOverview: ...

    def analyze_chapter(
        self, doc: ExtractedDocument, span: ChapterSpan, *, subject: str | None, grade: int | None
    ) -> ChapterAnalysis: ...
