from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Student
from ..schemas import StudentCreate, StudentOut
from ..tutor.progress import progress_overview, revision_plan

router = APIRouter(prefix="/students", tags=["students"])


@router.post("", response_model=StudentOut, status_code=201)
def create_student(body: StudentCreate, db: Session = Depends(get_db)):
    student = Student(name=body.name.strip(), grade=body.grade, learning_profile={})
    db.add(student)
    db.commit()
    return student


@router.get("", response_model=list[StudentOut])
def list_students(db: Session = Depends(get_db)):
    return db.scalars(select(Student).order_by(Student.id)).all()


def load_student(db: Session, student_id: int) -> Student:
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(404, "Student not found")
    return student


@router.get("/{student_id}", response_model=StudentOut)
def get_student(student_id: int, db: Session = Depends(get_db)):
    return load_student(db, student_id)


@router.get("/{student_id}/progress")
def get_progress(student_id: int, db: Session = Depends(get_db)):
    return progress_overview(db, load_student(db, student_id))


@router.get("/{student_id}/revision-plan")
def get_revision_plan(student_id: int, db: Session = Depends(get_db)):
    return revision_plan(db, load_student(db, student_id))
