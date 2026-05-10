from backend.app.schemas import MarketState, SignalCandidate


class MockLLMAnalyzer:
    def analyze(self, symbol: str, market: MarketState) -> SignalCandidate:
        normalized = symbol.strip().upper()
        score = 60 if normalized.startswith("LOW") else 82
        return SignalCandidate(
            symbol=normalized,
            action="buy",
            score=score,
            confidence=0.78,
            risk_level="medium",
            price_range=(10.0, 10.5),
            stop_loss=9.2,
            take_profit=12.4,
            max_position_pct=3.0,
            reasons=[f"mock trend confirmation at {market.last_price:.2f}"],
            risks=["mock market volatility"],
            manual_checklist=[
                "confirm signal manually",
                "confirm account and position limits manually",
            ],
        )
