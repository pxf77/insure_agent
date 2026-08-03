from __future__ import annotations

import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from quant_agent.risk.approval_store import ApprovalStore
from quant_agent.risk.kill_switch_store import KillSwitchStore
from quant_agent.risk.v2_engine import DeterministicRiskEngine
from quant_agent.risk.v2_models import (
    ApprovalEvidence,
    KillSwitchScope,
    RiskContext,
    RiskPolicy,
)
from quant_agent.schemas.v2 import RiskDecisionType, TargetPortfolio

RiskEvalAction = Literal[
    "approve",
    "single_weight",
    "total_weight",
    "industry_weight",
    "liquidity",
    "t_plus_one",
    "suspended",
    "st_buy",
    "limit_up",
    "limit_down",
    "stale_data",
    "future_snapshot",
    "missing_approval",
    "approval_scope_mismatch",
    "approval_expired",
    "approval_future",
    "daily_loss",
    "drawdown",
    "hard_kill_switch",
    "reduce_only",
    "missing_instrument_context",
    "duplicate_context",
    "strategy_mismatch",
    "infeasible_total_floor",
]


class RiskEvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=200)
    action: RiskEvalAction
    expected_decision: RiskDecisionType | None = None
    expected_reason_codes: list[str] = Field(default_factory=list)
    expected_weights: dict[str, Decimal] = Field(default_factory=dict)
    expected_error: str | None = None
    tags: list[str] = Field(default_factory=list)
    severity: str = "normal"


class RiskEvalOutcome(BaseModel):
    case_id: str
    passed: bool
    action: str
    details: str | None = None


class RiskEvalReport(BaseModel):
    suite_version: str
    total: int
    passed: int
    failed: int
    outcomes: list[RiskEvalOutcome]

    @property
    def success(self) -> bool:
        return self.failed == 0


def load_risk_cases(suite_path: str | Path) -> tuple[str, list[RiskEvalCase]]:
    path = Path(suite_path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    suite_version = str(payload.get("suite_version", "unknown"))
    cases = [RiskEvalCase.model_validate(item) for item in payload.get("cases", [])]
    if not cases:
        raise ValueError(f"risk evaluation suite contains no cases: {path}")
    identifiers = [case.id for case in cases]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("risk evaluation case IDs must be unique")
    return suite_version, cases


def _base_target() -> dict[str, Any]:
    return {
        "run_id": "research-risk-eval",
        "strategy_id": "strategy-risk-eval",
        "trade_date": "2026-05-22",
        "generated_at": "2026-05-22T08:00:00Z",
        "universe": "risk-eval-universe",
        "positions": [
            {"instrument": "600519.SH", "target_weight": "0.15", "score": "1.0", "rank": 1},
            {"instrument": "000001.SZ", "target_weight": "0.15", "score": "0.8", "rank": 2},
            {"instrument": "300750.SZ", "target_weight": "0.15", "score": "0.6", "rank": 3},
        ],
    }


def _approval() -> dict[str, Any]:
    return {
        "approval_id": "11111111-1111-4111-8111-111111111111",
        "status": "APPROVED",
        "account_id": "paper-account",
        "strategy_id": "strategy-risk-eval",
        "target_run_id": "research-risk-eval",
        "policy_version": "risk-eval-v1",
        "approved_at": "2026-05-22T23:00:00Z",
        "expires_at": "2026-05-23T01:00:00Z",
        "approvers": ["risk-officer"],
    }


def _base_context() -> dict[str, Any]:
    return {
        "account_id": "paper-account",
        "strategy_id": "strategy-risk-eval",
        "evaluated_at": "2026-05-23T00:00:00Z",
        "snapshot_as_of": "2026-05-22T07:05:00Z",
        "account_value": "1000000",
        "cash": "550000",
        "daily_loss": "0.01",
        "drawdown": "0.05",
        "approval": _approval(),
        "current_positions": [
            {
                "instrument": "600519.SH",
                "current_weight": "0.10",
                "sellable_weight": "0.05",
                "industry": "Consumer",
            },
            {
                "instrument": "000001.SZ",
                "current_weight": "0.10",
                "sellable_weight": "0.10",
                "industry": "Financial",
            },
            {
                "instrument": "300750.SZ",
                "current_weight": "0.10",
                "sellable_weight": "0.00",
                "industry": "NewEnergy",
            },
        ],
        "instruments": [
            {
                "instrument": "600519.SH",
                "industry": "Consumer",
                "last_price": "1500",
                "max_liquidity_weight": "0.25",
            },
            {
                "instrument": "000001.SZ",
                "industry": "Financial",
                "last_price": "12",
                "max_liquidity_weight": "0.25",
            },
            {
                "instrument": "300750.SZ",
                "industry": "NewEnergy",
                "last_price": "220",
                "max_liquidity_weight": "0.25",
            },
        ],
    }


def _base_policy() -> dict[str, Any]:
    return {
        "policy_version": "risk-eval-v1",
        "max_data_age_minutes": 1440,
        "max_single_weight": "0.20",
        "max_total_weight": "0.80",
        "max_industry_weight": "0.35",
        "minimum_cash_weight": "0.20",
        "max_daily_loss": "0.05",
        "max_drawdown": "0.20",
        "allow_st": False,
        "require_approval": True,
    }


def _position(target: dict[str, Any], instrument: str) -> dict[str, Any]:
    for item in cast(list[dict[str, Any]], target["positions"]):
        if item["instrument"] == instrument:
            return item
    raise KeyError(instrument)


def _instrument(context: dict[str, Any], instrument: str) -> dict[str, Any]:
    for item in cast(list[dict[str, Any]], context["instruments"]):
        if item["instrument"] == instrument:
            return item
    raise KeyError(instrument)


def _current_position(context: dict[str, Any], instrument: str) -> dict[str, Any]:
    for item in cast(list[dict[str, Any]], context["current_positions"]):
        if item["instrument"] == instrument:
            return item
    raise KeyError(instrument)


def _prepare_case(
    case: RiskEvalCase,
    store: KillSwitchStore,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    target = _base_target()
    context = _base_context()
    policy = _base_policy()
    action = case.action

    if action == "single_weight":
        _position(target, "600519.SH")["target_weight"] = "0.30"
    elif action == "total_weight":
        policy["max_total_weight"] = "0.36"
        for item in cast(list[dict[str, Any]], context["current_positions"]):
            item["sellable_weight"] = item["current_weight"]
    elif action == "industry_weight":
        policy["max_industry_weight"] = "0.28"
        for item in cast(list[dict[str, Any]], context["current_positions"]):
            item["sellable_weight"] = item["current_weight"]
        target["positions"].append(
            {
                "instrument": "000858.SZ",
                "target_weight": "0.20",
                "score": "0.5",
                "rank": 4,
            }
        )
        context["instruments"].append(
            {
                "instrument": "000858.SZ",
                "industry": "Consumer",
                "last_price": "160",
                "max_liquidity_weight": "0.25",
            }
        )
    elif action == "liquidity":
        _instrument(context, "600519.SH")["max_liquidity_weight"] = "0.10"
    elif action == "t_plus_one":
        current = _current_position(context, "600519.SH")
        current["current_weight"] = "0.20"
        current["sellable_weight"] = "0.05"
        context["cash"] = "500000"
        _position(target, "600519.SH")["target_weight"] = "0.05"
    elif action == "suspended":
        _instrument(context, "600519.SH")["suspended"] = True
    elif action == "st_buy":
        _instrument(context, "600519.SH")["is_st"] = True
    elif action == "limit_up":
        _instrument(context, "600519.SH")["limit_up"] = True
    elif action == "limit_down":
        _instrument(context, "600519.SH")["limit_down"] = True
        _position(target, "600519.SH")["target_weight"] = "0.05"
    elif action == "stale_data":
        context["snapshot_as_of"] = "2026-05-20T00:00:00Z"
    elif action == "future_snapshot":
        context["snapshot_as_of"] = "2026-05-23T00:01:00Z"
    elif action == "missing_approval":
        context["approval"] = None
    elif action == "approval_scope_mismatch":
        _approval_payload = cast(dict[str, Any], context["approval"])
        _approval_payload["target_run_id"] = "forged-run"
    elif action == "approval_expired":
        _approval_payload = cast(dict[str, Any], context["approval"])
        _approval_payload["expires_at"] = "2026-05-22T23:59:00Z"
    elif action == "approval_future":
        _approval_payload = cast(dict[str, Any], context["approval"])
        _approval_payload["approved_at"] = "2026-05-23T00:01:00Z"
        _approval_payload["expires_at"] = "2026-05-23T01:00:00Z"
    elif action == "daily_loss":
        context["daily_loss"] = "0.05"
    elif action == "drawdown":
        context["drawdown"] = "0.20"
    elif action == "hard_kill_switch":
        store.set(
            scope=KillSwitchScope.GLOBAL,
            scope_id=None,
            active=True,
            reduce_only=False,
            reason_code="EVAL_HARD_KILL",
            message="evaluation hard kill",
            changed_by="eval",
        )
    elif action == "reduce_only":
        store.set(
            scope=KillSwitchScope.STRATEGY,
            scope_id="strategy-risk-eval",
            active=True,
            reduce_only=True,
            reason_code="EVAL_REDUCE_ONLY",
            message="evaluation reduce only",
            changed_by="eval",
        )
        _position(target, "600519.SH")["target_weight"] = "0.20"
    elif action == "missing_instrument_context":
        context["instruments"] = [
            item for item in context["instruments"] if item["instrument"] != "600519.SH"
        ]
    elif action == "duplicate_context":
        context["instruments"].append(dict(context["instruments"][0]))
    elif action == "strategy_mismatch":
        context["strategy_id"] = "different-strategy"
    elif action == "infeasible_total_floor":
        policy["max_total_weight"] = "0.40"
        context["cash"] = "400000"
        for item in cast(list[dict[str, Any]], context["current_positions"]):
            item["current_weight"] = "0.20"
            item["sellable_weight"] = "0.00"
        for item in cast(list[dict[str, Any]], target["positions"]):
            item["target_weight"] = "0.20"
    return target, context, policy


def _evaluate_case(case: RiskEvalCase) -> RiskEvalOutcome:
    try:
        with tempfile.TemporaryDirectory(prefix="quant-agent-risk-eval-") as temporary:
            store = KillSwitchStore(Path(temporary) / "kill_switches.json")
            approval_store = ApprovalStore(Path(temporary) / "approvals.json")
            target_payload, context_payload, policy_payload = _prepare_case(case, store)
            trusted_payload = _approval()
            if case.action in {"approval_expired", "approval_future"}:
                trusted_payload = cast(dict[str, Any], context_payload["approval"])
            approval_store.issue(ApprovalEvidence.model_validate(trusted_payload))
            target = TargetPortfolio.model_validate(target_payload)
            context = RiskContext.model_validate(context_payload)
            policy = RiskPolicy.model_validate(policy_payload)
            switch_state = store.read()
            approval_state = approval_store.read()
            decision = DeterministicRiskEngine(
                policy=policy,
                kill_switch_store=store,
                approval_store=approval_store,
            ).evaluate(
                target,
                context,
                kill_switch_state=switch_state,
                approval_state=approval_state,
            )
    except (ValidationError, ValueError) as exc:
        if case.expected_error and case.expected_error.lower() in str(exc).lower():
            return RiskEvalOutcome(case_id=case.id, passed=True, action=case.action)
        return RiskEvalOutcome(
            case_id=case.id,
            passed=False,
            action=case.action,
            details=str(exc),
        )

    if case.expected_error:
        return RiskEvalOutcome(
            case_id=case.id,
            passed=False,
            action=case.action,
            details="evaluation unexpectedly produced a decision",
        )
    reason_codes = {result.reason_code for result in decision.rule_results}
    missing_codes = sorted(set(case.expected_reason_codes) - reason_codes)
    actual_weights = {
        str(position.instrument): position.target_weight for position in decision.positions
    }
    weight_mismatches = {
        instrument: {"expected": expected, "actual": actual_weights.get(instrument)}
        for instrument, expected in case.expected_weights.items()
        if actual_weights.get(instrument) != expected
    }
    passed = (
        decision.decision == case.expected_decision
        and not missing_codes
        and not weight_mismatches
    )
    details = None
    if not passed:
        details = (
            f"decision={decision.decision}, expected={case.expected_decision}, "
            f"missing_codes={missing_codes}, weight_mismatches={weight_mismatches}"
        )
    return RiskEvalOutcome(
        case_id=case.id,
        passed=passed,
        action=case.action,
        details=details,
    )


def run_risk_evals(suite_path: str | Path) -> RiskEvalReport:
    suite_version, cases = load_risk_cases(suite_path)
    outcomes = [_evaluate_case(case) for case in cases]
    passed = sum(outcome.passed for outcome in outcomes)
    return RiskEvalReport(
        suite_version=suite_version,
        total=len(outcomes),
        passed=passed,
        failed=len(outcomes) - passed,
        outcomes=outcomes,
    )


def render_risk_eval_report(report: RiskEvalReport) -> str:
    lines = [
        f"suite_version: {report.suite_version}",
        f"result: {report.passed}/{report.total} passed",
    ]
    for outcome in report.outcomes:
        status = "PASS" if outcome.passed else "FAIL"
        lines.append(f"[{status}] {outcome.case_id} ({outcome.action})")
        if outcome.details and not outcome.passed:
            lines.append(f"  details: {outcome.details}")
    return "\n".join(lines)
