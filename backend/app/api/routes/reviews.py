from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session

from backend.app.api.deps import get_db_session
from backend.app.schemas import DailyReviewResponse
from backend.app.services.review_engine import ReviewEngine

router = APIRouter(prefix="/api/reviews", tags=["reviews"])
SessionDep = Annotated[Session, Depends(get_db_session)]


@router.get("/daily", response_model=DailyReviewResponse)
def get_daily_review(session: SessionDep, review_date: date | None = None) -> DailyReviewResponse:
    return ReviewEngine().daily_review(session, review_date)
