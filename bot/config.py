import json
import os
from typing import Dict, Any

CONFIG_FILE = "user_config.json"

DEFAULT_CONFIG = {
    # Exchange integration (ccxt)
    # Use public endpoints for market data if api_key/secret are empty.
    "exchange_id": "kraken",          # e.g. kraken, binance, coinbase, okx...
    "exchange_api_key": "",
    "exchange_api_secret": "",
    "sandbox_mode": False,
    "execution_mode": "paper",        # paper | live

    # Trading settings
    "symbol": "BTC/USDT",
    "max_capital": 100.0,
    "bet_usd": 20.0,
    "trade_interval_seconds": 60,

    # Strategy (RSI)
    "timeframe": "1m",
    "ohlcv_limit": 200,
    "rsi_period": 14,
    "rsi_buy_threshold": 30.0,
    "rsi_sell_threshold": 70.0,

    # Optional legacy key (kept to avoid breaking existing configs)
    "revolut_api_key": "",
    "revolut_api_secret": "",

    # Stock alerts (separate feature)
    "stock_alerts_enabled": False,
    "stock_market": "US",
    "alert_aggressiveness": "medium",

    # Ops
    "static_ip": None,
    "is_configured": False
}

class ConfigManager:
    def __init__(self):
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        if not os.path.exists(CONFIG_FILE):
            return DEFAULT_CONFIG.copy()
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except:
            return DEFAULT_CONFIG.copy()

    def save_config(self):
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.config, f, indent=4)

    def get(self, key: str, default=None):
        return self.config.get(key, default)

    def set(self, key: str, value: Any):
        self.config[key] = value
        self.save_config()

    @property
    def is_configured(self):
        return self.config.get("is_configured", False)

config_manager = ConfigManager()
