import pandas as pd
import pytest

from quant_agent.data.validators import validate_daily_bar


def make_daily_bar_frame(**overrides):
    row = {
        "trade_date": "2026-05-22",
        "symbol": "600519.SH",
        "open": 100.0,
        "high": 110.0,
        "low": 99.0,
        "close": 105.0,
        "volume": 1000,
        "amount": 105000.0,
    }
    row.update(overrides)
    return pd.DataFrame([row])


def test_validate_daily_bar_accepts_valid_frame():
    validate_daily_bar(make_daily_bar_frame())


def test_validate_daily_bar_rejects_missing_columns():
    frame = make_daily_bar_frame().drop(columns=["amount"])

    with pytest.raises(ValueError, match="missing columns"):
        validate_daily_bar(frame)


def test_validate_daily_bar_rejects_duplicate_symbol_date_rows():
    frame = pd.concat([make_daily_bar_frame(), make_daily_bar_frame()], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate daily bars"):
        validate_daily_bar(frame)


def test_validate_daily_bar_rejects_bad_price_relationships():
    frame = make_daily_bar_frame(high=90.0, low=99.0)

    with pytest.raises(ValueError, match="invalid price rows"):
        validate_daily_bar(frame)


def test_validate_daily_bar_rejects_non_positive_close():
    frame = make_daily_bar_frame(close=0.0)

    with pytest.raises(ValueError, match="invalid price rows"):
        validate_daily_bar(frame)
