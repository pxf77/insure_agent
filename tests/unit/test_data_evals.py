import json
from pathlib import Path

from typer.testing import CliRunner

from quant_agent.cli import app
from quant_agent.evals.data import run_data_evals

runner = CliRunner()


def test_data_eval_suite_v02_passes() -> None:
    report = run_data_evals(Path("evals/data/v0.2.yaml"))

    assert report.success
    assert report.total == 9
    assert report.passed == 9
    assert report.failed == 0


def test_data_eval_cli_emits_json() -> None:
    result = runner.invoke(
        app,
        ["eval", "data", "--suite", "evals/data/v0.2.yaml", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["suite_version"] == "0.2"
    assert payload["total"] == 9
    assert payload["failed"] == 0


def test_data_eval_cli_fails_for_wrong_expectation(tmp_path: Path) -> None:
    suite = tmp_path / "failing.yaml"
    suite.write_text(
        """
suite_version: test
cases:
  - id: valid-row-marked-invalid
    action: quality
    rows:
      - trade_date: "2026-05-20"
        symbol: "600519.SH"
        open: 100
        high: 110
        low: 99
        close: 105
        volume: 1000
        amount: 105000
        available_at: "2026-05-20T15:05:00+08:00"
    expect_success: false
""".strip(),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["eval", "data", "--suite", str(suite)])

    assert result.exit_code == 1
    assert "[FAIL] valid-row-marked-invalid" in result.stdout
