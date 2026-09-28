"""End-of-session learning report and revision scheduling."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..llm import LLMClient, LLMError
from ..models import Attempt, DailyLesson, Question, Student, Topic, TutorSession
from . import knowledge, prompts
from .context import describe_learner

log = logging.getLogger(__name__)


def build_report(
    db: Session,
    session: TutorSession,
    student: Student,
    state: dict[str, Any],
    llm: LLMClient,
    lesson: DailyLesson | None,
) -> dict[str, Any]:
    from .engine import get_mastery

    questions = {q.id: q for q in session.questions}
    attempts = db.scalars(select(Attempt).where(Attempt.question_id.in_(list(questions)))).all()
    by_topic: dict[int, list[tuple[Question, Attempt]]] = defaultdict(list)
    for a in attempts:
        by_topic[a.topic_id].append((questions[a.question_id], a))

    topics_out = []
    for tid in session.topic_ids:
        topic = db.get(Topic, tid)
        assert topic is not None
        items = by_topic.get(tid, [])
        test_items = [a for q, a in items if q.phase == "test"]
        learn_items = [a for q, a in items if q.phase != "test"]
        accuracy = _mean([a.score for _, a in items])
        test_score = _mean([a.score for a in test_items])
        ts = state["topics"][str(tid)]

        mastery = get_mastery(db, student.id, tid)
        basis = test_score if test_score is not None else accuracy
        quality = round(5 * basis) if basis is not None else 2
        if ts["status"] == "needs_followup":
            quality = min(quality, 2)
        knowledge.schedule_review(mastery, quality)

        topics_out.append(
            {
                "topic_id": tid,
                "title": topic.title,
                "chapter": topic.chapter.title,
                "status": ts["status"],
                "mastery_start": round(ts["mastery_start"], 3),
                "mastery_end": round(mastery.p_known, 3),
                "mastery_label": knowledge.mastery_label(mastery.p_known),
                "questions": len(items),
                "correct": sum(1 for _, a in items if a.verdict == "correct"),
                "accuracy": accuracy,
                "learning_accuracy": _mean([a.score for a in learn_items]),
                "test_score": test_score,
                "reteach_count": ts["reteach_count"],
                "strategies_used": ts["strategies_used"],
                "misconceptions": list(dict.fromkeys(a.misconception for _, a in items if a.misconception)),
                "next_review_at": mastery.next_review_at.isoformat() if mastery.next_review_at else None,
            }
        )

    test_attempts = [a for a in attempts if questions[a.question_id].phase == "test"]
    ended = session.ended_at or session.started_at
    overall = {
        "questions": len(attempts),
        "correct": sum(1 for a in attempts if a.verdict == "correct"),
        "accuracy": _mean([a.score for a in attempts]),
        "test_score": _mean([a.score for a in test_attempts]),
        "test_questions": len(test_attempts),
        "hints_used": sum(q.hints_used for q in questions.values()),
        "minutes": max(1, round((ended - session.started_at).total_seconds() / 60)),
    }
    test_review = [
        {
            "question": questions[a.question_id].prompt,
            "topic": next(t["title"] for t in topics_out if t["topic_id"] == a.topic_id),
            "your_answer": a.answer,
            "correct_answer": questions[a.question_id].answer,
            "verdict": a.verdict,
            "feedback": a.feedback,
            "explanation": questions[a.question_id].explanation,
        }
        for a in sorted(test_attempts, key=lambda a: a.id)
    ]

    facts = _facts_text(topics_out, overall, test_review)
    try:
        summary = llm.generate(
            system=prompts.tutor_system(student.grade),
            prompt=prompts.summary_prompt(describe_learner(student, None, lesson), facts),
            schema=prompts.SessionSummary,
            purpose="summary",
        ).model_dump()
    except LLMError as exc:  # the numbers are what matter; don't lose the session over the prose
        log.warning("summary generation failed: %s", exc)
        summary = {
            "message_for_student": "Great effort today! Check your report to see how you did.",
            "summary_for_parent": facts,
            "strengths": [t["title"] for t in topics_out if t["mastery_label"] == "mastered"],
            "areas_to_improve": [t["title"] for t in topics_out if t["mastery_label"] == "needs_work"],
            "recommended_next_steps": ["Revise the topics marked 'needs work' at the next review date."],
        }

    return {"overall": overall, "topics": topics_out, "test_review": test_review, "ai": summary}


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.0%}"


def _facts_text(topics: list[dict[str, Any]], overall: dict[str, Any], test_review: list[dict[str, Any]]) -> str:
    lines = [
        f"Overall: {overall['correct']}/{overall['questions']} answers fully correct, accuracy {_pct(overall['accuracy'])}, "
        f"test score {_pct(overall['test_score'])}, {overall['hints_used']} hints used, ~{overall['minutes']} min."
    ]
    for t in topics:
        lines.append(
            f"- {t['title']}: status {t['status']}, mastery {t['mastery_start']:.0%} -> {t['mastery_end']:.0%}, "
            f"accuracy {_pct(t['accuracy'])}, test {_pct(t['test_score'])}, re-taught {t['reteach_count']}x"
            + (f" (strategies: {', '.join(t['strategies_used'])})" if t["strategies_used"] else "")
            + (f"; misconceptions: {'; '.join(t['misconceptions'])}" if t["misconceptions"] else "")
        )
    wrong = [r for r in test_review if r["verdict"] != "correct"]
    if wrong:
        lines.append("Test questions missed:")
        lines += [f"- {r['question'][:160]} (answered '{r['your_answer']}', correct '{r['correct_answer']}')" for r in wrong]
    return "\n".join(lines)
