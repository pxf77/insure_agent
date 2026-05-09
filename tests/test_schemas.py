import pytest
from pydantic import ValidationError

from backend.app.schemas import ManualReviewCreate, SignalCandidate, WatchlistCreate


def test_watchlist_create_uppercases_symbol() -> None:
    payload = WatchlistCreate(symbol="  sh600000  ", name="PF Bank")

    assert payload.symbol == "SH600000"


def test_signal_candidate_rejects_bad_score() -> None:
    with pytest.raises(ValidationError):
        SignalCandidate(
            symbol="SH600000",
            action="buy",
            score=101,
            confidence=0.8,
            risk_level="medium",
            price_range=(10.0, 10.5),
            stop_loss=9.5,
            take_profit=12.0,
            max_position_pct=3.0,
            reasons=["trend"],
            risks=["volatility"],
            manual_checklist=["confirm manually"],
        )


def test_manual_review_rejects_unknown_decision() -> None:
    with pytest.raises(ValidationError):
        ManualReviewCreate(decision="approve")
