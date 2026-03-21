from datetime import datetime
from typing import Optional
from .base_strategy import BaseStrategy, RawSignal
from kira_shared.models.market import FeatureVector
try:
    import til_core
    HAS_TIL_CORE = True
except ImportError:
    HAS_TIL_CORE = False

class AccumulationBreakoutStrategy(BaseStrategy):
    """
    Fires when a stock is in or ending accumulation phase.
    """
    
    async def evaluate(
        self,
        symbol: str,
        features: FeatureVector
    ) -> Optional[RawSignal]:
        
        # Accumulation setup conditions
        if features.adx > 28:
            return None     # Already trending, not accumulating
        
        if features.atr_slope_5d > 0.001:
            return None     # Volatility expanding, not contracting
        
        if features.obv_slope_5d <= 0:
            return None     # OBV must be positive (accumulation)
        
        if features.momentum_5d < -0.015:
            return None     # Too much recent weakness
        
        if features.volume_cv_10d > 0.60:
            return None     # Volume too inconsistent
        
        score = self.get_pattern_score(features)
        if score < 0.40:
            return None
        
        return RawSignal(
            signal_id=          f"sg_{symbol}_acc_{datetime.utcnow():%Y%m%d%H%M%S}",
            symbol=             symbol,
            signal_type=        "accumulation_breakout_buy",
            direction=          "LONG",
            timestamp=          datetime.utcnow(),
            pattern_score=      score,
            entry_price_estimate= features.close,
            stop_price_estimate=  self.compute_stop(features),
            pattern_features={
                "adx":            features.adx,
                "atr_slope":      features.atr_slope_5d,
                "obv_slope":      features.obv_slope_5d,
                "volume_cv":      features.volume_cv_10d,
                "hurst":          features.hurst
            },
            features=           features.dict()
        )
    
    def get_pattern_score(self, features: FeatureVector) -> float:
        if HAS_TIL_CORE:
            # Explicitly pass all 5 required institutional parameters
            return til_core.score_accumulation_pattern(
                float(features.adx),
                float(features.atr_slope_5d),
                float(features.obv_slope_5d),
                float(features.momentum_5d),
                float(features.hurst)
            )
        # Fallback to Python logic
        adx_score    = max(0, 1.0 - (features.adx / 25))
        atr_score    = max(0, -features.atr_slope_5d / 0.002)
        atr_score    = min(1.0, atr_score)
        obv_score    = min(1.0, features.obv_slope_5d / 0.005)
        flat_score   = max(0, 1.0 - abs(features.momentum_5d) / 0.015)
        hurst_score  = min(1.0, max(0, (features.hurst - 0.45) / 0.15))
        
        return (adx_score  * 0.20 +
                atr_score  * 0.25 +
                obv_score  * 0.25 +
                flat_score * 0.20 +
                hurst_score * 0.10)
    
    def compute_stop(self, features: FeatureVector) -> float:
        # Accumulation stop: ATR x 1.5 below current price
        return round(features.close - (features.atr_price * 1.5), 2)
