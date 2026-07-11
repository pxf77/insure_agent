from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from quant_agent.risk.kill_switch_store import KillSwitchStore
from quant_agent.risk.v2_models import InstrumentRiskState, RiskContext, RiskPolicy
from quant_agent.schemas.v2 import (
    ApprovedTarget,
    RiskDecisionType,
    RiskDecisionV2,
    RiskRuleResult,
    RuleOutcome,
    TargetPortfolio,
)

_WEIGHT_QUANTUM = Decimal("0.0000000001")
_ZERO = Decimal("0")
_ONE = Decimal("1")


@dataclass(frozen=True)
class _Bound:
    value: Decimal
    rule_id: str
    reason_code: str
    message: str


@dataclass(frozen=True)
class _InfeasiblePortfolio(Exception):
    rule_id: str
    reason_code: str
    message: str


def _weight(value: Decimal) -> Decimal:
    if value <= _ZERO:
        return _ZERO
    return value.quantize(_WEIGHT_QUANTUM, rounding=ROUND_DOWN)


class DeterministicRiskEngine:
    """Ordered fail-closed risk evaluation for complete v2 target portfolios."""

    def __init__(self, *, policy: RiskPolicy, kill_switch_store: KillSwitchStore):
        self.policy = policy
        self.kill_switch_store = kill_switch_store

    def evaluate(self, target: TargetPortfolio, context: RiskContext) -> RiskDecisionV2:
        results: list[RiskRuleResult] = []
        if target.strategy_id != context.strategy_id:
            return self._reject(
                target,
                context,
                results,
                rule_id="INPUT_CONTEXT",
                reason_code="STRATEGY_CONTEXT_MISMATCH",
                message="target strategy_id does not match risk context",
            )

        market = {str(item.instrument): item for item in context.instruments}
        current = {str(item.instrument): item for item in context.current_positions}
        working_instruments = sorted(
            {str(position.instrument) for position in target.positions} | set(current)
        )
        missing_market = sorted(set(working_instruments) - set(market))
        if missing_market:
            return self._reject(
                target,
                context,
                results,
                rule_id="INPUT_CONTEXT",
                reason_code="MISSING_INSTRUMENT_CONTEXT",
                message=f"missing risk context for instruments: {missing_market}",
            )
        inconsistent_industries = sorted(
            instrument
            for instrument, position in current.items()
            if market[instrument].industry != position.industry
        )
        if inconsistent_industries:
            return self._reject(
                target,
                context,
                results,
                rule_id="INPUT_CONTEXT",
                reason_code="INDUSTRY_CONTEXT_MISMATCH",
                message=f"industry mismatch for instruments: {inconsistent_industries}",
            )
        current_invested = sum(
            (position.current_weight for position in current.values()),
            _ZERO,
        )
        cash_weight = context.cash / context.account_value
        if current_invested + cash_weight > _ONE + _WEIGHT_QUANTUM:
            return self._reject(
                target,
                context,
                results,
                rule_id="ACCOUNT_STATE",
                reason_code="ACCOUNT_STATE_INCONSISTENT",
                message="current position weights plus cash weight exceed account value",
            )

        freshness = context.evaluated_at - context.snapshot_as_of
        if freshness < timedelta(0):
            return self._reject(
                target,
                context,
                results,
                rule_id="DATA_FRESHNESS",
                reason_code="SNAPSHOT_FROM_FUTURE",
                message="snapshot_as_of is later than evaluated_at",
            )
        if freshness > timedelta(minutes=self.policy.max_data_age_minutes):
            return self._reject(
                target,
                context,
                results,
                rule_id="DATA_FRESHNESS",
                reason_code="STALE_DATA",
                message=(
                    f"snapshot age {freshness.total_seconds() / 60:.2f} minutes exceeds "
                    f"{self.policy.max_data_age_minutes} minutes"
                ),
            )
        results.append(
            self._result(
                rule_id="DATA_FRESHNESS",
                outcome=RuleOutcome.PASS,
                reason_code="DATA_FRESH",
                message="snapshot freshness is within policy",
            )
        )

        switches = self.kill_switch_store.active_for(
            account_id=context.account_id,
            strategy_id=context.strategy_id,
        )
        hard_switches = [record.switch_id for record in switches if not record.reduce_only]
        if hard_switches:
            return self._reject(
                target,
                context,
                results,
                rule_id="KILL_SWITCH",
                reason_code="KILL_SWITCH_ACTIVE",
                message=f"hard kill switch active: {hard_switches}",
            )
        reduce_only = bool(switches)
        results.append(
            self._result(
                rule_id="KILL_SWITCH",
                outcome=RuleOutcome.WARN if reduce_only else RuleOutcome.PASS,
                reason_code="REDUCE_ONLY_ACTIVE" if reduce_only else "NO_KILL_SWITCH",
                message=(
                    "reduce-only kill switch is active"
                    if reduce_only
                    else "no applicable kill switch is active"
                ),
            )
        )

        if context.daily_loss >= self.policy.max_daily_loss:
            return self._reject(
                target,
                context,
                results,
                rule_id="LOSS_LIMIT",
                reason_code="DAILY_LOSS_LIMIT",
                message="daily loss reached the configured limit",
            )
        if context.drawdown >= self.policy.max_drawdown:
            return self._reject(
                target,
                context,
                results,
                rule_id="DRAWDOWN_LIMIT",
                reason_code="DRAWDOWN_LIMIT",
                message="drawdown reached the configured limit",
            )
        results.extend(
            (
                self._result(
                    rule_id="LOSS_LIMIT",
                    outcome=RuleOutcome.PASS,
                    reason_code="DAILY_LOSS_OK",
                    message="daily loss is within policy",
                ),
                self._result(
                    rule_id="DRAWDOWN_LIMIT",
                    outcome=RuleOutcome.PASS,
                    reason_code="DRAWDOWN_OK",
                    message="drawdown is within policy",
                ),
            )
        )

        if self.policy.require_approval and context.approval_id is None:
            return self._reject(
                target,
                context,
                results,
                rule_id="APPROVAL",
                reason_code="APPROVAL_REQUIRED",
                message="risk policy requires a valid approval reference",
            )
        results.append(
            self._result(
                rule_id="APPROVAL",
                outcome=RuleOutcome.PASS,
                reason_code="APPROVAL_OK",
                message="approval requirement is satisfied",
            )
        )

        requested = {
            str(position.instrument): position.target_weight for position in target.positions
        }
        original = {
            instrument: requested.get(instrument, _ZERO)
            for instrument in working_instruments
        }
        weights = dict(original)
        floors: dict[str, Decimal] = {}
        reasons: dict[str, str] = {}
        for instrument in working_instruments:
            position = current.get(instrument)
            state = market[instrument]
            current_weight = position.current_weight if position else _ZERO
            sellable_weight = position.sellable_weight if position else _ZERO
            floor = _Bound(
                value=max(_ZERO, current_weight - sellable_weight),
                rule_id="T_PLUS_ONE",
                reason_code="T_PLUS_ONE_SELL_LIMIT",
                message="target reduction exceeds sellable position weight",
            )
            if state.limit_down and current_weight > floor.value:
                floor = _Bound(
                    value=current_weight,
                    rule_id="TRADABILITY",
                    reason_code="LIMIT_DOWN_SELL_BLOCKED",
                    message="limit-down instrument cannot be reduced",
                )
            if state.suspended and current_weight >= floor.value:
                floor = _Bound(
                    value=current_weight,
                    rule_id="TRADABILITY",
                    reason_code="SUSPENDED",
                    message="suspended instrument cannot be rebalanced",
                )

            ceiling = _Bound(
                value=min(state.max_liquidity_weight, self.policy.max_single_weight),
                rule_id=(
                    "LIQUIDITY"
                    if state.max_liquidity_weight <= self.policy.max_single_weight
                    else "SINGLE_POSITION"
                ),
                reason_code=(
                    "LIQUIDITY_CAP"
                    if state.max_liquidity_weight <= self.policy.max_single_weight
                    else "MAX_SINGLE_WEIGHT"
                ),
                message=(
                    "target weight exceeds liquidity capacity"
                    if state.max_liquidity_weight <= self.policy.max_single_weight
                    else "target weight exceeds single-position limit"
                ),
            )
            if state.limit_up and current_weight < ceiling.value:
                ceiling = _Bound(
                    value=current_weight,
                    rule_id="TRADABILITY",
                    reason_code="LIMIT_UP_BUY_BLOCKED",
                    message="limit-up instrument cannot be increased",
                )
            if state.is_st and not self.policy.allow_st and current_weight <= ceiling.value:
                ceiling = _Bound(
                    value=current_weight,
                    rule_id="TRADABILITY",
                    reason_code="ST_BUY_BLOCKED",
                    message="ST instrument position increase is blocked",
                )
            if reduce_only and current_weight <= ceiling.value:
                ceiling = _Bound(
                    value=current_weight,
                    rule_id="KILL_SWITCH",
                    reason_code="REDUCE_ONLY",
                    message="reduce-only kill switch blocked a position increase",
                )
            if state.suspended and current_weight <= ceiling.value:
                ceiling = _Bound(
                    value=current_weight,
                    rule_id="TRADABILITY",
                    reason_code="SUSPENDED",
                    message="suspended instrument cannot be rebalanced",
                )
            if floor.value > ceiling.value:
                return self._reject(
                    target,
                    context,
                    results,
                    rule_id="INSTRUMENT_BOUNDS",
                    reason_code="INFEASIBLE_INSTRUMENT_BOUNDS",
                    message=(
                        f"instrument {instrument} has floor {floor.value} above "
                        f"ceiling {ceiling.value}"
                    ),
                )
            floors[instrument] = floor.value
            if weights[instrument] < floor.value:
                self._set_weight(
                    weights,
                    reasons,
                    results,
                    instrument=instrument,
                    adjusted=floor.value,
                    threshold=floor.value,
                    bound=floor,
                )
            elif weights[instrument] > ceiling.value:
                self._set_weight(
                    weights,
                    reasons,
                    results,
                    instrument=instrument,
                    adjusted=ceiling.value,
                    threshold=ceiling.value,
                    bound=ceiling,
                )

        try:
            self._apply_industry_limits(weights, floors, reasons, results, market)
            effective_total_limit = min(
                self.policy.max_total_weight,
                _ONE - self.policy.minimum_cash_weight,
            )
            self._scale_with_floors(
                instruments=working_instruments,
                weights=weights,
                floors=floors,
                reasons=reasons,
                results=results,
                limit=effective_total_limit,
                rule_id="TOTAL_WEIGHT",
                reason_code="MAX_TOTAL_WEIGHT",
                message="portfolio target exceeds effective invested-weight limit",
            )
        except _InfeasiblePortfolio as exc:
            return self._reject(
                target,
                context,
                results,
                rule_id=exc.rule_id,
                reason_code=exc.reason_code,
                message=exc.message,
            )

        adjusted = any(weights[key] != original[key] for key in original)
        if not adjusted:
            results.append(
                self._result(
                    rule_id="PORTFOLIO_LIMITS",
                    outcome=RuleOutcome.PASS,
                    reason_code="PORTFOLIO_LIMITS_OK",
                    message="portfolio limits require no adjustment",
                )
            )
        positions = [
            ApprovedTarget(
                instrument=instrument,
                target_weight=_weight(weights[instrument]),
                adjusted=weights[instrument] != original[instrument],
                reason_code=reasons.get(instrument),
            )
            for instrument in working_instruments
        ]
        return RiskDecisionV2(
            run_id=target.run_id,
            strategy_id=target.strategy_id,
            policy_version=self.policy.policy_version,
            decision=(RiskDecisionType.ADJUST if adjusted else RiskDecisionType.APPROVE),
            approved=True,
            decided_at=context.evaluated_at,
            positions=positions,
            rule_results=results,
        )

    def _apply_industry_limits(
        self,
        weights: dict[str, Decimal],
        floors: dict[str, Decimal],
        reasons: dict[str, str],
        results: list[RiskRuleResult],
        market: dict[str, InstrumentRiskState],
    ) -> None:
        industries: dict[str, list[str]] = defaultdict(list)
        for instrument in sorted(weights):
            industries[market[instrument].industry].append(instrument)
        for industry in sorted(industries):
            self._scale_with_floors(
                instruments=industries[industry],
                weights=weights,
                floors=floors,
                reasons=reasons,
                results=results,
                limit=self.policy.max_industry_weight,
                rule_id="INDUSTRY_LIMIT",
                reason_code="MAX_INDUSTRY_WEIGHT",
                message=f"industry {industry} exceeds configured limit",
            )

    @staticmethod
    def _scale_with_floors(
        *,
        instruments: list[str],
        weights: dict[str, Decimal],
        floors: dict[str, Decimal],
        reasons: dict[str, str],
        results: list[RiskRuleResult],
        limit: Decimal,
        rule_id: str,
        reason_code: str,
        message: str,
    ) -> None:
        total = sum((weights[item] for item in instruments), _ZERO)
        if total <= limit:
            return
        floor_total = sum((floors[item] for item in instruments), _ZERO)
        if floor_total > limit:
            raise _InfeasiblePortfolio(
                rule_id=rule_id,
                reason_code=f"INFEASIBLE_{reason_code}",
                message=f"mandatory sell floors {floor_total} exceed limit {limit}",
            )
        flexible_total = total - floor_total
        if flexible_total <= _ZERO:
            raise _InfeasiblePortfolio(
                rule_id=rule_id,
                reason_code=f"INFEASIBLE_{reason_code}",
                message="portfolio cannot be reduced without violating sell floors",
            )
        factor = (limit - floor_total) / flexible_total
        bound = _Bound(
            value=limit,
            rule_id=rule_id,
            reason_code=reason_code,
            message=message,
        )
        for instrument in sorted(instruments):
            flexible = weights[instrument] - floors[instrument]
            adjusted = floors[instrument] + _weight(flexible * factor)
            DeterministicRiskEngine._set_weight(
                weights,
                reasons,
                results,
                instrument=instrument,
                adjusted=adjusted,
                threshold=limit,
                bound=bound,
            )

    @staticmethod
    def _set_weight(
        weights: dict[str, Decimal],
        reasons: dict[str, str],
        results: list[RiskRuleResult],
        *,
        instrument: str,
        adjusted: Decimal,
        threshold: Decimal,
        bound: _Bound,
    ) -> None:
        previous = weights[instrument]
        normalized = _weight(adjusted)
        if normalized == previous:
            return
        weights[instrument] = normalized
        reasons.setdefault(instrument, bound.reason_code)
        results.append(
            RiskRuleResult(
                rule_id=bound.rule_id,
                rule_version="1",
                outcome=RuleOutcome.ADJUST,
                reason_code=bound.reason_code,
                message=bound.message,
                instrument=instrument,
                original_value=str(previous),
                threshold=str(threshold),
                adjusted_value=str(normalized),
            )
        )

    def _reject(
        self,
        target: TargetPortfolio,
        context: RiskContext,
        results: list[RiskRuleResult],
        *,
        rule_id: str,
        reason_code: str,
        message: str,
    ) -> RiskDecisionV2:
        results.append(
            self._result(
                rule_id=rule_id,
                outcome=RuleOutcome.REJECT,
                reason_code=reason_code,
                message=message,
            )
        )
        return RiskDecisionV2(
            run_id=target.run_id,
            strategy_id=target.strategy_id,
            policy_version=self.policy.policy_version,
            decision=RiskDecisionType.REJECT,
            approved=False,
            decided_at=context.evaluated_at,
            positions=[],
            rule_results=results,
        )

    @staticmethod
    def _result(
        *,
        rule_id: str,
        outcome: RuleOutcome,
        reason_code: str,
        message: str,
    ) -> RiskRuleResult:
        return RiskRuleResult(
            rule_id=rule_id,
            rule_version="1",
            outcome=outcome,
            reason_code=reason_code,
            message=message,
        )
