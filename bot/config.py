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

    # Crypto strategy: short-term momentum + trailing stop
    "timeframe": "1m",
    "ohlcv_limit": 200,
    "crypto_lookback_bars": 5,
    "crypto_rise_threshold_pct": 0.25,
    "crypto_fall_threshold_pct": 0.25,
    "crypto_trailing_window_bars": 30,
    "crypto_trailing_stop_pct": 0.30,

    # Optional legacy key (kept to avoid breaking existing configs)
    "revolut_api_key": "",
    "revolut_api_secret": "",

    # Stock alerts (separate feature)
    "stock_alerts_enabled": False,
    "stock_market": "US",
    "alert_aggressiveness": "medium",

    # Forex alerts (manual trading; bot only notifies)
    # Watch symbols like: "EURUSD=X", "GBPUSD=X", "USDJPY=X"
    "forex_alerts_enabled": True,
    "forex_poll_interval_seconds": 60,
    "forex_default_interval": "1m",
    "forex_default_lookback_bars": 5,
    "forex_default_rise_threshold_pct": 0.05,
    "forex_default_fall_threshold_pct": 0.05,

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
