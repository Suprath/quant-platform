import pytest
from src.portfolio_engine.models import PortfolioState, Position, TradeApprovalRequest
from src.portfolio_engine.heat_manager import HeatManager
from src.portfolio_engine.factor_exposure import FactorManager

def test_heat_calculation():
    manager = HeatManager(max_heat_pct=10.0)
    state = PortfolioState(
        total_equity=100000.0,
        cash=100000.0,
        used_margin=0.0,
        open_positions=[
            Position(
                symbol="RELIANCE",
                direction="LONG",
                qty=10,
                entry_price=2500.0,
                current_price=2500.0,
                market_value=25000.0,
                risk_at_risk=50.0,  # 50 per share risk
                sector="ENERGY"
            )
        ]
    )
    
    heat = manager.calculate_heat(state)
    assert heat == 0.5  # (50 * 10) / 100000 * 100 = 0.5%

def test_heat_limit_validation():
    manager = HeatManager(max_heat_pct=10.0)
    state = PortfolioState(total_equity=100000.0, cash=100000.0)
    
    # Try a trade with 1% risk -> OK
    ok, msg = manager.validate_trade_risk(state, 1000.0)
    assert ok is True
    
    # Try a trade with 11% risk -> REJECT
    ok, msg = manager.validate_trade_risk(state, 11000.0)
    assert ok is False
    assert "TOTAL_HEAT_LIMIT_EXCEEDED" in msg

def test_sector_exposure_validation():
    manager = FactorManager(max_sector_exposure_pct=30.0)
    state = PortfolioState(
        total_equity=100000.0,
        cash=100000.0,
        open_positions=[
            Position(
                symbol="TCS",
                direction="LONG",
                qty=10,
                entry_price=3000.0,
                current_price=3000.0,
                market_value=30000.0,
                risk_at_risk=60.0,
                sector="IT"
            )
        ]
    )
    
    # IT sector exposure is already 30%
    manager.calculate_exposures(state)
    assert state.sector_exposure["IT"] == 30.0
    
    # Adding more IT -> REJECT
    ok, msg = manager.validate_sector_limit(state, "IT", 5000.0)
    assert ok is False
    assert "SEC_LIMIT_EXCEEDED" in msg
    
    # Adding ENERGY -> OK
    ok, msg = manager.validate_sector_limit(state, "ENERGY", 5000.0)
    assert ok is True
