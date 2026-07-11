import json
from pathlib import Path

from typer.testing import CliRunner

from quant_agent.cli import app
from quant_agent.common.doctor import CheckStatus, DoctorProfile, run_doctor

runner = CliRunner()


def _status(report, check_id: str) -> CheckStatus:
    return next(check.status for check in report.checks if check.check_id == check_id)


def test_mvp_doctor_has_no_failures(tmp_path: Path) -> None:
    report = run_doctor(
        config_path=Path("configs/env/dev.yaml"),
        project_root=tmp_path,
        profile=DoctorProfile.MVP,
    )

    assert not report.has_failures
    assert _status(report, "config") == CheckStatus.PASS
    assert _status(report, "artifact_writable") == CheckStatus.PASS
    assert _status(report, "live_trading_safety") == CheckStatus.PASS
    assert any(check.check_id == "module_qlib" for check in report.checks)
    assert any(check.check_id == "module_vnpy" for check in report.checks)


def test_dev_live_trading_is_rejected(tmp_path: Path) -> None:
    config = tmp_path / "unsafe.yaml"
    config.write_text(
        """
app:
  env: dev
  artifact_dir: artifacts
runtime:
  allow_live_trading: true
  require_manual_approval: true
""".strip(),
        encoding="utf-8",
    )

    report = run_doctor(
        config_path=config,
        project_root=tmp_path,
        profile=DoctorProfile.MVP,
    )

    assert report.has_failures
    assert report.overall_status == CheckStatus.FAIL
    assert _status(report, "live_trading_safety") == CheckStatus.FAIL


def test_doctor_cli_emits_json(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "doctor",
            "--profile",
            "mvp",
            "--json",
            "--config",
            "configs/env/dev.yaml",
            "--project-root",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["profile"] == "mvp"
    assert payload["has_failures"] is False
    assert payload["overall_status"] in {"PASS", "WARN"}
    assert any(item["check_id"] == "live_trading_safety" for item in payload["checks"])


def test_doctor_cli_rejects_invalid_profile(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["doctor", "--profile", "bogus", "--project-root", str(tmp_path)],
    )

    assert result.exit_code == 2
    assert "profile must be one of" in result.output
