from __future__ import annotations

import json
import os
import shutil
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from quant_agent.common.io import atomic_write_json, file_sha256
from quant_agent.data.adjustment import apply_forward_adjustment
from quant_agent.data.snapshots import DataSnapshotStore
from quant_agent.schemas.data import DataManifest


@dataclass(frozen=True)
class QlibBinaryResult:
    qlib_dir: Path
    calendar_path: Path
    instruments_path: Path
    metadata_path: Path
    symbols: list[str]
    rows: int


class QlibBinaryConverter:
    """Convert a valid canonical snapshot into Qlib's local binary layout."""

    FIELDS = ("open", "high", "low", "close", "volume", "amount", "factor")

    def __init__(self, artifact_root: str | Path):
        self.artifact_root = Path(artifact_root)

    def convert(self, manifest: DataManifest) -> QlibBinaryResult:
        if not manifest.valid:
            raise ValueError("cannot convert an invalid data snapshot")
        target = self.artifact_root / "data" / "qlib" / manifest.data_version
        metadata_path = target / "metadata.json"
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata.get("data_version") != manifest.data_version:
                raise ValueError(f"Qlib directory has inconsistent metadata: {target}")
            checksums = metadata.get("file_checksums")
            if not isinstance(checksums, dict) or not checksums:
                raise ValueError(f"Qlib directory has no file checksums: {target}")
            resolved_target = target.resolve()
            for relative_name, expected in checksums.items():
                candidate = (target / str(relative_name)).resolve()
                if not candidate.is_relative_to(resolved_target):
                    raise ValueError(
                        f"Qlib metadata contains an unsafe path: {relative_name}"
                    )
                if not candidate.is_file() or file_sha256(candidate) != expected:
                    raise ValueError(
                        f"Qlib file checksum mismatch: {candidate}"
                    )
            return QlibBinaryResult(
                qlib_dir=target,
                calendar_path=target / "calendars" / "day.txt",
                instruments_path=target / "instruments" / "all.txt",
                metadata_path=metadata_path,
                symbols=list(metadata["symbols"]),
                rows=int(metadata["rows"]),
            )

        daily = DataSnapshotStore.load_dataset(manifest, "daily_bar")
        factors = DataSnapshotStore.load_dataset(manifest, "adjust_factor")
        calendar = DataSnapshotStore.load_dataset(manifest, "trading_calendar")
        open_days = sorted(
            pd.to_datetime(calendar.loc[calendar["is_open"].astype(bool), "trade_date"])
            .dt.strftime("%Y-%m-%d")
            .tolist()
        )
        if not open_days:
            raise ValueError("Qlib conversion requires an open trading calendar")
        daily["trade_date"] = pd.to_datetime(daily["trade_date"]).dt.strftime("%Y-%m-%d")
        factors["trade_date"] = pd.to_datetime(factors["trade_date"]).dt.strftime(
            "%Y-%m-%d"
        )
        daily = apply_forward_adjustment(daily, factors)

        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{manifest.data_version}.", dir=target.parent)
        )
        try:
            calendars_dir = temporary / "calendars"
            instruments_dir = temporary / "instruments"
            features_dir = temporary / "features"
            calendars_dir.mkdir()
            instruments_dir.mkdir()
            features_dir.mkdir()
            (calendars_dir / "day.txt").write_text(
                "\n".join(open_days) + "\n",
                encoding="utf-8",
            )
            calendar_index = {value: index for index, value in enumerate(open_days)}
            instrument_lines: list[str] = []
            symbols = sorted(daily["symbol"].astype(str).unique())
            for symbol in symbols:
                symbol_frame = (
                    daily[daily["symbol"] == symbol]
                    .sort_values("trade_date")
                    .drop_duplicates("trade_date")
                )
                start = str(symbol_frame["trade_date"].min())
                end = str(symbol_frame["trade_date"].max())
                instrument_lines.append(
                    f"{self._qlib_instrument(symbol)}\t{start}\t{end}"
                )
                start_index = calendar_index[start]
                relevant_calendar = [
                    value for value in open_days if start <= value <= end
                ]
                aligned = symbol_frame.set_index("trade_date").reindex(relevant_calendar)
                symbol_dir = features_dir / self._qlib_instrument(symbol).lower()
                symbol_dir.mkdir()
                for field in self.FIELDS:
                    values = [float(start_index)]
                    values.extend(
                        float(value) if pd.notna(value) else float("nan")
                        for value in aligned[field].tolist()
                    )
                    (symbol_dir / f"{field}.day.bin").write_bytes(
                        struct.pack(f"<{len(values)}f", *values)
                    )
            (instruments_dir / "all.txt").write_text(
                "\n".join(instrument_lines) + "\n",
                encoding="utf-8",
            )
            generated_files = sorted(
                path
                for path in temporary.rglob("*")
                if path.is_file()
            )
            file_checksums = {
                str(path.relative_to(temporary)): file_sha256(path)
                for path in generated_files
            }
            metadata = {
                "schema_version": "1.0",
                "data_version": manifest.data_version,
                "source_manifest": str(
                    Path(manifest.snapshot_dir) / "data_manifest.json"
                ),
                "symbols": symbols,
                "rows": int(len(daily)),
                "fields": list(self.FIELDS),
                "file_checksums": file_checksums,
            }
            atomic_write_json(temporary / "metadata.json", metadata)
            try:
                os.replace(temporary, target)
            except FileExistsError:
                shutil.rmtree(temporary)
        except BaseException:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise
        return QlibBinaryResult(
            qlib_dir=target,
            calendar_path=target / "calendars" / "day.txt",
            instruments_path=target / "instruments" / "all.txt",
            metadata_path=target / "metadata.json",
            symbols=symbols,
            rows=int(len(daily)),
        )

    @staticmethod
    def _qlib_instrument(symbol: str) -> str:
        code, exchange = symbol.split(".")
        return f"{exchange}{code}"
