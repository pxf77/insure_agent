from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from quant_agent.data.adjustment import apply_forward_adjustment
from quant_agent.data.providers.akshare_provider import (
    AkShareProvider,
    OptionalProviderUnavailable,
)
from quant_agent.data.providers.base import CanonicalDataBundle, MarketDataProvider
from quant_agent.data.providers.sample_provider import SampleDataProvider
from quant_agent.data.providers.tushare_provider import TushareProvider
from quant_agent.data.snapshots import DataQualityError, DataSnapshotStore


def test_forward_adjustment_removes_a_split_jump():
    daily = pd.DataFrame(
        [
            {
                "trade_date": "2026-07-28",
                "symbol": "600519.SH",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1000,
                "amount": 100000.0,
            },
            {
                "trade_date": "2026-07-29",
                "symbol": "600519.SH",
                "open": 50.0,
                "high": 51.0,
                "low": 49.0,
                "close": 50.0,
                "volume": 2000,
                "amount": 100000.0,
            },
        ]
    )
    factors = pd.DataFrame(
        [
            {
                "trade_date": "2026-07-28",
                "symbol": "600519.SH",
                "adjust_factor": 1.0,
            },
            {
                "trade_date": "2026-07-29",
                "symbol": "600519.SH",
                "adjust_factor": 2.0,
            },
        ]
    )

    adjusted = apply_forward_adjustment(daily, factors)

    assert adjusted["close"].tolist() == [50.0, 50.0]
    assert adjusted["factor"].tolist() == [0.5, 1.0]
    assert adjusted["volume"].tolist() == [2000.0, 2000.0]


def test_tushare_suspension_query_excludes_resume_records():
    class Pro:
        def suspend_d(self, **kwargs):
            assert kwargs == {
                "trade_date": "20260729",
                "suspend_type": "S",
            }
            return pd.DataFrame(
                [{"ts_code": "600519.SH", "suspend_type": "S"}]
            )

    assert TushareProvider._suspended_symbols(Pro(), "20260729") == {
        "600519.SH"
    }


class ChangedSampleProvider(SampleDataProvider):
    def fetch(self, trade_date: date) -> CanonicalDataBundle:
        original = super().fetch(trade_date)
        datasets = {name: frame.copy() for name, frame in original.datasets.items()}
        datasets["daily_bar"].loc[0, "close"] = datasets["daily_bar"].loc[0, "close"] + 0.01
        datasets["daily_bar"].loc[0, "high"] = max(
            datasets["daily_bar"].loc[0, "high"],
            datasets["daily_bar"].loc[0, "close"],
        )
        return CanonicalDataBundle(
            provider=original.provider,
            trade_date=original.trade_date,
            datasets=datasets,
            metadata=original.metadata,
        )


class InvalidSampleProvider(SampleDataProvider):
    def fetch(self, trade_date: date) -> CanonicalDataBundle:
        original = super().fetch(trade_date)
        datasets = {name: frame.copy() for name, frame in original.datasets.items()}
        datasets["daily_bar"].loc[0, "high"] = 0
        return CanonicalDataBundle(
            provider=original.provider,
            trade_date=original.trade_date,
            datasets=datasets,
            metadata=original.metadata,
        )


def test_snapshot_is_valid_immutable_and_reused(tmp_path: Path):
    store = DataSnapshotStore(tmp_path)
    requested_date = date(2026, 7, 29)

    first = store.synchronize(SampleDataProvider(), requested_date)
    second = store.synchronize(SampleDataProvider(), requested_date)

    assert first.manifest.valid is True
    assert second.reused is True
    assert first.manifest.data_version == second.manifest.data_version
    assert set(first.manifest.datasets) == {
        "daily_bar",
        "adjust_factor",
        "trading_calendar",
        "instrument_status",
        "limit_price",
        "listing",
        "universe_membership",
    }
    assert all(dataset.path.endswith(".csv.gz") for dataset in first.manifest.datasets.values())
    daily = store.load_dataset(first.manifest, "daily_bar")
    assert set(daily["symbol"]) == {"600519.SH", "000001.SZ", "300750.SZ"}


def test_changed_payload_creates_new_data_version(tmp_path: Path):
    store = DataSnapshotStore(tmp_path)
    requested_date = date(2026, 7, 29)

    first = store.synchronize(SampleDataProvider(), requested_date)
    changed = store.synchronize(ChangedSampleProvider(), requested_date)

    assert changed.reused is False
    assert changed.manifest.data_version != first.manifest.data_version
    assert Path(first.manifest.snapshot_dir).exists()
    assert Path(changed.manifest.snapshot_dir).exists()


def test_invalid_snapshot_is_persisted_and_blocked(tmp_path: Path):
    store = DataSnapshotStore(tmp_path)
    requested_date = date(2026, 7, 29)

    result = store.synchronize(InvalidSampleProvider(), requested_date, strict=False)

    assert result.manifest.valid is False
    assert result.manifest_path.exists()
    with pytest.raises(DataQualityError, match="DAILY_BAR_VALID"):
        store.synchronize(InvalidSampleProvider(), requested_date)


def test_akshare_missing_optional_package_fails_without_fallback(monkeypatch):
    def missing_import(_name: str):
        raise ImportError

    monkeypatch.setattr(
        "quant_agent.data.providers.akshare_provider.import_module",
        missing_import,
    )

    with pytest.raises(OptionalProviderUnavailable, match="AkShare is not installed"):
        AkShareProvider().fetch(date(2026, 7, 29))


def test_tushare_requires_token_without_exposing_a_fallback(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)

    with pytest.raises(OptionalProviderUnavailable, match="TUSHARE_TOKEN"):
        TushareProvider().fetch(date(2026, 7, 29))


def test_snapshot_detects_modified_dataset(tmp_path: Path):
    store = DataSnapshotStore(tmp_path)
    result = store.synchronize(SampleDataProvider(), date(2026, 7, 29))
    daily_path = Path(result.manifest.datasets["daily_bar"].path)
    daily_path.write_bytes(b"corrupted")

    with pytest.raises(DataQualityError, match="DATASET_CHECKSUM"):
        store.load_dataset(result.manifest, "daily_bar")
    with pytest.raises(DataQualityError, match="DATASET_CHECKSUM"):
        store.synchronize(SampleDataProvider(), date(2026, 7, 29))


class MissingDatasetProvider(MarketDataProvider):
    name = "missing"

    def fetch(self, trade_date: date) -> CanonicalDataBundle:
        return CanonicalDataBundle(
            provider=self.name,
            trade_date=trade_date,
            datasets={"daily_bar": pd.DataFrame()},
        )


def test_provider_must_return_every_canonical_dataset(tmp_path: Path):
    with pytest.raises(ValueError, match="provider omitted canonical dataset"):
        DataSnapshotStore(tmp_path).synchronize(
            MissingDatasetProvider(),
            date(2026, 7, 29),
        )
