from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MomentumSignal:
    symbol: str
    last_price: float
    mom_1h: float
    mom_15m: float


@dataclass(frozen=True)
class EntrySignal:
    kind: str  # "momentum" | "breakout" | "dip"
    symbol: str
    last_price: float
    reason: str
    mom_1h: float | None = None
    mom_15m: float | None = None


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


def compute_breakout_signal(symbol: str, candles: list[dict[str, Any]], breakout_pct: float) -> EntrySignal | None:
    """
    Breakout: last close > max close of previous hour by breakout_pct.
    Uses 13 candles (5m) ~ 1h window.
    """
    if len(candles) < 13:
        return None
    last = float(candles[-1]["close"])
    prev = [float(c["close"]) for c in candles[-13:-1]]
    hi = max(prev)
    if hi <= 0:
        return None
    if last >= hi * (1.0 + float(breakout_pct)):
        return EntrySignal(
            kind="breakout",
            symbol=symbol,
            last_price=last,
            reason=f"breakout: last {last:.8g} >= hi_1h {hi:.8g} * (1+{breakout_pct*100:.2f}%)",
        )
    return None


def compute_dip_signal(symbol: str, candles: list[dict[str, Any]], dip_pct: float) -> EntrySignal | None:
    """
    Dip buy (mean reversion): last close <= max close of prev hour * (1 - dip_pct).
    This triggers more often in volatile markets; use with strict trailing stop.
    """
    if len(candles) < 13:
        return None
    last = float(candles[-1]["close"])
    prev = [float(c["close"]) for c in candles[-13:-1]]
    hi = max(prev)
    if hi <= 0:
        return None
    if last <= hi * (1.0 - float(dip_pct)):
        return EntrySignal(
            kind="dip",
            symbol=symbol,
            last_price=last,
            reason=f"dip: last {last:.8g} <= hi_1h {hi:.8g} * (1-{dip_pct*100:.2f}%)",
        )
    return None


def fmt_pct(x: float) -> str:
    return f"{x * 100:.2f}%"

