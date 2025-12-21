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
                    realized_pnl REAL
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
        allowed = {"base_currency", "starting_capital", "risk_mode", "paused"}
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
                SET base_currency=?, starting_capital=?, risk_mode=?, paused=?
                WHERE id=1
                """,
                (
                    DEFAULT_SETTINGS["base_currency"],
                    DEFAULT_SETTINGS["starting_capital"],
                    DEFAULT_SETTINGS["risk_mode"],
                    DEFAULT_SETTINGS["paused"],
                ),
            )

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

    def add_buy(self, symbol: str, amount_base: float, price: float) -> None:
        symbol = symbol.upper()
        qty = amount_base / price
        ts_utc = self._now_utc_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trades (ts_utc, side, symbol, amount_base, price, qty, realized_pnl)
                VALUES (?, 'BUY', ?, ?, ?, ?, NULL)
                """,
                (ts_utc, symbol, amount_base, price, qty),
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

    def add_sell(self, symbol: str, amount_base: float, price: float) -> float:
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
                INSERT INTO trades (ts_utc, side, symbol, amount_base, price, qty, realized_pnl)
                VALUES (?, 'SELL', ?, ?, ?, ?, ?)
                """,
                (ts_utc, symbol, amount_base, price, qty, realized),
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
                )
                for r in rows
            ]

