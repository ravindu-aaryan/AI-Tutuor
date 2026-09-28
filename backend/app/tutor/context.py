"""Grounding context for tutoring: textbook excerpts and a description of the learner."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Chapter, DailyLesson, Student, TextChunk, Topic, TopicMastery
from .knowledge import mastery_label

_WORD = re.compile(r"[a-zA-Z]{4,}")


def topic_excerpt(db: Session, topic: Topic, max_chars: int) -> str:
    """Textbook text for a topic: its own pages (plus neighbours) or, failing that, the best-matching
    pages of its chapter by keyword overlap."""
    chapter: Chapter = topic.chapter
    textbook_id = chapter.textbook_id
    if topic.start_page and topic.end_page:
        start = max(chapter.start_page, topic.start_page - 1)
        end = min(chapter.end_page, topic.end_page + 1)
    else:
        start, end = chapter.start_page, chapter.end_page
    pages = db.scalars(
        select(TextChunk)
        .where(TextChunk.textbook_id == textbook_id, TextChunk.page >= start, TextChunk.page <= end)
        .order_by(TextChunk.page)
    ).all()

    if sum(len(p.text) for p in pages) > max_chars:
        # Too long: keep the pages that talk most about this topic, in book order.
        terms = {w.lower() for w in _WORD.findall(" ".join([topic.title, *topic.key_terms, *topic.learning_objectives]))}
        scored = sorted(pages, key=lambda p: -sum(p.text.lower().count(t) for t in terms))
        keep, size = set(), 0
        for p in scored:
            if size + len(p.text) > max_chars and keep:
                continue
            keep.add(p.page)
            size += len(p.text)
        pages = [p for p in pages if p.page in keep]

    return "\n\n".join(f"[[Page {p.page}]]\n{p.text}" for p in pages if p.text)


def describe_topic(topic: Topic) -> str:
    lines = [f"Topic: {topic.title}", f"Chapter: {topic.chapter.title}"]
    if topic.summary:
        lines.append(f"Summary: {topic.summary}")
    if topic.learning_objectives:
        lines.append("Learning objectives:\n" + "\n".join(f"- {o}" for o in topic.learning_objectives))
    if topic.key_terms:
        lines.append("Key terms: " + ", ".join(topic.key_terms))
    if topic.prerequisites:
        lines.append("Prerequisites: " + ", ".join(topic.prerequisites))
    return "\n".join(lines)


def describe_learner(student: Student, mastery: TopicMastery | None, lesson: DailyLesson | None) -> str:
    lines = [f"Student: {student.name}, grade {student.grade}."]
    if mastery is None or mastery.attempts == 0:
        lines.append("This is the first time the student practises this topic with you.")
    else:
        lines.append(
            f"Current mastery estimate: {mastery.p_known:.0%} ({mastery_label(mastery.p_known).replace('_', ' ')}); "
            f"{mastery.correct}/{mastery.attempts} questions right so far."
        )
        if mastery.misconceptions:
            lines.append("Mistakes/misconceptions seen before:\n" + "\n".join(f"- {m}" for m in mastery.misconceptions[-5:]))
    stats = (student.learning_profile or {}).get("strategy_stats", {})
    good = [s for s, v in stats.items() if v.get("tried", 0) >= 2 and v.get("succeeded", 0) / v["tried"] >= 0.6]
    if good:
        lines.append("Explanation styles that have worked well for this student: " + ", ".join(good))
    if lesson and lesson.notes:
        lines.append(f"What the teacher covered at school today (from the parent/student): {lesson.notes}")
    return "\n".join(lines)
