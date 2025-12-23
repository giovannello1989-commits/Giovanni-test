from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger(__name__)


class MarketDataClient:
    """
    Minimal market data interface:
    - get_pairs(): returns list like ["BTC-EUR", "ETH-EUR"]
    - get_candles(symbol, interval, limit): returns list of dicts with at least "close"
    - get_last_price(symbol)
    """

    def get_pairs(self) -> list[str]:
        raise NotImplementedError

    def get_candles(self, symbol: str, interval: str, limit: int) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get_last_price(self, symbol: str) -> float | None:
        raise NotImplementedError


@dataclass(frozen=True)
class BinanceConfig:
    base_url: str = "https://api.binance.com"
    timeout_seconds: int = 10
    retries: int = 1


class BinancePublicClient(MarketDataClient):
    """
    Uses Binance public endpoints (no API key).

    Notes:
    - Binance symbols are like "BTCEUR" (no dash). We expose "BTC-EUR".
    - Candle interval uses Binance interval strings ("5m", "1m", etc.)
    """

    def __init__(self, quote: str = "EUR", cfg: BinanceConfig | None = None) -> None:
        self.quote = quote.upper()
        self.cfg = cfg or BinanceConfig()
        self.session = requests.Session()

    def _request_json(self, path: str, params: dict[str, Any] | None = None) -> Any | None:
        url = self.cfg.base_url.rstrip("/") + path
        last: Exception | None = None
        for attempt in range(self.cfg.retries + 1):
            try:
                r = self.session.get(url, params=params, timeout=self.cfg.timeout_seconds)
                if r.status_code >= 400:
                    logger.warning("Binance API error %s for %s: %s", r.status_code, url, r.text[:200])
                    return None
                return r.json()
            except Exception as e:
                last = e
                if attempt < self.cfg.retries:
                    time.sleep(0.4 * (2**attempt))
                    continue
                logger.warning("Binance request failed: %s (%s)", url, repr(last))
                return None

    @staticmethod
    def _to_exchange_symbol(symbol: str) -> str:
        # "BTC-EUR" -> "BTCEUR"
        s = symbol.replace("-", "").replace("/", "").upper()
        return s

    @staticmethod
    def _to_dash_symbol(base: str, quote: str) -> str:
        return f"{base.upper()}-{quote.upper()}"

    def get_pairs(self) -> list[str]:
        data = self._request_json("/api/v3/exchangeInfo")
        if not isinstance(data, dict) or "symbols" not in data:
            return []
        out: list[str] = []
        for s in data.get("symbols", []):
            if not isinstance(s, dict):
                continue
            if s.get("status") != "TRADING":
                continue
            base = s.get("baseAsset")
            quote = s.get("quoteAsset")
            if not base or not quote:
                continue
            if str(quote).upper() != self.quote:
                continue
            out.append(self._to_dash_symbol(str(base), str(quote)))
        return sorted(set(out))

    def get_candles(self, symbol: str, interval: str, limit: int) -> list[dict[str, Any]]:
        ex_symbol = self._to_exchange_symbol(symbol)
        data = self._request_json(
            "/api/v3/klines",
            params={"symbol": ex_symbol, "interval": interval, "limit": limit},
        )
        # Binance returns list of lists:
        # [ openTime, open, high, low, close, volume, closeTime, ... ]
        if not isinstance(data, list):
            return []
        candles: list[dict[str, Any]] = []
        for row in data:
            if not isinstance(row, list) or len(row) < 6:
                continue
            try:
                candles.append(
                    {
                        "timestamp": int(row[0]),
                        "open": float(row[1]),
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "close": float(row[4]),
                        "volume": float(row[5]),
                    }
                )
            except Exception:
                continue
        return candles

    def get_last_price(self, symbol: str) -> float | None:
        ex_symbol = self._to_exchange_symbol(symbol)
        data = self._request_json("/api/v3/ticker/price", params={"symbol": ex_symbol})
        if isinstance(data, dict) and data.get("price") is not None:
            try:
                return float(data["price"])
            except Exception:
                return None
        return None

    def get_top_movers(self, limit: int = 50) -> list[str]:
        """
        Returns the top positive 24h movers for this quote currency.
        Uses /api/v3/ticker/24hr (public).
        """
        data = self._request_json("/api/v3/ticker/24hr")
        if not isinstance(data, list):
            return []
        rows: list[tuple[float, str, str]] = []
        for r in data:
            if not isinstance(r, dict):
                continue
            sym = str(r.get("symbol", "")).upper()
            if not sym.endswith(self.quote):
                continue
            try:
                chg = float(r.get("priceChangePercent"))
            except Exception:
                continue
            base = sym[: -len(self.quote)]
            if not base:
                continue
            rows.append((chg, base, self.quote))
        rows.sort(key=lambda x: x[0], reverse=True)
        out = [self._to_dash_symbol(base, quote) for _, base, quote in rows[: max(1, int(limit))]]
        return out


class RevolutXMarketDataClient(MarketDataClient):
    """
    Adapter around RevolutXClient (read-only) to conform to MarketDataClient.
    """

    def __init__(self, base_url: str, base_path: str, api_key: str | None, timeout_seconds: int = 10) -> None:
        # Local import to keep dependencies optional/clean.
        from bot.revolutx import RevolutXClient

        self.rx = RevolutXClient(
            base_url=base_url,
            base_path=base_path,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )

    def get_pairs(self) -> list[str]:
        return self.rx.get_pairs()

    def get_candles(self, symbol: str, interval: str, limit: int) -> list[dict[str, Any]]:
        # RevolutXClient has flexible signature; we pass limit and rely on its parsing.
        return self.rx.get_candles(symbol=symbol, interval=interval, limit=limit)

    def get_last_price(self, symbol: str) -> float | None:
        return self.rx.get_last_price(symbol=symbol, interval_fallback="5m")


def create_market_data_client(
    provider: str,
    quote: str,
    timeout_seconds: int = 10,
    revolutx_base_url: str | None = None,
    revolutx_base_path: str | None = None,
    revolutx_api_key: str | None = None,
) -> MarketDataClient:
    provider = (provider or "binance").lower().strip()
    if provider == "binance":
        return BinancePublicClient(
            quote=quote,
            cfg=BinanceConfig(timeout_seconds=timeout_seconds),
        )
    if provider == "revolutx":
        if not revolutx_base_url or revolutx_base_url.strip() == "":
            raise ValueError("MARKET_DATA_PROVIDER=revolutx requires REVOLUTX_BASE_URL (or revolutx_base_url)")
        return RevolutXMarketDataClient(
            base_url=revolutx_base_url,
            base_path=revolutx_base_path or "",
            api_key=revolutx_api_key,
            timeout_seconds=timeout_seconds,
        )
    raise ValueError(f"Unsupported MARKET_DATA_PROVIDER: {provider}")

