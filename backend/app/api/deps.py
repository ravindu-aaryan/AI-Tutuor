from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from ..brain import TutorBrain, get_tutor_brain
from ..db import get_db
from ..llm import LLMNotConfigured


def require_brain(db: Session = Depends(get_db)) -> TutorBrain:
    try:
        return get_tutor_brain(db)
    except LLMNotConfigured as exc:
        raise HTTPException(
            status_code=503,
            detail=f"{exc} Or switch the tutor to 'Offline' or 'Local AI' in Settings.",
        ) from exc
