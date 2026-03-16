from pydantic import BaseModel
from datetime import datetime, date, time
from typing import Optional, Dict, Any, List

class TradeRecord(BaseModel):
    trade_id: str
    signal_id: str
    symbol: str
    direction: str
    
    entry_date: date
    entry_time: time
    entry_price: float
    shares: int
    position_value: float
    entry_costs: float = 0.0
    
    # Signal context
    primary_mechanism: Optional[str] = None
    mechanism_confidence: float = 0.0
    market_regime: Optional[str] = None
    pattern_score: float = 0.0
    
    # Exit data (filled later)
    exit_date: Optional[date] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    net_pnl: float = 0.0
    return_r: float = 0.0
    
    # Excursion metrics
    max_adverse_excursion: float = 0.0  # MAE in R
    max_favorable_excursion: float = 0.0 # MFE in R
    capture_ratio: float = 0.0
    
    result: str = "OPEN" # OPEN, WIN, LOSS, BREAKEVEN
