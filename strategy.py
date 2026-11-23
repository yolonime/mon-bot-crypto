"""
Calcul des indicateurs techniques, détection des signaux et diagnostic en direct pour le site web.
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


def build_symbol_snapshot(df: pd.DataFrame) -> dict:
    """
    Extrait les 60 dernières bougies + EMA et l'état détaillé des 4 filtres
    pour afficher ce que regarde le bot et ses scénarios potentiels sur le site web.
    """
    if len(df) < 5:
        return {}

    prev = df.iloc[-3]
    curr = df.iloc[-2]
    live = df.iloc[-1]

    close_val = float(curr["close"])
    live_price = float(live["close"])
    ema_fast = float(curr["ema_fast"])
    ema_slow = float(curr["ema_slow"])
    ema_trend = float(curr["ema_trend"]) if not pd.isna(curr["ema_trend"]) else close_val
    rsi_val = float(curr["rsi"]) if not pd.isna(curr["rsi"]) else 50.0
    vol_val = float(curr["volume"])
    vol_sma = float(curr["vol_sma"]) if not pd.isna(curr["vol_sma"]) else 0.0
    atr_val = float(curr["atr"]) if not pd.isna(curr["atr"]) else 0.0

    trend_ok = close_val > ema_trend
    crossover_ok = (float(prev["ema_fast"]) <= float(prev["ema_slow"])) and (ema_fast > ema_slow)
    rsi_ok = config.RSI_MIN <= rsi_val <= config.RSI_MAX
    volume_ok = (vol_sma > 0) and (vol_val > vol_sma)

    score = sum([trend_ok, crossover_ok, rsi_ok, volume_ok])

    projected_sl = round(live_price - config.ATR_SL_MULTIPLIER * atr_val, 4) if atr_val > 0 else None
    projected_tp = (
        round(live_price + (config.ATR_SL_MULTIPLIER * atr_val * config.RISK_REWARD_RATIO), 4)
        if atr_val > 0
        else None
    )

    # Scénario / prédiction pédagogique
    if score == 4:
        prediction = (
            f"Signal d'achat complet détecté ! Entrée estimée autour de {live_price:.2f} € "
            f"avec Stop-Loss à {projected_sl:.2f} € et objectif Take-Profit à {projected_tp:.2f} €."
        )
    elif not trend_ok:
        diff_pct = ((ema_trend - close_val) / close_val) * 100.0
        prediction = (
            f"Tendance de fond baissière ou neutre (prix {diff_pct:.2f} % sous l'EMA 50 à {ema_trend:.2f} €). "
            "Le bot reste à l'écart tant que le cours ne repasse pas au-dessus de l'EMA 50."
        )
    elif ema_fast <= ema_slow:
        gap = ema_slow - ema_fast
        prediction = (
            f"Tendance de fond haussière (au-dessus d'EMA 50), mais EMA 9 ({ema_fast:.2f} €) est encore "
            f"{gap:.2f} € sous EMA 21 ({ema_slow:.2f} €). Le bot guette un croisement haussier."
        )
    else:
        missing = []
        if not crossover_ok:
            missing.append("croisement récent EMA 9/21 déjà passé (le bot attend une nouvelle impulsion)")
        if not rsi_ok:
            missing.append(f"RSI à {rsi_val:.1f} hors zone cible [{config.RSI_MIN:.0f}-{config.RSI_MAX:.0f}]")
        if not volume_ok:
            missing.append("volume inférieur à la moyenne des 20 bougies")
        prediction = (
            f"Configuration haussière en cours, en attente de : {', '.join(missing)}. "
            f"Si déclenchement maintenant : SL potentiel à {projected_sl:.2f} € / TP à {projected_tp:.2f} €."
        )

    candles = []
    for _, row in df.tail(60).iterrows():
        ts_unix = int(pd.Timestamp(row["timestamp"]).timestamp())
        candles.append(
            {
                "time": ts_unix,
                "open": round(float(row["open"]), 4),
                "high": round(float(row["high"]), 4),
                "low": round(float(row["low"]), 4),
                "close": round(float(row["close"]), 4),
                "ema9": round(float(row["ema_fast"]), 4) if not pd.isna(row["ema_fast"]) else None,
                "ema21": round(float(row["ema_slow"]), 4) if not pd.isna(row["ema_slow"]) else None,
                "ema50": round(float(row["ema_trend"]), 4) if not pd.isna(row["ema_trend"]) else None,
            }
        )

    return {
        "current_price": round(live_price, 4),
        "rsi": round(rsi_val, 2),
        "atr": round(atr_val, 4),
        "projected_sl": projected_sl,
        "projected_tp": projected_tp,
        "score": score,
        "checks": [
            {
                "label": "1. Tendance (Prix > EMA 50)",
                "detail": f"Clôture {close_val:.2f} € vs EMA50 {ema_trend:.2f} €",
                "ok": bool(trend_ok),
            },
            {
                "label": "2. Impulsion (Croisement EMA 9 > EMA 21)",
                "detail": f"EMA9 {ema_fast:.2f} € vs EMA21 {ema_slow:.2f} €",
                "ok": bool(crossover_ok),
            },
            {
                "label": f"3. Momentum (RSI entre {config.RSI_MIN:.0f} et {config.RSI_MAX:.0f})",
                "detail": f"RSI(14) actuel = {rsi_val:.1f}",
                "ok": bool(rsi_ok),
            },
            {
                "label": "4. Volume (> Moyenne 20 bougies)",
                "detail": f"Vol {vol_val:.4f} vs Moy {vol_sma:.4f}",
                "ok": bool(volume_ok),
            },
        ],
        "prediction_text": prediction,
        "candles": candles,
    }
