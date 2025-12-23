from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


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

    # IMPORTANT:
    # These are placeholders. In the official Revolut X REST API, paths usually start from /api
    # (example from docs: /api/1.0/orders).
    #
    # Keep these centralized so you can update them quickly.
    #
    # --- Configuration (documented) ---
    # - GET /api/1.0/configuration/currencies (confirmed 200 in your account)
    # - GET /api/1.0/configuration/currency-pairs (may vary; we probe alternatives in code)
    config_currencies: str = "/api/1.0/configuration/currencies"
    config_currency_pairs: str = "/api/1.0/configuration/currency-pairs"

    # --- Public market data (documented) ---
    public_last_trades: str = "/api/1.0/public/last-trades"
    public_order_book: str = "/api/1.0/public/order-book/{symbol}"

    # --- Account ---
    balances: str = "/api/1.0/balances"  # confirmed 200

    # Trading / orders (confirmed /active = 200)
    place_order: str = "/api/1.0/orders"  # POST (per doc)
    active_orders: str = "/api/1.0/orders/active"
    historical_orders: str = "/api/1.0/orders/historical"
    order_by_id: str = "/api/1.0/orders/{venue_order_id}"
    cancel_order_by_id: str = "/api/1.0/orders/{venue_order_id}"  # DELETE (per doc)

    # Trades / fills
    private_trades_by_symbol: str = "/api/1.0/trades/private/{symbol}"


class RevolutXClient:
    def __init__(
        self,
        base_url: str,
        base_path: str,
        api_key: str | None = None,
        private_key_pem: str | None = None,
        timeout_seconds: int = 10,
        endpoints: RevolutXEndpoints | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.base_path = (base_path or "").strip()
        self.api_key = api_key
        self.private_key_pem = private_key_pem
        self.timeout_seconds = timeout_seconds
        self.endpoints = endpoints or RevolutXEndpoints()

        self.session = requests.Session()

    def _load_private_key(self) -> Ed25519PrivateKey | None:
        if not self.private_key_pem:
            return None
        try:
            key = serialization.load_pem_private_key(
                self.private_key_pem.encode("utf-8"),
                password=None,
            )
            if isinstance(key, Ed25519PrivateKey):
                return key
        except Exception as e:
            logger.warning("Failed to load Revolut X private key PEM: %s", repr(e))
        return None

    def auth_ready(self) -> bool:
        """
        Returns True if we have both API key and a loadable Ed25519 private key.
        """
        return bool(self.api_key) and (self._load_private_key() is not None)

    def derived_public_key_pem(self) -> str | None:
        """
        Returns the public key PEM derived from the loaded private key.
        Useful to verify that the key registered in Revolut X matches the server key.
        Public key is not secret.
        """
        pk = self._load_private_key()
        if not pk:
            return None
        pub = pk.public_key()
        pem = pub.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return pem.decode("utf-8")

    @staticmethod
    def _minified_json(obj: Any) -> str:
        return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _sorted_query_string(params: dict[str, Any] | None) -> str:
        if not params:
            return ""
        # Deterministic order is important for signatures.
        items = []
        for k in sorted(params.keys()):
            v = params[k]
            if v is None:
                continue
            items.append(f"{k}={v}")
        return "&".join(items)

    def _sign_headers(
        self,
        method: str,
        request_path: str,
        query_string: str,
        body_json_minified: str,
    ) -> dict[str, str]:
        """
        Revolut X signature scheme (from docs):
          message = timestamp_ms + METHOD + PATH + QUERY + BODY
          signature = base64( sign_ed25519(private_key, message) )
          headers:
            X-Revx-API-Key
            X-Revx-Timestamp
            X-Revx-Signature
        """
        api_key = (self.api_key or "").strip()
        if not api_key:
            return {}
        pk = self._load_private_key()
        if not pk:
            return {}
        ts_ms = str(int(time.time() * 1000))
        msg = f"{ts_ms}{method.upper()}{request_path}{query_string}{body_json_minified}"
        sig = pk.sign(msg.encode("utf-8"))
        sig_b64 = base64.b64encode(sig).decode("ascii")
        return {
            "X-Revx-API-Key": api_key,
            "X-Revx-Timestamp": ts_ms,
            "X-Revx-Signature": sig_b64,
        }

    def _headers(self) -> dict[str, str]:
        # Base headers. Auth/signature headers are added per request in _request_json.
        return {"Accept": "application/json"}

    def _make_url(self, relative_path: str) -> str:
        # base_url + base_path + relative_path (all normalized)
        base = self.base_url + ("" if not self.base_path else ("/" + self.base_path.strip("/")))
        return urljoin(base + "/", relative_path.lstrip("/"))

    def _public_get_json(self, relative_path: str, params: dict[str, Any] | None = None) -> Any | None:
        """
        Public GET without auth/signature headers.
        Some deployments are picky and may reject signed requests on public endpoints.
        """
        url = self._make_url(relative_path)
        try:
            resp = self.session.get(url, params=params, headers=self._headers(), timeout=self.timeout_seconds)
            if resp.status_code >= 400:
                logger.warning("Revolut X public API error %s for %s: %s", resp.status_code, url, resp.text[:300])
                return None
            try:
                return resp.json()
            except Exception:
                return None
        except Exception as e:
            logger.warning("Revolut X public request failed: %s (%s)", url, repr(e))
            return None

    def _request_json(
        self,
        method: str,
        relative_path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        retries: int = 2,
        backoff_seconds: float = 0.5,
    ) -> Any | None:
        status, data = self._request(method, relative_path, params=params, json_body=json_body, retries=retries, backoff_seconds=backoff_seconds)
        if status is None:
            return None
        if status >= 400:
            return None
        return data

    def _request(
        self,
        method: str,
        relative_path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        retries: int = 2,
        backoff_seconds: float = 0.5,
    ) -> tuple[int | None, Any | None]:
        """
        Low-level request that returns (status_code, parsed_json_or_text_or_none).
        Used for debugging/probing endpoints.
        """
        url = self._make_url(relative_path)
        request_path = ("/" + self.base_path.strip("/")) if self.base_path else ""
        request_path = request_path + (relative_path if relative_path.startswith("/") else f"/{relative_path}")
        query_string = self._sorted_query_string(params)
        body_min = self._minified_json(json_body) if json_body is not None else ""
        sig_headers = self._sign_headers(method, request_path, query_string, body_min)
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            try:
                headers = {**self._headers(), **sig_headers}
                if json_body is not None:
                    headers["Content-Type"] = "application/json"
                resp = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json_body,
                    headers=headers,
                    timeout=self.timeout_seconds,
                )
                if resp.status_code >= 500:
                    raise requests.HTTPError(f"Server error {resp.status_code}", response=resp)
                if resp.status_code == 429:
                    raise requests.HTTPError("Rate limited (429)", response=resp)
                if resp.status_code >= 400:
                    logger.warning("Revolut X API error %s for %s: %s", resp.status_code, url, resp.text[:300])
                    # best-effort parse
                    try:
                        return resp.status_code, resp.json()
                    except Exception:
                        return resp.status_code, resp.text
                try:
                    return resp.status_code, resp.json()
                except Exception:
                    return resp.status_code, resp.text
            except Exception as e:
                last_err = e
                if attempt < retries:
                    time.sleep(backoff_seconds * (2**attempt))
                    continue
                logger.warning("Revolut X request failed: %s %s (%s)", method, url, repr(last_err))
                # Use status=0 to indicate "no HTTP response" (network/DNS/TLS/etc.)
                return 0, repr(last_err)

    def probe(self, relative_paths: list[str]) -> list[dict[str, Any]]:
        """
        Probe a list of paths (GET) and return status codes.
        """
        results: list[dict[str, Any]] = []
        for p in relative_paths:
            status, data = self._request("GET", p, params=None, json_body=None, retries=0)
            results.append(
                {
                    "path": p,
                    "status": status,
                    "sample": (str(data)[:140] if data is not None else None),
                }
            )
        return results

    # --- Public API ---
    def get_pairs(self) -> list[str]:
        """
        Returns list of tradable symbols/pairs (e.g., ["BTC-USD", "ETH-USD"]).

        Prefer the official configuration endpoint:
          GET /api/1.0/configuration/currency-pairs
        """
        data = self._request_json("GET", self.endpoints.config_currency_pairs)
        if not data:
            # Fallback for older/unknown deployments
            data = self._request_json("GET", self.endpoints.pairs)
            if not data:
                return []

        # Common shapes:
        # - {"data": [{"symbol": "BTC-USD"}, ...]}
        # - {"pairs": [{"symbol": "BTC-USD"}, ...]}
        # - [{"symbol": "BTC-USD"}, ...]
        if isinstance(data, dict) and "pairs" in data and isinstance(data["pairs"], list):
            items = data["pairs"]
        elif isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
            items = data["data"]
        elif isinstance(data, list):
            items = data
        else:
            items = []

        out: list[str] = []
        for it in items:
            if isinstance(it, dict):
                sym = it.get("symbol") or it.get("pair") or it.get("name")
                if not sym:
                    # Sometimes split base/quote fields
                    base = it.get("base") or it.get("base_currency") or it.get("baseCurrency")
                    quote = it.get("quote") or it.get("quote_currency") or it.get("quoteCurrency")
                    if base and quote:
                        sym = f"{base}-{quote}"
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
        Revolut X REST: prefer public last-trades for price discovery.
        """
        data = self._public_get_json(self.endpoints.public_last_trades)
        # Some deployments require signature even on "public" endpoints.
        if data is None and self.auth_ready():
            data = self._request_json("GET", self.endpoints.public_last_trades)
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            for it in data["data"]:
                if not isinstance(it, dict):
                    continue
                if str(it.get("symbol", "")).upper() != symbol.upper():
                    continue
                px = it.get("price") or it.get("last_price") or it.get("lastPrice")
                if px is not None:
                    try:
                        return float(px)
                    except Exception:
                        return None
        elif isinstance(data, list):
            for it in data:
                if not isinstance(it, dict):
                    continue
                if str(it.get("symbol", "")).upper() != symbol.upper():
                    continue
                px = it.get("price") or it.get("last_price") or it.get("lastPrice")
                if px is not None:
                    try:
                        return float(px)
                    except Exception:
                        return None
        return None

    def get_public_symbols(self) -> set[str]:
        """
        Best-effort way to list tradable symbols/pairs.
        Uses the public endpoint /api/1.0/public/last-trades which in practice
        returns rows including a 'symbol' field (e.g. BTC-USD, BTC-USDC).
        """
        data = self._public_get_json(self.endpoints.public_last_trades)
        # Some deployments require signature even on "public" endpoints.
        if data is None and self.auth_ready():
            data = self._request_json("GET", self.endpoints.public_last_trades)
        items: list[Any] = []
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            items = data["data"]
        elif isinstance(data, list):
            items = data
        out: set[str] = set()
        for it in items:
            if not isinstance(it, dict):
                continue
            sym = it.get("symbol")
            if sym:
                out.add(str(sym).upper())
        return out

    # --- Optional private read-only endpoints (only if API supports them) ---
    def get_balances(self) -> Any | None:
        return self._request_json("GET", self.endpoints.balances)

    def get_private_trades(self, symbol: str) -> Any | None:
        path = self.endpoints.private_trades_by_symbol.format(symbol=symbol)
        return self._request_json("GET", path)

    def get_currencies(self) -> list[str]:
        """
        Returns list of currency codes from:
          GET /api/1.0/configuration/currencies
        In your account this endpoint returns a dict keyed by currency code.
        """
        data = self._request_json("GET", self.endpoints.config_currencies)
        if not data:
            return []
        if isinstance(data, dict):
            return sorted({str(k).upper() for k in data.keys()})
        if isinstance(data, list):
            out = []
            for it in data:
                if isinstance(it, dict) and it.get("symbol"):
                    out.append(str(it["symbol"]).upper())
            return sorted(set(out))
        return []

    def get_currency_pairs(self) -> list[str]:
        """
        Try to fetch tradable currency pairs from configuration endpoint.
        Because some deployments differ, try a small set of candidate paths.

        Returns symbols like "BTC-USD".
        """
        candidates = [
            self.endpoints.config_currency_pairs,
            "/api/1.0/configuration/currency_pairs",
            "/api/1.0/configuration/currencyPairs",
            "/api/1.0/configuration/currency-pairs",
            "/api/1.0/configuration/pairs",
        ]
        data = None
        for path in candidates:
            status, payload = self._request("GET", path, retries=0)
            if status == 200:
                data = payload
                break
        if not data:
            return []

        # Shapes seen in docs: list or {"data":[...]}
        items = []
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            items = data["data"]
        elif isinstance(data, list):
            items = data
        elif isinstance(data, dict) and isinstance(data.get("pairs"), list):
            items = data["pairs"]

        out: list[str] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            sym = it.get("symbol")
            if sym:
                out.append(str(sym).upper())
                continue
            base = it.get("base") or it.get("base_currency") or it.get("baseCurrency")
            quote = it.get("quote") or it.get("quote_currency") or it.get("quoteCurrency")
            if base and quote:
                out.append(f"{str(base).upper()}-{str(quote).upper()}")
        return sorted(set(out))

    def pair_exists_via_trades_private(self, symbol: str) -> bool:
        """
        Uses trades/private/{symbol} as an existence check.
        If it returns 200 (even with empty data), we treat pair as existing.
        """
        path = self.endpoints.private_trades_by_symbol.format(symbol=symbol)
        status, _ = self._request("GET", path, retries=0)
        return status == 200

    # --- Trading endpoints (ONLY if you enable trading and your key allows it) ---
    def place_order(
        self,
        symbol: str,
        side: str,  # "buy" | "sell"
        client_order_id: str,
        market_base_size: str | None = None,
        market_quote_size: str | None = None,
    ) -> Any | None:
        """
        Revolut X docs:
          POST /api/1.0/orders
        Required:
          - client_order_id
          - symbol
          - side: "buy"|"sell"
          - order_configuration.market with exactly one of base_size or quote_size (strings)
        """
        if (market_base_size is None) == (market_quote_size is None):
            raise ValueError("Provide exactly one of market_base_size or market_quote_size")
        market: dict[str, Any] = {}
        if market_base_size is not None:
            market["base_size"] = market_base_size
        if market_quote_size is not None:
            market["quote_size"] = market_quote_size
        # Docs examples use uppercase BUY/SELL.
        side_norm = str(side).upper().strip()
        if side_norm not in ("BUY", "SELL"):
            # Allow "buy"/"sell" inputs as well.
            side_norm = "BUY" if str(side).lower().strip() == "buy" else ("SELL" if str(side).lower().strip() == "sell" else side_norm)

        payload: dict[str, Any] = {
            "client_order_id": client_order_id,
            "symbol": symbol,
            "side": side_norm,
            "order_configuration": {"market": market},
        }
        # For trading we want the error payload too (not just None).
        status, data = self._request("POST", self.endpoints.place_order, json_body=payload, retries=0)
        if status is None:
            return {"_error": True, "status": None, "data": None}
        if status >= 400:
            return {"_error": True, "status": status, "data": data}
        return data

    def get_active_orders(self) -> Any | None:
        return self._request_json("GET", self.endpoints.active_orders)

    def get_historical_orders(self) -> Any | None:
        return self._request_json("GET", self.endpoints.historical_orders)

    def get_order(self, venue_order_id: str) -> Any | None:
        path = self.endpoints.order_by_id.format(venue_order_id=venue_order_id)
        return self._request_json("GET", path)

    def cancel_order(self, venue_order_id: str) -> Any | None:
        path = self.endpoints.cancel_order_by_id.format(venue_order_id=venue_order_id)
        return self._request_json("DELETE", path)

