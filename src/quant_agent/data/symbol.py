from __future__ import annotations

import re

_PLAIN_SYMBOL = re.compile(r"^\d{6}$")
_SUFFIX_SYMBOL = re.compile(r"^(\d{6})\.(SH|SZ)$")
_PREFIX_SYMBOL = re.compile(r"^(SH|SZ)(\d{6})$")


def normalize_symbol(symbol: str) -> str:
    """Normalize A-share symbols to `000000.SH` or `000000.SZ`."""
    value = symbol.strip().upper().replace(" ", "")
    if not value:
        raise ValueError("symbol is empty")

    suffix_match = _SUFFIX_SYMBOL.match(value)
    if suffix_match:
        return f"{suffix_match.group(1)}.{suffix_match.group(2)}"

    prefix_match = _PREFIX_SYMBOL.match(value)
    if prefix_match:
        return f"{prefix_match.group(2)}.{prefix_match.group(1)}"

    if not _PLAIN_SYMBOL.match(value):
        raise ValueError(f"invalid A-share symbol: {symbol!r}")

    if value.startswith(("5", "6", "9")):
        return f"{value}.SH"
    return f"{value}.SZ"
