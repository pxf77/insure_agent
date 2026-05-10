from backend.app.schemas import SignalCandidate
from backend.app.services.notifications import ConsoleNotificationProvider


def test_console_notification_contains_manual_confirmation_disclaimer(capsys) -> None:  # type: ignore[no-untyped-def]
    candidate = SignalCandidate(
        symbol="SH600000",
        action="buy",
        score=82,
        confidence=0.78,
        risk_level="medium",
        price_range=(10.0, 10.5),
        stop_loss=9.2,
        take_profit=12.4,
        max_position_pct=3.0,
        reasons=["trend confirmation"],
        risks=["market volatility"],
        manual_checklist=["confirm account state"],
    )

    ConsoleNotificationProvider().notify(candidate, signal_id=1)

    output = capsys.readouterr().out
    assert "manual confirmation required" in output
    assert "not an automatic order instruction" in output
    assert "SH600000" in output
