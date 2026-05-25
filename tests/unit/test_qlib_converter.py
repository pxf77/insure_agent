import json

import pandas as pd

from quant_agent.data.qlib_converter import QlibConverter


def test_qlib_converter_writes_features_instruments_and_metadata(tmp_path):
    raw_dir = tmp_path / "raw"
    qlib_dir = tmp_path / "qlib"
    raw_dir.mkdir()
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
                "trade_date": "2026-05-20",
                "symbol": "000001.SZ",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10.5,
                "volume": 2000,
                "amount": 21000,
            },
        ]
    ).to_csv(raw_dir / "daily_bar.csv", index=False)

    result = QlibConverter(raw_dir=raw_dir, qlib_dir=qlib_dir).convert()

    assert result.instrument_path == qlib_dir / "instruments" / "all_a.txt"
    assert result.metadata_path == qlib_dir / "metadata.json"
    assert (qlib_dir / "features" / "600519.SH.csv").is_file()
    assert (qlib_dir / "features" / "000001.SZ.csv").is_file()
    assert result.instrument_path.read_text().splitlines() == ["000001.SZ", "600519.SH"]
    assert json.loads(result.metadata_path.read_text())["rows"] == 2
