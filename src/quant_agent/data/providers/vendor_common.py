from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

from quant_agent.data.symbol import normalize_symbol

DAILY_BAR_FIELDS = (
    "trade_date",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "available_at",
)
_SOURCE_FIELDS = DAILY_BAR_FIELDS[:-1]
_CHINA_TIMEZONE = ZoneInfo("Asia/Shanghai")


def normalize_symbols(values: Iterable[str]) -> tuple[str, ...]:
    symbols = tuple(
        dict.fromkeys(normalize_symbol(value.strip()) for value in values if value.strip())
    )
    if not symbols:
        raise ValueError("at least one normalized A-share symbol is required")
    return symbols


def iter_symbol_batches(
    symbols: tuple[str, ...],
    *,
    batch_size: int,
) -> Iterator[tuple[str, ...]]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    for offset in range(0, len(symbols), batch_size):
        yield symbols[offset : offset + batch_size]


def china_market_date(value: datetime) -> date:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must include timezone information")
    return value.astimezone(_CHINA_TIMEZONE).date()


def validate_requested_symbols(
    frame: pd.DataFrame,
    *,
    requested_symbols: tuple[str, ...],
) -> None:
    actual = set(frame["symbol"].astype(str))
    expected = set(requested_symbols)
    if actual == expected:
        return
    missing = ",".join(sorted(expected - actual)) or "none"
    unexpected = ",".join(sorted(actual - expected)) or "none"
    raise ValueError(
        f"vendor response symbol mismatch: missing={missing}; unexpected={unexpected}"
    )


def finalize_daily_bars(
    frame: pd.DataFrame,
    *,
    available_time: time,
) -> pd.DataFrame:
    missing = [field for field in _SOURCE_FIELDS if field not in frame.columns]
    if missing:
        raise ValueError(f"vendor daily bars are missing columns: {', '.join(missing)}")

    result = frame.loc[:, list(_SOURCE_FIELDS)].copy()
    trade_dates = pd.to_datetime(result["trade_date"], errors="raise")
    result["trade_date"] = trade_dates.dt.strftime("%Y-%m-%d")
    result["symbol"] = result["symbol"].map(lambda value: normalize_symbol(str(value)))
    for column in ("open", "high", "low", "close", "volume", "amount"):
        result[column] = pd.to_numeric(result[column], errors="raise")

    result["available_at"] = [
        timestamp.to_pydatetime()
        .replace(
            hour=available_time.hour,
            minute=available_time.minute,
            second=available_time.second,
            microsecond=0,
            tzinfo=_CHINA_TIMEZONE,
        )
        .isoformat()
        for timestamp in trade_dates
    ]
    return result.loc[:, list(DAILY_BAR_FIELDS)].reset_index(drop=True)
