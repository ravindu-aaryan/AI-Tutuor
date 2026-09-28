"""Progress overview and revision planning across all of a student's learning."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Attempt, Student, Textbook, TopicMastery, TutorSession, utcnow
from .knowledge import WEAK, mastery_label


def _mastery_by_topic(db: Session, student_id: int) -> dict[int, TopicMastery]:
    return {m.topic_id: m for m in db.scalars(select(TopicMastery).where(TopicMastery.student_id == student_id))}


def progress_overview(db: Session, student: Student) -> dict[str, Any]:
    mastery = _mastery_by_topic(db, student.id)
    textbooks = db.scalars(select(Textbook).where(Textbook.student_id == student.id, Textbook.status == "ready")).all()
    counts = {"mastered": 0, "developing": 0, "needs_work": 0, "not_started": 0}
    books = []
    for tb in textbooks:
        chapters = []
        for ch in tb.chapters:
            topics = []
            for t in ch.topics:
                m = mastery.get(t.id)
                started = m is not None and (m.attempts > 0 or m.times_taught > 0)
                label = mastery_label(m.p_known) if started and m else "not_started"
                counts[label] += 1
                topics.append(
                    {
                        "topic_id": t.id,
                        "title": t.title,
                        "status": label,
                        "p_known": round(m.p_known, 3) if started and m else None,
                        "attempts": m.attempts if m else 0,
                        "accuracy": round(m.correct / m.attempts, 3) if m and m.attempts else None,
                        "misconceptions": (m.misconceptions or [])[-3:] if m else [],
                        "next_review_at": m.next_review_at.isoformat() if m and m.next_review_at else None,
                    }
                )
            started_topics = [x for x in topics if x["p_known"] is not None]
            chapters.append(
                {
                    "chapter_id": ch.id,
                    "number": ch.number,
                    "title": ch.title,
                    "topics": topics,
                    "average_mastery": round(sum(x["p_known"] for x in started_topics) / len(started_topics), 3)
                    if started_topics
                    else None,
                }
            )
        books.append({"textbook_id": tb.id, "title": tb.title, "subject": tb.subject, "chapters": chapters})

    sessions = db.scalars(
        select(TutorSession).where(TutorSession.student_id == student.id).order_by(TutorSession.id.desc())
    ).all()
    finished = [s for s in sessions if s.phase == "complete"]
    test_scores = [s.report["overall"]["test_score"] for s in finished if s.report and s.report["overall"]["test_score"] is not None]
    total_attempts = db.query(Attempt).filter(Attempt.student_id == student.id).count()
    stats = (student.learning_profile or {}).get("strategy_stats", {})
    return {
        "student": {"id": student.id, "name": student.name, "grade": student.grade},
        "counts": counts,
        "sessions_completed": len(finished),
        "questions_answered": total_attempts,
        "recent_test_scores": [
            {"session_id": s.id, "date": s.ended_at.isoformat() if s.ended_at else None, "score": s.report["overall"]["test_score"]}
            for s in finished[:10]
            if s.report and s.report["overall"]["test_score"] is not None
        ],
        "average_test_score": round(sum(test_scores) / len(test_scores), 3) if test_scores else None,
        "teaching_strategies": {
            k: {**v, "success_rate": round(v["succeeded"] / v["tried"], 2) if v.get("tried") else None}
            for k, v in stats.items()
        },
        "textbooks": books,
    }


def revision_plan(db: Session, student: Student, horizon_days: int = 7) -> dict[str, Any]:
    now = utcnow()
    due, upcoming = [], []
    for m in _mastery_by_topic(db, student.id).values():
        if m.attempts == 0 and m.times_taught == 0:
            continue
        t = m.topic
        overdue_days = (now - m.next_review_at).total_seconds() / 86400 if m.next_review_at else 0.0
        is_due = m.next_review_at is None or m.next_review_at <= now
        is_weak = m.p_known < WEAK
        item = {
            "topic_id": t.id,
            "title": t.title,
            "chapter": t.chapter.title,
            "textbook": t.chapter.textbook.title,
            "p_known": round(m.p_known, 3),
            "status": mastery_label(m.p_known),
            "next_review_at": m.next_review_at.isoformat() if m.next_review_at else None,
            "reason": "due_and_weak" if is_due and is_weak else "due" if is_due else "weak" if is_weak else "scheduled",
            "misconceptions": (m.misconceptions or [])[-3:],
            "priority": round(max(0.0, overdue_days) + 3 * (1 - m.p_known), 2),
        }
        if is_due or is_weak:
            due.append(item)
        elif m.next_review_at and m.next_review_at <= now + timedelta(days=horizon_days):
            upcoming.append(item)
    due.sort(key=lambda x: -x["priority"])
    upcoming.sort(key=lambda x: x["next_review_at"] or "")
    return {
        "due": due,
        "upcoming": upcoming,
        # A sensible next revision session: the most urgent few topics.
        "suggested_topic_ids": [x["topic_id"] for x in due[:3]],
    }
