from .models import PortfolioState, Position
from typing import Dict, List
try:
    import til_core
    HAS_TIL_CORE = True
except ImportError:
    HAS_TIL_CORE = False

class FactorManager:
    """
    Manages Sector and Factor Exposure.
    Ensures the portfolio isn't overly concentrated in one industry or group.
    """
    
    def __init__(self, max_sector_exposure_pct: float = 30.0):
        self.max_sector_exposure_pct = max_sector_exposure_pct
        # Standard SECTOR Mapping for Indian Market if not provided
        self.sector_limits = {
            "BANKING": 35.0,
            "IT": 25.0,
            "ENERGY": 20.0,
            "FMCG": 20.0,
            "PHARMA": 15.0
        }

    def calculate_exposures(self, state: PortfolioState):
        if state.total_equity <= 0:
            return
            
        sector_totals = {}
        for pos in state.open_positions:
            val = pos.market_value
            sector_totals[pos.sector] = sector_totals.get(pos.sector, 0.0) + val
            
        state.sector_exposure = {
            s: (v / state.total_equity) * 100 
            for s, v in sector_totals.items()
        }

    def validate_sector_limit(self, state: PortfolioState, sector: str, trade_value: float) -> (bool, str):
        self.calculate_exposures(state)
        
        if HAS_TIL_CORE:
            new_exp = ((trade_value) / state.total_equity) * 100 if state.total_equity > 0 else 0
            limit = self.sector_limits.get(sector, self.max_sector_exposure_pct)
            
            # current_heat=0 because we only care about sector here
            res = til_core.validate_risk_batch(
                0.0, 
                100.0, 
                new_exp, 
                state.sector_exposure, 
                sector, 
                limit
            )
            
            if not res.approved:
                return False, res.reason
            
            return True, "Sector Approved"
            
        current_exp = state.sector_exposure.get(sector, 0.0)
        new_exp = ((trade_value) / state.total_equity) * 100
        total_exp = current_exp + new_exp
        limit = self.sector_limits.get(sector, self.max_sector_exposure_pct)
        if total_exp > limit:
            return False, f"SEC_LIMIT_EXCEEDED"
        return True, "Sector Approved"
