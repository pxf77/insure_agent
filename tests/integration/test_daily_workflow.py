import json
from datetime import date
from pathlib import Path

import pytest

from quant_agent.common.run_index import RunIndex
from quant_agent.schemas.run import RunStatus, StageStatus
from quant_agent.workflow.daily import DailyWorkflow

TRADE_DATE = date(2026, 7, 29)


def test_daily_workflow_stops_for_approval_then_completes(tmp_path: Path):
    workflow = DailyWorkflow(project_root=tmp_path)

    started = workflow.start(trade_date=TRADE_DATE, provider_name="sample")
    repeated = workflow.start(trade_date=TRADE_DATE, provider_name="sample")

    assert started.status == RunStatus.AWAITING_APPROVAL
    assert repeated.run_id == started.run_id
    assert repeated.status == RunStatus.AWAITING_APPROVAL
    assert started.report_path is not None and started.report_path.is_file()
    assert "approval grant" in (started.instruction or "")
    manifest = workflow.show(started.run_id)
    research = next(stage for stage in manifest.stages if stage.name == "RESEARCH")
    assert len(research.attempts) == 1
    assert next(
        stage for stage in manifest.stages if stage.name == "APPROVAL"
    ).status == StageStatus.PENDING

    approval, approval_path = workflow.grant_approval(
        run_id=started.run_id,
        approver="test-operator",
    )
    completed = workflow.execute(started.run_id)

    assert approval.run_id == started.run_id
    assert approval_path.is_file()
    assert completed.status == RunStatus.COMPLETED
    assert completed.report_path is not None
    report = completed.report_path.read_text(encoding="utf-8")
    for heading in (
        "## Data Health",
        "## Research And Baseline",
        "## Current Holdings",
        "## Target Holdings",
        "## Proposed Deltas And Estimated Costs",
        "## Risk",
        "## Approval",
        "## Execution",
        "## NAV",
    ):
        assert heading in report
    latest = RunIndex(tmp_path / "artifacts").read()
    assert latest["completed_run"] == started.run_id
    assert latest["run_manifest"] == str(completed.manifest_path)


def test_approval_renewal_updates_manifest_artifact_and_attempt(tmp_path: Path):
    workflow = DailyWorkflow(project_root=tmp_path)
    started = workflow.start(trade_date=TRADE_DATE)

    _, first_path = workflow.grant_approval(
        run_id=started.run_id,
        approver="first-operator",
    )
    _, second_path = workflow.grant_approval(
        run_id=started.run_id,
        approver="second-operator",
    )
    manifest = workflow.show(started.run_id)
    approval_stage = next(
        stage for stage in manifest.stages if stage.name == "APPROVAL"
    )

    assert first_path != second_path
    assert len(approval_stage.attempts) == 2
    assert manifest.artifacts["approval"].path == str(second_path)


def test_tampered_registered_artifact_blocks_approval(tmp_path: Path):
    workflow = DailyWorkflow(project_root=tmp_path)
    started = workflow.start(trade_date=TRADE_DATE)
    manifest = workflow.show(started.run_id)
    approved_plan = Path(manifest.artifacts["approved_order_plan"].path)
    approved_plan.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="artifact checksum mismatch"):
        workflow.grant_approval(
            run_id=started.run_id,
            approver="operator",
        )


def test_execution_failure_can_resume_without_duplicate_orders(tmp_path: Path):
    workflow = DailyWorkflow(project_root=tmp_path)
    started = workflow.start(trade_date=TRADE_DATE)
    workflow.grant_approval(run_id=started.run_id, approver="test-operator")
    kill_switch = tmp_path / "artifacts" / "KILL_SWITCH"
    kill_switch.write_text("stop\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="kill switch is active"):
        workflow.execute(started.run_id)
    failed = workflow.show(started.run_id)
    assert failed.status == RunStatus.FAILED
    execution_stage = next(
        stage for stage in failed.stages if stage.name == "EXECUTION"
    )
    assert execution_stage.status == StageStatus.FAILED

    kill_switch.unlink()
    completed = workflow.resume(started.run_id)

    assert completed.status == RunStatus.COMPLETED
    assert workflow.ledger.order_count() == workflow.ledger.trade_count()
    assert workflow.ledger.order_count() > 0
    resumed = workflow.show(started.run_id)
    execution_stage = next(
        stage for stage in resumed.stages if stage.name == "EXECUTION"
    )
    assert len(execution_stage.attempts) == 2


def test_daily_replay_has_stable_run_and_semantic_plan(tmp_path: Path):
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first = DailyWorkflow(project_root=first_root).start(trade_date=TRADE_DATE)
    second = DailyWorkflow(project_root=second_root).start(trade_date=TRADE_DATE)

    assert first.run_id == second.run_id
    first_manifest = DailyWorkflow(project_root=first_root).show(first.run_id)
    second_manifest = DailyWorkflow(project_root=second_root).show(second.run_id)
    first_plan = json.loads(
        Path(first_manifest.artifacts["approved_order_plan"].path).read_text(
            encoding="utf-8"
        )
    )
    second_plan = json.loads(
        Path(second_manifest.artifacts["approved_order_plan"].path).read_text(
            encoding="utf-8"
        )
    )
    assert first_plan["plan_checksum"] == second_plan["plan_checksum"]
    assert first_plan["orders"] == second_plan["orders"]
    assert first_plan["target_weights"] == second_plan["target_weights"]


def test_two_daily_runs_share_account_but_keep_coherent_run_artifacts(tmp_path: Path):
    workflow = DailyWorkflow(project_root=tmp_path)
    first = workflow.start(trade_date=date(2026, 7, 29))
    workflow.grant_approval(run_id=first.run_id, approver="operator")
    first_completed = workflow.execute(first.run_id)

    second = workflow.start(trade_date=date(2026, 7, 30))
    workflow.grant_approval(run_id=second.run_id, approver="operator")
    second_completed = workflow.execute(second.run_id)

    assert first_completed.status == RunStatus.COMPLETED
    assert second_completed.status == RunStatus.COMPLETED
    assert first.run_id != second.run_id
    second_manifest = workflow.show(second.run_id)
    assert {
        reference.stage for reference in second_manifest.artifacts.values()
    } >= {
        "DATA_SYNC",
        "DATA_VALIDATE",
        "RESEARCH",
        "PLAN",
        "RISK",
        "REPORT_PRE",
        "APPROVAL",
        "EXECUTION",
        "REPORT_FINAL",
    }
    latest = RunIndex(tmp_path / "artifacts").read()
    assert latest["completed_run"] == second.run_id
    nav = workflow.ledger.latest_nav("paper-main")
    assert nav is not None
    assert nav.trade_date == "2026-07-30"


def test_completed_run_republishes_missing_latest_pointer(tmp_path: Path):
    workflow = DailyWorkflow(project_root=tmp_path)
    started = workflow.start(trade_date=TRADE_DATE)
    workflow.grant_approval(run_id=started.run_id, approver="operator")
    completed = workflow.execute(started.run_id)
    latest_path = tmp_path / "artifacts" / "latest.json"
    latest_path.unlink()

    replayed = workflow.resume(completed.run_id)

    assert replayed.status == RunStatus.COMPLETED
    assert RunIndex(tmp_path / "artifacts").read()["completed_run"] == completed.run_id
