from __future__ import annotations

import importlib
import os
import time as clock
from datetime import datetime, time, timedelta
from typing import Any

import pandas as pd

from quant_agent.data.providers.vendor_common import (
    china_market_date,
    finalize_daily_bars,
    iter_symbol_batches,
    normalize_symbols,
    validate_requested_symbols,
)


class ChoiceMarketDataProvider:
    """Eastmoney Choice daily bars through the official ``EmQuantAPI`` SDK."""

    provider_id = "eastmoney-choice"
    provider_version = "emquantapi-csd-v1"

    def __init__(
        self,
        *,
        symbols: tuple[str, ...] | list[str],
        lookback_days: int = 365,
        batch_size: int = 50,
        request_interval_seconds: float = 0.1,
        client: Any | None = None,
        login_options: str | None = None,
        csd_options: str | None = None,
    ) -> None:
        if lookback_days < 1:
            raise ValueError("lookback_days must be positive")
        self.symbols = normalize_symbols(symbols)
        self.lookback_days = lookback_days
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if request_interval_seconds < 0:
            raise ValueError("request_interval_seconds must not be negative")
        self.batch_size = batch_size
        self.request_interval_seconds = request_interval_seconds
        self._client = client
        self.login_options = login_options or os.getenv(
            "CHOICE_LOGIN_OPTIONS",
            "ForceLogin=0,RecordLoginInfo=0",
        )
        self.csd_options = csd_options or os.getenv(
            "CHOICE_CSD_OPTIONS",
            "RowIndex=1,period=1,adjustflag=1,curtype=1,order=1,Ispandas=0",
        )

    def fetch_daily_bars(self, *, as_of: datetime) -> pd.DataFrame:
        end_date = china_market_date(as_of)
        start_date = (end_date - timedelta(days=self.lookback_days)).isoformat()
        client = self._client or self._load_client()
        start = client.start(self.login_options)
        self._raise_api_error(start, action="login")
        try:
            frames: list[pd.DataFrame] = []
            for batch_index, batch in enumerate(
                iter_symbol_batches(self.symbols, batch_size=self.batch_size)
            ):
                if batch_index and self.request_interval_seconds:
                    clock.sleep(self.request_interval_seconds)
                response = client.csd(
                    ",".join(batch),
                    "OPEN,HIGH,LOW,CLOSE,VOLUME,AMOUNT",
                    start_date,
                    end_date.isoformat(),
                    self.csd_options,
                )
                self._raise_api_error(response, action="daily-bar query")
                frames.append(self._to_frame(response, expected_symbols=batch))
            frame = finalize_daily_bars(
                pd.concat(frames, ignore_index=True),
                available_time=time(15, 10),
            )
            validate_requested_symbols(frame, requested_symbols=self.symbols)
            return frame
        finally:
            client.stop()

    @staticmethod
    def _load_client() -> Any:
        try:
            module = importlib.import_module("EmQuantAPI")
        except ImportError as exc:
            raise RuntimeError(
                "Choice EmQuantAPI SDK is not installed; download and activate the official SDK"
            ) from exc
        client = getattr(module, "c", None)
        if client is None:
            raise RuntimeError("Choice EmQuantAPI module does not expose client 'c'")
        return client

    @staticmethod
    def _raise_api_error(response: Any, *, action: str) -> None:
        if isinstance(response, int):
            code = response
            message = ""
        else:
            code = int(getattr(response, "ErrorCode", 0))
            message = str(getattr(response, "ErrorMsg", ""))
        if code != 0:
            detail = f": {message}" if message else ""
            raise RuntimeError(f"Choice {action} failed with error {code}{detail}")

    def _to_frame(
        self,
        response: Any,
        *,
        expected_symbols: tuple[str, ...] | None = None,
    ) -> pd.DataFrame:
        symbols = expected_symbols or self.symbols
        if isinstance(response, pd.DataFrame):
            return self._normalize_dataframe(response, expected_symbols=symbols)
        data = getattr(response, "Data", None)
        if isinstance(data, pd.DataFrame):
            return self._normalize_dataframe(data, expected_symbols=symbols)

        codes = [str(value) for value in getattr(response, "Codes", [])]
        dates = [str(value) for value in getattr(response, "Dates", [])]
        indicators = [str(value).lower() for value in getattr(response, "Indicators", [])]
        if not codes or not dates or not indicators or not isinstance(data, dict):
            raise ValueError("Choice response does not contain a supported csd payload")

        rows: list[dict[str, object]] = []
        for code in codes:
            values = data.get(code)
            if not isinstance(values, (list, tuple)) or len(values) != len(indicators):
                raise ValueError(f"Choice response has malformed data for {code}")
            for date_index, trade_date in enumerate(dates):
                row: dict[str, object] = {"symbol": code, "trade_date": trade_date}
                for indicator_index, indicator in enumerate(indicators):
                    series = values[indicator_index]
                    if not isinstance(series, (list, tuple)) or date_index >= len(series):
                        raise ValueError(
                            f"Choice response has malformed {indicator} data for {code}"
                        )
                    row[indicator] = series[date_index]
                rows.append(row)
        return pd.DataFrame(rows)

    @staticmethod
    def _normalize_dataframe(
        frame: pd.DataFrame,
        *,
        expected_symbols: tuple[str, ...],
    ) -> pd.DataFrame:
        normalized = frame.reset_index()
        normalized.columns = [str(column).strip().lower() for column in normalized.columns]
        aliases = {
            "codes": "symbol",
            "code": "symbol",
            "secu_code": "symbol",
            "dates": "trade_date",
            "date": "trade_date",
            "amt": "amount",
        }
        normalized = normalized.rename(columns=aliases)
        if "symbol" not in normalized.columns:
            if len(expected_symbols) != 1:
                raise ValueError("Choice pandas response is missing a symbol column")
            normalized["symbol"] = expected_symbols[0]
        if "trade_date" not in normalized.columns:
            raise ValueError("Choice pandas response is missing a trade date column")
        return normalized
