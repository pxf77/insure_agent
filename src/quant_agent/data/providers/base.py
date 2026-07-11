from __future__ import annotations

from datetime import datetime
from typing import Protocol

import pandas as pd


class MarketDataProvider(Protocol):
    """Provider contract for point-in-time market data ingestion."""

    @property
    def provider_id(self) -> str: ...

    @property
    def provider_version(self) -> str: ...

    def fetch_daily_bars(self, *, as_of: datetime) -> pd.DataFrame:
        """Return all source rows visible to the provider request.

        Rows must include an aware ``available_at`` timestamp. The snapshot layer
        independently applies the point-in-time cutoff and must not trust the
        provider to filter correctly.
        """
        ...
