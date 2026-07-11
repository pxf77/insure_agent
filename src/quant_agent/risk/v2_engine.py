from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from quant_agent.risk.kill_switch_store import KillSwitchStore
from quant_agent.risk.v2_models import RiskContext, RiskPolicy
from quant_agent.schemas.v2 import (
    ApprovedTarget,
    RiskDecisionType,
    RiskDecisionV2,
    RiskRuleResult,
    RuleOutcome,
    TargetPortfolio,
)


class DeterministicRiskEngine:
    """Ordered fail-closed risk evaluation for v2 target portfolios."""

    def __init__(self, *, policy: RiskPolicy, kill_switch_store: KillSwitchStore):
        self.policy = policy
        self.kill_switch_store = kill_switch_store

    def evaluate(self, target: TargetPortfolio, context: RiskContext) -> RiskDecisionV2:
        results: list[RiskRuleResult] = []
        original = {
            str(position.instrument): position.target_weight for position in target.positions
        }
        weights = dict(original)
        reasons: dict[str, str] = {}

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
        unknown = sorted(set(weights) - set(market))
        if unknown:
            return self._reject(
                target,
                context,
                results,
                rule_id="INPUT_CONTEXT",
                reason_code="MISSING_INSTRUMENT_CONTEXT",
                message=f"missing risk context for instruments: {unknown}",
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
        maximum_age = timedelta(minutes=self.policy.max_data_age_minutes)
        if freshness > maximum_age:
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
        hard_switches = [record for record in switches if not record.reduce_only]
        if hard_switches:
            switch_ids = [record.switch_id for record in hard_switches]
            return self._reject(
                target,
                context,
                results,
                rule_id="KILL_SWITCH",
                reason_code="KILL_SWITCH_ACTIVE",
                message=f"hard kill switch active: {switch_ids}",
            )

        reduce_only = bool(switches)
        if reduce_only:
            for instrument in sorted(weights):
                current_weight = current.get(instrument)
                maximum = current_weight.current_weight if current_weight else Decimal("0")
                if weights[instrument] > maximum:
                    weights[instrument] = maximum
                    reasons.setdefault(instrument, "REDUCE_ONLY")
                    results.append(
                        self._adjustment(
                            rule_id="KILL_SWITCH",
                            reason_code="REDUCE_ONLY",
                            message="reduce-only kill switch blocked a position increase",
                            instrument=instrument,
                            original_value=original[instrument],
                            threshold=maximum,
                            adjusted_value=maximum,
                        )
                    )
            if not any(result.rule_id == "KILL_SWITCH" for result in results):
                results.append(
                    self._result(
                        rule_id="KILL_SWITCH",
                        outcome=RuleOutcome.WARN,
                        reason_code="REDUCE_ONLY_ACTIVE",
                        message="reduce-only kill switch is active",
                    )
                )
        else:
            results.append(
                self._result(
                    rule_id="KILL_SWITCH",
                    outcome=RuleOutcome.PASS,
                    reason_code="NO_KILL_SWITCH",
                    message="no applicable kill switch is active",
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

        for instrument in sorted(weights):
            state = market[instrument]
            position = current.get(instrument)
            current_weight = position.current_weight if position else Decimal("0")
            target_weight = weights[instrument]

            if state.suspended and target_weight != current_weight:
                self._set_weight(
                    weights,
                    reasons,
                    results,
                    instrument=instrument,
                    adjusted=current_weight,
                    rule_id="TRADABILITY",
                    reason_code="SUSPENDED",
                    message="suspended instrument cannot be rebalanced",
                )
                target_weight = weights[instrument]
            if state.is_st and not self.policy.allow_st and target_weight > current_weight:
                self._set_weight(
                    weights,
                    reasons,
                    results,
                    instrument=instrument,
                    adjusted=current_weight,
                    rule_id="TRADABILITY",
                    reason_code="ST_BUY_BLOCKED",
                    message="ST instrument position increase is blocked",
                )
                target_weight = weights[instrument]
            if state.limit_up and target_weight > current_weight:
                self._set_weight(
                    weights,
                    reasons,
                    results,
                    instrument=instrument,
                    adjusted=current_weight,
                    rule_id="TRADABILITY",
                    reason_code="LIMIT_UP_BUY_BLOCKED",
                    message="limit-up instrument cannot be increased",
                )
                target_weight = weights[instrument]
            if state.limit_down and target_weight < current_weight:
                self._set_weight(
                    weights,
                    reasons,
                    results,
                    instrument=instrument,
                    adjusted=current_weight,
                    rule_id="TRADABILITY",
                    reason_code="LIMIT_DOWN_SELL_BLOCKED",
                    message="limit-down instrument cannot be reduced",
                )
                target_weight = weights[instrument]

            if position and target_weight < current_weight:
                minimum_weight = current_weight - position.sellable_weight
                if target_weight < minimum_weight:
                    self._set_weight(
                        weights,
                        reasons,
                        results,
                        instrument=instrument,
                        adjusted=minimum_weight,
                        rule_id="T_PLUS_ONE",
                        reason_code="T_PLUS_ONE_SELL_LIMIT",
                        message="target reduction exceeds sellable position weight",
                    )
                    target_weight = weights[instrument]

            if target_weight > state.max_liquidity_weight:
                self._set_weight(
                    weights,
                    reasons,
                    results,
                    instrument=instrument,
                    adjusted=state.max_liquidity_weight,
                    rule_id="LIQUIDITY",
                    reason_code="LIQUIDITY_CAP",
                    message="target weight exceeds liquidity capacity",
                )
                target_weight = weights[instrument]

            if target_weight > self.policy.max_single_weight:
                self._set_weight(
                    weights,
                    reasons,
                    results,
                    instrument=instrument,
                    adjusted=self.policy.max_single_weight,
                    rule_id="SINGLE_POSITION",
                    reason_code="MAX_SINGLE_WEIGHT",
                    message="target weight exceeds single-position limit",
                )

        self._apply_industry_limit(weights, reasons, results, market)
        effective_total_limit = min(
            self.policy.max_total_weight,
            Decimal("1") - self.policy.minimum_cash_weight,
        )
        self._scale_total(
            weights,
            reasons,
            results,
            limit=effective_total_limit,
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
                target_weight=weights[instrument],
                adjusted=weights[instrument] != original[instrument],
                reason_code=reasons.get(instrument),
            )
            for instrument in sorted(weights)
        ]
        decision = RiskDecisionType.ADJUST if adjusted else RiskDecisionType.APPROVE
        return RiskDecisionV2(
            run_id=target.run_id,
            strategy_id=target.strategy_id,
            policy_version=self.policy.policy_version,
            decision=decision,
            approved=True,
            decided_at=context.evaluated_at,
            positions=positions,
            rule_results=results,
        )

    def _apply_industry_limit(
        self,
        weights: dict[str, Decimal],
        reasons: dict[str, str],
        results: list[RiskRuleResult],
        market: dict[str, object],
    ) -> None:
        industries: dict[str, list[str]] = defaultdict(list)
        for instrument in sorted(weights):
            state = market[instrument]
            industry = getattr(state, "industry")
            industries[str(industry)].append(instrument)
        for industry in sorted(industries):
            instruments = industries[industry]
            total = sum((weights[item] for item in instruments), Decimal("0"))
            if total <= self.policy.max_industry_weight or total == 0:
                continue
            factor = self.policy.max_industry_weight / total
            for instrument in instruments:
                adjusted = weights[instrument] * factor
                self._set_weight(
                    weights,
                    reasons,
                    results,
                    instrument=instrument,
                    adjusted=adjusted,
                    rule_id="INDUSTRY_LIMIT",
                    reason_code="MAX_INDUSTRY_WEIGHT",
                    message=f"industry {industry} exceeds configured limit",
                )

    def _scale_total(
        self,
        weights: dict[str, Decimal],
        reasons: dict[str, str],
        results: list[RiskRuleResult],
        *,
        limit: Decimal,
    ) -> None:
        total = sum(weights.values(), Decimal("0"))
        if total <= limit or total == 0:
            return
        factor = limit / total
        for instrument in sorted(weights):
            self._set_weight(
                weights,
                reasons,
                results,
                instrument=instrument,
                adjusted=weights[instrument] * factor,
                rule_id="TOTAL_WEIGHT",
                reason_code="MAX_TOTAL_WEIGHT",
                message="portfolio target exceeds effective invested-weight limit",
            )

    @staticmethod
    def _set_weight(
        weights: dict[str, Decimal],
        reasons: dict[str, str],
        results: list[RiskRuleResult],
        *,
        instrument: str,
        adjusted: Decimal,
        rule_id: str,
        reason_code: str,
        message: str,
    ) -> None:
        original = weights[instrument]
        if adjusted == original:
            return
        weights[instrument] = adjusted
        reasons.setdefault(instrument, reason_code)
        results.append(
            DeterministicRiskEngine._adjustment(
                rule_id=rule_id,
                reason_code=reason_code,
                message=message,
                instrument=instrument,
                original_value=original,
                threshold=adjusted,
                adjusted_value=adjusted,
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
    def _adjustment(
        *,
        rule_id: str,
        reason_code: str,
        message: str,
        instrument: str,
        original_value: Decimal,
        threshold: Decimal,
        adjusted_value: Decimal,
    ) -> RiskRuleResult:
        return RiskRuleResult(
            rule_id=rule_id,
            rule_version="1",
            outcome=RuleOutcome.ADJUST,
            reason_code=reason_code,
            message=message,
            instrument=instrument,
            original_value=str(original_value),
            threshold=str(threshold),
            adjusted_value=str(adjusted_value),
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
