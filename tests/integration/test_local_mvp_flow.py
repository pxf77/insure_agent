from typer.testing import CliRunner

from quant_agent.cli import app

runner = CliRunner()


def invoke(args):
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.stdout
    return result


def test_local_mvp_flow_runs_end_to_end(tmp_path):
    base_args = ["--project-root", str(tmp_path)]

    invoke(["init", *base_args])
    invoke(["data", "pull", "--sample", *base_args])
    invoke(["data", "convert", *base_args])
    research = invoke(["research", "qlib", *base_args])
    assert "target_positions.json" in research.stdout

    risk = invoke(["risk", "validate", *base_args])
    assert "decision: ADJUST" in risk.stdout

    paper = invoke(["paper", "run", *base_args])
    assert "trades.json" in paper.stdout

    report = invoke(["report", "generate", *base_args])
    assert "report.md" in report.stdout

    latest = invoke(["latest", *base_args])
    assert "research_run" in latest.stdout
    assert "report" in latest.stdout

    assert (tmp_path / "artifacts" / "research_runs").is_dir()
    assert (tmp_path / "artifacts" / "risk_runs").is_dir()
    assert (tmp_path / "artifacts" / "execution_runs").is_dir()
    assert (tmp_path / "artifacts" / "reports").is_dir()


def test_kill_switch_blocks_risk_validation(tmp_path):
    base_args = ["--project-root", str(tmp_path)]

    invoke(["init", *base_args])
    invoke(["data", "pull", "--sample", *base_args])
    invoke(["data", "convert", *base_args])
    invoke(["research", "qlib", *base_args])

    (tmp_path / "artifacts" / "KILL_SWITCH").write_text("stop\n", encoding="utf-8")

    result = runner.invoke(app, ["risk", "validate", *base_args])

    assert result.exit_code == 2, result.stdout
    assert "decision: REJECT" in result.stdout
    assert "approved: False" in result.stdout
