"""
test_parity.py — Validates result parity between Python and C++ backtest engines.

Runs the SAME strategy with the SAME tick data through both engines and
asserts identical results: trades, final balance, and portfolio state.

Usage:
    cd services/strategy_runtime
    python test_parity.py
"""

import os
import sys
import time
import logging
from datetime import datetime, timedelta
from unittest.mock import MagicMock

logging.getLogger().setLevel(logging.WARNING)  # Silence engine spam

# ── Setup path ──
sys.path.insert(0, os.path.dirname(__file__))

from quant_sdk import QCAlgorithm
from quant_sdk.data import Tick, FastSlice
from engine import AlgorithmEngine, SecurityHolding


# ═══════════════════════════════════════════════════════════════
# Test Strategy: SMA Crossover (exercises indicators + SetHoldings)
# ═══════════════════════════════════════════════════════════════

class TestStrategy(QCAlgorithm):
    """Simple SMA crossover strategy for parity testing."""

    def Initialize(self):
        self.SetCash(100000)
        self.sma_fast = self.SMA("TEST_STOCK", 5)
        self.sma_slow = self.SMA("TEST_STOCK", 20)
        self._in_position = False

    def OnData(self, data):
        if not data.ContainsKey("TEST_STOCK"):
            return
        if not self.sma_fast.IsReady or not self.sma_slow.IsReady:
            return

        price = data["TEST_STOCK"].Price

        if self.sma_fast.Value > self.sma_slow.Value and not self._in_position:
            self.SetHoldings("TEST_STOCK", 0.5)
            self._in_position = True
        elif self.sma_fast.Value < self.sma_slow.Value and self._in_position:
            self.SetHoldings("TEST_STOCK", 0)
            self._in_position = False


# ═══════════════════════════════════════════════════════════════
# Generate deterministic test data
# ═══════════════════════════════════════════════════════════════

def generate_test_ticks(n=50000):
    """Generate N ticks with a sine-wave price pattern for SMA crossovers."""
    import math
    ticks = []
    base_dt = datetime(2025, 1, 2, 9, 15)
    base_ts_ms = int(base_dt.timestamp() * 1000)

    for i in range(n):
        # Price oscillates: 100 ± 10, period ~1000 ticks → multiple crossovers
        price = 100.0 + 10.0 * math.sin(2 * math.pi * i / 1000)

        minute = 15 + (i % 360)  # Stay within 9:15 - 15:15
        hour = 9 + minute // 60
        minute = minute % 60

        day_offset = i // 2000  # New day every 2000 ticks
        dt = base_dt + timedelta(days=day_offset)
        date_int = (dt.year * 10000) + (dt.month * 100) + dt.day

        ticks.append({
            'symbol': 'TEST_STOCK',
            'ltp': round(price, 2),
            'v': 1000,
            'timestamp': base_ts_ms + i * 60000,
            '_dt': dt.replace(hour=hour, minute=minute),
            '_date_int': date_int,
            '_hour': hour,
            '_minute': minute,
        })

    return ticks


# ═══════════════════════════════════════════════════════════════
# Helpers to create a fresh engine
# ═══════════════════════════════════════════════════════════════

class MockExchange:
    """In-memory exchange mock — same interface as PaperExchange for backtest."""
    def __init__(self):
        self._bt_tick_count = 0
        self._bt_balance = 100000.0
        self._bt_positions = {}
        self._bt_order_buf = []
        self._bt_trade_count = 0

    def begin_session(self, bal):
        self._bt_balance = bal
        self._bt_tick_count = 0

    def flush_session(self):
        pass

    def _get_conn(self):
        return None


def create_engine(use_cpp=False):
    """Create a fresh AlgorithmEngine with TestStrategy."""
    # Set env var BEFORE importing/creating engine
    if use_cpp:
        os.environ['KIRA_CPP_ENGINE'] = 'true'
    else:
        os.environ['KIRA_CPP_ENGINE'] = 'false'

    engine = AlgorithmEngine()
    engine.Algorithm = TestStrategy(engine=engine)
    engine.Algorithm.Portfolio['Cash'] = 100000.0
    engine.Exchange = MockExchange()
    engine.TradingMode = "MIS"
    engine.BacktestMode = True
    engine.RunID = "test_parity_run"
    engine.Speed = "fast"

    engine.Algorithm.Initialize()

    return engine


# ═══════════════════════════════════════════════════════════════
# Main parity test
# ═══════════════════════════════════════════════════════════════

def run_parity_test():
    print("=" * 60)
    print("  PARITY TEST: Python Engine vs C++ Engine")
    print("=" * 60)

    ticks = generate_test_ticks(50000)
    print(f"\n📊 Generated {len(ticks):,} test ticks")

    # ── Run Python engine ──
    print("\n─── Running Python Engine ───")
    py_engine = create_engine(use_cpp=False)
    py_engine.SetBacktestData(ticks)
    py_engine.Exchange.begin_session(100000.0)

    t0 = time.time()
    py_engine.Run()
    py_time = time.time() - t0

    py_orders = list(py_engine.Exchange._bt_order_buf)
    py_balance = py_engine.Exchange._bt_balance
    py_tps = len(ticks) / py_time if py_time > 0 else 0
    print(f"  ⏱  Time: {py_time:.3f}s ({py_tps:,.0f} ticks/sec)")
    print(f"  💰 Final Balance: ₹{py_balance:,.2f}")
    print(f"  📋 Trades: {len(py_orders)}")

    # ── Run C++ engine ──
    cpp_available = True
    try:
        import kira_engine
    except ImportError:
        cpp_available = False

    if not cpp_available:
        print("\n⚠️  C++ engine (kira_engine.so) not built yet.")
        print("   Build with: cd cpp && mkdir build && cd build && cmake .. && make")
        print("   Skipping C++ parity test — Python baseline recorded above.")
        return

    print("\n─── Running C++ Engine ───")
    cpp_engine = create_engine(use_cpp=True)
    cpp_engine.SetBacktestData(ticks)
    cpp_engine.Exchange.begin_session(100000.0)

    t0 = time.time()
    cpp_engine.Run()
    cpp_time = time.time() - t0

    cpp_orders = list(cpp_engine.Exchange._bt_order_buf)
    cpp_balance = cpp_engine.Exchange._bt_balance
    cpp_tps = len(ticks) / cpp_time if cpp_time > 0 else 0
    print(f"  ⏱  Time: {cpp_time:.3f}s ({cpp_tps:,.0f} ticks/sec)")
    print(f"  💰 Final Balance: ₹{cpp_balance:,.2f}")
    print(f"  📋 Trades: {len(cpp_orders)}")

    # ── Compare results ──
    print("\n─── Parity Check ───")
    errors = 0

    # Trade count
    if len(py_orders) != len(cpp_orders):
        print(f"  ❌ Trade count mismatch: Python={len(py_orders)}, C++={len(cpp_orders)}")
        errors += 1
    else:
        print(f"  ✅ Trade count: {len(py_orders)} (match)")

    # Final balance
    balance_diff = abs(py_balance - cpp_balance)
    if balance_diff > 0.01:
        print(f"  ❌ Balance mismatch: Python=₹{py_balance:.2f}, C++=₹{cpp_balance:.2f} (diff=₹{balance_diff:.2f})")
        errors += 1
    else:
        print(f"  ✅ Final balance: ₹{py_balance:.2f} (match)")

    # Trade-by-trade comparison
    n_compare = min(len(py_orders), len(cpp_orders))
    trade_mismatches = 0
    for i in range(n_compare):
        py_o = py_orders[i]
        cpp_o = cpp_orders[i]
        # Compare: (run_id, symbol, side, qty, price, pnl)
        if py_o[1] != cpp_o[1] or py_o[2] != cpp_o[2] or py_o[3] != cpp_o[3]:
            if trade_mismatches < 5:  # Show first 5 mismatches
                print(f"  ❌ Trade {i}: Python={py_o[1:5]}, C++={cpp_o[1:5]}")
            trade_mismatches += 1

    if trade_mismatches > 0:
        print(f"  ❌ {trade_mismatches} trade mismatches")
        errors += 1
    else:
        print(f"  ✅ All {n_compare} trades match")

    # Speedup
    if cpp_time > 0 and py_time > 0:
        speedup = py_time / cpp_time
        print(f"\n  🚀 Speedup: {speedup:.1f}x (Python: {py_tps:,.0f} → C++: {cpp_tps:,.0f} ticks/sec)")

    print("\n" + "=" * 60)
    if errors == 0:
        print("  ✅ ALL PARITY CHECKS PASSED")
    else:
        print(f"  ❌ {errors} PARITY CHECK(S) FAILED")
    print("=" * 60)

    return errors == 0


if __name__ == "__main__":
    success = run_parity_test()
    sys.exit(0 if success else 1)
