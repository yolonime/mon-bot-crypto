"""
Gestion stricte du risque pour un petit capital (ex: 100 €).
"""

from datetime import datetime, timezone
import config


class RiskManager:
    def __init__(self, initial_session_capital: float):
        self.session_start_capital = initial_session_capital
        self.trades_this_session = 0
        self.consecutive_losses = 0
        self.last_trade_time: datetime | None = None
        self.kill_switch_triggered = False
        self.kill_reason = ""

    def check_kill_switch(self, current_capital: float) -> tuple[bool, str]:
        if self.kill_switch_triggered:
            return True, self.kill_reason

        session_loss = self.session_start_capital - current_capital
        max_allowed_loss = self.session_start_capital * config.MAX_SESSION_LOSS_PCT

        if session_loss >= max_allowed_loss:
            self.kill_switch_triggered = True
            self.kill_reason = (
                f"Perte session atteinte ({session_loss:.2f} € >= limite {max_allowed_loss:.2f} €)"
            )
            return True, self.kill_reason

        if self.consecutive_losses >= config.MAX_CONSECUTIVE_LOSSES:
            self.kill_switch_triggered = True
            self.kill_reason = f"{self.consecutive_losses} Stop-Loss consécutifs atteints"
            return True, self.kill_reason

        return False, ""

    def can_open_trade(
        self,
        current_capital: float,
        open_positions_count: int,
        closing_soon: bool,
        now: datetime | None = None,
    ) -> tuple[bool, str]:
        if now is None:
            now = datetime.now(timezone.utc)

        killed, reason = self.check_kill_switch(current_capital)
        if killed:
            return False, f"Kill switch actif : {reason}"

        if closing_soon:
            return False, "Fenêtre de fin de session active : ouverture bloquée"

        if open_positions_count >= config.MAX_OPEN_POSITIONS:
            return False, f"Limite de positions simultanées atteinte ({config.MAX_OPEN_POSITIONS})"

        if self.trades_this_session >= config.MAX_TRADES_PER_SESSION:
            return False, f"Limite de trades par session atteinte ({config.MAX_TRADES_PER_SESSION})"

        if self.last_trade_time is not None:
            elapsed_minutes = (now - self.last_trade_time).total_seconds() / 60.0
            if elapsed_minutes < config.COOLDOWN_MINUTES:
                return (
                    False,
                    f"Cooldown actif ({elapsed_minutes:.1f}/{config.COOLDOWN_MINUTES} min écoulées)",
                )

        return True, "OK"

    def calculate_position_size(
        self,
        current_capital: float,
        entry_price: float,
        stop_loss: float,
    ) -> tuple[float, float, str]:
        risk_distance = entry_price - stop_loss
        if risk_distance <= 0 or entry_price <= 0:
            return 0.0, 0.0, "Distance au Stop-Loss invalide"

        max_risk_eur = current_capital * config.MAX_RISK_PER_TRADE_PCT
        amount = max_risk_eur / risk_distance
        notional_eur = amount * entry_price

        if notional_eur > current_capital:
            notional_eur = current_capital
            amount = notional_eur / entry_price

        if notional_eur < config.MIN_ORDER_VALUE_EUR:
            return (
                0.0,
                notional_eur,
                f"Taille d'ordre ({notional_eur:.2f} €) inférieure au minimum requis ({config.MIN_ORDER_VALUE_EUR:.2f} €)",
            )

        return (
            amount,
            notional_eur,
            f"Taille validée : {amount:.6f} unités ({notional_eur:.2f} €), risque max ~{max_risk_eur:.2f} €",
        )

    def record_trade_opened(self, now: datetime | None = None) -> None:
        self.trades_this_session += 1
        self.last_trade_time = now if now is not None else datetime.now(timezone.utc)

    def record_trade_closed(self, net_pnl_eur: float) -> None:
        if net_pnl_eur < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
