from __future__ import annotations

from quant_agent.schemas.risk import RiskDecision


def summarize_risk_decision(decision: RiskDecision) -> str:
    return (
        f"decision: {decision.decision}\n"
        f"approved: {decision.approved}\n"
        f"violations: {len(decision.violations)}"
    )
