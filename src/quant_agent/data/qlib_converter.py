from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from quant_agent.data.adapters.local_csv_adapter import LocalCsvAdapter
from quant_agent.data.symbol import normalize_symbol
from quant_agent.data.validators import validate_daily_bar


@dataclass(frozen=True)
class QlibConversionResult:
    qlib_dir: Path
    feature_dir: Path
    instrument_path: Path
    metadata_path: Path
    rows: int
    symbols: list[str]


class QlibConverter:
    """Create a lightweight Qlib-compatible local data layout for Phase 1."""

    def __init__(self, raw_dir: str | Path, qlib_dir: str | Path):
        self.raw_dir = Path(raw_dir)
        self.qlib_dir = Path(qlib_dir)

    def convert(self) -> QlibConversionResult:
        frame = LocalCsvAdapter(self.raw_dir)._read_table("daily_bar")
        frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.strftime("%Y-%m-%d")
        frame["symbol"] = frame["symbol"].map(normalize_symbol)
        validate_daily_bar(frame)

        feature_dir = self.qlib_dir / "features"
        instrument_dir = self.qlib_dir / "instruments"
        feature_dir.mkdir(parents=True, exist_ok=True)
        instrument_dir.mkdir(parents=True, exist_ok=True)

        symbols = sorted(frame["symbol"].unique().tolist())
        for symbol in symbols:
            symbol_frame = frame[frame["symbol"] == symbol].sort_values("trade_date")
            symbol_frame.to_csv(feature_dir / f"{symbol}.csv", index=False)

        instrument_path = instrument_dir / "all_a.txt"
        instrument_path.write_text("\n".join(symbols) + "\n", encoding="utf-8")

        metadata_path = self.qlib_dir / "metadata.json"
        metadata = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "rows": int(len(frame)),
            "symbols": symbols,
            "source": str(self.raw_dir),
        }
        metadata_text = json.dumps(metadata, indent=2, ensure_ascii=False)
        metadata_path.write_text(metadata_text, encoding="utf-8")

        return QlibConversionResult(
            qlib_dir=self.qlib_dir,
            feature_dir=feature_dir,
            instrument_path=instrument_path,
            metadata_path=metadata_path,
            rows=int(len(frame)),
            symbols=symbols,
        )
