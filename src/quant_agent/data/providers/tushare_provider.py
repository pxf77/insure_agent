from __future__ import annotations

import os
from datetime import date, timedelta
from importlib import import_module
from typing import Any

import pandas as pd

from quant_agent.data.providers.akshare_provider import OptionalProviderUnavailable
from quant_agent.data.providers.base import CanonicalDataBundle, MarketDataProvider
from quant_agent.data.symbol import normalize_symbol


class TushareProvider(MarketDataProvider):
    name = "tushare"

    def __init__(
        self,
        *,
        token: str | None = None,
        lookback_days: int = 400,
        index_code: str = "000300.SH",
    ):
        self.token = token or os.getenv("TUSHARE_TOKEN")
        self.lookback_days = lookback_days
        self.index_code = index_code

    def fetch(self, trade_date: date) -> CanonicalDataBundle:
        if not self.token:
            raise OptionalProviderUnavailable(
                "Tushare requires TUSHARE_TOKEN; no token was found"
            )
        try:
            tushare: Any = import_module("tushare")
        except ImportError as exc:
            raise OptionalProviderUnavailable(
                "Tushare is not installed; install the research extra before "
                "selecting the tushare provider"
            ) from exc
        pro = tushare.pro_api(self.token)
        start = trade_date - timedelta(days=self.lookback_days)
        start_text = start.strftime("%Y%m%d")
        end_text = trade_date.strftime("%Y%m%d")
        weights = pro.index_weight(
            index_code=self.index_code,
            start_date=start_text,
            end_date=end_text,
        )
        if weights.empty:
            raise ValueError(
                f"Tushare returned no {self.index_code} membership through {end_text}"
            )
        membership = self._membership(weights)
        active = membership[
            (membership["effective_start"] <= trade_date.isoformat())
            & (
                membership["effective_end"].isna()
                | (membership["effective_end"] >= trade_date.isoformat())
            )
        ]
        current_symbols = sorted(set(active["symbol"].astype(str)))
        history_symbols = sorted(set(membership["symbol"].astype(str)))
        daily_frames = []
        factor_frames = []
        for symbol in history_symbols:
            raw_daily = pro.daily(
                ts_code=symbol,
                start_date=start_text,
                end_date=end_text,
            )
            if not raw_daily.empty:
                raw_daily = raw_daily.rename(
                    columns={
                        "ts_code": "symbol",
                        "trade_date": "trade_date",
                        "vol": "volume",
                    }
                )
                raw_daily["trade_date"] = pd.to_datetime(
                    raw_daily["trade_date"],
                    format="%Y%m%d",
                ).dt.strftime("%Y-%m-%d")
                raw_daily["symbol"] = raw_daily["symbol"].map(normalize_symbol)
                raw_daily["volume"] = pd.to_numeric(raw_daily["volume"]) * 100
                raw_daily["amount"] = pd.to_numeric(raw_daily["amount"]) * 1_000
                daily_frames.append(
                    raw_daily[
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
            raw_factor = pro.adj_factor(
                ts_code=symbol,
                start_date=start_text,
                end_date=end_text,
            )
            if not raw_factor.empty:
                raw_factor = raw_factor.rename(
                    columns={
                        "ts_code": "symbol",
                        "adj_factor": "adjust_factor",
                    }
                )
                raw_factor["trade_date"] = pd.to_datetime(
                    raw_factor["trade_date"],
                    format="%Y%m%d",
                ).dt.strftime("%Y-%m-%d")
                raw_factor["symbol"] = raw_factor["symbol"].map(normalize_symbol)
                factor_frames.append(
                    raw_factor[["trade_date", "symbol", "adjust_factor"]]
                )
        if not daily_frames:
            raise ValueError(
                f"Tushare returned no daily bars through {end_text}"
            )
        if not factor_frames:
            raise ValueError(
                f"Tushare returned no adjustment factors through {end_text}"
            )
        daily_bar = pd.concat(daily_frames, ignore_index=True)
        adjust_factor = pd.concat(factor_frames, ignore_index=True)

        calendar_raw = pro.trade_cal(
            exchange="",
            start_date=start_text,
            end_date=end_text,
            fields="cal_date,is_open",
        )
        calendar = pd.DataFrame(
            {
                "trade_date": pd.to_datetime(
                    calendar_raw["cal_date"],
                    format="%Y%m%d",
                ).dt.strftime("%Y-%m-%d"),
                "is_open": calendar_raw["is_open"].astype(int).astype(bool),
            }
        )
        suspended_symbols = self._suspended_symbols(pro, end_text)
        instrument_status = pd.DataFrame(
            [
                {
                    "trade_date": trade_date.isoformat(),
                    "symbol": symbol,
                    "suspended": symbol in suspended_symbols,
                    "status": "SUSPENDED" if symbol in suspended_symbols else "NORMAL",
                }
                for symbol in current_symbols
            ]
        )
        limit_raw = pro.stk_limit(trade_date=end_text)
        limit_raw = limit_raw[limit_raw["ts_code"].isin(current_symbols)]
        limit_price = pd.DataFrame(
            {
                "trade_date": trade_date.isoformat(),
                "symbol": limit_raw["ts_code"].map(normalize_symbol),
                "limit_up": pd.to_numeric(limit_raw["up_limit"]),
                "limit_down": pd.to_numeric(limit_raw["down_limit"]),
            }
        )
        basic = pro.stock_basic(
            exchange="",
            list_status="L",
            fields="ts_code,name,list_date,delist_date",
        )
        basic = basic[basic["ts_code"].isin(history_symbols)]
        listing = pd.DataFrame(
            {
                "symbol": basic["ts_code"].map(normalize_symbol),
                "list_date": pd.to_datetime(
                    basic["list_date"],
                    format="%Y%m%d",
                ).dt.strftime("%Y-%m-%d"),
                "delist_date": pd.to_datetime(
                    basic["delist_date"],
                    format="%Y%m%d",
                    errors="coerce",
                ).dt.strftime("%Y-%m-%d"),
                "name": basic["name"],
            }
        )
        return CanonicalDataBundle(
            provider=self.name,
            trade_date=trade_date,
            datasets={
                "daily_bar": daily_bar,
                "adjust_factor": adjust_factor,
                "trading_calendar": calendar,
                "instrument_status": instrument_status,
                "limit_price": limit_price,
                "listing": listing,
                "universe_membership": membership,
            },
            metadata={
                "universe": "CSI300",
                "index_code": self.index_code,
                "point_in_time_universe": True,
                "lookback_days": self.lookback_days,
            },
        )

    @staticmethod
    def _membership(weights: pd.DataFrame) -> pd.DataFrame:
        source = weights[["trade_date", "con_code"]].copy()
        source["trade_date"] = pd.to_datetime(
            source["trade_date"],
            format="%Y%m%d",
        )
        revisions = sorted(source["trade_date"].drop_duplicates())
        rows: list[dict[str, str | None]] = []
        for index, revision in enumerate(revisions):
            effective_end = (
                (revisions[index + 1] - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
                if index + 1 < len(revisions)
                else None
            )
            revision_symbols = source[source["trade_date"] == revision]["con_code"]
            rows.extend(
                {
                    "universe": "CSI300",
                    "symbol": normalize_symbol(str(symbol)),
                    "effective_start": revision.strftime("%Y-%m-%d"),
                    "effective_end": effective_end,
                }
                for symbol in revision_symbols
            )
        return pd.DataFrame(rows)

    @staticmethod
    def _suspended_symbols(pro: Any, trade_date: str) -> set[str]:
        suspend_method = getattr(pro, "suspend_d", None)
        if suspend_method is None:
            raise ValueError("Tushare client does not expose suspend_d")
        frame = suspend_method(trade_date=trade_date, suspend_type="S")
        if frame.empty or "ts_code" not in frame:
            return set()
        return {normalize_symbol(str(value)) for value in frame["ts_code"]}
