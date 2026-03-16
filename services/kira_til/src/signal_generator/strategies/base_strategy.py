from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, Any, Optional
from kira_shared.models.market import FeatureVector

@dataclass
class RawSignal:
    """
    Output of signal generator.
    No mechanism, no validation.
    Just: what to trade and basic pattern quality.
    """
    signal_id:          str
    symbol:             str
    signal_type:        str
    direction:          str          # LONG / SHORT
    timestamp:          datetime
    
    # Pattern quality from strategy's own logic
    pattern_score:      float        # 0-1: how well does it match ideal?
    
    # Context the mechanism classifier needs
    entry_price_estimate: float
    stop_price_estimate:  float
    pattern_features:   Dict[str, Any]         # Strategy-specific features
    
    # Raw feature snapshot
    features:           Dict[str, Any]

    def to_dict(self):
        d = asdict(self)
        d['timestamp'] = self.timestamp.isoformat()
        return d

class BaseStrategy(ABC):
    
    @abstractmethod
    async def evaluate(
        self,
        symbol: str,
        features: FeatureVector
    ) -> Optional[RawSignal]:
        """
        Returns signal if pattern conditions met.
        Returns None if no signal.
        """
        pass
    
    @abstractmethod
    def get_pattern_score(self, features: FeatureVector) -> float:
        """
        0-1: how closely does this match the ideal setup?
        """
        pass
    
    @abstractmethod
    def compute_stop(self, features: FeatureVector) -> float:
        """
        Technical stop price based on strategy-specific logic.
        """
        pass
