from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from quant_agent.data.providers.base import CanonicalDataBundle, MarketDataProvider


class SampleDataProvider(MarketDataProvider):
    name = "sample"

    def fetch(self, trade_date: date) -> CanonicalDataBundle:
        trading_days = [
            trade_date - timedelta(days=offset)
            for offset in range(120, -1, -1)
            if (trade_date - timedelta(days=offset)).weekday() < 5
        ]
        symbols = {
            "600519.SH": 100.0,
            "000001.SZ": 10.0,
            "300750.SZ": 200.0,
        }
        daily_rows: list[dict[str, object]] = []
        factor_rows: list[dict[str, object]] = []
        status_rows: list[dict[str, object]] = []
        limit_rows: list[dict[str, object]] = []
        for symbol_index, (symbol, base_price) in enumerate(symbols.items()):
            previous_close = base_price
            for day_index, current_date in enumerate(trading_days):
                drift = 1 + (day_index * 0.003) + (symbol_index * 0.001)
                open_price = round(base_price * drift, 4)
                close_price = round(open_price * (1.002 + symbol_index * 0.001), 4)
                daily_rows.append(
                    {
                        "trade_date": current_date.isoformat(),
                        "symbol": symbol,
                        "open": open_price,
                        "high": round(max(open_price, close_price) * 1.01, 4),
                        "low": round(min(open_price, close_price) * 0.99, 4),
                        "close": close_price,
                        "volume": 1_000_000 + day_index * 10_000,
                        "amount": round(close_price * (1_000_000 + day_index * 10_000), 2),
                    }
                )
                factor_rows.append(
                    {
                        "trade_date": current_date.isoformat(),
                        "symbol": symbol,
                        "adjust_factor": 1.0,
                    }
                )
                status_rows.append(
                    {
                        "trade_date": current_date.isoformat(),
                        "symbol": symbol,
                        "suspended": False,
                        "status": "NORMAL",
                    }
                )
                limit_rows.append(
                    {
                        "trade_date": current_date.isoformat(),
                        "symbol": symbol,
                        "limit_up": round(previous_close * 1.1, 4),
                        "limit_down": round(previous_close * 0.9, 4),
                    }
                )
                previous_close = close_price

        calendar = pd.DataFrame(
            [{"trade_date": value.isoformat(), "is_open": True} for value in trading_days]
        )
        listing = pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "list_date": "2010-01-01",
                    "delist_date": None,
                    "name": f"Sample {symbol}",
                }
                for symbol in symbols
            ]
        )
        membership = pd.DataFrame(
            [
                {
                    "universe": "CSI300",
                    "symbol": symbol,
                    "effective_start": "2010-01-01",
                    "effective_end": None,
                }
                for symbol in symbols
            ]
        )
        return CanonicalDataBundle(
            provider=self.name,
            trade_date=trade_date,
            datasets={
                "daily_bar": pd.DataFrame(daily_rows),
                "adjust_factor": pd.DataFrame(factor_rows),
                "trading_calendar": calendar,
                "instrument_status": pd.DataFrame(status_rows),
                "limit_price": pd.DataFrame(limit_rows),
                "listing": listing,
                "universe_membership": membership,
            },
            metadata={"deterministic": True, "universe": "CSI300"},
        )
