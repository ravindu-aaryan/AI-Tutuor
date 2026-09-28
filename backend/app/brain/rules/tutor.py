"""The offline tutor: teaches, questions, re-teaches and reports using only the textbook text and rules."""

from __future__ import annotations

import difflib
import random
import re
from typing import Any

from ...tutor.grading import parse_number
from ...tutor.prompts import AnswerEvaluation, ChatReply, QuestionDraft, ReteachOutput, SessionSummary, TeachOutput
from ..base import MissedQuestion, TopicContext
from . import maths
from .questions import TopicMaterial, make_question, material
from .text import best_matches, content_stems, overlap, stem

CONFUSED = re.compile(
    r"(don'?t|do not|didn'?t|did not|can'?t|cannot) (really )?(understand|get)|confus|explain (it |that |this )?again|"
    r"i'?m lost|no idea|makes no sense|too hard|what\?+$|^huh",
    re.IGNORECASE,
)
WANTS_ANSWER = re.compile(r"(what'?s|what is|tell me|give me|just say)( me)? the (answer|solution)", re.IGNORECASE)
SMALL_TALK = re.compile(r"^\s*(hi|hello|hey|thanks|thank you|ok|okay|cool|yes|no|bye)\b[\s!.]*$", re.IGNORECASE)


def _page_ref(page: int | None) -> str:
    return f" *(page {page})*" if page else ""


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{round(v * 100)}%"


class RuleTutorBrain:
    name = "rules"
    strategies = ["worked_example", "step_by_step", "visual_description", "contrast_mistake", "simpler_language"]
    context_scale = 1.0

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _rng(*parts: object) -> random.Random:
        return random.Random("|".join(map(str, parts)))

    @staticmethod
    def _material(ctx: TopicContext) -> TopicMaterial:
        return material(ctx.title, ctx.summary, ctx.excerpt, ctx.key_terms, ctx.start_page, ctx.end_page)

    def _question(self, ctx: TopicContext, m: TopicMaterial, difficulty: int, previous: list[str]) -> QuestionDraft:
        rng = self._rng(ctx.title, len(previous), difficulty, "q")
        return make_question(m, difficulty, previous, rng, ctx.related_terms)

    @staticmethod
    def _example_calc(m: TopicMaterial, rng: random.Random, difficulty: int = 2) -> maths.Expression | None:
        if not m.calculations:
            return None
        printed = [e for e, ans in m.calculations if ans]
        if printed:
            return rng.choice(printed)
        return maths.generate_like(m.calculations[0][0], difficulty, rng)

    @staticmethod
    def _worked(expr: maths.Expression, with_picture: bool = True) -> str:
        steps = maths.solution_steps(expr)
        answer, _ = maths.answer_forms(expr.value(), expr)
        body = f"**{expr.text} = ?**\n\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1)) + f"\n\nAnswer: **{answer}**"
        pic = maths.picture(expr) if with_picture else None
        return body + (f"\n\n{pic}" if pic else "")

    # ------------------------------------------------------------------ teaching

    def teach(self, ctx: TopicContext, *, recap: bool, difficulty: int, previous: list[str]) -> TeachOutput:
        m = self._material(ctx)
        rng = self._rng(ctx.title, "teach", len(previous))
        parts: list[str] = []
        if recap:
            parts.append("You already know this topic quite well, so here's a quick recap.")
        if ctx.lesson_notes and not recap:
            parts.append(f"You said that in class today: *{ctx.lesson_notes}*. Let's go through it together.")
        if ctx.summary:
            parts.append(ctx.summary)
        key = m.key_sentences[: 3 if recap else 5]
        if key:
            parts.append("**What your textbook says**\n\n" + "\n".join(f"- {s.text}{_page_ref(s.page)}" for s in key))
        if m.definitions:
            rows = "\n".join(f"| **{d.term}** | {d.sentence} |" for d in m.definitions[:5])
            parts.append("**Key words**\n\n| Word | What it means |\n|---|---|\n" + rows)
        if ctx.start_page:
            end = f"–{ctx.end_page}" if ctx.end_page and ctx.end_page != ctx.start_page else ""
            parts.append(f"📖 Follow along in your textbook on page {ctx.start_page}{end}.")
        if not key and not m.definitions:
            parts.append("I couldn't find much text for this topic in the book, so read the pages above first, then try the questions.")

        expr = self._example_calc(m, rng)
        if expr is not None:
            example = self._worked(expr)
        elif m.definitions:
            d = m.definitions[0]
            example = f"From your book{_page_ref(d.page)}:\n\n> {d.sentence}\n\nThe key word here is **{d.term}**. Try saying the sentence in your own words."
        elif key:
            example = f"From your book{_page_ref(key[0].page)}:\n\n> {key[0].text}"
        else:
            example = "Look at the first worked example on these pages of your textbook."

        points = list(ctx.learning_objectives[:4]) or [f"{d.term}: {d.sentence}" for d in m.definitions[:3]]
        return TeachOutput(
            explanation="\n\n".join(parts),
            worked_example=example,
            key_points=points,
            question=self._question(ctx, m, difficulty, previous),
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
        m = self._material(ctx)
        rng = self._rng(ctx.title, strategy, len(previous))
        expr = maths.parse_expression(missed.prompt.replace("*", "")) if missed and missed.qtype == "numeric" else None

        misconception = None
        if missed is None:
            what = "No problem - let's try explaining it a different way."
        elif expr is not None:
            value = parse_number(student_answer)
            diag = maths.diagnose(expr, value) if value is not None else None
            misconception = diag.split(".")[0] if diag else None
            what = f"You wrote **{student_answer}**, but {expr.text} = **{missed.answer}**. " + (diag or "Let's go through the working together.")
        else:
            other = next((d for d in m.definitions if d.term == student_answer.strip().lower()), None)
            if other:
                misconception = f"Confuses '{other.term}' with '{missed.answer}'"
                what = f"“{student_answer}” is a different idea: {other.sentence} The answer we needed was **{missed.answer}**."
            else:
                what = f"The answer we were looking for was **{missed.answer}**."

        example_expr = expr or (self._example_calc(m, rng, max(1, difficulty - 1)) if m.is_maths else None)
        explanation = self._strategy_text(strategy, m, example_expr, missed, student_answer, rng, difficulty)
        return ReteachOutput(
            what_went_wrong=what,
            misconception=misconception,
            explanation=explanation,
            question=self._question(ctx, m, difficulty, previous),
        )

    def _strategy_text(
        self,
        strategy: str,
        m: TopicMaterial,
        expr: maths.Expression | None,
        missed: MissedQuestion | None,
        student_answer: str,
        rng: random.Random,
        difficulty: int,
    ) -> str:
        if expr is not None:
            if strategy == "worked_example":
                fresh = maths.generate_like(expr, max(1, difficulty - 1), rng)
                return "Here's another one, worked all the way through:\n\n" + self._worked(fresh)
            if strategy == "step_by_step":
                steps = maths.solution_steps(expr)
                return "Let's go slowly, one step at a time:\n\n" + "\n".join(
                    f"**Step {i}.** {s}" for i, s in enumerate(steps, 1)
                )
            if strategy == "visual_description":
                pic = maths.picture(expr) or maths.picture(maths.generate_like(expr, 1, rng))
                if pic:
                    return "Let's picture it:\n\n" + pic
                return self._strategy_text("step_by_step", m, expr, missed, student_answer, rng, difficulty)
            if strategy == "contrast_mistake":
                value = parse_number(student_answer) if student_answer else None
                diag = maths.diagnose(expr, value) if value is not None else None
                wrong = f"❌ **The tempting way:** {diag}\n\n" if diag else ""
                return wrong + "✅ **The right way:**\n\n" + self._worked(expr, with_picture=False)
            return self._simple_rule(expr) + "\n\n" + self._worked(maths.generate_like(expr, 1, rng), with_picture=False)

        # Text topics
        defs = m.definitions
        target = next((d for d in defs if missed and d.term == missed.answer.lower()), defs[0] if defs else None)
        if strategy == "worked_example":
            others = [s for s in m.key_sentences if not target or s.text != target.sentence][:3]
            if target:
                lines = [f"Here is how your book uses **{target.term}**:", f"> {target.sentence}{_page_ref(target.page)}"]
            else:
                lines = ["Here are the most important sentences again:"]
            lines += [f"> {s.text}{_page_ref(s.page)}" for s in others]
            return "\n\n".join(lines)
        if strategy == "step_by_step" and target:
            pieces = [p.strip() for p in re.split(r",|;| which | that | and ", target.sentence) if len(p.split()) >= 2]
            return f"Let's break down what **{target.term}** means:\n\n" + "\n".join(f"{i}. {p}" for i, p in enumerate(pieces, 1))
        if strategy == "visual_description" and defs:
            rows = "\n".join(f"| **{d.term}** | {d.sentence} | {d.page or ''} |" for d in defs[:6])
            return "Here's a table to picture how the ideas fit together:\n\n| Word | Meaning | Page |\n|---|---|---|\n" + rows
        if strategy == "contrast_mistake" and target:
            other = next((d for d in defs if d.term == student_answer.strip().lower()), None)
            if other:
                return (
                    f"These two are easy to mix up:\n\n| **{other.term}** | **{target.term}** |\n|---|---|\n"
                    f"| {other.sentence} | {target.sentence} |"
                )
            return f"Remember: **{target.term}** — {target.sentence}"
        # simpler_language (and fallback)
        chosen = [target.sentence] if target else [s.text for s in m.key_sentences[:3]]
        short: list[str] = []
        for sentence in chosen:
            short += [p.strip().rstrip(".") + "." for p in re.split(r",|;| which | because | so that ", sentence) if len(p.split()) >= 3]
        if not short:
            return "Let's read the textbook pages for this topic again slowly, then try another question."
        text = "In simple words:\n\n" + "\n".join(f"- {s[0].upper()}{s[1:]}" for s in short[:6])
        for d in defs[:6]:
            text = re.sub(rf"\b({re.escape(d.term)})\b", r"**\1**", text, count=1, flags=re.IGNORECASE)
        return text

    @staticmethod
    def _simple_rule(expr: maths.Expression) -> str:
        op = expr.ops[0]
        if expr.is_fraction and op in "+−":
            return ("**The rule in simple words:**\n1. Look at the bottom numbers (denominators).\n"
                    "2. If they are different, change the fractions so they are the same.\n"
                    f"3. Keep the bottom number. {maths.OP_WORD[op].capitalize()} only the top numbers.\n4. Simplify if you can.")
        if expr.is_fraction and op == "×":
            return "**The rule in simple words:** top × top, bottom × bottom, then simplify."
        if expr.is_fraction and op == "÷":
            return "**The rule in simple words:** keep the first fraction, flip the second one, then multiply."
        if len(expr.ops) > 1:
            return "**The rule in simple words:** first do every × and ÷, then do + and − from left to right."
        return f"**The rule in simple words:** we need to {maths.OP_WORD[op]}. Take it one digit (column) at a time."

    def question(self, ctx: TopicContext, *, difficulty: int, previous: list[str]) -> QuestionDraft:
        return self._question(ctx, self._material(ctx), difficulty, previous)

    def test_paper(self, sections: list[tuple[TopicContext, list[int]]], *, learner_desc: str, previous: list[str]) -> list[QuestionDraft]:
        seen = list(previous)
        out: list[QuestionDraft] = []
        for ctx, levels in sections:
            m = self._material(ctx)
            for level in levels:
                q = self._question(ctx, m, level, seen)
                seen.append(q.prompt[:200])
                out.append(q)
        return out

    # ------------------------------------------------------------------ marking & chat

    def evaluate(self, ctx: TopicContext, *, question: str, model_answer: str, acceptable: list[str], student_answer: str) -> AnswerEvaluation:
        references = [model_answer, *acceptable]
        short_ref = len(model_answer.split()) <= 4
        if short_ref:  # a single word/phrase answer: be forgiving about spelling only
            ratio = max(difflib.SequenceMatcher(None, r.lower(), student_answer.lower().strip()).ratio() for r in references)
            if ratio >= 0.8:
                return AnswerEvaluation(verdict="correct", score=1.0, feedback=f"Yes! (Watch the spelling: **{model_answer}**.)", misconception=None)
            other = next((t for t in ctx.key_terms + ctx.related_terms if t.lower() == student_answer.strip().lower()), None)
            return AnswerEvaluation(
                verdict="incorrect",
                score=0.0,
                feedback=f"Not quite - the answer is **{model_answer}**.",
                misconception=f"Confuses '{other}' with '{model_answer}'" if other else None,
            )
        score = max(overlap(r, student_answer) for r in references)
        missing = sorted(content_stems(model_answer) - content_stems(student_answer))
        # Show missing ideas as real words from the model answer, not stems.
        missing_words = [w for w in re.findall(r"[A-Za-z]+", model_answer) if stem(w.lower()) in missing]
        missing_text = ", ".join(dict.fromkeys(w.lower() for w in missing_words))[:160]
        if score >= 0.6:
            return AnswerEvaluation(verdict="correct", score=1.0, feedback="Yes - you've got the key idea.", misconception=None)
        if score >= 0.3:
            return AnswerEvaluation(
                verdict="partial", score=round(score, 2),
                feedback=f"You're on the right track. A full answer also mentions: {missing_text}.", misconception=None,
            )
        return AnswerEvaluation(
            verdict="incorrect", score=round(score, 2),
            feedback=f"That doesn't match the key idea yet. Look for these words in the lesson: {missing_text}.",
            misconception=None,
        )

    def chat(self, ctx: TopicContext, *, transcript: str, pending_question: str | None, message: str) -> ChatReply:
        confused = bool(CONFUSED.search(message))
        if confused:
            return ChatReply(reply="No problem at all - let's look at it another way. 🙂", student_is_confused=True)
        if pending_question and WANTS_ANSWER.search(message):
            return ChatReply(
                reply="I can't give you the answer - but you can do it! Press **💡 Hint** for a nudge, or look back at the worked example above.",
                student_is_confused=False,
            )
        if SMALL_TALK.match(message):
            return ChatReply(reply="😊 Whenever you're ready, carry on with the question - or ask me about anything in the lesson.", student_is_confused=False)

        m = self._material(ctx)
        lower = message.lower()
        term_hits = [d for d in m.definitions if d.term in lower]
        lines: list[str] = []
        for d in term_hits[:2]:
            lines.append(f"**{d.term.capitalize()}**: {d.sentence}{_page_ref(d.page)}")
        if not term_hits:
            for s in best_matches(message, ctx.excerpt, 2):
                lines.append(f"> {s.text}{_page_ref(s.page)}")
        if not lines:
            reply = ("I couldn't find that in this part of your textbook. I'm in offline mode, so I can only answer from "
                     "the book. Try using the key words from the lesson, or ask your teacher tomorrow!")
        else:
            reply = "Here's what your textbook says about that:\n\n" + "\n\n".join(lines)
        return ChatReply(reply=reply, student_is_confused=False)

    def summary(self, *, learner_desc: str, student_name: str, grade: int, facts: str, report: dict[str, Any]) -> SessionSummary:
        topics = report["topics"]
        score = report["overall"]["test_score"]
        weakest = min(topics, key=lambda t: t["mastery_end"])["title"] if topics else "these topics"
        if score is None:
            msg = f"Great effort today, {student_name}!"
        elif score >= 0.8:
            msg = f"Fantastic work, {student_name}! You scored {_pct(score)} on the test. 🌟"
        elif score >= 0.5:
            msg = f"Good effort, {student_name}! You scored {_pct(score)}. A bit more practice on **{weakest}** and you'll have it."
        else:
            msg = f"Well done for sticking with it, {student_name}. These ideas are tricky - we'll go over **{weakest}** again soon."
        strengths = [f"{t['title']} ({_pct(t['test_score'])} on the test)" for t in topics if t["mastery_label"] == "mastered" or (t["test_score"] or 0) >= 0.8]
        improve = [f"{t['title']}" for t in topics if t["mastery_label"] != "mastered"]
        improve += [f"Watch out for: {mc}" for t in topics for mc in t["misconceptions"][:2]]
        steps = [f"Revise **{t['title']}** on {t['next_review_at'][:10]}" for t in topics if t["next_review_at"]]
        return SessionSummary(
            message_for_student=msg,
            summary_for_parent=facts,
            strengths=strengths or ["Kept going through the whole session"],
            areas_to_improve=improve or ["Nothing major - keep practising"],
            recommended_next_steps=steps,
        )

