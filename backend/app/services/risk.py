from backend.app.schemas import (
    AccountState,
    MarketState,
    RiskCheckResult,
    RiskConfig,
    SignalCandidate,
)


class RiskEngine:
    def __init__(self, config: RiskConfig | None = None) -> None:
        self.config = config or RiskConfig()

    def evaluate(
        self,
        candidate: SignalCandidate,
        account: AccountState,
        market: MarketState,
    ) -> RiskCheckResult:
        config = self.config

        if candidate.score < config.min_signal_score:
            return self._blocked("score below minimum")
        if candidate.stop_loss is None:
            return self._blocked("missing stop loss")
        if candidate.max_position_pct > config.max_single_position_pct:
            return self._blocked("single position too large")
        if account.total_position_pct >= config.max_total_position_pct:
            return self._blocked("total position limit reached")
        if account.daily_loss_pct <= -config.max_daily_loss_pct:
            return self._blocked("daily loss limit reached")
        if config.block_st and market.is_st:
            return self._blocked("st or risk-warning stock blocked")
        if market.turnover_cny < config.min_turnover_cny:
            return self._blocked("turnover below minimum")
        if candidate.price_range is None:
            return self._blocked("missing price range")
        if candidate.take_profit is None:
            return self._blocked("missing take profit")

        entry_price = sum(candidate.price_range) / 2
        if candidate.action == "buy":
            if candidate.stop_loss >= entry_price:
                return self._blocked("invalid stop loss")
            if config.block_limit_up_buy and market.is_limit_up:
                return self._blocked("limit-up buy blocked")
            risk = entry_price - candidate.stop_loss
            reward = candidate.take_profit - entry_price
        else:
            risk = abs(entry_price - candidate.stop_loss)
            reward = abs(candidate.take_profit - entry_price)

        if risk <= 0:
            return self._blocked("invalid stop loss")
        if reward / risk < config.min_reward_risk_ratio:
            return self._blocked("reward/risk ratio below minimum")

        return RiskCheckResult(passed=True)

    @staticmethod
    def _blocked(reason: str) -> RiskCheckResult:
        return RiskCheckResult(passed=False, blocked_reason=reason)
