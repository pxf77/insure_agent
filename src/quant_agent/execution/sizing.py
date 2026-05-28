from __future__ import annotations


def round_to_lot(volume: int, lot_size: int = 100) -> int:
    if volume <= 0:
        return 0
    return (volume // lot_size) * lot_size
