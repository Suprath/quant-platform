import time
from datetime import datetime, timedelta
import collections

# Fake engine parts just to benchmark ProcessTickFast

from engine import AlgorithmEngine
from quant_sdk import QCAlgorithm
from quant_sdk.data import Slice
from paper_exchange import PaperExchange
from unittest.mock import MagicMock
import logging

logging.getLogger().setLevel(logging.CRITICAL) # silence logs inside engine

# 1. Fake Algo
class FakeAlgo(QCAlgorithm):
    def Initialize(self):
        self.SetCash(100000)
    def OnData(self, data):
        # Heavy strategy just holds some price checking
        if data.ContainsKey("RIL"):
            pass

class MockExchange:
    def __init__(self):
        self._bt_tick_count = 0
        self._bt_balance = 100_000
    def begin_session(self, b):
        self._bt_tick_count = 0
    def flush_session(self):
        pass

engine = AlgorithmEngine()
engine.Algorithm = FakeAlgo()
engine.Algorithm.Portfolio['Cash'] = 100_000
engine.Exchange = MockExchange()
engine.TradingMode = "MIS"
engine.SQUARE_OFF_HOUR = 15
engine.SQUARE_OFF_MINUTE = 20

# Generate 1 MILLION dummy ticks already in dict format!
ticks = []
dt = datetime(2023,1,1, 9, 15)
dt_int = 20230101
for i in range(1_000_000):
   if i % 100_000 == 0: 
       dt += timedelta(days=1)
       dt_int += 1
   m_add = i % 60
   h_add = (i // 60) % 6
   ticks.append({
       'symbol': 'RIL',
       'ltp': 100.0 + (i % 10),
       'v': 100,
       '_dt': dt,
       '_date_int': dt_int,
       '_hour': 9 + h_add,
       '_minute': m_add,
   })

engine.SetBacktestData(ticks)
engine.Speed = "turbo" # or delay=0

print(f"Starting test for {len(ticks)} ticks...")
import time

t0 = time.time()
engine.Run()
t1 = time.time()
elapsed = t1-t0

print(f"Elapsed: {elapsed:.2f}s")
if elapsed > 0:
    print(f"Ticks/sec: {len(ticks) / elapsed:.0f}")

