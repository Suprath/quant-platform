import pytest
import os
from datetime import datetime
from unittest.mock import MagicMock, patch
from engine import AlgorithmEngine
from quant_sdk.data import Slice, Tick

@pytest.fixture
def engine():
    # Setup engine in backtest mode without real Kafka/QuestDB
    engine = AlgorithmEngine(run_id="integ_test", backtest_mode=True, trading_mode="MIS")
    
    # Mock Algorithm
    from strategies.kira_integrated_strategy import KiraIntegratedStrategy
    engine.LoadAlgorithm("strategies.kira_integrated_strategy", "KiraIntegratedStrategy")
    engine.Algorithm.Initialize() # Required to setup last_prices etc.
    
    # Mock Exchange to capture orders
    engine.Exchange = MagicMock()
    engine.Exchange._bt_balance = 100000.0
    engine.Exchange._bt_positions = {}
    engine.Exchange.execute_order.return_value = True
    
    return engine

def test_full_entry_pipeline(engine):
    """
    Test the full pipeline:
    1. Coarse Selection (Scanner)
    2. Data Slice (Tick)
    3. Noise Filter (Confidence)
    4. Position Sizer (Sizing)
    5. Order Execution
    """
    algo = engine.Algorithm
    
    # 1. Simulate Scanner Picks
    scored_list = [
        {'symbol': 'NSE_EQ|RELIANCE', 'score': 2.0},
        {'symbol': 'NSE_EQ|TCS', 'score': 1.8},
        {'symbol': 'NSE_EQ|INFY', 'score': 1.6}
    ]
    engine.ActiveUniverse = algo.CoarseSelectionFunction(scored_list)
    assert "NSE_EQ|RELIANCE" in algo.ActiveUniverse

    # 2. Setup Mocks for SDK calls
    # Mock confidence = 80, Sizer = 100 shares
    with patch.object(algo, 'GetKiraConfidence', return_value=80.0):
        with patch.object(algo, 'GetKiraPositionSize', return_value={"shares": 100, "exit_plan": {}}):
            
            # 3. Simulate Ticks (Momentum Trigger)
            # Price moves from 2500 to 2510 (0.4% move > 0.35% trigger)
            algo.last_prices["NSE_EQ|RELIANCE"] = 2500.0
            # 3. Create simulated slice (Reliance + NIFTY Benchmark)
            nifty_tick = Tick(datetime.now(), "NSE_EQ|NIFTY_50", 22000.0, 1000000)
            tick = Tick(datetime.now(), "NSE_EQ|RELIANCE", 2510.0, 1000000) # Volume spike included
            data_slice = Slice(datetime.now(), {
                "NSE_EQ|RELIANCE": tick,
                "NSE_EQ|NIFTY_50": nifty_tick
            })
            
            # 4. Process through engine (which calls OnData)
            engine.CurrentSlice = data_slice
            algo.OnData(data_slice)
            
            # 5. Verify order was submitted to exchange
            engine.Exchange.execute_order.assert_called_once()
            args, _ = engine.Exchange.execute_order.call_args
            order_signal = args[0]
            
            assert order_signal["symbol"] == "NSE_EQ|RELIANCE"
            assert order_signal["quantity"] == 100
            assert order_signal["action"] == "BUY"
            assert order_signal["price"] == 2510.0

def test_no_entry_on_low_confidence(engine):
    """Ensure no entry if KIRA Confidence is below threshold."""
    algo = engine.Algorithm
    engine.ActiveUniverse = ["NSE_EQ|RELIANCE"]
    
    # Mock confidence = 30 (below threshold 75)
    with patch.object(algo, 'GetKiraConfidence', return_value=30.0):
        algo.last_prices["NSE_EQ|RELIANCE"] = 2500.0
        nifty_tick = Tick(datetime.now(), "NSE_EQ|NIFTY_50", 22000.0, 1000)
        tick = Tick(datetime.now(), "NSE_EQ|RELIANCE", 2510.0, 1000)
        data_slice = Slice(datetime.now(), {
            "NSE_EQ|RELIANCE": tick,
            "NSE_EQ|NIFTY_50": nifty_tick
        })
        
        engine.CurrentSlice = data_slice
        algo.OnData(data_slice)
        
        # Verify NO order was submitted
        engine.Exchange.execute_order.assert_not_called()
