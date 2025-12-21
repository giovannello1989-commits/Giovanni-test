from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from bot.config import RISK_PROFILES
from bot.storage import Storage


def _env(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    return v


def _require_admin(request: Request) -> None:
    """
    Very small "admin token" guard to avoid exposing setup to the internet.
    Use:
      - SETUP_ADMIN_TOKEN env var (required when web setup is enabled)
      - pass token as ?token=... (or header X-Setup-Token)
    """
    admin = _env("SETUP_ADMIN_TOKEN")
    if not admin:
        raise HTTPException(status_code=500, detail="Missing SETUP_ADMIN_TOKEN")
    token = request.query_params.get("token") or request.headers.get("X-Setup-Token")
    if token != admin:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _html_page(body: str) -> str:
    return f"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Bot Setup</title>
  <style>
    body {{ font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial; background:#0b1220; color:#e6e8ee; margin:0; }}
    .wrap {{ max-width: 760px; margin: 0 auto; padding: 28px 18px; }}
    .card {{ background:#111a2e; border:1px solid #223055; border-radius:16px; padding:18px; margin-bottom:14px; }}
    h1,h2 {{ margin: 0 0 12px 0; }}
    label {{ display:block; margin: 10px 0 6px; font-size: 14px; color:#c7cfdd; }}
    input, select {{ width:100%; padding:10px 12px; border-radius:12px; border:1px solid #2c3a63; background:#0b1220; color:#e6e8ee; }}
    .row {{ display:grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .muted {{ color:#aab3c6; font-size: 13px; line-height: 1.4; }}
    .btn {{ margin-top: 14px; padding: 12px 14px; background:#3b82f6; border:0; border-radius:12px; color:white; font-weight:600; cursor:pointer; }}
    .btn:active {{ transform: translateY(1px); }}
    code {{ background:#0b1220; border:1px solid #223055; padding: 2px 6px; border-radius:8px; }}
    a {{ color:#8ab4ff; }}
  </style>
</head>
<body>
  <div class="wrap">
    {body}
  </div>
</body>
</html>"""


def create_web_app(store: Storage, on_settings_changed_cb=None) -> FastAPI:
    app = FastAPI(title="RevolutX Bot Setup", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        _require_admin(request)
        st = store.get_settings()
        body = f"""
        <div class="card">
          <h1>Setup bot</h1>
          <p class="muted">Pagina di configurazione (tipo “registration”). Protetta da token admin.</p>
        </div>
        <div class="card">
          <h2>Stato attuale</h2>
          <p class="muted">
            base_currency: <code>{st.get('base_currency')}</code><br/>
            starting_capital: <code>{st.get('starting_capital')}</code><br/>
            risk_mode: <code>{st.get('risk_mode')}</code><br/>
            scan_interval_seconds: <code>{st.get('scan_interval_seconds')}</code><br/>
            pairs_limit: <code>{st.get('pairs_limit')}</code><br/>
            hard_close_minute: <code>{st.get('hard_close_minute')}</code><br/>
            revolutx_base_url: <code>{st.get('revolutx_base_url')}</code><br/>
            revolutx_base_path: <code>{st.get('revolutx_base_path')}</code><br/>
          </p>
          <p class="muted"><a href="/setup?token={request.query_params.get('token','')}">Apri wizard</a></p>
        </div>
        <div class="card">
          <h2>Segreti (NON qui)</h2>
          <p class="muted">
            I segreti vanno solo come ENV sul provider: <code>TELEGRAM_BOT_TOKEN</code> e (se serve) <code>REVOLUTX_API_KEY</code>.
          </p>
        </div>
        """
        return HTMLResponse(_html_page(body))

    @app.get("/health", response_class=PlainTextResponse)
    async def health():
        return PlainTextResponse("ok")

    @app.get("/setup", response_class=HTMLResponse)
    async def setup_get(request: Request):
        _require_admin(request)
        st = store.get_settings()

        risk_options = "".join(
            [f'<option value="{k}" {"selected" if st.get("risk_mode")==k else ""}>{k}</option>' for k in RISK_PROFILES]
        )

        body = f"""
        <div class="card">
          <h1>Wizard configurazione</h1>
          <p class="muted">Compila e salva. Le modifiche operative vengono applicate subito.</p>
        </div>
        <form method="post" action="/setup?token={request.query_params.get('token','')}">
          <div class="card">
            <h2>Capitale</h2>
            <div class="row">
              <div>
                <label>Valuta base</label>
                <input name="base_currency" value="{st.get('base_currency','EUR')}" placeholder="EUR"/>
              </div>
              <div>
                <label>Capitale iniziale</label>
                <input name="starting_capital" value="{st.get('starting_capital',0)}" placeholder="1000"/>
              </div>
            </div>
          </div>
          <div class="card">
            <h2>Rischio & Scanner</h2>
            <div class="row">
              <div>
                <label>Risk mode</label>
                <select name="risk_mode">{risk_options}</select>
              </div>
              <div>
                <label>Scan interval (secondi)</label>
                <input name="scan_interval_seconds" value="{st.get('scan_interval_seconds',60)}" placeholder="60"/>
              </div>
            </div>
            <div class="row">
              <div>
                <label>Pairs limit</label>
                <input name="pairs_limit" value="{st.get('pairs_limit',50)}" placeholder="50"/>
              </div>
              <div>
                <label>Hard-close minute (19:MM)</label>
                <input name="hard_close_minute" value="{st.get('hard_close_minute',55)}" placeholder="55"/>
              </div>
            </div>
          </div>
          <div class="card">
            <h2>Revolut X (non-segreti)</h2>
            <p class="muted">Qui configuri base URL e base path. Se l’API richiede auth, imposta <code>REVOLUTX_API_KEY</code> come ENV sul provider.</p>
            <label>REVOLUTX_BASE_URL</label>
            <input name="revolutx_base_url" value="{st.get('revolutx_base_url','')}" placeholder="https://..."/>
            <label>REVOLUTX_BASE_PATH</label>
            <input name="revolutx_base_path" value="{st.get('revolutx_base_path','')}" placeholder="/api/v1"/>
          </div>
          <div class="card">
            <h2>Salva</h2>
            <button class="btn" type="submit">Salva impostazioni</button>
            <p class="muted">Dopo il salvataggio puoi chiudere questa pagina.</p>
          </div>
        </form>
        """
        return HTMLResponse(_html_page(body))

    @app.post("/setup", response_class=HTMLResponse)
    async def setup_post(
        request: Request,
        base_currency: str = Form(...),
        starting_capital: str = Form(...),
        risk_mode: str = Form(...),
        scan_interval_seconds: str = Form(...),
        pairs_limit: str = Form(...),
        hard_close_minute: str = Form(...),
        revolutx_base_url: str = Form(""),
        revolutx_base_path: str = Form(""),
    ):
        _require_admin(request)

        base_currency = (base_currency or "EUR").upper().strip()
        try:
            starting_capital_f = float(str(starting_capital).replace(",", "."))
        except Exception:
            raise HTTPException(status_code=400, detail="starting_capital invalid")
        if starting_capital_f < 0:
            raise HTTPException(status_code=400, detail="starting_capital must be >= 0")
        if risk_mode not in RISK_PROFILES:
            raise HTTPException(status_code=400, detail="risk_mode invalid")
        try:
            scan_i = int(scan_interval_seconds)
            pairs_i = int(pairs_limit)
            hard_i = int(hard_close_minute)
        except Exception:
            raise HTTPException(status_code=400, detail="numeric fields invalid")
        if scan_i < 10 or scan_i > 3600:
            raise HTTPException(status_code=400, detail="scan_interval_seconds out of range")
        if pairs_i < 1 or pairs_i > 500:
            raise HTTPException(status_code=400, detail="pairs_limit out of range")
        if hard_i < 0 or hard_i > 59:
            raise HTTPException(status_code=400, detail="hard_close_minute out of range")

        store.update_settings(
            base_currency=base_currency,
            starting_capital=starting_capital_f,
            risk_mode=risk_mode,
            scan_interval_seconds=scan_i,
            pairs_limit=pairs_i,
            hard_close_minute=hard_i,
            revolutx_base_url=revolutx_base_url.strip(),
            revolutx_base_path=revolutx_base_path.strip(),
        )

        if on_settings_changed_cb:
            try:
                on_settings_changed_cb()
            except Exception:
                # Don't break setup page on callback errors
                pass

        token = request.query_params.get("token", "")
        body = f"""
        <div class="card">
          <h1>✅ Salvato</h1>
          <p class="muted">Impostazioni salvate nel DB. Torna alla home o chiudi la pagina.</p>
          <p><a href="/?token={token}">Torna alla home</a></p>
        </div>
        """
        return HTMLResponse(_html_page(body))

    return app

