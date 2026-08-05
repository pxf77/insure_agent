from __future__ import annotations

import gzip
from dataclasses import dataclass
from datetime import date, datetime
from io import StringIO
from pathlib import Path

import pandas as pd

from quant_agent.common.io import (
    atomic_write_bytes,
    atomic_write_json,
    bytes_sha256,
    content_sha256,
    file_sha256,
    read_json,
)
from quant_agent.data.providers.base import (
    CANONICAL_COLUMNS,
    CANONICAL_DATASETS,
    CanonicalDataBundle,
    MarketDataProvider,
)
from quant_agent.data.quality import has_critical_failures, validate_canonical_datasets
from quant_agent.data.symbol import normalize_symbol
from quant_agent.schemas.data import DataManifest, DatasetManifest, DataValidationResult


class DataQualityError(RuntimeError):
    def __init__(self, manifest: DataManifest):
        failed = [
            result.rule_id
            for result in manifest.validations
            if not result.passed and result.severity == "ERROR"
        ]
        super().__init__(f"critical data validation failed: {', '.join(failed)}")
        self.manifest = manifest


@dataclass(frozen=True)
class SnapshotResult:
    manifest: DataManifest
    manifest_path: Path
    reused: bool


class DataSnapshotStore:
    def __init__(self, artifact_root: str | Path):
        self.artifact_root = Path(artifact_root)
        self.snapshots_root = self.artifact_root / "data" / "snapshots"

    def synchronize(
        self,
        provider: MarketDataProvider,
        trade_date: date,
        *,
        strict: bool = True,
    ) -> SnapshotResult:
        bundle = provider.fetch(trade_date)
        datasets = self._canonicalize_bundle(bundle)
        canonical_payloads = {
            name: self._to_csv_bytes(datasets[name]) for name in CANONICAL_DATASETS
        }
        data_version = content_sha256(
            {name: bytes_sha256(payload) for name, payload in canonical_payloads.items()}
        )
        snapshot_dir = self.snapshots_root / trade_date.isoformat() / data_version
        manifest_path = snapshot_dir / "data_manifest.json"
        if manifest_path.exists():
            manifest = DataManifest.model_validate(read_json(manifest_path))
            for name in manifest.datasets:
                self.load_dataset(manifest, name)
            if strict and not manifest.valid:
                raise DataQualityError(manifest)
            return SnapshotResult(manifest=manifest, manifest_path=manifest_path, reused=True)

        snapshot_dir.mkdir(parents=True, exist_ok=False)
        dataset_manifests: dict[str, DatasetManifest] = {}
        for name, csv_payload in canonical_payloads.items():
            output_path = snapshot_dir / f"{name}.csv.gz"
            atomic_write_bytes(output_path, gzip.compress(csv_payload, mtime=0))
            dataset_manifests[name] = DatasetManifest(
                name=name,
                path=str(output_path),
                rows=len(datasets[name]),
                sha256=file_sha256(output_path),
                columns=list(datasets[name].columns),
            )
        validations = validate_canonical_datasets(datasets, trade_date=trade_date)
        manifest = DataManifest(
            data_version=data_version,
            provider=bundle.provider,
            trade_date=trade_date.isoformat(),
            as_of=trade_date.isoformat(),
            retrieved_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            valid=not has_critical_failures(validations),
            snapshot_dir=str(snapshot_dir),
            datasets=dataset_manifests,
            validations=validations,
            provider_metadata=bundle.metadata,
        )
        atomic_write_json(manifest_path, manifest)
        if manifest.valid:
            atomic_write_json(
                self.snapshots_root / trade_date.isoformat() / "latest.json",
                {
                    "data_version": data_version,
                    "manifest": str(manifest_path),
                },
            )
        if strict and not manifest.valid:
            raise DataQualityError(manifest)
        return SnapshotResult(manifest=manifest, manifest_path=manifest_path, reused=False)

    def latest(self, trade_date: date) -> SnapshotResult:
        pointer_path = self.snapshots_root / trade_date.isoformat() / "latest.json"
        if not pointer_path.exists():
            raise FileNotFoundError(f"no valid data snapshot for {trade_date}")
        pointer = read_json(pointer_path)
        manifest_path = Path(str(pointer["manifest"]))
        manifest = DataManifest.model_validate(read_json(manifest_path))
        if not manifest.valid:
            raise DataQualityError(manifest)
        return SnapshotResult(manifest=manifest, manifest_path=manifest_path, reused=True)

    @staticmethod
    def load_dataset(manifest: DataManifest, name: str) -> pd.DataFrame:
        if name not in manifest.datasets:
            raise KeyError(f"dataset is not registered: {name}")
        dataset = manifest.datasets[name]
        path = Path(dataset.path)
        if file_sha256(path) != dataset.sha256:
            raise DataQualityError(
                manifest.model_copy(
                    update={
                        "valid": False,
                        "validations": [
                            *manifest.validations,
                            DataValidationResult(
                                rule_id="DATASET_CHECKSUM",
                                passed=False,
                                severity="ERROR",
                                dataset=name,
                                message=f"checksum mismatch: {path}",
                            ),
                        ],
                    }
                )
            )
        return pd.read_csv(path, compression="gzip")

    @staticmethod
    def _canonicalize_bundle(bundle: CanonicalDataBundle) -> dict[str, pd.DataFrame]:
        omitted = sorted(set(CANONICAL_DATASETS) - set(bundle.datasets))
        if omitted:
            raise ValueError(f"provider omitted canonical datasets: {omitted}")
        result: dict[str, pd.DataFrame] = {}
        for name in CANONICAL_DATASETS:
            frame = bundle.datasets[name].copy()
            missing = set(CANONICAL_COLUMNS[name]) - set(frame.columns)
            if missing:
                raise ValueError(f"{name} missing canonical columns: {sorted(missing)}")
            frame = frame[list(CANONICAL_COLUMNS[name])]
            if "symbol" in frame:
                frame["symbol"] = frame["symbol"].map(normalize_symbol)
            for column in (
                "trade_date",
                "list_date",
                "delist_date",
                "effective_start",
                "effective_end",
            ):
                if column in frame and not frame.empty:
                    non_null = frame[column].notna()
                    frame.loc[non_null, column] = pd.to_datetime(
                        frame.loc[non_null, column]
                    ).dt.strftime("%Y-%m-%d")
            sort_columns = [
                column
                for column in (
                    "trade_date",
                    "universe",
                    "symbol",
                    "effective_start",
                )
                if column in frame
            ]
            if sort_columns:
                frame = frame.sort_values(sort_columns, kind="stable")
            result[name] = frame.reset_index(drop=True)
        return result

    @staticmethod
    def _to_csv_bytes(frame: pd.DataFrame) -> bytes:
        buffer = StringIO()
        frame.to_csv(buffer, index=False, lineterminator="\n")
        return buffer.getvalue().encode("utf-8")
