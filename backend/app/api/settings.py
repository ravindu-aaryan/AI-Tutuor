from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..brain import brain_status
from ..db import get_db
from ..runtime_settings import AISettings, save_ai_settings

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/ai")
def get_ai(db: Session = Depends(get_db)):
    """Current tutor brain plus which brains are usable right now."""
    return brain_status(db)


@router.put("/ai")
def put_ai(body: AISettings, db: Session = Depends(get_db)):
    save_ai_settings(db, body)
    return brain_status(db)
