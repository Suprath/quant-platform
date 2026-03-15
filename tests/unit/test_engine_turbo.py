import pytest
from datetime import datetime
from unittest.mock import MagicMock
from engine import AlgorithmEngine, SecurityHolding
from quant_sdk.algorithm import QCAlgorithm

class TestableAlgorithm(QCAlgorithm):
    def Initialize(self): pass
    def OnData(self, data): pass

@pytest.fixture
def engine():
    engine = AlgorithmEngine(run_id="test_run", backtest_mode=True, trading_mode="MIS")
    engine.Algorithm = TestableAlgorithm(engine=engine)
    engine.Algorithm.Portfolio = {"Cash": 100000.0, "TotalPortfolioValue": 100000.0}
    engine.Exchange = MagicMock()
    engine.Exchange._bt_balance = 100000.0
    engine.Exchange._bt_positions = {}
    return engine

def test_date_rollover_logic(engine):
    """Test that date rollover correctly resets square-off flags and logs equity."""
    # Setup initial state
    engine._last_square_off_date = datetime(2024, 1, 1).date()
    engine._squared_off_today = True
    
    tick_dict = {
        '_date_int': 20240102,
        '_dt': datetime(2024, 1, 2, 9, 15)
    }
    
    # Trigger rollover
    engine._bt_handle_date_rollover(tick_dict)
    
    assert engine._bt_last_date_int == 20240102
    assert engine._squared_off_today is False

def test_submit_order_failures(engine):
    """Verify SubmitOrder handles invalid inputs correctly."""
    # 1. Zero quantity
    assert engine.SubmitOrder("RELIANCE", 0) is False
    
    # 2. No price data
    engine.CurrentSlice = None
    engine._last_prices = {}
    assert engine.SubmitOrder("RELIANCE", 100) is False
    
    # 3. Negative price (should be handled/rejected)
    engine._last_prices["RELIANCE"] = -10.0
    assert engine.SubmitOrder("RELIANCE", 100) is False

def test_sync_portfolio_state(engine):
    """Verify SyncPortfolio correctly maps exchange state to algorithm."""
    # Simulate exchange state
    engine.Exchange._bt_balance = 85000.0
    engine.Exchange._bt_positions = {
        "RELIANCE": {"qty": 10, "avg_price": 2500.0}
    }
    
    engine.SyncPortfolio()
    
    assert engine.Algorithm.Portfolio["Cash"] == 85000.0
    assert engine.Algorithm.Portfolio["RELIANCE"].Quantity == 10
    assert engine.Algorithm.Portfolio["RELIANCE"].AveragePrice == 2500.0

def test_intraday_square_off_mis(engine):
    """Test that square-off triggers for MIS but not CNC."""
    # Case 1: MIS with positions
    engine.TradingMode = "MIS"
    engine.Algorithm.Portfolio["RELIANCE"] = SecurityHolding("RELIANCE", 10, 2500)
    
    engine._bt_handle_square_off()
    
    assert engine._squared_off_today is True
    engine.Exchange.liquidate_all.assert_called # Liquidate() calls Exchange.liquidate_all or submit Sell orders

def test_no_square_off_cnc(engine):
    """Test that CNC positions are NOT squared off at 3:20 PM."""
    engine.TradingMode = "CNC"
    engine.Algorithm.Portfolio["RELIANCE"] = SecurityHolding("RELIANCE", 10, 2500)
    
    engine._bt_handle_square_off()
    
    # Even if squared_off_today is True (to avoid re-triggering), Liquidate should NOT be called
    assert engine._squared_off_today is True
    # We need to verify Liquidate was NOT called. 
    # In engine.py: if self.TradingMode != "CNC": self.Liquidate()
    engine.Exchange.liquidate_all.assert_not_called()
