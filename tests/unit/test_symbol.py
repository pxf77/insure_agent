import pytest

from quant_agent.data.symbol import normalize_symbol


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("600519", "600519.SH"),
        ("000001", "000001.SZ"),
        ("300750", "300750.SZ"),
        ("SH600519", "600519.SH"),
        ("SZ000001", "000001.SZ"),
        ("600519.SH", "600519.SH"),
        ("000001.sz", "000001.SZ"),
        (" 600519 ", "600519.SH"),
    ],
)
def test_normalize_symbol(raw, expected):
    assert normalize_symbol(raw) == expected


@pytest.mark.parametrize("raw", ["", "ABC", "12345", "1234567", "60051A"])
def test_normalize_symbol_rejects_invalid_values(raw):
    with pytest.raises(ValueError):
        normalize_symbol(raw)
