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

# Config
RUN_ID = os.getenv('RUN_ID', 'test_run')
STRATEGY_NAME = os.getenv('STRATEGY_NAME')
QUESTDB_URL = os.getenv('QUESTDB_URL', 'http://questdb_tsdb:9000')
UPSTOX_ACCESS_TOKEN = os.getenv('UPSTOX_ACCESS_TOKEN', '')
UPSTOX_API_BASE = "https://api.upstox.com/v3/historical-candle"

# Known stocks for backfill (ISIN -> Name mapping)
KNOWN_STOCKS = {
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
    "NSE_EQ|INE775A01035": "TATAMOTORS",
}

# Rate limit config (safe margin below Upstox limits)
BACKFILL_DELAY_CHUNKS = 1.5   # seconds between API calls
BACKFILL_DELAY_STOCKS = 3.0   # seconds between stocks

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
        SELECT timestamp FROM ohlc 
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
                
                # Loose check: If we have >90% of data, assume it's fine (holidays etc)
                # But typically we want exact matches. 
                # Let's log if we find *some* data but not all.
                if len(existing_days) > 0 and len(sym_missing) > 0:
                     logger.info(f"  ℹ️ {sym}: Found {len(existing_days)} days, Missing {len(sym_missing)} days")

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
    """Fetch a single chunk from Upstox V3 API."""
    encoded_symbol = urllib.parse.quote(symbol)
    url = f"{UPSTOX_API_BASE}/{encoded_symbol}/minutes/1/{to_date}/{from_date}"
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
                logger.warning("⚠️ Rate limited! Waiting 60s...")
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

    # Group consecutive missing dates into date ranges for efficient API calls
    missing_dts = sorted([datetime.strptime(d, "%Y-%m-%d") for d in missing_dates])
    ranges = []
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
        from_str = r_start.strftime('%Y-%m-%d')
        to_str = r_end.strftime('%Y-%m-%d')
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


def scan_market(date_str, top_n=5):
    """
    Mimic Scanner Service: Fetch top N stocks by Momentum/RS from QuestDB.
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
                     
        # Top N
        top = sorted(scored, key=lambda x: x['score'], reverse=True)[:top_n]
        
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

def get_qdb_conn():
    """Connect to QuestDB"""
    # Assuming we are in the same docker network
    try:
        conn = psycopg2.connect(
            host=os.getenv("QUESTDB_HOST", "questdb_tsdb"),
            port=8812,
            user="admin",
            password="quest",
            database="qdb"
        )
        conn.autocommit = True
        return conn
    except Exception as e:
        logger.error(f"QuestDB Connection Error: {e}")
        return None

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
    This reduces directional bias in backtests.
    """
    ticks = []
    base_ts = int(timestamp.timestamp() * 1000)
    vol_per_tick = int(volume / 4)
    
    # Open (always first)
    ticks.append({"ltp": open_price, "v": vol_per_tick, "timestamp": base_ts})
    
    if close >= open_price:
        # Bullish: O → L → H → C (dips then rallies)
        ticks.append({"ltp": low, "v": vol_per_tick, "timestamp": base_ts + 15000})
        ticks.append({"ltp": high, "v": vol_per_tick, "timestamp": base_ts + 30000})
    else:
        # Bearish: O → H → L → C (rallies then dips)
        ticks.append({"ltp": high, "v": vol_per_tick, "timestamp": base_ts + 15000})
        ticks.append({"ltp": low, "v": vol_per_tick, "timestamp": base_ts + 30000})
    
    # Close (always last)
    ticks.append({"ltp": close, "v": vol_per_tick, "timestamp": base_ts + 45000})
    
    return ticks

def run(symbol, start, end, initial_cash, speed="fast"):
    if not STRATEGY_NAME:
        logger.error("STRATEGY_NAME env var not set")
        sys.exit(1)

    logger.info(f"🚀 Starting Backtest Runner: {RUN_ID} for {STRATEGY_NAME}")
    
    # Parse clean date strings for backfill/scanner
    start_clean = start.split('T')[0] if 'T' in start else start
    end_clean = end.split('T')[0] if 'T' in end else end
    
    # ===== STEP 1: Auto-backfill missing data =====
    all_known_symbols = list(KNOWN_STOCKS.keys())
    try:
        asyncio.run(auto_backfill(all_known_symbols, start_clean, end_clean))
    except Exception as e:
        logger.warning(f"⚠️ Auto-backfill encountered an error (continuing): {e}")
    
    # ===== STEP 2: Initialize Engine =====
    engine = AlgorithmEngine(run_id=RUN_ID, backtest_mode=True, speed=speed)
    
    # Load Strategy
    try:
        module_path, class_name = STRATEGY_NAME.rsplit('.', 1)
        engine.LoadAlgorithm(module_path, class_name)
    except Exception as e:
        logger.error(f"Failed to load strategy: {e}")
        sys.exit(1)

    # Initialize
    engine.Initialize()
    
    # Override Cash
    engine.Algorithm.Portfolio['Cash'] = initial_cash
    engine.Algorithm.Portfolio['TotalPortfolioValue'] = initial_cash
    
    # Read scanner frequency from engine (set by strategy in Initialize)
    scanner_frequency_minutes = getattr(engine, 'ScannerFrequency', None)
    if scanner_frequency_minutes:
        logger.info(f"⏱️ Scanner frequency: every {scanner_frequency_minutes} minutes")
    
    # ===== STEP 3: Universe Selection — Scan each trading day =====
    universe_symbols = set()
    if engine.UniverseSettings:
        logger.info("🌌 Dynamic Universe Requested. Scanning each trading day...")
        try:
            start_dt = datetime.strptime(start_clean, "%Y-%m-%d")
            end_dt = datetime.strptime(end_clean, "%Y-%m-%d")

            current = start_dt
            while current <= end_dt:
                # Skip weekends (Sat=5, Sun=6) — NSE is closed
                if current.weekday() < 5:
                    date_str = current.strftime("%Y-%m-%d")
                    scanned = scan_market(date_str)
                    if scanned:
                        universe_symbols.update(scanned)
                        logger.info(f"🌌 Day {date_str}: Scanned {len(scanned)} stocks")
                    else:
                        logger.info(f"📅 Day {date_str}: No scanner results (holiday?)")
                current += timedelta(days=1)

            if universe_symbols:
                logger.info(f"🌌 Total Universe: {len(universe_symbols)} unique symbols across all days")
            else:
                logger.warning("⚠️ Scan returned no results for any day. Fallback to provided symbol.")
                universe_symbols = {symbol}
        except Exception as e:
            logger.error(f"Scan Failed: {e}")
            universe_symbols = {symbol}
    else:
        universe_symbols = {symbol}

    universe_symbols = list(universe_symbols)


    # 5. Fetch Data for Universe
    all_ticks = []
    
    for sym in universe_symbols:
        logger.info(f"📥 Fetching Data for {sym}...")
        candles = fetch_historical_data(sym, start, end)
        if not candles: continue
        
        for c in candles:
             ts, o, h, l, c_price, v = c
             candle_ticks = ohlc_to_ticks(ts, o, h, l, c_price, v)
             for t in candle_ticks:
                 t['symbol'] = sym
                 all_ticks.append(t)
                 
    # Sort by Timestamp to simulate market playback
    all_ticks.sort(key=lambda x: x['timestamp'])
    
    if not all_ticks:
        logger.warning("⚠️ No data found for any symbol in universe. Exiting Backtest.")
        return
    
    logger.info(f"✅ Prepared {len(all_ticks)} ticks for simulation.")

    # Load Data
    engine.SetBacktestData(all_ticks)
    
    # Run
    engine.Run()

    # Save Statistics (Sharpe, Drawdown, etc.)
    engine.SaveStatistics()
    
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
