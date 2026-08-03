from __future__ import annotations

import json
import os
import time as clock
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
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

_HISTORY_URL = "https://quantapi.51ifind.com/api/v1/cmd_history_quotation"
_OFFICIAL_HOST = "quantapi.51ifind.com"
_MAX_RESPONSE_BYTES = 20 * 1024 * 1024
HttpTransport = Callable[[str, dict[str, object], dict[str, str], float], Mapping[str, Any]]


def _post_json(
    url: str,
    payload: dict[str, object],
    headers: dict[str, str],
    timeout_seconds: float,
) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        content = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(content) > _MAX_RESPONSE_BYTES:
        raise ValueError("iFinD HTTP response exceeds the 20 MiB safety limit")
    decoded = json.loads(content.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("iFinD HTTP response must be a JSON object")
    return decoded


class IFindMarketDataProvider:
    """Tonghuashun iFinD daily bars through the official HTTP API."""

    provider_id = "tonghuashun-ifind"
    provider_version = "http-history-quotation-v1"

    def __init__(
        self,
        *,
        symbols: tuple[str, ...] | list[str],
        lookback_days: int = 365,
        batch_size: int = 50,
        access_token: str | None = None,
        access_token_env: str = "IFIND_ACCESS_TOKEN",
        endpoint: str = _HISTORY_URL,
        transport: HttpTransport | None = None,
        timeout_seconds: float = 30.0,
        max_attempts: int = 3,
        request_interval_seconds: float = 0.11,
    ) -> None:
        if lookback_days < 1:
            raise ValueError("lookback_days must be positive")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if request_interval_seconds < 0:
            raise ValueError("request_interval_seconds must not be negative")
        parsed_endpoint = urllib.parse.urlparse(endpoint)
        if parsed_endpoint.scheme != "https" or parsed_endpoint.hostname != _OFFICIAL_HOST:
            raise ValueError("iFinD endpoint must use the official HTTPS API host")
        self.symbols = normalize_symbols(symbols)
        self.lookback_days = lookback_days
        self.batch_size = batch_size
        self._access_token = access_token
        self.access_token_env = access_token_env
        self.endpoint = endpoint
        self.transport = transport or _post_json
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.request_interval_seconds = request_interval_seconds

    def fetch_daily_bars(self, *, as_of: datetime) -> pd.DataFrame:
        end_date = china_market_date(as_of)
        start_date = (end_date - timedelta(days=self.lookback_days)).isoformat()
        token = self._access_token or os.getenv(self.access_token_env)
        if not token:
            raise RuntimeError(
                f"iFinD access token is missing; set environment variable {self.access_token_env}"
            )
        headers = {"Content-Type": "application/json", "access_token": token}
        frames: list[pd.DataFrame] = []
        for batch_index, batch in enumerate(
            iter_symbol_batches(self.symbols, batch_size=self.batch_size)
        ):
            if batch_index and self.request_interval_seconds:
                clock.sleep(self.request_interval_seconds)
            payload: dict[str, object] = {
                "codes": ",".join(batch),
                "indicators": "open,high,low,close,volume,amount",
                "startdate": start_date,
                "enddate": end_date.isoformat(),
                "functionpara": {"Fill": "Blank"},
            }
            response = self._request_with_retry(payload, headers)
            self._raise_api_error(response)
            frames.append(self._to_frame(response))
        frame = finalize_daily_bars(
            pd.concat(frames, ignore_index=True),
            available_time=time(15, 7),
        )
        validate_requested_symbols(frame, requested_symbols=self.symbols)
        return frame

    def _request_with_retry(
        self,
        payload: dict[str, object],
        headers: dict[str, str],
    ) -> Mapping[str, Any]:
        for attempt in range(1, self.max_attempts + 1):
            try:
                return self.transport(self.endpoint, payload, headers, self.timeout_seconds)
            except urllib.error.HTTPError as exc:
                retryable = exc.code in {408, 429} or 500 <= exc.code < 600
                if not retryable:
                    raise RuntimeError(f"iFinD request failed with HTTP {exc.code}") from exc
                if attempt == self.max_attempts:
                    raise RuntimeError("iFinD request failed after retry budget") from exc
                clock.sleep(0.1 * attempt)
            except (TimeoutError, urllib.error.URLError) as exc:
                if attempt == self.max_attempts:
                    raise RuntimeError("iFinD request failed after retry budget") from exc
                clock.sleep(0.1 * attempt)
        raise AssertionError("unreachable")

    @staticmethod
    def _raise_api_error(response: Mapping[str, Any]) -> None:
        raw_code = response.get("errorcode", response.get("errorCode", 0))
        code = int(raw_code) if raw_code is not None else 0
        if code == 0:
            return
        message = response.get("errmsg", response.get("errorMsg", ""))
        detail = f": {message}" if message else ""
        raise RuntimeError(f"iFinD history quotation failed with error {code}{detail}")

    @staticmethod
    def _to_frame(response: Mapping[str, Any]) -> pd.DataFrame:
        raw_tables = response.get("tables")
        if isinstance(raw_tables, Mapping):
            tables: Sequence[object] = [raw_tables]
        elif isinstance(raw_tables, Sequence) and not isinstance(raw_tables, (str, bytes)):
            tables = raw_tables
        else:
            raise ValueError("iFinD response is missing tables")

        rows: list[dict[str, object]] = []
        for raw_table in tables:
            if not isinstance(raw_table, Mapping):
                raise ValueError("iFinD table must be a JSON object")
            symbol = raw_table.get("thscode", raw_table.get("code"))
            payload = raw_table.get("table", raw_table)
            if not symbol or not isinstance(payload, Mapping):
                raise ValueError("iFinD table is missing thscode or table data")
            dates = raw_table.get("time", payload.get("time", payload.get("date")))
            if not isinstance(dates, Sequence) or isinstance(dates, (str, bytes)):
                raise ValueError(f"iFinD table for {symbol} is missing time values")
            for index, trade_date in enumerate(dates):
                row: dict[str, object] = {"symbol": symbol, "trade_date": trade_date}
                for field in ("open", "high", "low", "close", "volume", "amount"):
                    values = payload.get(field)
                    if field == "amount" and values is None:
                        values = payload.get("amt")
                    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
                        raise ValueError(f"iFinD table for {symbol} is missing {field}")
                    if index >= len(values):
                        raise ValueError(f"iFinD table for {symbol} has truncated {field} data")
                    row[field] = values[index]
                rows.append(row)
        return pd.DataFrame(rows)
