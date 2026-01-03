import logging
import asyncio
import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters
from .config import config_manager
from .crypto_trader import TradingEngine
from .stock_monitor import StockMonitor
from .forex_monitor import ForexMonitor
from .cloud_manager import CloudManager
from .database import get_total_exposure, init_db, AuditLog, ForexWatch, ForexHolding

logger = logging.getLogger(__name__)

# States (simplified for Revolut X default)
REVX_API_KEY, REVX_PRIVATE_KEY, TEST_TRADE, CONFIRM_CAPITAL, STOCK_ALERTS, STOCK_MARKET, AGGRESSIVENESS, CONFIRM_START = range(8)

class BotInterface:
    def __init__(self, token):
        self.application = Application.builder().token(token).build()
        self.trader = TradingEngine(config_manager)
        self.stock_monitor = StockMonitor(config_manager)
        self.forex_monitor = ForexMonitor(config_manager)
        self.cloud_manager = CloudManager()
        
        # Initialize DB
        init_db()
        self.trader.initialize()

        self.setup_handlers()

    def setup_handlers(self):
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", self.start_wizard)],
            states={
                REVX_API_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.receive_revolutx_api_key)],
                REVX_PRIVATE_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.receive_revolutx_private_key)],
                TEST_TRADE: [MessageHandler(filters.Regex("^(RUN_TEST|SKIP)$"), self.test_trade_step)],
                CONFIRM_CAPITAL: [MessageHandler(filters.Regex("^(Yes|No)$"), self.confirm_capital)],
                STOCK_ALERTS: [MessageHandler(filters.Regex("^(Yes|No)$"), self.ask_stock_alerts)],
                STOCK_MARKET: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.choose_stock_market)],
                AGGRESSIVENESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.choose_aggressiveness)],
                CONFIRM_START: [MessageHandler(filters.Regex("^(START|CANCEL)$"), self.finish_setup)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel), CommandHandler("start", self.start_wizard)],
            allow_reentry=True,
        )

        self.application.add_handler(conv_handler)
        self.application.add_handler(CommandHandler("status", self.status))
        self.application.add_handler(CommandHandler("balance", self.balance))
        self.application.add_handler(CommandHandler("emergency_stop", self.emergency_stop))
        self.application.add_handler(CommandHandler("resume", self.resume))
        self.application.add_handler(CommandHandler("logs", self.logs))

        # Forex alerts (manual trading)
        self.application.add_handler(CommandHandler("forex_watch", self.forex_watch))
        self.application.add_handler(CommandHandler("forex_unwatch", self.forex_unwatch))
        self.application.add_handler(CommandHandler("forex_list", self.forex_list))
        self.application.add_handler(CommandHandler("forex_buy", self.forex_buy))
        self.application.add_handler(CommandHandler("forex_sell", self.forex_sell))
        self.application.add_handler(CommandHandler("forex_positions", self.forex_positions))

        # Job Queue
        self.job_queue = self.application.job_queue
        # Schedule regular jobs if configured
        if config_manager.is_configured:
            self.start_scheduled_jobs()

    async def start_wizard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        config_manager.set("admin_chat_id", chat_id)
        logger.info("Wizard started for chat_id=%s", chat_id)

        # Default to Revolut X + LIVE
        config_manager.set("exchange_id", "revolutx")
        config_manager.set("execution_mode", "live")
        config_manager.set("symbol", config_manager.get("symbol", "BTC_USDC"))
        
        await update.message.reply_text(
            "👋 Welcome!\n\n"
            "Default exchange: Revolut X (LIVE).\n\n"
            "Please enter your Revolut X API Key:",
            reply_markup=ReplyKeyboardRemove()
        )
        return REVX_API_KEY

    async def receive_revolutx_api_key(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        api_key = update.message.text.strip()
        config_manager.set("revolutx_api_key", api_key)
        await update.message.reply_text(
            "Private key (Ed25519) for signing:\n\n"
            "- Recommended: save it as a local file named 'private.pem' next to the project, then reply '-' here.\n"
            "- Or (less safe): paste the PEM content here (including -----BEGIN/END----- lines).",
            reply_markup=ReplyKeyboardRemove(),
        )
        return REVX_PRIVATE_KEY

    async def receive_revolutx_private_key(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        pem = update.message.text.strip()
        if pem != "-":
            config_manager.set("revolutx_private_key_pem", pem)

        await update.message.reply_text(
            "I will now run a LIVE connectivity test: BUY+SELL (~1 USDC) to verify the API works.\n"
            "Reply RUN_TEST (recommended) or SKIP:",
            reply_markup=ReplyKeyboardMarkup([["RUN_TEST", "SKIP"]], one_time_keyboard=True),
        )
        return TEST_TRADE

    async def test_trade_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        choice = update.message.text.strip().upper()
        if choice == "RUN_TEST":
            await update.message.reply_text("Running LIVE test trade... please wait.", reply_markup=ReplyKeyboardRemove())
            loop = asyncio.get_running_loop()

            # Re-init trader with provided Revolut X credentials
            self.trader.initialize()
            symbol = config_manager.get("symbol", "BTC_USDC")
            result = await loop.run_in_executor(None, lambda: self.trader.run_test_trade(symbol=symbol, quote_amount=1.0))
            await update.message.reply_text(result)

        await update.message.reply_text(
            "🔒 SAFETY CHECK: Your maximum trading capital is strictly limited to 100 USDC.\n"
            "Confirm strict 100 USDC limit?",
            reply_markup=ReplyKeyboardMarkup([["Yes", "No"]], one_time_keyboard=True),
        )
        return CONFIRM_CAPITAL

    async def confirm_capital(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.text == "No":
            await update.message.reply_text("⛔ Safety limit is mandatory. Setup cancelled.")
            return ConversationHandler.END
        
        config_manager.set("max_capital", 100.0)
        
        await update.message.reply_text(
            "Do you want Stock Market (Fiat) Alerts? (No automated trading, just alerts)",
            reply_markup=ReplyKeyboardMarkup([["Yes", "No"]], one_time_keyboard=True)
        )
        return STOCK_ALERTS

    async def ask_stock_alerts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.text == "No":
            config_manager.set("stock_alerts_enabled", False)
            return await self.finalize_setup_step(update)
        
        config_manager.set("stock_alerts_enabled", True)
        await update.message.reply_text(
            "Which market?",
            reply_markup=ReplyKeyboardMarkup([["US", "EU"]], one_time_keyboard=True)
        )
        return STOCK_MARKET

    async def choose_stock_market(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        config_manager.set("stock_market", update.message.text)
        await update.message.reply_text(
            "Alert Aggressiveness:",
            reply_markup=ReplyKeyboardMarkup([["Low", "Medium", "High"]], one_time_keyboard=True)
        )
        return AGGRESSIVENESS

    async def choose_aggressiveness(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        config_manager.set("alert_aggressiveness", update.message.text.lower())
        return await self.finalize_setup_step(update)

    async def finalize_setup_step(self, update: Update):
        await update.message.reply_text("⚙️ Provisioning Cloud Resources... (Setting up Static IP)")
        
        # Simulate provisioning
        # Run blocking provisioning in executor just in case
        loop = asyncio.get_running_loop()
        ip = await loop.run_in_executor(None, self.cloud_manager.provision_static_ip)
        config_manager.set("static_ip", ip)
        
        summary = (
            "✅ SETUP COMPLETE\n\n"
            f"🔹 Exchange: Revolut X\n"
            f"🔹 Exec Mode: LIVE\n"
            f"🔹 Symbol: {config_manager.get('symbol')}\n"
            f"🔹 Max Capital: 100 USDC\n"
            f"🔹 Stock Alerts: {config_manager.get('stock_alerts_enabled')}\n"
            f"🔹 Static IP: {ip}\n\n"
            "Ready to START?"
        )
        
        await update.message.reply_text(
            summary,
            reply_markup=ReplyKeyboardMarkup([["START", "CANCEL"]], one_time_keyboard=True)
        )
        return CONFIRM_START

    async def finish_setup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.text == "CANCEL":
            await update.message.reply_text("Cancelled.")
            return ConversationHandler.END
        
        config_manager.set("is_configured", True)
        self.trader.initialize()
        self.trader.is_running = True
        self.start_scheduled_jobs()
        
        await update.message.reply_text("🚀 Bot STARTED! I will notify you of any trades.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Operation cancelled.")
        return ConversationHandler.END

    def start_scheduled_jobs(self):
        # Remove existing jobs to avoid duplicates
        for job in self.job_queue.jobs():
            job.schedule_removal()
            
        chat_id = config_manager.get("admin_chat_id")
        if chat_id:
            # Pass chat_id to the callback via context if needed, or just access config in callback
            interval = int(config_manager.get("trade_interval_seconds", 60))
            self.job_queue.run_repeating(self.trade_job, interval=interval, first=10, chat_id=chat_id)
            
            if config_manager.get("stock_alerts_enabled"):
                self.job_queue.run_repeating(self.stock_job, interval=60*60, first=20, chat_id=chat_id) # Every hour

            if config_manager.get("forex_alerts_enabled", True):
                fx_interval = int(config_manager.get("forex_poll_interval_seconds", 60))
                self.job_queue.run_repeating(self.forex_job, interval=fx_interval, first=15, chat_id=chat_id)

    async def trade_job(self, context: ContextTypes.DEFAULT_TYPE):
        if not self.trader.is_running:
            return
        
        # Run synchronous trading logic in a separate thread
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, self.trader.execute_trade_cycle)
        
        if result and result != "No action":
            await context.bot.send_message(
                chat_id=context.job.chat_id,
                text=f"🤖 **Trade Executed**\n{result}"
            )
            
    async def stock_job(self, context: ContextTypes.DEFAULT_TYPE):
        loop = asyncio.get_running_loop()
        msg = await loop.run_in_executor(None, self.stock_monitor.check_market)
        
        if msg:
             await context.bot.send_message(chat_id=context.job.chat_id, text=msg)

    async def forex_job(self, context: ContextTypes.DEFAULT_TYPE):
        """
        1) If a watched forex symbol is rising fast -> alert to consider buying.
        2) If user marked a symbol as bought and it starts falling -> alert to consider selling.
        """
        if not config_manager.get("forex_alerts_enabled", True):
            return

        watches = list(ForexWatch.select().where(ForexWatch.is_active == True))
        if not watches:
            return

        cooldown_seconds = 10 * 60
        now = datetime.datetime.utcnow()

        for w in watches:
            signal = self.forex_monitor.detect_signal(
                w.symbol,
                lookback_bars=w.lookback_bars,
                rise_threshold_pct=w.rise_threshold_pct,
                fall_threshold_pct=w.fall_threshold_pct,
                interval=w.interval,
            )
            if not signal:
                continue

            # Rising: notify to consider buy
            if signal.direction == "RISE":
                if w.last_rise_alert_at and (now - w.last_rise_alert_at).total_seconds() < cooldown_seconds:
                    continue
                w.last_rise_alert_at = now
                w.save()
                await context.bot.send_message(
                    chat_id=context.job.chat_id,
                    text=(
                        f"📈 FOREX RISING ({w.symbol})\n"
                        f"Price: {signal.last}\n"
                        f"Move({w.lookback_bars} bars): +{signal.change_pct:.4f}%\n\n"
                        f"If you buy, tell me with:\n/forex_buy {w.symbol}"
                    ),
                )
                continue

            # Falling: only notify if the user said they're in a position
            holding = (
                ForexHolding.select()
                .where(ForexHolding.symbol == w.symbol, ForexHolding.is_open == True)
                .order_by(ForexHolding.bought_at.desc())
                .first()
            )
            if holding:
                if w.last_fall_alert_at and (now - w.last_fall_alert_at).total_seconds() < cooldown_seconds:
                    continue
                w.last_fall_alert_at = now
                w.save()
                await context.bot.send_message(
                    chat_id=context.job.chat_id,
                    text=(
                        f"📉 FOREX FALLING ({w.symbol})\n"
                        f"Price: {signal.last}\n"
                        f"Move({w.lookback_bars} bars): {signal.change_pct:.4f}%\n\n"
                        f"If you sell, tell me with:\n/forex_sell {w.symbol}"
                    ),
                )

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        status = "RUNNING" if self.trader.is_running else "PAUSED"
        ip = config_manager.get("static_ip")
        symbol = config_manager.get("symbol", "BTC_USDC")
        exchange_id = config_manager.get("exchange_id", "revolutx")
        mode = config_manager.get("execution_mode", "live")
        price = self.trader.last_price
        ts = self.trader.last_price_ts
        await update.message.reply_text(
            f"Status: {status}\n"
            f"Exchange: {exchange_id}\n"
            f"Mode: {mode}\n"
            f"Symbol: {symbol}\n"
            f"Last price: {price}\n"
            f"Last price ts: {ts}\n"
            f"IP: {ip}"
        )

    async def balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        exposure = get_total_exposure()
        await update.message.reply_text(f"Current Exposure: {exposure:.2f} USDC / 100.00 USDC")

    async def emergency_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = self.trader.emergency_stop()
        # self.job_queue.stop() # deprecated/not recommended to stop whole queue usually, better to just stop scheduling or have jobs check flag
        # But for emergency, stopping queue is fine or just setting flag
        self.trader.is_running = False
        await update.message.reply_text(f"🚨 EMERGENCY STOP TRIGGERED.\n{msg}")

    async def resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.trader.is_running = True
        self.start_scheduled_jobs()
        await update.message.reply_text("▶️ Resumed.")

    async def logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Fetch last 5 logs
        logs = AuditLog.select().order_by(AuditLog.timestamp.desc()).limit(5)
        msg = "📋 **Recent Logs:**\n\n"
        for l in logs:
            msg += f"{l.timestamp}: {l.action} - {l.details}\n"
        await update.message.reply_text(msg)

    async def forex_watch(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Usage: /forex_watch EURUSD=X [lookback_bars] [rise_pct] [fall_pct]
        """
        if not context.args:
            await update.message.reply_text("Usage: /forex_watch EURUSD=X [lookback_bars] [rise_pct] [fall_pct]")
            return

        symbol = context.args[0].strip()
        lookback = int(context.args[1]) if len(context.args) >= 2 else int(config_manager.get("forex_default_lookback_bars", 5))
        rise = float(context.args[2]) if len(context.args) >= 3 else float(config_manager.get("forex_default_rise_threshold_pct", 0.05))
        fall = float(context.args[3]) if len(context.args) >= 4 else float(config_manager.get("forex_default_fall_threshold_pct", 0.05))
        interval = str(config_manager.get("forex_default_interval", "1m"))

        obj, created = ForexWatch.get_or_create(symbol=symbol, defaults={
            "lookback_bars": lookback,
            "rise_threshold_pct": rise,
            "fall_threshold_pct": fall,
            "interval": interval,
            "is_active": True,
        })
        if not created:
            obj.lookback_bars = lookback
            obj.rise_threshold_pct = rise
            obj.fall_threshold_pct = fall
            obj.interval = interval
            obj.is_active = True
            obj.save()

        await update.message.reply_text(
            f"✅ Watching {symbol}\nlookback={lookback} bars, rise={rise}%, fall={fall}%, interval={interval}"
        )

    async def forex_unwatch(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /forex_unwatch EURUSD=X")
            return
        symbol = context.args[0].strip()
        q = ForexWatch.update(is_active=False).where(ForexWatch.symbol == symbol)
        q.execute()
        await update.message.reply_text(f"🛑 Unwatched {symbol}")

    async def forex_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        watches = list(ForexWatch.select().where(ForexWatch.is_active == True))
        if not watches:
            await update.message.reply_text("No active forex watches. Add one with /forex_watch EURUSD=X")
            return
        msg = "👀 Active forex watches:\n\n"
        for w in watches:
            msg += f"- {w.symbol} (lookback={w.lookback_bars}, rise={w.rise_threshold_pct}%, fall={w.fall_threshold_pct}%, interval={w.interval})\n"
        await update.message.reply_text(msg)

    async def forex_buy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /forex_buy EURUSD=X")
            return
        symbol = context.args[0].strip()
        last = self.forex_monitor.get_last_price(symbol, interval=str(config_manager.get("forex_default_interval", "1m")))
        ForexHolding.create(symbol=symbol, is_open=True, bought_price=last)
        await update.message.reply_text(f"✅ Marked as BOUGHT: {symbol}. I will alert you when it starts falling.")

    async def forex_sell(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /forex_sell EURUSD=X")
            return
        symbol = context.args[0].strip()
        q = ForexHolding.update(is_open=False).where(ForexHolding.symbol == symbol, ForexHolding.is_open == True)
        q.execute()
        await update.message.reply_text(f"✅ Marked as SOLD: {symbol}.")

    async def forex_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        holdings = list(ForexHolding.select().where(ForexHolding.is_open == True).order_by(ForexHolding.bought_at.desc()))
        if not holdings:
            await update.message.reply_text("No open forex positions marked. Use /forex_buy EURUSD=X")
            return
        msg = "💼 Open forex positions (manual):\n\n"
        for h in holdings:
            msg += f"- {h.symbol} (since {h.bought_at})\n"
        await update.message.reply_text(msg)

    def run(self):
        self.application.run_polling()
