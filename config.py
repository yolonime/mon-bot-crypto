"""
Configuration centrale multi-bots (4 profils comparatifs en mode PAPER).
"""

import os

MODE = "PAPER"
EXCHANGE_ID = "kraken"
SYMBOLS = ["BTC/EUR", "ETH/EUR"]

TIMEFRAME = "5m"
OHLCV_LIMIT = 120

SESSION_DURATION_MINUTES = 120
CLOSE_BEFORE_END_MINUTES = 15
LOOP_SLEEP_SECONDS = 60

INITIAL_CAPITAL_EUR = 100.0
FEE_RATE = 0.0010
SLIPPAGE_RATE = 0.0005

BOT_PROFILES = {
    "bot1": {
        "name": "Bot 1 — Strict (RSI 45-65)",
        "description": "Base équilibrée : EMA 9/21 > EMA 50, RSI 45–65, Volume > SMA 20, SL 1.5x ATR / TP 3.0x ATR.",
        "ema_fast": 9,
        "ema_slow": 21,
        "ema_trend": 50,
        "rsi_min": 45.0,
        "rsi_max": 65.0,
        "atr_sl_mult": 1.5,
        "rr_ratio": 2.0,
    },
    "bot2": {
        "name": "Bot 2 — Momentum (RSI 45-75)",
        "description": "Chasseur de pics : autorise le RSI jusqu'à 75 pour capter les fortes accélérations.",
        "ema_fast": 9,
        "ema_slow": 21,
        "ema_trend": 50,
        "rsi_min": 45.0,
        "rsi_max": 75.0,
        "atr_sl_mult": 1.5,
        "rr_ratio": 2.0,
    },
    "bot3": {
        "name": "Bot 3 — Réactif (EMA 5/13)",
        "description": "Moyennes courtes EMA 5/13 au-dessus d'EMA 50 avec RSI 45–70 pour entrer plus tôt.",
        "ema_fast": 5,
        "ema_slow": 13,
        "ema_trend": 50,
        "rsi_min": 45.0,
        "rsi_max": 70.0,
        "atr_sl_mult": 1.5,
        "rr_ratio": 2.0,
    },
    "bot4": {
        "name": "Bot 4 — TP Serré (R/R 1.5)",
        "description": "Prend ses profits plus vite (TP = 1.5x le risque) sur la base EMA 9/21 & RSI 45–65.",
        "ema_fast": 9,
        "ema_slow": 21,
        "ema_trend": 50,
        "rsi_min": 45.0,
        "rsi_max": 65.0,
        "atr_sl_mult": 1.5,
        "rr_ratio": 1.5,
    },
}

DEFAULT_BOT_ID = os.getenv("BOT_ID", "bot1").strip().lower()
if DEFAULT_BOT_ID not in BOT_PROFILES:
    DEFAULT_BOT_ID = "bot1"

VOLUME_SMA_PERIOD = 20
RSI_PERIOD = 14
ATR_PERIOD = 14

MAX_RISK_PER_TRADE_PCT = 0.01
MIN_ORDER_VALUE_EUR = 10.0
MAX_OPEN_POSITIONS = 1
MAX_TRADES_PER_SESSION = 3
COOLDOWN_MINUTES = 15
MAX_SESSION_LOSS_PCT = 0.03
MAX_CONSECUTIVE_LOSSES = 2

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
README_PATH = "README.md"


def get_bot_settings(bot_id: str) -> dict:
    bid = bot_id.strip().lower()
    if bid not in BOT_PROFILES:
        raise ValueError(f"BOT_ID inconnu : {bot_id}")
    cfg = dict(BOT_PROFILES[bid])
    cfg["bot_id"] = bid
    cfg["csv_path"] = f"data/trades_{bid}.csv"
    cfg["status_json_path"] = f"docs/status_{bid}.json"
    return cfg
