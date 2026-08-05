from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from quant_agent.data.providers.sample_provider import SampleDataProvider
from quant_agent.data.snapshots import DataSnapshotStore
from quant_agent.execution.config import PaperAccountSettings
from quant_agent.execution.ledger import PortfolioLedger
from quant_agent.execution.paper import LedgerPaperExecutor
from quant_agent.execution.planning import (
    ExecutionSafetyError,
    PortfolioOrderPlanner,
    make_planned_order,
    replace_plan_orders,
)
from quant_agent.risk.approval import ApprovalError, ApprovalStore
from quant_agent.risk.plan_engine import PlanRiskEngine
from quant_agent.schemas.research import TargetPosition, TargetPositionRequest

TRADE_DATE = date(2026, 7, 29)


def setup_plan(
    tmp_path: Path,
    weights: list[tuple[str, float]],
):
    market = DataSnapshotStore(tmp_path).synchronize(
        SampleDataProvider(),
        TRADE_DATE,
    )
    settings = PaperAccountSettings()
    ledger = PortfolioLedger(tmp_path / "portfolio.db")
    planner = PortfolioOrderPlanner(
        ledger=ledger,
        settings=settings,
        artifact_root=tmp_path,
    )
    targets = TargetPositionRequest(
        run_id="daily-run-risk",
        strategy_id="daily-momentum",
        trade_date=TRADE_DATE.isoformat(),
        generated_at="2026-07-29T16:00:00+08:00",
        universe="CSI300",
        positions=[
            TargetPosition(
                symbol=symbol,
                target_weight=weight,
                score=1 - index,
                rank=index + 1,
            )
            for index, (symbol, weight) in enumerate(weights)
        ],
        data_version=market.manifest.data_version,
        config_hash="config-hash",
        code_version="code-hash",
    )
    plan = planner.build(targets=targets, manifest=market.manifest)
    return market, settings, ledger, planner, plan


def test_plan_risk_safely_caps_order_value_and_rebinds_checksum(tmp_path: Path):
    market, settings, ledger, _, plan = setup_plan(
        tmp_path,
        [("600519.SH", 0.2), ("000001.SZ", 0.2)],
    )
    assessment = PlanRiskEngine(
        artifact_root=tmp_path,
        ledger=ledger,
        settings=settings,
        max_order_value=50_000,
    ).evaluate(plan=plan, manifest=market.manifest)

    assert assessment.approved is True
    assert assessment.decision == "ADJUST"
    assert assessment.adjusted_plan is not None
    assert assessment.plan_checksum != plan.plan_checksum
    assert all(
        order.estimated_value <= 50_000
        for order in assessment.adjusted_plan.orders
    )
    assert any(
        result.rule_id == "MAX_ORDER_VALUE" and not result.passed
        for result in assessment.rule_results
    )


def test_plan_risk_rejects_hard_exposure_failure(tmp_path: Path):
    market, settings, ledger, _, plan = setup_plan(
        tmp_path,
        [("600519.SH", 0.4), ("000001.SZ", 0.4), ("300750.SZ", 0.1)],
    )
    assessment = PlanRiskEngine(
        artifact_root=tmp_path,
        ledger=ledger,
        settings=settings,
        max_turnover=1.0,
        max_order_value=1_000_000,
    ).evaluate(plan=plan, manifest=market.manifest)

    assert assessment.approved is False
    assert assessment.decision == "REJECT"
    assert {
        violation.rule_id for violation in assessment.violations
    } >= {"GROSS_EXPOSURE", "MAX_SINGLE_WEIGHT"}


def test_risk_uses_projected_holdings_when_t1_blocks_a_sell(tmp_path: Path):
    market = DataSnapshotStore(tmp_path).synchronize(
        SampleDataProvider(),
        TRADE_DATE,
    )
    settings = PaperAccountSettings(initial_cash=100_000)
    ledger = PortfolioLedger(tmp_path / "portfolio.db")
    ledger.ensure_account(settings.account_id, settings.initial_cash)
    ledger.seed_lot(
        account_id=settings.account_id,
        symbol="600519.SH",
        acquired_date=TRADE_DATE.isoformat(),
        volume=1_000,
        unit_cost=100,
    )
    planner = PortfolioOrderPlanner(
        ledger=ledger,
        settings=settings,
        artifact_root=tmp_path,
    )
    targets = TargetPositionRequest(
        run_id="t1-risk",
        strategy_id="daily-momentum",
        trade_date=TRADE_DATE.isoformat(),
        generated_at="2026-07-29T16:00:00+08:00",
        universe="CSI300",
        positions=[],
        data_version=market.manifest.data_version,
        config_hash="config-hash",
        code_version="code-hash",
    )
    plan = planner.build(targets=targets, manifest=market.manifest)

    assessment = PlanRiskEngine(
        artifact_root=tmp_path,
        ledger=ledger,
        settings=settings,
        max_turnover=1.0,
        max_order_value=1_000_000,
    ).evaluate(plan=plan, manifest=market.manifest)

    assert plan.orders == []
    assert assessment.approved is False
    assert {
        violation.rule_id for violation in assessment.violations
    } >= {"MAX_SINGLE_WEIGHT"}


def test_approval_expires_and_plan_change_invalidates_it(tmp_path: Path):
    market, settings, ledger, _, plan = setup_plan(
        tmp_path,
        [("600519.SH", 0.2)],
    )
    assessment = PlanRiskEngine(
        artifact_root=tmp_path,
        ledger=ledger,
        settings=settings,
        max_turnover=1.0,
        max_order_value=1_000_000,
    ).evaluate(plan=plan, manifest=market.manifest)
    assert assessment.adjusted_plan is not None
    approved_plan = assessment.adjusted_plan
    now = datetime(2026, 7, 29, 9, 0, tzinfo=timezone.utc)
    store = ApprovalStore(tmp_path)
    approval, _ = store.grant(
        plan=approved_plan,
        assessment=assessment,
        approver="operator",
        expires_in_minutes=60,
        now=now,
    )

    assert store.validate(
        plan=approved_plan,
        approval=approval,
        now=now + timedelta(minutes=30),
    ) == approval
    with pytest.raises(ApprovalError, match="expired"):
        store.validate(
            plan=approved_plan,
            approval=approval,
            now=now + timedelta(minutes=60),
        )

    original = approved_plan.orders[0]
    changed_order = make_planned_order(
        run_id=approved_plan.run_id,
        symbol=original.symbol,
        side=original.side,
        price=original.price,
        volume=original.volume - 100,
        fees=settings.fees,
        reason="operator_changed",
    )
    changed_plan = replace_plan_orders(approved_plan, [changed_order])
    with pytest.raises(ApprovalError, match="does not match"):
        store.validate(
            plan=changed_plan,
            approval=approval,
            now=now + timedelta(minutes=30),
        )


def test_kill_switch_after_risk_blocks_execution_without_mutation(tmp_path: Path):
    market, settings, ledger, _, plan = setup_plan(
        tmp_path,
        [("600519.SH", 0.2)],
    )
    assessment = PlanRiskEngine(
        artifact_root=tmp_path,
        ledger=ledger,
        settings=settings,
        max_turnover=1.0,
        max_order_value=1_000_000,
    ).evaluate(plan=plan, manifest=market.manifest)
    assert assessment.adjusted_plan is not None
    approved_plan = assessment.adjusted_plan
    approval, _ = ApprovalStore(tmp_path).grant(
        plan=approved_plan,
        assessment=assessment,
        approver="operator",
    )
    (tmp_path / "KILL_SWITCH").write_text("stop\n", encoding="utf-8")

    with pytest.raises(ExecutionSafetyError, match="kill switch is active"):
        LedgerPaperExecutor(
            ledger=ledger,
            settings=settings,
            artifact_root=tmp_path,
        ).execute(
            plan=approved_plan,
            manifest=market.manifest,
            approval=approval,
        )

    assert ledger.order_count() == 0
    assert ledger.trade_count() == 0
    assert ledger.cash(settings.account_id) == settings.initial_cash


def test_kill_switch_blocks_order_planning(tmp_path: Path):
    market, _, _, planner, _ = setup_plan(
        tmp_path,
        [("600519.SH", 0.2)],
    )
    (tmp_path / "KILL_SWITCH").write_text("stop\n", encoding="utf-8")
    targets = TargetPositionRequest(
        run_id="blocked-run",
        strategy_id="daily-momentum",
        trade_date=TRADE_DATE.isoformat(),
        generated_at="2026-07-29T16:00:00+08:00",
        universe="CSI300",
        positions=[],
        data_version=market.manifest.data_version,
        config_hash="config-hash",
        code_version="code-hash",
    )

    with pytest.raises(ExecutionSafetyError, match="kill switch is active"):
        planner.build(targets=targets, manifest=market.manifest)
