import re
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..ingestion.extract import SUPPORTED_EXTENSIONS
from ..ingestion.pipeline import process_textbook
from ..models import Textbook
from ..schemas import TextbookDetail, TextbookOut
from .students import load_student

router = APIRouter(prefix="/textbooks", tags=["textbooks"])


@router.post("", response_model=TextbookOut, status_code=202)
async def upload_textbook(
    background: BackgroundTasks,
    student_id: int = Form(...),
    file: UploadFile = File(...),
    title: str | None = Form(None),
    subject: str | None = Form(None),
    grade: int | None = Form(None),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    load_student(db, student_id)
    filename = Path(file.filename or "textbook").name
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(415, f"Unsupported file type '{ext or 'none'}'. Upload a PDF, .txt or .md file.")

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
    dest = settings.upload_dir / f"{uuid.uuid4().hex}_{safe}"
    limit = settings.max_upload_mb * 1024 * 1024
    size = 0
    with dest.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, f"File is larger than {settings.max_upload_mb} MB.")
            out.write(chunk)
    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "The uploaded file is empty.")

    tb = Textbook(
        student_id=student_id,
        title=(title or "").strip() or Path(filename).stem,
        subject=(subject or "").strip() or None,
        grade=grade,
        filename=filename,
        stored_path=str(dest),
        status="uploaded",
        status_detail="Waiting to be processed",
        progress=0.0,
    )
    db.add(tb)
    db.commit()
    background.add_task(process_textbook, tb.id)
    return tb


@router.get("", response_model=list[TextbookOut])
def list_textbooks(student_id: int, db: Session = Depends(get_db)):
    return db.scalars(select(Textbook).where(Textbook.student_id == student_id).order_by(Textbook.id.desc())).all()


def load_textbook(db: Session, textbook_id: int) -> Textbook:
    tb = db.get(Textbook, textbook_id)
    if tb is None:
        raise HTTPException(404, "Textbook not found")
    return tb


@router.get("/{textbook_id}", response_model=TextbookDetail)
def get_textbook(textbook_id: int, db: Session = Depends(get_db)):
    return load_textbook(db, textbook_id)


@router.post("/{textbook_id}/process", response_model=TextbookOut, status_code=202)
def reprocess_textbook(textbook_id: int, background: BackgroundTasks, db: Session = Depends(get_db)):
    tb = load_textbook(db, textbook_id)
    if tb.status == "processing":
        raise HTTPException(409, "This textbook is already being processed.")
    tb.status, tb.status_detail, tb.progress = "uploaded", "Waiting to be processed", 0.0
    db.commit()
    background.add_task(process_textbook, tb.id)
    return tb


@router.delete("/{textbook_id}", status_code=204)
def delete_textbook(textbook_id: int, db: Session = Depends(get_db)):
    tb = load_textbook(db, textbook_id)
    path = Path(tb.stored_path)
    db.delete(tb)
    db.commit()
    path.unlink(missing_ok=True)
