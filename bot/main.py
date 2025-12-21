from __future__ import annotations

import asyncio
import logging
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
from bot.revolutx import RevolutXClient
from bot.storage import Storage
from bot.strategy import compute_momentum_from_5m_candles, fmt_pct


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
    return bool(chat and chat.id == cfg.telegram_allowed_chat_id)


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
    st = await asyncio.to_thread(store.get_settings)
    risk = RISK_PROFILES.get(st["risk_mode"], RISK_PROFILES["aggressive"])

    # If user hasn't configured starting capital yet, offer setup wizard.
    if float(st.get("starting_capital", 0.0)) <= 0.0:
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Inizia setup guidato", callback_data=SETUP_START_CB)],
            ]
        )
        await update.message.reply_text(
            "Prima configurazione: vuoi impostare capitale/valuta/risk con un wizard step-by-step?",
            reply_markup=kb,
        )

    now = datetime.now(cfg.tz)
    msg = (
        "*Revolut X Momentum Bot (read-only)*\n\n"
        "- Nessun trading automatico: solo segnali.\n"
        "- Finestra operativa: 09:00–20:00 (Europe/Rome).\n"
        "- Alert hard-close: 19:{hard_min:02d}\n"
        "- Recap: 20:00\n\n"
        f"*Stato*\n"
        f"- Ora: `{now.isoformat(timespec='seconds')}`\n"
        f"- Paused: `{bool(st['paused'])}`\n"
        f"- Risk: `{risk.name}` (mom_1h≥{fmt_pct(risk.mom_1h_threshold)}, mom_15m≥{fmt_pct(risk.mom_15m_threshold)}, trailing={fmt_pct(risk.trailing_stop_pct)})\n"
        f"- Base currency: `{st['base_currency']}`\n"
        f"- Starting capital: `{st['starting_capital']}`\n\n"
        "Comandi: /setcapital, /setrisk, /buy, /sell, /portfolio, /config, /pause, /resume, /reset\n"
    ).format(hard_min=cfg.hard_close_time.minute)
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    if not _authorized(cfg, update):
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
        f"- scan_interval_seconds: `{cfg.scan_interval_seconds}`\n"
        f"- pairs_limit: `{cfg.pairs_limit}`\n"
        f"- signal_cooldown_seconds: `{cfg.signal_cooldown_seconds}`\n"
        f"- window: `09:00–20:00 {cfg.tz_name}`\n"
        f"- hard_close: `19:{cfg.hard_close_time.minute:02d}`\n"
        f"- revolutx_base_url: `{cfg.revolutx_base_url}`\n"
        f"- revolutx_base_path: `{cfg.revolutx_base_path}`\n"
        "\n"
        "_Nota: se Revolut X cambia path, aggiorna REVOLUTX_BASE_URL/REVOLUTX_BASE_PATH e i path in bot/revolutx.py._\n"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    if not _authorized(cfg, update):
        return
    store: Storage = context.application.bot_data["store"]
    await asyncio.to_thread(store.update_settings, paused=1)
    await update.message.reply_text("Scansione segnali: *PAUSA*.", parse_mode=ParseMode.MARKDOWN)


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    if not _authorized(cfg, update):
        return
    store: Storage = context.application.bot_data["store"]
    await asyncio.to_thread(store.update_settings, paused=0)
    await update.message.reply_text("Scansione segnali: *ATTIVA*.", parse_mode=ParseMode.MARKDOWN)


async def cmd_setcapital(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    if not _authorized(cfg, update):
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
    if not is_within_operating_window(now, cfg.window_start, cfg.window_end):
        return

    risk = RISK_PROFILES.get(st["risk_mode"], RISK_PROFILES["aggressive"])
    client: RevolutXClient = context.application.bot_data["rx"]

    # Load pairs (read-only). If endpoint mismatch, it'll return [] and we just skip.
    pairs = await asyncio.to_thread(client.get_pairs)
    if not pairs:
        return
    pairs = pairs[: cfg.pairs_limit]

    last_signal_by_symbol: dict[str, float] = context.application.bot_data.setdefault("last_signal_by_symbol", {})
    last_mom15_sign: dict[str, int] = context.application.bot_data.setdefault("last_mom15_sign", {})

    # Scan momentum for candidate BUY signals
    for symbol in pairs:
        candles = await asyncio.to_thread(client.get_candles, symbol, "5m", None, None, 13)
        sig = compute_momentum_from_5m_candles(symbol, candles)
        if not sig:
            continue

        if sig.mom_1h >= risk.mom_1h_threshold and sig.mom_15m >= risk.mom_15m_threshold:
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
                await context.application.bot.send_message(
                    chat_id=cfg.telegram_allowed_chat_id,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN,
                )

        # Track sign of mom_15m (for reversal alerts on open positions)
        mom_sign = 1 if sig.mom_15m > 0 else (-1 if sig.mom_15m < 0 else 0)
        last_mom15_sign[symbol] = mom_sign

    # Evaluate trailing stops / reversal alerts for OPEN positions
    positions = await asyncio.to_thread(store.list_positions)
    for p in positions:
        last_price = await asyncio.to_thread(client.get_last_price, p.symbol)
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
            await context.application.bot.send_message(
                chat_id=cfg.telegram_allowed_chat_id,
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
        candles = await asyncio.to_thread(client.get_candles, p.symbol, "5m", None, None, 13)
        sig = compute_momentum_from_5m_candles(p.symbol, candles)
        if sig:
            prev = last_mom15_sign.get(p.symbol, 0)
            cur = 1 if sig.mom_15m > 0 else (-1 if sig.mom_15m < 0 else 0)
            last_mom15_sign[p.symbol] = cur
            if prev > 0 and cur < 0:
                await context.application.bot.send_message(
                    chat_id=cfg.telegram_allowed_chat_id,
                    text=(
                        "*EXIT ALERT (reversal 15m)*\n"
                        f"- symbol: `{p.symbol}`\n"
                        f"- momentum 15m: `{fmt_pct(sig.mom_15m)}`\n\n"
                        "_Il bot non può chiudere posizioni: chiudi manualmente se necessario._"
                    ),
                    parse_mode=ParseMode.MARKDOWN,
                )


async def hard_close_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: AppConfig = context.application.bot_data["cfg"]
    store: Storage = context.application.bot_data["store"]
    positions = await asyncio.to_thread(store.list_positions)
    if not positions:
        return
    text = (
        "*CHIUDI TUTTO ORA*\n"
        f"Sono le 19:{cfg.hard_close_time.minute:02d} ({cfg.tz_name}). Hai posizioni aperte:\n"
        + "\n".join([f"- `{p.symbol}` qty≈{p.qty:.8g}" for p in positions])
        + "\n\n_Il bot non può chiudere: chiudi manualmente entro le 20:00._"
    )
    await context.application.bot.send_message(chat_id=cfg.telegram_allowed_chat_id, text=text, parse_mode=ParseMode.MARKDOWN)


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

    await context.application.bot.send_message(
        chat_id=cfg.telegram_allowed_chat_id,
        text=recap,
        parse_mode=ParseMode.MARKDOWN,
    )

    positions = await asyncio.to_thread(store.list_positions)
    if positions:
        await context.application.bot.send_message(
            chat_id=cfg.telegram_allowed_chat_id,
            text=(
                "*EMERGENZA: posizioni ancora aperte alle 20:00*\n"
                + "\n".join([f"- `{p.symbol}` qty≈{p.qty:.8g}" for p in positions])
                + "\n\n_Il bot non può chiudere: chiudi manualmente._"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )


def build_app(cfg: AppConfig) -> Application:
    store = Storage(cfg.db_path)
    rx = RevolutXClient(
        base_url=cfg.revolutx_base_url,
        base_path=cfg.revolutx_base_path,
        api_key=cfg.revolutx_api_key,
        timeout_seconds=cfg.revolutx_timeout_seconds,
    )

    app = Application.builder().token(cfg.telegram_bot_token).build()
    app.bot_data["cfg"] = cfg
    app.bot_data["store"] = store
    app.bot_data["rx"] = rx
    app.bot_data["last_signal_by_symbol"] = {}
    app.bot_data["last_mom15_sign"] = {}

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("config", cmd_config))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("setcapital", cmd_setcapital))
    app.add_handler(CommandHandler("setrisk", cmd_setrisk))
    app.add_handler(CommandHandler("buy", cmd_buy))
    app.add_handler(CommandHandler("sell", cmd_sell))
    app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("setup", cmd_setup))
    app.add_handler(CallbackQueryHandler(on_reset_callback, pattern=f"^{RESET_CONFIRM_CB}$|^{RESET_CANCEL_CB}$"))
    app.add_handler(CallbackQueryHandler(on_setup_callback, pattern=r"^(setup_|setup_base:|setup_risk:|setup_scan:|setup_pairs:|setup_hardmin:)"))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), on_setup_text))

    # Scheduling
    jq = app.job_queue
    jq.run_repeating(scan_job, interval=cfg.scan_interval_seconds, first=5, name="scan")
    jq.run_daily(hard_close_job, time=cfg.hard_close_time, name="hard_close")
    jq.run_daily(recap_job, time=cfg.recap_time, name="recap")

    return app


def main() -> None:
    cfg = load_config()
    app = build_app(cfg)
    logger.info("Bot starting. TZ=%s window=09:00-20:00 allowed_chat_id=%s", cfg.tz_name, cfg.telegram_allowed_chat_id)
    app.run_polling(close_loop=False, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

