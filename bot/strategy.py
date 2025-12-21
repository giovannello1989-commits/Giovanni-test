from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MomentumSignal:
    symbol: str
    last_price: float
    mom_1h: float
    mom_15m: float


def compute_momentum_from_5m_candles(symbol: str, candles: list[dict[str, Any]]) -> MomentumSignal | None:
    """
    Expects 5m candles ordered oldest->newest.

    Need at least:
    - 1h ago close => 12 * 5m = 60m => index -13 (last + 12 previous)
    - 15m ago close => 3 * 5m = 15m => index -4
    """
    if len(candles) < 13:
        return None

    last = float(candles[-1]["close"])
    close_1h_ago = float(candles[-13]["close"])
    close_15m_ago = float(candles[-4]["close"]) if len(candles) >= 4 else None
    if close_1h_ago <= 0:
        return None
    if close_15m_ago is None or close_15m_ago <= 0:
        return None

    mom_1h = (last - close_1h_ago) / close_1h_ago
    mom_15m = (last - close_15m_ago) / close_15m_ago
    return MomentumSignal(symbol=symbol, last_price=last, mom_1h=mom_1h, mom_15m=mom_15m)


def fmt_pct(x: float) -> str:
    return f"{x * 100:.2f}%"

