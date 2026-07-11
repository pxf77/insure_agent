import json
from pathlib import Path

from typer.testing import CliRunner

from quant_agent.cli import app
from quant_agent.common import doctor as doctor_module
from quant_agent.common.doctor import CheckStatus, DoctorProfile, run_doctor

runner = CliRunner()


def _status(report, check_id: str) -> CheckStatus:
    return next(check.status for check in report.checks if check.check_id == check_id)


def _write_live_config(path: Path, *, env: str) -> Path:
    path.write_text(
        f"""
app:
  env: {env}
  artifact_dir: artifacts
runtime:
  allow_live_trading: true
  require_manual_approval: true
""".strip(),
        encoding="utf-8",
    )
    return path


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
    config = _write_live_config(tmp_path / "unsafe.yaml", env="dev")

    report = run_doctor(
        config_path=config,
        project_root=tmp_path,
        profile=DoctorProfile.MVP,
    )

    assert report.has_failures
    assert report.overall_status == CheckStatus.FAIL
    assert _status(report, "live_trading_safety") == CheckStatus.FAIL


def test_nominal_live_configuration_is_rejected_until_m9(tmp_path: Path) -> None:
    config = _write_live_config(tmp_path / "live.yaml", env="live")

    report = run_doctor(
        config_path=config,
        project_root=tmp_path,
        profile=DoctorProfile.EXECUTION,
    )

    assert report.has_failures
    assert _status(report, "live_trading_safety") == CheckStatus.FAIL
    live_check = next(
        check for check in report.checks if check.check_id == "live_trading_safety"
    )
    assert "not implemented or certified" in live_check.message


def test_research_profile_fails_when_required_modules_are_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(doctor_module.importlib.util, "find_spec", lambda _name: None)

    report = run_doctor(
        config_path=Path("configs/env/dev.yaml"),
        project_root=tmp_path,
        profile=DoctorProfile.RESEARCH,
    )

    assert report.has_failures
    assert _status(report, "module_qlib") == CheckStatus.FAIL
    assert _status(report, "module_lightgbm") == CheckStatus.FAIL
    assert _status(report, "module_vnpy") == CheckStatus.WARN


def test_execution_profile_fails_when_vnpy_is_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(doctor_module.importlib.util, "find_spec", lambda _name: None)

    report = run_doctor(
        config_path=Path("configs/env/dev.yaml"),
        project_root=tmp_path,
        profile=DoctorProfile.EXECUTION,
    )

    assert report.has_failures
    assert _status(report, "module_vnpy") == CheckStatus.FAIL
    assert _status(report, "module_qlib") == CheckStatus.WARN


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
