from .base_mechanism import BaseMechanism
from ..classifier import MechanismResult
from ...signal_generator.strategies.base_strategy import RawSignal
from kira_shared.models.market import FeatureVector, MarketContext

class AccumulationMechanism(BaseMechanism):
    """
    Checks for institutional accumulation footprint.
    """
    
    MECHANISM_TYPE = "ACCUMULATION"
    MINIMUM_SCORE = 0.65
    
    async def check(
        self,
        signal: RawSignal,
        features: FeatureVector,
        context: MarketContext
    ) -> MechanismResult:
        
        # High-performance C++ scoring
        try:
            import til_core
            score = til_core.score_accumulation_pattern(
                features.obv_slope_5d,
                features.adx,
                0.0, # vwap_dist (could add to features later)
                features.volume_cv_10d
            ) / 100.0 # Convert back to 0-1 range
        except ImportError:
            # Fallback
            obv_score = min(1.0, features.obv_slope_5d / 0.005)
            adx_score = max(0, 1.0 - (features.adx / 30))
            vol_score = max(0, 1.0 - (features.volume_cv_10d / 0.8))
            score = (obv_score * 0.4 + adx_score * 0.3 + vol_score * 0.3)
        
        if score < self.MINIMUM_SCORE:
            return MechanismResult(
                is_present=False,
                mechanism_type=self.MECHANISM_TYPE,
                confidence=score
            )
            
        return MechanismResult(
            is_present=True,
            mechanism_type=self.MECHANISM_TYPE,
            confidence=score,
            evidence={
                "obv_slope": features.obv_slope_5d,
                "adx": features.adx,
                "volume_cv": features.volume_cv_10d
            },
            thesis_components={
                "strength": "STRONG" if score > 0.70 else "MODERATE",
                "near_completion": features.hurst > 0.55
            },
            invalidation_triggers=[
                "obv_slope_turns_negative",
                "price_closes_below_range_low",
                "volume_surges_on_down_day"
            ],
            expected_days=(5, 15)
        )
