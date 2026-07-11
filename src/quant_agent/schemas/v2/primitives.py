from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, Field, RootModel, field_validator

from quant_agent.data.symbol import normalize_symbol


def _normalize_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include timezone information")
    return value.astimezone(timezone.utc)


AwareDateTime = Annotated[datetime, AfterValidator(_normalize_aware_datetime)]
Money = Annotated[Decimal, Field(max_digits=20, decimal_places=4)]
Price = Annotated[Decimal, Field(gt=0, max_digits=20, decimal_places=6)]
Weight = Annotated[Decimal, Field(ge=0, le=1, max_digits=12, decimal_places=10)]
Score = Annotated[Decimal, Field(max_digits=24, decimal_places=12)]
NonNegativeBps = Annotated[Decimal, Field(ge=0, le=10_000, decimal_places=4)]
PositiveQuantity = Annotated[int, Field(gt=0)]


class InstrumentId(RootModel[str]):
    """Normalized A-share instrument identifier such as ``600519.SH``."""

    root: str

    @field_validator("root", mode="before")
    @classmethod
    def normalize(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("instrument identifier must be a string")
        return normalize_symbol(value)

    def __str__(self) -> str:
        return self.root
