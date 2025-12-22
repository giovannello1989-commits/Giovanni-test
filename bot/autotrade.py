from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from bot.marketdata import MarketDataClient
from bot.storage import Storage


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AutoTradeConfig:
    enabled: bool
    mode: str  # "paper" or "live"
    max_quote: float  # e.g. 100.0
    quote_currency: str  # e.g. USDT


@dataclass(frozen=True)
class ExecResult:
    ok: bool
    order_id: str | None
    fill_price: float | None
    error: str | None


@dataclass(frozen=True)
class AutoTradeDecision:
    action: str  # "BUY" | "SELL" | "SKIP"
    symbol: str
    quote_amount: float | None = None
    reason: str | None = None


def symbol_quote(symbol: str) -> str:
    parts = symbol.split("-")
    return parts[-1].upper() if len(parts) >= 2 else ""


def total_open_notional(store: Storage, quote: str) -> float:
    """
    Estimate open notional using avg_entry * qty, filtered by quote currency.
    """
    q = quote.upper()
    tot = 0.0
    for p in store.list_positions():
        if symbol_quote(p.symbol) != q:
            continue
        tot += float(p.avg_entry) * float(p.qty)
    return tot


def decide_autobuy(
    store: Storage,
    symbol: str,
    quote_cap_total: float,
    quote_currency: str,
    min_trade_quote: float = 10.0,
) -> AutoTradeDecision:
    """
    Risk rule:
    - only 1 open position per symbol
    - total open notional across quote currency <= quote_cap_total
    - buy with remaining budget (>= min_trade_quote)
    """
    positions = store.list_positions()
    if any(p.symbol.upper() == symbol.upper() for p in positions):
        return AutoTradeDecision(action="SKIP", symbol=symbol, reason="position already open (same symbol)")

    # Enforce single active position per quote currency (simple & safer).
    if any(symbol_quote(p.symbol) == quote_currency.upper() for p in positions):
        return AutoTradeDecision(action="SKIP", symbol=symbol, reason="another position already open (single-position mode)")

    open_notional = total_open_notional(store, quote_currency)
    remaining = max(0.0, float(quote_cap_total) - open_notional)
    if remaining < float(min_trade_quote):
        return AutoTradeDecision(action="SKIP", symbol=symbol, reason="cap reached / remaining too small")

    return AutoTradeDecision(action="BUY", symbol=symbol, quote_amount=remaining, reason="buy (cap enforcement)")


def decide_autosell_all(symbol: str, reason: str) -> AutoTradeDecision:
    return AutoTradeDecision(action="SELL", symbol=symbol, quote_amount=None, reason=reason)


class PaperExecutor:
    """
    Simulated execution: uses last market price and records trades/positions in DB.
    amount_base in our DB is treated as "quote spent/received" (e.g. USDT).
    """

    def __init__(self, md: MarketDataClient, store: Storage, fee_bps: float = 10.0) -> None:
        self.md = md
        self.store = store
        self.fee_bps = fee_bps  # 10 bps = 0.10%

    def buy_quote(self, symbol: str, quote_amount: float) -> ExecResult:
        px = self.md.get_last_price(symbol)
        if px is None:
            return ExecResult(False, None, None, "no last price")
        fee = quote_amount * (self.fee_bps / 10000.0)
        spent = max(0.0, quote_amount - fee)
        oid = f"paper-{uuid.uuid4().hex[:12]}"
        self.store.add_buy(symbol=symbol, amount_base=spent, price=px, source="autotrade-paper", order_id=oid)
        return ExecResult(True, oid, px, None)

    def sell_all(self, symbol: str) -> ExecResult:
        px = self.md.get_last_price(symbol)
        if px is None:
            return ExecResult(False, None, None, "no last price")
        positions = self.store.list_positions()
        pos = next((p for p in positions if p.symbol.upper() == symbol.upper()), None)
        if pos is None or pos.qty <= 0:
            return ExecResult(False, None, None, "no position")
        quote_amount = pos.qty * px
        fee = quote_amount * (self.fee_bps / 10000.0)
        received = max(0.0, quote_amount - fee)
        oid = f"paper-{uuid.uuid4().hex[:12]}"
        self.store.add_sell(symbol=symbol, amount_base=received, price=px, source="autotrade-paper", order_id=oid)
        return ExecResult(True, oid, px, None)


class LiveRevolutXExecutor:
    """
    Live execution via Revolut X trading API.
    Requires Revolut X endpoints/auth to be correctly configured.

    WARNING: This is a best-effort generic implementation. You must adapt the payload/fields
    to match Revolut X official docs before enabling live trading.
    """

    def __init__(self, rx_client, store: Storage, md: MarketDataClient | None = None) -> None:
        self.rx = rx_client
        self.store = store
        self.md = md

    def buy_quote(self, symbol: str, quote_amount: float) -> ExecResult:
        client_oid = f"auto-{uuid.uuid4().hex[:12]}"
        data = self.rx.place_order(
            symbol=symbol,
            side="BUY",
            order_type="MARKET",
            quote_amount=quote_amount,
            client_order_id=client_oid,
        )
        if not data:
            return ExecResult(False, None, None, "place_order returned null (check endpoint/payload/auth)")
        order_id = None
        for k in ("orderId", "id", "order_id"):
            if isinstance(data, dict) and data.get(k):
                order_id = str(data[k])
                break
        px = None
        if self.md:
            px = self.md.get_last_price(symbol)
        if px is None:
            px = self.rx.get_last_price(symbol)
        if px is not None:
            self.store.add_buy(
                symbol=symbol,
                amount_base=quote_amount,
                price=float(px),
                source="autotrade-live",
                order_id=order_id or client_oid,
            )
        return ExecResult(True, order_id or client_oid, px, None)

    def sell_all(self, symbol: str) -> ExecResult:
        positions = self.store.list_positions()
        pos = next((p for p in positions if p.symbol.upper() == symbol.upper()), None)
        if pos is None or pos.qty <= 0:
            return ExecResult(False, None, None, "no position")

        client_oid = f"auto-{uuid.uuid4().hex[:12]}"
        data = self.rx.place_order(
            symbol=symbol,
            side="SELL",
            order_type="MARKET",
            base_amount=float(pos.qty),
            client_order_id=client_oid,
        )
        if not data:
            return ExecResult(False, None, None, "place_order returned null (check endpoint/payload/auth)")
        order_id = None
        for k in ("orderId", "id", "order_id"):
            if isinstance(data, dict) and data.get(k):
                order_id = str(data[k])
                break
        px = None
        if self.md:
            px = self.md.get_last_price(symbol)
        if px is None:
            px = self.rx.get_last_price(symbol)
        if px is not None:
            self.store.add_sell(
                symbol=symbol,
                amount_base=float(pos.qty) * float(px),
                price=float(px),
                source="autotrade-live",
                order_id=order_id or client_oid,
            )
        return ExecResult(True, order_id or client_oid, px, None)
