from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

CANONICAL_DATASETS = (
    "daily_bar",
    "adjust_factor",
    "trading_calendar",
    "instrument_status",
    "limit_price",
    "listing",
    "universe_membership",
)

CANONICAL_COLUMNS: dict[str, tuple[str, ...]] = {
    "daily_bar": (
        "trade_date",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    ),
    "adjust_factor": ("trade_date", "symbol", "adjust_factor"),
    "trading_calendar": ("trade_date", "is_open"),
    "instrument_status": ("trade_date", "symbol", "suspended", "status"),
    "limit_price": ("trade_date", "symbol", "limit_up", "limit_down"),
    "listing": ("symbol", "list_date", "delist_date", "name"),
    "universe_membership": ("universe", "symbol", "effective_start", "effective_end"),
}


@dataclass(frozen=True)
class CanonicalDataBundle:
    provider: str
    trade_date: date
    datasets: dict[str, pd.DataFrame]
    metadata: dict[str, Any] = field(default_factory=dict)


class MarketDataProvider(ABC):
    name: str

    @abstractmethod
    def fetch(self, trade_date: date) -> CanonicalDataBundle:
        raise NotImplementedError


def empty_canonical_frame(dataset: str) -> pd.DataFrame:
    return pd.DataFrame(columns=list(CANONICAL_COLUMNS[dataset]))
