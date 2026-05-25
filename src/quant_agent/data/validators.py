from __future__ import annotations

import pandas as pd

DAILY_BAR_REQUIRED_COLUMNS = {
    "trade_date",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
}


def validate_daily_bar(frame: pd.DataFrame) -> None:
    missing = DAILY_BAR_REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")

    if frame.duplicated(["trade_date", "symbol"]).any():
        raise ValueError("duplicate daily bars detected")

    bad_price = frame[
        (frame["high"] < frame["low"])
        | (frame["open"] <= 0)
        | (frame["high"] <= 0)
        | (frame["low"] <= 0)
        | (frame["close"] <= 0)
    ]
    if not bad_price.empty:
        raise ValueError("invalid price rows detected")

    bad_volume = frame[(frame["volume"] < 0) | (frame["amount"] < 0)]
    if not bad_volume.empty:
        raise ValueError("invalid volume or amount rows detected")
