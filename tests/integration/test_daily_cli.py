import json
from pathlib import Path

from typer.testing import CliRunner

from quant_agent.cli import app

runner = CliRunner()


def value_from_output(output: str, key: str) -> str:
    prefix = f"{key}: "
    return next(
        line.removeprefix(prefix)
        for line in output.splitlines()
        if line.startswith(prefix)
    )


def test_daily_cli_approval_execution_and_show(tmp_path: Path):
    project_args = ["--project-root", str(tmp_path)]
    daily = runner.invoke(
        app,
        [
            "run",
            "daily",
            "--trade-date",
            "2026-07-29",
            "--provider",
            "sample",
            *project_args,
        ],
    )
    assert daily.exit_code == 0, daily.stdout
    assert "status: AWAITING_APPROVAL" in daily.stdout
    run_id = value_from_output(daily.stdout, "run_id")

    approval = runner.invoke(
        app,
        [
            "approval",
            "grant",
            "--run-id",
            run_id,
            "--approver",
            "cli-operator",
            *project_args,
        ],
    )
    assert approval.exit_code == 0, approval.stdout
    assert "plan_checksum:" in approval.stdout

    paper = runner.invoke(
        app,
        ["paper", "run", "--run-id", run_id, *project_args],
    )
    assert paper.exit_code == 0, paper.stdout
    assert "status: COMPLETED" in paper.stdout

    show = runner.invoke(
        app,
        ["run", "show", "--run-id", run_id, *project_args],
    )
    assert show.exit_code == 0, show.stdout
    manifest = json.loads(show.stdout)
    assert manifest["run_id"] == run_id
    assert manifest["status"] == "COMPLETED"
    assert manifest["artifacts"]["report"]["path"].endswith("_final_report.md")


def test_live_mode_remains_disabled(tmp_path: Path):
    result = runner.invoke(
        app,
        [
            "run",
            "pipeline",
            "--mode",
            "live",
            "--project-root",
            str(tmp_path),
        ],
    )

    assert result.exit_code != 0
    assert not (tmp_path / "artifacts" / "portfolio.db").exists()
