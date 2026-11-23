"""
Configuration centrale du bot en mode simulation (PAPER).
Toutes les règles de session, de stratégie et de risque sont regroupées ici.
"""

# Sécurité : le bot reste en simulation ("PAPER") par défaut.
MODE = "PAPER"

# Exchange public utilisé pour récupérer les bougies (OHLCV) via ccxt
EXCHANGE_ID = "kraken"

# Paires Spot surveillées (pas d'effet de levier, pas de short)
SYMBOLS = ["BTC/EUR", "ETH/EUR"]

# Timeframe : bougies de 5 minutes
TIMEFRAME = "5m"
OHLCV_LIMIT = 120  # Assez de bougies pour calculer EMA(50), RSI(14) et ATR(14)

# Durée d'une session sur GitHub Actions (en minutes)
SESSION_DURATION_MINUTES = 120

# À partir de la 105e minute (120 - 15), on n'ouvre plus rien et on ferme toute position ouverte
CLOSE_BEFORE_END_MINUTES = 15

# Pause entre deux vérifications de marché (en secondes)
LOOP_SLEEP_SECONDS = 60

# Capital initial virtuel pour la simulation
INITIAL_CAPITAL_EUR = 100.0

# Frais et glissement (slippage) simulés à chaque ordre (achat ou vente)
FEE_RATE = 0.0010       # 0.10 % de frais simulés par transaction
SLIPPAGE_RATE = 0.0005  # 0.05 % de slippage simulé par transaction

# Paramètres de la stratégie (Tendance + Momentum + Volatilité)
EMA_FAST = 9
EMA_SLOW = 21
EMA_TREND = 50
RSI_PERIOD = 14
RSI_MIN = 45.0
RSI_MAX = 65.0
VOLUME_SMA_PERIOD = 20
ATR_PERIOD = 14
ATR_SL_MULTIPLIER = 1.5
RISK_REWARD_RATIO = 2.0  # Take-Profit à 2x la distance du Stop-Loss (1.5 * 2 = 3.0 * ATR)

# Gestion du risque (Risk Management)
MAX_RISK_PER_TRADE_PCT = 0.01   # 1 % du capital actuel max par trade (ex: 1,00 € sur 100 €)
MIN_ORDER_VALUE_EUR = 10.0      # Montant minimum d'un ordre simulé en euros
MAX_OPEN_POSITIONS = 1          # Maximum 1 position ouverte à la fois
MAX_TRADES_PER_SESSION = 3      # Maximum 3 trades par session de 2h
COOLDOWN_MINUTES = 15           # Délai minimum entre deux trades
MAX_SESSION_LOSS_PCT = 0.03     # Kill switch : arrêt si perte session >= 3 % (ex: 3,00 €)
MAX_CONSECUTIVE_LOSSES = 2    # Kill switch : arrêt après 2 Stop-Loss consécutifs

# Fichiers de sortie
TRADES_CSV_PATH = "trades_history.csv"
STATE_JSON_PATH = "state.json"
