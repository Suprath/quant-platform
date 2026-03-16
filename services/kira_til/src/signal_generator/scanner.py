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
        Runs concurrently for all stocks.
        """
        tasks = [
            self._scan_stock(symbol, features)
            for symbol, features in features_batch.items()
        ]
        
        results = await asyncio.gather(*tasks)
        
        fired_signals = []
        for signal_list in results:
            fired_signals.extend(signal_list)
            
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
