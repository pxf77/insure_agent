import json
from pathlib import Path

import pandas as pd

from quant_agent.research.qlib_runner import QlibRunner


def write_raw_daily_bar(raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "trade_date": "2026-05-20",
                "symbol": "600519.SH",
                "open": 100.0,
                "high": 110.0,
                "low": 99.0,
                "close": 105.0,
                "volume": 1000,
                "amount": 105000.0,
            },
            {
                "trade_date": "2026-05-20",
                "symbol": "000001.SZ",
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "volume": 2000,
                "amount": 21000.0,
            },
            {
                "trade_date": "2026-05-21",
                "symbol": "300750.SZ",
                "open": 200.0,
                "high": 210.0,
                "low": 198.0,
                "close": 205.0,
                "volume": 1200,
                "amount": 246000.0,
            },
        ]
    ).to_csv(raw_dir / "daily_bar.csv", index=False)


def test_qlib_runner_creates_research_run_outputs(tmp_path):
    write_raw_daily_bar(tmp_path / "artifacts" / "data" / "raw")
    runner = QlibRunner(
        config_path=Path("configs/research/baseline_lgb_alpha158.yaml"),
        artifact_root=tmp_path / "artifacts",
        raw_data_dir=tmp_path / "artifacts" / "data" / "raw",
    )

    result = runner.run_backtest()

    assert result.target_positions_path.is_file()
    assert result.metrics_path.is_file()
    assert result.report_path.is_file()
    payload = json.loads(result.target_positions_path.read_text())
    assert payload["schema_version"] == "1.0"
    assert payload["strategy_id"] == "lgb_alpha158_csi300_v1"
    assert payload["positions"][0]["target_weight"] > 0.2
    assert len(payload["positions"]) == 3
