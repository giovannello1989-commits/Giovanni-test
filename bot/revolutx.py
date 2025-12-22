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
    pairs: str = "/api/1.0/pairs"
    candles: str = "/api/1.0/candles"
    ticker: str = "/api/1.0/ticker"
    balances: str = "/api/1.0/balances"
    private_trades: str = "/api/1.0/trades"
    # Trading (write) endpoints (placeholders — MUST match official docs)
    place_order: str = "/api/1.0/orders"
    cancel_order: str = "/api/1.0/orders/cancel"
    order_status: str = "/api/1.0/orders"


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

    # --- Trading endpoints (ONLY if you enable trading and your key allows it) ---
    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str = "MARKET",
        quote_amount: float | None = None,
        base_amount: float | None = None,
        client_order_id: str | None = None,
    ) -> Any | None:
        """
        IMPORTANT: This is a generic placeholder implementation.
        You MUST adapt payload/fields to Revolut X official trading docs.

        Many exchanges support either:
        - quote amount (spend X USDT)
        - base amount (buy X BTC)
        """
        payload: dict[str, Any] = {
            "symbol": symbol,
            "side": side.upper(),
            "type": order_type.upper(),
        }
        if quote_amount is not None:
            payload["quoteAmount"] = quote_amount
        if base_amount is not None:
            payload["baseAmount"] = base_amount
        if client_order_id:
            payload["clientOrderId"] = client_order_id

        # Revolut X signing requires the minified JSON body to be part of the signature.
        return self._request_json("POST", self.endpoints.place_order, json_body=payload)

    def cancel_order(self, order_id: str) -> Any | None:
        payload = {"orderId": order_id}
        return self._request_json("POST", self.endpoints.cancel_order, json_body=payload)

    def get_order_status(self, order_id: str) -> Any | None:
        return self._request_json("GET", self.endpoints.order_status, params={"orderId": order_id})

