import logging
import time
from datetime import datetime
import os

from quant_sdk.data import Tick, FastSlice
from engine import SecurityHolding

logger = logging.getLogger("StrategyRuntimeService")

class CppBacktestRunner:
    def __init__(self, py_engine):
        self.py_engine = py_engine
        self.symbol_id_map = {}
        # Lazy load kira_engine to avoid build-time issues
        import kira_engine as cpp_mod
        self.cpp = cpp_mod.KiraEngine()

    def init_engine(self):
        engine = self.py_engine
        # Configure C++ engine
        is_cnc = (engine.TradingMode == "CNC")
        self.cpp.configure(
            engine.InitialCash,
            engine.SquareOffHour,
            engine.SquareOffMinute,
            engine.TradingMode,
            engine.Leverage
        )

    def add_ticks(self, ticks):
        if not ticks:
            return
        for t in ticks:
            sym = t['symbol']
            if sym not in self.symbol_id_map:
                self.symbol_id_map[sym] = self.cpp.get_or_create_symbol_id(sym)
            
            sid = self.symbol_id_map[sym]
            
            # Robustly fetch datetime
            dt = t.get('_dt')
            if not dt:
                ts = t.get('timestamp')
                if isinstance(ts, (int, float)):
                    dt = datetime.utcfromtimestamp(ts / 1000.0)
                else:
                    dt = ts
            
            date_int = t.get('_date_int')
            if date_int is None:
                date_int = dt.year * 10000 + dt.month * 100 + dt.day
            
            hour = t.get('_hour', dt.hour)
            minute = t.get('_minute', dt.minute)
            
            self.cpp.add_tick(
                sid,
                float(t.get('price', t.get('ltp', 0.0))),
                int(t.get('volume', t.get('v', 0))),
                int(dt.timestamp() * 1000),
                date_int,
                hour,
                minute
            )
        logger.info(f"⏳ C++ Engine buffered {len(ticks):,} ticks. Total in C++ RAM: {self.cpp.tick_count():,}")

    def run(self):
        engine = self.py_engine
        algo = engine.Algorithm
        cpp = self.cpp
        symbol_id_map = self.symbol_id_map
        id_to_symbol = {v: k for k, v in symbol_id_map.items()}

        # ── 3. Register indicators in C++ ──
        indicator_id_counter = 0
        indicator_map = {}
        for sym_str, ind_list in engine.Indicators.items():
            if sym_str not in symbol_id_map: continue
            sym_id = symbol_id_map[sym_str]
            for py_ind in ind_list:
                ind_id = indicator_id_counter
                indicator_id_counter += 1
                class_name = type(py_ind).__name__
                period = getattr(py_ind, 'Period', 14)
                if class_name == 'SimpleMovingAverage':
                    cpp.register_sma(sym_id, period, ind_id)
                elif class_name == 'ExponentialMovingAverage':
                    cpp.register_ema(sym_id, period, ind_id)
                indicator_map[ind_id] = py_ind

        # ── 4. Setup trading hooks ──
        _original_set_holdings = engine.SetHoldings
        def cpp_set_holdings(symbol, percentage):
            if symbol not in symbol_id_map: return False
            sym_id = symbol_id_map[symbol]
            price = cpp.get_last_price(sym_id)
            if price <= 0: return False
            res = cpp.set_holdings(sym_id, percentage, price)
            algo.Portfolio['Cash'] = cpp.get_cash()
            return res

        _original_liquidate = getattr(engine, 'Liquidate', None)
        def cpp_liquidate(symbol=None):
            if symbol is None: cpp.liquidate_all(0)
            elif symbol in symbol_id_map: cpp.liquidate(symbol_id_map[symbol], 0)
            algo.Portfolio['Cash'] = cpp.get_cash()

        engine.SetHoldings = cpp_set_holdings
        engine.Liquidate = cpp_liquidate

        # ── 5. Run loop with aggregation ──
        _tick = Tick(None, '', 0, 0)
        _slice = FastSlice()
        n_total = cpp.tick_count()
        _tick_counter = [0]
        _t_interval = [time.time()]
        _max_tps = [0.0]
        _report_interval = 500_000

        def on_window(ts_list, counts, sym_ids, prices, volumes):
            """Called from C++ for a window of unique timestamps (Slices)."""
            flat_idx = 0
            pool = getattr(on_window, '_tick_pool', None)
            if pool is None:
                pool = {}
                on_window._tick_pool = pool

            for i in range(len(ts_list)):
                ts_ms = ts_list[i]
                n_syms = counts[i]
                dt = datetime.utcfromtimestamp(ts_ms / 1000.0)
                
                algo.Time = dt
                # Only sync cash once per window or if first/last slice (heuristic)
                if i == 0 or i == len(ts_list) - 1:
                    algo.Portfolio['Cash'] = cpp.get_cash()
                    algo.Portfolio['TotalPortfolioValue'] = cpp.get_portfolio_value()

                # 1. Setup Lazy Indicators (Once per run)
                if not hasattr(on_window, '_lazy_ready'):
                    for ind_id, py_ind in indicator_map.items():
                        # Use closures for lazy C++ calls
                        type(py_ind).Value = property(lambda self, iid=ind_id: cpp.get_indicator_value(iid))
                        type(py_ind).IsReady = property(lambda self, iid=ind_id: cpp.is_indicator_ready(iid))
                    on_window._lazy_ready = True

                slice_data = {}
                for j in range(n_syms):
                    sid, price, vol = sym_ids[flat_idx], prices[flat_idx], volumes[flat_idx]
                    flat_idx += 1
                    
                    sym = id_to_symbol.get(sid, '')
                    if sym not in pool:
                        pool[sym] = Tick(dt, sym, price, vol)
                    
                    t = pool[sym]
                    t.Time, t.Price, t.Volume, t.Value = dt, price, vol, price
                    slice_data[sym] = t
                    
                    # Update holdings In-place
                    holding = algo.Portfolio.get(sym)
                    if holding is not None:
                        holding.Quantity = cpp.get_position_qty(sid)
                        holding.AveragePrice = cpp.get_position_avg_price(sid)
                    else:
                        algo.Portfolio[sym] = SecurityHolding(sym, 
                            cpp.get_position_qty(sid), 
                            cpp.get_position_avg_price(sid))

                engine.ProcessSliceFast(dt, slice_data)

            # Speed reporting (Once per window)
            _tick_counter[0] += len(sym_ids)
            if _tick_counter[0] // _report_interval > ( (_tick_counter[0] - len(sym_ids)) // _report_interval):
                now = time.time()
                elapsed = now - _t_interval[0]
                if elapsed > 0:
                    tps = _report_interval / elapsed
                    _max_tps[0] = max(_max_tps[0], tps)
                    logger.info(f"⚡ SPEED: {tps:,.0f} ticks/sec | Progress: {(_tick_counter[0]/n_total)*100:.1f}%")
                _t_interval[0] = now

        logger.info("🚀 Starting C++ engine with Windowed Aggregation (Window=5000)...")
        t_start = time.time()
        cpp.run(on_window, 5000)
        
        # ── 6. Cleanup ──
        engine.SetHoldings = _original_set_holdings
        engine.Liquidate = _original_liquidate
        
        # Sync final state
        engine.Exchange._bt_balance = cpp.get_cash()
        for sym_str, sid in symbol_id_map.items():
            qty, avg = cpp.get_position_qty(sid), cpp.get_position_avg_price(sid)
            if qty != 0: engine.Exchange._bt_positions[sym_str] = {'qty': qty, 'avg_price': avg}
            else: engine.Exchange._bt_positions.pop(sym_str, None)

        # Sync equity curve
        for ts_ms, val in cpp.get_equity_curve():
            engine.EquityCurve.append({'timestamp': datetime.utcfromtimestamp(ts_ms/1000.0), 'equity': val})

        dur = time.time() - t_start
        logger.info(f"✅ C++ engine finished in {dur:.2f}s (Avg {n_total/dur:,.0f} TPS)")

