from datetime import date

import pandas as pd
import pytest

from quant_agent.data.adapters.local_csv_adapter import LocalCsvAdapter


def write_daily_bar_csv(base_dir):
    base_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "trade_date": "2026-05-20",
                "symbol": "600519.SH",
                "open": 100,
                "high": 110,
                "low": 99,
                "close": 105,
                "volume": 1000,
                "amount": 105000,
            },
            {
                "trade_date": "2026-05-21",
                "symbol": "000001.SZ",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10.5,
                "volume": 2000,
                "amount": 21000,
            },
        ]
    ).to_csv(base_dir / "daily_bar.csv", index=False)


def test_fetch_daily_bar_filters_by_date_range(tmp_path):
    write_daily_bar_csv(tmp_path)
    adapter = LocalCsvAdapter(tmp_path)

    frame = adapter.fetch_daily_bar(start=date(2026, 5, 21), end=date(2026, 5, 21))

    assert frame["symbol"].tolist() == ["000001.SZ"]


def test_fetch_daily_bar_filters_by_symbols(tmp_path):
    write_daily_bar_csv(tmp_path)
    adapter = LocalCsvAdapter(tmp_path)

    frame = adapter.fetch_daily_bar(
        start=date(2026, 5, 20),
        end=date(2026, 5, 21),
        symbols=["600519.SH"],
    )

    assert frame["symbol"].tolist() == ["600519.SH"]


def test_fetch_daily_bar_raises_for_missing_file(tmp_path):
    adapter = LocalCsvAdapter(tmp_path)

    with pytest.raises(FileNotFoundError, match="daily_bar"):
        adapter.fetch_daily_bar(start=date(2026, 5, 20), end=date(2026, 5, 21))
