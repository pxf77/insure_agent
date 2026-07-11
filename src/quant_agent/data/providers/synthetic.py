from __future__ import annotations

from datetime import datetime

import pandas as pd


class SyntheticMarketDataProvider:
    """Deterministic A-share data provider for local and CI workflows."""

    provider_id = "synthetic-a-share"
    provider_version = "1.0"

    def fetch_daily_bars(self, *, as_of: datetime) -> pd.DataFrame:
        del as_of  # SnapshotBuilder applies the independent PIT cutoff.
        return pd.DataFrame(
            [
                {
                    "trade_date": "2026-05-20",
                    "symbol": "SH600519",
                    "open": 100.0,
                    "high": 110.0,
                    "low": 99.0,
                    "close": 105.0,
                    "volume": 1_000,
                    "amount": 105_000.0,
                    "available_at": "2026-05-20T15:05:00+08:00",
                },
                {
                    "trade_date": "2026-05-20",
                    "symbol": "000001.sz",
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.0,
                    "close": 10.5,
                    "volume": 2_000,
                    "amount": 21_000.0,
                    "available_at": "2026-05-20T15:05:00+08:00",
                },
                {
                    "trade_date": "2026-05-21",
                    "symbol": "300750",
                    "open": 200.0,
                    "high": 210.0,
                    "low": 198.0,
                    "close": 205.0,
                    "volume": 1_200,
                    "amount": 246_000.0,
                    "available_at": "2026-05-21T15:05:00+08:00",
                },
                {
                    "trade_date": "2026-05-22",
                    "symbol": "600036",
                    "open": 35.0,
                    "high": 36.0,
                    "low": 34.5,
                    "close": 35.5,
                    "volume": 3_000,
                    "amount": 106_500.0,
                    "available_at": "2026-05-22T15:05:00+08:00",
                },
            ]
        )
