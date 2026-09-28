"""Brain backed by a language model (Claude via the API, or a local model via Ollama)."""

from __future__ import annotations

from typing import Any

from ..ingestion import curriculum
from ..ingestion.curriculum import BookOverview, ChapterAnalysis
from ..ingestion.extract import ExtractedDocument
from ..ingestion.structure import ChapterSpan
from ..llm import LLMClient, LLMError
from ..tutor import prompts
from ..tutor.prompts import AnswerEvaluation, ChatReply, QuestionDraft, ReteachOutput, SessionSummary, TeachOutput
from .base import MissedQuestion, TopicContext


class LLMTutorBrain:
    strategies = list(prompts.STRATEGIES)

    def __init__(self, llm: LLMClient, *, name: str = "claude", context_scale: float = 1.0) -> None:
        self.llm = llm
        self.name = name
        self.context_scale = context_scale

    def _gen(self, ctx_grade: int, prompt: str, schema, purpose: str):
        return self.llm.generate(system=prompts.tutor_system(ctx_grade), prompt=prompt, schema=schema, purpose=purpose)

    def teach(self, ctx: TopicContext, *, recap: bool, difficulty: int, previous: list[str]) -> TeachOutput:
        return self._gen(
            ctx.grade,
            prompts.teach_prompt(ctx.topic_desc, ctx.learner_desc, ctx.excerpt, recap=recap, difficulty=difficulty, previous=previous),
            prompts.TeachOutput,
            "teach",
        )

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
    ) -> ReteachOutput:
        return self._gen(
            ctx.grade,
            prompts.reteach_prompt(
                ctx.topic_desc,
                ctx.learner_desc,
                ctx.excerpt,
                question=missed.prompt if missed else "",
                correct_answer=missed.answer if missed else "",
                student_answer=student_answer,
                strategy=strategy,
                difficulty=difficulty,
                previous=previous,
                reason=reason,
            ),
            prompts.ReteachOutput,
            "reteach",
        )

    def question(self, ctx: TopicContext, *, difficulty: int, previous: list[str]) -> QuestionDraft:
        return self._gen(
            ctx.grade,
            prompts.practice_prompt(ctx.topic_desc, ctx.learner_desc, ctx.excerpt, difficulty=difficulty, previous=previous),
            prompts.QuestionOnly,
            "question",
        ).question

    def test_paper(self, sections: list[tuple[TopicContext, list[int]]], *, learner_desc: str, previous: list[str]) -> list[QuestionDraft]:
        blocks = []
        for i, (ctx, levels) in enumerate(sections, start=1):
            half = ctx.excerpt[: max(2000, len(ctx.excerpt) // 2)]
            block = f"<topic_{i}>\n{ctx.topic_desc}\n\n<textbook_excerpt>\n{half}\n</textbook_excerpt>\n</topic_{i}>"
            blocks.append((block, ctx.title, levels))
        paper = self._gen(sections[0][0].grade, prompts.test_prompt(blocks, learner_desc, previous), prompts.TestPaper, "test")
        if not paper.questions:
            raise LLMError("The test could not be prepared - please try again.")
        return paper.questions

    def evaluate(self, ctx: TopicContext, *, question: str, model_answer: str, acceptable: list[str], student_answer: str) -> AnswerEvaluation:
        return self._gen(
            ctx.grade,
            prompts.evaluate_prompt(
                ctx.topic_desc, question=question, model_answer=model_answer, acceptable=acceptable,
                student_answer=student_answer, grade=ctx.grade,
            ),
            prompts.AnswerEvaluation,
            "evaluate",
        )

    def chat(self, ctx: TopicContext, *, transcript: str, pending_question: str | None, message: str) -> ChatReply:
        return self._gen(
            ctx.grade,
            prompts.chat_prompt(ctx.topic_desc, ctx.learner_desc, ctx.excerpt, transcript=transcript,
                                pending_question=pending_question, message=message),
            prompts.ChatReply,
            "chat",
        )

    def summary(self, *, learner_desc: str, student_name: str, grade: int, facts: str, report: dict[str, Any]) -> SessionSummary:
        return self._gen(grade, prompts.summary_prompt(learner_desc, facts), prompts.SessionSummary, "summary")


class LLMCurriculumBrain:
    def __init__(self, llm: LLMClient, *, name: str, chapter_chars: int, effort: str) -> None:
        self.llm = llm
        self.name = name
        self.chapter_chars = chapter_chars
        self.effort = effort

    def segment(self, doc: ExtractedDocument) -> list[ChapterSpan]:
        return curriculum.segment_with_ai(self.llm, doc, self.effort)

    def overview(self, doc: ExtractedDocument, chapters: list[ChapterSpan], filename: str) -> BookOverview:
        return curriculum.book_overview(self.llm, doc, chapters, filename)

    def analyze_chapter(self, doc: ExtractedDocument, span: ChapterSpan, *, subject: str | None, grade: int | None) -> ChapterAnalysis:
        return curriculum.analyze_chapter(
            self.llm, doc, span, subject=subject, grade=grade, max_chars=self.chapter_chars, effort=self.effort
        )
