from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..llm import LLMClient, LLMError
from ..models import Attempt, Chapter, DailyLesson, Question, Textbook, Topic, TutorSession
from ..schemas import (
    AnswerIn,
    ChatIn,
    HintIn,
    MessageOut,
    PendingQuestion,
    SessionCreate,
    SessionListItem,
    SessionOut,
    TopicProgress,
)
from ..tutor.engine import SessionError, TutorEngine, get_mastery
from .deps import require_llm
from .students import load_student

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _run(db: Session, action: Callable[[], object]) -> None:
    """Run one engine step atomically: commit on success, roll back on any failure."""
    try:
        action()
        db.commit()
    except SessionError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except LLMError as exc:
        db.rollback()
        raise HTTPException(502, f"The tutor couldn't respond: {exc}") from exc
    except Exception:
        db.rollback()
        raise


def session_view(db: Session, s: TutorSession) -> SessionOut:
    state = s.state or {}
    topics = {t.id: t for t in db.scalars(select(Topic).where(Topic.id.in_(s.topic_ids)))}
    pending = None
    qid = state.get("current_question_id")
    if qid and s.awaiting == "answer":
        q = db.get(Question, qid)
        if q is not None:
            pending = PendingQuestion(
                id=q.id,
                topic_id=q.topic_id,
                phase=q.phase,
                qtype=q.qtype,
                prompt=q.prompt,
                options=[o["text"] for o in q.options],
                difficulty=q.difficulty,
                hints_available=q.phase != "test" and bool(q.hint) and q.hints_used == 0,
            )
    test_ids = state.get("test_question_ids", [])
    test_answered = (
        len(set(db.scalars(select(Attempt.question_id).where(Attempt.question_id.in_(test_ids))))) if test_ids else 0
    )
    settings = get_settings()
    return SessionOut(
        id=s.id,
        student_id=s.student_id,
        mode=s.mode,
        phase=s.phase,
        awaiting=s.awaiting,
        started_at=s.started_at,
        ended_at=s.ended_at,
        topics=[
            TopicProgress(
                topic_id=tid,
                title=topics[tid].title,
                status=state.get("topics", {}).get(str(tid), {}).get("status", "pending"),
                p_known=round(get_mastery(db, s.student_id, tid).p_known, 3),
            )
            for tid in s.topic_ids
            if tid in topics
        ],
        practice_done=state.get("practice_done", 0),
        practice_total=settings.practice_questions,
        test_answered=test_answered,
        test_total=len(test_ids) or settings.test_questions,
        pending_question=pending,
        messages=[MessageOut.model_validate(m) for m in s.messages],
        report=s.report,
    )


def _load(db: Session, session_id: int) -> TutorSession:
    s = db.get(TutorSession, session_id)
    if s is None:
        raise HTTPException(404, "Session not found")
    return s


def _engine(db: Session, session_id: int, llm: LLMClient) -> tuple[TutorSession, TutorEngine]:
    s = _load(db, session_id)
    return s, TutorEngine(db, s, llm, get_settings())


@router.post("", response_model=SessionOut, status_code=201)
def start_session(body: SessionCreate, db: Session = Depends(get_db), llm: LLMClient = Depends(require_llm)):
    student = load_student(db, body.student_id)
    lesson = None
    if body.lesson_id is not None:
        lesson = db.get(DailyLesson, body.lesson_id)
        if lesson is None or lesson.student_id != student.id:
            raise HTTPException(404, "Lesson not found")
        topic_ids = list(lesson.topic_ids)
    elif body.topic_ids:
        topic_ids = list(dict.fromkeys(body.topic_ids))
    else:
        raise HTTPException(400, "Give either a lesson_id or topic_ids.")

    owners = set(
        db.scalars(
            select(Textbook.student_id)
            .join(Chapter, Chapter.textbook_id == Textbook.id)
            .join(Topic, Topic.chapter_id == Chapter.id)
            .where(Topic.id.in_(topic_ids))
        )
    )
    if owners != {student.id}:
        raise HTTPException(400, "Those topics don't belong to this student's textbooks.")

    holder: dict[str, TutorEngine] = {}

    def create() -> None:
        holder["engine"] = TutorEngine.create(
            db, llm, get_settings(), student=student, topic_ids=topic_ids, lesson=lesson, mode=body.mode
        )

    _run(db, create)
    return session_view(db, holder["engine"].s)


@router.get("", response_model=list[SessionListItem])
def list_sessions(student_id: int, db: Session = Depends(get_db)):
    sessions = db.scalars(
        select(TutorSession).where(TutorSession.student_id == student_id).order_by(TutorSession.id.desc())
    ).all()
    titles = {t.id: t.title for t in db.scalars(select(Topic).where(Topic.id.in_({t for s in sessions for t in s.topic_ids})))}
    return [
        SessionListItem(
            id=s.id,
            mode=s.mode,
            phase=s.phase,
            started_at=s.started_at,
            ended_at=s.ended_at,
            topic_titles=[titles[t] for t in s.topic_ids if t in titles],
            test_score=(s.report or {}).get("overall", {}).get("test_score"),
        )
        for s in sessions
    ]


@router.get("/{session_id}", response_model=SessionOut)
def get_session(session_id: int, db: Session = Depends(get_db)):
    return session_view(db, _load(db, session_id))


@router.post("/{session_id}/answer", response_model=SessionOut)
def answer(session_id: int, body: AnswerIn, db: Session = Depends(get_db), llm: LLMClient = Depends(require_llm)):
    s, engine = _engine(db, session_id, llm)
    _run(db, lambda: engine.answer(body.question_id, body.answer))
    return session_view(db, s)


@router.post("/{session_id}/hint", response_model=SessionOut)
def hint(session_id: int, body: HintIn, db: Session = Depends(get_db), llm: LLMClient = Depends(require_llm)):
    s, engine = _engine(db, session_id, llm)
    _run(db, lambda: engine.hint(body.question_id))
    return session_view(db, s)


@router.post("/{session_id}/chat", response_model=SessionOut)
def chat(session_id: int, body: ChatIn, db: Session = Depends(get_db), llm: LLMClient = Depends(require_llm)):
    s, engine = _engine(db, session_id, llm)
    _run(db, lambda: engine.chat(body.text))
    return session_view(db, s)


@router.post("/{session_id}/advance", response_model=SessionOut)
def advance(session_id: int, db: Session = Depends(get_db), llm: LLMClient = Depends(require_llm)):
    s, engine = _engine(db, session_id, llm)
    _run(db, engine.advance)
    return session_view(db, s)


@router.post("/{session_id}/skip-to-test", response_model=SessionOut)
def skip_to_test(session_id: int, db: Session = Depends(get_db), llm: LLMClient = Depends(require_llm)):
    s, engine = _engine(db, session_id, llm)
    _run(db, engine.skip_to_test)
    return session_view(db, s)
