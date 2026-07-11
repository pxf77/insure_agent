import json
from pathlib import Path

from typer.testing import CliRunner

from quant_agent.evals.risk import run_risk_evals
from quant_agent.risk.v2_cli import app

runner = CliRunner()


def test_risk_eval_suite_v04_passes() -> None:
    report = run_risk_evals(Path("evals/risk/v0.4.yaml"))

    assert report.success
    assert report.total == 18
    assert report.passed == 18
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
