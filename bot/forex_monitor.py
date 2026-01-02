import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ForexSignal:
    symbol: str
    last: float
    change_pct: float
    direction: str  # "RISE" | "FALL"


class ForexMonitor:
    """
    Forex alerts only (no trading).

    Uses yfinance FX symbols (e.g. "EURUSD=X", "GBPUSD=X", "USDJPY=X").
    """

    def __init__(self, config_manager):
        self.config = config_manager

    def _fetch_intraday(self, symbol: str, interval: str = "1m", period: str = "1d") -> Optional[pd.DataFrame]:
        """
        Fetch intraday candles from Yahoo Finance chart endpoint directly.
        This is more reliable than yfinance in restricted environments.
        """
        # Yahoo expects range, not period; keep "1d" default.
        range_ = period
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        params = {"interval": interval, "range": range_}
        headers = {"User-Agent": "TradingBot/1.0"}

        try:
            resp = requests.get(url, params=params, headers=headers, timeout=15)
            if resp.status_code != 200:
                logger.error("Yahoo chart HTTP %s for %s: %s", resp.status_code, symbol, resp.text[:200])
                return None
            data = resp.json()
        except Exception as e:
            logger.error("Forex fetch failed for %s: %s", symbol, e)
            return None

        try:
            result = (data.get("chart", {}).get("result") or [None])[0]
            if not result:
                return None
            ts = result.get("timestamp") or []
            quote = (result.get("indicators", {}).get("quote") or [None])[0] or {}
            closes = quote.get("close") or []
            opens = quote.get("open") or []
            highs = quote.get("high") or []
            lows = quote.get("low") or []
            vols = quote.get("volume") or []

            if not ts or not closes:
                return None

            df = pd.DataFrame(
                {
                    "ts": pd.to_datetime(pd.Series(ts, dtype="int64"), unit="s", utc=True),
                    "Open": opens,
                    "High": highs,
                    "Low": lows,
                    "Close": closes,
                    "Volume": vols,
                }
            )
            df = df.dropna(subset=["Close"])
            return df if not df.empty else None
        except Exception as e:
            logger.error("Failed parsing Yahoo chart for %s: %s", symbol, e)
            return None

    def get_last_price(self, symbol: str, *, interval: str = "1m") -> Optional[float]:
        df = self._fetch_intraday(symbol, interval=interval, period="1d")
        if df is None or df.empty:
            return None
        closes = df["Close"].dropna()
        if closes.empty:
            return None
        return float(closes.iloc[-1])

    def detect_signal(
        self,
        symbol: str,
        *,
        lookback_bars: int,
        rise_threshold_pct: float,
        fall_threshold_pct: float,
        interval: str = "1m",
    ) -> Optional[ForexSignal]:
        """
        Detects short-term rise/fall based on % change over lookback bars.
        """
        df = self._fetch_intraday(symbol, interval=interval, period="1d")
        if df is None or len(df) < lookback_bars + 1:
            return None

        closes = df["Close"].dropna()
        if len(closes) < lookback_bars + 1:
            return None

        last = float(closes.iloc[-1])
        prev = float(closes.iloc[-(lookback_bars + 1)])
        if prev == 0:
            return None

        change_pct = ((last - prev) / prev) * 100.0

        if change_pct >= rise_threshold_pct:
            return ForexSignal(symbol=symbol, last=last, change_pct=change_pct, direction="RISE")
        if change_pct <= -abs(fall_threshold_pct):
            return ForexSignal(symbol=symbol, last=last, change_pct=change_pct, direction="FALL")
        return None

