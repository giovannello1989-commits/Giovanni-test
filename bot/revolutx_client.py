import base64
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RevolutXConfig:
    api_key: str
    private_key_pem: str
    base_url: str = "https://api.revolutx.com"


class RevolutXClient:
    """
    Revolut X REST client with Ed25519 signature authentication.

    Signing rule (no spaces/newlines):
      <timestamp><HTTP_METHOD><request_path><query_string><body_json>
    """

    def __init__(self, cfg: RevolutXConfig):
        if not cfg.api_key:
            raise ValueError("RevolutX api_key is required")
        if not cfg.private_key_pem:
            raise ValueError("RevolutX private_key_pem is required")
        self.cfg = cfg
        self._sk = self._load_private_key(cfg.private_key_pem)
        self.session = requests.Session()

    def _load_private_key(self, pem_text: str) -> Ed25519PrivateKey:
        key = serialization.load_pem_private_key(
            pem_text.encode("utf-8"),
            password=None,
        )
        if not isinstance(key, Ed25519PrivateKey):
            raise TypeError("Provided PEM is not an Ed25519 private key")
        return key

    def _canonical_json(self, body: Any) -> str:
        if body in (None, "", b""):
            return ""
        # Deterministic, no spaces. (Some APIs are sensitive to key order.)
        return json.dumps(body, separators=(",", ":"), sort_keys=True)

    def _timestamp_ms(self) -> str:
        return str(int(time.time() * 1000))

    def _sign(self, message: str) -> str:
        sig = self._sk.sign(message.encode("utf-8"))
        return base64.b64encode(sig).decode("ascii")

    def _build_signature_payload(self, *, ts: str, method: str, path: str, query_string: str, body_json: str) -> str:
        return f"{ts}{method}{path}{query_string}{body_json}"

    def request(self, method: str, path: str, *, params: Optional[dict] = None, body: Any = None) -> Any:
        method_up = method.upper()
        qs = urlencode(params or {}, doseq=True)
        body_json = self._canonical_json(body)
        ts = self._timestamp_ms()

        payload = self._build_signature_payload(ts=ts, method=method_up, path=path, query_string=qs, body_json=body_json)
        signature = self._sign(payload)

        headers = {
            "X-Revx-API-Key": self.cfg.api_key,
            "X-Revx-Timestamp": ts,
            "X-Revx-Signature": signature,
            "Content-Type": "application/json",
        }

        url = self.cfg.base_url.rstrip("/") + path
        resp = self.session.request(
            method=method_up,
            url=url,
            headers=headers,
            params=params,
            data=body_json if body_json else None,
            timeout=20,
        )

        if resp.status_code >= 400:
            raise RuntimeError(f"RevolutX HTTP {resp.status_code}: {resp.text[:500]}")

        if not resp.text:
            return None
        try:
            return resp.json()
        except Exception:
            return resp.text

    # ---- API helpers ----
    def get_time(self) -> Any:
        return self.request("GET", "/api/v1/time")

    def get_balances(self) -> Any:
        return self.request("GET", "/api/v1/balances")

    def get_markets(self) -> Any:
        return self.request("GET", "/api/v1/markets")

    def get_orders(self) -> Any:
        return self.request("GET", "/api/v1/orders")

    def get_trades(self) -> Any:
        return self.request("GET", "/api/v1/trades")

    def create_market_order(self, *, symbol: str, side: str, quantity: str) -> Any:
        body = {"symbol": symbol, "side": side.upper(), "type": "MARKET", "quantity": str(quantity)}
        return self.request("POST", "/api/v1/orders", body=body)

    def cancel_order(self, order_id: str) -> Any:
        return self.request("DELETE", f"/api/v1/orders/{order_id}")

    def get_last_price(self, symbol: str) -> Optional[float]:
        """
        Best-effort: tries to extract a last price for a given symbol from /markets.
        """
        data = self.get_markets()

        candidates: list[dict] = []
        if isinstance(data, list):
            candidates = [x for x in data if isinstance(x, dict)]
        elif isinstance(data, dict):
            # sometimes APIs return {"markets":[...]} or {"data":[...]}
            for k in ("markets", "data", "result"):
                v = data.get(k)
                if isinstance(v, list):
                    candidates = [x for x in v if isinstance(x, dict)]
                    if candidates:
                        break

        for m in candidates:
            if str(m.get("symbol") or m.get("market") or "") != symbol:
                continue
            for key in ("last", "lastPrice", "price", "markPrice", "mid"):
                v = m.get(key)
                if v is None:
                    continue
                try:
                    return float(v)
                except Exception:
                    continue

        return None

