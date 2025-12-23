from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

import json



DEFAULT_SETTINGS = {
    "base_currency": "EUR",
    "starting_capital": 0.0,
    "risk_mode": "aggressive",
    "paused": 0,
    "scan_interval_seconds": 60,
    "pairs_limit": 50,
    "hard_close_minute": 55,
    "revolutx_base_url": "",
    "revolutx_base_path": "",
    "owner_chat_id": None,
    # Operating mode: "session" (09-20) or "always" (24/7)
    "mode": "session",
    # Auto-trading (OFF by default)
    "autotrade_enabled": 0,
    # "paper" (simulated) or "live" (real orders)
    "autotrade_mode": "paper",
    # Hard cap in quote currency (e.g., 100 USDT)
    "autotrade_max_quote": 100.0,
    "autotrade_quote_currency": "USDT",
    "autotrade_max_positions": 3,
    # How to interpret autotrade_max_quote:
    # - fixed: hard cap (default)
    # - balance: min(cap, available balance)
    # - compound: cap + realized profits (still capped by available balance in live mode)
    "autotrade_cap_mode": "fixed",
    # Market data (signals)
    "market_data_provider": "binance",
    "market_data_quote": "USDT",
    # Internal: if 0, /start will apply bootstrap defaults
    "bootstrapped": 0,
    # Entry strategy (controls how often we enter)
    # - momentum: current logic
    # - breakout: 1h high breakout
    # - dip: mean-reversion dip buy
    "entry_strategy": "momentum",
    "breakout_pct": 0.015,
    "dip_pct": 0.03,
}


@dataclass(frozen=True)
class Trade:
    id: int
    ts_utc: str
    side: str
    symbol: str
    amount_base: float
    price: float
    qty: float
    realized_pnl: float | None
    source: str | None
    order_id: str | None


@dataclass(frozen=True)
class Position:
    symbol: str
    qty: float
    avg_entry: float
    peak_price: float
    opened_ts_utc: str


class Storage:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    base_currency TEXT NOT NULL,
                    starting_capital REAL NOT NULL,
                    risk_mode TEXT NOT NULL,
                    paused INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_utc TEXT NOT NULL,
                    side TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    amount_base REAL NOT NULL,
                    price REAL NOT NULL,
                    qty REAL NOT NULL,
                    realized_pnl REAL,
                    source TEXT,
                    order_id TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS positions (
                    symbol TEXT PRIMARY KEY,
                    qty REAL NOT NULL,
                    avg_entry REAL NOT NULL,
                    peak_price REAL NOT NULL,
                    opened_ts_utc TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS onboarding (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    step TEXT,
                    data_json TEXT
                )
                """
            )
            # Ensure singleton settings row exists
            row = conn.execute("SELECT id FROM settings WHERE id=1").fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO settings (id, base_currency, starting_capital, risk_mode, paused)
                    VALUES (1, ?, ?, ?, ?)
                    """,
                    (
                        DEFAULT_SETTINGS["base_currency"],
                        DEFAULT_SETTINGS["starting_capital"],
                        DEFAULT_SETTINGS["risk_mode"],
                        DEFAULT_SETTINGS["paused"],
                    ),
                )
            # Lightweight migration for new columns
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(settings)").fetchall()]
            def _ensure_col(name: str, ddl: str, default_val):
                if name in cols:
                    return
                conn.execute(f"ALTER TABLE settings ADD COLUMN {ddl}")
                conn.execute(f"UPDATE settings SET {name}=? WHERE id=1", (default_val,))

            _ensure_col("scan_interval_seconds", "scan_interval_seconds INTEGER NOT NULL DEFAULT 60", DEFAULT_SETTINGS["scan_interval_seconds"])
            _ensure_col("pairs_limit", "pairs_limit INTEGER NOT NULL DEFAULT 50", DEFAULT_SETTINGS["pairs_limit"])
            _ensure_col("hard_close_minute", "hard_close_minute INTEGER NOT NULL DEFAULT 55", DEFAULT_SETTINGS["hard_close_minute"])
            _ensure_col("revolutx_base_url", "revolutx_base_url TEXT NOT NULL DEFAULT ''", DEFAULT_SETTINGS["revolutx_base_url"])
            _ensure_col("revolutx_base_path", "revolutx_base_path TEXT NOT NULL DEFAULT ''", DEFAULT_SETTINGS["revolutx_base_path"])
            # Nullable owner chat id (single-user binding)
            if "owner_chat_id" not in cols:
                conn.execute("ALTER TABLE settings ADD COLUMN owner_chat_id INTEGER")
            # Autotrade / mode
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(settings)").fetchall()]
            _ensure_col("mode", "mode TEXT NOT NULL DEFAULT 'session'", DEFAULT_SETTINGS["mode"])
            _ensure_col("autotrade_enabled", "autotrade_enabled INTEGER NOT NULL DEFAULT 0", DEFAULT_SETTINGS["autotrade_enabled"])
            _ensure_col("autotrade_mode", "autotrade_mode TEXT NOT NULL DEFAULT 'paper'", DEFAULT_SETTINGS["autotrade_mode"])
            _ensure_col("autotrade_max_quote", "autotrade_max_quote REAL NOT NULL DEFAULT 100.0", DEFAULT_SETTINGS["autotrade_max_quote"])
            _ensure_col("autotrade_quote_currency", "autotrade_quote_currency TEXT NOT NULL DEFAULT 'USDT'", DEFAULT_SETTINGS["autotrade_quote_currency"])
            _ensure_col("autotrade_max_positions", "autotrade_max_positions INTEGER NOT NULL DEFAULT 3", DEFAULT_SETTINGS["autotrade_max_positions"])
            _ensure_col("autotrade_cap_mode", "autotrade_cap_mode TEXT NOT NULL DEFAULT 'fixed'", DEFAULT_SETTINGS["autotrade_cap_mode"])
            _ensure_col("market_data_provider", "market_data_provider TEXT NOT NULL DEFAULT 'binance'", DEFAULT_SETTINGS["market_data_provider"])
            _ensure_col("market_data_quote", "market_data_quote TEXT NOT NULL DEFAULT 'USDT'", DEFAULT_SETTINGS["market_data_quote"])
            _ensure_col("bootstrapped", "bootstrapped INTEGER NOT NULL DEFAULT 0", DEFAULT_SETTINGS["bootstrapped"])
            _ensure_col("entry_strategy", "entry_strategy TEXT NOT NULL DEFAULT 'momentum'", DEFAULT_SETTINGS["entry_strategy"])
            _ensure_col("breakout_pct", "breakout_pct REAL NOT NULL DEFAULT 0.015", DEFAULT_SETTINGS["breakout_pct"])
            _ensure_col("dip_pct", "dip_pct REAL NOT NULL DEFAULT 0.03", DEFAULT_SETTINGS["dip_pct"])

            # Trades table migration for new columns
            trade_cols = [r["name"] for r in conn.execute("PRAGMA table_info(trades)").fetchall()]
            if "source" not in trade_cols:
                conn.execute("ALTER TABLE trades ADD COLUMN source TEXT")
            if "order_id" not in trade_cols:
                conn.execute("ALTER TABLE trades ADD COLUMN order_id TEXT")
            row2 = conn.execute("SELECT id FROM onboarding WHERE id=1").fetchone()
            if row2 is None:
                conn.execute(
                    "INSERT INTO onboarding (id, step, data_json) VALUES (1, NULL, NULL)"
                )

    def get_settings(self) -> dict:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM settings WHERE id=1").fetchone()
            if row is None:
                return dict(DEFAULT_SETTINGS)
            return dict(row)

    def update_settings(self, **kwargs) -> None:
        allowed = {
            "base_currency",
            "starting_capital",
            "risk_mode",
            "paused",
            "scan_interval_seconds",
            "pairs_limit",
            "hard_close_minute",
            "revolutx_base_url",
            "revolutx_base_path",
            "owner_chat_id",
            "mode",
            "autotrade_enabled",
            "autotrade_mode",
            "autotrade_max_quote",
            "autotrade_quote_currency",
            "autotrade_max_positions",
            "autotrade_cap_mode",
            "market_data_provider",
            "market_data_quote",
            "bootstrapped",
            "entry_strategy",
            "breakout_pct",
            "dip_pct",
        }
        fields = [(k, v) for k, v in kwargs.items() if k in allowed]
        if not fields:
            return
        set_expr = ", ".join([f"{k}=?" for k, _ in fields])
        values = [v for _, v in fields]
        with self._connect() as conn:
            conn.execute(f"UPDATE settings SET {set_expr} WHERE id=1", values)

    def reset_all(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM trades")
            conn.execute("DELETE FROM positions")
            conn.execute("UPDATE onboarding SET step=NULL, data_json=NULL WHERE id=1")
            conn.execute(
                """
                UPDATE settings
                SET base_currency=?, starting_capital=?, risk_mode=?, paused=?,
                    scan_interval_seconds=?, pairs_limit=?, hard_close_minute=?,
                    revolutx_base_url=?, revolutx_base_path=?,
                    owner_chat_id=NULL,
                    mode=?,
                    autotrade_enabled=?,
                    autotrade_mode=?,
                    autotrade_max_quote=?,
                    autotrade_quote_currency=?,
                    autotrade_max_positions=?,
                    autotrade_cap_mode=?,
                    market_data_provider=?,
                    market_data_quote=?,
                    bootstrapped=?,
                    entry_strategy=?,
                    breakout_pct=?,
                    dip_pct=?
                WHERE id=1
                """,
                (
                    DEFAULT_SETTINGS["base_currency"],
                    DEFAULT_SETTINGS["starting_capital"],
                    DEFAULT_SETTINGS["risk_mode"],
                    DEFAULT_SETTINGS["paused"],
                    DEFAULT_SETTINGS["scan_interval_seconds"],
                    DEFAULT_SETTINGS["pairs_limit"],
                    DEFAULT_SETTINGS["hard_close_minute"],
                    DEFAULT_SETTINGS["revolutx_base_url"],
                    DEFAULT_SETTINGS["revolutx_base_path"],
                    DEFAULT_SETTINGS["mode"],
                    DEFAULT_SETTINGS["autotrade_enabled"],
                    DEFAULT_SETTINGS["autotrade_mode"],
                    DEFAULT_SETTINGS["autotrade_max_quote"],
                    DEFAULT_SETTINGS["autotrade_quote_currency"],
                    DEFAULT_SETTINGS["autotrade_max_positions"],
                    DEFAULT_SETTINGS["autotrade_cap_mode"],
                    DEFAULT_SETTINGS["market_data_provider"],
                    DEFAULT_SETTINGS["market_data_quote"],
                    DEFAULT_SETTINGS["bootstrapped"],
                    DEFAULT_SETTINGS["entry_strategy"],
                    DEFAULT_SETTINGS["breakout_pct"],
                    DEFAULT_SETTINGS["dip_pct"],
                ),
            )

    def sum_realized_pnl_for_quote(self, quote_currency: str) -> float:
        """
        Sum realized PnL for SELL trades for symbols with the given quote currency.
        Best-effort (relies on symbol format BASE-QUOTE).
        """
        q = (quote_currency or "").upper().strip()
        if not q:
            return 0.0
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(realized_pnl), 0.0) AS s
                FROM trades
                WHERE side='SELL'
                  AND realized_pnl IS NOT NULL
                  AND UPPER(symbol) LIKE ?
                """,
                (f"%-{q}",),
            ).fetchone()
            try:
                return float(row["s"]) if row is not None else 0.0
            except Exception:
                return 0.0

    # --- Onboarding (setup wizard) ---
    def get_onboarding(self) -> dict:
        with self._connect() as conn:
            row = conn.execute("SELECT step, data_json FROM onboarding WHERE id=1").fetchone()
            if row is None:
                return {"step": None, "data": {}}
            data = {}
            if row["data_json"]:
                try:
                    data = json.loads(row["data_json"])
                except Exception:
                    data = {}
            return {"step": row["step"], "data": data}

    def set_onboarding(self, step: str | None, data: dict) -> None:
        payload = json.dumps(data, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                "UPDATE onboarding SET step=?, data_json=? WHERE id=1",
                (step, payload),
            )

    def clear_onboarding(self) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE onboarding SET step=NULL, data_json=NULL WHERE id=1")

    # --- Trades / Positions ---
    def _now_utc_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def add_buy(self, symbol: str, amount_base: float, price: float, source: str = "manual", order_id: str | None = None) -> None:
        symbol = symbol.upper()
        qty = amount_base / price
        ts_utc = self._now_utc_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trades (ts_utc, side, symbol, amount_base, price, qty, realized_pnl, source, order_id)
                VALUES (?, 'BUY', ?, ?, ?, ?, NULL, ?, ?)
                """,
                (ts_utc, symbol, amount_base, price, qty, source, order_id),
            )
            pos = conn.execute("SELECT * FROM positions WHERE symbol=?", (symbol,)).fetchone()
            if pos is None:
                conn.execute(
                    """
                    INSERT INTO positions (symbol, qty, avg_entry, peak_price, opened_ts_utc)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (symbol, qty, price, price, ts_utc),
                )
            else:
                old_qty = float(pos["qty"])
                old_avg = float(pos["avg_entry"])
                new_qty = old_qty + qty
                new_avg = ((old_qty * old_avg) + (qty * price)) / new_qty
                peak_price = max(float(pos["peak_price"]), price)
                conn.execute(
                    """
                    UPDATE positions
                    SET qty=?, avg_entry=?, peak_price=?
                    WHERE symbol=?
                    """,
                    (new_qty, new_avg, peak_price, symbol),
                )

    def add_sell(self, symbol: str, amount_base: float, price: float, source: str = "manual", order_id: str | None = None) -> float:
        """
        Returns realized PnL for this sell (base currency).
        If the position doesn't exist, PnL is computed vs 0 avg_entry (still recorded).
        """
        symbol = symbol.upper()
        qty = amount_base / price
        ts_utc = self._now_utc_iso()
        with self._connect() as conn:
            pos = conn.execute("SELECT * FROM positions WHERE symbol=?", (symbol,)).fetchone()
            avg_entry = float(pos["avg_entry"]) if pos is not None else 0.0
            realized = amount_base - (qty * avg_entry)
            conn.execute(
                """
                INSERT INTO trades (ts_utc, side, symbol, amount_base, price, qty, realized_pnl, source, order_id)
                VALUES (?, 'SELL', ?, ?, ?, ?, ?, ?, ?)
                """,
                (ts_utc, symbol, amount_base, price, qty, realized, source, order_id),
            )

            if pos is None:
                return realized

            old_qty = float(pos["qty"])
            new_qty = old_qty - qty
            if new_qty <= 1e-12:
                conn.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
            else:
                # avg_entry stays the same in average-cost model
                conn.execute(
                    """
                    UPDATE positions
                    SET qty=?
                    WHERE symbol=?
                    """,
                    (new_qty, symbol),
                )
            return realized

    def list_positions(self) -> list[Position]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM positions ORDER BY symbol ASC").fetchall()
            return [
                Position(
                    symbol=r["symbol"],
                    qty=float(r["qty"]),
                    avg_entry=float(r["avg_entry"]),
                    peak_price=float(r["peak_price"]),
                    opened_ts_utc=r["opened_ts_utc"],
                )
                for r in rows
            ]

    def update_peak(self, symbol: str, peak_price: float) -> None:
        symbol = symbol.upper()
        with self._connect() as conn:
            conn.execute(
                "UPDATE positions SET peak_price=? WHERE symbol=?",
                (peak_price, symbol),
            )

    def list_trades_since_utc(self, since_utc_iso: str) -> list[Trade]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM trades
                WHERE ts_utc >= ?
                ORDER BY ts_utc ASC
                """,
                (since_utc_iso,),
            ).fetchall()
            return [
                Trade(
                    id=int(r["id"]),
                    ts_utc=r["ts_utc"],
                    side=r["side"],
                    symbol=r["symbol"],
                    amount_base=float(r["amount_base"]),
                    price=float(r["price"]),
                    qty=float(r["qty"]),
                    realized_pnl=float(r["realized_pnl"]) if r["realized_pnl"] is not None else None,
                    source=r["source"] if "source" in r.keys() else None,
                    order_id=r["order_id"] if "order_id" in r.keys() else None,
                )
                for r in rows
            ]

    def list_all_trades(self) -> list[Trade]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM trades ORDER BY ts_utc ASC").fetchall()
            return [
                Trade(
                    id=int(r["id"]),
                    ts_utc=r["ts_utc"],
                    side=r["side"],
                    symbol=r["symbol"],
                    amount_base=float(r["amount_base"]),
                    price=float(r["price"]),
                    qty=float(r["qty"]),
                    realized_pnl=float(r["realized_pnl"]) if r["realized_pnl"] is not None else None,
                    source=r["source"] if "source" in r.keys() else None,
                    order_id=r["order_id"] if "order_id" in r.keys() else None,
                )
                for r in rows
            ]

