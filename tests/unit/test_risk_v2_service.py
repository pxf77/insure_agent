from __future__ import annotations

import json
from pathlib import Path

import yaml

from quant_agent.risk.approval_store import ApprovalStore
from quant_agent.risk.v2_models import RiskContext
from quant_agent.risk.v2_service import RiskDecisionService


def write_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    target = tmp_path / "target.json"
    context = tmp_path / "context.json"
    policy = tmp_path / "policy.yaml"
    target.write_text(
        json.dumps(
            {
                "run_id": "service-run",
                "strategy_id": "service-strategy",
                "trade_date": "2026-05-22",
                "generated_at": "2026-05-22T08:00:00Z",
                "universe": "service",
                "positions": [
                    {
                        "instrument": "600519.SH",
                        "target_weight": "0.15",
                        "score": "1",
                        "rank": 1,
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    context.write_text(
        json.dumps(
            {
                "account_id": "paper",
                "strategy_id": "service-strategy",
                "evaluated_at": "2026-05-23T00:00:00Z",
                "snapshot_as_of": "2026-05-22T07:05:00Z",
                "account_value": "1000000",
                "cash": "850000",
                "daily_loss": "0.01",
                "drawdown": "0.05",
                "approval": {
                    "approval_id": "11111111-1111-4111-8111-111111111111",
                    "status": "APPROVED",
                    "account_id": "paper",
                    "strategy_id": "service-strategy",
                    "target_run_id": "service-run",
                    "policy_version": "service-v1",
                    "approved_at": "2026-05-22T23:00:00Z",
                    "expires_at": "2026-05-23T01:00:00Z",
                    "approvers": ["risk-officer"],
                },
                "current_positions": [],
                "instruments": [
                    {
                        "instrument": "600519.SH",
                        "industry": "Consumer",
                        "last_price": "1500",
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    policy.write_text(
        yaml.safe_dump(
            {
                "policy_version": "service-v1",
                "max_data_age_minutes": 1440,
                "max_single_weight": "0.20",
                "max_total_weight": "0.80",
                "max_industry_weight": "0.35",
                "minimum_cash_weight": "0.20",
                "max_daily_loss": "0.05",
                "max_drawdown": "0.20",
                "allow_st": False,
                "require_approval": True,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return target, context, policy


def issue_context_approval(context: Path, approval_path: Path) -> None:
    context_model = RiskContext.model_validate_json(context.read_text(encoding="utf-8"))
    assert context_model.approval is not None
    ApprovalStore(approval_path).issue(context_model.approval)


def test_risk_service_creates_and_reuses_immutable_artifacts(tmp_path: Path) -> None:
    target, context, policy = write_inputs(tmp_path)
    approval_path = tmp_path / "risk_state" / "approvals.json"
    issue_context_approval(context, approval_path)
    service = RiskDecisionService(
        artifact_root=tmp_path / "artifacts",
        kill_switch_path=tmp_path / "risk_state" / "switches.json",
        approval_path=approval_path,
    )

    first_decision, first_dir, first_reused = service.evaluate_files(
        target_path=target,
        context_path=context,
        policy_path=policy,
    )
    second_decision, second_dir, second_reused = service.evaluate_files(
        target_path=target,
        context_path=context,
        policy_path=policy,
    )

    assert first_decision == second_decision
    assert not first_reused
    assert second_reused
    assert first_dir == second_dir
    expected = {
        "target_portfolio.json",
        "risk_context.json",
        "risk_policy.yaml",
        "kill_switch_state.json",
        "approval_state.json",
        "risk_decision.json",
        "manifest.json",
    }
    assert {path.name for path in first_dir.iterdir()} == expected


def test_risk_service_detects_decision_tampering(tmp_path: Path) -> None:
    target, context, policy = write_inputs(tmp_path)
    approval_path = tmp_path / "risk_state" / "approvals.json"
    issue_context_approval(context, approval_path)
    service = RiskDecisionService(
        artifact_root=tmp_path / "artifacts",
        kill_switch_path=tmp_path / "risk_state" / "switches.json",
        approval_path=approval_path,
    )
    _, artifact_dir, _ = service.evaluate_files(
        target_path=target,
        context_path=context,
        policy_path=policy,
    )
    (artifact_dir / "risk_decision.json").write_text("{}\n", encoding="utf-8")

    try:
        service.evaluate_files(
            target_path=target,
            context_path=context,
            policy_path=policy,
        )
    except ValueError as exc:
        assert "integrity check" in str(exc)
    else:
        raise AssertionError("tampered risk decision was accepted")
