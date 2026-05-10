import pytest

from backend.app.schemas import AccountState, MarketState, SignalCandidate
from backend.app.services.risk import RiskEngine


def candidate(**overrides: object) -> SignalCandidate:
    data: dict[str, object] = {
        "symbol": "SH600000",
        "action": "buy",
        "score": 82,
        "confidence": 0.78,
        "risk_level": "medium",
        "price_range": (10.0, 10.5),
        "stop_loss": 9.2,
        "take_profit": 12.4,
        "max_position_pct": 3.0,
        "reasons": ["trend confirmation"],
        "risks": ["market volatility"],
        "manual_checklist": ["confirm account state"],
    }
    data.update(overrides)
    return SignalCandidate(**data)


def market(**overrides: object) -> MarketState:
    data: dict[str, object] = {
        "symbol": "SH600000",
        "last_price": 10.2,
        "turnover_cny": 150_000_000,
        "is_st": False,
        "is_limit_up": False,
    }
    data.update(overrides)
    return MarketState(**data)


@pytest.mark.parametrize(
    ("bad_candidate", "expected_reason"),
    [
        (candidate(score=69), "score below minimum"),
        (candidate(stop_loss=None), "missing stop loss"),
        (candidate(max_position_pct=5.1), "single position too large"),
        (candidate(take_profit=11.0), "reward/risk ratio below minimum"),
        (candidate(price_range=None), "missing price range"),
        (candidate(take_profit=None), "missing take profit"),
        (candidate(stop_loss=10.3), "invalid stop loss"),
    ],
)
def test_candidate_risk_rules_block(
    bad_candidate: SignalCandidate,
    expected_reason: str,
) -> None:
    result = RiskEngine().evaluate(bad_candidate, AccountState(), market())

    assert result.passed is False
    assert result.blocked_reason == expected_reason


def test_total_position_rule_blocks() -> None:
    result = RiskEngine().evaluate(
        candidate(),
        AccountState(total_position_pct=50),
        market(),
    )

    assert result.passed is False
    assert result.blocked_reason == "total position limit reached"


def test_daily_loss_rule_blocks() -> None:
    result = RiskEngine().evaluate(
        candidate(),
        AccountState(daily_loss_pct=-2),
        market(),
    )

    assert result.passed is False
    assert result.blocked_reason == "daily loss limit reached"


def test_st_rule_blocks() -> None:
    result = RiskEngine().evaluate(candidate(), AccountState(), market(is_st=True))

    assert result.passed is False
    assert result.blocked_reason == "st or risk-warning stock blocked"


def test_turnover_rule_blocks() -> None:
    result = RiskEngine().evaluate(
        candidate(),
        AccountState(),
        market(turnover_cny=99_000_000),
    )

    assert result.passed is False
    assert result.blocked_reason == "turnover below minimum"


def test_limit_up_buy_rule_blocks() -> None:
    result = RiskEngine().evaluate(candidate(), AccountState(), market(is_limit_up=True))

    assert result.passed is False
    assert result.blocked_reason == "limit-up buy blocked"


def test_valid_candidate_passes() -> None:
    result = RiskEngine().evaluate(candidate(), AccountState(), market())

    assert result.passed is True
    assert result.blocked_reason is None
