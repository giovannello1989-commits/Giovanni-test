from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import requests


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RevolutXEndpoints:
    """
    IMPORTANT: Revolut X API paths may change.
    Keep them centralized here so you can update them quickly.

    You can change BASE_URL and BASE_PATH via env vars:
    - REVOLUTX_BASE_URL
    - REVOLUTX_BASE_PATH

    Then adjust these relative paths if the doc differs.
    """

    # Examples / placeholders — update to match official docs.
    pairs: str = "/public/pairs"
    candles: str = "/public/candles"
    ticker: str = "/public/ticker"
    balances: str = "/private/balances"
    private_trades: str = "/private/trades"


class RevolutXClient:
    def __init__(
        self,
        base_url: str,
        base_path: str,
        api_key: str | None = None,
        timeout_seconds: int = 10,
        endpoints: RevolutXEndpoints | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.base_path = (base_path or "").strip()
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.endpoints = endpoints or RevolutXEndpoints()

        self.session = requests.Session()

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if self.api_key:
            # Placeholder: adjust header name as per official Revolut X docs.
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _make_url(self, relative_path: str) -> str:
        # base_url + base_path + relative_path (all normalized)
        base = self.base_url + ("" if not self.base_path else ("/" + self.base_path.strip("/")))
        return urljoin(base + "/", relative_path.lstrip("/"))

    def _request_json(
        self,
        method: str,
        relative_path: str,
        params: dict[str, Any] | None = None,
        retries: int = 2,
        backoff_seconds: float = 0.5,
    ) -> Any | None:
        url = self._make_url(relative_path)
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            try:
                resp = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    headers=self._headers(),
                    timeout=self.timeout_seconds,
                )
                if resp.status_code >= 500:
                    raise requests.HTTPError(f"Server error {resp.status_code}", response=resp)
                if resp.status_code == 429:
                    raise requests.HTTPError("Rate limited (429)", response=resp)
                if resp.status_code >= 400:
                    logger.warning("Revolut X API error %s for %s: %s", resp.status_code, url, resp.text[:300])
                    return None
                return resp.json()
            except Exception as e:
                last_err = e
                if attempt < retries:
                    time.sleep(backoff_seconds * (2**attempt))
                    continue
                logger.warning("Revolut X request failed: %s %s (%s)", method, url, repr(last_err))
                return None

    # --- Public API ---
    def get_pairs(self) -> list[str]:
        """
        Returns list of tradable symbols/pairs (e.g., ["BTC-EUR", "ETH-EUR"]).
        Adjust parsing to match Revolut X docs.
        """
        data = self._request_json("GET", self.endpoints.pairs)
        if not data:
            return []

        # Common shapes:
        # - {"pairs": [{"symbol": "BTC-EUR"}, ...]}
        # - [{"symbol": "BTC-EUR"}, ...]
        if isinstance(data, dict) and "pairs" in data and isinstance(data["pairs"], list):
            items = data["pairs"]
        elif isinstance(data, list):
            items = data
        else:
            items = []

        out: list[str] = []
        for it in items:
            if isinstance(it, dict):
                sym = it.get("symbol") or it.get("pair") or it.get("name")
                if sym:
                    out.append(str(sym).upper())
        return sorted(set(out))

    def get_candles(
        self,
        symbol: str,
        interval: str,
        start: int | None = None,
        end: int | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Returns a list of candles ordered oldest->newest.

        Params are intentionally generic because Revolut X candle endpoints vary.
        Update params and parsing to match official docs.
        """
        params: dict[str, Any] = {"symbol": symbol, "interval": interval}
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        if limit is not None:
            params["limit"] = limit

        data = self._request_json("GET", self.endpoints.candles, params=params)
        if not data:
            return []

        # Common shapes:
        # - {"candles": [{"t":..., "o":..., "h":..., "l":..., "c":...}, ...]}
        # - [{"timestamp":..., "open":..., "high":..., "low":..., "close":...}, ...]
        if isinstance(data, dict) and "candles" in data and isinstance(data["candles"], list):
            items = data["candles"]
        elif isinstance(data, list):
            items = data
        else:
            items = []

        candles: list[dict[str, Any]] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            # Normalize keys we use downstream: timestamp, open, high, low, close
            close = it.get("close", it.get("c"))
            open_ = it.get("open", it.get("o"))
            high = it.get("high", it.get("h"))
            low = it.get("low", it.get("l"))
            ts = it.get("timestamp", it.get("t"))
            if close is None:
                continue
            candles.append(
                {
                    "timestamp": ts,
                    "open": float(open_) if open_ is not None else None,
                    "high": float(high) if high is not None else None,
                    "low": float(low) if low is not None else None,
                    "close": float(close),
                }
            )

        # If timestamp sortable, sort (safe fallback)
        def _sort_key(c: dict[str, Any]):
            v = c.get("timestamp")
            try:
                return float(v)
            except Exception:
                return 0.0

        candles.sort(key=_sort_key)
        return candles

    def get_last_price(self, symbol: str, interval_fallback: str = "5m") -> float | None:
        """
        Try ticker endpoint if available; otherwise fallback to last candle close.
        """
        data = self._request_json("GET", self.endpoints.ticker, params={"symbol": symbol})
        if isinstance(data, dict):
            for key in ("last", "lastPrice", "price", "last_price"):
                if key in data and data[key] is not None:
                    try:
                        return float(data[key])
                    except Exception:
                        pass
            # Sometimes: {"ticker": {"last": ...}}
            t = data.get("ticker")
            if isinstance(t, dict):
                v = t.get("last") or t.get("price")
                if v is not None:
                    try:
                        return float(v)
                    except Exception:
                        pass

        candles = self.get_candles(symbol=symbol, interval=interval_fallback, limit=1)
        if candles:
            return float(candles[-1]["close"])
        return None

    # --- Optional private read-only endpoints (only if API supports them) ---
    def get_balances(self) -> Any | None:
        return self._request_json("GET", self.endpoints.balances)

    def get_private_trades(self, symbol: str | None = None) -> Any | None:
        params = {"symbol": symbol} if symbol else None
        return self._request_json("GET", self.endpoints.private_trades, params=params)

