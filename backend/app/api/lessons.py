from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Chapter, DailyLesson, Textbook, Topic
from ..schemas import LessonCreate, LessonOut
from .students import load_student

router = APIRouter(prefix="/lessons", tags=["lessons"])


@router.post("", response_model=LessonOut, status_code=201)
def create_lesson(body: LessonCreate, db: Session = Depends(get_db)):
    """Record what was taught at school today."""
    load_student(db, body.student_id)
    chapter = db.get(Chapter, body.chapter_id)
    if chapter is None:
        raise HTTPException(404, "Chapter not found")
    textbook = db.get(Textbook, chapter.textbook_id)
    assert textbook is not None
    if textbook.student_id != body.student_id:
        raise HTTPException(403, "That textbook belongs to another student.")
    topic_ids = list(dict.fromkeys(body.topic_ids))
    valid = set(db.scalars(select(Topic.id).where(Topic.chapter_id == chapter.id, Topic.id.in_(topic_ids))))
    if valid != set(topic_ids):
        raise HTTPException(400, "Every topic must belong to the chosen chapter.")
    lesson = DailyLesson(
        student_id=body.student_id,
        textbook_id=textbook.id,
        chapter_id=chapter.id,
        topic_ids=topic_ids,
        lesson_date=body.lesson_date or date.today(),
        notes=(body.notes or "").strip() or None,
    )
    db.add(lesson)
    db.commit()
    return lesson


@router.get("", response_model=list[LessonOut])
def list_lessons(student_id: int, db: Session = Depends(get_db)):
    return db.scalars(
        select(DailyLesson).where(DailyLesson.student_id == student_id).order_by(DailyLesson.lesson_date.desc(), DailyLesson.id.desc())
    ).all()
