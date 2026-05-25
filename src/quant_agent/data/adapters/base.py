from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import pandas as pd


class DataAdapter(ABC):
    @abstractmethod
    def fetch_daily_bar(
        self,
        start: date,
        end: date,
        symbols: list[str] | None = None,
    ) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def fetch_adjust_factor(
        self,
        start: date,
        end: date,
        symbols: list[str] | None = None,
    ) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def fetch_instrument_status(self, start: date, end: date) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def fetch_limit_price(
        self,
        start: date,
        end: date,
        symbols: list[str] | None = None,
    ) -> pd.DataFrame:
        raise NotImplementedError
