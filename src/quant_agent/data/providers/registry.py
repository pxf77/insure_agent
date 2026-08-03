from __future__ import annotations

from quant_agent.data.providers.base import MarketDataProvider
from quant_agent.data.providers.choice import ChoiceMarketDataProvider
from quant_agent.data.providers.ifind import IFindMarketDataProvider
from quant_agent.data.providers.synthetic import SyntheticMarketDataProvider
from quant_agent.data.providers.synthetic_research import SyntheticResearchMarketDataProvider

AVAILABLE_PROVIDERS = ("synthetic", "synthetic-research", "choice", "ifind")


def create_market_data_provider(
    name: str,
    *,
    symbols: tuple[str, ...] = (),
    lookback_days: int = 365,
    batch_size: int = 50,
) -> MarketDataProvider:
    if name == "synthetic":
        return SyntheticMarketDataProvider()
    if name == "synthetic-research":
        return SyntheticResearchMarketDataProvider()
    if name == "choice":
        return ChoiceMarketDataProvider(
            symbols=symbols,
            lookback_days=lookback_days,
            batch_size=batch_size,
        )
    if name == "ifind":
        return IFindMarketDataProvider(
            symbols=symbols,
            lookback_days=lookback_days,
            batch_size=batch_size,
        )
    allowed = ", ".join(AVAILABLE_PROVIDERS)
    raise ValueError(f"provider must be one of: {allowed}")
