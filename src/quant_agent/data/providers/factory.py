from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from quant_agent.data.providers.akshare_provider import AkShareProvider
from quant_agent.data.providers.base import MarketDataProvider
from quant_agent.data.providers.sample_provider import SampleDataProvider
from quant_agent.data.providers.tushare_provider import TushareProvider


def provider_from_config(
    name: str,
    *,
    config_dir: str | Path | None = None,
) -> MarketDataProvider:
    normalized = name.strip().lower()
    provider_values = _provider_values(normalized, config_dir)
    configured_name = str(provider_values.get("name", normalized)).strip().lower()
    if configured_name != normalized:
        raise ValueError(
            f"provider configuration selects {configured_name}, not {normalized}"
        )
    if normalized == "sample":
        return SampleDataProvider()
    if normalized == "akshare":
        return AkShareProvider(
            lookback_days=int(provider_values.get("lookback_days", 400))
        )
    if normalized == "tushare":
        return TushareProvider(
            lookback_days=int(provider_values.get("lookback_days", 400)),
            index_code=str(provider_values.get("index_code", "000300.SH")),
        )
    raise ValueError(f"unsupported data provider: {name}")


def _provider_values(
    name: str,
    config_dir: str | Path | None,
) -> dict[str, Any]:
    if config_dir is None:
        return {}
    path = Path(config_dir) / f"{name}.yaml"
    if not path.exists():
        return {}
    values = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    provider = values.get("provider", {})
    if not isinstance(provider, dict):
        raise ValueError(f"provider configuration must be a mapping: {path}")
    return provider
