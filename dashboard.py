"""
Génère automatiquement un tableau de bord de suivi dans README.md à partir de trades_history.csv.
Visible directement sur la page d'accueil du dépôt GitHub (y compris sur téléphone).
"""

from datetime import datetime, timezone
import os
import pandas as pd
import config

START_MARKER = "<!-- DASHBOARD_START -->"
END_MARKER = "<!-- DASHBOARD_END -->"


def build_dashboard_markdown() -> str:
    now_str = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

    if not os.path.exists(config.TRADES_CSV_PATH):
        return f"*Dernière mise à jour : {now_str} — Aucun historique disponible.*"

    df = pd.read_csv(config.TRADES_CSV_PATH)
    if df.empty:
        return (
            f"*Dernière mise à jour : {now_str}*\n\n"
            "Aucune transaction enregistrée pour le moment (le bot a surveillé le marché sans signal valide)."
        )

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
