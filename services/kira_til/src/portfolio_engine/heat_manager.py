from .models import PortfolioState, Position
from typing import List

class HeatManager:
    """
    Manages Portfolio Heat and Risk Exposure.
    Heat = (Total Risk / Total Equity) * 100
    Total Risk = Sum of (Entry Price - Stop Loss) for all positions
    """
    
    def __init__(self, max_heat_pct: float = 10.0, max_single_stock_risk_pct: float = 2.0):
        self.max_heat_pct = max_heat_pct
        self.max_single_stock_risk_pct = max_single_stock_risk_pct

    def calculate_heat(self, state: PortfolioState) -> float:
        if state.total_equity <= 0:
            return 0.0
            
        total_risk = sum(pos.risk_at_risk * pos.qty for pos in state.open_positions)
        state.total_heat_pct = (total_risk / state.total_equity) * 100
        return state.total_heat_pct

    def validate_trade_risk(self, state: PortfolioState, risk_amount: float) -> (bool, str):
        """
        Check if adding a new trade exceeds risk limits using C++ til_core.
        """
        try:
            import til_core
            # new_risk_pct = (risk_amount / state.total_equity) * 100
            # risk_at_risk is already absolute currency risk, state.total_equity is currency.
            # til_core.validate_risk_batch(current_heat, max_heat, new_risk, sector_exp, sector, sector_limit)
            
            current_heat = self.calculate_heat(state)
            new_risk_pct = (risk_amount / state.total_equity) * 100 if state.total_equity > 0 else 0
            
            # For HeatManager, we don't care about sector, so we pass defaults
            res = til_core.validate_risk_batch(
                current_heat, 
                self.max_heat_pct, 
                new_risk_pct, 
                {}, 
                "UNKNOWN", 
                100.0
            )
            
            if not res.approved:
                return False, res.reason
            
            if new_risk_pct > self.max_single_stock_risk_pct:
                 return False, f"SINGLE_STOCK_RISK_LIMIT_EXCEEDED: {new_risk_pct:.2f}%"

            return True, "Risk Approved"
        except ImportError:
            # Fallback to Python logic if C++ extension isn't loaded
            current_heat = self.calculate_heat(state)
            new_risk_pct = (risk_amount / state.total_equity) * 100
            if (current_heat + new_risk_pct) > self.max_heat_pct:
                return False, "TOTAL_HEAT_LIMIT_EXCEEDED"
            return True, "Risk Approved"
