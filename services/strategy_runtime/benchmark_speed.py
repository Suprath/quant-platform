import sys
import time
from datetime import datetime
import uuid
import logging

# Add paths
sys.path.append("/app")
from engine import AlgorithmEngine
from engine_cpp import CppBacktestRunner

# Disable logging for clear output
logging.getLogger().setLevel(logging.ERROR)

def benchmark():
    run_id = str(uuid.uuid4())
    print(f"🚀 Starting Speed Benchmark (Slice Aggregation + O(1) Indicators)")
    
    # 1. Setup Engine
    engine = AlgorithmEngine(run_id=run_id, backtest_mode=True)
    class MockAlgo:
        def __init__(self):
            self.Portfolio = {'Cash': 100000.0, 'TotalPortfolioValue': 100000.0}
            self.Time = datetime.now()
        def OnData(self, slice):
            # Simulate some strategy logic (accessing slice)
            for sym, tick in slice.items():
                p = tick.Price
    
    engine.Algorithm = MockAlgo()
    runner = CppBacktestRunner(engine)
    
    # 2. Add 1,000,000 ticks (10 symbols, 100,000 timestamps)
    print("⏳ Buffering 1,000,000 ticks...")
    symbols = [f"SYM_{i}" for i in range(3)]
    ticks = []
    base_time = datetime(2024, 1, 1, 10, 0, 0)
    from datetime import timedelta
    for i in range(100000):
        ts = base_time + timedelta(seconds=i) 
        for sym in symbols:
            ticks.append({'symbol': sym, 'price': 100.0 + i*0.01, 'timestamp': ts})
            
    runner.add_ticks(ticks)
    
    # 3. Run Benchmark
    print("🔥 Running Engine...")
    t0 = time.time()
    runner.run()
    elapsed = time.time() - t0
    
    tps = 1000000 / elapsed
    print(f"🏁 Benchmark Finished!")
    print(f"⏱️ Elapsed: {elapsed:.3f}s")
    print(f"🚀 SPEED: {tps:,.0f} ticks/sec")
    
    if tps > 1000000:
        print("✅ SUCCESS: Speed is over 1M TPS!")
    else:
        print("❌ FAILURE: Speed is still below 1M TPS.")

if __name__ == "__main__":
    benchmark()
