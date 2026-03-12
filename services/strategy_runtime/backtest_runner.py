import os
import logging
import sys
import argparse
import time
import asyncio
import aiohttp
import psycopg2
from datetime import datetime, timedelta
from engine import AlgorithmEngine
from db import get_db_connection

import requests
import urllib.parse
import math
from operator import itemgetter

# Config
RUN_ID = os.getenv('RUN_ID', 'test_run')
STRATEGY_NAME = os.getenv('STRATEGY_NAME')
QUESTDB_URL = os.getenv('QUESTDB_URL', 'http://questdb_tsdb:9000')
TRADING_MODE = os.getenv('TRADING_MODE', 'MIS')
UPSTOX_ACCESS_TOKEN = os.getenv('UPSTOX_ACCESS_TOKEN', '')
UPSTOX_API_BASE = "https://api.upstox.com/v2/historical-candle"

# Known stocks for backfill (ISIN -> Name mapping)
KNOWN_STOCKS = {
    # Indices
    "NSE_INDEX|Nifty 50": "NIFTY 50",
    "NSE_INDEX|Nifty Bank": "BANK NIFTY",
    # NSE
    "NSE_EQ|INE002A01018": "RELIANCE",
    "NSE_EQ|INE040A01034": "HDFCBANK",
    "NSE_EQ|INE090A01021": "TCS",
    "NSE_EQ|INE009A01021": "INFY",
    "NSE_EQ|INE467B01029": "ICICIBANK",
    "NSE_EQ|INE062A01020": "SBIN",
    "NSE_EQ|INE154A01025": "ITC",
    "NSE_EQ|INE669E01016": "BAJFINANCE",
    "NSE_EQ|INE030A01027": "HINDUNILVR",
    "NSE_EQ|INE585B01010": "MARUTI",
    "NSE_EQ|INE176A01028": "AXISBANK",
    "NSE_EQ|INE021A01026": "ASIANPAINT",
    "NSE_EQ|INE075A01022": "WIPRO",
    "NSE_EQ|INE019A01038": "KOTAKBANK",
    "NSE_EQ|INE028A01039": "BAJAJFINSV",
    "NSE_EQ|INE397D01024": "BHARTIARTL",
    "NSE_EQ|INE047A01021": "SUNPHARMA",
    "NSE_EQ|INE326A01037": "ULTRACEMCO",
    "NSE_EQ|INE101A01026": "HCLTECH",
    "NSE_EQ|INE155A01022": "TATAMOTORS",
    # BSE
    "BSE_EQ|INE002A01018": "RELIANCE (BSE)",
    "BSE_EQ|INE040A01034": "HDFCBANK (BSE)",
    "BSE_EQ|INE090A01021": "TCS (BSE)",
    "BSE_EQ|INE009A01021": "INFY (BSE)",
    "BSE_EQ|INE467B01029": "ICICIBANK (BSE)",
    "BSE_EQ|INE062A01020": "SBIN (BSE)",
    "BSE_EQ|INE154A01025": "ITC (BSE)",
    "BSE_EQ|INE669E01016": "BAJFINANCE (BSE)",
    "BSE_EQ|INE030A01027": "HINDUNILVR (BSE)",
    "BSE_EQ|INE585B01010": "MARUTI (BSE)",
    "BSE_EQ|INE176A01028": "AXISBANK (BSE)",
    "BSE_EQ|INE021A01026": "ASIANPAINT (BSE)",
    "BSE_EQ|INE075A01022": "WIPRO (BSE)",
    "BSE_EQ|INE019A01038": "KOTAKBANK (BSE)",
    "BSE_EQ|INE028A01039": "BAJAJFINSV (BSE)",
    "BSE_EQ|INE397D01024": "BHARTIARTL (BSE)",
    "BSE_EQ|INE047A01021": "SUNPHARMA (BSE)",
    "BSE_EQ|INE326A01037": "ULTRACEMCO (BSE)",
    "BSE_EQ|INE101A01026": "HCLTECH (BSE)",
    "BSE_EQ|INE155A01022": "TATAMOTORS (BSE)"
}

# Rate limit config (safe margin below Upstox limits - Free Tier 1 req/s)
BACKFILL_DELAY_CHUNKS = 1.6   # seconds between API calls
BACKFILL_DELAY_STOCKS = 3.2   # seconds between stocks

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("BacktestRunner")


# ============================================================
# AUTO-BACKFILL: Detect & fill missing data before backtesting
# ============================================================

def get_qdb_conn():
    """Get raw QuestDB connection for backfill writes."""
    host = os.getenv("QUESTDB_HOST", "questdb_tsdb")
    try:
        conn = psycopg2.connect(host=host, port=8812, user="admin", password="quest", database="qdb")
        conn.autocommit = True
        return conn
    except Exception as e:
        logger.error(f"Cannot connect to QuestDB: {e}")
        return None


def find_missing_dates(symbols, start_date, end_date):
    """
    Check QuestDB for which trading days have data for each symbol.
    Returns dict: {symbol: [missing_date_str, ...]}
    """
    missing = {}

    # Generate all expected weekdays in range
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    expected_days = []
    current = start_dt
    while current <= end_dt:
        if current.weekday() < 5:  # Mon-Fri
            expected_days.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)

    if not expected_days:
        return missing

    for sym in symbols:
        # Query QuestDB for distinct dates with data using SAMPLE BY for speed
        query = f"""
        SELECT first(timestamp) FROM ohlc 
        WHERE symbol = '{sym}' 
          AND timestamp >= '{start_date}T00:00:00.000000Z' 
          AND timestamp <= '{end_date}T23:59:59.999999Z'
        SAMPLE BY 1d
        """
        try:
            encoded = urllib.parse.urlencode({"query": query})
            resp = requests.get(f"{QUESTDB_URL}/exec?{encoded}", timeout=10)
            
            if resp.status_code == 200:
                dataset = resp.json().get('dataset', [])
                existing_days = set()
                for row in dataset:
                    # QuestDB returns date as string like "2026-01-02T00:00:00.000000Z"
                    if row[0]:
                        day_str = str(row[0])[:10]
                        existing_days.add(day_str)

                sym_missing = [d for d in expected_days if d not in existing_days]

                # Use 75% threshold to account for NSE market holidays
                # (weekdays that are NSE holidays will never have data)
                coverage = len(existing_days) / len(expected_days) if expected_days else 0
                if coverage >= 0.75:
                    # Enough data present — skip this symbol (holidays account for the rest)
                    logger.info(f"  ✅ {sym}: {len(existing_days)}/{len(expected_days)} days ({coverage*100:.0f}% coverage) — skipping backfill")
                    continue

                if sym_missing:
                    missing[sym] = sym_missing
            else:
                 logger.warning(f"  ⚠️ QuestDB Query Failed for {sym}: {resp.status_code} - {resp.text}")
                 missing[sym] = expected_days # Assume missing if query fails

        except Exception as e:
            logger.warning(f"  ⚠️ Could not check data for {sym}: {e}")
            missing[sym] = expected_days  # Assume all missing if check fails

    return missing


async def fetch_candle_chunk(session, symbol, to_date, from_date):
    """Fetch a single chunk from Upstox V2 API."""
    encoded_symbol = urllib.parse.quote(symbol)
    url = f"{UPSTOX_API_BASE}/{encoded_symbol}/1minute/{to_date}/{from_date}"
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {UPSTOX_ACCESS_TOKEN}'
    }
    try:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                res_json = await response.json()
                return res_json.get('data', {}).get('candles', [])
            elif response.status == 401:
                logger.error("❌ Upstox API: 401 Unauthorized — Token expired")
                return None
            elif response.status == 429:
                logger.warning("⚠️ Rate limited (429)! Waiting 60s before retry...")
                await asyncio.sleep(60)
                return []
            else:
                text = await response.text()
                logger.warning(f"  Upstox API error {response.status}: {text[:200]}")
                return []
    except Exception as e:
        logger.warning(f"  Network error fetching {symbol}: {e}")
        return []


async def backfill_symbol(session, qdb_conn, symbol, missing_dates):
    """Backfill missing dates for a single symbol."""
    if not missing_dates:
        return 0

    name = KNOWN_STOCKS.get(symbol, symbol)
    total_saved = 0

    # Group consecutive missing dates into date ranges
    missing_dts = sorted([datetime.strptime(d, "%Y-%m-%d") for d in missing_dates])
    ranges = []
    if missing_dts:
        range_start = missing_dts[0]
        range_end = missing_dts[0]

        for dt in missing_dts[1:]:
            if (dt - range_end).days <= 3:  # Group dates within 3 days (skipping weekends)
                range_end = dt
            else:
                ranges.append((range_start, range_end))
                range_start = dt
                range_end = dt
        ranges.append((range_start, range_end))

    for r_start, r_end in ranges:
        # Split each range into 30-day chunks to satisfy Upstox API limits
        current_to = r_end
        while current_to >= r_start:
            current_from = max(r_start, current_to - timedelta(days=25))
            
            from_str = current_from.strftime('%Y-%m-%d')
            to_str = current_to.strftime('%Y-%m-%d')
            logger.info(f"  📥 Backfilling {name}: {from_str} → {to_str}...")

            candles = await fetch_candle_chunk(session, symbol, to_str, from_str)

            if candles is None:  # Auth error
                return -1

            if candles:
                cur = qdb_conn.cursor()
                for c in candles:
                    cur.execute("""
                        INSERT INTO ohlc (timestamp, symbol, timeframe, open, high, low, close, volume)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (c[0], symbol, "1m", c[1], c[2], c[3], c[4], c[5]))
                qdb_conn.commit()
                cur.close()
                total_saved += len(candles)
                logger.info(f"  ✅ {name}: {len(candles)} candles saved & committed")

            current_to = current_from - timedelta(days=1)
            await asyncio.sleep(BACKFILL_DELAY_CHUNKS)

    return total_saved


async def auto_backfill(symbols, start_date, end_date):
    """
    Main auto-backfill routine. Checks for missing data and fills gaps.
    Called before the backtest runs.
    """
    if not UPSTOX_ACCESS_TOKEN or len(UPSTOX_ACCESS_TOKEN) < 10:
        logger.warning("⚠️ UPSTOX_ACCESS_TOKEN not set — skipping auto-backfill")
        return

    logger.info("=" * 60)
    logger.info("🔍 AUTO-BACKFILL: Checking for missing data...")
    logger.info(f"   Symbols: {len(symbols)} | Range: {start_date} → {end_date}")
    logger.info("=" * 60)

    # Check which dates are missing for each symbol
    missing = find_missing_dates(symbols, start_date, end_date)

    if not missing:
        logger.info("✅ All data present — no backfill needed!")
        return

    total_missing = sum(len(dates) for dates in missing.values())
    logger.info(f"📊 Found {total_missing} missing stock-days across {len(missing)} symbols")
    for sym, dates in missing.items():
        name = KNOWN_STOCKS.get(sym, sym)
        logger.info(f"   {name}: {len(dates)} days missing")

    # Connect to QuestDB for writes
    qdb_conn = get_qdb_conn()
    if not qdb_conn:
        logger.error("❌ Cannot connect to QuestDB — skipping backfill")
        return

    # Backfill each symbol
    results = {}
    async with aiohttp.ClientSession() as session:
        for i, (sym, dates) in enumerate(missing.items()):
            name = KNOWN_STOCKS.get(sym, sym)
            logger.info(f"\n[{i+1}/{len(missing)}] Backfilling {name}...")

            count = await backfill_symbol(session, qdb_conn, sym, dates)

            if count == -1:
                logger.error("❌ API auth failed — stopping backfill")
                break

            results[name] = count

            if i < len(missing) - 1:
                await asyncio.sleep(BACKFILL_DELAY_STOCKS)

    qdb_conn.close()

    # Summary
    total = sum(results.values())
    logger.info("=" * 60)
    logger.info(f"📊 BACKFILL COMPLETE: {total:,} candles added")
    for name, count in results.items():
        status = f"✅ {count:,} candles" if count > 0 else "⏭️ No new data"
        logger.info(f"   {name:15s} → {status}")
    logger.info("=" * 60)

    # POST-BACKFILL VERIFICATION: Confirm data actually persisted
    if total > 0:
        try:
            for sym in list(missing.keys())[:3]:  # Verify first 3 symbols
                name = KNOWN_STOCKS.get(sym, sym)
                verify_query = f"SELECT count() FROM ohlc WHERE symbol = '{sym}'"
                encoded = urllib.parse.urlencode({"query": verify_query})
                resp = requests.get(f"{QUESTDB_URL}/exec?{encoded}", timeout=10)
                if resp.status_code == 200:
                    count = resp.json().get('dataset', [[0]])[0][0]
                    logger.info(f"  🔍 VERIFY {name}: {count} total rows in QuestDB")
                else:
                    logger.warning(f"  ⚠️ Verification query failed for {name}")
        except Exception as e:
            logger.warning(f"  ⚠️ Post-backfill verification error: {e}")


def scan_market(date_str, selection_func=None):
    """
    Mimic Scanner Service: Fetch stocks by Momentum/RS from QuestDB.
    Passes candidates to selection_func if provided, otherwise returns top 5.
    """
    try:
        # 1. Get Nifty 50 Performance (Reference)
        nifty_query = f"SELECT first(open), last(close) FROM ohlc WHERE symbol = 'NSE_INDEX|Nifty 50' AND timestamp >= '{date_str}T03:45:00.000000Z' AND timestamp <= '{date_str}T04:00:00.000000Z'"
        nifty_perf = 0.0
        resp = requests.get(f"{QUESTDB_URL}/exec?query={urllib.parse.quote(nifty_query)}")
        if resp.status_code == 200:
            dataset = resp.json().get('dataset', [])
            if dataset and dataset[0][0] and dataset[0][1]:
                 nifty_perf = (dataset[0][1] - dataset[0][0]) / dataset[0][0] * 100
        
        # 2. Scan Stocks
        query = f"""
        SELECT symbol, first(open), last(close), max(high) - min(low), sum(volume)
        FROM ohlc WHERE timestamp >= '{date_str}T03:45:00.000000Z' AND timestamp <= '{date_str}T04:00:00.000000Z'
        AND symbol != 'NSE_INDEX|Nifty 50'
        GROUP BY symbol
        """
        encoded = urllib.parse.urlencode({"query": query})
        resp = requests.get(f"{QUESTDB_URL}/exec?{encoded}")
        
        scored = []
        if resp.status_code == 200:
             dataset = resp.json().get('dataset', [])
             for row in dataset:
                 sym, op, cp, dr, vol = row
                 if op and op > 0 and vol > 100000:
                     perf = (cp - op) / op * 100
                     rs = perf - nifty_perf
                     score = abs(rs) * math.log10(vol)
                     scored.append({"symbol": sym, "score": score})
                     
        # Hand over to user's selection function if provided
        if selection_func and callable(selection_func):
            try:
                # User function expects a list of dicts with 'symbol' and 'score'
                selected = selection_func(scored)
                # Ensure it returns symbols
                if selected and isinstance(selected[0], dict):
                    top = selected
                else:
                    # If it returned strings, wrap back into dicts for persistence
                    symbol_set = set(selected)
                    top = [s for s in scored if s['symbol'] in symbol_set]
            except Exception as e:
                logger.error(f"User Selection Function Failed: {e}. Falling back to top 5.")
                top = sorted(scored, key=lambda x: x['score'], reverse=True)[:5]
        else:
            # Default: Top 5
            top = sorted(scored, key=lambda x: x['score'], reverse=True)[:5]
        
        # Persist to Postgres
        try:
             pg_conn = get_db_connection()
             pg_cur = pg_conn.cursor()
             
             for item in top:
                 pg_cur.execute("""
                     INSERT INTO backtest_universe (run_id, date, symbol, score)
                     VALUES (%s, %s, %s, %s)
                     ON CONFLICT (run_id, date, symbol) DO NOTHING
                 """, (RUN_ID, date_str, item['symbol'], item['score']))
             
             pg_conn.commit()
             pg_cur.close()
             pg_conn.close()
             logger.info(f"💾 Saved {len(top)} scanned symbols to DB for {date_str}")
        except Exception as e:
             logger.error(f"Failed to save scanner results: {e}")

        return [x['symbol'] for x in top]
        
    except Exception as e:
        logger.error(f"Scanner Logic Failed: {e}")
        return []

def fetch_historical_data(symbol, start_date, end_date, timeframe='1m'):
    """Fetch OHLC candles from QuestDB"""
    conn = get_qdb_conn()
    if not conn: return []
    cur = conn.cursor()
    
    query = """
        SELECT timestamp, open, high, low, close, volume
        FROM ohlc
        WHERE symbol = %s
          AND timeframe = %s
          AND timestamp >= %s
          AND timestamp < %s
        ORDER BY timestamp ASC
    """
    
    # Format dates to ISO for QuestDB
    # If already formatted, this might be redundant but safe
    try:
        if 'T' not in start_date:
            start_date = f"{start_date}T00:00:00.000000Z"
        if 'T' not in end_date:
            # Add +1 day to make end date inclusive (user expects Jan 9 to include Jan 9 data)
            from datetime import datetime as dt, timedelta
            end_dt = dt.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            end_date = end_dt.strftime("%Y-%m-%dT00:00:00.000000Z")
    except:
        pass

    # Use explicit cast or string literal approach if bind fails, 
    # but let's try updating the params first.
    # QuestDB via Postgres Wire often needs TIMESTAMP '...' literal or correct string.
    
    cur.execute(query, (symbol, timeframe, start_date, end_date))
    candles = cur.fetchall()
    cur.close()
    conn.close()
    
    logger.info(f"📊 Loaded {len(candles)} candles for {symbol}")
    return candles

def ohlc_to_ticks(timestamp, open_price, high, low, close, volume):
    """
    Convert OHLC to Ticks with direction-aware price path.
    Bullish candle (close > open): O → L → H → C
    Bearish candle (close < open): O → H → L → C
    
    Pre-computes _dt, _hour, _minute, _date_int fields for the engine's
    fast path (ProcessTickFast) so no datetime math is needed per tick.
    """
    base_ts = int(timestamp.timestamp() * 1000)
    vol_per_tick = int(volume / 4)
    
    # Pre-compute datetime fields ONCE per candle (shared by all 4 ticks)
    dt_obj = timestamp
    date_int = dt_obj.year * 10000 + dt_obj.month * 100 + dt_obj.day
    hour = dt_obj.hour
    minute = dt_obj.minute
    
    # Base dict fields (pre-computed, avoids per-tick datetime math)
    common = {'_dt': dt_obj, '_date_int': date_int, '_hour': hour, '_minute': minute}
    
    # Open (always first)
    t_open  = {'ltp': open_price, 'v': vol_per_tick, 'timestamp': base_ts}
    t_open.update(common)
    
    if close >= open_price:
        # Bullish: O → L → H → C
        t_mid1 = {'ltp': low,  'v': vol_per_tick, 'timestamp': base_ts + 15000}
        t_mid2 = {'ltp': high, 'v': vol_per_tick, 'timestamp': base_ts + 30000}
    else:
        # Bearish: O → H → L → C
        t_mid1 = {'ltp': high, 'v': vol_per_tick, 'timestamp': base_ts + 15000}
        t_mid2 = {'ltp': low,  'v': vol_per_tick, 'timestamp': base_ts + 30000}
    t_mid1.update(common)
    t_mid2.update(common)
    
    # Close (always last)
    t_close = {'ltp': close, 'v': vol_per_tick, 'timestamp': base_ts + 45000}
    t_close.update(common)
    
    return [t_open, t_mid1, t_mid2, t_close]

def run(symbol, start, end, initial_cash, speed="fast"):
    if not STRATEGY_NAME:
        logger.error("STRATEGY_NAME env var not set")
        sys.exit(1)

    logger.info(f"🚀 Starting Backtest Runner: {RUN_ID} for {STRATEGY_NAME}")
    
    # Parse clean date strings for backfill/scanner
    start_clean = start.split('T')[0] if 'T' in start else start
    end_clean = end.split('T')[0] if 'T' in end else end
    
    # ===== STEP 1: Initialize Engine & Load Strategy =====
    try:
        pg_conn = get_db_connection()
        pg_cur = pg_conn.cursor()
        pg_cur.execute(f"DELETE FROM backtest_portfolios WHERE run_id = %s", (RUN_ID,))
        pg_cur.execute(f"INSERT INTO backtest_portfolios (user_id, run_id, balance, equity) VALUES (%s, %s, %s, %s)", ('default_user', RUN_ID, initial_cash, initial_cash))
        pg_cur.execute("DELETE FROM backtest_positions WHERE portfolio_id IN (SELECT id FROM backtest_portfolios WHERE run_id = %s)", (RUN_ID,))
        pg_conn.commit()
        pg_cur.close()
        pg_conn.close()
        logger.info(f"💰 Initialized Backtest Portfolio: ₹{initial_cash}")
    except Exception as e:
        logger.error(f"Failed to initialize backtest DB: {e}")

    engine = AlgorithmEngine(run_id=RUN_ID, backtest_mode=True, speed=speed, trading_mode=TRADING_MODE)
    
    try:
        module_path, class_name = STRATEGY_NAME.rsplit('.', 1)
        engine.LoadAlgorithm(module_path, class_name)
    except Exception as e:
        logger.error(f"Failed to load strategy: {e}")
        sys.exit(1)

    # Initialize Strategy (adds static symbols via AddEquity)
    try:
        engine.Initialize()
    except Exception as e:
        import traceback
        logger.error(f"STRATEGY_ERROR: Error in strategy Initialize(): {e}\n{traceback.format_exc()}")
        sys.exit(1)
    
    # Read scanner frequency from engine (set by strategy in Initialize)
    scanner_frequency_minutes = getattr(engine, 'ScannerFrequency', None)
    if scanner_frequency_minutes:
        logger.info(f"⏱️ Scanner frequency: every {scanner_frequency_minutes} minutes")
    
    # Override Cash & Set Stats Baseline
    engine.SetInitialCapital(initial_cash)
    engine.Algorithm.Portfolio['Cash'] = initial_cash
    engine.Algorithm.Portfolio['TotalPortfolioValue'] = initial_cash
    
    # ===== STEP 2: First-Pass Auto-backfill (Primary + Static Subscriptions) =====
    # We need these to run the scanner or the first day of the loop
    initial_symbols = set([symbol] + list(engine.SubscriptionManager.Subscriptions.keys()))
    try:
        logger.info("📡 Checking initial symbols for backfill...")
        asyncio.run(auto_backfill(list(initial_symbols), start_clean, end_clean))
    except Exception as e:
        logger.warning(f"⚠️ Initial auto-backfill error: {e}")

    # ===== STEP 3: Universe Selection — Scan each trading day =====
    universe_symbols = set(initial_symbols)
    if engine.UniverseSettings:
        logger.info("🌌 Dynamic Universe Requested. Scanning each trading day...")
        try:
            start_dt = datetime.strptime(start_clean, "%Y-%m-%d")
            end_dt = datetime.strptime(end_clean, "%Y-%m-%d")

            current = start_dt
            while current <= end_dt:
                if current.weekday() < 5:
                    date_str = current.strftime("%Y-%m-%d")
                    scanned = scan_market(date_str, selection_func=engine.UniverseSettings)
                    if scanned:
                        universe_symbols.update(scanned)
                        logger.info(f"🌌 Day {date_str}: Scanned {len(scanned)} stocks")
                current += timedelta(days=1)
            
            # Second-Pass Auto-backfill (Capture dynamically added symbols)
            newly_added = universe_symbols - initial_symbols
            if newly_added:
                logger.info(f"📡 Backfilling {len(newly_added)} symbols discovered by scanner...")
                asyncio.run(auto_backfill(list(newly_added), start_clean, end_clean))
                
        except Exception as e:
            logger.error(f"Scan/Second-backfill Failed: {e}")
    else:
        universe_symbols = initial_symbols

    universe_symbols = list(universe_symbols)


    # 5. Fetch & Process Data Day-by-Day (Streaming — constant memory)
    # Instead of 8M+ ticks in memory, we process one trading day at a time (~35K ticks).
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import time as _time_br

    def _fetch_candles_for_date(sym, date_str):
        """Fetch one symbol's candles for a single date from QuestDB."""
        conn = get_qdb_conn()
        if not conn: return sym, []
        cur = conn.cursor()
        start_ts = f"{date_str}T00:00:00.000000Z"
        # Next day for exclusive upper bound
        from datetime import datetime as dt2, timedelta as td2
        next_day = (dt2.strptime(date_str, "%Y-%m-%d") + td2(days=1)).strftime("%Y-%m-%dT00:00:00.000000Z")
        cur.execute("""
            SELECT timestamp, open, high, low, close, volume
            FROM ohlc
            WHERE symbol = %s AND timeframe = '1m'
              AND timestamp >= %s AND timestamp < %s
            ORDER BY timestamp ASC
        """, (sym, start_ts, next_day))
        candles = cur.fetchall()
        cur.close()
        conn.close()
        return sym, candles

    # Generate trading dates (skip weekends)
    start_dt = datetime.strptime(start_clean, "%Y-%m-%d")
    end_dt = datetime.strptime(end_clean, "%Y-%m-%d")
    trading_dates = []
    current = start_dt
    while current <= end_dt:
        if current.weekday() < 5:  # Mon-Fri
            trading_dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)

    if not trading_dates:
        logger.warning("⚠️ No trading dates in range. Exiting.")
        return

    logger.info(f"📅 Streaming backtest: {len(trading_dates)} trading days, {len(universe_symbols)} symbols")

    # ── Open persistent session (zero per-trade connections) ──
    _has_session = hasattr(engine.Exchange, 'begin_session')
    if _has_session:
        engine.Exchange.begin_session(initial_cash)

    import time as _time
    # Inject Initial Equity Point
    first_date_str = trading_dates[0]
    first_dt = datetime.strptime(first_date_str, "%Y-%m-%d") - timedelta(seconds=1)
    engine.EquityCurve.append({'timestamp': first_dt, 'equity': initial_cash})

    # Enable turbo mode
    engine.Algorithm._turbo_mode = True
    engine.SyncPortfolio()

    _t0 = _time.time()
    total_ticks = 0
    max_workers = min(len(universe_symbols), 16)

    for day_idx, date_str in enumerate(trading_dates):
        # Fetch this day's candles for all symbols in parallel
        day_ticks = []
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_fetch_candles_for_date, sym, date_str): sym for sym in universe_symbols}
            for future in as_completed(futures):
                sym, candles = future.result()
                if candles:
                    for c in candles:
                        ts, o, h, l, c_price, v = c
                        for t in ohlc_to_ticks(ts, o, h, l, c_price, v):
                            t['symbol'] = sym
                            day_ticks.append(t)

        if not day_ticks:
            continue  # Holiday or no data

        # Sort this day's ticks chronologically
        day_ticks.sort(key=itemgetter('timestamp'))

        # Feed to engine and process
        engine.SetBacktestData(day_ticks)
        engine._run_python_turbo_path()
        total_ticks += len(day_ticks)

        # Discard — free memory immediately
        del day_ticks

        # Progress report every 20 days
        if (day_idx + 1) % 20 == 0 or day_idx == len(trading_dates) - 1:
            elapsed = _time.time() - _t0
            tps = total_ticks / elapsed if elapsed > 0 else 0
            logger.info(f"📊 Day {day_idx+1}/{len(trading_dates)} done | "
                        f"{total_ticks:,} ticks in {elapsed:.1f}s ({tps:,.0f} tps)")

    _elapsed = _time.time() - _t0
    _tps = total_ticks / _elapsed if _elapsed > 0 else 0
    logger.info(f"⚡ Streaming tick loop done: {total_ticks:,} ticks in {_elapsed:.2f}s = {_tps:,.0f} ticks/sec")

    # ── Liquidate open positions for accurate PnL stats ──
    logger.info("⏱️ Streaming Complete. Auto-liquidating open positions...")
    engine.Liquidate()

    # ── Flush all buffered orders + positions to DB ──
    if _has_session:
        engine.Algorithm.Portfolio['Cash'] = engine.Exchange._bt_balance
        engine.Exchange.flush_session()

    # Finalize Equity Curve
    engine.SyncPortfolio()
    equity = engine.Algorithm.Portfolio.get('TotalPortfolioValue', 0.0)
    engine.EquityCurve.append({'timestamp': datetime.now(), 'equity': equity})
    logger.info("✅ Streaming backtest complete.")

    # Save Statistics
    try:
        engine.SaveStatistics()
    except Exception as e:
        import traceback
        logger.error(f"STRATEGY_ERROR: Error saving statistics: {e}\n{traceback.format_exc()}")

    logger.info("🏁 Backtest Runner Finished.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--cash", type=float, default=100000.0)
    parser.add_argument("--speed", type=str, default="fast")
    args = parser.parse_args()
    
    run(args.symbol, args.start, args.end, args.cash, args.speed)
