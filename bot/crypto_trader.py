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

    def _rsi(self, closes: pd.Series, period: int = 14) -> float | None:
        if closes is None or len(closes) < period + 2:
            return None

        delta = closes.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta.where(delta < 0, 0.0))

        # Wilder's smoothing (EMA with alpha=1/period) is common for RSI;
        # ewm gives stable results and avoids the "all nan" early window issue.
        avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        val = rsi.iloc[-1]
        return float(val) if pd.notna(val) else None

    def analyze_market(self, symbol: str):
        """
        RSI-based strategy using real OHLCV data from the exchange.
        """
        if not self.client:
            return "HOLD", None

        timeframe = self.config.get("timeframe", "1m")
        limit = int(self.config.get("ohlcv_limit", 200))
        df = self.client.fetch_ohlcv_df(symbol, timeframe=timeframe, limit=limit)
        if df is None or df.empty:
            return "HOLD", None

        rsi = self._rsi(df["close"], period=int(self.config.get("rsi_period", 14)))
        if rsi is None:
            return "HOLD", None

        buy_th = float(self.config.get("rsi_buy_threshold", 30.0))
        sell_th = float(self.config.get("rsi_sell_threshold", 70.0))

        if rsi <= buy_th:
            return "BUY"
        if rsi >= sell_th:
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
            
        signal = self.analyze_market(symbol)

        if signal == "BUY":
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
            positions = Position.select().where(Position.symbol == symbol, Position.is_open == True)
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
