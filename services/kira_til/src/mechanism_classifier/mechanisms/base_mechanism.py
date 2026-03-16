from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, Tuple, List, Optional
from ..classifier import MechanismResult
from ...signal_generator.strategies.base_strategy import RawSignal
from kira_shared.models.market import FeatureVector, MarketContext

class BaseMechanism(ABC):
    
    @abstractmethod
    async def check(
        self,
        signal: RawSignal,
        features: FeatureVector,
        context: MarketContext
    ) -> MechanismResult:
        """
        Runs mechanism specific checks.
        """
        pass
