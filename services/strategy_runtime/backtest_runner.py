import os
import logging
import sys
import argparse
import time
import psycopg2
from datetime import datetime
from engine import AlgorithmEngine

import requests
import urllib.parse
import math

# Config
RUN_ID = os.getenv('RUN_ID', 'test_run')
STRATEGY_NAME = os.getenv('STRATEGY_NAME')
QUESTDB_URL = os.getenv('QUESTDB_URL', 'http://questdb_tsdb:9000')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("BacktestRunner")

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
            end_date = f"{end_date}T00:00:00.000000Z"
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
    """Convert OHLC to Ticks (Mocking tick data from candles)"""
    ticks = []
    base_ts = int(timestamp.timestamp() * 1000)
    vol_per_tick = int(volume / 4)
    
    # Open
    ticks.append({"ltp": open_price, "v": vol_per_tick, "timestamp": base_ts})
    # High
    ticks.append({"ltp": high, "v": vol_per_tick, "timestamp": base_ts + 15000})
    # Low
    ticks.append({"ltp": low, "v": vol_per_tick, "timestamp": base_ts + 30000})
    # Close
    ticks.append({"ltp": close, "v": vol_per_tick, "timestamp": base_ts + 45000})
    
    return ticks

def run(symbol, start, end, initial_cash):
    if not STRATEGY_NAME:
        logger.error("STRATEGY_NAME env var not set")
        sys.exit(1)

    logger.info(f"🚀 Starting Backtest Runner: {RUN_ID} for {STRATEGY_NAME}")
    
    # 3. Initialize Engine
    engine = AlgorithmEngine(run_id=RUN_ID, backtest_mode=True)
    
    # Verify/Set Cash (Override default)
    # Default engine uses DB sync. We might want to inject initial cash if DB is empty for this RunID.
    # Engine.SyncPortfolio() checks DB.
    # Since this is a new RunID, DB will be empty.
    # Engine initializes to 5000.0. User might want more.
    # We should probably update DB *before* initialization or hack Engine.
    # Hack: engine.Algorithm.Portfolio['Cash'] = initial_cash AFTER Init.
    
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
    
    # 4. Universe Selection
    universe_symbols = [symbol]
    if engine.UniverseSettings:
        logger.info("🌌 Dynamic Universe Requested. Scanning Market...")
        try:
             # Run Scan for Start Date
             scanned = scan_market(start)
             if scanned:
                 universe_symbols = scanned
                 logger.info(f"🌌 Universe Selected: {universe_symbols}")
             else:
                 logger.warning("⚠️ Scan returned no results. Fallback to provided symbol.")
        except Exception as e:
             logger.error(f"Scan Failed: {e}")

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
    
    logger.info("🏁 Backtest Runner Finished.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--cash", type=float, default=100000.0)
    args = parser.parse_args()
    
    run(args.symbol, args.start, args.end, args.cash)
