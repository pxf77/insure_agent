from __future__ import annotations

from pathlib import Path

from quant_agent.schemas.risk import RiskViolation


def check_kill_switch(
    artifact_root: str | Path,
    file_path: str = "KILL_SWITCH",
) -> RiskViolation | None:
    path = Path(file_path)
    if not path.is_absolute():
        path = Path(artifact_root) / path
    if not path.exists():
        return None
    return RiskViolation(
        rule_id="KILL_SWITCH",
        severity="ERROR",
        symbol=None,
        message=f"kill switch is active: {path}",
    )
