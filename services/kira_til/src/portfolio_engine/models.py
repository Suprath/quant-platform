from pydantic import BaseModel, Field
from typing import List, Dict, Optional
from datetime import datetime

class Position(BaseModel):
    symbol: str
    direction: str  # LONG / SHORT
    qty: int
    entry_price: float
    current_price: float
    market_value: float
    risk_at_risk: float  # Amount at risk (Entry - Stop)
    sector: str
    factor_betas: Dict[str, float] = {}

class PortfolioState(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.now)
    total_equity: float = 0.0
    cash: float = 0.0
    used_margin: float = 0.0
    open_positions: List[Position] = []
    
    # Risk Metrics
    total_heat_pct: float = 0.0  # (Total Risk / Equity) * 100
    daily_var_pct: float = 0.0
    
    # Factor Exposures
    sector_exposure: Dict[str, float] = {}  # Sector -> % of Equity
    factor_exposure: Dict[str, float] = {}  # Factor -> Weight

class TradeApprovalRequest(BaseModel):
    symbol: str
    direction: str
    qty: int
    entry_price: float
    stop_loss: float
    sector: Optional[str] = "Unknown"
    
class TradeApprovalResponse(BaseModel):
    approved: bool
    reason: Optional[str] = None
    max_qty_allowed: int
    adjusted_qty: int
    risk_metrics_post_trade: Optional[Dict[str, float]] = None
