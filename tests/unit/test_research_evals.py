import json
from pathlib import Path

from typer.testing import CliRunner

from quant_agent.cli import app
from quant_agent.evals.research import run_research_evals

runner = CliRunner()


def test_research_eval_suite_v03_passes() -> None:
    report = run_research_evals(Path("evals/research/v0.3.yaml"))

    assert report.success
    assert report.total == 5
    assert report.passed == 5
    assert report.failed == 0


def test_research_eval_cli_emits_json() -> None:
    result = runner.invoke(
        app,
        [
            "eval",
            "research",
            "--suite",
            "evals/research/v0.3.yaml",
            "--config",
            "configs/research/snapshot_baseline.yaml",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["suite_version"] == "0.3"
    assert payload["total"] == 5
    assert payload["failed"] == 0


def test_research_eval_cli_exits_nonzero_for_unknown_action(tmp_path: Path) -> None:
    suite = tmp_path / "invalid.yaml"
    suite.write_text(
        """
suite_version: invalid
cases:
  - id: invalid-action
    action: unsupported
""".strip(),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["eval", "research", "--suite", str(suite)])

    assert result.exit_code != 0
