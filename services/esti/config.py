# ESTI — Evolutionary Survival Trading Intelligence
"""ESTI Core Configuration and Constants."""

import os
import torch
import logging
from datetime import timezone, timedelta

# ─────────────────────────────────────────────────────────
#  LOGGING SETUP — Detailed, structured, and consistent
# ─────────────────────────────────────────────────────────

LOG_FORMAT = "%(asctime)s | %(name)-20s | %(levelname)-7s | %(message)s"
LOG_LEVEL = os.getenv("ESTI_LOG_LEVEL", "DEBUG")

def setup_logger(name: str) -> logging.Logger:
    """Create a consistently-formatted logger with the given name."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))
        logger.addHandler(handler)
    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.DEBUG))
    return logger

# ─────────────────────────────────────────────────────────
#  HARDWARE
# ─────────────────────────────────────────────────────────

DEVICE = "cpu"  # Docker containers use CPU; MPS/CUDA for native
if torch.backends.mps.is_available():
    DEVICE = "mps"
elif torch.cuda.is_available():
    DEVICE = "cuda"

# ─────────────────────────────────────────────────────────
#  API GATEWAY (data source)
# ─────────────────────────────────────────────────────────

API_GATEWAY_URL = os.getenv("API_GATEWAY_URL", "http://api_gateway:8000")

# ─────────────────────────────────────────────────────────
#  POPULATION & NEURAL NETWORK
# ─────────────────────────────────────────────────────────

POPULATION_SIZE = int(os.getenv("ESTI_POPULATION_SIZE", "30"))
STATE_DIM       = 20       # Feature vector dimensionality
BRAIN_DIM       = 64       # SharedBrain output dimensionality
HIDDEN_DIM      = 128      # Hidden layer width
LEARNING_RATE   = 3e-4

# ─────────────────────────────────────────────────────────
#  SURVIVAL ENGINE  (Theory Sections 3-6)
# ─────────────────────────────────────────────────────────

INITIAL_CAPITAL = 100_000.0  # ₹1,00,000 per agent
BASE_GROWTH     = 0.001      # G_base: minimum 0.1% growth required
HEALTH_DECAY    = 0.03       # λ: health penalty per stagnation step
GROWTH_WINDOW   = 20         # k: lookback window for growth calc

# Composite Survival Score weights: Σ = w_c·C̃ + w_g·G̃ + w_h·H + w_r·R
WEIGHT_CAPITAL  = 0.4   # w_c
WEIGHT_GROWTH   = 0.3   # w_g
WEIGHT_HEALTH   = 0.2   # w_h
WEIGHT_RANK     = 0.1   # w_r

# ─────────────────────────────────────────────────────────
#  TRAINING
# ─────────────────────────────────────────────────────────

EVOLUTION_INTERVAL   = 100    # Steps between evolutionary cycles
CHECKPOINT_INTERVAL  = 500    # Steps between state saves
MUTATION_SIGMA       = 0.1    # Gaussian mutation std
CROSSOVER_RATE       = 0.3    # Probability of crossover
TOURNAMENT_SIZE      = 5      # Tournament selection pool

# Growth Pressure (Push until Plateau)
PRESSURE_LOOKBACK    = 3      # Cycles to check for stagnation
MIN_IMPROVEMENT      = 0.05   # 5% Sharpe improvement required
MAX_PRESSURE_LEVEL   = 3      # Max escalation level
BREAKOUT_CYCLES      = 5      # Aggressive cycles to break plateau

# ─────────────────────────────────────────────────────────
#  SHARPE OPTIMISER  (India-specific)
# ─────────────────────────────────────────────────────────

RISK_FREE_RATE   = 0.071       # India 10-Year Government Bond ~7.1%
SHARPE_WINDOW    = 252         # Rolling window (1 trading year)
SHARPE_ELITE_THR = 2.0         # Archive agents with Sharpe > 2

# ─────────────────────────────────────────────────────────
#  RISK / CIRCUIT BREAKERS
# ─────────────────────────────────────────────────────────

MAX_DRAWDOWN         = 0.20    # 20% drawdown → halt
MAX_POSITION_SIZE    = 0.50    # Max 50% of capital per trade
MIN_POPULATION       = 5       # Emergency repopulate threshold
MAX_CORRELATION      = 0.80    # Warn if agents too correlated
SHARPE_FLOOR         = -1.0    # Halt if Sharpe falls below
KELLY_FRACTION       = 0.5     # Half-Kelly for safety
MAX_SINGLE_TRADE     = 0.25    # Max 25% per trade

# ─────────────────────────────────────────────────────────
#  MARKET (Indian NSE)
# ─────────────────────────────────────────────────────────

IST = timezone(timedelta(hours=5, minutes=30))
MARKET_OPEN_HOUR    = 9
MARKET_OPEN_MINUTE  = 15
MARKET_CLOSE_HOUR   = 15
MARKET_CLOSE_MINUTE = 30

# Backfilled stocks (same as backfiller service)
DEFAULT_SYMBOLS = [
    "NSE_EQ|INE002A01018",  # RELIANCE
    "NSE_EQ|INE040A01034",  # HDFCBANK
    "NSE_EQ|INE090A01021",  # TCS
    "NSE_EQ|INE009A01021",  # INFY
    "NSE_EQ|INE467B01029",  # ICICIBANK
    "NSE_EQ|INE062A01020",  # SBIN
    "NSE_EQ|INE154A01025",  # ITC
    "NSE_EQ|INE669E01016",  # BAJFINANCE
    "NSE_EQ|INE030A01027",  # HINDUNILVR
    "NSE_EQ|INE585B01010",  # MARUTI
]

SYMBOL_NAMES = {
    "NSE_EQ|INE002A01018": "RELIANCE",
    "NSE_EQ|INE040A01034": "HDFCBANK",
    "NSE_EQ|INE090A01021": "TCS",
    "NSE_EQ|INE009A01021": "INFY",
    "NSE_EQ|INE467B01029": "ICICIBANK",
    "NSE_EQ|INE062A01020": "SBIN",
    "NSE_EQ|INE154A01025": "ITC",
    "NSE_EQ|INE669E01016": "BAJFINANCE",
    "NSE_EQ|INE030A01027": "HINDUNILVR",
    "NSE_EQ|INE585B01010": "MARUTI",
}

# ─────────────────────────────────────────────────────────
#  PERSISTENCE
# ─────────────────────────────────────────────────────────

CHECKPOINT_DIR  = os.getenv("ESTI_CHECKPOINT_DIR", "/app/checkpoints")
ARCHIVE_DB_PATH = os.getenv("ESTI_ARCHIVE_DB", "/app/checkpoints/knowledge_archive.db")
