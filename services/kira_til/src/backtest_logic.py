import os
import asyncio
import logging
import pandas as pd
import psycopg2
from psycopg2 import pool
import json
import aiohttp
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from kira_shared.models.market import FeatureVector, MarketContext
from .registry import (
    scanner, mechanism_classifier, noise_filter, 
    position_sizer, portfolio_engine
)

import sys
import traceback

logger = logging.getLogger("TILBacktest")
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format='%(asctime)s %(name)s %(levelname)s %(message)s')

# Global HTTP Session for connection pooling
_http_session: Optional[aiohttp.ClientSession] = None

async def get_http_session() -> aiohttp.ClientSession:
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession()
    return _http_session

# Global QDB Pool
_qdb_pool: Optional[pool.ThreadedConnectionPool] = None

def get_qdb_pool():
    global _qdb_pool
    if _qdb_pool is None:
        host = os.getenv("QUESTDB_HOST", "questdb_tsdb")
        _qdb_pool = pool.ThreadedConnectionPool(
            1, 20, # min, max connections
            host=host,
            port=8812,
            user="admin",
            password="quest",
            database="qdb"
        )
    return _qdb_pool

class BacktestController:
    """
    Orchestrates historical TIL simulations using QuestDB data.
    """
    def __init__(self):
        self.qdb_host = os.getenv("QUESTDB_HOST", "questdb_tsdb")
        self.qdb_port = 8812
        self.is_running = False
        self.is_backfilling = False
        self.backfill_progress = 0
        self.progress = 0
        self.total_steps = 0
        self.current_step = 0
        self.current_simulation_run_id = None
        
    def _qdb_exec(self, query: str, params=None):
        """
        Execute a QuestDB query using a short-lived connection from the pool.
        Acquires a connection, executes the query, and immediately returns the
        connection to the pool. This prevents stale connections during long
        simulation runs.
        """
        qdb_pool = get_qdb_pool()
        conn = qdb_pool.getconn()
        try:
            # Ensure connection is alive before using it
            if conn.closed:
                qdb_pool.putconn(conn, close=True)
                conn = qdb_pool.getconn()
            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()
            cur.close()
            return rows
        except Exception as e:
            logger.error(f"QDB query error: {e}")
            # Return broken connection to be discarded
            qdb_pool.putconn(conn, close=True)
            return []
        finally:
            try:
                qdb_pool.putconn(conn)
            except Exception:
                pass  # Already returned above

    def get_conn(self):
        # Compatibility method, now using pool
        return get_qdb_pool().getconn()

    async def run_backtest(self, symbols: List[str], start_date: str, end_date: str, timeframe: str = "5m", initial_capital: float = 100000.0):
        """
        Main loop for historical simulation.
        """
        if self.is_running:
            logger.warning("Backtest already in progress. Ignoring request.")
            return {"status": "error", "message": "Backtest already in progress"}

        # Generate unique run_id for this backtest
        import uuid
        sim_run_id = str(uuid.uuid4())
        self.current_simulation_run_id = sim_run_id
        
        self.is_running = True
        self.current_step = 0
        self.progress = 0
        
        is_dynamic = len(symbols) == 0
        logger.info(f"Starting TIL Backtest {sim_run_id}: {start_date} to {end_date} | Mode: {'Dynamic' if is_dynamic else f'{len(symbols)} symbols'} | TF: {timeframe} | Cap: {initial_capital}")
        
        # We'll run the actual simulation in a background thread to prevent blocking
        task = asyncio.create_task(self._execute_simulation(symbols, start_date, end_date, timeframe, initial_capital, is_dynamic, sim_run_id))
        
        def _handle_task_result(t: asyncio.Task):
            try:
                t.result()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                with open("/tmp/backtest_debug.log", "a") as f:
                    f.write(f"[{datetime.now()}] 💥 Unhandled Exception in background task: {e}\\n")
                    f.write(traceback.format_exc())
                self.is_running = False
                
        task.add_done_callback(_handle_task_result)
        self._current_task = task  # Keep a strong reference to prevent garbage collection
        
        return {"status": "started", "run_id": sim_run_id}

    async def _execute_simulation(self, symbols, start_date, end_date, timeframe, initial_capital, is_dynamic, sim_run_id):
        """
        Direct DB Streaming Engine (IDE Parity)
        Fetches OHLCV from QuestDB day-by-day and processes tick slices
        through the TIL module pipeline. Zero lookahead bias guaranteed
        by sequential day processing.
        """
        current_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        
        if current_dt > end_dt:
            logger.warning(f"Inverted date range detected ({start_date} to {end_date}). Swapping dates.")
            current_dt, end_dt = end_dt, current_dt
            start_date, end_date = end_date, start_date

        pg_conn = None
        
        try:
            with open("/tmp/backtest_debug.log", "a") as f:
                f.write(f"\\n[{datetime.now()}] Entering _execute_simulation run_id={sim_run_id} symbols={symbols} dates={start_date}->{end_date}\\n")

            pg_conn = psycopg2.connect(
                host=os.getenv("POSTGRES_HOST", "postgres_metadata"),
                port=5432, user="admin", password="password123", database="quant_platform"
            )
            with open("/tmp/backtest_debug.log", "a") as f: f.write(f"[{datetime.now()}] PG connected. Clearing state...\\n")

            # 1. Clear State
            await portfolio_engine.clear_state(timestamp=current_dt, initial_capital=initial_capital, run_id=sim_run_id)
            with open("/tmp/backtest_debug.log", "a") as f: f.write(f"[{datetime.now()}] State cleared. Checking data completeness...\\n")
            
            # 2. Check & Backfill
            needs_backfill = await self._check_data_completeness(symbols, start_date, end_date, timeframe)
            if needs_backfill:
                logger.info("📥 Data incomplete. Triggering backfill...")
                await self._trigger_backfill(symbols, start_date, end_date, timeframe)
                logger.info("✅ Backfill complete.")

            # 3. Generate trading days (Mon-Fri only, matching IDE pattern)
            trading_days = []
            tmp = current_dt
            while tmp <= end_dt:
                if tmp.weekday() < 5:
                    trading_days.append(tmp)
                tmp += timedelta(days=1)
            
            if not trading_days:
                logger.warning("⚠️ No trading dates in range.")
                return

            # Progress tracking
            tf_map = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "1d": 375}
            step_min = tf_map.get(timeframe, 5)
            steps_per_day = 375 // step_min
            self.total_steps = len(trading_days) * steps_per_day
            self.current_step = 0

            print(f"[TIL-BACKTEST] 📅 Starting simulation: {len(trading_days)} days, {len(symbols)} syms, TF={timeframe}", flush=True)
            logger.info(f"📅 Starting simulation: {len(trading_days)} trading days, {len(symbols)} symbols, TF={timeframe}")

            # 4. DAY-BY-DAY STREAMING (matching IDE backtest_runner.py pattern)
            for day_idx, day_dt in enumerate(trading_days):
                date_str = day_dt.strftime("%Y-%m-%d")
                
                # Discovery Universe (if dynamic)
                active_universe = list(symbols)
                if is_dynamic:
                    active_universe = self._fetch_discovery_universe(day_dt.replace(hour=9, minute=15), timeframe)
                
                # Include held symbols for MtM continuity (IDE parity)
                portfolio_state = await portfolio_engine.get_state()
                held_symbols = [p.symbol for p in portfolio_state.open_positions]
                fetch_symbols = list(set(active_universe + held_symbols))
                
                # Record universe for frontend visibility
                try:
                    cur_pg = pg_conn.cursor()
                    for sym in active_universe:
                        cur_pg.execute("""
                            INSERT INTO backtest_universe (run_id, date, symbol, score)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT (run_id, date, symbol) DO NOTHING;
                        """, (sim_run_id, day_dt.date(), sym, 1.0))
                    pg_conn.commit()
                    cur_pg.close()
                except Exception as e:
                    logger.error(f"Failed to record backtest_universe: {e}")

                if not fetch_symbols:
                    continue

                # 5. BULK FETCH OHLCV for this day (using short-lived connection)
                start_ts = f"{date_str}T00:00:00.000000Z"
                end_ts = f"{date_str}T23:59:59.999999Z"
                
                ohlc_rows = self._fetch_ohlc_bulk(fetch_symbols, start_ts, end_ts, timeframe)
                noise_map = self._fetch_noise_confidence_bulk(fetch_symbols, date_str)
                features_day = {} # Initialize to avoid NameError
                
                if not ohlc_rows:
                    continue

                logger.info(f"📅 Day {day_idx+1}/{len(trading_days)} ({date_str}): {len(ohlc_rows)} ticks across {len(fetch_symbols)} symbols")

                # 6. GROUP BY TIMESTAMP → Time Slices (IDE pattern)
                from collections import defaultdict
                time_slices = defaultdict(dict)
                for row in ohlc_rows:
                    sym, ts, cl, vol = row[0], row[1], row[2], row[3] if len(row) > 3 else 0
                    time_slices[ts][sym] = {
                        'ltp': float(cl),
                        'volume': int(vol) if vol else 0
                    }
                
                # 7. PROCESS SLICES SEQUENTIALLY (zero lookahead bias)
                sorted_timestamps = sorted(time_slices.keys())
                day_snapshots = []
                day_orders = []
                
                # Mock a list to collect orders since we bypassed the engine's internal DB write
                self._current_day_orders = day_orders

                for ts_obj in sorted_timestamps:
                    data_at_time = time_slices[ts_obj]
                    try:
                        # Pass skip_db=True to avoid synchronous per-tick writes
                        await self._step_v4(data_at_time, features_day, ts_obj, timeframe, pg_conn, sim_run_id, fetch_symbols, skip_db=True)
                        
                        # Capture a snapshot in memory for the equity curve
                        state = await portfolio_engine.get_state()
                        day_snapshots.append((
                            ts_obj, state.total_heat_pct, 
                            state.factor_exposure.get("BANKING", 0.0),
                            state.factor_exposure.get("IT", 0.0),
                            state.factor_exposure.get("ENERGY", 0.0),
                            state.factor_exposure.get("FMCG", 0.0),
                            len(state.open_positions),
                            state.json(),
                            sim_run_id
                        ))

                    except Exception as e:
                        logger.error(f"Error in _step_v3 at {ts_obj}: {e}")
                    
                    self.current_step += 1
                    self.progress = min(99, int((self.current_step / max(1, self.total_steps)) * 100))

                # 8. DAY-END BATCH FLUSH (The "Speed Boost")
                try:
                    cur_pg = pg_conn.cursor()
                    # Batch insert snapshots
                    if day_snapshots:
                        # We only flush every Nth snapshot to keep the DB size manageable while maintaining resolution
                        # e.g. every 5th snapshot for 1m data, or all for 15m+
                        # Record ALL snapshots for maximum curve resolution in backtests
                        stride = 1
                        batch_snaps = day_snapshots[::stride]
                        
                        cur_pg.executemany("""
                            INSERT INTO portfolio_snapshots (
                                snapshot_time, heat_pct, factor_banking, factor_it, 
                                factor_energy, factor_fmcg, open_positions_count, full_json, run_id
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, batch_snaps)
                    
                    # Batch insert orders recorded during the day (Fixed: Removed nonexistent 'status' column)
                    if day_orders:
                        cur_pg.executemany("""
                            INSERT INTO backtest_orders (run_id, timestamp, symbol, transaction_type, quantity, price, pnl)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """, day_orders)
                    
                    # Update the final equity for the day in the summary table
                    state = await portfolio_engine.get_state()
                    cur_pg.execute("""
                        UPDATE backtest_portfolios 
                        SET balance = %s, equity = %s, last_updated = %s
                        WHERE run_id = %s;
                    """, (state.cash, state.total_equity, day_dt, sim_run_id))
                    
                    pg_conn.commit()
                    cur_pg.close()
                except Exception as e:
                    logger.error(f"Failed to flush day batch to DB: {e}")

                # Yield to event loop periodically
                await asyncio.sleep(0)

            # 8. Final Stats
            await self._persist_final_stats(pg_conn, sim_run_id, initial_capital)
            
            portfolio_state = await portfolio_engine.get_state()
            logger.info(f"🏁 Simulation {sim_run_id} Complete. Total Equity: {portfolio_state.total_equity:.2f}")

        except Exception as e:
            logger.error(f"🚨 Backtest Critical Failure: {e}", exc_info=True)
            print(f"[TIL-BACKTEST] 🚨 CRITICAL FAILURE: {e}", flush=True)
            import traceback
            traceback.print_exc()
        finally:
            if pg_conn:
                pg_conn.close()
            self.is_running = False
            self.progress = 100
            logger.info(f"✅ TIL Backtest {sim_run_id} finished.")

    async def _persist_final_stats(self, pg_conn, run_id, initial_capital):
        """Calculates final simulation statistics and saves to backtest_results."""
        try:
            cur = pg_conn.cursor()
            # Fetch all trades for this run to compute stats
            cur.execute("""
                SELECT pnl, price, quantity FROM backtest_orders 
                WHERE run_id = %s AND pnl IS NOT NULL
            """, (run_id,))
            trades = cur.fetchall()
            
            portfolio_state = await portfolio_engine.get_state()
            final_equity = portfolio_state.total_equity
            total_net_pnl = final_equity - initial_capital
            total_return = (total_net_pnl / initial_capital) * 100
            
            pnl_list = [float(t[0]) for t in trades if t[0] is not None]
            wins = [p for p in pnl_list if p > 0]
            win_rate = (len(wins) / len(pnl_list)) * 100 if pnl_list else 0
            
            stats_json = {
                "net_profit": round(total_net_pnl, 2),
                "total_return": round(total_return, 2),
                "win_rate": round(win_rate, 2),
                "total_trades": len(pnl_list),
                "initial_capital": initial_capital,
                "final_equity": round(final_equity, 2)
            }
            
            cur.execute("""
                INSERT INTO backtest_results (run_id, total_return, win_rate, stats_json)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (run_id) DO UPDATE SET
                total_return = EXCLUDED.total_return,
                win_rate = EXCLUDED.win_rate,
                stats_json = EXCLUDED.stats_json;
            """, (run_id, total_return, win_rate, json.dumps(stats_json)))
            pg_conn.commit()
            cur.close()
            logger.info(f"📊 Final stats persisted for {run_id}: Ret {total_return:.2f}% | WR {win_rate:.2f}%")
        except Exception as e:
            logger.error(f"Failed to persist final stats: {e}")

    def _fetch_ohlc_bulk(self, symbols: List[str], start_ts: str, end_ts: str, timeframe: str):
        """Optimal bulk fetch for OHLC using QuestDB SAMPLE BY for dynamic downsampling."""
        sym_list = "'" + "','".join(symbols) + "'"
        # Query the base 'ohlc' table which has 1m data and use SAMPLE BY to aggregate on the fly
        query = f"""
            SELECT symbol, timestamp, first(open) as open, max(high) as high, min(low) as low, last(close) as close, sum(volume) as volume
            FROM ohlc
            WHERE symbol IN ({sym_list})
              AND timeframe = '1m'
              AND timestamp >= '{start_ts}'
              AND timestamp <= '{end_ts}'
            SAMPLE BY {timeframe} FILL(NONE)
            ORDER BY timestamp ASC;
        """
        # We need to map the aggregated columns back to standard dictionary format if needed
        # The query returns: symbol, timestamp, open, high, low, close, volume (7 items)
        # But _execute_simulation only extracts timestamp, close, volume. But we fetch 7 columns.
        rows = self._qdb_exec(query)
        # return [symbol, timestamp, close, volume] format to match existing _execute_simulation unpack
        return [[r[0], r[1], r[5], r[6]] for r in rows]

    def _fetch_noise_confidence_bulk(self, symbols: List[str], date_str: str):
        """Optimal bulk fetch for noise confidence using a short-lived connection."""
        conf_map = {s: 0.0 for s in symbols}
        
        # Backtest Mode Fallback
        if os.getenv("TIL_BACKTEST_MODE", "false").lower() == "true":
            for s in symbols:
                conf_map[s] = 0.85
            return conf_map
            
        sym_list = "'" + "','".join(symbols) + "'"
        # Use LATEST BY for efficiency
        query = f"""
            SELECT symbol, confidence
            FROM noise_confidence
            LATEST BY symbol
            WHERE symbol IN ({sym_list})
              AND timestamp <= '{date_str}T23:59:59.999999Z';
        """
        rows = self._qdb_exec(query)
        for r in rows:
            conf_map[r[0]] = r[1]
        return conf_map

    async def _execute_trade(self, symbol, direction, qty, price, timestamp, run_id, skip_db):
        """Executes a trade in the portfolio engine and records it."""
        try:
            # 1. Update Portfolio Engine (Internal State)
            await portfolio_engine.update_position_v2(
                symbol=symbol, qty=qty, price=price,
                sector="EQUITY", direction=direction,
                timestamp=timestamp, run_id=run_id
            )
            
            # 2. Set Metadata (Stops and Targets)
            if not hasattr(self, "position_metadata"): self.position_metadata = {}
            self.position_metadata[symbol] = {
                "bars_held": 0,
                "sl": price * 0.985 if direction == "LONG" else price * 1.015,
                "tp_price": price * 1.05 if direction == "LONG" else price * 0.95,
                "is_trailing": False
            }
            
            # 3. Batch Log (for Speed)
            if skip_db and hasattr(self, "_current_day_orders"):
                # Order: (run_id, timestamp, symbol, transaction_type, quantity, price, pnl)
                self._current_day_orders.append((
                    run_id, timestamp, symbol, direction, qty, price, None # PnL is only for exits
                ))
        except Exception as e:
            logger.error(f"Trade Execution Failed for {symbol}: {e}")

    async def _step_v4(self, tick_data: Dict, features_day: Dict, timestamp: datetime, timeframe: str, pg_conn, run_id, discovery_universe, skip_db: bool = False):
        """
        Ultra-High Performance C++ Batch Ticker.
        Zero Pydantic Allocation in Hot Loop.
        """
        if not tick_data: return
        
        portfolio_state = await portfolio_engine.get_state()
        if not hasattr(self, 'feature_state'): self.feature_state = {}
        
        try:
            import til_core
            # 1. Prepare Portfolio Data for C++
            cpp_positions = []
            for pos in portfolio_state.open_positions:
                meta = getattr(self, "position_metadata", {}).get(pos.symbol, {})
                cpp_pos = til_core.PositionState()
                cpp_pos.symbol = pos.symbol
                cpp_pos.entry_price = pos.entry_price
                cpp_pos.current_price = pos.current_price
                cpp_pos.qty = pos.qty
                cpp_pos.direction = pos.direction
                cpp_pos.sl_price = meta.get("sl", pos.entry_price * 0.985)
                cpp_pos.tp_price = meta.get("tp_price", pos.entry_price * 1.05)
                cpp_pos.bars_held = meta.get("bars_held", 0)
                cpp_positions.append(cpp_pos)
            
            # 2. Prepare Universe Data (Fast dict updates instead of Pydantic)
            cpp_universe = {}
            for sym, tick in tick_data.items():
                ltp = tick['ltp']
                fs = self.feature_state.get(sym, {"sma50": ltp, "sma200": ltp, "rsi": 50.0, "last_ltp": ltp})
                
                # Recursive SMA updates (O(1))
                fs["sma50"] = (fs["sma50"] * 49 + ltp) / 50
                fs["sma200"] = (fs["sma200"] * 199 + ltp) / 200
                fs["last_ltp"] = ltp
                self.feature_state[sym] = fs

                momentum = (ltp / fs["sma50"]) - 1
                
                feat = til_core.StockFeatures()
                feat.adx = 25.0 # Mock or from features_day
                feat.atr_slope_5d = -0.0001
                feat.obv_slope_5d = 0.02
                feat.momentum_5d = momentum
                feat.hurst = 0.55
                feat.close = ltp
                cpp_universe[sym] = feat
            
            # 3. Call C++ Atomic Operation (Scanning + Exit + MTW)
            results = til_core.process_tick_batch(cpp_positions, cpp_universe)
            
            # 4. Sync State back to Python
            for i, pos in enumerate(portfolio_state.open_positions):
                pos.current_price = cpp_positions[i].current_price
                pos.market_value = pos.qty * pos.current_price
                meta = getattr(self, "position_metadata", {})
                if pos.symbol not in meta: meta[pos.symbol] = {}
                meta[pos.symbol]["bars_held"] = cpp_positions[i].bars_held
                self.position_metadata = meta

            portfolio_state.total_equity = portfolio_state.cash + sum(p.market_value for p in portfolio_state.open_positions)
            
            # 5. Handle Exits
            for exit_sig in results.exits:
                pos = next((p for p in portfolio_state.open_positions if p.symbol == exit_sig.symbol), None)
                if not pos: continue
                
                price = tick_data[pos.symbol]['ltp']
                if skip_db and hasattr(self, "_current_day_orders"):
                    mult = 1 if pos.direction == "LONG" else -1
                    actual_pnl = pos.qty * (price - pos.entry_price) * mult
                    self._current_day_orders.append((
                        run_id, timestamp, pos.symbol, 
                        "LONG" if pos.direction=="SHORT" else "SHORT", abs(pos.qty), price, actual_pnl
                    ))

                await portfolio_engine.update_position_v2(
                    symbol=pos.symbol, qty=-pos.qty, price=price,
                    sector="EQUITY", direction="LONG" if pos.direction=="SHORT" else "SHORT",
                    timestamp=timestamp, run_id=run_id
                )
                if pos.symbol in self.position_metadata:
                    del self.position_metadata[pos.symbol]

            # 6. Handle New Signals
            for sym, score in results.signals.items():
                if any(p.symbol == sym for p in portfolio_state.open_positions):
                    continue
                
                # ML Logic (Python) - Only for approved signals
                # confidence = await classifier.classify(sym, ...) # Optional
                
                size_res = await position_sizer.get_size(
                    symbol=sym, entry_price=tick_data[sym]['ltp'],
                    confidence=score, current_equity=portfolio_state.total_equity,
                    in_backtest=True
                )
                
                shares = size_res.get("shares", 0)
                if shares > 0:
                    await self._execute_trade(sym, "LONG", shares, tick_data[sym]['ltp'], timestamp, run_id, skip_db)

        except (ImportError, Exception) as e:
            logger.error(f"C++ Batch Error: {e}")
            await self._step_v3(tick_data, {}, timestamp, timeframe, pg_conn, run_id, discovery_universe, skip_db)

    async def _step_v3(self, tick_data: Dict, noise_map: Dict, timestamp: datetime, timeframe: str, pg_conn, run_id, discovery_universe, skip_db: bool = False):
        """
        High-Performance Tick Execution.
        Processes OHLC slice for all symbols at once.
        """
        if not tick_data: return
        # 1. Mark to Market (Update Portfolio Value)
        price_map = {sym: d['ltp'] for sym, d in tick_data.items()}
        await portfolio_engine.mark_to_market(price_map, timestamp, db_conn=pg_conn, run_id=run_id, skip_db=skip_db)
        
        portfolio_state = await portfolio_engine.get_state()
        
        # --- EXIT MANAGEMENT BLOCK ---
        # Evaluate all open positions against current OHLC slice
        for pos in portfolio_state.open_positions[:]:
            if pos.symbol not in tick_data: continue
            
            tick = tick_data[pos.symbol]
            current_price = tick['ltp']
            
            meta = getattr(self, "position_metadata", {})
            if pos.symbol not in meta:
                meta[pos.symbol] = {
                    "bars_held": 0,
                    "sl": pos.entry_price * 0.98,
                    "tp_price": pos.entry_price * 1.04,
                    "is_trailing": False
                }
                self.position_metadata = meta
                
            p_meta = self.position_metadata[pos.symbol]
            p_meta["bars_held"] += 1
            
            pnl_pct = (current_price - pos.entry_price) / pos.entry_price
            if pos.direction == "SHORT": pnl_pct = -pnl_pct
            
            # Multi-Stage Trailing Stop (IDE Parity)
            if not p_meta["is_trailing"] and pnl_pct >= 0.015:
                p_meta["sl"] = pos.entry_price * 1.001
                p_meta["is_trailing"] = True
                
            if pnl_pct >= 0.03:
                new_sl = current_price * 0.985 if pos.direction == "LONG" else current_price * 1.015
                if (pos.direction == "LONG" and new_sl > p_meta["sl"]) or (pos.direction == "SHORT" and new_sl < p_meta["sl"]):
                    p_meta["sl"] = new_sl
                    
            # Check Exit Conditions
            exit_reason = None
            if (pos.direction == "LONG" and current_price >= p_meta["tp_price"]) or (pos.direction == "SHORT" and current_price <= p_meta["tp_price"]):
                exit_reason = "TARGET HIT"
            elif (pos.direction == "LONG" and current_price <= p_meta["sl"]) or (pos.direction == "SHORT" and current_price >= p_meta["sl"]):
                exit_reason = "STOP LOSS"
            elif p_meta["bars_held"] >= 40: # Time exit ~ 10 hours on 15m
                exit_reason = "TIME EXIT"
                
            if exit_reason:
                # Record order locally for batching (Parity with update_position_v2 calculation)
                if skip_db and hasattr(self, "_current_day_orders"):
                    mult = 1 if pos.direction == "LONG" else -1
                    actual_pnl = pos.qty * (current_price - pos.entry_price) * mult
                    self._current_day_orders.append((
                        run_id, timestamp, pos.symbol, 
                        "LONG" if pos.direction=="SHORT" else "SHORT", abs(pos.qty), current_price, actual_pnl
                    ))

                await portfolio_engine.update_position_v2(
                    symbol=pos.symbol,
                    qty=-pos.qty, # Reverse quantity to close
                    price=current_price,
                    sector=pos.sector,
                    direction="LONG" if pos.direction=="SHORT" else "SHORT", # closing trade direction
                    timestamp=timestamp,
                    run_id=run_id
                )
                self.position_metadata.pop(pos.symbol, None)
                continue
        # --- END EXIT MANAGEMENT ---
        
        # 2. Features for SCANNING (Discovery symbols only)
        # Using a simple rolling state for realistic dynamic features
        if not hasattr(self, 'feature_state'): self.feature_state = {}
        
        features_batch = {}
        for symbol in discovery_universe:
            if symbol not in tick_data: continue
            row = tick_data[symbol]
            ltp = row['ltp']
            
            fs = self.feature_state.get(symbol, {"sma50": ltp, "sma200": ltp, "rsi": 50.0, "last_ltp": ltp})
            
            # Simple recursive updates for realistic dynamics
            fs["sma50"] = (fs["sma50"] * 49 + ltp) / 50
            fs["sma200"] = (fs["sma200"] * 199 + ltp) / 200
            
            diff = ltp - fs["last_ltp"]
            gain = diff if diff > 0 else 0
            loss = abs(diff) if diff < 0 else 0
            # Approx Wilder's Smoothing
            rs = (gain / max(loss, 0.001))
            fs["rsi"] = (fs["rsi"] * 13 + (100 - (100 / (1 + rs)))) / 14
            fs["last_ltp"] = ltp
            self.feature_state[symbol] = fs
            
            momentum = (ltp / fs["sma50"]) - 1
            
            features_batch[symbol] = FeatureVector(
                symbol=symbol,
                timestamp=timestamp,
                close=ltp,
                adx=25.0, adx_slope_5d=0.01,
                hurst=0.6, hurst_slope_5d=0.0,
                momentum_5d=momentum, momentum_21d=momentum*2, momentum_63d=momentum*4,
                obv_slope_5d=0.02, obv_slope_21d=0.03,
                close_vs_50sma=(ltp / fs["sma50"]) - 1, close_vs_200sma=(ltp / fs["sma200"]) - 1,
                atr_pct=0.02, atr_price=ltp*0.02, atr_slope_5d=0.0,
                volume_ratio_1d=1.2, volume_cv_10d=0.5,
                rsi_14=fs["rsi"],
                beta_market_63d=1.0, beta_sector_63d=1.0,
                rs_vs_sector_21d=0.02, rs_vs_market_21d=0.02,
                weekly_adx=30.0, weekly_hurst=0.6, weekly_momentum_12w=0.1, weekly_obv_slope=0.02,
                monthly_close_vs_12msma=0.05
            )

        # 3. Pipeline Scan
        context = MarketContext(
            timestamp=timestamp,
            nifty_level=20000.0,
            nifty_return_today=0.0,
            india_vix=15.0,
            vix_slope_5d=0.0,
            pairwise_correlation=0.5,
            signal_density=1,
            market_regime="TRENDING",
            days_in_regime=10,
            expiry_proximity="FAR",
            sector_returns={}
        )
        
        signals = await scanner.scan(features_batch)
        current_equity = portfolio_state.total_equity
        
        # Fetch current positions for gating
        held_syms = set([p.symbol for p in portfolio_state.open_positions])
        
        for signal in signals:
            if signal.symbol in held_syms: continue # Do not add to existing position in standard vector test
            
            features = features_batch.get(signal.symbol)
            if not features: continue
            
            mech_res = await mechanism_classifier.classify(signal, features, context)
            if not mech_res or mech_res.action == "DISCARD":
                continue
            
            confidence_from_db = noise_map.get(signal.symbol, 0.0)
            if confidence_from_db < 0.3:
                continue
                
            combined_conf = (signal.pattern_score + mech_res.mechanism_confidence + confidence_from_db) / 3.0
            
            sizing = await position_sizer.get_size(
                signal.symbol,
                signal.entry_price_estimate,
                combined_conf,
                current_equity,
                signal.signal_type,
                signal.direction.name if hasattr(signal.direction, 'name') else str(signal.direction),
                timestamp.isoformat(),
                skip_db
            )
            
            direction_str = signal.direction.name if hasattr(signal.direction, 'name') else str(signal.direction)
            if sizing.get("approved"):
                # Record order locally for batching instead of calling engine's internal sync
                if skip_db and hasattr(self, "_current_day_orders"):
                    self._current_day_orders.append((
                        run_id, timestamp, signal.symbol, 
                        direction_str, abs(sizing.get("shares")), signal.entry_price_estimate, 0.0
                    ))

                await portfolio_engine.update_position_v2(
                    symbol=signal.symbol,
                    qty=sizing.get("shares"),
                    price=signal.entry_price_estimate,
                    sector="EQUITY",
                    direction=direction_str,
                    timestamp=timestamp,
                    run_id=run_id
                )
                
                # Assign Exit Metdata
                exit_plan = sizing.get("exit_plan", {})
                sl_price = exit_plan.get("stop_loss", signal.entry_price_estimate * 0.985)
                tp_price = exit_plan.get("take_profit", signal.entry_price_estimate * 1.05)
                
                if not hasattr(self, "position_metadata"): self.position_metadata = {}
                self.position_metadata[signal.symbol] = {
                    "bars_held": 0,
                    "sl": sl_price,
                    "tp_price": tp_price,
                    "is_trailing": False
                }

    def _fetch_discovery_universe(self, timestamp: datetime, timeframe: str) -> List[str]:
        """
        Discovers active symbols in QuestDB. 
        Always looks at '1m' base data for discovery.
        """
        window_start = timestamp - timedelta(hours=2)
        query = f"""
        SELECT DISTINCT symbol 
        FROM ohlc 
        WHERE timeframe = '1m'
        AND timestamp >= '{window_start.isoformat()}'
        AND timestamp <= '{timestamp.isoformat()}';
        """
        rows = self._qdb_exec(query)
        return [r[0] for r in rows]

    def _fetch_synced_data(self, conn, symbols: List[str], timestamp: datetime, timeframe: str) -> Dict:
        """
        Fetches the nearest OHLC/Microstructure slice for all symbols.
        """
        data = {}
        if not symbols: return data
        
        try:
            cur = conn.cursor()
            sym_list = "'" + "','".join(symbols) + "'"
            query = f"""
            SELECT symbol, close, volume 
            FROM ohlc LATEST BY symbol 
            WHERE timeframe = '{timeframe}'
            AND symbol IN ({sym_list}) 
            AND timestamp <= '{timestamp.isoformat()}';
            """
            cur.execute(query)
            rows = cur.fetchall()
            for r in rows:
                data[r[0]] = {
                    'ltp': r[1],
                    'volume': r[2],
                    'oi': 0 # OHLC doesn't always have OI
                }
            cur.close()
        except Exception as e:
            logger.error(f"QuestDB fetch error: {e}")
        return data

    async def _check_data_completeness(self, symbols: List[str], start_date: str, end_date: str, timeframe: str) -> bool:
        """Checks if QuestDB has sufficient 1-minute data for the run. Returns True if backfill is needed."""
        try:
            if not symbols:
                # Dynamic mode: check if we have ANY data for this timeframe/period
                rows = self._qdb_exec(
                    f"SELECT count(*) FROM ohlc WHERE timeframe = '1m' "
                    f"AND timestamp >= '{start_date}T00:00:00.000000Z' "
                    f"AND timestamp <= '{end_date}T23:59:59.999999Z'"
                )
                return (rows[0][0] if rows else 0) < 100  # Lower threshold
            
            missing_count = 0
            for symbol in symbols:
                rows = self._qdb_exec(
                    f"SELECT count(*) FROM ohlc WHERE symbol = '{symbol}' "
                    f"AND timeframe = '1m' "
                    f"AND timestamp >= '{start_date}T00:00:00.000000Z' "
                    f"AND timestamp <= '{end_date}T23:59:59.999999Z'"
                )
                count = rows[0][0] if rows else 0
                if count < 50:
                    missing_count += 1
            return missing_count > 0
        except:
            return True  # Assume missing if table doesn't exist

    async def _trigger_backfill(self, symbols: List[str], start_date: str, end_date: str, timeframe: str):
        """Calls the backfiller service for 1-minute data and polls until complete."""
        self.is_backfilling = True
        self.backfill_progress = 0
        
        # Upstox V2 API rejects 5minute intra-day. Always pull 1m and assemble using SAMPLE BY.
        interval = "1"
        unit = "minutes"
        
        # Format symbols for backfiller (e.g. "NSE_EQ|RELIANCE" -> "RELIANCE (NSE)")
        if symbols:
            fb_symbols = [f"{s.split('|')[1]} (NSE)" if "|" in s else f"{s} (NSE)" for s in symbols]
        else:
            # Default symbols for dynamic mode if none provided
            fb_symbols = [
                "NSE_EQ|INE002A01018", # RELIANCE
                "NSE_EQ|INE040A01034", # HDFCBANK
                "NSE_EQ|INE467B01029", # TCS
                "NSE_EQ|INE009A01021", # INFY
                "NSE_EQ|INE090A01021", # ICICIBANK
                "NSE_EQ|INE062A01020", # SBIN
                "NSE_EQ|INE154A01025", # ITC
                "NSE_EQ|INE018A01030", # L&T
                "NSE_EQ|INE238A01034"  # AXISBANK
            ]
        
        payload = {
            "start_date": start_date,
            "end_date": end_date,
            "stocks": fb_symbols,
            "interval": interval,
            "unit": unit,
            "run_noise_filter": True
        }
        
        try:
            session = await get_http_session()
            async with session.post("http://data_backfiller:8001/backfill/start", json=payload) as resp:
                if resp.status == 409:
                    logger.info("Backfill already in progress. Joining polling loop to wait for completion.")
                elif resp.status != 200:
                    logger.error(f"Backfill trigger failed: {await resp.text()}")
                    self.is_backfilling = False
                    return

            # Poll
            while self.is_backfilling:
                async with session.get("http://data_backfiller:8001/backfill/status") as s_resp:
                    if s_resp.status == 200:
                        status = await s_resp.json()
                        self.backfill_progress = status.get("overall_progress", 0)
                        if status.get("finished") or not status.get("running"):
                            break
                await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"Error during backfill orchestration: {e}")
        
        self.is_backfilling = False
        logger.info("Backfill complete. Proceeding to simulation.")
