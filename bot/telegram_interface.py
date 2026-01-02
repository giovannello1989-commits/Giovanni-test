import logging
import asyncio
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters
from .config import config_manager
from .crypto_trader import TradingEngine
from .stock_monitor import StockMonitor
from .cloud_manager import CloudManager
from .database import get_total_exposure, init_db, AuditLog

logger = logging.getLogger(__name__)

# States
EXCHANGE_ID, API_KEY, API_SECRET, EXECUTION_MODE, CONFIRM_CAPITAL, STOCK_ALERTS, STOCK_MARKET, AGGRESSIVENESS, CONFIRM_START = range(9)

class BotInterface:
    def __init__(self, token):
        self.application = Application.builder().token(token).build()
        self.trader = TradingEngine(config_manager)
        self.stock_monitor = StockMonitor(config_manager)
        self.cloud_manager = CloudManager()
        
        # Initialize DB
        init_db()
        self.trader.initialize()

        self.setup_handlers()

    def setup_handlers(self):
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", self.start_wizard)],
            states={
                EXCHANGE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.receive_exchange_id)],
                API_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.receive_api_key)],
                API_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.receive_api_secret)],
                EXECUTION_MODE: [MessageHandler(filters.Regex("^(PAPER|LIVE)$"), self.receive_execution_mode)],
                CONFIRM_CAPITAL: [MessageHandler(filters.Regex("^(Yes|No)$"), self.confirm_capital)],
                STOCK_ALERTS: [MessageHandler(filters.Regex("^(Yes|No)$"), self.ask_stock_alerts)],
                STOCK_MARKET: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.choose_stock_market)],
                AGGRESSIVENESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.choose_aggressiveness)],
                CONFIRM_START: [MessageHandler(filters.Regex("^(START|CANCEL)$"), self.finish_setup)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)],
        )

        self.application.add_handler(conv_handler)
        self.application.add_handler(CommandHandler("status", self.status))
        self.application.add_handler(CommandHandler("balance", self.balance))
        self.application.add_handler(CommandHandler("emergency_stop", self.emergency_stop))
        self.application.add_handler(CommandHandler("resume", self.resume))
        self.application.add_handler(CommandHandler("logs", self.logs))

        # Job Queue
        self.job_queue = self.application.job_queue
        # Schedule regular jobs if configured
        if config_manager.is_configured:
            self.start_scheduled_jobs()

    async def start_wizard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        config_manager.set("admin_chat_id", chat_id)
        
        await update.message.reply_text(
            "👋 Welcome to your Automated Trading Bot!\n\n"
            "I will guide you through the setup. NO technical knowledge required.\n\n"
            "First, choose your exchange (ccxt id).\n"
            "Examples: kraken, binance, coinbase, okx\n\n"
            "Reply with the exchange id (default: kraken):",
            reply_markup=ReplyKeyboardRemove()
        )
        return EXCHANGE_ID

    async def receive_exchange_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        exchange_id = update.message.text.strip().lower() or "kraken"
        config_manager.set("exchange_id", exchange_id)
        await update.message.reply_text(
            "Now enter your Exchange API Key.\n\n"
            "If you only want REAL market data but NO live trading, you can send '-' to skip.",
            reply_markup=ReplyKeyboardRemove()
        )
        return API_KEY

    async def receive_api_key(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        api_key = update.message.text.strip()
        if api_key == "-":
            api_key = ""
        config_manager.set("exchange_api_key", api_key)
        
        await update.message.reply_text(
            "Now enter your Exchange API Secret.\n\n"
            "If you skipped the key, send '-' to skip.",
            reply_markup=ReplyKeyboardRemove()
        )
        return API_SECRET

    async def receive_api_secret(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        api_secret = update.message.text.strip()
        if api_secret == "-":
            api_secret = ""
        config_manager.set("exchange_api_secret", api_secret)

        await update.message.reply_text(
            "Choose execution mode:\n"
            "- PAPER: logs + DB only (no real orders)\n"
            "- LIVE: sends real market orders via the exchange API\n\n"
            "Reply with PAPER or LIVE:",
            reply_markup=ReplyKeyboardMarkup([["PAPER", "LIVE"]], one_time_keyboard=True)
        )
        return EXECUTION_MODE

    async def receive_execution_mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        mode = update.message.text.strip().upper()
        config_manager.set("execution_mode", "live" if mode == "LIVE" else "paper")
        await update.message.reply_text(
            "🔒 SAFETY CHECK: Your maximum trading capital is strictly limited to 100 USDC.\n"
            "Confirm strict 100 USDC limit?",
            reply_markup=ReplyKeyboardMarkup([["Yes", "No"]], one_time_keyboard=True)
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
            f"🔹 Exchange: {config_manager.get('exchange_id')}\n"
            f"🔹 Exec Mode: {config_manager.get('execution_mode')}\n"
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

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        status = "RUNNING" if self.trader.is_running else "PAUSED"
        ip = config_manager.get("static_ip")
        symbol = config_manager.get("symbol", "BTC/USDT")
        exchange_id = config_manager.get("exchange_id", "kraken")
        mode = config_manager.get("execution_mode", "paper")
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

    def run(self):
        self.application.run_polling()
