from __future__ import annotations

from dataclasses import dataclass

from bot.storage import Position, Storage


@dataclass(frozen=True)
class AutoTradeDecision:
    action: str  # "BUY" | "SELL" | "SKIP"
    symbol: str
    quote_amount: float | None = None
    reason: str | None = None


def symbol_quote(symbol: str) -> str:
    parts = symbol.split("-")
    return parts[-1].upper() if len(parts) >= 2 else ""


def total_open_notional(store_positions: list[Position], quote: str) -> float:
    """
    Estimate open notional using avg_entry * qty, filtered by quote currency.
    """
    q = quote.upper()
    tot = 0.0
    for p in store_positions:
        if symbol_quote(p.symbol) != q:
            continue
        tot += float(p.avg_entry) * float(p.qty)
    return tot


def decide_autobuy(
    store: Storage,
    symbol: str,
    last_price: float,
    quote_cap_total: float,
    quote_currency: str,
    min_trade_quote: float,
) -> AutoTradeDecision:
    """
    Simple risk rule:
    - only 1 open position per symbol
    - total open notional across quote currency <= quote_cap_total
    - buy with remaining budget (>= min_trade_quote)
    """
    positions = store.list_positions()
    if any(p.symbol.upper() == symbol.upper() for p in positions):
        return AutoTradeDecision(action="SKIP", symbol=symbol, reason="position already open")

    open_notional = total_open_notional(positions, quote_currency)
    remaining = max(0.0, float(quote_cap_total) - open_notional)
    if remaining < float(min_trade_quote):
        return AutoTradeDecision(action="SKIP", symbol=symbol, reason="cap reached / remaining too small")

    # Spend remaining (hard cap total = 100 USDT by default)
    return AutoTradeDecision(action="BUY", symbol=symbol, quote_amount=remaining)


def decide_autosell_all(symbol: str, reason: str) -> AutoTradeDecision:
    return AutoTradeDecision(action="SELL", symbol=symbol, quote_amount=None, reason=reason)

