from sqlmodel import Session, select

from backend.app.models import RiskCheck, Signal, Watchlist
from backend.app.schemas import AccountState, SignalCandidate, SignalScanResult
from backend.app.services.llm_analyzer import MockLLMAnalyzer
from backend.app.services.market_data import MockMarketDataProvider
from backend.app.services.notifications import ConsoleNotificationProvider
from backend.app.services.risk import RiskEngine


def _join_text(values: list[str]) -> str:
    return "\n".join(values)


def _to_signal(candidate: SignalCandidate, status: str) -> Signal:
    price_low: float | None = None
    price_high: float | None = None
    if candidate.price_range is not None:
        price_low, price_high = candidate.price_range
    return Signal(
        symbol=candidate.symbol,
        action=candidate.action,
        score=candidate.score,
        confidence=candidate.confidence,
        risk_level=candidate.risk_level,
        price_low=price_low,
        price_high=price_high,
        stop_loss=candidate.stop_loss,
        take_profit=candidate.take_profit,
        max_position_pct=candidate.max_position_pct,
        status=status,
        reasons_text=_join_text(candidate.reasons),
        risks_text=_join_text(candidate.risks),
        manual_checklist_text=_join_text(candidate.manual_checklist),
    )


class SignalEngine:
    def __init__(
        self,
        market_provider: MockMarketDataProvider | None = None,
        analyzer: MockLLMAnalyzer | None = None,
        risk_engine: RiskEngine | None = None,
        notifier: ConsoleNotificationProvider | None = None,
    ) -> None:
        self.market_provider = market_provider or MockMarketDataProvider()
        self.analyzer = analyzer or MockLLMAnalyzer()
        self.risk_engine = risk_engine or RiskEngine()
        self.notifier = notifier or ConsoleNotificationProvider()

    def scan_active_watchlist(
        self,
        session: Session,
        account: AccountState,
    ) -> list[SignalScanResult]:
        entries = session.exec(
            select(Watchlist).where(Watchlist.status == "active"),
        ).all()
        results: list[SignalScanResult] = []

        for entry in entries:
            try:
                market = self.market_provider.get_market_state(entry.symbol)
                candidate = self.analyzer.analyze(entry.symbol, market)
                risk_result = self.risk_engine.evaluate(candidate, account, market)
                signal_status = "risk_passed" if risk_result.passed else "risk_blocked"
                signal = _to_signal(candidate, signal_status)
                session.add(signal)
                session.flush()
                if signal.id is None:
                    msg = "signal id was not generated"
                    raise RuntimeError(msg)
                signal_id = signal.id

                risk_check = RiskCheck(
                    signal_id=signal_id,
                    passed=risk_result.passed,
                    blocked_reason=risk_result.blocked_reason,
                )
                session.add(risk_check)

                if risk_result.passed:
                    self.notifier.notify(candidate, signal_id)

                session.commit()
                session.refresh(signal)
                results.append(
                    SignalScanResult(
                        symbol=entry.symbol,
                        signal_id=signal_id,
                        risk_passed=risk_result.passed,
                        blocked_reason=risk_result.blocked_reason,
                    ),
                )
            except Exception as exc:
                session.rollback()
                results.append(SignalScanResult(symbol=entry.symbol, error=str(exc)))

        return results
