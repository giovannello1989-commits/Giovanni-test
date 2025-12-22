from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo


def _env(name: str, default: str | None = None) -> str | None:
    # Env vars are case-sensitive on Linux, but some UIs may create keys with
    # unexpected casing (e.g. Telegram_bot_token). Be forgiving: resolve keys
    # case-insensitively.
    val = os.getenv(name)
    if val is not None and val != "":
        return val

    target = name.lower()
    for k, v in os.environ.items():
        if k.lower() == target and v != "":
            return v

    return default


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _present_env_keys(prefix: str) -> list[str]:
    p = prefix.lower()
    keys = []
    for k in os.environ.keys():
        if k.lower().startswith(p):
            keys.append(k)
    return sorted(keys)


@dataclass(frozen=True)
class RiskProfile:
    name: str
    mom_1h_threshold: float
    mom_15m_threshold: float
    trailing_stop_pct: float


RISK_PROFILES: dict[str, RiskProfile] = {
    "aggressive": RiskProfile(
        name="aggressive",
        mom_1h_threshold=0.06,
        mom_15m_threshold=0.03,
        trailing_stop_pct=0.025,
    ),
    "normal": RiskProfile(
        name="normal",
        mom_1h_threshold=0.04,
        mom_15m_threshold=0.02,
        trailing_stop_pct=0.035,
    ),
    "conservative": RiskProfile(
        name="conservative",
        mom_1h_threshold=0.03,
        mom_15m_threshold=0.015,
        trailing_stop_pct=0.05,
    ),
}


@dataclass(frozen=True)
class AppConfig:
    telegram_bot_token: str
    telegram_allowed_chat_id: int | None

    tz_name: str
    tz: ZoneInfo

    # Operating window (Europe/Rome)
    window_start: time
    window_end: time
    hard_close_time: time
    recap_time: time

    scan_interval_seconds: int
    pairs_limit: int
    signal_cooldown_seconds: int

    # Revolut X API
    revolutx_base_url: str
    revolutx_base_path: str
    revolutx_api_key: str | None
    revolutx_timeout_seconds: int

    # Storage
    db_path: str


def load_config() -> AppConfig:
    token = _env("TELEGRAM_BOT_TOKEN")
    allowed_chat_id = _env("TELEGRAM_ALLOWED_CHAT_ID")
    if not token:
        keys = _present_env_keys("TELEGRAM_")
        raise RuntimeError(
            "Missing TELEGRAM_BOT_TOKEN env var. "
            f"Env keys seen with prefix TELEGRAM_: {keys}"
        )

    allowed_chat_id_int: int | None = None
    if allowed_chat_id:
        try:
            allowed_chat_id_int = int(str(allowed_chat_id).strip())
        except Exception:
            allowed_chat_id_int = None

    tz_name = _env("TZ", "Europe/Rome") or "Europe/Rome"
    tz = ZoneInfo(tz_name)

    # Window: 09:00–20:00, hard-close alert default 19:55, recap 20:00
    window_start = time(hour=9, minute=0, tzinfo=tz)
    window_end = time(hour=20, minute=0, tzinfo=tz)
    hard_close_time = time(
        hour=19,
        minute=_env_int("HARD_CLOSE_MINUTE", 55),
        tzinfo=tz,
    )
    recap_time = time(hour=20, minute=0, tzinfo=tz)

    # Revolut X REST API doc examples use https://revx.revolut.com
    revolutx_base_url = (_env("REVOLUTX_BASE_URL", "https://revx.revolut.com") or "").rstrip(
        "/"
    )
    # Paths in doc start with /api/..., so base path should usually be empty.
    revolutx_base_path = (_env("REVOLUTX_BASE_PATH", "") or "").rstrip("/")
    revolutx_api_key = _env("REVOLUTX_API_KEY")
    revolutx_timeout_seconds = _env_int("REVOLUTX_TIMEOUT_SECONDS", 10)

    scan_interval_seconds = _env_int("SCAN_INTERVAL_SECONDS", 60)
    pairs_limit = _env_int("PAIRS_LIMIT", 50)
    signal_cooldown_seconds = _env_int("SIGNAL_COOLDOWN_SECONDS", 1800)  # 30 min

    db_path = _env("DB_PATH", "bot.db") or "bot.db"

    return AppConfig(
        telegram_bot_token=token,
        telegram_allowed_chat_id=allowed_chat_id_int,
        tz_name=tz_name,
        tz=tz,
        window_start=window_start,
        window_end=window_end,
        hard_close_time=hard_close_time,
        recap_time=recap_time,
        scan_interval_seconds=scan_interval_seconds,
        pairs_limit=pairs_limit,
        signal_cooldown_seconds=signal_cooldown_seconds,
        revolutx_base_url=revolutx_base_url,
        revolutx_base_path=revolutx_base_path,
        revolutx_api_key=revolutx_api_key,
        revolutx_timeout_seconds=revolutx_timeout_seconds,
        db_path=db_path,
    )


def is_within_operating_window(now_local, window_start: time, window_end: time) -> bool:
    # Expect `now_local` to be timezone-aware.
    t = now_local.timetz()
    return window_start <= t < window_end

