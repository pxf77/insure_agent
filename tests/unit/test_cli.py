
from typer.testing import CliRunner

from quant_agent.cli import app

runner = CliRunner()


def test_status_command_reports_dev_environment():
    result = runner.invoke(app, ["status", "--config", "configs/env/dev.yaml"])

    assert result.exit_code == 0
    assert "env: dev" in result.stdout
    assert "live_trading: disabled" in result.stdout


def test_init_creates_artifact_directories(tmp_path):
    result = runner.invoke(
        app,
        ["init", "--config", "configs/env/dev.yaml", "--project-root", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert (tmp_path / "artifacts" / "data" / "raw").is_dir()
    assert (tmp_path / "artifacts" / "reports").is_dir()


def test_data_pull_and_convert_create_sample_outputs(tmp_path):
    pull_result = runner.invoke(
        app,
        [
            "data",
            "pull",
            "--sample",
            "--config",
            "configs/env/dev.yaml",
            "--project-root",
            str(tmp_path),
        ],
    )

    assert pull_result.exit_code == 0
    assert (tmp_path / "artifacts" / "data" / "raw" / "daily_bar.csv").is_file()

    convert_result = runner.invoke(
        app,
        [
            "data",
            "convert",
            "--config",
            "configs/env/dev.yaml",
            "--project-root",
            str(tmp_path),
        ],
    )

    assert convert_result.exit_code == 0
    assert (tmp_path / "artifacts" / "data" / "qlib" / "cn_data" / "metadata.json").is_file()
