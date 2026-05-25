from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from quant_agent.data.adapters.base import DataAdapter
from quant_agent.data.symbol import normalize_symbol
from quant_agent.data.validators import validate_daily_bar


class LocalCsvAdapter(DataAdapter):
    """Load local CSV or Parquet files from a raw data directory."""

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)

    def fetch_daily_bar(
        self,
        start: date,
        end: date,
        symbols: list[str] | None = None,
    ) -> pd.DataFrame:
        frame = self._read_table("daily_bar")
        frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
        frame["symbol"] = frame["symbol"].map(normalize_symbol)
        normalized_symbols = {normalize_symbol(symbol) for symbol in symbols or []}

        filtered = frame[(frame["trade_date"] >= start) & (frame["trade_date"] <= end)]
        if normalized_symbols:
            filtered = filtered[filtered["symbol"].isin(normalized_symbols)]

        result = filtered.reset_index(drop=True)
        validate_daily_bar(result)
        return result

    def fetch_adjust_factor(
        self,
        start: date,
        end: date,
        symbols: list[str] | None = None,
    ) -> pd.DataFrame:
        return self._filter_optional_table("adjust_factor", start, end, symbols)

    def fetch_instrument_status(self, start: date, end: date) -> pd.DataFrame:
        return self._filter_optional_table("instrument_status", start, end, None)

    def fetch_limit_price(
        self,
        start: date,
        end: date,
        symbols: list[str] | None = None,
    ) -> pd.DataFrame:
        return self._filter_optional_table("limit_price", start, end, symbols)

    def _filter_optional_table(
        self,
        name: str,
        start: date,
        end: date,
        symbols: list[str] | None,
    ) -> pd.DataFrame:
        frame = self._read_table(name)
        if "trade_date" in frame.columns:
            frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
            frame = frame[(frame["trade_date"] >= start) & (frame["trade_date"] <= end)]
        if symbols and "symbol" in frame.columns:
            normalized_symbols = {normalize_symbol(symbol) for symbol in symbols}
            frame["symbol"] = frame["symbol"].map(normalize_symbol)
            frame = frame[frame["symbol"].isin(normalized_symbols)]
        return frame.reset_index(drop=True)

    def _read_table(self, name: str) -> pd.DataFrame:
        csv_path = self.base_dir / f"{name}.csv"
        parquet_path = self.base_dir / f"{name}.parquet"
        if csv_path.exists():
            return pd.read_csv(csv_path)
        if parquet_path.exists():
            return pd.read_parquet(parquet_path)
        raise FileNotFoundError(f"{name} data file not found in {self.base_dir}")
