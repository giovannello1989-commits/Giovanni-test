import json
import os
from typing import Dict, Any

CONFIG_FILE = "user_config.json"

DEFAULT_CONFIG = {
    "revolut_api_key": "",
    "revolut_api_secret": "",  # If needed, usually just one key for some APIs
    "max_capital": 100.0,
    "trading_style": "test_mode",
    "stock_alerts_enabled": False,
    "stock_market": "US",
    "alert_aggressiveness": "medium",
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
