import logging
import time
import pandas as pd
import numpy as np
from .database import Position, Trade, AuditLog, get_total_exposure, db

logger = logging.getLogger(__name__)

class ExchangeClient:
    """
    Real exchange integration via ccxt.

    Supports:
    - real-time-ish prices via fetch_ticker (polling)
    - OHLCV for indicators via fetch_ohlcv
    - market orders (optional) via create_market_buy/sell_order
    """

    def __init__(self, exchange_id: str, api_key: str | None, api_secret: str | None, *, sandbox: bool):
        try:
            import ccxt  # type: ignore
        except Exception as e:
            raise RuntimeError("Missing dependency 'ccxt'. Install requirements.txt") from e

        if not exchange_id:
            raise ValueError("exchange_id is required")

        exchange_cls = getattr(ccxt, exchange_id, None)
        if exchange_cls is None:
            raise ValueError(f"Unsupported exchange id '{exchange_id}' for ccxt")

        opts: dict = {"enableRateLimit": True}
        if api_key:
            opts["apiKey"] = api_key
        if api_secret:
            opts["secret"] = api_secret

        self.exchange = exchange_cls(opts)

        # Many exchanges support sandbox; if not, we just ignore.
        if sandbox and hasattr(self.exchange, "set_sandbox_mode"):
            try:
                self.exchange.set_sandbox_mode(True)
            except Exception as e:
                logger.warning("Sandbox requested but not supported/failed: %s", e)

    def get_ticker_price(self, symbol: str) -> float | None:
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            last = ticker.get("last")
            return float(last) if last is not None else None
        except Exception as e:
            logger.error("Failed fetching ticker for %s: %s", symbol, e)
            return None

    def fetch_ohlcv_df(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame | None:
        try:
            candles = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            if not candles:
                return None
            df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume"])
            df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
            return df
        except Exception as e:
            logger.error("Failed fetching OHLCV for %s: %s", symbol, e)
            return None

    def place_market_order(self, symbol: str, side: str, amount: float) -> dict | None:
        try:
            side_up = side.upper()
            if side_up == "BUY":
                return self.exchange.create_market_buy_order(symbol, amount)
            if side_up == "SELL":
                return self.exchange.create_market_sell_order(symbol, amount)
            raise ValueError("side must be BUY or SELL")
        except Exception as e:
            logger.error("Order failed %s %s amount=%s: %s", side, symbol, amount, e)
            return None

class TradingEngine:
    def __init__(self, config_manager):
        self.config = config_manager
        self.client: ExchangeClient | None = None
        self.is_running = False
        self.max_capital = 100.0
        self.last_price: float | None = None
        self.last_price_ts: str | None = None
        
    def initialize(self):
        exchange_id = self.config.get("exchange_id", "kraken")
        api_key = self.config.get("exchange_api_key")
        api_secret = self.config.get("exchange_api_secret")
        sandbox = bool(self.config.get("sandbox_mode", False))
        self.client = ExchangeClient(exchange_id, api_key, api_secret, sandbox=sandbox)
        self.max_capital = self.config.get("max_capital", 100.0)
        logger.info("Trading Engine Initialized. Exchange=%s sandbox=%s", exchange_id, sandbox)

    def check_exposure_limit(self, potential_cost):
        current_exposure = get_total_exposure()
        if current_exposure + potential_cost > self.max_capital:
            logger.warning(f"Trade blocked! Exposure {current_exposure} + {potential_cost} > {self.max_capital}")
            return False
        return True

    def _pct_change(self, closes: pd.Series, lookback_bars: int) -> float | None:
        if closes is None or len(closes) < lookback_bars + 1:
            return None
        last = float(closes.iloc[-1])
        prev = float(closes.iloc[-(lookback_bars + 1)])
        if prev == 0:
            return None
        return ((last - prev) / prev) * 100.0

    def analyze_market(self, symbol: str, *, has_open_position: bool):
        """
        Short-term momentum:
        - BUY when price rises fast over a short window
        - SELL when price starts falling OR breaks trailing stop from recent peak
        """
        if not self.client:
            return "HOLD"

        timeframe = self.config.get("timeframe", "1m")
        limit = int(self.config.get("ohlcv_limit", 200))
        df = self.client.fetch_ohlcv_df(symbol, timeframe=timeframe, limit=limit)
        if df is None or df.empty:
            return "HOLD"

        closes = df["close"].dropna()
        lookback = int(self.config.get("crypto_lookback_bars", 5))
        change_pct = self._pct_change(closes, lookback_bars=lookback)
        if change_pct is None:
            return "HOLD"

        rise_th = float(self.config.get("crypto_rise_threshold_pct", 0.25))
        fall_th = float(self.config.get("crypto_fall_threshold_pct", 0.25))

        # If we don't have a position, only consider BUY.
        if not has_open_position:
            if change_pct >= rise_th:
                return "BUY"
            return "HOLD"

        # If we have a position, only consider SELL.
        if change_pct <= -abs(fall_th):
            return "SELL"

        trailing_window = int(self.config.get("crypto_trailing_window_bars", 30))
        trailing_stop_pct = float(self.config.get("crypto_trailing_stop_pct", 0.30))
        if len(closes) >= trailing_window:
            window = closes.iloc[-trailing_window:]
            peak = float(window.max())
            last = float(window.iloc[-1])
            if peak > 0:
                drawdown_pct = ((peak - last) / peak) * 100.0
                if drawdown_pct >= abs(trailing_stop_pct):
                    return "SELL"

        return "HOLD"

    def execute_trade_cycle(self):
        if not self.client:
            return "Not initialized"
        
        symbol = self.config.get("symbol", "BTC/USDT")
        
        # Get price first (fresh market data)
        price = self.client.get_ticker_price(symbol)
        
        if not price:
            return "Error fetching price (Check logs)"

        self.last_price = float(price)
        self.last_price_ts = pd.Timestamp.utcnow().isoformat()

        open_positions = Position.select().where(Position.symbol == symbol, Position.is_open == True)
        has_open_position = open_positions.exists()

        signal = self.analyze_market(symbol, has_open_position=has_open_position)

        if signal == "BUY":
            if has_open_position:
                return "No action"
            # Buy logic
            amount_to_invest = float(self.config.get("bet_usd", 20.0))  # Fixed bet size in quote currency
            quantity = amount_to_invest / price
            
            if self.check_exposure_limit(amount_to_invest):
                execution_mode = self.config.get("execution_mode", "paper")  # paper | live
                order = None
                if execution_mode == "live":
                    order = self.client.place_market_order(symbol, "BUY", float(quantity))

                if execution_mode == "paper" or order:
                    Trade.create(
                        symbol=symbol,
                        side="BUY",
                        quantity=quantity,
                        price=price,
                        cost=amount_to_invest
                    )
                    Position.create(
                        symbol=symbol,
                        quantity=quantity,
                        average_entry_price=price
                    )
                    AuditLog.create(
                        action="BUY",
                        details=f"{execution_mode.upper()} BUY {quantity:.8f} {symbol} @ {price}",
                        capital_exposure=get_total_exposure()
                    )
                    return f"{execution_mode.upper()} BUY {quantity:.8f} {symbol}"
                return "Buy failed (API Error)"
            else:
                return "Buy blocked by capital limit"

        elif signal == "SELL":
            # Sell logic - sell all open positions
            positions = open_positions
            total_qty = sum([p.quantity for p in positions])
            
            if total_qty > 0:
                execution_mode = self.config.get("execution_mode", "paper")
                order = None
                if execution_mode == "live":
                    order = self.client.place_market_order(symbol, "SELL", float(total_qty))

                if execution_mode == "paper" or order:
                    Trade.create(
                        symbol=symbol,
                        side="SELL",
                        quantity=total_qty,
                        price=price,
                        cost=total_qty * price # Not really cost, but value
                    )
                    # Close positions
                    for p in positions:
                        p.is_open = False
                        p.save()
                        
                    AuditLog.create(
                        action="SELL",
                        details=f"{execution_mode.upper()} SELL {total_qty:.8f} {symbol} @ {price}",
                        capital_exposure=get_total_exposure()
                    )
                    return f"{execution_mode.upper()} SELL {total_qty:.8f} {symbol}"
                return "Sell failed (API Error)"
        
        return "No action"

    def emergency_stop(self):
        """
        Stops trading and optionally closes positions.
        """
        self.is_running = False
        # Logic to close all positions could go here if configured
        return "Trading stopped."
