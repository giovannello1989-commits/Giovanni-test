from __future__ import annotations

import asyncio
import logging
import os
import threading
import base64
from datetime import datetime, timezone
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from bot.config import RISK_PROFILES, AppConfig, is_within_operating_window, load_config
from bot.autotrade import LiveRevolutXExecutor, PaperExecutor, decide_autobuy
from bot.marketdata import MarketDataClient, create_market_data_client
from bot.revolutx import RevolutXClient
from bot.storage import Storage
from bot.strategy import compute_momentum_from_5m_candles, fmt_pct
from bot.web import create_web_app


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("bot")


RESET_CONFIRM_CB = "reset_confirm"
RESET_CANCEL_CB = "reset_cancel"

SETUP_START_CB = "setup_start"
SETUP_CANCEL_CB = "setup_cancel"

SETUP_BASE_PREFIX = "setup_base:"
SETUP_RISK_PREFIX = "setup_risk:"
SETUP_SCAN_PREFIX = "setup_scan:"
SETUP_PAIRS_PREFIX = "setup_pairs:"
SETUP_HARDMIN_PREFIX = "setup_hardmin:"
SETUP_CONFIRM_CB = "setup_confirm"

SETUP_STEP_NONE = None
SETUP_STEP_BASE = "base_currency"
SETUP_STEP_CAPITAL = "starting_capital"
SETUP_STEP_RISK = "risk_mode"
SETUP_STEP_SCAN = "scan_interval_seconds"
SETUP_STEP_PAIRS = "pairs_limit"
SETUP_STEP_HARDMIN = "hard_close_minute"
SETUP_STEP_CONFIRM = "confirm"


def _authorized(cfg: AppConfig, update: Update) -> bool:
    chat = update.effective_chat
    # If allowed chat id is not configured, authorization is handled by onboarding
    # (first /start becomes owner).
    if not chat:
        return False
    if cfg.telegram_allowed_chat_id is None:
        return True
    return chat.id == cfg.telegram_allowed_chat_id


async def _get_owner_chat_id(context: ContextTypes.DEFAULT_TYPE) -> int | None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    if cfg.telegram_allowed_chat_id is not None:
        return cfg.telegram_allowed_chat_id
    store: Storage = context.application.bot_data["store"]
    st = await asyncio.to_thread(store.get_settings)
    v = st.get("owner_chat_id")
    return int(v) if v is not None else None


def _money(x: float, cur: str) -> str:
    return f"{x:.2f} {cur}"


def _parse_float(s: str) -> float | None:
    try:
        return float(s.replace(",", "."))
    except Exception:
        return None


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    if not _authorized(cfg, update):
        return

    store: Storage = context.application.bot_data["store"]
    # If TELEGRAM_ALLOWED_CHAT_ID is not set, bind first /start chat as owner.
    if cfg.telegram_allowed_chat_id is None:
        owner = await _get_owner_chat_id(context)
        chat = update.effective_chat
        if owner is None and chat:
            await asyncio.to_thread(store.update_settings, owner_chat_id=chat.id)
            owner = chat.id
            await update.message.reply_text(
                f"✅ Registrazione completata. Questa chat è ora l’owner (chat_id={owner})."
            )
        # If someone else writes later, block.
        if owner is not None and chat and chat.id != owner:
            return

    st = await asyncio.to_thread(store.get_settings)
    risk = RISK_PROFILES.get(st["risk_mode"], RISK_PROFILES["aggressive"])

    now = datetime.now(cfg.tz)
    run_mode = (st.get("mode") or "session").lower()
    autotrade_enabled = bool(int(st.get("autotrade_enabled", 0)))
    autotrade_mode = st.get("autotrade_mode", "paper")
    cap_amt = st.get("autotrade_max_quote", 100.0)
    cap_cur = st.get("autotrade_quote_currency", "USDT")

    msg = (
        "*Revolut X AutoTrade Bot*\n\n"
        f"Stato:\n"
        f"- ora: `{now.isoformat(timespec='seconds')}`\n"
        f"- run mode: `{run_mode}` (always=24/7)\n"
        f"- scanner paused: `{bool(st['paused'])}`\n"
        f"- risk: `{risk.name}` (mom_1h≥{fmt_pct(risk.mom_1h_threshold)}, mom_15m≥{fmt_pct(risk.mom_15m_threshold)}, trailing={fmt_pct(risk.trailing_stop_pct)})\n"
        f"- autotrade: `{autotrade_enabled}` mode=`{autotrade_mode}` cap=`{cap_amt} {cap_cur}`\n\n"
        "Comandi principali:\n"
        "- /status\n"
        "- /wallet\n"
        "- /setmode always|session\n"
        "- /autotrade on|off\n"
        "- /autotrade mode paper|live\n"
        "- /autotrade cap <AMOUNT> <CUR>\n"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def _build_status_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    cfg: AppConfig = context.application.bot_data["cfg"]
    store: Storage = context.application.bot_data["store"]
    st = await asyncio.to_thread(store.get_settings)
    risk = RISK_PROFILES.get(st["risk_mode"], RISK_PROFILES["aggressive"])

    now = datetime.now(cfg.tz)
    within = is_within_operating_window(now, cfg.window_start, cfg.window_end)
    paused = bool(int(st.get("paused", 0)))
    run_mode = (st.get("mode") or "session").lower()
    effective_within = True if run_mode == "always" else within

    owner = await _get_owner_chat_id(context)
    positions = await asyncio.to_thread(store.list_positions)

    metrics: dict[str, Any] = context.application.bot_data.setdefault("metrics", {})
    scans_ok = int(metrics.get("scans_ok", 0))
    scans_err = int(metrics.get("scans_err", 0))
    signals_sent = int(metrics.get("signals_sent", 0))
    last_trade_action = metrics.get("last_trade_action")
    last_trade_ts = metrics.get("last_trade_ts")

    def _fmt_ts(v: Any) -> str:
        if not v:
            return "n/a"
        try:
            return datetime.fromtimestamp(float(v), tz=cfg.tz).isoformat(timespec="seconds")
        except Exception:
            return "n/a"

    last_pairs_count = metrics.get("last_pairs_count")
    why = []
    if paused:
        why.append("scanner in pausa")
    if run_mode != "always" and not within:
        why.append("fuori 09:00–20:00")
    if last_pairs_count in (0, None):
        why.append("pairs non disponibili (endpoint/parsing)")
    if not why:
        why.append("nessun segnale (soglie non raggiunte)")

    base_url = st.get("revolutx_base_url") or cfg.revolutx_base_url
    base_path = st.get("revolutx_base_path") or cfg.revolutx_base_path
    md_provider = context.application.bot_data.get("md_provider", "binance")
    md_quote = context.application.bot_data.get("md_quote", "EUR")

    # Plain text on purpose: avoids Telegram parse errors (HTML/Markdown entities).
    text = (
        "STATUS BOT\n"
        f"- ora: {now.isoformat(timespec='seconds')}\n"
        f"- owner chat_id: {owner}\n"
        f"- paused: {paused}\n"
        f"- finestra: {'OK' if effective_within else 'NO'} (09:00–20:00 {cfg.tz_name})\n"
        f"- risk: {risk.name} (mom_1h≥{fmt_pct(risk.mom_1h_threshold)}, mom_15m≥{fmt_pct(risk.mom_15m_threshold)}, trailing={fmt_pct(risk.trailing_stop_pct)})\n"
        "\n"
        "SCANNER\n"
        f"- last scan started: {_fmt_ts(metrics.get('last_scan_started'))}\n"
        f"- last scan completed: {_fmt_ts(metrics.get('last_scan_completed'))}\n"
        f"- last pairs count: {last_pairs_count if last_pairs_count is not None else 'n/a'}\n"
        f"- scans ok/err: {scans_ok}/{scans_err}\n"
        f"- last scan note: {metrics.get('last_scan_note') or 'n/a'}\n"
        "\n"
        "NOTIFICHE\n"
        f"- signals sent (runtime): {signals_sent}\n"
        f"- last signal: {_fmt_ts(metrics.get('last_signal_ts'))}\n"
        f"- perché potresti non riceverne: {'; '.join(why)}\n"
        f"- last trade action: {last_trade_action or 'n/a'} @ {_fmt_ts(last_trade_ts)}\n"
        "\n"
        "PORTFOLIO (manuale)\n"
        f"- posizioni aperte: {len(positions)}\n"
        "\n"
        "REVOLUT X\n"
        f"- base_url: {base_url}\n"
        f"- base_path: {base_path}\n"
        f"- api_key presente: {bool(cfg.revolutx_api_key)}\n"
        "\n"
        "MARKET DATA\n"
        f"- provider: {md_provider}\n"
        f"- quote: {md_quote}\n"
        "\n"
        "AUTOTRADE\n"
        f"- enabled: {bool(int(st.get('autotrade_enabled', 0)))}\n"
        f"- mode: {st.get('autotrade_mode', 'paper')}\n"
        f"- cap: {st.get('autotrade_max_quote', 100.0)} {st.get('autotrade_quote_currency', 'USDT')}\n"
        f"- run mode: {st.get('mode', 'session')} (session=09-20, always=24/7)\n"
    )
    last_error = metrics.get("last_error")
    if last_error:
        text += "\nULTIMO ERRORE\n" + str(last_error)[:800] + "\n"
    return text


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    if not _authorized(cfg, update):
        return
    owner = await _get_owner_chat_id(context)
    chat = update.effective_chat
    if owner is not None and chat and chat.id != owner:
        return
    await update.message.reply_text(await _build_status_text(context))

async def cmd_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    if not _authorized(cfg, update):
        return
    owner = await _get_owner_chat_id(context)
    chat = update.effective_chat
    if owner is not None and chat and chat.id != owner:
        return
    rx: RevolutXClient = context.application.bot_data["rx"]
    data = await asyncio.to_thread(rx.get_balances)
    if not isinstance(data, list):
        await update.message.reply_text("Wallet: non disponibile (balances non è una lista).")
        return
    # Show main currencies first
    wanted = ["USDT", "USD", "EUR", "BTC", "ETH", "SOL"]
    by_cur = {str(r.get("currency", "")).upper(): r for r in data if isinstance(r, dict)}
    lines = ["WALLET (Revolut X)"]
    for cur in wanted:
        r = by_cur.get(cur)
        if not r:
            continue
        lines.append(f"- {cur}: available={r.get('available')} reserved={r.get('reserved')}")
    # Show a few more non-zero
    extra = []
    for cur, r in by_cur.items():
        if cur in wanted:
            continue
        try:
            av = float(r.get("available") or 0)
        except Exception:
            continue
        if av <= 0:
            continue
        extra.append((av, cur))
    extra.sort(reverse=True)
    for av, cur in extra[:10]:
        lines.append(f"- {cur}: available={by_cur[cur].get('available')} reserved={by_cur[cur].get('reserved')}")
    await update.message.reply_text("\n".join(lines))


async def cmd_revxprobe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Probes common Revolut X REST API paths (read-only) to discover correct endpoints.
    """
    cfg: AppConfig = context.application.bot_data["cfg"]
    if not _authorized(cfg, update):
        return
    owner = await _get_owner_chat_id(context)
    chat = update.effective_chat
    if owner is not None and chat and chat.id != owner:
        return

    rx: RevolutXClient = context.application.bot_data["rx"]
    candidates = [
        "/api/1.0/balances",
        "/api/1.0/configuration/currencies",
        "/api/1.0/configuration/currency-pairs",
        "/api/1.0/pairs",
        "/api/1.0/symbols",
        "/api/1.0/instruments",
        "/api/1.0/markets",
        "/api/1.0/ticker",
        "/api/1.0/tickers",
        "/api/1.0/candles",
        "/api/1.0/klines",
        "/api/1.0/orders/active",
        "/api/1.0/orders/historical",
        "/api/1.0/orders",
        "/api/1.0/trades",
        "/api/1.0/trades/private/BTC-USD",
        "/api/1.0/trades/private/BTC-USDT",
    ]
    results = await asyncio.to_thread(rx.probe, candidates)
    lines = ["REVX PROBE (GET)"]
    lines.append(f"- auth_ready: {await asyncio.to_thread(rx.auth_ready)}")
    for r in results:
        lines.append(f"- {r['path']}: {r['status']} {'' if not r['sample'] else str(r['sample'])[:60]}")
    lines.append("\nSe vedi 200 su balances/pairs/candles, mi hai trovato gli endpoint corretti.")
    await update.message.reply_text("\n".join(lines))


async def cmd_revxpub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Prints the public key PEM derived from the private key loaded on the server.
    Paste this into Revolut X API key creation (public key field).
    """
    cfg: AppConfig = context.application.bot_data["cfg"]
    if not _authorized(cfg, update):
        return
    owner = await _get_owner_chat_id(context)
    chat = update.effective_chat
    if owner is not None and chat and chat.id != owner:
        return
    rx: RevolutXClient = context.application.bot_data["rx"]
    pem = await asyncio.to_thread(rx.derived_public_key_pem)
    if not pem:
        await update.message.reply_text("Nessuna private key caricata/leggibile sul server.")
        return
    await update.message.reply_text("PUBLIC KEY (derived from server private key):\n" + pem)
async def cmd_setmode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    if not _authorized(cfg, update):
        return
    owner = await _get_owner_chat_id(context)
    chat = update.effective_chat
    if owner is not None and chat and chat.id != owner:
        return
    if not context.args:
        await update.message.reply_text("Uso: `/setmode session|always`", parse_mode=ParseMode.MARKDOWN)
        return
    mode = context.args[0].lower().strip()
    if mode not in ("session", "always"):
        await update.message.reply_text("Valore non valido. Usa: session|always")
        return
    store: Storage = context.application.bot_data["store"]
    await asyncio.to_thread(store.update_settings, mode=mode)
    await update.message.reply_text(f"OK. Mode impostato: {mode}.")


async def cmd_autotrade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /autotrade on|off
    /autotrade mode paper|live
    /autotrade cap 100 USDT
    """
    cfg: AppConfig = context.application.bot_data["cfg"]
    if not _authorized(cfg, update):
        return
    owner = await _get_owner_chat_id(context)
    chat = update.effective_chat
    if owner is not None and chat and chat.id != owner:
        return

    store: Storage = context.application.bot_data["store"]
    if not context.args:
        st = await asyncio.to_thread(store.get_settings)
        await update.message.reply_text(
            "Uso:\n"
            "- /autotrade on|off\n"
            "- /autotrade mode paper|live\n"
            "- /autotrade cap 100 USDT\n\n"
            f"Stato: enabled={bool(int(st.get('autotrade_enabled',0)))}, mode={st.get('autotrade_mode','paper')}, cap={st.get('autotrade_max_quote',100)} {st.get('autotrade_quote_currency','USDT')}"
        )
        return

    sub = context.args[0].lower()
    if sub in ("on", "off"):
        enabled = 1 if sub == "on" else 0
        await asyncio.to_thread(store.update_settings, autotrade_enabled=enabled)
        if enabled == 1:
            # Force 24/7 as requested
            await asyncio.to_thread(store.update_settings, mode="always")
        st = await asyncio.to_thread(store.get_settings)
        await update.message.reply_text(
            f"OK. autotrade_enabled={bool(enabled)} (mode={st.get('mode','session')})."
        )
        return

    if sub == "mode":
        if len(context.args) < 2:
            await update.message.reply_text("Uso: `/autotrade mode paper|live`", parse_mode=ParseMode.MARKDOWN)
            return
        m = context.args[1].lower().strip()
        if m not in ("paper", "live"):
            await update.message.reply_text("Valore non valido. Usa: paper|live")
            return
        if m == "live":
            # Safety: require explicit env confirmation, because Revolut X trading endpoints/signature must be correct.
            if os.getenv("ALLOW_LIVE_TRADING", "0") != "1":
                await update.message.reply_text(
                    "LIVE trading è bloccato per sicurezza.\n"
                    "Per abilitarlo devi impostare su Railway: `ALLOW_LIVE_TRADING=1` (e avere auth/endpoints Revolut X corretti)."
                )
                return
        await asyncio.to_thread(store.update_settings, autotrade_mode=m)
        await update.message.reply_text(f"OK. autotrade_mode={m}.")
        return

    if sub == "cap":
        if len(context.args) < 3:
            await update.message.reply_text("Uso: `/autotrade cap 100 USDT`", parse_mode=ParseMode.MARKDOWN)
            return
        amt = _parse_float(context.args[1])
        cur = context.args[2].upper()
        if amt is None or amt <= 0:
            await update.message.reply_text("Importo non valido.")
            return
        await asyncio.to_thread(store.update_settings, autotrade_max_quote=float(amt), autotrade_quote_currency=cur)
        await update.message.reply_text(f"OK. Cap autotrade: {amt:.2f} {cur}.")
        return

    await update.message.reply_text("Comando non riconosciuto. Usa: on|off|mode|cap")


async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    if not _authorized(cfg, update):
        return
    owner = await _get_owner_chat_id(context)
    chat = update.effective_chat
    if owner is not None and chat and chat.id != owner:
        return
    store: Storage = context.application.bot_data["store"]
    st = await asyncio.to_thread(store.get_settings)
    risk = RISK_PROFILES.get(st["risk_mode"], RISK_PROFILES["aggressive"])
    msg = (
        "*Config*\n"
        f"- paused: `{bool(st['paused'])}`\n"
        f"- risk: `{risk.name}`\n"
        f"- base_currency: `{st['base_currency']}`\n"
        f"- starting_capital: `{st['starting_capital']}`\n"
        f"- scan_interval_seconds: `{st.get('scan_interval_seconds', cfg.scan_interval_seconds)}`\n"
        f"- pairs_limit: `{st.get('pairs_limit', cfg.pairs_limit)}`\n"
        f"- signal_cooldown_seconds: `{cfg.signal_cooldown_seconds}`\n"
        f"- window: `09:00–20:00 {cfg.tz_name}`\n"
        f"- hard_close: `19:{st.get('hard_close_minute', cfg.hard_close_time.minute):02d}`\n"
        f"- revolutx_base_url: `{st.get('revolutx_base_url') or cfg.revolutx_base_url}`\n"
        f"- revolutx_base_path: `{st.get('revolutx_base_path') or cfg.revolutx_base_path}`\n"
        "\n"
        "_Nota: se Revolut X cambia path, aggiorna REVOLUTX_BASE_URL/REVOLUTX_BASE_PATH e i path in bot/revolutx.py._\n"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    if not _authorized(cfg, update):
        return
    owner = await _get_owner_chat_id(context)
    chat = update.effective_chat
    if owner is not None and chat and chat.id != owner:
        return
    store: Storage = context.application.bot_data["store"]
    await asyncio.to_thread(store.update_settings, paused=1)
    await update.message.reply_text("Scansione segnali: *PAUSA*.", parse_mode=ParseMode.MARKDOWN)


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    if not _authorized(cfg, update):
        return
    owner = await _get_owner_chat_id(context)
    chat = update.effective_chat
    if owner is not None and chat and chat.id != owner:
        return
    store: Storage = context.application.bot_data["store"]
    await asyncio.to_thread(store.update_settings, paused=0)
    await update.message.reply_text("Scansione segnali: *ATTIVA*.", parse_mode=ParseMode.MARKDOWN)


async def cmd_setcapital(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    if not _authorized(cfg, update):
        return
    owner = await _get_owner_chat_id(context)
    chat = update.effective_chat
    if owner is not None and chat and chat.id != owner:
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Uso: `/setcapital 100 EUR`", parse_mode=ParseMode.MARKDOWN)
        return
    amount = _parse_float(context.args[0])
    cur = context.args[1].upper()
    if amount is None or amount < 0:
        await update.message.reply_text("Importo non valido.")
        return
    store: Storage = context.application.bot_data["store"]
    await asyncio.to_thread(store.update_settings, starting_capital=amount, base_currency=cur)
    await update.message.reply_text(f"OK. Capitale iniziale impostato a {_money(amount, cur)}.")


async def cmd_setrisk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    if not _authorized(cfg, update):
        return
    owner = await _get_owner_chat_id(context)
    chat = update.effective_chat
    if owner is not None and chat and chat.id != owner:
        return
    if not context.args:
        await update.message.reply_text("Uso: `/setrisk aggressive|normal|conservative`", parse_mode=ParseMode.MARKDOWN)
        return
    mode = context.args[0].lower()
    if mode not in RISK_PROFILES:
        await update.message.reply_text("Valore non valido. Usa: aggressive|normal|conservative")
        return
    store: Storage = context.application.bot_data["store"]
    await asyncio.to_thread(store.update_settings, risk_mode=mode)
    r = RISK_PROFILES[mode]
    await update.message.reply_text(
        f"OK. Risk mode: *{r.name}* (mom_1h≥{fmt_pct(r.mom_1h_threshold)}, mom_15m≥{fmt_pct(r.mom_15m_threshold)}, trailing={fmt_pct(r.trailing_stop_pct)}).",
        parse_mode=ParseMode.MARKDOWN,
    )


def _parse_trade_cmd(args: list[str]) -> tuple[str, float, float] | None:
    """
    Expected:
      /buy SYMBOL AMOUNT at PRICE
    Example:
      /buy BTC-EUR 20 at 43000
    """
    if len(args) < 4:
        return None
    symbol = args[0].upper()
    amount = _parse_float(args[1])
    if amount is None:
        return None
    if args[2].lower() != "at":
        return None
    price = _parse_float(args[3])
    if price is None or price <= 0:
        return None
    return symbol, float(amount), float(price)


async def cmd_buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    if not _authorized(cfg, update):
        return
    owner = await _get_owner_chat_id(context)
    chat = update.effective_chat
    if owner is not None and chat and chat.id != owner:
        return
    parsed = _parse_trade_cmd(context.args)
    if not parsed:
        await update.message.reply_text("Uso: `/buy BTC-EUR 20 at 43000`", parse_mode=ParseMode.MARKDOWN)
        return
    symbol, amount, price = parsed
    store: Storage = context.application.bot_data["store"]
    st = await asyncio.to_thread(store.get_settings)
    await asyncio.to_thread(store.add_buy, symbol=symbol, amount_base=amount, price=price)
    qty = amount / price
    await update.message.reply_text(
        f"Registrato BUY: {symbol} • {_money(amount, st['base_currency'])} @ {price:.8g} (qty≈{qty:.8g})"
    )


async def cmd_sell(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    if not _authorized(cfg, update):
        return
    owner = await _get_owner_chat_id(context)
    chat = update.effective_chat
    if owner is not None and chat and chat.id != owner:
        return
    parsed = _parse_trade_cmd(context.args)
    if not parsed:
        await update.message.reply_text("Uso: `/sell BTC-EUR 20 at 43000`", parse_mode=ParseMode.MARKDOWN)
        return
    symbol, amount, price = parsed
    store: Storage = context.application.bot_data["store"]
    st = await asyncio.to_thread(store.get_settings)
    realized = await asyncio.to_thread(store.add_sell, symbol=symbol, amount_base=amount, price=price)
    qty = amount / price
    await update.message.reply_text(
        f"Registrato SELL: {symbol} • {_money(amount, st['base_currency'])} @ {price:.8g} (qty≈{qty:.8g})\n"
        f"PnL realizzato (stima): {_money(realized, st['base_currency'])}"
    )


async def cmd_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    if not _authorized(cfg, update):
        return
    owner = await _get_owner_chat_id(context)
    chat = update.effective_chat
    if owner is not None and chat and chat.id != owner:
        return

    store: Storage = context.application.bot_data["store"]
    st = await asyncio.to_thread(store.get_settings)
    positions = await asyncio.to_thread(store.list_positions)
    if not positions:
        await update.message.reply_text("Nessuna posizione aperta.")
        return

    client: RevolutXClient = context.application.bot_data["rx"]
    total_unreal = 0.0
    lines = ["*Portfolio (posizioni aperte)*"]
    for p in positions:
        last_price = await asyncio.to_thread(client.get_last_price, p.symbol)
        if last_price is None:
            lines.append(f"- {p.symbol}: qty={p.qty:.8g}, entry={p.avg_entry:.8g}, peak={p.peak_price:.8g} (last: n/a)")
            continue
        unreal = (last_price - p.avg_entry) * p.qty
        total_unreal += unreal
        lines.append(
            f"- {p.symbol}: qty={p.qty:.8g}, entry={p.avg_entry:.8g}, peak={p.peak_price:.8g}, last={last_price:.8g}, PnL≈{_money(unreal, st['base_currency'])}"
        )

    lines.append(f"\nTotale PnL non realizzato (stima): {_money(total_unreal, st['base_currency'])}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    if not _authorized(cfg, update):
        return
    owner = await _get_owner_chat_id(context)
    chat = update.effective_chat
    if owner is not None and chat and chat.id != owner:
        return
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("CONFERMA RESET", callback_data=RESET_CONFIRM_CB),
                InlineKeyboardButton("ANNULLA", callback_data=RESET_CANCEL_CB),
            ]
        ]
    )
    await update.message.reply_text(
        "Sei sicuro di voler fare RESET? Cancellerò trades/posizioni e ripristinerò le impostazioni di default.",
        reply_markup=kb,
    )


async def on_reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    if not _authorized(cfg, update):
        return
    owner = await _get_owner_chat_id(context)
    chat = update.effective_chat
    if owner is not None and chat and chat.id != owner:
        return
    q = update.callback_query
    if not q:
        return
    await q.answer()
    if q.data == RESET_CANCEL_CB:
        await q.edit_message_text("Reset annullato.")
        return
    if q.data == RESET_CONFIRM_CB:
        store: Storage = context.application.bot_data["store"]
        await asyncio.to_thread(store.reset_all)
        # Reset signal throttles in memory
        context.application.bot_data["last_signal_by_symbol"] = {}
        context.application.bot_data["last_mom15_sign"] = {}
        await q.edit_message_text("Reset completato.")

def _setup_keyboard_base() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("EUR", callback_data=f"{SETUP_BASE_PREFIX}EUR"),
                InlineKeyboardButton("USD", callback_data=f"{SETUP_BASE_PREFIX}USD"),
                InlineKeyboardButton("GBP", callback_data=f"{SETUP_BASE_PREFIX}GBP"),
            ],
            [InlineKeyboardButton("Annulla", callback_data=SETUP_CANCEL_CB)],
        ]
    )


def _setup_keyboard_risk() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Aggressive", callback_data=f"{SETUP_RISK_PREFIX}aggressive"),
                InlineKeyboardButton("Normal", callback_data=f"{SETUP_RISK_PREFIX}normal"),
                InlineKeyboardButton("Conservative", callback_data=f"{SETUP_RISK_PREFIX}conservative"),
            ],
            [InlineKeyboardButton("Annulla", callback_data=SETUP_CANCEL_CB)],
        ]
    )


def _setup_keyboard_scan() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("30s", callback_data=f"{SETUP_SCAN_PREFIX}30"),
                InlineKeyboardButton("60s", callback_data=f"{SETUP_SCAN_PREFIX}60"),
                InlineKeyboardButton("120s", callback_data=f"{SETUP_SCAN_PREFIX}120"),
            ],
            [InlineKeyboardButton("Annulla", callback_data=SETUP_CANCEL_CB)],
        ]
    )


def _setup_keyboard_pairs() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("20", callback_data=f"{SETUP_PAIRS_PREFIX}20"),
                InlineKeyboardButton("50", callback_data=f"{SETUP_PAIRS_PREFIX}50"),
                InlineKeyboardButton("100", callback_data=f"{SETUP_PAIRS_PREFIX}100"),
            ],
            [InlineKeyboardButton("Annulla", callback_data=SETUP_CANCEL_CB)],
        ]
    )


def _setup_keyboard_hardmin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("19:45", callback_data=f"{SETUP_HARDMIN_PREFIX}45"),
                InlineKeyboardButton("19:50", callback_data=f"{SETUP_HARDMIN_PREFIX}50"),
                InlineKeyboardButton("19:55", callback_data=f"{SETUP_HARDMIN_PREFIX}55"),
            ],
            [InlineKeyboardButton("Annulla", callback_data=SETUP_CANCEL_CB)],
        ]
    )


async def cmd_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    if not _authorized(cfg, update):
        return
    owner = await _get_owner_chat_id(context)
    chat = update.effective_chat
    if owner is not None and chat and chat.id != owner:
        return
    store: Storage = context.application.bot_data["store"]
    await asyncio.to_thread(store.set_onboarding, SETUP_STEP_BASE, {})
    await update.message.reply_text(
        "*Setup guidato*\nStep 1/6: scegli la valuta base.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_setup_keyboard_base(),
    )


async def _setup_advance_prompt(context: ContextTypes.DEFAULT_TYPE, step: str) -> None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    if step == SETUP_STEP_CAPITAL:
        await context.application.bot.send_message(
            chat_id=cfg.telegram_allowed_chat_id,
            text="Step 2/6: scrivi il *capitale iniziale* (solo numero). Esempio: `1000`",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif step == SETUP_STEP_RISK:
        await context.application.bot.send_message(
            chat_id=cfg.telegram_allowed_chat_id,
            text="Step 3/6: scegli il profilo rischio (soglie momentum + trailing).",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_setup_keyboard_risk(),
        )
    elif step == SETUP_STEP_SCAN:
        await context.application.bot.send_message(
            chat_id=cfg.telegram_allowed_chat_id,
            text="Step 4/6: ogni quanto scansionare i simboli?",
            reply_markup=_setup_keyboard_scan(),
        )
    elif step == SETUP_STEP_PAIRS:
        await context.application.bot.send_message(
            chat_id=cfg.telegram_allowed_chat_id,
            text="Step 5/6: quanti simboli scansionare (per performance)?",
            reply_markup=_setup_keyboard_pairs(),
        )
    elif step == SETUP_STEP_HARDMIN:
        await context.application.bot.send_message(
            chat_id=cfg.telegram_allowed_chat_id,
            text="Step 6/6: a che ora vuoi l’alert *CHIUDI TUTTO*?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_setup_keyboard_hardmin(),
        )
    elif step == SETUP_STEP_CONFIRM:
        store: Storage = context.application.bot_data["store"]
        ob = await asyncio.to_thread(store.get_onboarding)
        data = ob.get("data", {})
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Conferma e salva", callback_data=SETUP_CONFIRM_CB)],
                [InlineKeyboardButton("Annulla", callback_data=SETUP_CANCEL_CB)],
            ]
        )
        await context.application.bot.send_message(
            chat_id=cfg.telegram_allowed_chat_id,
            text=(
                "*Riepilogo setup*\n"
                f"- base_currency: `{data.get('base_currency')}`\n"
                f"- starting_capital: `{data.get('starting_capital')}`\n"
                f"- risk_mode: `{data.get('risk_mode')}`\n"
                f"- scan_interval_seconds: `{data.get('scan_interval_seconds')}`\n"
                f"- pairs_limit: `{data.get('pairs_limit')}`\n"
                f"- hard_close_minute: `{data.get('hard_close_minute')}`\n"
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb,
        )


async def on_setup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    if not _authorized(cfg, update):
        return
    owner = await _get_owner_chat_id(context)
    chat = update.effective_chat
    if owner is not None and chat and chat.id != owner:
        return
    q = update.callback_query
    if not q:
        return
    await q.answer()

    store: Storage = context.application.bot_data["store"]

    if q.data == SETUP_START_CB:
        await asyncio.to_thread(store.set_onboarding, SETUP_STEP_BASE, {})
        await q.edit_message_text(
            "Setup guidato: Step 1/6: scegli la valuta base.",
            reply_markup=_setup_keyboard_base(),
        )
        return

    if q.data == SETUP_CANCEL_CB:
        await asyncio.to_thread(store.clear_onboarding)
        await q.edit_message_text("Setup annullato.")
        return

    ob = await asyncio.to_thread(store.get_onboarding)
    data = ob.get("data", {})

    if q.data.startswith(SETUP_BASE_PREFIX):
        cur = q.data.split(":", 1)[1].upper()
        data["base_currency"] = cur
        await asyncio.to_thread(store.set_onboarding, SETUP_STEP_CAPITAL, data)
        await q.edit_message_text(f"Valuta base impostata: {cur}")
        await _setup_advance_prompt(context, SETUP_STEP_CAPITAL)
        return

    if q.data.startswith(SETUP_RISK_PREFIX):
        mode = q.data.split(":", 1)[1].lower()
        if mode not in RISK_PROFILES:
            return
        data["risk_mode"] = mode
        await asyncio.to_thread(store.set_onboarding, SETUP_STEP_SCAN, data)
        await q.edit_message_text(f"Risk mode impostato: {mode}")
        await _setup_advance_prompt(context, SETUP_STEP_SCAN)
        return

    if q.data.startswith(SETUP_SCAN_PREFIX):
        v = _parse_float(q.data.split(":", 1)[1])
        if v is None or v <= 0:
            return
        data["scan_interval_seconds"] = int(v)
        await asyncio.to_thread(store.set_onboarding, SETUP_STEP_PAIRS, data)
        await q.edit_message_text(f"Scan interval impostato: {int(v)}s")
        await _setup_advance_prompt(context, SETUP_STEP_PAIRS)
        return

    if q.data.startswith(SETUP_PAIRS_PREFIX):
        v = _parse_float(q.data.split(":", 1)[1])
        if v is None or v <= 0:
            return
        data["pairs_limit"] = int(v)
        await asyncio.to_thread(store.set_onboarding, SETUP_STEP_HARDMIN, data)
        await q.edit_message_text(f"Pairs limit impostato: {int(v)}")
        await _setup_advance_prompt(context, SETUP_STEP_HARDMIN)
        return

    if q.data.startswith(SETUP_HARDMIN_PREFIX):
        v = _parse_float(q.data.split(":", 1)[1])
        if v is None or v < 0 or v >= 60:
            return
        data["hard_close_minute"] = int(v)
        await asyncio.to_thread(store.set_onboarding, SETUP_STEP_CONFIRM, data)
        await q.edit_message_text(f"Hard-close alert impostato: 19:{int(v):02d}")
        await _setup_advance_prompt(context, SETUP_STEP_CONFIRM)
        return

    if q.data == SETUP_CONFIRM_CB:
        # Save into settings + advise which env vars remain required
        st = await asyncio.to_thread(store.get_settings)
        base = data.get("base_currency", st.get("base_currency", "EUR"))
        capital = float(data.get("starting_capital", st.get("starting_capital", 0.0)))
        risk_mode = data.get("risk_mode", st.get("risk_mode", "aggressive"))
        await asyncio.to_thread(
            store.update_settings,
            base_currency=base,
            starting_capital=capital,
            risk_mode=risk_mode,
        )

        # Apply runtime-only settings by updating cfg in memory for this process.
        # Note: scan interval/pairs limit/hard-close minute are loaded from ENV at startup; we keep them in onboarding summary
        # and show the user what to set if they want to persist via ENV.
        await asyncio.to_thread(store.clear_onboarding)
        await q.edit_message_text(
            "Setup salvato ✅\n\n"
            "Se vuoi rendere persistenti anche *scan interval*, *pairs limit* e *hard-close minute* tra deploy, "
            "impostali come ENV: `SCAN_INTERVAL_SECONDS`, `PAIRS_LIMIT`, `HARD_CLOSE_MINUTE`.",
        )
        return


async def on_setup_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    if not _authorized(cfg, update):
        return
    owner = await _get_owner_chat_id(context)
    chat = update.effective_chat
    if owner is not None and chat and chat.id != owner:
        return
    if not update.message or not update.message.text:
        return

    store: Storage = context.application.bot_data["store"]
    ob = await asyncio.to_thread(store.get_onboarding)
    step = ob.get("step")
    data = ob.get("data", {})
    if step != SETUP_STEP_CAPITAL:
        return

    amt = _parse_float(update.message.text.strip())
    if amt is None or amt < 0:
        await update.message.reply_text("Valore non valido. Scrivi solo un numero, es. `1000`", parse_mode=ParseMode.MARKDOWN)
        return

    data["starting_capital"] = float(amt)
    await asyncio.to_thread(store.set_onboarding, SETUP_STEP_RISK, data)
    await update.message.reply_text(f"Capitale iniziale impostato: {amt:.2f}")
    await _setup_advance_prompt(context, SETUP_STEP_RISK)


async def _compute_pnl_snapshot(
    cfg: AppConfig,
    context: ContextTypes.DEFAULT_TYPE,
) -> dict[str, Any]:
    """
    Returns a snapshot dict with realized/unrealized PnL estimates.
    """
    store: Storage = context.application.bot_data["store"]
    client: RevolutXClient = context.application.bot_data["rx"]
    st = await asyncio.to_thread(store.get_settings)
    trades = await asyncio.to_thread(store.list_all_trades)
    positions = await asyncio.to_thread(store.list_positions)

    realized_total = sum(t.realized_pnl or 0.0 for t in trades if t.side == "SELL")

    unreal_total = 0.0
    priced_positions = 0
    for p in positions:
        last_price = await asyncio.to_thread(client.get_last_price, p.symbol)
        if last_price is None:
            continue
        unreal_total += (last_price - p.avg_entry) * p.qty
        priced_positions += 1

    equity = float(st["starting_capital"]) + realized_total + unreal_total
    return {
        "base_currency": st["base_currency"],
        "starting_capital": float(st["starting_capital"]),
        "realized_total": realized_total,
        "unreal_total": unreal_total,
        "equity": equity,
        "priced_positions": priced_positions,
        "open_positions": positions,
    }


async def scan_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    store: Storage = context.application.bot_data["store"]
    st = await asyncio.to_thread(store.get_settings)
    if int(st["paused"]) == 1:
        return

    now = datetime.now(cfg.tz)
    run_mode = (st.get("mode") or "session").lower()
    if run_mode != "always":
        if not is_within_operating_window(now, cfg.window_start, cfg.window_end):
            return

    risk = RISK_PROFILES.get(st["risk_mode"], RISK_PROFILES["aggressive"])
    md: MarketDataClient = context.application.bot_data["md"]
    paper_exec: PaperExecutor = context.application.bot_data["paper_exec"]
    live_exec: LiveRevolutXExecutor = context.application.bot_data["live_exec"]

    metrics: dict[str, Any] = context.application.bot_data.setdefault("metrics", {})
    metrics["last_scan_started"] = now.timestamp()

    # Load pairs from market data provider.
    try:
        pairs = await asyncio.to_thread(md.get_pairs)
    except Exception as e:
        metrics["scans_err"] = int(metrics.get("scans_err", 0)) + 1
        metrics["last_error"] = f"get_pairs error: {repr(e)}"
        metrics["last_scan_note"] = "get_pairs exception"
        metrics["last_scan_completed"] = datetime.now(cfg.tz).timestamp()
        return

    metrics["last_pairs_count"] = len(pairs) if pairs is not None else None
    if not pairs:
        metrics["scans_ok"] = int(metrics.get("scans_ok", 0)) + 1
        metrics["last_scan_note"] = "get_pairs returned empty"
        metrics["last_scan_completed"] = datetime.now(cfg.tz).timestamp()
        return
    pairs_limit = int(st.get("pairs_limit", cfg.pairs_limit))
    pairs = pairs[:pairs_limit]

    last_signal_by_symbol: dict[str, float] = context.application.bot_data.setdefault("last_signal_by_symbol", {})
    last_mom15_sign: dict[str, int] = context.application.bot_data.setdefault("last_mom15_sign", {})

    autotrade_on = int(st.get("autotrade_enabled", 0)) == 1
    quote_cap = float(st.get("autotrade_max_quote", 100.0))
    quote_cur = str(st.get("autotrade_quote_currency", "USDT")).upper()
    exec_mode = str(st.get("autotrade_mode", "paper")).lower()
    executor = live_exec if exec_mode == "live" else paper_exec

    # Track best candidate this scan (so we open at most one position per scan).
    best_candidate = None  # (symbol, sig)

    # Scan momentum for candidate BUY signals
    try:
        for symbol in pairs:
            candles = await asyncio.to_thread(md.get_candles, symbol, "5m", 13)
            sig = compute_momentum_from_5m_candles(symbol, candles)
            if not sig:
                continue

            if sig.mom_1h >= risk.mom_1h_threshold and sig.mom_15m >= risk.mom_15m_threshold:
                # Keep best candidate for auto-buy (highest 15m momentum)
                if autotrade_on and symbol.endswith(f"-{quote_cur}"):
                    if best_candidate is None or sig.mom_15m > best_candidate[1].mom_15m:
                        best_candidate = (symbol, sig)

                now_ts = now.timestamp()
                last_ts = float(last_signal_by_symbol.get(symbol, 0.0))
                if now_ts - last_ts >= cfg.signal_cooldown_seconds:
                    last_signal_by_symbol[symbol] = now_ts
                    text = (
                        "*CANDIDATE BUY*\n"
                        f"- symbol: `{symbol}`\n"
                        f"- price: `{sig.last_price:.8g}`\n"
                        f"- momentum 1h: `{fmt_pct(sig.mom_1h)}`\n"
                        f"- momentum 15m: `{fmt_pct(sig.mom_15m)}`\n\n"
                        "_È un segnale quantitativo (non certezza). Usa stop aggressivi e ricorda: chiudi entro le 20:00._"
                    )
                    owner = await _get_owner_chat_id(context)
                    if owner is not None:
                        await context.application.bot.send_message(
                            chat_id=owner,
                            text=text,
                            parse_mode=ParseMode.MARKDOWN,
                        )
                        metrics["signals_sent"] = int(metrics.get("signals_sent", 0)) + 1
                        metrics["last_signal_ts"] = now_ts

            # Track sign of mom_15m (for reversal alerts on open positions)
            mom_sign = 1 if sig.mom_15m > 0 else (-1 if sig.mom_15m < 0 else 0)
            last_mom15_sign[symbol] = mom_sign
    except Exception as e:
        metrics["scans_err"] = int(metrics.get("scans_err", 0)) + 1
        metrics["last_error"] = f"scan loop error: {repr(e)}"
        metrics["last_scan_note"] = "scan loop exception"
        metrics["last_scan_completed"] = datetime.now(cfg.tz).timestamp()
        return

    # Execute at most one AUTO BUY per scan (single-position mode enforced in decide_autobuy).
    if autotrade_on and best_candidate is not None:
        symbol, sig = best_candidate
        decision = decide_autobuy(
            store=store,
            symbol=symbol,
            quote_cap_total=quote_cap,
            quote_currency=quote_cur,
            min_trade_quote=10.0,
        )
        if decision.action == "BUY" and decision.quote_amount:
            res = await asyncio.to_thread(executor.buy_quote, symbol, float(decision.quote_amount))
            owner = await _get_owner_chat_id(context)
            if owner is not None:
                if res.ok:
                    metrics["last_trade_action"] = f"BUY {symbol} {decision.quote_amount:.2f} {quote_cur} ({exec_mode})"
                    metrics["last_trade_ts"] = now.timestamp()
                    await context.application.bot.send_message(
                        chat_id=owner,
                        text=(
                            "AUTO BUY\n"
                            f"- symbol: {symbol}\n"
                            f"- spent: {decision.quote_amount:.2f} {quote_cur} (cap {quote_cap:.2f})\n"
                            f"- price: {res.fill_price if res.fill_price is not None else 'n/a'}\n"
                            f"- reason: mom_1h={fmt_pct(sig.mom_1h)}>= {fmt_pct(risk.mom_1h_threshold)} AND mom_15m={fmt_pct(sig.mom_15m)}>= {fmt_pct(risk.mom_15m_threshold)}\n"
                            f"- order_id: {res.order_id}\n"
                        ),
                    )
                else:
                    metrics["last_trade_action"] = f"BUY FAILED {symbol} ({exec_mode})"
                    metrics["last_trade_ts"] = now.timestamp()
                    await context.application.bot.send_message(
                        chat_id=owner,
                        text=f"AUTO BUY FAILED\n- symbol: {symbol}\n- error: {res.error}",
                    )

    # Evaluate trailing stops / reversal alerts for OPEN positions
    positions = await asyncio.to_thread(store.list_positions)
    for p in positions:
        last_price = await asyncio.to_thread(md.get_last_price, p.symbol)
        if last_price is None:
            continue

        # Update peak
        if last_price > p.peak_price:
            await asyncio.to_thread(store.update_peak, p.symbol, last_price)
            peak = last_price
        else:
            peak = p.peak_price

        # Trailing stop alert
        if last_price <= peak * (1.0 - risk.trailing_stop_pct):
            owner = await _get_owner_chat_id(context)
            if owner is None:
                continue
            # If autotrade enabled: auto-sell
            if int(st.get("autotrade_enabled", 0)) == 1:
                exec_mode = str(st.get("autotrade_mode", "paper")).lower()
                ex = live_exec if exec_mode == "live" else paper_exec
                res = await asyncio.to_thread(ex.sell_all, p.symbol)
                if res.ok:
                    # realized PnL is stored by storage.add_sell; compute quick % vs entry
                    pnl_quote = (last_price - p.avg_entry) * p.qty
                    pct = ((last_price - p.avg_entry) / p.avg_entry) if p.avg_entry else 0.0
                    metrics["last_trade_action"] = f"SELL {p.symbol} ({exec_mode}) pnl≈{pnl_quote:+.2f}"
                    metrics["last_trade_ts"] = now.timestamp()
                    await context.application.bot.send_message(
                        chat_id=owner,
                        text=(
                            "AUTO SELL (trailing stop)\n"
                            f"- symbol: {p.symbol}\n"
                            f"- last: {last_price:.8g}\n"
                            f"- entry: {p.avg_entry:.8g}\n"
                            f"- peak: {peak:.8g}\n"
                            f"- pnl≈ {pnl_quote:+.2f} ({pct*100:+.2f}%)\n"
                            f"- reason: last <= peak*(1-{risk.trailing_stop_pct*100:.2f}%)\n"
                            f"- order_id: {res.order_id}\n"
                        ),
                    )
                    continue
                else:
                    await context.application.bot.send_message(
                        chat_id=owner,
                        text=f"AUTO SELL FAILED\n- symbol: {p.symbol}\n- error: {res.error}",
                    )
            await context.application.bot.send_message(
                chat_id=owner,
                text=(
                    "*EXIT ALERT (trailing stop)*\n"
                    f"- symbol: `{p.symbol}`\n"
                    f"- last: `{last_price:.8g}`\n"
                    f"- peak: `{peak:.8g}`\n"
                    f"- trailing: `{fmt_pct(risk.trailing_stop_pct)}`\n\n"
                    "_Il bot non può chiudere posizioni: chiudi manualmente se necessario._"
                ),
                parse_mode=ParseMode.MARKDOWN,
            )

        # Reversal: mom_15m negative after being positive (best-effort)
        candles = await asyncio.to_thread(md.get_candles, p.symbol, "5m", 13)
        sig = compute_momentum_from_5m_candles(p.symbol, candles)
        if sig:
            prev = last_mom15_sign.get(p.symbol, 0)
            cur = 1 if sig.mom_15m > 0 else (-1 if sig.mom_15m < 0 else 0)
            last_mom15_sign[p.symbol] = cur
            if prev > 0 and cur < 0:
                owner = await _get_owner_chat_id(context)
                if owner is None:
                    continue
                await context.application.bot.send_message(
                    chat_id=owner,
                    text=(
                        "*EXIT ALERT (reversal 15m)*\n"
                        f"- symbol: `{p.symbol}`\n"
                        f"- momentum 15m: `{fmt_pct(sig.mom_15m)}`\n\n"
                        "_Il bot non può chiudere posizioni: chiudi manualmente se necessario._"
                    ),
                    parse_mode=ParseMode.MARKDOWN,
                )

    metrics["scans_ok"] = int(metrics.get("scans_ok", 0)) + 1
    metrics["last_scan_note"] = "scan completed"
    metrics["last_scan_completed"] = datetime.now(cfg.tz).timestamp()


async def status_ping_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    owner = await _get_owner_chat_id(context)
    if owner is None:
        return
    store: Storage = context.application.bot_data["store"]
    st = await asyncio.to_thread(store.get_settings)
    run_mode = (st.get("mode") or "session").lower()
    always = os.getenv("STATUS_PING_ALWAYS", "0") == "1" or run_mode == "always" or int(st.get("autotrade_enabled", 0)) == 1
    now = datetime.now(cfg.tz)
    if not always and not is_within_operating_window(now, cfg.window_start, cfg.window_end):
        return
    await context.application.bot.send_message(chat_id=owner, text=await _build_status_text(context))

async def hourly_report_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Hourly operational report: wallet snapshot + open positions + last actions.
    """
    cfg: AppConfig = context.application.bot_data["cfg"]
    owner = await _get_owner_chat_id(context)
    if owner is None:
        return
    store: Storage = context.application.bot_data["store"]
    st = await asyncio.to_thread(store.get_settings)
    if int(st.get("autotrade_enabled", 0)) != 1 and (st.get("mode") or "session") != "always":
        return
    rx: RevolutXClient = context.application.bot_data["rx"]
    balances = await asyncio.to_thread(rx.get_balances)
    md: MarketDataClient = context.application.bot_data["md"]
    positions = await asyncio.to_thread(store.list_positions)
    metrics: dict[str, Any] = context.application.bot_data.setdefault("metrics", {})

    lines = ["REPORT ORARIO"]
    lines.append(f"- ora: {datetime.now(cfg.tz).isoformat(timespec='seconds')}")
    lines.append(f"- autotrade: {bool(int(st.get('autotrade_enabled',0)))} mode={st.get('autotrade_mode','paper')} cap={st.get('autotrade_max_quote')} {st.get('autotrade_quote_currency')}")
    lines.append(f"- last action: {metrics.get('last_trade_action','n/a')}")
    if isinstance(balances, list):
        by_cur = {str(r.get('currency','')).upper(): r for r in balances if isinstance(r, dict)}
        for cur in ["USDT", "USD"]:
            if cur in by_cur:
                lines.append(f"- wallet {cur}: available={by_cur[cur].get('available')} reserved={by_cur[cur].get('reserved')}")
    # Positions + PnL snapshot
    if not positions:
        lines.append("- posizioni aperte: 0")
    else:
        lines.append(f"- posizioni aperte: {len(positions)}")
        for p in positions[:10]:
            last = await asyncio.to_thread(md.get_last_price, p.symbol)
            if last is None:
                lines.append(f"  - {p.symbol}: qty={p.qty:.6g} entry={p.avg_entry:.6g} (last n/a)")
                continue
            pnl = (last - p.avg_entry) * p.qty
            pct = ((last - p.avg_entry) / p.avg_entry) * 100 if p.avg_entry else 0.0
            lines.append(f"  - {p.symbol}: qty={p.qty:.6g} entry={p.avg_entry:.6g} last={last:.6g} pnl≈{pnl:+.2f} ({pct:+.2f}%)")
    await context.application.bot.send_message(chat_id=owner, text="\n".join(lines))


async def hard_close_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    store: Storage = context.application.bot_data["store"]
    positions = await asyncio.to_thread(store.list_positions)
    if not positions:
        return
    st = await asyncio.to_thread(store.get_settings)
    hard_min = int(st.get("hard_close_minute", cfg.hard_close_time.minute))
    text = (
        "*CHIUDI TUTTO ORA*\n"
        f"Sono le 19:{hard_min:02d} ({cfg.tz_name}). Hai posizioni aperte:\n"
        + "\n".join([f"- `{p.symbol}` qty≈{p.qty:.8g}" for p in positions])
        + "\n\n_Il bot non può chiudere: chiudi manualmente entro le 20:00._"
    )
    owner = await _get_owner_chat_id(context)
    if owner is None:
        return
    await context.application.bot.send_message(chat_id=owner, text=text, parse_mode=ParseMode.MARKDOWN)


async def recap_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    store: Storage = context.application.bot_data["store"]

    st = await asyncio.to_thread(store.get_settings)
    base = st["base_currency"]

    now_local = datetime.now(cfg.tz)
    start_local = datetime(year=now_local.year, month=now_local.month, day=now_local.day, tzinfo=cfg.tz)
    start_utc = start_local.astimezone(timezone.utc).isoformat()
    trades_today = await asyncio.to_thread(store.list_trades_since_utc, start_utc)
    realized_today = sum(t.realized_pnl or 0.0 for t in trades_today if t.side == "SELL")

    snap = await _compute_pnl_snapshot(cfg, context)
    realized_total = float(snap["realized_total"])
    unreal_total = float(snap["unreal_total"])

    trade_lines = []
    for t in trades_today:
        rp = "" if t.realized_pnl is None else f" pnl={t.realized_pnl:+.2f}"
        trade_lines.append(f"- {t.ts_utc}: {t.side} {t.symbol} amount={t.amount_base:.2f} price={t.price:.8g}{rp}")

    recap = (
        "*Recap giornaliero (20:00)*\n"
        f"- Trades oggi: `{len(trades_today)}`\n"
        + ("(nessuno)\n" if not trade_lines else "\n".join(trade_lines) + "\n")
        + f"\n*PnL stimato*\n"
        f"- Realizzato oggi (solo SELL): `{_money(realized_today, base)}`\n"
        f"- Realizzato totale: `{_money(realized_total, base)}`\n"
        f"- Non realizzato (snapshot): `{_money(unreal_total, base)}`\n"
        f"- Equity stimata: `{_money(float(snap['equity']), base)}`\n"
        "\n_Note: il non realizzato è uno snapshot a fine giornata (dipende dall’ultimo prezzo disponibile)._"
    )

    owner = await _get_owner_chat_id(context)
    if owner is None:
        return
    await context.application.bot.send_message(
        chat_id=owner,
        text=recap,
        parse_mode=ParseMode.MARKDOWN,
    )

    positions = await asyncio.to_thread(store.list_positions)
    if positions:
        await context.application.bot.send_message(
            chat_id=owner,
            text=(
                "*EMERGENZA: posizioni ancora aperte alle 20:00*\n"
                + "\n".join([f"- `{p.symbol}` qty≈{p.qty:.8g}" for p in positions])
                + "\n\n_Il bot non può chiudere: chiudi manualmente._"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )


def build_app(cfg: AppConfig) -> Application:
    store = Storage(cfg.db_path)
    # Bootstrap RevolutX base url/path from settings if present (non-secrets)
    st = store.get_settings()
    base_url = st.get("revolutx_base_url") or cfg.revolutx_base_url
    base_path = st.get("revolutx_base_path") or cfg.revolutx_base_path
    private_pem = os.getenv("REVOLUTX_ED25519_PRIVATE_KEY_PEM")
    if not private_pem:
        b64 = os.getenv("REVOLUTX_ED25519_PRIVATE_KEY_PEM_B64")
        if b64:
            try:
                private_pem = base64.b64decode(b64.encode("utf-8")).decode("utf-8")
            except Exception:
                private_pem = None

    rx = RevolutXClient(
        base_url=base_url,
        base_path=base_path,
        api_key=cfg.revolutx_api_key,
        private_key_pem=private_pem,
        timeout_seconds=cfg.revolutx_timeout_seconds,
    )

    # Market data provider (default: Binance public, no key)
    md_provider = os.getenv("MARKET_DATA_PROVIDER", "binance")
    md_quote = os.getenv("MARKET_DATA_QUOTE", st.get("base_currency", "EUR")) or "EUR"
    md = create_market_data_client(
        md_provider,
        quote=md_quote,
        timeout_seconds=cfg.revolutx_timeout_seconds,
        revolutx_base_url=base_url,
        revolutx_base_path=base_path,
        revolutx_api_key=cfg.revolutx_api_key,
    )

    paper_exec = PaperExecutor(md=md, store=store)
    live_exec = LiveRevolutXExecutor(rx_client=rx, store=store, md=md)

    app = Application.builder().token(cfg.telegram_bot_token).build()
    app.bot_data["cfg"] = cfg
    app.bot_data["store"] = store
    app.bot_data["rx"] = rx
    app.bot_data["md"] = md
    app.bot_data["md_provider"] = md_provider
    app.bot_data["md_quote"] = md_quote
    app.bot_data["paper_exec"] = paper_exec
    app.bot_data["live_exec"] = live_exec
    app.bot_data["last_signal_by_symbol"] = {}
    app.bot_data["last_mom15_sign"] = {}
    app.bot_data["metrics"] = {}

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("config", cmd_config))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("setcapital", cmd_setcapital))
    app.add_handler(CommandHandler("setrisk", cmd_setrisk))
    app.add_handler(CommandHandler("buy", cmd_buy))
    app.add_handler(CommandHandler("sell", cmd_sell))
    app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("revxprobe", cmd_revxprobe))
    app.add_handler(CommandHandler("revxpub", cmd_revxpub))
    app.add_handler(CommandHandler("wallet", cmd_wallet))
    app.add_handler(CommandHandler("setmode", cmd_setmode))
    app.add_handler(CommandHandler("autotrade", cmd_autotrade))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("setup", cmd_setup))
    app.add_handler(CallbackQueryHandler(on_reset_callback, pattern=f"^{RESET_CONFIRM_CB}$|^{RESET_CANCEL_CB}$"))
    app.add_handler(CallbackQueryHandler(on_setup_callback, pattern=r"^(setup_|setup_base:|setup_risk:|setup_scan:|setup_pairs:|setup_hardmin:)"))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), on_setup_text))

    # Scheduling
    jq = app.job_queue
    scan_interval = int(st.get("scan_interval_seconds", cfg.scan_interval_seconds))
    hard_min = int(st.get("hard_close_minute", cfg.hard_close_time.minute))
    hard_close_time = cfg.hard_close_time.replace(minute=hard_min)
    jq.run_repeating(scan_job, interval=scan_interval, first=5, name="scan")
    jq.run_daily(hard_close_job, time=hard_close_time, name="hard_close")
    jq.run_daily(recap_job, time=cfg.recap_time, name="recap")
    status_every_minutes = int(os.getenv("STATUS_PING_MINUTES", "30") or "30")
    jq.run_repeating(
        status_ping_job,
        interval=max(60, status_every_minutes * 60),
        first=15,
        name="status_ping",
    )
    jq.run_repeating(hourly_report_job, interval=3600, first=60, name="hourly_report")

    return app


def main() -> None:
    # If Telegram token is missing but web setup is enabled, keep the service alive
    # and expose a small page that tells what is missing.
    if os.getenv("ENABLE_WEB_SETUP", "0") == "1" and not (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("telegram_bot_token")):
        import uvicorn
        from fastapi import FastAPI
        from fastapi.responses import HTMLResponse

        app_web = FastAPI(docs_url=None, redoc_url=None)

        @app_web.get("/", response_class=HTMLResponse)
        async def _missing():
            return HTMLResponse(
                "<h2>Bot non avviato: manca TELEGRAM_BOT_TOKEN</h2>"
                "<p>Imposta su Railway (Variables) <code>TELEGRAM_BOT_TOKEN</code> e fai Redeploy.</p>"
            )

        web_port = int(os.getenv("PORT") or os.getenv("WEB_PORT") or "8080")
        web_host = os.getenv("WEB_HOST", "0.0.0.0")
        logger.error("Missing TELEGRAM_BOT_TOKEN. Starting web-only helper on port=%s.", web_port)
        uvicorn.run(app_web, host=web_host, port=web_port, log_level="info")
        return

    cfg = load_config()
    app = build_app(cfg)
    logger.info("Bot starting. TZ=%s window=09:00-20:00 allowed_chat_id=%s", cfg.tz_name, cfg.telegram_allowed_chat_id)

    # Optional web setup wizard (frontend + server)
    if os.getenv("ENABLE_WEB_SETUP", "0") == "1":
        store: Storage = app.bot_data["store"]

        def _run_web():
            import uvicorn

            web_port = int(os.getenv("PORT") or os.getenv("WEB_PORT") or "8080")
            web_host = os.getenv("WEB_HOST", "0.0.0.0")
            web_app = create_web_app(store)
            uvicorn.run(web_app, host=web_host, port=web_port, log_level="info")

        t = threading.Thread(target=_run_web, daemon=True)
        t.start()
        logger.info("Web setup enabled on port=%s (set SETUP_ADMIN_TOKEN).", os.getenv("PORT") or os.getenv("WEB_PORT") or "8080")

    app.run_polling(close_loop=False, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

