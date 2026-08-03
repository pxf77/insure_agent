from __future__ import annotations

import urllib.error
from datetime import datetime
from typing import Any

import pandas as pd
import pytest

from quant_agent.data.providers.choice import ChoiceMarketDataProvider
from quant_agent.data.providers.ifind import IFindMarketDataProvider
from quant_agent.data.snapshot import SnapshotBuilder


class ChoiceResult:
    def __init__(self, *, error_code: int = 0, error_message: str = "") -> None:
        self.ErrorCode = error_code
        self.ErrorMsg = error_message


class FakeChoiceClient:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.started_with: str | None = None
        self.csd_args: tuple[object, ...] | None = None
        self.csd_calls: list[tuple[object, ...]] = []
        self.stopped = False

    def start(self, options: str) -> ChoiceResult:
        self.started_with = options
        return ChoiceResult()

    def csd(self, *args: object) -> pd.DataFrame:
        self.csd_args = args
        self.csd_calls.append(args)
        return self.frame

    def stop(self) -> ChoiceResult:
        self.stopped = True
        return ChoiceResult()


def test_choice_provider_uses_official_csd_shape_and_normalizes_rows() -> None:
    frame = pd.DataFrame(
        {
            "DATES": ["2026-05-21", "2026-05-22"],
            "OPEN": [100, 101],
            "HIGH": [105, 106],
            "LOW": [99, 100],
            "CLOSE": [104, 105],
            "VOLUME": [1000, 1100],
            "AMOUNT": [104000, 115500],
        },
        index=pd.Index(["SH600519", "SH600519"], name="CODES"),
    )
    client = FakeChoiceClient(frame)
    provider = ChoiceMarketDataProvider(
        symbols=["600519.SH"],
        lookback_days=30,
        client=client,
    )

    result = provider.fetch_daily_bars(
        as_of=datetime.fromisoformat("2026-05-22T16:00:00+08:00")
    )

    assert result["symbol"].tolist() == ["600519.SH", "600519.SH"]
    assert result["available_at"].tolist() == [
        "2026-05-21T15:10:00+08:00",
        "2026-05-22T15:10:00+08:00",
    ]
    assert client.started_with == "ForceLogin=0,RecordLoginInfo=0"
    assert client.csd_args is not None
    assert client.csd_args[0] == "600519.SH"
    assert client.csd_args[1] == "OPEN,HIGH,LOW,CLOSE,VOLUME,AMOUNT"
    assert client.csd_args[2:4] == ("2026-04-22", "2026-05-22")
    assert "Ispandas=0" in str(client.csd_args[5 - 1])
    assert client.stopped


def test_choice_provider_uses_china_market_date_for_utc_cutoff() -> None:
    frame = pd.DataFrame(
        {
            "DATES": ["2026-05-22"],
            "OPEN": [10.0],
            "HIGH": [10.5],
            "LOW": [9.9],
            "CLOSE": [10.2],
            "VOLUME": [1000],
            "AMOUNT": [10200.0],
        },
        index=pd.Index(["000001.SZ"], name="CODES"),
    )
    client = FakeChoiceClient(frame)
    provider = ChoiceMarketDataProvider(
        symbols=["000001.SZ"],
        lookback_days=1,
        client=client,
    )

    provider.fetch_daily_bars(as_of=datetime.fromisoformat("2026-05-21T16:30:00Z"))

    assert client.csd_args is not None
    assert client.csd_args[2:4] == ("2026-05-21", "2026-05-22")


def test_choice_provider_batches_symbol_queries() -> None:
    class BatchedChoiceClient(FakeChoiceClient):
        def csd(self, *args: object) -> pd.DataFrame:
            self.csd_args = args
            self.csd_calls.append(args)
            symbols = str(args[0]).split(",")
            return pd.DataFrame(
                {
                    "DATES": ["2026-05-22"] * len(symbols),
                    "OPEN": [10.0] * len(symbols),
                    "HIGH": [10.5] * len(symbols),
                    "LOW": [9.9] * len(symbols),
                    "CLOSE": [10.2] * len(symbols),
                    "VOLUME": [1000] * len(symbols),
                    "AMOUNT": [10200.0] * len(symbols),
                },
                index=pd.Index(symbols, name="CODES"),
            )

    client = BatchedChoiceClient(pd.DataFrame())
    provider = ChoiceMarketDataProvider(
        symbols=["600519.SH", "000001.SZ", "300750.SZ"],
        batch_size=2,
        request_interval_seconds=0.0,
        client=client,
    )

    result = provider.fetch_daily_bars(
        as_of=datetime.fromisoformat("2026-05-22T16:00:00+08:00")
    )

    assert [call[0] for call in client.csd_calls] == [
        "600519.SH,000001.SZ",
        "300750.SZ",
    ]
    assert result["symbol"].tolist() == ["600519.SH", "000001.SZ", "300750.SZ"]


def test_choice_provider_parses_emquant_data_mapping() -> None:
    provider = ChoiceMarketDataProvider(symbols=["000001.SZ"], client=object())
    response = ChoiceResult()
    response.Codes = ["000001.SZ"]
    response.Dates = ["2026-05-22"]
    response.Indicators = ["OPEN", "HIGH", "LOW", "CLOSE", "VOLUME", "AMOUNT"]
    response.Data = {
        "000001.SZ": [[10.0], [10.5], [9.9], [10.2], [1000], [10200.0]]
    }

    frame = provider._to_frame(response)

    assert frame.to_dict(orient="records") == [
        {
            "symbol": "000001.SZ",
            "trade_date": "2026-05-22",
            "open": 10.0,
            "high": 10.5,
            "low": 9.9,
            "close": 10.2,
            "volume": 1000,
            "amount": 10200.0,
        }
    ]


def _ifind_response(symbol: str = "000001.SZ") -> dict[str, Any]:
    return {
        "errorcode": 0,
        "tables": [
            {
                "thscode": symbol,
                "time": ["2026-05-21", "2026-05-22"],
                "table": {
                    "open": [10.0, 10.1],
                    "high": [10.5, 10.6],
                    "low": [9.9, 10.0],
                    "close": [10.2, 10.4],
                    "volume": [1000, 1100],
                    "amount": [10200, 11440],
                },
            }
        ],
    }


def test_ifind_provider_uses_http_token_without_exposing_it() -> None:
    calls: list[tuple[str, dict[str, object], dict[str, str], float]] = []

    def transport(
        url: str,
        payload: dict[str, object],
        headers: dict[str, str],
        timeout: float,
    ) -> dict[str, Any]:
        calls.append((url, payload, headers, timeout))
        return _ifind_response()

    provider = IFindMarketDataProvider(
        symbols=["SZ000001"],
        access_token="secret-token",
        transport=transport,
    )
    result = provider.fetch_daily_bars(
        as_of=datetime.fromisoformat("2026-05-22T16:00:00+08:00")
    )

    assert result["symbol"].tolist() == ["000001.SZ", "000001.SZ"]
    assert result["available_at"].iloc[-1] == "2026-05-22T15:07:00+08:00"
    assert calls[0][1]["codes"] == "000001.SZ"
    assert calls[0][2]["access_token"] == "secret-token"


def test_ifind_provider_batches_and_paces_symbol_queries() -> None:
    calls: list[str] = []

    def transport(
        _url: str,
        payload: dict[str, object],
        _headers: dict[str, str],
        _timeout: float,
    ) -> dict[str, Any]:
        symbol = str(payload["codes"])
        calls.append(symbol)
        return _ifind_response(symbol)

    provider = IFindMarketDataProvider(
        symbols=["000001.SZ", "600519.SH"],
        batch_size=1,
        access_token="test-token",
        transport=transport,
        request_interval_seconds=0.0,
    )

    result = provider.fetch_daily_bars(
        as_of=datetime.fromisoformat("2026-05-22T16:00:00+08:00")
    )

    assert calls == ["000001.SZ", "600519.SH"]
    assert result["symbol"].drop_duplicates().tolist() == ["000001.SZ", "600519.SH"]


def test_ifind_provider_rejects_vendor_symbol_mismatch() -> None:
    provider = IFindMarketDataProvider(
        symbols=["000001.SZ"],
        access_token="test-token",
        transport=lambda *_args: _ifind_response("600519.SH"),
    )

    with pytest.raises(ValueError, match="symbol mismatch"):
        provider.fetch_daily_bars(
            as_of=datetime.fromisoformat("2026-05-22T16:00:00+08:00")
        )


def test_ifind_provider_does_not_retry_non_transient_http_error() -> None:
    calls = 0

    def transport(*_args: object) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        raise urllib.error.HTTPError(
            url="https://quantapi.51ifind.com",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=None,
        )

    provider = IFindMarketDataProvider(
        symbols=["000001.SZ"],
        access_token="test-token",
        transport=transport,
    )

    with pytest.raises(RuntimeError, match="HTTP 401"):
        provider.fetch_daily_bars(
            as_of=datetime.fromisoformat("2026-05-22T16:00:00+08:00")
        )

    assert calls == 1


def test_ifind_provider_uses_china_market_date_for_utc_cutoff() -> None:
    payloads: list[dict[str, object]] = []

    def transport(
        _url: str,
        payload: dict[str, object],
        _headers: dict[str, str],
        _timeout: float,
    ) -> dict[str, Any]:
        payloads.append(payload)
        return _ifind_response()

    provider = IFindMarketDataProvider(
        symbols=["000001.SZ"],
        lookback_days=1,
        access_token="test-token",
        transport=transport,
    )

    provider.fetch_daily_bars(as_of=datetime.fromisoformat("2026-05-21T16:30:00Z"))

    assert payloads[0]["startdate"] == "2026-05-21"
    assert payloads[0]["enddate"] == "2026-05-22"


def test_ifind_provider_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IFIND_ACCESS_TOKEN", raising=False)
    provider = IFindMarketDataProvider(symbols=["000001.SZ"], transport=lambda *_args: {})

    with pytest.raises(RuntimeError, match="IFIND_ACCESS_TOKEN"):
        provider.fetch_daily_bars(
            as_of=datetime.fromisoformat("2026-05-22T16:00:00+08:00")
        )


def test_ifind_provider_rejects_non_official_endpoint() -> None:
    with pytest.raises(ValueError, match="official HTTPS API host"):
        IFindMarketDataProvider(
            symbols=["000001.SZ"],
            access_token="test-token",
            endpoint="https://example.com/history",
        )


def test_ifind_provider_integrates_with_point_in_time_snapshot(tmp_path) -> None:
    provider = IFindMarketDataProvider(
        symbols=["000001.SZ"],
        access_token="test-token",
        transport=lambda *_args: _ifind_response(),
    )
    result = SnapshotBuilder(snapshot_root=tmp_path / "snapshots").build_daily_bars(
        provider,
        as_of=datetime.fromisoformat("2026-05-22T15:06:00+08:00"),
    )

    assert result.manifest.input_rows == 2
    assert result.manifest.visible_rows == 1
    assert result.manifest.provider_id == "tonghuashun-ifind"
