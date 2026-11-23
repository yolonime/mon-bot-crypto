"""
Point d'entrée d'un bot comparatif (ex: BOT_ID=bot1, bot2, bot3 ou bot4).
Pousse vers GitHub uniquement lors d'un trade et à la fin de la session.
"""

import argparse
from datetime import datetime, timedelta, timezone
import logging
import sys
import time
import ccxt
import pandas as pd

import config
from dashboard import push_bot_update, update_web_status
from notifier import send_telegram
from paper_broker import PaperBroker
from risk_manager import RiskManager
from strategy import check_buy_signal, check_exit_condition, compute_indicators

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("CryptoPaperBot")


def parse_bot_id() -> str:
    parser = argparse.ArgumentParser(description="Bot Crypto Paper Trading")
    parser.add_argument("--bot-id", default=config.DEFAULT_BOT_ID, help="Identifiant du bot (bot1..bot4)")
    args, _ = parser.parse_known_args()
    return args.bot_id.strip().lower()


def create_exchange() -> ccxt.Exchange:
    exchange_cls = getattr(ccxt, config.EXCHANGE_ID)
    exchange = exchange_cls({"enableRateLimit": True})
    exchange.load_markets()
    return exchange


def fetch_ohlcv_df(exchange: ccxt.Exchange, symbol: str) -> pd.DataFrame:
    raw = exchange.fetch_ohlcv(symbol, timeframe=config.TIMEFRAME, limit=config.OHLCV_LIMIT)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df


def close_all_positions(
    bot_cfg: dict,
    broker: PaperBroker,
    risk_manager: RiskManager,
    current_prices: dict[str, float],
    reason: str,
) -> bool:
    closed_any = False
    for symbol in list(broker.positions.keys()):
        px = current_prices.get(symbol, broker.positions[symbol]["entry_price"])
        pnl = broker.close_long(symbol, px, reason=reason)
        if pnl is not None:
            closed_any = True
            risk_manager.record_trade_closed(pnl)
            logger.info("[%s] Position fermée [%s] (%s) | PnL net : %+.4f €", bot_cfg["bot_id"], symbol, reason, pnl)
            send_telegram(
                f"🔴 <b>[{bot_cfg['name']}] VENTE ({reason})</b>\nPaire : <b>{symbol}</b>\nPrix : {px:.2f} €\nPnL net : <b>{pnl:+.2f} €</b>\nCapital : {broker.cash_eur:.2f} €"
            )
    return closed_any


def run_session(bot_id: str) -> None:
    bot_cfg = config.get_bot_settings(bot_id)
    start_time = datetime.now(timezone.utc)
    end_time = start_time + timedelta(minutes=config.SESSION_DURATION_MINUTES)
    close_window_start = end_time - timedelta(minutes=config.CLOSE_BEFORE_END_MINUTES)
    session_id = start_time.strftime("%Y%m%d_%H%M%S")

    logger.info("=== Démarrage %s (%s) | Capital=%.2f € ===", bot_cfg["name"], session_id, config.INITIAL_CAPITAL_EUR)
    send_telegram(
        f"🚀 <b>{bot_cfg['name']} démarré</b>\nSession : <code>{session_id}</code>\nCapital : {config.INITIAL_CAPITAL_EUR:.2f} € | Durée : {config.SESSION_DURATION_MINUTES} min"
    )

    exchange = create_exchange()
    broker = PaperBroker(session_id=session_id, csv_path=bot_cfg["csv_path"], initial_capital=config.INITIAL_CAPITAL_EUR)
    risk_manager = RiskManager(initial_session_capital=config.INITIAL_CAPITAL_EUR)

    last_prices: dict[str, float] = {}
    equity_curve: list[dict] = []

    try:
        while True:
            now = datetime.now(timezone.utc)
            if now >= end_time:
                logger.info("[%s] Temps de session écoulé. Arrêt propre.", bot_id)
                break

            trade_occurred = False
            closing_soon = now >= close_window_start
            current_prices: dict[str, float] = {}
            indicators_by_symbol: dict[str, pd.DataFrame] = {}

            for symbol in config.SYMBOLS:
                try:
                    df = fetch_ohlcv_df(exchange, symbol)
                    df_ind = compute_indicators(df, bot_cfg)
                    indicators_by_symbol[symbol] = df_ind
                    latest_price = float(df_ind.iloc[-1]["close"])
                    current_prices[symbol] = latest_price
                    last_prices[symbol] = latest_price
                except (ccxt.NetworkError, ccxt.ExchangeError) as exc:
                    logger.warning("[%s] Erreur réseau sur %s : %s", bot_id, symbol, exc)
                except Exception as exc:
                    logger.exception("[%s] Erreur inattendue sur %s : %s", bot_id, symbol, exc)

            if not current_prices:
                time.sleep(config.LOOP_SLEEP_SECONDS)
                continue

            equity = broker.total_equity(current_prices)
            killed, kill_reason = risk_manager.check_kill_switch(equity)
            if killed:
                logger.warning("[%s] KILL SWITCH : %s", bot_id, kill_reason)
                send_telegram(f"🛑 <b>[{bot_cfg['name']}] KILL SWITCH</b>\n{kill_reason}")
                if close_all_positions(bot_cfg, broker, risk_manager, current_prices, reason="KILL_SWITCH"):
                    trade_occurred = True
                equity_after = broker.total_equity(current_prices)
                equity_curve.append({"time": now.strftime("%H:%M"), "equity": round(equity_after, 4)})
                update_web_status(
                    bot_cfg=bot_cfg,
                    session_id=session_id,
                    status="RUNNING",
                    cash_eur=broker.cash_eur,
                    equity_eur=equity_after,
                    trades_session=risk_manager.trades_this_session,
                    prices=current_prices,
                    positions=broker.positions,
                    equity_curve=equity_curve,
                )
                if trade_occurred:
                    push_bot_update(bot_cfg, f"[{bot_id}] Kill switch exit")
                break

            for symbol in list(broker.positions.keys()):
                px = current_prices.get(symbol)
                if px is None:
                    continue

                if closing_soon:
                    pnl = broker.close_long(symbol, px, reason="SESSION_END_CLOSE")
                    if pnl is not None:
                        trade_occurred = True
                        risk_manager.record_trade_closed(pnl)
                        logger.info("[%s] Clôture fin session [%s] | PnL : %+.4f €", bot_id, symbol, pnl)
                    continue

                pos = broker.positions[symbol]
                exit_reason = check_exit_condition(pos, px)
                if exit_reason:
                    pnl = broker.close_long(symbol, px, reason=exit_reason)
                    if pnl is not None:
                        trade_occurred = True
                        risk_manager.record_trade_closed(pnl)
                        logger.info("[%s] Sortie [%s] (%s) | PnL : %+.4f €", bot_id, symbol, exit_reason, pnl)
                        icon = "✅" if pnl >= 0 else "❌"
                        send_telegram(
                            f"{icon} <b>[{bot_cfg['name']}] VENTE ({exit_reason})</b>\nPaire : <b>{symbol}</b> à {px:.2f} €\nPnL net : <b>{pnl:+.2f} €</b>\nCapital : {broker.cash_eur:.2f} €"
                        )

            for symbol, df_ind in indicators_by_symbol.items():
                can_open, _ = risk_manager.can_open_trade(
                    current_capital=broker.cash_eur,
                    open_positions_count=len(broker.positions),
                    closing_soon=closing_soon,
                    now=now,
                )
                if not can_open:
                    continue

                signal = check_buy_signal(df_ind, bot_cfg)
                if signal:
                    amount, notional_eur, size_msg = risk_manager.calculate_position_size(
                        current_capital=broker.cash_eur,
                        entry_price=signal["entry_price"],
                        stop_loss=signal["stop_loss"],
                    )
                    if amount <= 0:
                        continue

                    opened = broker.open_long(
                        symbol=symbol,
                        market_price=signal["entry_price"],
                        amount=amount,
                        stop_loss=signal["stop_loss"],
                        take_profit=signal["take_profit"],
                        reason="EMA_RSI_VOL_BUY",
                    )
                    if opened:
                        trade_occurred = True
                        risk_manager.record_trade_opened(now=now)
                        logger.info("[%s] ACHAT [%s] | %s", bot_id, symbol, size_msg)
                        send_telegram(
                            f"🟢 <b>[{bot_cfg['name']}] ACHAT ({symbol})</b>\nPrix : {opened['entry_price']:.2f} € | Montant : {notional_eur:.2f} €\nSL : {signal['stop_loss']:.2f} € | TP : {signal['take_profit']:.2f} €"
                        )

            equity_after = broker.total_equity(current_prices)
            equity_curve.append({"time": now.strftime("%H:%M"), "equity": round(equity_after, 4)})
            update_web_status(
                bot_cfg=bot_cfg,
                session_id=session_id,
                status="RUNNING",
                cash_eur=broker.cash_eur,
                equity_eur=equity_after,
                trades_session=risk_manager.trades_this_session,
                prices=current_prices,
                positions=broker.positions,
                equity_curve=equity_curve,
            )
            if trade_occurred:
                push_bot_update(bot_cfg, f"[{bot_id}] Trade executed")

            logger.info(
                "[%s] Cash=%.2f € | Equity=%.2f € | Pos=%d | Trades=%d/%d",
                bot_id,
                broker.cash_eur,
                equity_after,
                len(broker.positions),
                risk_manager.trades_this_session,
                config.MAX_TRADES_PER_SESSION,
            )

            remaining_seconds = (end_time - datetime.now(timezone.utc)).total_seconds()
            if remaining_seconds <= 0:
                break
            time.sleep(min(config.LOOP_SLEEP_SECONDS, remaining_seconds))

    finally:
        if broker.positions:
            close_all_positions(bot_cfg, broker, risk_manager, last_prices, reason="FINAL_SHUTDOWN")

        final_equity = broker.total_equity(last_prices)
        equity_curve.append({"time": datetime.now(timezone.utc).strftime("%H:%M"), "equity": round(final_equity, 4)})
        update_web_status(
            bot_cfg=bot_cfg,
            session_id=session_id,
            status="IDLE",
            cash_eur=broker.cash_eur,
            equity_eur=final_equity,
            trades_session=risk_manager.trades_this_session,
            prices=last_prices,
            positions=broker.positions,
            equity_curve=equity_curve,
        )
        push_bot_update(bot_cfg, f"[{bot_id}] Final session update")

        net_session_pnl = final_equity - config.INITIAL_CAPITAL_EUR
        logger.info("=== Fin %s | Equity : %.2f € | PnL : %+.2f € ===", bot_cfg["name"], final_equity, net_session_pnl)
        send_telegram(
            f"🏁 <b>Fin {bot_cfg['name']}</b>\nTrades : {risk_manager.trades_this_session}\nEquity finale : <b>{final_equity:.2f} €</b> ({net_session_pnl:+.2f} €)"
        )


if __name__ == "__main__":
    run_session(parse_bot_id())
