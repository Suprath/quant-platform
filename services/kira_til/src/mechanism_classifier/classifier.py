import asyncio
import time
import logging
from typing import List, Optional
from .models import ClassifiedSignal, MechanismResult, Thesis
from .mechanisms.m1_accumulation import AccumulationMechanism
from .thesis_generator import ThesisGenerator
from ..signal_generator.strategies.base_strategy import RawSignal
from kira_shared.models.market import FeatureVector, MarketContext

logger = logging.getLogger("MechanismClassifier")

class MechanismClassifier:
    """
    Orchestrates multiple mechanism checks to validate signals.
    """
    
    def __init__(self):
        self.mechanisms = [
            AccumulationMechanism(),
            # ShortSqueezeMechanism(),
            # MomentumContinuationMechanism(),
        ]
        self.thesis_generator = ThesisGenerator()
    
    async def classify(
        self,
        signal: RawSignal,
        features: FeatureVector,
        market_context: MarketContext
    ) -> ClassifiedSignal:
        
        start_ms = time.monotonic() * 1000
        
        # Run all mechanism checks concurrently
        tasks = [
            asyncio.create_task(m.check(signal, features, market_context))
            for m in self.mechanisms
        ]
        
        results = await asyncio.gather(*tasks)
        
        # Filter to present mechanisms
        present = [r for r in results if r.is_present]
        
        if not present:
            logger.info(f"Signal {signal.symbol} discarded: No mechanism found (Max Conf: {max([r.confidence for r in results] or [0]):.2f})")
            return ClassifiedSignal(
                signal_id=      signal.signal_id,
                symbol=         signal.symbol,
                signal_type=    signal.signal_type,
                direction=      signal.direction,
                has_mechanism=  False,
                action=         "DISCARD",
                computation_ms= time.monotonic() * 1000 - start_ms
            )
        
        # Primary = strongest mechanism
        primary = max(present, key=lambda m: m.confidence)
        supporting = [m for m in present if m != primary]
        
        # Generate thesis
        thesis = self.thesis_generator.generate(
            signal=signal,
            primary_mechanism=primary,
            supporting=supporting
        )
        
        return ClassifiedSignal(
            signal_id=          signal.signal_id,
            symbol=             signal.symbol,
            signal_type=        signal.signal_type,
            direction=          signal.direction,
            has_mechanism=      True,
            primary_mechanism=  primary.mechanism_type,
            mechanism_confidence=primary.confidence,
            pattern_score=      signal.pattern_score,
            thesis=             thesis.statement,
            invalidation_conditions=thesis.invalidation_conditions,
            expected_days_min=  primary.expected_days[0],
            expected_days_max=  primary.expected_days[1],
            supporting_mechanisms=[s.mechanism_type for s in supporting],
            action=             "PROCEED_TO_PORTFOLIO_ENGINE",
            computation_ms=     time.monotonic() * 1000 - start_ms
        )
