from __future__ import annotations

from quant_agent.schemas.research import TargetPosition
from quant_agent.schemas.risk import ApprovedPosition, RiskViolation


def apply_single_position_limit(
    position: TargetPosition,
    max_single_weight: float,
) -> tuple[ApprovedPosition, RiskViolation | None]:
    if position.target_weight <= max_single_weight:
        return (
            ApprovedPosition(
                symbol=position.symbol,
                target_weight=position.target_weight,
                adjusted=False,
                reason=None,
            ),
            None,
        )
    return (
        ApprovedPosition(
            symbol=position.symbol,
            target_weight=max_single_weight,
            adjusted=True,
            reason="max_single_weight",
        ),
        RiskViolation(
            rule_id="MAX_SINGLE_WEIGHT",
            severity="WARN",
            symbol=position.symbol,
            message=(
                f"weight adjusted from {position.target_weight:.4f} "
                f"to {max_single_weight:.4f}"
            ),
        ),
    )
