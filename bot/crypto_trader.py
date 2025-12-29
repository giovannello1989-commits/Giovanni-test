import logging
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from .database import Position, Trade, AuditLog, get_total_exposure, db

logger = logging.getLogger(__name__)

class RevolutXClient:
    def __init__(self, api_key, secret_key, test_mode=True):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = "https://exchange.revolut.com/api/v1" if not test_mode else "https://sandbox-exchange.revolut.com/api/v1"
        self.test_mode = test_mode
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        })

    def get_price(self, pair="BTC-USD"):
        if self.test_mode:
            # Mock price
            import random
            base = 40000 if "BTC" in pair else 2000
            return base * (1 + random.uniform(-0.01, 0.01))
        
        try:
            # Hypothetical endpoint
            resp = self.session.get(f"{self.base_url}/ticker?symbol={pair}")
            if resp.status_code == 200:
                data = resp.json()
                return float(data['last'])
            return None
        except Exception as e:
            logger.error(f"Error fetching price: {e}")
            return None

    def place_order(self, pair, side, quantity):
        """
        side: 'BUY' or 'SELL'
        """
        logger.info(f"Placing {side} order for {quantity} {pair}")
        if self.test_mode:
            return {
                "id": f"mock_{int(time.time())}",
                "status": "filled",
                "price": self.get_price(pair),
                "quantity": quantity,
                "side": side
            }
        
        # Real implementation would go here
        payload = {
            "symbol": pair,
            "side": side.lower(),
            "type": "market",
            "quantity": quantity
        }
        try:
            resp = self.session.post(f"{self.base_url}/order", json=payload)
            return resp.json()
        except Exception as e:
            logger.error(f"Order failed: {e}")
            return None

class TradingEngine:
    def __init__(self, config_manager):
        self.config = config_manager
        self.client = None
        self.is_running = False
        self.max_capital = 100.0
        
    def initialize(self):
        api_key = self.config.get("revolut_api_key")
        test_mode = self.config.get("trading_style") == "test_mode"
        self.client = RevolutXClient(api_key, "", test_mode=test_mode)
        self.max_capital = self.config.get("max_capital", 100.0)
        logger.info(f"Trading Engine Initialized. Test Mode: {test_mode}")

    def check_exposure_limit(self, potential_cost):
        current_exposure = get_total_exposure()
        if current_exposure + potential_cost > self.max_capital:
            logger.warning(f"Trade blocked! Exposure {current_exposure} + {potential_cost} > {self.max_capital}")
            return False
        return True

    def analyze_market(self):
        """
        Simple momentum strategy.
        In a real app, this would fetch historical candles and calculate RSI/MACD.
        """
        # For this MVP, we simulate a signal
        import random
        dice = random.random()
        if dice > 0.8:
            return "BUY"
        elif dice < 0.2:
            return "SELL"
        return "HOLD"

    def execute_trade_cycle(self):
        if not self.client:
            return "Not initialized"
        
        symbol = "BTC-USD" # Default pair
        signal = self.analyze_market()
        price = self.client.get_price(symbol)
        
        if not price:
            return "Error fetching price"

        if signal == "BUY":
            # Buy logic
            amount_to_invest = 20.0 # Fixed bet size
            quantity = amount_to_invest / price
            
            if self.check_exposure_limit(amount_to_invest):
                order = self.client.place_order(symbol, "BUY", quantity)
                if order:
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
                        details=f"Bought {quantity:.6f} BTC at {price}",
                        capital_exposure=get_total_exposure()
                    )
                    return f"Bought {quantity:.6f} BTC"
            else:
                return "Buy blocked by capital limit"

        elif signal == "SELL":
            # Sell logic - sell all open positions
            positions = Position.select().where(Position.symbol == symbol, Position.is_open == True)
            total_qty = sum([p.quantity for p in positions])
            
            if total_qty > 0:
                order = self.client.place_order(symbol, "SELL", total_qty)
                if order:
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
                        details=f"Sold {total_qty:.6f} BTC at {price}",
                        capital_exposure=get_total_exposure()
                    )
                    return f"Sold {total_qty:.6f} BTC"
        
        return "No action"

    def emergency_stop(self):
        """
        Stops trading and optionally closes positions.
        """
        self.is_running = False
        # Logic to close all positions could go here if configured
        return "Trading stopped."
