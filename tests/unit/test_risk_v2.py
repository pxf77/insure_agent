from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID

from quant_agent.risk.kill_switch_store import KillSwitchStore
from quant_agent.risk.v2_engine import DeterministicRiskEngine
from quant_agent.risk.v2_models import RiskContext, RiskPolicy
from quant_agent.schemas.v2 import RiskDecisionType, TargetPortfolio


def target_payload() -> dict[str, object]:
    return {
        "run_id": "risk-unit",
        "strategy_id": "risk-unit-strategy",
        "trade_date": "2026-05-22",
        "generated_at": "2026-05-22T08:00:00Z",
        "universe": "unit",
        "positions": [
            {"instrument": "600519.SH", "target_weight": "0.15", "score": "1", "rank": 1},
            {"instrument": "000001.SZ", "target_weight": "0.15", "score": "0.8", "rank": 2},
            {"instrument": "300750.SZ", "target_weight": "0.15", "score": "0.6", "rank": 3},
        ],
    }


def context_payload() -> dict[str, object]:
    return {
        "account_id": "paper",
        "strategy_id": "risk-unit-strategy",
        "evaluated_at": "2026-05-23T00:00:00Z",
        "snapshot_as_of": "2026-05-22T07:05:00Z",
        "account_value": "1000000",
        "cash": "550000",
        "daily_loss": "0.01",
        "drawdown": "0.05",
        "approval_id": str(UUID("11111111-1111-4111-8111-111111111111")),
        "current_positions": [],
        "instruments": [
            {"instrument": "600519.SH", "industry": "Consumer", "last_price": "1500"},
            {"instrument": "000001.SZ", "industry": "Financial", "last_price": "12"},
            {"instrument": "300750.SZ", "industry": "NewEnergy", "last_price": "220"},
        ],
    }


def policy_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "policy_version": "unit-v1",
        "max_data_age_minutes": 1440,
        "max_single_weight": "0.20",
        "max_total_weight": "0.80",
        "max_industry_weight": "0.35",
        "minimum_cash_weight": "0.20",
        "max_daily_loss": "0.05",
        "max_drawdown": "0.20",
        "allow_st": False,
        "require_approval": True,
    }
    payload.update(updates)
    return payload


def test_total_weight_scaling_is_deterministic(tmp_path: Path) -> None:
    decision = DeterministicRiskEngine(
        policy=RiskPolicy.model_validate(policy_payload(max_total_weight="0.36")),
        kill_switch_store=KillSwitchStore(tmp_path / "switches.json"),
    ).evaluate(
        TargetPortfolio.model_validate(target_payload()),
        RiskContext.model_validate(context_payload()),
    )

    assert decision.decision == RiskDecisionType.ADJUST
    assert {result.reason_code for result in decision.rule_results} >= {"MAX_TOTAL_WEIGHT"}
    assert {str(item.instrument): item.target_weight for item in decision.positions} == {
        "000001.SZ": Decimal("0.12"),
        "300750.SZ": Decimal("0.12"),
        "600519.SH": Decimal("0.12"),
    }


def test_industry_weight_scaling_is_deterministic(tmp_path: Path) -> None:
    target = target_payload()
    positions = target["positions"]
    assert isinstance(positions, list)
    positions.append(
        {"instrument": "000858.SZ", "target_weight": "0.20", "score": "0.5", "rank": 4}
    )
    context = context_payload()
    instruments = context["instruments"]
    assert isinstance(instruments, list)
    instruments.append(
        {"instrument": "000858.SZ", "industry": "Consumer", "last_price": "160"}
    )

    decision = DeterministicRiskEngine(
        policy=RiskPolicy.model_validate(policy_payload(max_industry_weight="0.28")),
        kill_switch_store=KillSwitchStore(tmp_path / "switches.json"),
    ).evaluate(
        TargetPortfolio.model_validate(target),
        RiskContext.model_validate(context),
    )

    weights = {str(item.instrument): item.target_weight for item in decision.positions}
    assert decision.decision == RiskDecisionType.ADJUST
    assert "MAX_INDUSTRY_WEIGHT" in {result.reason_code for result in decision.rule_results}
    assert weights["600519.SH"] == Decimal("0.12")
    assert weights["000858.SZ"] == Decimal("0.16")


def test_kill_switch_store_is_atomic_and_scope_aware(tmp_path: Path) -> None:
    store = KillSwitchStore(tmp_path / "risk" / "switches.json")
    store.set(
        scope="ACCOUNT",
        scope_id="paper",
        active=True,
        reduce_only=True,
        reason_code="ACCOUNT_REDUCE_ONLY",
        message="unit test",
        changed_by="pytest",
    )

    records = store.active_for(account_id="paper", strategy_id="other")
    assert len(records) == 1
    assert records[0].reduce_only
    assert store.active_for(account_id="different", strategy_id="other") == []
