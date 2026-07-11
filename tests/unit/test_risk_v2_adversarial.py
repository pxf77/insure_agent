from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from quant_agent.risk.kill_switch_store import KillSwitchState, KillSwitchStore
from quant_agent.risk.v2_engine import DeterministicRiskEngine
from quant_agent.risk.v2_models import (
    KillSwitchRecord,
    KillSwitchScope,
    RiskContext,
    RiskPolicy,
)
from quant_agent.schemas.v2 import RiskDecisionType, TargetPortfolio


def _target() -> TargetPortfolio:
    return TargetPortfolio.model_validate(
        {
            "run_id": "adversarial-run",
            "strategy_id": "adversarial-strategy",
            "trade_date": "2026-05-22",
            "generated_at": "2026-05-22T08:00:00Z",
            "universe": "adversarial",
            "positions": [
                {
                    "instrument": "600519.SH",
                    "target_weight": "0.15",
                    "score": "1",
                    "rank": 1,
                }
            ],
        }
    )


def _context() -> RiskContext:
    return RiskContext.model_validate(
        {
            "account_id": "paper",
            "strategy_id": "adversarial-strategy",
            "evaluated_at": "2026-05-23T00:00:00Z",
            "snapshot_as_of": "2026-05-22T07:05:00Z",
            "account_value": "1000000",
            "cash": "900000",
            "daily_loss": "0.01",
            "drawdown": "0.05",
            "approval": {
                "approval_id": "11111111-1111-4111-8111-111111111111",
                "status": "APPROVED",
                "account_id": "paper",
                "strategy_id": "adversarial-strategy",
                "target_run_id": "adversarial-run",
                "policy_version": "adversarial-v1",
                "approved_at": "2026-05-22T23:00:00Z",
                "expires_at": "2026-05-23T01:00:00Z",
                "approvers": ["risk-officer"],
            },
            "current_positions": [
                {
                    "instrument": "600519.SH",
                    "current_weight": "0.10",
                    "sellable_weight": "0.10",
                    "industry": "Consumer",
                }
            ],
            "instruments": [
                {
                    "instrument": "600519.SH",
                    "industry": "Consumer",
                    "last_price": "1500",
                }
            ],
        }
    )


def _policy() -> RiskPolicy:
    return RiskPolicy.model_validate(
        {
            "policy_version": "adversarial-v1",
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
    )


def test_concurrent_scoped_kill_switch_updates_are_not_lost(tmp_path: Path) -> None:
    store = KillSwitchStore(tmp_path / "switches.json")

    def write(index: int) -> None:
        store.set(
            scope=KillSwitchScope.STRATEGY,
            scope_id=f"strategy-{index}",
            active=True,
            reduce_only=True,
            reason_code="CONCURRENT_TEST",
            message="concurrent update",
            changed_by="pytest",
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(write, range(16)))

    state = store.read()
    assert len(state.records) == 16
    assert {record.scope_id for record in state.records} == {
        f"strategy-{index}" for index in range(16)
    }


def test_stale_kill_switch_update_cannot_clear_newer_state(tmp_path: Path) -> None:
    store = KillSwitchStore(tmp_path / "switches.json")
    newer = datetime(2026, 5, 23, 0, 0, tzinfo=timezone.utc)
    store.set(
        scope=KillSwitchScope.ACCOUNT,
        scope_id="paper",
        active=True,
        reduce_only=False,
        reason_code="NEWER_STATE",
        message="newer",
        changed_by="pytest",
        changed_at=newer,
    )

    with pytest.raises(ValueError, match="stale or non-monotonic"):
        store.set(
            scope=KillSwitchScope.ACCOUNT,
            scope_id="paper",
            active=False,
            reduce_only=False,
            reason_code="STALE_CLEAR",
            message="stale",
            changed_by="pytest",
            changed_at=newer - timedelta(seconds=1),
        )

    assert store.active_for(account_id="paper", strategy_id="other")[0].active


def test_engine_uses_one_immutable_kill_switch_snapshot(tmp_path: Path) -> None:
    reduce_record = KillSwitchRecord(
        switch_id="strategy:adversarial-strategy",
        scope=KillSwitchScope.STRATEGY,
        scope_id="adversarial-strategy",
        active=True,
        reduce_only=True,
        reason_code="REDUCE",
        message="reduce only",
        changed_at="2026-05-22T23:00:00Z",
        changed_by="pytest",
    )
    hard_record = reduce_record.model_copy(
        update={"reduce_only": False, "reason_code": "HARD"}
    )

    class FlappingStore(KillSwitchStore):
        def __init__(self, path: Path):
            super().__init__(path)
            self.read_count = 0

        def read(self) -> KillSwitchState:
            self.read_count += 1
            return KillSwitchState(
                records=[reduce_record if self.read_count == 1 else hard_record]
            )

    store = FlappingStore(tmp_path / "switches.json")
    decision = DeterministicRiskEngine(
        policy=_policy(),
        kill_switch_store=store,
    ).evaluate(_target(), _context())

    assert store.read_count == 1
    assert decision.decision == RiskDecisionType.ADJUST
    assert "REDUCE_ONLY" in {result.reason_code for result in decision.rule_results}
