from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import yaml

from quant_agent.common.run_index import RunIndex
from quant_agent.risk.rules.kill_switch import check_kill_switch
from quant_agent.risk.rules.position_limit import apply_single_position_limit
from quant_agent.schemas.research import TargetPositionRequest
from quant_agent.schemas.risk import RiskDecision


class RiskEngine:
    def __init__(
        self,
        *,
        artifact_root: str | Path,
        max_single_weight: float,
        kill_switch_file: str = "KILL_SWITCH",
    ):
        self.artifact_root = Path(artifact_root)
        self.max_single_weight = max_single_weight
        self.kill_switch_file = kill_switch_file

    @classmethod
    def from_config(cls, config_path: str | Path, artifact_root: str | Path) -> RiskEngine:
        config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
        limits = cast(dict[str, Any], config.get("limits", {}))
        kill_switch = cast(dict[str, Any], config.get("kill_switch", {}))
        return cls(
            artifact_root=artifact_root,
            max_single_weight=float(limits.get("max_single_weight", 0.2)),
            kill_switch_file=str(kill_switch.get("file_path", "KILL_SWITCH")),
        )

    def validate_targets(self, request: TargetPositionRequest) -> RiskDecision:
        kill_switch_violation = check_kill_switch(self.artifact_root, self.kill_switch_file)
        if kill_switch_violation:
            return RiskDecision(
                run_id=request.run_id,
                strategy_id=request.strategy_id,
                approved=False,
                decision="REJECT",
                positions=[],
                violations=[kill_switch_violation],
            )

        positions = []
        violations = []
        for position in request.positions:
            approved_position, violation = apply_single_position_limit(
                position,
                self.max_single_weight,
            )
            positions.append(approved_position)
            if violation:
                violations.append(violation)
        decision = "ADJUST" if violations else "APPROVE"
        return RiskDecision(
            run_id=request.run_id,
            strategy_id=request.strategy_id,
            approved=True,
            decision=decision,
            positions=positions,
            violations=violations,
        )

    def validate_file(self, target_path: str | Path) -> tuple[RiskDecision, Path]:
        payload = json.loads(Path(target_path).read_text(encoding="utf-8"))
        request = TargetPositionRequest.model_validate(payload)
        decision = self.validate_targets(request)
        output_dir = self.artifact_root / "risk_runs" / request.run_id
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "approved_positions.json"
        output_path.write_text(
            json.dumps(decision.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        RunIndex(self.artifact_root).update(
            risk_run=request.run_id,
            approved_positions=str(output_path),
            risk_decision=decision.decision,
        )
        return decision, output_path
