"""A scripted stand-in for Claude, used only by the test-suite.

It produces schema-valid, deterministic outputs so the full pipeline (ingestion -> tutoring -> report) can
be exercised offline. Every call is recorded in ``calls`` for assertions.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from app.ingestion.curriculum import BookOverview, BookSegmentation, ChapterAnalysis, ChapterStart, TopicDraft
from app.tutor import prompts as p


def numeric_q(n: int, difficulty: int = 2) -> p.QuestionDraft:
    return p.QuestionDraft(
        qtype="numeric",
        prompt=f"Q{n}: What is {n} + 1?",
        options=[],
        answer=str(n + 1),
        acceptable_answers=[],
        tolerance=None,
        explanation=f"{n} + 1 = {n + 1}",
        hint="Count on by one.",
        difficulty=difficulty,
    )


def mcq_q(n: int) -> p.QuestionDraft:
    return p.QuestionDraft(
        qtype="mcq",
        prompt=f"Q{n}: Which fraction is equal to one half?",
        options=[
            p.OptionDraft(text="2/4", misconception=None),
            p.OptionDraft(text="1/3", misconception="Thinks a bigger denominator means a bigger fraction"),
            p.OptionDraft(text="2/3", misconception="Adds one to both parts"),
            p.OptionDraft(text="3/4", misconception="Guessing"),
        ],
        answer="2/4",
        acceptable_answers=[],
        tolerance=None,
        explanation="2/4 simplifies to 1/2.",
        hint="Simplify each fraction.",
        difficulty=2,
    )


def short_q(n: int) -> p.QuestionDraft:
    return p.QuestionDraft(
        qtype="short",
        prompt=f"Q{n}: What do we call the bottom number of a fraction?",
        options=[],
        answer="denominator",
        acceptable_answers=["the denominator"],
        tolerance=None,
        explanation="The bottom number is the denominator.",
        hint="It starts with 'd'.",
        difficulty=2,
    )


class FakeLLM:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.counter = 0
        # Queue of question kinds to hand out next ("numeric" | "mcq" | "short"); defaults to numeric.
        self.question_kinds: list[str] = []
        self.fail_purposes: set[str] = set()

    def next_question(self, difficulty: int = 2) -> p.QuestionDraft:
        self.counter += 1
        kind = self.question_kinds.pop(0) if self.question_kinds else "numeric"
        if kind == "mcq":
            return mcq_q(self.counter)
        if kind == "short":
            return short_q(self.counter)
        return numeric_q(self.counter, difficulty)

    def generate(self, *, system: str, prompt: str, schema: type[BaseModel], purpose: str, effort: str | None = None):
        self.calls.append({"purpose": purpose, "prompt": prompt, "system": system})
        if purpose in self.fail_purposes:
            from app.llm import LLMError

            raise LLMError(f"scripted failure for {purpose}")

        if schema is BookSegmentation:
            starts = []
            for m in re.finditer(r"\[\[Page (\d+)\]\] ([^\n]*)", prompt):
                if "section" in m.group(2).lower():
                    starts.append(ChapterStart(title=m.group(2)[:40], start_page=int(m.group(1))))
            return BookSegmentation(chapters=starts)
        if schema is BookOverview:
            return BookOverview(title="Maths Made Easy", subject="Mathematics", grade=5)
        if schema is ChapterAnalysis:
            m = re.search(r"\(pages (\d+)-(\d+)\)", prompt)
            a, b = int(m.group(1)), int(m.group(2))
            title = re.search(r"Chapter: (.*?) \(pages", prompt).group(1)
            return ChapterAnalysis(
                title=title,
                summary=f"About {title}.",
                topics=[
                    TopicDraft(title=f"{title} - basics", summary="Basics.", learning_objectives=["Student can do basics"],
                               key_terms=["fraction"], prerequisites=[], start_page=a, end_page=a),
                    TopicDraft(title=f"{title} - more", summary="More.", learning_objectives=["Student can do more"],
                               key_terms=["numerator"], prerequisites=[], start_page=b, end_page=b + 50),
                ],
            )
        if schema is p.TeachOutput:
            return p.TeachOutput(explanation="Here is how it works.", worked_example="1 + 1 = 2", key_points=["Add carefully"],
                                 question=self.next_question())
        if schema is p.ReteachOutput:
            return p.ReteachOutput(what_went_wrong="You added two instead of one.", misconception="adds wrong amount",
                                   explanation="Think of steps on a number line.", question=self.next_question())
        if schema is p.QuestionOnly:
            return p.QuestionOnly(question=self.next_question())
        if schema is p.TestPaper:
            n = int(re.search(r"exactly (\d+) questions", prompt).group(1))
            return p.TestPaper(questions=[self.next_question() for _ in range(n)])
        if schema is p.AnswerEvaluation:
            ans = re.search(r"Student's answer: (.*)", prompt).group(1)
            if "good" in ans:
                return p.AnswerEvaluation(verdict="correct", score=1.0, feedback="Well explained!", misconception=None)
            if "half" in ans:
                return p.AnswerEvaluation(verdict="partial", score=0.5, feedback="Nearly.", misconception=None)
            return p.AnswerEvaluation(verdict="incorrect", score=0.0, feedback="That's not it.", misconception="confuses terms")
        if schema is p.ChatReply:
            msg = re.search(r'The student says: "(.*)"', prompt).group(1)
            return p.ChatReply(reply=f"Good question about: {msg}", student_is_confused="don't understand" in msg)
        if schema is p.SessionSummary:
            return p.SessionSummary(message_for_student="Great work today!", summary_for_parent="Solid session.",
                                    strengths=["Adding"], areas_to_improve=["Speed"], recommended_next_steps=["Revise"])
        raise AssertionError(f"FakeLLM has no script for {schema.__name__}")
