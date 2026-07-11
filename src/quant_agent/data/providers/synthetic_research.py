from __future__ import annotations

import math
from datetime import datetime

import pandas as pd


class SyntheticResearchMarketDataProvider:
    """Deterministic multi-symbol daily bars for local research workflows."""

    provider_id = "synthetic-research-a-share"
    provider_version = "1.0"

    _SYMBOLS = (
        "600519.SH",
        "600036.SH",
        "000001.SZ",
        "000858.SZ",
        "300750.SZ",
        "300059.SZ",
    )

    def fetch_daily_bars(self, *, as_of: datetime) -> pd.DataFrame:
        del as_of  # SnapshotBuilder independently enforces point-in-time visibility.
        dates = pd.bdate_range("2024-01-02", "2026-05-22")
        rows: list[dict[str, object]] = []
        for symbol_index, symbol in enumerate(self._SYMBOLS):
            previous_close = 20.0 + symbol_index * 18.0
            for day_index, trade_date in enumerate(dates):
                trend = 0.00025 * (symbol_index + 1)
                cycle = 0.006 * math.sin((day_index + symbol_index * 7) / 13.0)
                shock = 0.0025 * math.cos((day_index * (symbol_index + 2)) / 31.0)
                overnight = 0.0015 * math.sin((day_index + symbol_index) / 9.0)
                open_price = max(1.0, previous_close * (1.0 + overnight))
                close_price = max(1.0, open_price * (1.0 + trend + cycle + shock))
                high_price = max(open_price, close_price) * 1.006
                low_price = min(open_price, close_price) * 0.994
                volume = 800_000 + symbol_index * 150_000 + (day_index % 23) * 12_000
                amount = volume * (open_price + close_price) / 2.0
                rows.append(
                    {
                        "trade_date": trade_date.strftime("%Y-%m-%d"),
                        "symbol": symbol,
                        "open": round(open_price, 4),
                        "high": round(high_price, 4),
                        "low": round(low_price, 4),
                        "close": round(close_price, 4),
                        "volume": volume,
                        "amount": round(amount, 4),
                        "available_at": (
                            trade_date.strftime("%Y-%m-%d") + "T15:05:00+08:00"
                        ),
                    }
                )
                previous_close = close_price
        return pd.DataFrame(rows)
