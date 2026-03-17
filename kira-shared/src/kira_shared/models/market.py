from pydantic import BaseModel
from datetime import datetime

class PriceBar(BaseModel):
    symbol:     str
    timestamp:  datetime
    open:       float
    high:       float
    low:        float
    close:      float
    volume:     int
    vwap:       float | None = None

class FeatureVector(BaseModel):
    symbol:             str
    timestamp:          datetime
    close:              float
    adx:                float
    adx_slope_5d:       float
    hurst:              float
    hurst_slope_5d:     float
    momentum_5d:        float
    momentum_21d:       float
    momentum_63d:       float
    obv_slope_5d:       float
    obv_slope_21d:      float
    close_vs_50sma:     float
    close_vs_200sma:    float
    atr_pct:            float
    atr_price:          float
    atr_slope_5d:       float
    volume_ratio_1d:    float
    volume_cv_10d:      float
    rsi_14:             float
    beta_market_63d:    float
    beta_sector_63d:    float
    rs_vs_sector_21d:   float
    rs_vs_market_21d:   float
    weekly_adx:         float
    weekly_hurst:       float
    weekly_momentum_12w: float
    weekly_obv_slope:   float
    monthly_close_vs_12msma: float

class MarketContext(BaseModel):
    timestamp:              datetime
    nifty_level:            float
    nifty_return_today:     float
    india_vix:              float
    vix_slope_5d:           float
    pairwise_correlation:   float
    signal_density:         int
    market_regime:          str
    days_in_regime:         int
    expiry_proximity:       str
    sector_returns:         dict[str, float]
