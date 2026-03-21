import asyncio
import logging
from typing import List, Dict
from .strategies.base_strategy import BaseStrategy, RawSignal
from kira_shared.models.market import FeatureVector

logger = logging.getLogger("UniverseScanner")

class UniverseScanner:
    """
    Scans stocks against all strategy patterns.
    """
    
    def __init__(self, strategies: List[BaseStrategy]):
        self.strategies = strategies
    
    async def scan(self, features_batch: Dict[str, FeatureVector]) -> List[RawSignal]:
        """
        Runs sequentially for all stocks (optimized for backtest).
        """
        fired_signals = []
        for symbol, features in features_batch.items():
            try:
                stock_signals = await self._scan_stock(symbol, features)
                if stock_signals:
                    fired_signals.extend(stock_signals)
            except Exception as e:
                logger.error(f"Error scanning {symbol}: {e}")
            
        return fired_signals
    
    async def _scan_stock(
        self,
        symbol: str,
        features: FeatureVector
    ) -> List[RawSignal]:
        
        signals = []
        for strategy in self.strategies:
            try:
                signal = await strategy.evaluate(symbol, features)
                if signal:
                    signals.append(signal)
            except Exception as e:
                logger.error(f"Error evaluating {strategy.__class__.__name__} for {symbol}: {e}")
        
        return signals
