"""
Met à jour docs/status_<bot_id>.json et pousse uniquement les fichiers propres au bot
lors d'un trade ou en fin de session (avec boucle anti-conflit Git).
"""

from datetime import datetime, timezone
import json
import logging
import os
import subprocess
import time
import pandas as pd
import config

logger = logging.getLogger("CryptoPaperBot")


def _load_recent_trades(csv_path: str, limit: int = 20) -> list[dict]:
    if not os.path.exists(csv_path):
        return []
    df = pd.read_csv(csv_path)
    if df.empty:
        return []
    recent = df.tail(limit).iloc[::-1]
    rows = []
    for _, r in recent.iterrows():
        rows.append(
            {
                "timestamp_utc": str(r["timestamp_utc"])[:19].replace("T", " "),
                "symbol": str(r["symbol"]),
                "side": str(r["side"]),
                "price": float(r["price"]),
                "gross_value_eur": float(r["gross_value_eur"]),
                "fee_eur": float(r["fee_eur"]),
                "net_pnl_eur": float(r["net_pnl_eur"]),
                "reason": str(r["reason"]),
            }
        )
    return rows


def update_web_status(
    bot_cfg: dict,
    session_id: str,
    status: str,
    cash_eur: float,
    equity_eur: float,
    trades_session: int,
    prices: dict[str, float],
    positions: dict[str, dict],
    equity_curve: list[dict],
) -> None:
    status_path = bot_cfg["status_json_path"]
    os.makedirs(os.path.dirname(status_path), exist_ok=True)
    now_str = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S UTC")

    open_pos_list = []
    for sym, pos in positions.items():
        cur_px = float(prices.get(sym, pos["entry_price"]))
        unrealized = (cur_px - float(pos["entry_price"])) * float(pos["amount"])
        open_pos_list.append(
            {
                "symbol": sym,
                "amount": float(pos["amount"]),
                "entry_price": float(pos["entry_price"]),
                "current_price": cur_px,
                "stop_loss": float(pos["stop_loss"]),
                "take_profit": float(pos["take_profit"]),
                "unrealized_pnl_eur": round(unrealized, 4),
            }
        )

    payload = {
        "bot_id": bot_cfg["bot_id"],
        "bot_name": bot_cfg["name"],
        "bot_description": bot_cfg["description"],
        "params": {
            "ema_fast": bot_cfg["ema_fast"],
            "ema_slow": bot_cfg["ema_slow"],
            "ema_trend": bot_cfg["ema_trend"],
            "rsi_min": bot_cfg["rsi_min"],
            "rsi_max": bot_cfg["rsi_max"],
            "atr_sl_mult": bot_cfg["atr_sl_mult"],
            "rr_ratio": bot_cfg["rr_ratio"],
        },
        "updated_at_utc": now_str,
        "session_id": session_id,
        "status": status,
        "cash_eur": round(float(cash_eur), 4),
        "equity_eur": round(float(equity_eur), 4),
        "session_pnl_eur": round(float(equity_eur) - config.INITIAL_CAPITAL_EUR, 4),
        "trades_session": int(trades_session),
        "max_trades_session": int(config.MAX_TRADES_PER_SESSION),
        "prices": {k: round(float(v), 4) for k, v in prices.items()},
        "open_positions": open_pos_list,
        "equity_curve": equity_curve[-150:],
        "recent_trades": _load_recent_trades(bot_cfg["csv_path"], 20),
    }

    with open(status_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def push_bot_update(bot_cfg: dict, commit_message: str) -> None:
    """
    Pousse uniquement les 2 fichiers propres au bot (docs/status_<id>.json et data/trades_<id>.csv)
    avec retry + git pull --rebase pour éviter tout conflit entre les 4 bots parallèles.
    """
    if os.getenv("GITHUB_ACTIONS") != "true":
        return

    status_path = bot_cfg["status_json_path"]
    csv_path = bot_cfg["csv_path"]

    try:
        subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=False)
        subprocess.run(
            ["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"],
            check=False,
        )
        subprocess.run(["git", "add", status_path, csv_path], check=False)
        diff = subprocess.run(["git", "diff", "--staged", "--quiet"], check=False)
        if diff.returncode == 0:
            return

        subprocess.run(["git", "commit", "-m", commit_message], check=False)

        for attempt in range(1, 5):
            subprocess.run(["git", "pull", "--rebase", "--autostash"], check=False)
            res = subprocess.run(["git", "push"], capture_output=True, text=True, check=False)
            if res.returncode == 0:
                logger.info("[%s] Sync GitHub OK (%s).", bot_cfg["bot_id"], commit_message)
                return
            logger.warning("[%s] Tentative push %d/4 rejetée, nouvelle tentative...", bot_cfg["bot_id"], attempt)
            time.sleep(2 * attempt)
    except Exception as exc:
        logger.warning("[%s] Erreur synchronisation GitHub : %s", bot_cfg["bot_id"], exc)
