import os
from .portfolio_engine.engine import PortfolioEngine
from .signal_generator.scanner import UniverseScanner
from .signal_generator.strategies.momentum_continuation import MomentumContinuationStrategy
from .signal_generator.strategies.accumulation_breakout import AccumulationBreakoutStrategy
from .mechanism_classifier.classifier import MechanismClassifier
from .clients import NoiseFilterClient, PositionSizerClient

# Environment Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
INITIAL_CAPITAL = float(os.getenv("INITIAL_CAPITAL", "100000.0"))

# Singleton Component Registry
portfolio_engine = PortfolioEngine(redis_host=REDIS_HOST, initial_capital=INITIAL_CAPITAL)
mechanism_classifier = MechanismClassifier()
noise_filter = NoiseFilterClient()
position_sizer = PositionSizerClient()
scanner = UniverseScanner(strategies=[
    MomentumContinuationStrategy(),
    AccumulationBreakoutStrategy()
])
