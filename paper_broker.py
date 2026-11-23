"""
Simulateur d'exécution (Paper Broker) par bot avec CSV dédié.
"""

import csv
from datetime import datetime, timezone
import os
import config


class PaperBroker:
    def __init__(self, session_id: str, csv_path: str, initial_capital: float = config.INITIAL_CAPITAL_EUR):
        if config.MODE != "PAPER":
            raise ValueError("Sécurité : ce broker n'accepte que MODE = 'PAPER'.")

        self.session_id = session_id
        self.csv_path = csv_path
        self.cash_eur = float(initial_capital)
        self.positions: dict[str, dict] = {}
        self._ensure_csv_header()

    def _ensure_csv_header(self) -> None:
        os.makedirs(os.path.dirname(self.csv_path), exist_ok=True)
        headers = [
            "timestamp_utc",
            "session_id",
            "symbol",
            "side",
            "price",
            "amount",
            "gross_value_eur",
            "fee_eur",
            "slippage_eur",
            "net_pnl_eur",
            "capital_after_eur",
            "reason",
        ]
        if not os.path.exists(self.csv_path) or os.path.getsize(self.csv_path) == 0:
            with open(self.csv_path, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(headers)

    def _append_csv(self, row: list) -> None:
        with open(self.csv_path, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(row)

    def total_equity(self, current_prices: dict[str, float]) -> float:
        positions_value = 0.0
        for symbol, pos in self.positions.items():
            px = current_prices.get(symbol, pos["entry_price"])
            positions_value += pos["amount"] * px
        return self.cash_eur + positions_value

    def open_long(
        self,
        symbol: str,
        market_price: float,
        amount: float,
        stop_loss: float,
        take_profit: float,
        reason: str = "SIGNAL_BUY",
    ) -> dict | None:
        exec_price = market_price * (1.0 + config.SLIPPAGE_RATE)
        gross_value = amount * exec_price
        fee_eur = gross_value * config.FEE_RATE
        slippage_eur = abs(exec_price - market_price) * amount
        total_cost = gross_value + fee_eur

        if total_cost > self.cash_eur:
            return None

        self.cash_eur -= total_cost
        now_iso = datetime.now(timezone.utc).isoformat()

        position = {
            "symbol": symbol,
            "amount": amount,
            "entry_price": exec_price,
            "entry_fee_eur": fee_eur,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "opened_at": now_iso,
        }
        self.positions[symbol] = position

        self._append_csv(
            [
                now_iso,
                self.session_id,
                symbol,
                "BUY",
                f"{exec_price:.6f}",
                f"{amount:.8f}",
                f"{gross_value:.4f}",
                f"{fee_eur:.4f}",
                f"{slippage_eur:.4f}",
                "0.0000",
                f"{self.cash_eur:.4f}",
                reason,
            ]
        )
        return position

    def close_long(self, symbol: str, market_price: float, reason: str) -> float | None:
        pos = self.positions.get(symbol)
        if not pos:
            return None

        exec_price = market_price * (1.0 - config.SLIPPAGE_RATE)
        gross_proceeds = pos["amount"] * exec_price
        fee_eur = gross_proceeds * config.FEE_RATE
        slippage_eur = abs(market_price - exec_price) * pos["amount"]
        net_proceeds = gross_proceeds - fee_eur

        entry_total_cost = (pos["amount"] * pos["entry_price"]) + pos["entry_fee_eur"]
        net_pnl_eur = net_proceeds - entry_total_cost

        self.cash_eur += net_proceeds
        del self.positions[symbol]

        now_iso = datetime.now(timezone.utc).isoformat()
        self._append_csv(
            [
                now_iso,
                self.session_id,
                symbol,
                "SELL",
                f"{exec_price:.6f}",
                f"{pos['amount']:.8f}",
                f"{gross_proceeds:.4f}",
                f"{fee_eur:.4f}",
                f"{slippage_eur:.4f}",
                f"{net_pnl_eur:.4f}",
                f"{self.cash_eur:.4f}",
                reason,
            ]
        )
        return net_pnl_eur
