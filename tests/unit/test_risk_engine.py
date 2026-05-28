from pathlib import Path

import pytest

from quant_agent.risk.engine import RiskEngine
from quant_agent.schemas.research import TargetPosition, TargetPositionRequest


def make_target_request() -> TargetPositionRequest:
    return TargetPositionRequest(
        run_id="demo-run",
        strategy_id="demo_strategy",
        trade_date="2026-05-22",
        generated_at="2026-05-21T17:00:00+08:00",
        universe="CSI300",
        benchmark="SH000300",
        positions=[
            TargetPosition(symbol="600519.SH", target_weight=0.35, score=1.8, rank=1),
            TargetPosition(symbol="000001.SZ", target_weight=0.10, score=1.2, rank=2),
        ],
    )


def test_risk_engine_adjusts_single_position_limit(tmp_path):
    engine = RiskEngine.from_config(
        Path("configs/risk/default.yaml"),
        artifact_root=tmp_path / "artifacts",
    )

    result = engine.validate_targets(make_target_request())

    assert result.approved is True
    assert result.decision == "ADJUST"
    assert result.positions[0].target_weight == pytest.approx(0.2)
    assert result.positions[0].adjusted is True
    assert result.violations[0].rule_id == "MAX_SINGLE_WEIGHT"


def test_risk_engine_rejects_when_kill_switch_exists(tmp_path):
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    (artifact_root / "KILL_SWITCH").write_text("stop", encoding="utf-8")
    engine = RiskEngine.from_config(Path("configs/risk/default.yaml"), artifact_root=artifact_root)

    result = engine.validate_targets(make_target_request())

    assert result.approved is False
    assert result.decision == "REJECT"
    assert result.violations[0].rule_id == "KILL_SWITCH"
