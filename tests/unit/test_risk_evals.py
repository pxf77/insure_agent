import json
from pathlib import Path

from typer.testing import CliRunner

from quant_agent.evals.risk import run_risk_evals
from quant_agent.risk.v2_cli import app

runner = CliRunner()


def test_risk_eval_suite_v04_passes() -> None:
    report = run_risk_evals(Path("evals/risk/v0.4.yaml"))

    assert report.success
    assert report.total == 24
    assert report.passed == 24
    assert report.failed == 0


def test_risk_cli_lists_empty_kill_switch_state(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "kill-switch",
            "list",
            "--state-path",
            str(tmp_path / "switches.json"),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "1.0"
    assert payload["records"] == []


def test_risk_cli_sets_scoped_kill_switch(tmp_path: Path) -> None:
    state_path = tmp_path / "switches.json"
    result = runner.invoke(
        app,
        [
            "kill-switch",
            "set",
            "--scope",
            "ACCOUNT",
            "--scope-id",
            "paper",
            "--reduce-only",
            "--changed-by",
            "pytest",
            "--state-path",
            str(state_path),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["scope"] == "ACCOUNT"
    assert payload["scope_id"] == "paper"
    assert payload["reduce_only"] is True
    assert state_path.is_file()


def test_risk_cli_issues_and_revokes_approval(tmp_path: Path) -> None:
    evidence_path = tmp_path / "approval.json"
    state_path = tmp_path / "approvals.json"
    approval_id = "11111111-1111-4111-8111-111111111111"
    evidence_path.write_text(
        json.dumps(
            {
                "approval_id": approval_id,
                "status": "APPROVED",
                "account_id": "paper",
                "strategy_id": "cli-strategy",
                "target_run_id": "cli-run",
                "policy_version": "cli-v1",
                "approved_at": "2026-05-22T23:00:00Z",
                "expires_at": "2026-05-23T01:00:00Z",
                "approvers": ["risk-officer"],
            }
        ),
        encoding="utf-8",
    )

    issued = runner.invoke(
        app,
        [
            "approval",
            "issue",
            "--evidence",
            str(evidence_path),
            "--state-path",
            str(state_path),
        ],
    )
    assert issued.exit_code == 0, issued.output
    assert json.loads(issued.stdout)["approval_id"] == approval_id

    revoked = runner.invoke(
        app,
        [
            "approval",
            "revoke",
            "--approval-id",
            approval_id,
            "--state-path",
            str(state_path),
        ],
    )
    assert revoked.exit_code == 0, revoked.output

    listed = runner.invoke(
        app,
        ["approval", "list", "--state-path", str(state_path)],
    )
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.stdout)["revoked_ids"] == [approval_id]
