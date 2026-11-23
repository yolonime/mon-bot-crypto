"""
Met à jour README.md et docs/status.json (bougies, indicateurs, prédictions, trades)
et pousse les données vers GitHub à chaque minute.
"""

from datetime import datetime, timezone
import json
import os
import subprocess
import pandas as pd
import config

START_MARKER = "<!-- DASHBOARD_START -->"
END_MARKER = "<!-- DASHBOARD_END -->"


def _load_recent_trades(limit: int = 20) -> list[dict]:
    if not os.path.exists(config.TRADES_CSV_PATH):
        return []
    df = pd.read_csv(config.TRADES_CSV_PATH)
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
    session_id: str,
    status: str,
    cash_eur: float,
    equity_eur: float,
    trades_session: int,
    prices: dict[str, float],
    positions: dict[str, dict],
    equity_curve: list[dict],
    market_analysis: dict[str, dict],
    blocker_reason: str = "",
) -> None:
    os.makedirs(os.path.dirname(config.STATUS_JSON_PATH), exist_ok=True)
    now_str = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S UTC")

    open_pos_list = []
    for sym, pos in positions.items():
        cur_px = float(prices.get(sym, pos["entry_price"]))
        unrealized = (cur_px - float(pos["entry_price"])) * float(pos["amount"])
        open_pos_list.append(
            {
                "symbol": sym,
                "entry_price": float(pos["entry_price"]),
                "current_price": cur_px,
                "stop_loss": float(pos["stop_loss"]),
                "take_profit": float(pos["take_profit"]),
                "unrealized_pnl_eur": round(unrealized, 4),
            }
        )

    payload = {
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
        "recent_trades": _load_recent_trades(20),
        "market_analysis": market_analysis,
        "blocker_reason": blocker_reason,
    }

    with open(config.STATUS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def push_live_update() -> None:
    if os.getenv("GITHUB_ACTIONS") != "true":
        return
    try:
        subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=False)
        subprocess.run(
            ["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"],
            check=False,
        )
        subprocess.run(
            ["git", "add", config.STATUS_JSON_PATH, config.TRADES_CSV_PATH, config.README_PATH],
            check=False,
        )
        diff = subprocess.run(["git", "diff", "--staged", "--quiet"], check=False)
        if diff.returncode != 0:
            subprocess.run(["git", "commit", "-m", "Live status update"], check=False)
            subprocess.run(["git", "push"], check=False)
    except Exception:
        pass


def build_dashboard_markdown() -> str:
    now_str = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

    if not os.path.exists(config.TRADES_CSV_PATH):
        return f"*Dernière mise à jour : {now_str} — Aucun historique disponible.*"

    df = pd.read_csv(config.TRADES_CSV_PATH)
    if df.empty:
        return f"*Dernière mise à jour : {now_str}*\n\nAucune transaction enregistrée pour le moment (le bot a surveillé le marché sans signal valide)."

    sells = df[df["side"] == "SELL"].copy()
    buys = df[df["side"] == "BUY"].copy()

    total_closed = len(sells)
    total_fees = float(df["fee_eur"].sum())
    total_slippage = float(df["slippage_eur"].sum())
    total_net_pnl = float(sells["net_pnl_eur"].sum()) if total_closed > 0 else 0.0

    wins = sells[sells["net_pnl_eur"] > 0]
    losses = sells[sells["net_pnl_eur"] < 0]
    win_rate = (len(wins) / total_closed * 100.0) if total_closed > 0 else 0.0
    best_trade = float(sells["net_pnl_eur"].max()) if total_closed > 0 else 0.0
    worst_trade = float(sells["net_pnl_eur"].min()) if total_closed > 0 else 0.0
    last_capital = float(df.iloc[-1]["capital_after_eur"])
    sessions_count = df["session_id"].nunique()

    lines = [
        f"*Dernière mise à jour : {now_str}*",
        "",
        "### Résumé global",
        "| Indicateur | Valeur |",
        "| :--- | :--- |",
        f"| **Sessions avec activité** | {sessions_count} |",
        f"| **Ordres exécutés** | {len(buys)} achats / {total_closed} ventes clôturées |",
        f"| **Taux de réussite (Win Rate)** | {win_rate:.1f} % ({len(wins)} gagnants / {len(losses)} perdants) |",
        f"| **PnL net cumulé (après frais)** | **{total_net_pnl:+.2f} €** |",
        f"| **Dernier capital enregistré** | {last_capital:.2f} € |",
        f"| **Frais + Slippage cumulés** | {total_fees + total_slippage:.2f} € ({total_fees:.2f} € frais + {total_slippage:.2f} € slippage) |",
        f"| **Meilleur / Pire trade** | {best_trade:+.2f} € / {worst_trade:+.2f} € |",
        "",
        "### Historique des 15 dernières opérations",
        "| Date (UTC) | Paire | Sens | Prix | Montant (€) | Frais (€) | PnL Net (€) | Motif |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    recent = df.tail(15).iloc[::-1]
    for _, row in recent.iterrows():
        ts = str(row["timestamp_utc"])[:16].replace("T", " ")
        side_label = "🟢 ACHAT" if row["side"] == "BUY" else "🔴 VENTE"
        pnl_val = float(row["net_pnl_eur"])
        pnl_str = f"**{pnl_val:+.2f} €**" if row["side"] == "SELL" else "-"
        lines.append(
            f"| {ts} | {row['symbol']} | {side_label} | {float(row['price']):.2f} | "
            f"{float(row['gross_value_eur']):.2f} € | {float(row['fee_eur']):.3f} € | {pnl_str} | `{row['reason']}` |"
        )

    return "\n".join(lines)


def update_readme() -> None:
    dashboard_md = build_dashboard_markdown()
    block = f"{START_MARKER}\n{dashboard_md}\n{END_MARKER}"

    if os.path.exists(config.README_PATH):
        with open(config.README_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = f"# Mon Bot Crypto (Paper Trading)\n\n## Dernier rapport de suivi\n{block}\n"

    if START_MARKER in content and END_MARKER in content:
        before = content.split(START_MARKER)[0]
        after = content.split(END_MARKER)[1]
        new_content = f"{before}{block}{after}"
    else:
        new_content = f"{content.rstrip()}\n\n## Dernier rapport de suivi\n{block}\n"

    with open(config.README_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)
