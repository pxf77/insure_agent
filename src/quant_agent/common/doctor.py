from __future__ import annotations

import importlib.util
import platform
import shutil
import sys
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field

from quant_agent.common.config import AppConfig, load_app_config
from quant_agent.common.paths import ProjectPaths


class DoctorProfile(str, Enum):
    MVP = "mvp"
    RESEARCH = "research"
    EXECUTION = "execution"


class CheckStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class DoctorCheck(BaseModel):
    check_id: str
    status: CheckStatus
    message: str
    remediation: str | None = None
    details: dict[str, str] = Field(default_factory=dict)


class DoctorReport(BaseModel):
    profile: DoctorProfile
    generated_at: datetime
    overall_status: CheckStatus
    has_failures: bool
    checks: list[DoctorCheck]


_REQUIRED_MODULES: dict[DoctorProfile, tuple[tuple[str, str], ...]] = {
    DoctorProfile.MVP: (),
    DoctorProfile.RESEARCH: (("qlib", "pyqlib"), ("lightgbm", "lightgbm")),
    DoctorProfile.EXECUTION: (("vnpy", "vnpy"),),
}
_ALL_OPTIONAL_MODULES: tuple[tuple[str, str], ...] = (
    ("qlib", "pyqlib"),
    ("lightgbm", "lightgbm"),
    ("mlflow", "mlflow"),
    ("rdagent", "rdagent"),
    ("vnpy", "vnpy"),
)


def _check_python() -> DoctorCheck:
    version = sys.version_info
    supported = (3, 10) <= (version.major, version.minor) < (3, 14)
    return DoctorCheck(
        check_id="python_version",
        status=CheckStatus.PASS if supported else CheckStatus.FAIL,
        message=f"Python {platform.python_version()} is {'supported' if supported else 'unsupported'}.",
        remediation=None if supported else "Install Python >=3.10,<3.14.",
    )


def _check_platform(profile: DoctorProfile) -> DoctorCheck:
    system = platform.system().lower()
    machine = platform.machine().lower()
    status = CheckStatus.PASS
    message = f"Platform {system}/{machine} is suitable for local development."
    remediation = None
    if profile == DoctorProfile.EXECUTION and system == "darwin":
        status = CheckStatus.WARN
        message = "macOS supports paper execution, but broker gateways may require Linux/Windows."
        remediation = "Use a dedicated Linux or Windows host before live gateway validation."
    return DoctorCheck(
        check_id="platform",
        status=status,
        message=message,
        remediation=remediation,
        details={"system": system, "machine": machine},
    )


def _check_timezone(config: AppConfig) -> DoctorCheck:
    try:
        ZoneInfo(config.app.timezone)
    except ZoneInfoNotFoundError:
        return DoctorCheck(
            check_id="timezone",
            status=CheckStatus.FAIL,
            message=f"Unknown timezone: {config.app.timezone}",
            remediation="Use an IANA timezone such as Asia/Shanghai.",
        )
    return DoctorCheck(
        check_id="timezone",
        status=CheckStatus.PASS,
        message=f"Timezone {config.app.timezone} is valid.",
    )


def _check_live_safety(config: AppConfig, profile: DoctorProfile) -> DoctorCheck:
    if not config.runtime.allow_live_trading:
        return DoctorCheck(
            check_id="live_trading_safety",
            status=CheckStatus.PASS,
            message="Live trading is disabled.",
        )
    if config.app.env != "live":
        return DoctorCheck(
            check_id="live_trading_safety",
            status=CheckStatus.FAIL,
            message=f"Live trading is enabled in non-live environment {config.app.env!r}.",
            remediation="Set runtime.allow_live_trading=false for dev/research/paper environments.",
        )
    if profile != DoctorProfile.EXECUTION:
        return DoctorCheck(
            check_id="live_trading_safety",
            status=CheckStatus.FAIL,
            message="Live trading configuration requires the execution doctor profile.",
            remediation="Run with --profile execution after completing live-readiness review.",
        )
    if not config.runtime.require_manual_approval:
        return DoctorCheck(
            check_id="live_trading_safety",
            status=CheckStatus.FAIL,
            message="Live trading is enabled without manual approval.",
            remediation="Set runtime.require_manual_approval=true.",
        )
    return DoctorCheck(
        check_id="live_trading_safety",
        status=CheckStatus.WARN,
        message="Live trading is enabled; this command does not certify broker readiness.",
        remediation="Complete the live-trading checklist and two-person approval before use.",
    )


def _check_artifact_writable(config: AppConfig, project_root: Path) -> DoctorCheck:
    paths = ProjectPaths.from_config(config, project_root=project_root)
    probe = paths.artifact_dir / ".doctor-write-probe"
    try:
        paths.ensure()
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return DoctorCheck(
            check_id="artifact_writable",
            status=CheckStatus.FAIL,
            message=f"Artifact directory is not writable: {paths.artifact_dir}",
            remediation="Fix directory ownership or configure a writable artifact_dir.",
            details={"error": str(exc)},
        )
    return DoctorCheck(
        check_id="artifact_writable",
        status=CheckStatus.PASS,
        message=f"Artifact directory is writable: {paths.artifact_dir}",
    )


def _check_module(module_name: str, package_name: str, *, required: bool) -> DoctorCheck:
    available = importlib.util.find_spec(module_name) is not None
    if available:
        return DoctorCheck(
            check_id=f"module_{module_name}",
            status=CheckStatus.PASS,
            message=f"Python module {module_name} is available.",
        )
    return DoctorCheck(
        check_id=f"module_{module_name}",
        status=CheckStatus.FAIL if required else CheckStatus.WARN,
        message=f"Python module {module_name} is not installed.",
        remediation=f"Install the project extra or package providing {package_name}.",
    )


def _check_executable(name: str, *, required: bool = False) -> DoctorCheck:
    executable = shutil.which(name)
    if executable:
        return DoctorCheck(
            check_id=f"executable_{name}",
            status=CheckStatus.PASS,
            message=f"Executable {name} is available.",
            details={"path": executable},
        )
    return DoctorCheck(
        check_id=f"executable_{name}",
        status=CheckStatus.FAIL if required else CheckStatus.WARN,
        message=f"Executable {name} is not available on PATH.",
        remediation=f"Install {name} or use the documented alternative workflow.",
    )


def _build_report(profile: DoctorProfile, checks: list[DoctorCheck]) -> DoctorReport:
    has_failures = any(check.status == CheckStatus.FAIL for check in checks)
    if has_failures:
        overall_status = CheckStatus.FAIL
    elif any(check.status == CheckStatus.WARN for check in checks):
        overall_status = CheckStatus.WARN
    else:
        overall_status = CheckStatus.PASS
    return DoctorReport(
        profile=profile,
        generated_at=datetime.now(timezone.utc),
        overall_status=overall_status,
        has_failures=has_failures,
        checks=checks,
    )


def run_doctor(
    *,
    config_path: str | Path,
    project_root: str | Path = ".",
    profile: DoctorProfile = DoctorProfile.MVP,
) -> DoctorReport:
    checks = [_check_python(), _check_platform(profile)]
    try:
        config = load_app_config(config_path)
    except (FileNotFoundError, ValueError) as exc:
        checks.append(
            DoctorCheck(
                check_id="config",
                status=CheckStatus.FAIL,
                message=f"Configuration could not be loaded: {config_path}",
                remediation="Create a valid YAML config based on configs/env/dev.yaml.",
                details={"error": str(exc)},
            )
        )
        return _build_report(profile, checks)

    checks.extend(
        (
            DoctorCheck(
                check_id="config",
                status=CheckStatus.PASS,
                message=f"Configuration loaded for environment {config.app.env}.",
            ),
            _check_timezone(config),
            _check_live_safety(config, profile),
            _check_artifact_writable(config, Path(project_root)),
            _check_executable("uv"),
            _check_executable("docker"),
        )
    )

    required_modules = {name for name, _ in _REQUIRED_MODULES[profile]}
    seen: set[str] = set()
    for module_name, package_name in _ALL_OPTIONAL_MODULES:
        if module_name in seen:
            continue
        seen.add(module_name)
        checks.append(
            _check_module(
                module_name,
                package_name,
                required=module_name in required_modules,
            )
        )

    return _build_report(profile, checks)


def render_doctor_report(report: DoctorReport) -> str:
    lines = [f"profile: {report.profile.value}"]
    for check in report.checks:
        lines.append(f"[{check.status.value}] {check.check_id}: {check.message}")
        if check.remediation:
            lines.append(f"  remediation: {check.remediation}")
    lines.append(f"overall: {report.overall_status.value}")
    return "\n".join(lines)
