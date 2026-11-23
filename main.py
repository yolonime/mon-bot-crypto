"""
Point d'entrée principal de la session de trading simulé (durée configurable, ex: 120 minutes).
Conçu pour tourner proprement sur GitHub Actions sans laisser de position ouverte en fin de session.
"""

from datetime import datetime, timedelta, timezone
import logging
import sys
import time
import ccxt
import pandas as pd

import config
from paper_broker import PaperBroker
from risk_manager import RiskManager
from strategy import check_buy_signal, check_exit_condition, compute_indicators

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("CryptoPaperBot")


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
    broker: PaperBroker,
    risk_manager: RiskManager,
    current_prices: dict[str, float],
    reason: str,
) -> None:
    for symbol in list(broker.positions.keys()):
        px = current_prices.get(symbol, broker.positions[symbol]["entry_price"])
        pnl = broker.close_long(symbol, px, reason=reason)
        if pnl is not None:
            risk_manager.record_trade_closed(pnl)
            logger.info("Position fermée [%s] (%s) | PnL net : %+.4f €", symbol, reason, pnl)


def run_session() -> None:
    start_time = datetime.now(timezone.utc)
    end_time = start_time + timedelta(minutes=config.SESSION_DURATION_MINUTES)
    close_window_start = end_time - timedelta(minutes=config.CLOSE_BEFORE_END_MINUTES)
    session_id = start_time.strftime("%Y%m%d_%H%M%S")

    logger.info("=== Démarrage session %s (MODE=%s, Capital=%.2f €) ===", session_id, config.MODE, config.INITIAL_CAPITAL_EUR)
    logger.info("Durée : %d min | Clôture auto à partir de : %s UTC", config.SESSION_DURATION_MINUTES, close_window_start.strftime("%H:%M:%S"))

    exchange = create_exchange()
    broker = PaperBroker(session_id=session_id, initial_capital=config.INITIAL_CAPITAL_EUR)
    risk_manager = RiskManager(initial_session_capital=config.INITIAL_CAPITAL_EUR)

    last_prices: dict[str, float] = {}

    try:
        while True:
            now = datetime.now(timezone.utc)
            if now >= end_time:
                logger.info("Temps de session écoulé (%d min). Arrêt propre.", config.SESSION_DURATION_MINUTES)
                break

            closing_soon = now >= close_window_start
            current_prices: dict[str, float] = {}
            indicators_by_symbol: dict[str, pd.DataFrame] = {}

            # 1. Récupération des données et calcul des indicateurs
            for symbol in config.SYMBOLS:
                try:
                    df = fetch_ohlcv_df(exchange, symbol)
                    df_ind = compute_indicators(df)
                    indicators_by_symbol[symbol] = df_ind
                    latest_price = float(df_ind.iloc[-1]["close"])
                    current_prices[symbol] = latest_price
                    last_prices[symbol] = latest_price
                except (ccxt.NetworkError, ccxt.ExchangeError) as exc:
                    logger.warning("Erreur réseau/exchange sur %s : %s", symbol, exc)
                except Exception as exc:
                    logger.exception("Erreur inattendue sur %s : %s", symbol, exc)

            if not current_prices:
                time.sleep(config.LOOP_SLEEP_SECONDS)
                continue

            # 2. Vérification du Kill Switch
            equity = broker.total_equity(current_prices)
            killed, kill_reason = risk_manager.check_kill_switch(equity)
            if killed:
                logger.warning("KILL SWITCH DÉCLENCHÉ : %s", kill_reason)
                close_all_positions(broker, risk_manager, current_prices, reason="KILL_SWITCH")
                break

            # 3. Gestion des positions ouvertes (SL / TP / Clôture fin de session)
            for symbol in list(broker.positions.keys()):
                px = current_prices.get(symbol)
                if px is None:
                    continue

                if closing_soon:
                    pnl = broker.close_long(symbol, px, reason="SESSION_END_CLOSE")
                    if pnl is not None:
                        risk_manager.record_trade_closed(pnl)
                        logger.info("Clôture fin de session [%s] à %.4f € | PnL net : %+.4f €", symbol, px, pnl)
                    continue

                pos = broker.positions[symbol]
                exit_reason = check_exit_condition(pos, px)
                if exit_reason:
                    pnl = broker.close_long(symbol, px, reason=exit_reason)
                    if pnl is not None:
                        risk_manager.record_trade_closed(pnl)
                        logger.info("Sortie [%s] (%s) à %.4f € | PnL net : %+.4f €", symbol, exit_reason, px, pnl)

            # 4. Recherche de nouveaux signaux d'achat
            for symbol, df_ind in indicators_by_symbol.items():
                can_open, reason_msg = risk_manager.can_open_trade(
                    current_capital=broker.cash_eur,
                    open_positions_count=len(broker.positions),
                    closing_soon=closing_soon,
                    now=now,
                )
                if not can_open:
                    continue

                signal = check_buy_signal(df_ind)
                if signal:
                    amount, notional_eur, size_msg = risk_manager.calculate_position_size(
                        current_capital=broker.cash_eur,
                        entry_price=signal["entry_price"],
                        stop_loss=signal["stop_loss"],
                    )
                    if amount <= 0:
                        logger.info("Signal ignoré sur %s : %s", symbol, size_msg)
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
                        risk_manager.record_trade_opened(now=now)
                        logger.info(
                            "ACHAT [%s] | %s | SL=%.4f | TP=%.4f",
                            symbol,
                            size_msg,
                            signal["stop_loss"],
                            signal["take_profit"],
                        )

            equity_after = broker.total_equity(current_prices)
            logger.info(
                "État | Cash=%.2f € | Equity=%.2f € | Positions=%d | Trades session=%d/%d",
                broker.cash_eur,
                equity_after,
                len(broker.positions),
                risk_manager.trades_this_session,
                config.MAX_TRADES_PER_SESSION,
            )

            # Attendre jusqu'à la prochaine boucle sans dépasser end_time
            remaining_seconds = (end_time - datetime.now(timezone.utc)).total_seconds()
            if remaining_seconds <= 0:
                break
            time.sleep(min(config.LOOP_SLEEP_SECONDS, remaining_seconds))

    finally:
        # Sécurité ultime : jamais laisser de position ouverte à la sortie du script
        if broker.positions:
            logger.info("Sécurité finale : fermeture des positions restantes avant arrêt.")
            close_all_positions(broker, risk_manager, last_prices, reason="FINAL_SHUTDOWN")

        final_equity = broker.total_equity(last_prices)
        net_session_pnl = final_equity - config.INITIAL_CAPITAL_EUR
        logger.info(
            "=== Fin session %s | Equity finale : %.2f € | PnL net : %+.2f € ===",
            session_id,
            final_equity,
            net_session_pnl,
        )


if __name__ == "__main__":
    run_session()
