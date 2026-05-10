from datetime import UTC, date, datetime, time, timedelta

from sqlmodel import Session, col, select

from backend.app.models import ManualReview, RiskCheck, Signal
from backend.app.schemas import DailyReviewResponse


class ReviewEngine:
    def daily_review(
        self,
        session: Session,
        review_date: date | None = None,
    ) -> DailyReviewResponse:
        selected_date = review_date or datetime.now(UTC).date()
        start = datetime.combine(selected_date, time.min, tzinfo=UTC)
        end = start + timedelta(days=1)

        signals = list(
            session.exec(
                select(Signal).where(Signal.generated_at >= start, Signal.generated_at < end),
            ).all(),
        )
        signal_ids = [signal.id for signal in signals if signal.id is not None]
        risk_checks: list[RiskCheck] = []
        reviews: list[ManualReview] = []
        if signal_ids:
            risk_checks = list(
                session.exec(select(RiskCheck).where(col(RiskCheck.signal_id).in_(signal_ids))).all(),
            )
            reviews = list(
                session.exec(
                    select(ManualReview).where(col(ManualReview.signal_id).in_(signal_ids)),
                ).all(),
            )

        risk_passed = sum(1 for check in risk_checks if check.passed)
        risk_blocked = sum(1 for check in risk_checks if not check.passed)
        accepted = sum(1 for review in reviews if review.decision == "accepted")
        rejected = sum(1 for review in reviews if review.decision == "rejected")
        ignored = sum(1 for review in reviews if review.decision == "ignored")
        summary = (
            f"{len(signals)} signals, {risk_passed} risk-passed, "
            f"{risk_blocked} risk-blocked, {accepted} accepted, "
            f"{rejected} rejected, {ignored} ignored."
        )

        return DailyReviewResponse(
            date=selected_date.isoformat(),
            total_signals=len(signals),
            risk_passed=risk_passed,
            risk_blocked=risk_blocked,
            accepted=accepted,
            rejected=rejected,
            ignored=ignored,
            summary=summary,
        )
