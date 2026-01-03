import logging
import threading
import time
from pathlib import Path

from flask import Flask, redirect, render_template, request, url_for

from .config import config_manager
from .crypto_trader import TradingEngine
from .database import AuditLog, get_total_exposure, init_db

logger = logging.getLogger(__name__)


class BotRunner:
    def __init__(self):
        init_db()
        self.engine = TradingEngine(config_manager)
        self.engine.initialize()

        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.is_running = False

    def start(self):
        if self.is_running:
            return
        self._stop.clear()
        self.is_running = True
        self._thread = threading.Thread(target=self._loop, name="bot-runner", daemon=True)
        self._thread.start()
        AuditLog.create(action="START", details="Local web start", capital_exposure=get_total_exposure())

    def stop(self):
        if not self.is_running:
            return
        self.is_running = False
        self._stop.set()
        AuditLog.create(action="STOP", details="Local web stop", capital_exposure=get_total_exposure())

    def trade_once(self) -> str:
        self.engine.initialize()
        result = self.engine.execute_trade_cycle()
        AuditLog.create(action="MANUAL", details=f"trade_once: {result}", capital_exposure=get_total_exposure())
        return result

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.engine.initialize()
                result = self.engine.execute_trade_cycle()
                if result and result != "No action":
                    AuditLog.create(action="CYCLE", details=result, capital_exposure=get_total_exposure())
            except Exception as e:
                AuditLog.create(action="ERROR", details=str(e), capital_exposure=get_total_exposure())

            interval = int(config_manager.get("trade_interval_seconds", 60))
            self._stop.wait(timeout=max(1, interval))


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).resolve().parent.parent / "web" / "templates"),
        static_folder=str(Path(__file__).resolve().parent.parent / "web" / "static"),
        static_url_path="/static",
    )

    runner = BotRunner()

    def _render_index():
        logs = list(AuditLog.select().order_by(AuditLog.timestamp.desc()).limit(80))
        log_lines = [f"{l.timestamp} [{l.action}] {l.details}" for l in logs]

        return render_template(
            "index.html",
            bot_running=runner.is_running,
            exchange_id=config_manager.get("exchange_id", "revolutx"),
            execution_mode=config_manager.get("execution_mode", "live"),
            symbol=config_manager.get("symbol", "BTC_USDC"),
            last_price=runner.engine.last_price,
            last_price_ts=runner.engine.last_price_ts,
            exposure=f"{get_total_exposure():.2f}",
            max_capital=f"{float(config_manager.get('max_capital', 100.0)):.2f}",
            bet_usd=config_manager.get("bet_usd", 20.0),
            trade_interval_seconds=config_manager.get("trade_interval_seconds", 60),
            revolutx_api_key=config_manager.get("revolutx_api_key", ""),
            revolutx_private_key_path=config_manager.get("revolutx_private_key_path", "private.pem"),
            logs=log_lines,
        )

    @app.get("/")
    def index():
        return _render_index()

    @app.post("/start")
    def start():
        runner.start()
        return redirect(url_for("index"))

    @app.post("/stop")
    def stop():
        runner.stop()
        return redirect(url_for("index"))

    @app.post("/trade-once")
    def trade_once():
        runner.trade_once()
        return redirect(url_for("index"))

    @app.post("/config")
    def update_config():
        for key in (
            "exchange_id",
            "execution_mode",
            "symbol",
            "bet_usd",
            "trade_interval_seconds",
            "max_capital",
            "revolutx_api_key",
            "revolutx_private_key_path",
        ):
            if key in request.form:
                val = request.form.get(key, "").strip()
                if key in ("bet_usd", "max_capital"):
                    try:
                        config_manager.set(key, float(val))
                    except Exception:
                        pass
                elif key in ("trade_interval_seconds",):
                    try:
                        config_manager.set(key, int(val))
                    except Exception:
                        pass
                else:
                    config_manager.set(key, val)

        runner.engine.initialize()
        AuditLog.create(action="CONFIG", details="Config updated via UI", capital_exposure=get_total_exposure())
        return redirect(url_for("index"))

    return app


def main():
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    app = create_app()
    # Local-only by default.
    app.run(host="127.0.0.1", port=8080, debug=False)


if __name__ == "__main__":
    main()

