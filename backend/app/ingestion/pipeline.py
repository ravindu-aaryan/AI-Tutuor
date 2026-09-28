"""End-to-end textbook processing: extract text -> detect chapters -> AI topic analysis -> save curriculum."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import delete

from ..db import new_session
from ..llm import LLMError
from ..models import Chapter, TextChunk, Textbook, Topic
from .extract import ExtractionError, extract
from .structure import detect_chapters

log = logging.getLogger(__name__)


def _set_status(textbook_id: int, status: str, detail: str | None = None, progress: float | None = None) -> None:
    with new_session() as db:
        tb = db.get(Textbook, textbook_id)
        if tb is None:
            return
        tb.status = status
        tb.status_detail = detail
        if progress is not None:
            tb.progress = progress
        db.commit()


def process_textbook(textbook_id: int) -> None:
    """Process an uploaded textbook. Never raises: failures are recorded on the textbook row."""
    try:
        _process(textbook_id)
    except (ExtractionError, LLMError) as exc:
        log.warning("textbook %s failed: %s", textbook_id, exc)
        _set_status(textbook_id, "failed", str(exc))
    except Exception as exc:  # noqa: BLE001 - surface unexpected errors to the user too
        log.exception("textbook %s failed unexpectedly", textbook_id)
        _set_status(textbook_id, "failed", f"Unexpected error while processing: {exc}")


def _process(textbook_id: int) -> None:
    with new_session() as db:
        tb = db.get(Textbook, textbook_id)
        if tb is None:
            return
        path, filename = Path(tb.stored_path), tb.filename
        known_subject, known_grade, known_title = tb.subject, tb.grade, tb.title

    _set_status(textbook_id, "processing", "Reading the book", 0.02)
    doc = extract(path)

    # Store page text first: it's the grounding source for all tutoring.
    with new_session() as db:
        tb = db.get(Textbook, textbook_id)
        assert tb is not None
        db.execute(delete(Topic).where(Topic.chapter_id.in_([c.id for c in tb.chapters])))
        db.execute(delete(Chapter).where(Chapter.textbook_id == textbook_id))
        db.execute(delete(TextChunk).where(TextChunk.textbook_id == textbook_id))
        db.add_all(TextChunk(textbook_id=textbook_id, page=i, text=t) for i, t in enumerate(doc.pages, start=1))
        tb.page_count = doc.page_count
        db.commit()

    from ..brain import get_curriculum_brain

    with new_session() as db:
        brain = get_curriculum_brain(db)
    _set_status(textbook_id, "processing", "Finding the chapters", 0.08)
    spans, source = detect_chapters(doc)
    if not spans:
        spans = brain.segment(doc)
        source = "ai" if brain.name != "rules" else "rules"
    if not spans:
        raise ExtractionError("Could not find any chapters or sections in this book.")

    overview = brain.overview(doc, spans, filename)
    subject = known_subject or overview.subject
    grade = known_grade or overview.grade
    with new_session() as db:
        tb = db.get(Textbook, textbook_id)
        assert tb is not None
        tb.subject = subject
        tb.grade = grade
        if not known_title or known_title == Path(filename).stem:
            tb.title = overview.title or doc.metadata_title or known_title
        tb.structure_source = source
        tb.analysis_mode = brain.name
        db.commit()

    for i, span in enumerate(spans, start=1):
        _set_status(
            textbook_id,
            "processing",
            f"Understanding chapter {i} of {len(spans)}: {span.title}",
            0.1 + 0.88 * (i - 1) / len(spans),
        )
        analysis = brain.analyze_chapter(doc, span, subject=subject, grade=grade)
        with new_session() as db:
            chapter = Chapter(
                textbook_id=textbook_id,
                number=i,
                title=analysis.title or span.title,
                summary=analysis.summary,
                start_page=span.start_page,
                end_page=span.end_page,
            )
            chapter.topics = [
                Topic(
                    order=j,
                    title=t.title,
                    summary=t.summary,
                    learning_objectives=t.learning_objectives,
                    key_terms=t.key_terms,
                    prerequisites=t.prerequisites,
                    start_page=t.start_page,
                    end_page=t.end_page,
                )
                for j, t in enumerate(analysis.topics, start=1)
            ]
            db.add(chapter)
            db.commit()

    _set_status(textbook_id, "ready", f"{len(spans)} chapters analysed", 1.0)
