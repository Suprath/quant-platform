import numpy as np
import til_core
import time
from datetime import datetime

def python_simulation(data, initial_capital):
    cash = initial_capital
    positions = {}
    trades = []
    
    for i in range(len(data)):
        ts, sym_id, price, adx, atr_slope, obv_slope, momentum, hurst = data[i]
        sym_id = int(sym_id)
        
        if sym_id in positions:
            pos = positions[sym_id]
            exit_flag = False
            reason = ""
            if pos['direction'] == "LONG":
                if price <= pos['sl_price']: exit_flag, reason = True, "SL"
                elif price >= pos['tp_price']: exit_flag, reason = True, "TP"
            
            if exit_flag:
                pnl = pos['qty'] * (price - pos['entry_price'])
                cash += (pos['qty'] * price)
                trades.append({'pnl': pnl})
                del positions[sym_id]
        else:
            # Score logic
            adx_score = max(0.0, 1.0 - (adx / 25.0))
            atr_score = min(1.0, max(0.0, -atr_slope / 0.002))
            obv_score = min(1.0, obv_slope / 0.005)
            flat_score = max(0.0, 1.0 - abs(momentum) / 0.015)
            hurst_score = min(1.0, max(0.0, (hurst - 0.45) / 0.15))
            score = (adx_score * 0.20 + atr_score * 0.25 + obv_score * 0.25 + flat_score * 0.20 + hurst_score * 0.10)
            
            if score >= 0.45 and cash >= (100 * price):
                qty = 100
                cash -= (qty * price)
                positions[sym_id] = {
                    'entry_price': price,
                    'qty': qty,
                    'direction': "LONG",
                    'sl_price': price * 0.98,
                    'tp_price': price * 1.04
                }
    
    final_equity = cash
    for sym_id, pos in positions.items():
        final_equity += pos['qty'] * pos['entry_price']
    return final_equity, len(trades)

def run_strict_validation():
    n_ticks = 100_000
    n_symbols = 50
    print(f"🔬 Validating Accuracy with {n_ticks:,} ticks across {n_symbols} symbols...")
    
    data = np.zeros((n_ticks, 8), dtype=np.float64)
    data[:, 0] = np.arange(n_ticks)
    data[:, 1] = np.random.randint(0, n_symbols, n_ticks) # Multiple symbols
    data[:, 2] = 2500.0 + np.cumsum(np.random.normal(0, 1, n_ticks))
    data[:, 3:8] = [20.0, -0.0001, 0.01, 0.0, 0.52]

    # 1. Python Baseline
    t0 = time.time()
    py_equity, py_trades = python_simulation(data, 1000000.0)
    py_dur = time.time() - t0
    
    # 2. C++ Engine
    engine = til_core.SimulationEngine(1000000.0)
    cpp_res = engine.run_vectorized_simulation(data, {})
    
    print(f"🐍 Python: Equity={py_equity:,.2f}, Trades={py_trades}, Time={py_dur:.4f}s")
    print(f"🚀 C++:    Equity={cpp_res.final_equity:,.2f}, Trades={len(cpp_res.trades)}, Time={cpp_res.execution_time_ms/1000:.4f}s")
    
    if abs(py_equity - cpp_res.final_equity) < 0.01:
        print("✅ ACCURACY MATCHES!")
    else:
        print("❌ ACCURACY MISMATCH!")

    # 3. High-Load Speed Test
    n_speed = 10_000_000
    print(f"\n🚀 Starting High-Load Stress Test ({n_speed:,} ticks)...")
    data_large = np.zeros((n_speed, 8), dtype=np.float64)
    data_large[:, 1] = np.random.randint(0, 500, n_speed) # 500 interleaved symbols
    data_large[:, 2] = 2500.0 + np.cumsum(np.random.normal(0, 1, n_speed))
    data_large[:, 3:8] = [20.0, -0.0001, 0.01, 0.0, 0.52]
    
    engine_large = til_core.SimulationEngine(1000000.0)
    res_large = engine_large.run_vectorized_simulation(data_large, {})
    
    speed_dur = res_large.execution_time_ms / 1000
    tp = n_speed / speed_dur
    print(f"📊 Final Stress Throughput: {tp:,.0f} ticks/sec")

if __name__ == "__main__":
    run_strict_validation()
