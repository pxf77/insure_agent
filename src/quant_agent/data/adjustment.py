from __future__ import annotations

import pandas as pd


def apply_forward_adjustment(
    daily_bar: pd.DataFrame,
    adjust_factor: pd.DataFrame,
) -> pd.DataFrame:
    """Return cutoff-adjusted OHLC data using the latest factor per instrument."""
    if daily_bar.empty:
        raise ValueError("cannot adjust an empty daily-bar dataset")
    if adjust_factor.empty:
        raise ValueError("adjustment factors are required")
    keys = ["trade_date", "symbol"]
    factors = adjust_factor[keys + ["adjust_factor"]].copy()
    factors["adjust_factor"] = pd.to_numeric(
        factors["adjust_factor"],
        errors="raise",
    )
    if (factors["adjust_factor"] <= 0).any():
        raise ValueError("adjustment factors must be positive")
    merged = daily_bar.merge(
        factors,
        on=keys,
        how="left",
        validate="one_to_one",
    )
    if merged["adjust_factor"].isna().any():
        missing = int(merged["adjust_factor"].isna().sum())
        raise ValueError(f"adjustment-factor coverage is incomplete: {missing} rows")
    merged = merged.sort_values(["symbol", "trade_date"], kind="stable")
    latest_factor = merged.groupby("symbol")["adjust_factor"].transform("last")
    merged["factor"] = merged["adjust_factor"] / latest_factor
    for field in ("open", "high", "low", "close"):
        merged[field] = pd.to_numeric(merged[field], errors="raise") * merged["factor"]
    if "volume" in merged:
        merged["volume"] = (
            pd.to_numeric(merged["volume"], errors="raise") / merged["factor"]
        )
    return merged.drop(columns=["adjust_factor"]).reset_index(drop=True)
