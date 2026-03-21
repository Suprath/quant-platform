"""
engine_cpp.py — Python integration layer for the KIRA C++ backtesting engine.

This module wraps the C++ KiraEngine (built via PyBind11) and bridges it
with the existing Python strategy framework. User strategies remain in
pure Python; only the hot tick loop runs in C++.

Usage (called from engine.py when KIRA_CPP_ENGINE=true):
    from engine_cpp import CppBacktestRunner
    runner = CppBacktestRunner(engine)
    runner.run()
"""

import os
import time
import logging
from datetime import datetime

logger = logging.getLogger("CppEngine")


class CppBacktestRunner:
    """
    Bridges the C++ KiraEngine with the Python AlgorithmEngine.

    Responsibilities:
    1. Convert Python tick dicts → C++ tick format (symbol strings → int IDs)
    2. Set up C++ indicators mirroring the Python indicator registry
    3. Create a Python callback that builds a Slice and calls OnData
    4. After C++ run completes, read buffered orders and flush to DB
    5. Sync equity curve and portfolio state back to Python engine
    """

    def __init__(self, py_engine):
        """
        Args:
            py_engine: The existing AlgorithmEngine instance from engine.py
        """
        self.py_engine = py_engine

    def init_engine(self):
        try:
            import kira_engine as ke
        except ImportError:
            logger.error(
                "❌ kira_engine C++ module not found. "
                "Falling back to Python engine. "
                "Build it with: cd cpp && mkdir build && cd build && cmake .. && make"
            )
            raise

        engine = self.py_engine
        algo = engine.Algorithm

        # ── 1. Create and configure C++ engine ──
        self.cpp = ke.KiraEngine()
        trading_mode = engine.TradingMode
        initial_cash = algo.Portfolio.get('Cash', 100000.0)
        self.cpp.configure(
            initial_cash=initial_cash,
            sq_hour=engine.SQUARE_OFF_HOUR,
            sq_minute=engine.SQUARE_OFF_MINUTE,
            is_cnc=trading_mode,
            leverage=engine.Leverage,
        )
        self.symbol_id_map = {}

    def add_ticks(self, ticks):
        """Append to C++ engine without holding list in python memory."""
        if not hasattr(self, 'cpp'):
            self.init_engine()
            
        # Build symbol map
        for t in ticks:
            sym = t['symbol']
            if sym not in self.symbol_id_map:
                self.symbol_id_map[sym] = self.cpp.get_or_create_symbol_id(sym)

        # Bulk-load ticks
        # C++ std::vector grows dynamically
        for t in ticks:
            self.cpp.add_tick(
                self.symbol_id_map[t['symbol']],
                t['ltp'],
                t['v'],
                t['timestamp'],
                t['_date_int'],
                t['_hour'],
                t['_minute'],
            )
        logger.info(f"⏳ C++ Engine buffered {len(ticks):,} ticks. Total in C++ RAM: {self.cpp.tick_count():,} | Symbols Tracked: {len(self.symbol_id_map)}")

    def run(self):
        engine = self.py_engine
        algo = engine.Algorithm
        if not hasattr(self, 'cpp'):
            self.init_engine()
            
        cpp = self.cpp
        symbol_id_map = self.symbol_id_map

        # ── 3. Register indicators in C++ ──
        indicator_id_counter = 0
        indicator_map = {}  # C++ indicator_id → Python indicator object

        for sym_str, ind_list in engine.Indicators.items():
            if sym_str not in symbol_id_map:
                continue
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
                else:
                    logger.warning(f"⚠️ Indicator {class_name} not yet in C++, "
                                   "will update via Python fallback")

                indicator_map[ind_id] = py_ind

        # ── 4. Build the callback that calls user strategy ──
        # This is called from C++ for each tick (GIL acquired by PyBind11)

        from quant_sdk.data import Tick, FastSlice
        from engine import SecurityHolding

        # Pre-allocate reusable objects (same optimisation as ProcessTickFast)
        _tick = Tick(None, '', 0, 0)
        # ── 3. Map Symbol IDs and populate initial Portfolio ──
        symbol_id_map = self.symbol_id_map # string symbol -> int id
        id_to_symbol = {v: k for k, v in symbol_id_map.items()}
        
        # Ensure algo.Portfolio has entries for all subscribed symbols to avoid KeyErrors
        for sym in symbol_id_map.keys():
            if sym not in algo.Portfolio:
                algo.Portfolio[sym] = SecurityHolding(sym, 0, 0.0)

        _slice = FastSlice() # This line was moved here from above

        def on_tick(symbol_id, price, volume, timestamp_ms):
            """Called from C++ per tick. Builds a Slice and invokes OnData."""
            sym = id_to_symbol.get(symbol_id, '')

            # Update reusable tick
            _tick.Price = price
            _tick.Value = price
            _tick.Volume = volume
            _tick.Symbol = sym
            # Minimal time object — avoid datetime.fromtimestamp per tick
            _tick.Time = None  # Strategy should use self.Time from algo

            # Update reusable FastSlice
            _slice._data_symbol = sym
            _slice._data_tick = _tick

            # Sync C++ state → Python Portfolio (lightweight reads)
            algo.Portfolio['Cash'] = cpp.get_cash()
            algo.Portfolio['TotalPortfolioValue'] = cpp.get_portfolio_value()

            # Date rollover logic for Noise Update!
            from datetime import datetime as _dt
            dt = _dt.utcfromtimestamp(timestamp_ms / 1000.0)
            current_date_int = dt.year * 10000 + dt.month * 100 + dt.day
            if not hasattr(engine, '_cpp_last_date_int') or engine._cpp_last_date_int != current_date_int:
                engine._cpp_last_date_int = current_date_int
                if hasattr(engine, 'AllNoiseData'):
                    engine.SetNoiseData(engine.AllNoiseData.get(current_date_int, {}))

            # Sync indicator values from C++ → Python objects
            for ind_id, py_ind in indicator_map.items():
                py_ind.Value = cpp.get_indicator_value(ind_id)
                py_ind.IsReady = cpp.is_indicator_ready(ind_id)

            # Update portfolio holdings for the current symbol
            qty = cpp.get_position_qty(symbol_id)
            avg = cpp.get_position_avg_price(symbol_id)
            if qty != 0:
                algo.Portfolio[sym] = SecurityHolding(sym, qty, avg)
            elif sym in algo.Portfolio and isinstance(algo.Portfolio.get(sym), SecurityHolding):
                algo.Portfolio[sym] = SecurityHolding(sym, 0, 0.0)

            # Set time on the algorithm
            algo.Time = datetime.utcfromtimestamp(timestamp_ms / 1000.0)
            _slice.Time = algo.Time
            engine.CurrentSlice = _slice

            # Call user strategy
            algo.OnData(_slice)

        # ── 5. Intercept SetHoldings calls from user strategy ──
        # Monkey-patch engine.SetHoldings to forward to C++
        _original_set_holdings = engine.SetHoldings

        def cpp_set_holdings(symbol, percentage):
            if symbol not in symbol_id_map:
                logger.warning(f"⚠️ SetHoldings: {symbol} not in universe")
                return False
            sym_id = symbol_id_map[symbol]
            current_price = cpp.get_last_price(sym_id)
            if current_price <= 0:
                return False
            result = cpp.set_holdings(sym_id, percentage, current_price)
            # Sync balance back
            algo.Portfolio['Cash'] = cpp.get_cash()
            return result

        _original_liquidate = getattr(engine, 'Liquidate', None)
        _original_submit_order = getattr(engine, 'SubmitOrder', None)

        def cpp_liquidate(symbol=None):
            if symbol is None:
                cpp.liquidate_all(0)
            elif symbol in symbol_id_map:
                cpp.liquidate(symbol_id_map[symbol], 0)
            algo.Portfolio['Cash'] = cpp.get_cash()

        def cpp_submit_order(symbol, quantity, order_type="MARKET"):
            if symbol not in symbol_id_map:
                logger.warning(f"⚠️ SubmitOrder: {symbol} not in universe")
                return False
            sym_id = symbol_id_map[symbol]
            price = cpp.get_last_price(sym_id)
            if price <= 0:
                return False
            
            # Execute in C++
            success = cpp.execute_order(sym_id, "BUY" if quantity > 0 else "SELL", abs(int(quantity)), price, 0)
            # Sync balance back
            algo.Portfolio['Cash'] = cpp.get_cash()
            return success

        engine.SetHoldings = cpp_set_holdings
        engine.Liquidate = cpp_liquidate
        engine.SubmitOrder = cpp_submit_order

        # ── 6. Run the C++ engine ──
        logger.info("🚀 Starting C++ engine tick loop...")
        t0 = time.time()
        n_total = cpp.tick_count()

        # Speed tracking state (captured in closure)
        _tick_counter = [0]
        _t_interval = [t0]
        _max_tps = [0.0]
        _speed_samples = []
        _report_interval = 500_000

        # Wrap on_tick with speed tracking
        _original_on_tick = on_tick

        def on_tick_with_speed(symbol_id, price, volume, timestamp_ms):
            _original_on_tick(symbol_id, price, volume, timestamp_ms)
            _tick_counter[0] += 1
            if _tick_counter[0] % _report_interval == 0:
                _now = time.time()
                _elapsed = _now - _t_interval[0]
                if _elapsed > 0:
                    _tps = _report_interval / _elapsed
                    _max_tps[0] = max(_max_tps[0], _tps)
                    _speed_samples.append(_tps)
                    _progress = (_tick_counter[0] / n_total) * 100
                    logger.info(f"⚡ SPEED: {_tps:,.0f} ticks/sec | "
                                f"Progress: {_progress:.1f}% ({_tick_counter[0]:,}/{n_total:,})")
                _t_interval[0] = _now

        cpp.run(on_tick_with_speed)

        elapsed = time.time() - t0
        n_ticks = cpp.tick_count()
        avg_tps = n_ticks / elapsed if elapsed > 0 else 0
        max_tps = max(_max_tps[0], avg_tps)
        logger.info(f"⚡ SPEED_FINAL: avg={avg_tps:,.0f} max={max_tps:,.0f} ticks/sec | "
                     f"Total: {n_ticks:,} ticks in {elapsed:.2f}s")

        # ── 7. Restore original methods ──
        engine.SetHoldings = _original_set_holdings
        if _original_liquidate:
            engine.Liquidate = _original_liquidate
        if _original_submit_order:
            engine.SubmitOrder = _original_submit_order

        # ── 8. Flush buffered orders to DB via existing exchange ──
        orders = cpp.get_orders()
        if orders and hasattr(engine.Exchange, '_bt_order_buf'):
            for o in orders:
                pnl = o.pnl if o.has_pnl else None
                trade_time = datetime.utcfromtimestamp(o.timestamp_ms / 1000.0) if o.timestamp_ms > 0 else datetime.utcnow()
                engine.Exchange._bt_order_buf.append(
                    (engine.RunID, o.symbol, o.side, o.quantity, o.price, pnl, trade_time)
                )
            engine.Exchange._bt_trade_count += cpp.get_trade_count()

        # ── 9. Sync final portfolio state ──
        engine.Exchange._bt_balance = cpp.get_cash()
        # Sync positions
        for sym_str, sym_id in symbol_id_map.items():
            qty = cpp.get_position_qty(sym_id)
            avg = cpp.get_position_avg_price(sym_id)
            if qty != 0:
                engine.Exchange._bt_positions[sym_str] = {'qty': qty, 'avg_price': avg}
            else:
                engine.Exchange._bt_positions.pop(sym_str, None)

        # ── 10. Sync equity curve ──
        eq_curve = cpp.get_equity_curve()
        for ts_ms, equity in eq_curve:
            ts = datetime.utcfromtimestamp(ts_ms / 1000.0) if ts_ms > 0 else datetime.now()
            engine.EquityCurve.append({'timestamp': ts, 'equity': equity})

        logger.info(f"✅ C++ engine completed — {cpp.get_trade_count()} trades, "
                     f"Final cash: ₹{cpp.get_cash():,.2f}")
