from __future__ import annotations

from datetime import datetime
from uuid import uuid4


def generate_run_id(
    mode: str,
    strategy_id: str,
    *,
    now: datetime | None = None,
    short_hash: str | None = None,
) -> str:
    timestamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    suffix = short_hash or uuid4().hex[:6]
    return f"{timestamp}-{mode}-{strategy_id}-{suffix}"
