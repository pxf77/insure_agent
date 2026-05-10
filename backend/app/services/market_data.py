from backend.app.schemas import MarketState


class MockMarketDataProvider:
    def get_market_state(self, symbol: str) -> MarketState:
        normalized = symbol.strip().upper()
        return MarketState(
            symbol=normalized,
            last_price=10.2,
            turnover_cny=50_000_000 if normalized.startswith("LOWTURN") else 150_000_000,
            is_st=normalized.startswith("ST"),
            is_limit_up=normalized.startswith("LIMITUP"),
        )
