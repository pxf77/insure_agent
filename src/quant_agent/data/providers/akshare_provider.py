from __future__ import annotations

from datetime import date, timedelta
from importlib import import_module
from typing import Any

import pandas as pd

from quant_agent.data.providers.base import (
    CANONICAL_DATASETS,
    CanonicalDataBundle,
    MarketDataProvider,
    empty_canonical_frame,
)
from quant_agent.data.symbol import normalize_symbol


class OptionalProviderUnavailable(RuntimeError):
    pass


class AkShareProvider(MarketDataProvider):
    name = "akshare"

    def __init__(self, *, lookback_days: int = 400):
        self.lookback_days = lookback_days

    def fetch(self, trade_date: date) -> CanonicalDataBundle:
        try:
            akshare: Any = import_module("akshare")
        except ImportError as exc:
            raise OptionalProviderUnavailable(
                "AkShare is not installed; install the research extra or select "
                "the sample provider"
            ) from exc

        constituents = akshare.index_stock_cons(symbol="000300")
        code_column = self._find_column(constituents, ("品种代码", "成分券代码", "代码", "symbol"))
        name_column = self._find_column(
            constituents,
            ("品种名称", "成分券名称", "名称", "name"),
            required=False,
        )
        codes = sorted({normalize_symbol(str(value)) for value in constituents[code_column]})
        start = trade_date - timedelta(days=self.lookback_days)
        daily_frames: list[pd.DataFrame] = []
        for symbol in codes:
            raw = akshare.stock_zh_a_hist(
                symbol=symbol.split(".")[0],
                period="daily",
                start_date=start.strftime("%Y%m%d"),
                end_date=trade_date.strftime("%Y%m%d"),
                adjust="",
            )
            if raw.empty:
                continue
            renamed = raw.rename(
                columns={
                    "日期": "trade_date",
                    "股票代码": "symbol",
                    "开盘": "open",
                    "最高": "high",
                    "最低": "low",
                    "收盘": "close",
                    "成交量": "volume",
                    "成交额": "amount",
                }
            )
            renamed["symbol"] = symbol
            daily_frames.append(
                renamed[
                    [
                        "trade_date",
                        "symbol",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                        "amount",
                    ]
                ]
            )
        daily_bar = (
            pd.concat(daily_frames, ignore_index=True)
            if daily_frames
            else empty_canonical_frame("daily_bar")
        )

        calendar_raw = akshare.tool_trade_date_hist_sina()
        calendar_column = self._find_column(calendar_raw, ("trade_date", "日期"))
        calendar = pd.DataFrame(
            {
                "trade_date": pd.to_datetime(calendar_raw[calendar_column]).dt.strftime(
                    "%Y-%m-%d"
                ),
                "is_open": True,
            }
        )
        calendar = calendar[
            (calendar["trade_date"] >= start.isoformat())
            & (calendar["trade_date"] <= trade_date.isoformat())
        ]

        listing_rows = []
        membership_rows = []
        for _, row in constituents.iterrows():
            symbol = normalize_symbol(str(row[code_column]))
            raw_name = row[name_column] if name_column else None
            listing_rows.append(
                {
                    "symbol": symbol,
                    "list_date": start.isoformat(),
                    "delist_date": None,
                    "name": str(raw_name) if raw_name is not None else None,
                }
            )
            membership_rows.append(
                {
                    "universe": "CSI300",
                    "symbol": symbol,
                    "effective_start": start.isoformat(),
                    "effective_end": None,
                }
            )
        datasets = {name: empty_canonical_frame(name) for name in CANONICAL_DATASETS}
        datasets.update(
            {
                "daily_bar": daily_bar,
                "trading_calendar": calendar,
                "listing": pd.DataFrame(
                    listing_rows,
                    columns=empty_canonical_frame("listing").columns,
                ),
                "universe_membership": pd.DataFrame(
                    membership_rows,
                    columns=empty_canonical_frame("universe_membership").columns,
                ),
            }
        )
        return CanonicalDataBundle(
            provider=self.name,
            trade_date=trade_date,
            datasets=datasets,
            metadata={
                "universe": "CSI300",
                "limitations": [
                    "adjust_factor unavailable in this adapter",
                    "instrument_status unavailable in this adapter",
                    "limit_price unavailable in this adapter",
                    "historical CSI300 membership dates unavailable in this adapter",
                ],
            },
        )

    @staticmethod
    def _find_column(
        frame: pd.DataFrame,
        candidates: tuple[str, ...],
        *,
        required: bool = True,
    ) -> str | None:
        for candidate in candidates:
            if candidate in frame.columns:
                return candidate
        if required:
            raise ValueError(
                f"AkShare response is missing expected columns {candidates}; "
                f"received {list(frame.columns)}"
            )
        return None
