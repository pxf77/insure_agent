from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from backend.app.api.deps import get_db_session
from backend.app.models import ManualReview, Signal
from backend.app.schemas import (
    ManualReviewCreate,
    ManualReviewRead,
    ScanRequest,
    ScanResponse,
    SignalRead,
)
from backend.app.services.signal_engine import SignalEngine

router = APIRouter(prefix="/api/signals", tags=["signals"])
SessionDep = Annotated[Session, Depends(get_db_session)]


@router.post("/scan", response_model=ScanResponse)
def scan_signals(payload: ScanRequest, session: SessionDep) -> ScanResponse:
    return ScanResponse(results=SignalEngine().scan_active_watchlist(session, payload.account))


@router.get("", response_model=list[SignalRead])
def list_signals(session: SessionDep, status_filter: str | None = None) -> list[Signal]:
    statement = select(Signal)
    if status_filter is not None:
        statement = statement.where(Signal.status == status_filter)
    return list(session.exec(statement).all())


def get_signal_or_404(session: Session, signal_id: int) -> Signal:
    signal = session.get(Signal, signal_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="signal not found")
    return signal


@router.post(
    "/{signal_id}/manual-review",
    response_model=ManualReviewRead,
    status_code=status.HTTP_201_CREATED,
)
def create_manual_review(
    signal_id: int,
    payload: ManualReviewCreate,
    session: SessionDep,
) -> ManualReview:
    signal = get_signal_or_404(session, signal_id)
    review = ManualReview(signal_id=signal_id, decision=payload.decision, note=payload.note)
    signal.status = payload.decision
    session.add(signal)
    session.add(review)
    session.commit()
    session.refresh(review)
    return review
