import json
from pathlib import Path

from typer.testing import CliRunner

from quant_agent.cli import app
from quant_agent.evals.contracts import run_contract_evals
from quant_agent.schemas.exporter import export_contract_schemas

runner = CliRunner()


def test_contract_eval_suite_v01_passes() -> None:
    report = run_contract_evals(Path("evals/contracts/v0.1.yaml"))

    assert report.success
    assert report.total == 21
    assert report.passed == 21
    assert report.failed == 0


def test_contract_eval_runner_reports_intentional_failure(tmp_path: Path) -> None:
    suite = tmp_path / "failing.yaml"
    suite.write_text(
        """
suite_version: test
cases:
  - id: expected-invalid-but-valid
    model: instrument-id-1.0
    payload: "600519.SH"
    expect_valid: false
""".strip(),
        encoding="utf-8",
    )

    report = run_contract_evals(suite)

    assert not report.success
    assert report.failed == 1
    assert report.outcomes[0].actual == "valid"


def test_schema_export_is_deterministic_and_indexed(tmp_path: Path) -> None:
    first = export_contract_schemas(tmp_path / "schemas")
    first_index = first.index_path.read_text(encoding="utf-8")
    second = export_contract_schemas(tmp_path / "schemas")

    assert first_index == second.index_path.read_text(encoding="utf-8")
    payload = json.loads(first_index)
    assert payload["schema_set_version"] == "v0.1"
    assert len(payload["schemas"]) == 6
    assert all(len(entry["sha256"]) == 64 for entry in payload["schemas"])


def test_contract_commands_export_and_evaluate(tmp_path: Path) -> None:
    export_result = runner.invoke(
        app,
        ["contracts", "export", "--output", str(tmp_path / "schemas")],
    )
    assert export_result.exit_code == 0, export_result.output
    assert (tmp_path / "schemas" / "index.json").is_file()

    eval_result = runner.invoke(
        app,
        ["eval", "contracts", "--suite", "evals/contracts/v0.1.yaml", "--json"],
    )
    assert eval_result.exit_code == 0, eval_result.output
    report = json.loads(eval_result.stdout)
    assert report["failed"] == 0
    assert report["total"] == 21


def test_contract_eval_cli_exits_nonzero_on_failure(tmp_path: Path) -> None:
    suite = tmp_path / "failing.yaml"
    suite.write_text(
        """
suite_version: test
cases:
  - id: expected-invalid-but-valid
    model: instrument-id-1.0
    payload: "600519.SH"
    expect_valid: false
""".strip(),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["eval", "contracts", "--suite", str(suite)])

    assert result.exit_code == 1
    assert "[FAIL] expected-invalid-but-valid" in result.stdout
