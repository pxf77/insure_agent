from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from quant_agent.risk.approval_store import ApprovalStore
from quant_agent.risk.kill_switch_store import KillSwitchStore
from quant_agent.risk.v2_engine import DeterministicRiskEngine
from quant_agent.risk.v2_models import ApprovalEvidence, RiskContext, RiskPolicy
from quant_agent.schemas.v2 import RiskDecisionType, TargetPortfolio


def approval(index: int = 0) -> ApprovalEvidence:
    return ApprovalEvidence(
        approval_id=UUID(f"00000000-0000-4000-8000-{index:012d}"),
        account_id="paper",
        strategy_id="approval-strategy",
        target_run_id=f"approval-run-{index}",
        policy_version="approval-v1",
        approved_at=datetime(2026, 5, 22, 23, 0, tzinfo=timezone.utc),
        expires_at=datetime(2026, 5, 23, 1, 0, tzinfo=timezone.utc),
        approvers=["risk-officer"],
    )


def test_approval_store_issues_and_revokes_immutable_evidence(tmp_path: Path) -> None:
    store = ApprovalStore(tmp_path / "approvals.json")
    record = approval()

    assert store.issue(record) == record
    assert store.read().trusted(record.approval_id) == record

    store.revoke(record.approval_id)
    assert store.read().trusted(record.approval_id) is None
    with pytest.raises(ValueError, match="cannot be reissued"):
        store.issue(record)


def test_approval_id_cannot_be_rebound(tmp_path: Path) -> None:
    store = ApprovalStore(tmp_path / "approvals.json")
    record = approval()
    store.issue(record)
    changed = record.model_copy(update={"expires_at": record.expires_at + timedelta(hours=1)})

    with pytest.raises(ValueError, match="already bound"):
        store.issue(changed)


def test_concurrent_approval_issuance_does_not_lose_records(tmp_path: Path) -> None:
    store = ApprovalStore(tmp_path / "approvals.json")

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda index: store.issue(approval(index)), range(16)))

    assert len(store.read().records) == 16


def test_untrusted_embedded_approval_is_rejected(tmp_path: Path) -> None:
    trusted_store = ApprovalStore(tmp_path / "approvals.json")
    trusted = approval()
    target = TargetPortfolio.model_validate(
        {
            "run_id": trusted.target_run_id,
            "strategy_id": trusted.strategy_id,
            "trade_date": "2026-05-22",
            "generated_at": "2026-05-22T08:00:00Z",
            "universe": "approval",
            "positions": [
                {
                    "instrument": "600519.SH",
                    "target_weight": "0.10",
                    "score": "1",
                    "rank": 1,
                }
            ],
        }
    )
    forged = trusted.model_copy(
        update={"approval_id": UUID("99999999-9999-4999-8999-999999999999")}
    )
    context = RiskContext.model_validate(
        {
            "account_id": trusted.account_id,
            "strategy_id": trusted.strategy_id,
            "evaluated_at": "2026-05-23T00:00:00Z",
            "snapshot_as_of": "2026-05-22T07:05:00Z",
            "account_value": "1000000",
            "cash": "900000",
            "daily_loss": "0",
            "drawdown": "0",
            "approval": forged.model_dump(mode="json"),
            "current_positions": [],
            "instruments": [
                {
                    "instrument": "600519.SH",
                    "industry": "Consumer",
                    "last_price": "1500",
                }
            ],
        }
    )
    policy = RiskPolicy.model_validate(
        {
            "policy_version": trusted.policy_version,
            "max_data_age_minutes": 1440,
            "max_single_weight": "0.20",
            "max_total_weight": "0.80",
            "max_industry_weight": "0.35",
            "minimum_cash_weight": "0.20",
            "max_daily_loss": "0.05",
            "max_drawdown": "0.20",
            "require_approval": True,
        }
    )

    decision = DeterministicRiskEngine(
        policy=policy,
        kill_switch_store=KillSwitchStore(tmp_path / "switches.json"),
        approval_store=trusted_store,
    ).evaluate(target, context)

    assert decision.decision == RiskDecisionType.REJECT
    assert "APPROVAL_NOT_TRUSTED" in {
        result.reason_code for result in decision.rule_results
    }
