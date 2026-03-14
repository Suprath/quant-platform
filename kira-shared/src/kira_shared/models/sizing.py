from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List

class SizingRequest(BaseModel):
    request_id: str
    symbol: str
    strategy_id: str
    signal_type: str
    direction: str  # BUY/SELL
    entry_price: float
    stop_price: Optional[float] = None
    confidence_score: float = 1.0

class SizingResult(BaseModel):
    request_id: str
    symbol: str
    approved: bool
    rejection_reason: Optional[str] = None
    shares: int = 0
    position_value: float = 0.0
    risk_pct_nav: float = 0.0
    net_ev: float = 0.0
    exit_plan: Optional[dict] = None
