from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Literal, cast
from uuid import uuid4

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

from quant_agent.data.providers.base import MarketDataProvider
from quant_agent.data.quality import (
    DAILY_BAR_SNAPSHOT_COLUMNS,
    DataQualityIssue,
    DataQualityReport,
    DataQualitySeverity,
    evaluate_daily_bar_quality,
    has_explicit_timezone,
)
from quant_agent.data.symbol import normalize_symbol
from quant_agent.schemas.v2.primitives import AwareDateTime

_REQUIRED_ARTIFACTS = {
    "raw/daily_bar.csv",
    "normalized/daily_bar.csv",
    "data_quality.json",
}


class SnapshotFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rows: int = Field(ge=0)
    bytes: int = Field(ge=0)

    @field_validator("path")
    @classmethod
    def validate_safe_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise ValueError("snapshot artifact path must be safe and relative")
        return path.as_posix()


class DataSnapshotManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    snapshot_id: str = Field(pattern=r"^daily-[0-9a-f]{20}$")
    dataset: Literal["daily_bar"] = "daily_bar"
    provider_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    provider_version: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9_.:+-]+$",
    )
    as_of: AwareDateTime
    created_at: AwareDateTime
    input_rows: int = Field(ge=0)
    visible_rows: int = Field(ge=0)
    symbols: list[str]
    quality_summary: dict[str, int]
    files: list[SnapshotFile]


class SnapshotBuildResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    snapshot_dir: Path
    manifest_path: Path
    quality_path: Path
    raw_path: Path
    normalized_path: Path
    manifest: DataSnapshotManifest
    reused: bool


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must include timezone information")
    return value.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return _aware_utc(value).isoformat().replace("+00:00", "Z")


def _canonical_json(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_csv(frame: pd.DataFrame) -> bytes:
    text = cast(
        str,
        frame.to_csv(
            index=False,
            lineterminator="\n",
            float_format="%.10g",
        ),
    )
    return text.encode("utf-8")


def _canonical_raw_daily_bars(frame: pd.DataFrame) -> pd.DataFrame:
    raw = frame.loc[:, list(DAILY_BAR_SNAPSHOT_COLUMNS)].copy()
    raw["_trade_sort"] = pd.to_datetime(raw["trade_date"], errors="raise")
    raw["_symbol_sort"] = raw["symbol"].astype(str)
    raw["_available_sort"] = pd.to_datetime(raw["available_at"], errors="raise", utc=True)
    raw = raw.sort_values(
        ["_trade_sort", "_symbol_sort", "_available_sort"],
        kind="mergesort",
    ).drop(columns=["_trade_sort", "_symbol_sort", "_available_sort"])
    return raw.reset_index(drop=True)


def normalize_daily_bars(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.loc[:, list(DAILY_BAR_SNAPSHOT_COLUMNS)].copy()
    normalized["trade_date"] = pd.to_datetime(normalized["trade_date"]).dt.strftime("%Y-%m-%d")
    normalized["symbol"] = normalized["symbol"].map(lambda value: normalize_symbol(str(value)))
    normalized["available_at"] = pd.to_datetime(
        normalized["available_at"], utc=True
    ).dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    for column in ("open", "high", "low", "close", "volume", "amount"):
        normalized[column] = pd.to_numeric(normalized[column])
    normalized = normalized.sort_values(
        ["trade_date", "symbol", "available_at"],
        kind="mergesort",
    ).reset_index(drop=True)
    return normalized


def _content_record(path: str, content: bytes, rows: int) -> SnapshotFile:
    return SnapshotFile(
        path=path,
        sha256=_sha256(content),
        rows=rows,
        bytes=len(content),
    )


def _identity_payload(
    *,
    provider_id: str,
    provider_version: str,
    as_of: datetime,
    input_rows: int,
    visible_rows: int,
    symbols: list[str],
    quality_summary: dict[str, int],
    files: list[SnapshotFile],
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "dataset": "daily_bar",
        "provider_id": provider_id,
        "provider_version": provider_version,
        "as_of": _utc_text(as_of),
        "input_rows": input_rows,
        "visible_rows": visible_rows,
        "symbols": sorted(symbols),
        "quality_summary": dict(sorted(quality_summary.items())),
        "files": [
            artifact.model_dump(mode="json")
            for artifact in sorted(files, key=lambda item: item.path)
        ],
    }


def _snapshot_id(identity: dict[str, object]) -> str:
    return f"daily-{_sha256(_canonical_json(identity))[:20]}"


class SnapshotBuilder:
    def __init__(self, *, snapshot_root: str | Path):
        self.snapshot_root = Path(snapshot_root)

    def build_daily_bars(
        self,
        provider: MarketDataProvider,
        *,
        as_of: datetime,
    ) -> SnapshotBuildResult:
        as_of_utc = _aware_utc(as_of)
        source = provider.fetch_daily_bars(as_of=as_of_utc).copy()
        input_rows = len(source)

        missing = [column for column in DAILY_BAR_SNAPSHOT_COLUMNS if column not in source.columns]
        if missing:
            report = evaluate_daily_bar_quality(source)
            raise ValueError(self._blocked_message(report))

        explicit_timezone = source["available_at"].map(has_explicit_timezone)
        if not explicit_timezone.all():
            report = evaluate_daily_bar_quality(source)
            raise ValueError(self._blocked_message(report))

        available_at = pd.to_datetime(source["available_at"], errors="coerce", utc=True)
        if available_at.isna().any():
            report = evaluate_daily_bar_quality(source)
            raise ValueError(self._blocked_message(report))

        visible = source.loc[available_at <= as_of_utc].copy()
        report = evaluate_daily_bar_quality(visible)
        if visible.empty:
            report.issues.append(
                DataQualityIssue(
                    check_id="EMPTY_AS_OF",
                    severity=DataQualitySeverity.CRITICAL,
                    message="no daily bar rows are available at the requested as_of time",
                    row_count=0,
                )
            )
        if report.blocked:
            raise ValueError(self._blocked_message(report))

        canonical_raw = _canonical_raw_daily_bars(visible)
        normalized = normalize_daily_bars(visible)
        raw_content = _canonical_csv(canonical_raw)
        normalized_content = _canonical_csv(normalized)
        quality_content = _canonical_json(report.model_dump(mode="json"))
        files = [
            _content_record("raw/daily_bar.csv", raw_content, len(canonical_raw)),
            _content_record("normalized/daily_bar.csv", normalized_content, len(normalized)),
            _content_record("data_quality.json", quality_content, len(report.issues)),
        ]
        symbols = sorted(normalized["symbol"].unique().tolist())
        identity = _identity_payload(
            provider_id=provider.provider_id,
            provider_version=provider.provider_version,
            as_of=as_of_utc,
            input_rows=input_rows,
            visible_rows=len(normalized),
            symbols=symbols,
            quality_summary=report.summary,
            files=files,
        )
        snapshot_id = _snapshot_id(identity)
        snapshot_dir = self.snapshot_root / snapshot_id
        if snapshot_dir.exists():
            manifest = self._verify_existing(snapshot_dir)
            return self._result(snapshot_dir, manifest, reused=True)

        temporary_dir = self.snapshot_root / f".{snapshot_id}.{uuid4().hex}.tmp"
        try:
            (temporary_dir / "raw").mkdir(parents=True, exist_ok=False)
            (temporary_dir / "normalized").mkdir(parents=True, exist_ok=False)
            (temporary_dir / "raw" / "daily_bar.csv").write_bytes(raw_content)
            (temporary_dir / "normalized" / "daily_bar.csv").write_bytes(normalized_content)
            (temporary_dir / "data_quality.json").write_bytes(quality_content)

            manifest = DataSnapshotManifest(
                snapshot_id=snapshot_id,
                provider_id=provider.provider_id,
                provider_version=provider.provider_version,
                as_of=as_of_utc,
                created_at=datetime.now(timezone.utc),
                input_rows=input_rows,
                visible_rows=len(normalized),
                symbols=symbols,
                quality_summary=report.summary,
                files=files,
            )
            (temporary_dir / "manifest.json").write_bytes(
                _canonical_json(manifest.model_dump(mode="json"))
            )
            self.snapshot_root.mkdir(parents=True, exist_ok=True)
            try:
                os.rename(temporary_dir, snapshot_dir)
            except FileExistsError:
                shutil.rmtree(temporary_dir)
                manifest = self._verify_existing(snapshot_dir)
                return self._result(snapshot_dir, manifest, reused=True)
        except Exception:
            if temporary_dir.exists():
                shutil.rmtree(temporary_dir)
            raise

        return self._result(snapshot_dir, manifest, reused=False)

    @staticmethod
    def _blocked_message(report: DataQualityReport) -> str:
        check_ids = [
            issue.check_id
            for issue in report.issues
            if issue.severity == DataQualitySeverity.CRITICAL
        ]
        return f"data quality blocked snapshot: {', '.join(check_ids) or 'UNKNOWN'}"

    def _verify_existing(self, snapshot_dir: Path) -> DataSnapshotManifest:
        manifest_path = snapshot_dir / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError(f"snapshot is incomplete or unsafe: {snapshot_dir}")
        manifest = DataSnapshotManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        if manifest.snapshot_id != snapshot_dir.name:
            raise ValueError("snapshot manifest ID does not match directory")

        file_paths = [artifact.path for artifact in manifest.files]
        if len(file_paths) != len(set(file_paths)) or set(file_paths) != _REQUIRED_ARTIFACTS:
            raise ValueError("snapshot manifest contains an unexpected artifact set")

        expected_entries = _REQUIRED_ARTIFACTS | {"manifest.json"}
        actual_entries: set[str] = set()
        for path in snapshot_dir.rglob("*"):
            if path.is_symlink():
                raise ValueError(f"snapshot contains a symbolic link: {path}")
            if path.is_file():
                actual_entries.add(path.relative_to(snapshot_dir).as_posix())
        if actual_entries != expected_entries:
            raise ValueError("snapshot contains missing or unexpected files")

        snapshot_root = snapshot_dir.resolve()
        for artifact in manifest.files:
            path = snapshot_dir / artifact.path
            resolved = path.resolve()
            if not resolved.is_relative_to(snapshot_root) or not path.is_file():
                raise ValueError(f"snapshot artifact path is unsafe: {artifact.path}")
            content = path.read_bytes()
            if _sha256(content) != artifact.sha256 or len(content) != artifact.bytes:
                raise ValueError(f"snapshot artifact failed integrity check: {artifact.path}")

        identity = _identity_payload(
            provider_id=manifest.provider_id,
            provider_version=manifest.provider_version,
            as_of=manifest.as_of,
            input_rows=manifest.input_rows,
            visible_rows=manifest.visible_rows,
            symbols=manifest.symbols,
            quality_summary=manifest.quality_summary,
            files=manifest.files,
        )
        if _snapshot_id(identity) != manifest.snapshot_id:
            raise ValueError("snapshot manifest failed identity verification")
        return manifest

    @staticmethod
    def _result(
        snapshot_dir: Path,
        manifest: DataSnapshotManifest,
        *,
        reused: bool,
    ) -> SnapshotBuildResult:
        return SnapshotBuildResult(
            snapshot_dir=snapshot_dir,
            manifest_path=snapshot_dir / "manifest.json",
            quality_path=snapshot_dir / "data_quality.json",
            raw_path=snapshot_dir / "raw" / "daily_bar.csv",
            normalized_path=snapshot_dir / "normalized" / "daily_bar.csv",
            manifest=manifest,
            reused=reused,
        )
