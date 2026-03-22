import numpy as np
import til_core
import time
from datetime import datetime

def run_benchmark():
    # 1. Create 1 Million mock ticks
    # [Timestamp, SymbolID, Close, ADX, ATR, OBV, Momentum, Hurst]
    n_ticks = 10_000_000
    print(f"🚀 Generating {n_ticks:,} mock ticks...")
    
    data = np.zeros((n_ticks, 8), dtype=np.float64)
    data[:, 0] = np.arange(n_ticks) # Timestamps
    data[:, 1] = 0 # Symbol ID 0
    data[:, 2] = 2500.0 + np.cumsum(np.random.normal(0, 1, n_ticks)) # Random Walk Price
    
    # Mock Features
    data[:, 3] = 20.0 # ADX
    data[:, 4] = -0.0001 # ATR Slope
    data[:, 5] = 0.01 # OBV Slope
    data[:, 6] = 0.0 # Momentum
    data[:, 7] = 0.52 # Hurst

    id_to_sym = {0: "BENCHMARK_TICK"}

    # 2. Initialize Engine
    engine = til_core.SimulationEngine(1000000.0)
    
    # 3. Time the simulation
    print("🎬 Starting C++ Vectorized Simulation...")
    start_time = time.time()
    
    result = engine.run_vectorized_simulation(data, id_to_sym)
    
    end_time = time.time()
    duration = end_time - start_time
    
    ticks_per_sec = n_ticks / duration
    
    print("\n✅ Benchmark Complete!")
    print(f"⏱️ Duration: {duration:.4f} seconds")
    print(f"📊 Throughput: {ticks_per_sec:,.0f} ticks/sec")
    print(f"💰 Final Equity: {result.final_equity:,.2f}")
    print(f"📝 Total Trades: {len(result.trades)}")

if __name__ == "__main__":
    run_benchmark()
