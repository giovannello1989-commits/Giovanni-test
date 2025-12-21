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
    ContextTypes,
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
    app.add_handler(CallbackQueryHandler(on_reset_callback))

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

