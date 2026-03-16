from datetime import datetime
from typing import Optional
from .base_strategy import BaseStrategy, RawSignal
from kira_shared.models.market import FeatureVector

class MomentumContinuationStrategy(BaseStrategy):
    """
    Fires when stock shows momentum continuation setup.
    Just checks if the price pattern is present.
    """
    
    async def evaluate(
        self,
        symbol: str,
        features: FeatureVector
    ) -> Optional[RawSignal]:
        
        # Pattern conditions — pure indicator thresholds
        if features.adx < 22:
            return None
        
        if features.momentum_21d < 0.008:
            return None
        
        if features.close_vs_50sma < 0:
            return None
        
        if features.hurst < 0.52:
            return None
        
        if features.obv_slope_5d <= 0:
            return None
        
        if features.rs_vs_sector_21d < -0.005:
            return None
        
        # Pattern matched — compute quality
        score = self.get_pattern_score(features)
        
        if score < 0.35:
            return None
        
        return RawSignal(
            signal_id=          f"sg_{symbol}_mom_{datetime.utcnow():%Y%m%d%H%M%S}",
            symbol=             symbol,
            signal_type=        "momentum_continuation_buy",
            direction=          "LONG",
            timestamp=          datetime.utcnow(),
            pattern_score=      score,
            entry_price_estimate= features.close,
            stop_price_estimate=  self.compute_stop(features),
            pattern_features={
                "adx":           features.adx,
                "momentum_21d":  features.momentum_21d,
                "hurst":         features.hurst,
                "obv_slope":     features.obv_slope_5d,
                "rs_sector":     features.rs_vs_sector_21d
            },
            features=           features.dict()
        )
    
    def get_pattern_score(self, features: FeatureVector) -> float:
        adx_score     = min(1.0, (features.adx - 22) / 18)
        mom_score     = min(1.0, features.momentum_21d / 0.04)
        hurst_score   = min(1.0, (features.hurst - 0.52) / 0.18)
        obv_score     = 1.0 if features.obv_slope_5d > 0.002 else 0.5
        rs_score      = min(1.0, max(0, features.rs_vs_sector_21d / 0.02))
        sma_score     = min(1.0, features.close_vs_50sma / 0.03)
        
        return (adx_score   * 0.20 +
                mom_score   * 0.25 +
                hurst_score * 0.20 +
                obv_score   * 0.15 +
                rs_score    * 0.10 +
                sma_score   * 0.10)
    
    def compute_stop(self, features: FeatureVector) -> float:
        atr_stop = features.close - (features.atr_price * 2.0)
        # In a real scenario we'd have swing_low from an indicator
        # For now, ATR-based stop is the anchor
        return round(atr_stop, 2)
