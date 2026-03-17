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

logger = logging.getLogger("TILBacktest")

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
        asyncio.create_task(self._execute_simulation(symbols, start_date, end_date, timeframe, initial_capital, is_dynamic, sim_run_id))
        
        return {"status": "started", "run_id": sim_run_id}

    async def _execute_simulation(self, symbols, start_date, end_date, timeframe, initial_capital, is_dynamic, sim_run_id):
        """
        High-Performance Streaming Replayer (Traditional Approach)
        Loads QuestDB data in daily chunks and processes in-memory.
        Uses per-operation connections to prevent stale connection errors.
        """
        # Date Range Robustness
        current_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        
        if current_dt > end_dt:
            logger.warning(f"Inverted date range detected ({start_date} to {end_date}). Swapping dates.")
            current_dt, end_dt = end_dt, current_dt
            start_date, end_date = end_date, start_date

        pg_conn = None
        
        try:
            pg_conn = psycopg2.connect(
                host=os.getenv("POSTGRES_HOST", "postgres_metadata"),
                port=5432, user="admin", password="password123", database="quant_platform"
            )
            # 1. Clear State with proper run_id for the initial T0 point
            await portfolio_engine.clear_state(timestamp=current_dt, initial_capital=initial_capital, run_id=sim_run_id)
            
            # 2. Check & Backfill (Including Noise Filter)
            # Uses _qdb_exec which manages its own short-lived connection
            needs_backfill = await self._check_data_completeness(symbols, start_date, end_date, timeframe)
            if needs_backfill:
                logger.info("📥 Data incomplete. Triggering backfill (this may take a few minutes)...")
                await self._trigger_backfill(symbols, start_date, end_date, timeframe)
                logger.info("✅ Backfill complete. Starting simulation.")

            # 3. Calculate Total Steps
            trading_days = []
            tmp = current_dt
            while tmp <= end_dt:
                if tmp.weekday() < 5: trading_days.append(tmp)
                tmp += timedelta(days=1)
            
            # Resolution for progress
            tf_map = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "1d": 375}
            step_min = tf_map.get(timeframe, 5)
            steps_per_day = 375 // step_min
            self.total_steps = len(trading_days) * steps_per_day
            self.current_step = 0

            # 4. START DAY-BY-DAY STREAMING
            # KEY FIX: Each day gets fresh connections via _qdb_exec.
            # No single connection is held open across the entire simulation.
            for day_dt in trading_days:
                date_str = day_dt.strftime("%Y-%m-%d")
                logger.info(f"📅 Processing Day: {date_str}")
                
                # Discovery Universe (if dynamic) - uses fresh connection
                active_universe = list(symbols)
                if is_dynamic:
                    active_universe = self._fetch_discovery_universe(day_dt.replace(hour=9, minute=15), timeframe)
                
                # Fetch currently held symbols to ensure MtM continuity
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
                    logger.debug(f"Recorded {len(active_universe)} symbols to backtest_universe for {date_str}")
                except Exception as e:
                    logger.error(f"Failed to record backtest_universe: {e}")

                if not fetch_symbols:
                    logger.debug(f"No symbols for {date_str}, skipping.")
                    continue

                # 5. BULK FETCH (One query for all symbols) - each uses fresh connection
                # Broaden window to account for potential timezone offsets (UTC vs IST)
                start_ts = f"{date_str}T00:00:00.000000Z"
                end_ts = f"{date_str}T23:59:59.999999Z"
                
                ohlc_rows = self._fetch_ohlc_bulk(fetch_symbols, start_ts, end_ts, timeframe)
                noise_map = self._fetch_noise_confidence_bulk(fetch_symbols, date_str)
                
                logger.info(f"OHLC Fetch for {date_str}: {len(ohlc_rows) if ohlc_rows else 0} rows found for symbols: {fetch_symbols}")
                
                if not ohlc_rows:
                    logger.warning(f"No OHLC data found for {date_str} even though symbols {fetch_symbols} were requested.")
                    continue

                logger.info(f"  → {len(ohlc_rows)} ticks across {len(fetch_symbols)} symbols")

                # 6. IN-MEMORY TICK REPLAY
                from collections import defaultdict
                time_slices = defaultdict(dict)
                for sym, ts, cl, vol in ohlc_rows:
                    time_slices[ts][sym] = {
                        'ltp': cl, 'volume': vol
                    }
                
                sorted_timestamps = sorted(time_slices.keys())
                
                for ts_obj in sorted_timestamps:
                    data_at_time = time_slices[ts_obj]
                    await self._step_v3(data_at_time, noise_map, ts_obj, timeframe, pg_conn, sim_run_id, active_universe)
                    
                    self.current_step += 1
                    self.progress = min(99, int((self.current_step / max(1, self.total_steps)) * 100))

            # Final Stats Calculation and Persistence
            await self._persist_final_stats(pg_conn, sim_run_id, initial_capital)
            
            logger.info(f"🏁 Simulation {sim_run_id} Complete. Total Equity: {portfolio_state.total_equity:.2f}")

        except Exception as e:
            logger.error(f"Backtest error in _execute_simulation: {e}", exc_info=True)
        finally:
            if pg_conn:
                pg_conn.close()
            self.is_running = False
            self.progress = 100

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
        """Optimal bulk fetch for OHLC using a short-lived connection."""
        sym_list = "'" + "','".join(symbols) + "'"
        query = f"""
            SELECT symbol, timestamp, close, volume
            FROM ohlc
            WHERE symbol IN ({sym_list})
              AND timeframe = '{timeframe}'
              AND timestamp >= '{start_ts}'
              AND timestamp <= '{end_ts}'
            ORDER BY timestamp ASC;
        """
        return self._qdb_exec(query)

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


    async def _step_v3(self, tick_data: Dict, noise_map: Dict, timestamp: datetime, timeframe: str, pg_conn, run_id, discovery_universe):
        """
        High-Performance Tick Execution.
        Processes OHLC slice for all symbols at once.
        """
        if not tick_data: return
        # 1. Mark to Market (Update Portfolio Value)
        price_map = {sym: d['ltp'] for sym, d in tick_data.items()}
        await portfolio_engine.mark_to_market(price_map, timestamp, db_conn=pg_conn, run_id=run_id)
        
        # 2. Features for SCANNING (Discovery symbols only)
        features_batch = {}
        for symbol in discovery_universe:
            if symbol not in tick_data: continue
            row = tick_data[symbol]
            features_batch[symbol] = FeatureVector(
                symbol=symbol,
                timestamp=timestamp,
                close=row['ltp'],
                adx=30.0, adx_slope_5d=0.01,
                hurst=0.6, hurst_slope_5d=0.0,
                momentum_5d=0.01, momentum_21d=0.05, momentum_63d=0.1,
                obv_slope_5d=0.02, obv_slope_21d=0.03,
                close_vs_50sma=0.05, close_vs_200sma=0.08,
                atr_pct=0.02, atr_price=row['ltp']*0.02, atr_slope_5d=0.0,
                volume_ratio_1d=1.2, volume_cv_10d=0.5,
                rsi_14=65.0,
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
        
        # Use CORRECT await scan()
        signals = await scanner.scan(features_batch)
        
        portfolio_state = await portfolio_engine.get_state()
        current_equity = portfolio_state.total_equity
        
        for signal in signals:
            features = features_batch.get(signal.symbol)
            if not features: continue
            
            # Use CORRECT await classify()
            mech_res = await mechanism_classifier.classify(signal, features, context)
            if not mech_res or mech_res.action == "DISCARD":
                continue
            
            # Integrated Noise Filter
            confidence_from_db = noise_map.get(signal.symbol, 0.0)
            if confidence_from_db < 0.3: # Quality threshold
                continue
                
            combined_conf = (signal.pattern_score + mech_res.mechanism_confidence + confidence_from_db) / 3.0
            
            # Use CORRECT await get_size()
            sizing = await position_sizer.get_size(
                symbol=signal.symbol,
                entry_price=signal.entry_price_estimate,
                confidence=combined_conf,
                current_equity=current_equity,
                signal_type=signal.signal_type,
                direction=signal.direction.name if hasattr(signal.direction, 'name') else str(signal.direction),
                timestamp=timestamp.isoformat()
            )
            
            if sizing.get("approved"):
                await portfolio_engine.update_position_v2(
                    symbol=signal.symbol,
                    qty=sizing.get("shares"),
                    price=signal.entry_price_estimate,
                    sector="EQUITY",
                    direction=signal.direction.name if hasattr(signal.direction, 'name') else str(signal.direction),
                    timestamp=timestamp,
                    run_id=run_id
                )

    def _fetch_discovery_universe(self, timestamp: datetime, timeframe: str) -> List[str]:
        """
        Discovers all active symbols in QuestDB for the given time slice.
        Uses a short-lived connection to prevent stale connection errors.
        """
        # Find symbols with data in the last 2 hours from ohlc table
        window_start = timestamp - timedelta(hours=2)
        query = f"""
        SELECT DISTINCT symbol 
        FROM ohlc 
        WHERE timeframe = '{timeframe}'
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
        """Checks if QuestDB has sufficient data for the run. Returns True if backfill is needed."""
        try:
            if not symbols:
                # Dynamic mode: check if we have ANY data for this timeframe/period
                rows = self._qdb_exec(
                    f"SELECT count(*) FROM ohlc WHERE timeframe = '{timeframe}' "
                    f"AND timestamp >= '{start_date}T00:00:00.000000Z' "
                    f"AND timestamp <= '{end_date}T23:59:59.999999Z'"
                )
                return (rows[0][0] if rows else 0) < 100  # Lower threshold
            
            missing_count = 0
            for symbol in symbols:
                rows = self._qdb_exec(
                    f"SELECT count(*) FROM ohlc WHERE symbol = '{symbol}' "
                    f"AND timeframe = '{timeframe}' "
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
        """Calls the backfiller service and polls until complete."""
        self.is_backfilling = True
        self.backfill_progress = 0
        
        interval = "".join(filter(str.isdigit, timeframe)) or "1"
        unit = "minutes" if "m" in timeframe else "hours" if "h" in timeframe else "day"
        
        # Default symbols for dynamic mode if none provided
        fb_symbols = symbols if symbols else [
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
                if resp.status != 200:
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
