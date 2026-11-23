"""
Calcul des indicateurs techniques et détection des signaux d'achat / sortie.
"""

import numpy as np
import pandas as pd
import config


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()

    data["ema_fast"] = data["close"].ewm(span=config.EMA_FAST, adjust=False).mean()
    data["ema_slow"] = data["close"].ewm(span=config.EMA_SLOW, adjust=False).mean()
    data["ema_trend"] = data["close"].ewm(span=config.EMA_TREND, adjust=False).mean()

    delta = data["close"].diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / config.RSI_PERIOD, min_periods=config.RSI_PERIOD, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / config.RSI_PERIOD, min_periods=config.RSI_PERIOD, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    data["rsi"] = 100.0 - (100.0 / (1.0 + rs))
    data["rsi"] = data["rsi"].fillna(50.0)

    data["vol_sma"] = data["volume"].rolling(window=config.VOLUME_SMA_PERIOD).mean()

    prev_close = data["close"].shift(1)
    tr = pd.concat(
        [
            data["high"] - data["low"],
            (data["high"] - prev_close).abs(),
            (data["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    data["atr"] = tr.rolling(window=config.ATR_PERIOD).mean()

    return data


def check_buy_signal(df: pd.DataFrame) -> dict | None:
    if len(df) < max(config.EMA_TREND, config.ATR_PERIOD, config.VOLUME_SMA_PERIOD) + 3:
        return None

    prev = df.iloc[-3]
    curr = df.iloc[-2]

    if pd.isna(curr["ema_trend"]) or pd.isna(curr["atr"]) or pd.isna(curr["vol_sma"]) or curr["atr"] <= 0:
        return None

    trend_ok = curr["close"] > curr["ema_trend"]
    crossover_ok = (prev["ema_fast"] <= prev["ema_slow"]) and (curr["ema_fast"] > curr["ema_slow"])
    rsi_ok = config.RSI_MIN <= curr["rsi"] <= config.RSI_MAX
    volume_ok = curr["volume"] > curr["vol_sma"]

    if trend_ok and crossover_ok and rsi_ok and volume_ok:
        entry_price = float(curr["close"])
        atr_val = float(curr["atr"])
        stop_loss = entry_price - (config.ATR_SL_MULTIPLIER * atr_val)
        risk_per_unit = entry_price - stop_loss

        if risk_per_unit <= 0:
            return None

        take_profit = entry_price + (risk_per_unit * config.RISK_REWARD_RATIO)

        return {
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "atr": atr_val,
            "rsi": float(curr["rsi"]),
        }

    return None


def check_exit_condition(position: dict, current_price: float) -> str | None:
    if current_price <= position["stop_loss"]:
        return "STOP_LOSS"
    if current_price >= position["take_profit"]:
        return "TAKE_PROFIT"
    return None
