import logging
from datetime import datetime
from engine_cpp import CppBacktestRunner

# Mock Engine
class MockAlgorithm:
    def __init__(self):
        self.Portfolio = {}
        self.Time = None

class MockEngine:
    def __init__(self):
        self.Algorithm = MockAlgorithm()
        self.Indicators = {}
        self.TradingMode = "MIS"
        self.InitialCash = 100000.0
        self.SquareOffHour = 15
        self.SquareOffMinute = 20
        self.Leverage = 1.0

def test_robustness():
    engine = MockEngine()
    runner = CppBacktestRunner(engine)
    runner.init_engine()
    
    # ── Format 1: Datetime timestamp (Legacy) ──
    ticks_dt = [
        {'symbol': 'NSE_EQ|RELIANCE', 'timestamp': datetime(2024, 1, 1, 10, 0), 'price': 2500.0, 'volume': 100}
    ]
    
    # ── Format 2: Epoch timestamp + _dt (New OHLC optimized) ──
    ticks_epoch = [
        {
            'symbol': 'NSE_EQ|HDFCBANK', 
            'timestamp': 1704103200000, 
            'ltp': 1600.0, 
            'v': 50,
            '_dt': datetime(2024, 1, 1, 10, 0),
            '_date_int': 20240101,
            '_hour': 10,
            '_minute': 0
        }
    ]
    
    print("Testing Datetime Format...")
    runner.add_ticks(ticks_dt)
    print("✅ Datetime Format OK")
    
    print("Testing Epoch + _dt Format...")
    runner.add_ticks(ticks_epoch)
    print("✅ Epoch Format OK")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_robustness()
