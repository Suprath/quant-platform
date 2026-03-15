"""
Backfiller FastAPI Service
Provides REST API for triggering and monitoring multi-stock data backfill.
"""
import os
import asyncio
import aiohttp
import psycopg2
import urllib.parse
import time
import threading
import uvicorn
from datetime import datetime, timedelta
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from psycopg2 import pool

load_dotenv()

app = FastAPI(title="Backfiller Service")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

API_BASE_URL = "https://api.upstox.com/v2/historical-candle"
# ACCESS_TOKEN read dynamically when needed to prevent blank state on container start
# Safe margin for Free Tier (1 req/s)
DELAY_BETWEEN_CHUNKS = 1.6
DELAY_BETWEEN_STOCKS = 3.2

# Top Nifty 50 stocks
# Multi-Exchange Stock Dictionary (Indices, NSE, BSE)
STOCK_LIST = [
    # --- INDICES ---
    ("NSE_INDEX|Nifty 50", "NIFTY 50 (NSE)"),
    ("NSE_INDEX|Nifty Bank", "BANK NIFTY (NSE)"),
    ("NSE_INDEX|Nifty Fin Service", "FINNIFTY (NSE)"),
    ("BSE_INDEX|SENSEX", "SENSEX (BSE)"),

    # --- NSE BLUECHIPS ---
    ("NSE_EQ|INE002A01018", "RELIANCE (NSE)"),
    ("NSE_EQ|INE467B01029", "TCS (NSE)"),
    ("NSE_EQ|INE040A01034", "HDFCBANK (NSE)"),
    ("NSE_EQ|INE009A01021", "INFY (NSE)"),
    ("NSE_EQ|INE090A01021", "ICICIBANK (NSE)"),
    ("NSE_EQ|INE155A01022", "TATAMOTORS (NSE)"),
    ("NSE_EQ|INE081A01020", "TATASTEEL (NSE)"),
    ("NSE_EQ|INE245A01021", "TATAPOWER (NSE)"),
    ("NSE_EQ|INE192A01025", "TATACONSUM (NSE)"),
    ("NSE_EQ|INE670A01012", "TATAELXSI (NSE)"),
    ("NSE_EQ|INE092A01019", "TATACHEM (NSE)"),
    ("NSE_EQ|INE151A01013", "TATACOMM (NSE)"),
    ("NSE_EQ|INE062A01020", "SBIN (NSE)"),
    ("NSE_EQ|INE154A01025", "ITC (NSE)"),
    ("NSE_EQ|INE238A01034", "AXISBANK (NSE)"),
    ("NSE_EQ|INE030A01027", "HINDUNILVR (NSE)"),
    ("NSE_EQ|INE018A01030", "L&T (NSE)"),
    ("NSE_EQ|INE423A01024", "ADANIENT (NSE)"),
    ("NSE_EQ|INE742F01042", "ADANIPORTS (NSE)"),
    ("NSE_EQ|INE044A01036", "SUNPHARMA (NSE)"),
    ("NSE_EQ|INE326A01037", "ULTRACEMCO (NSE)"),
    ("NSE_EQ|INE101A01026", "M&M (NSE)"),
    ("NSE_EQ|INE208A01029", "ASHOKLEY (NSE)"),
    ("NSE_EQ|INE121A01024", "CHOLAFIN (NSE)"),
    ("NSE_EQ|INE053F01010", "IRFC (NSE)"),
    ("NSE_EQ|INE280A01028", "TITAN (NSE)"),

    # --- BSE BLUECHIPS ---
    ("BSE_EQ|INE002A01018", "RELIANCE (BSE)"),
    ("BSE_EQ|INE467B01029", "TCS (BSE)"),
    ("BSE_EQ|INE040A01034", "HDFCBANK (BSE)"),
    ("BSE_EQ|INE009A01021", "INFY (BSE)"),
    ("BSE_EQ|INE081A01020", "TATASTEEL (BSE)"),
    ("BSE_EQ|INE192A01025", "TATACONSUM (BSE)"),
    ("BSE_EQ|INE245A01021", "TATAPOWER (BSE)"),
    ("BSE_EQ|INE092A01019", "TATACHEM (BSE)"),
    ("BSE_EQ|INE670A01012", "TATAELXSI (BSE)"),
    ("BSE_EQ|INE151A01013", "TATACOMM (BSE)"),
    ("BSE_EQ|INE142M01025", "TATATECH (BSE)"),
    ("BSE_EQ|INE672A01026", "TATAINVEST (BSE)"),
    ("BSE_EQ|INE062A01020", "SBIN (BSE)"),
    ("BSE_EQ|INE154A01025", "ITC (BSE)"),
    ("BSE_EQ|INE030A01027", "HINDUNILVR (BSE)"),
]

# --- Global Progress State ---
backfill_state = {
    "running": False,
    "total_stocks": 0,
    "completed_stocks": 0,
    "current_stock": "",
    "current_stock_progress": 0,  # 0-100 for current stock
    "total_candles": 0,
    "logs": [],
    "error": None,
    "finished": False,
}

def reset_state():
    backfill_state.update({
        "running": False,
        "total_stocks": 0,
        "completed_stocks": 0,
        "current_stock": "",
        "current_stock_progress": 0,
        "total_candles": 0,
        "logs": [],
        "error": None,
        "finished": False,
    })

def add_log(msg):
    backfill_state["logs"].append(msg)
    # Keep last 100 logs
    if len(backfill_state["logs"]) > 100:
        backfill_state["logs"] = backfill_state["logs"][-100:]
    print(msg)


# --- DB Helpers ---
# --- Global Connection Pools ---
_QDB_POOL = None
_PG_POOL = None

def get_qdb_conn():
    global _QDB_POOL
    host = os.getenv("QUESTDB_HOST", "questdb_tsdb")
    if _QDB_POOL is None:
        try:
            _QDB_POOL = pool.ThreadedConnectionPool(1, 10, 
                host=host, port=8812, user="admin", password="quest", database="qdb")
            add_log("✅ Backfiller QuestDB Pool Initialized")
        except Exception as e:
            add_log(f"⚠️ QuestDB Pool Init Failed: {e}")
            return psycopg2.connect(host=host, port=8812, user="admin", password="quest", database="qdb")
    return _QDB_POOL.getconn()

def release_qdb_conn(conn):
    if _QDB_POOL: _QDB_POOL.putconn(conn)
    else: conn.close()

def get_pg_conn():
    global _PG_POOL
    host = os.getenv("POSTGRES_HOST", "postgres_metadata")
    if _PG_POOL is None:
        try:
            _PG_POOL = pool.ThreadedConnectionPool(1, 10,
                host=host, port=5432, user="admin", password="password123", database="quant_platform")
            add_log("✅ Backfiller Postgres Pool Initialized")
        except Exception as e:
            add_log(f"⚠️ Postgres Pool Init Failed: {e}")
            return psycopg2.connect(host=host, port=5432, user="admin", password="password123", database="quant_platform")
    return _PG_POOL.getconn()

def release_pg_conn(conn):
    if _PG_POOL: _PG_POOL.putconn(conn)
    else: conn.close()

def ensure_instruments(stocks):
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS instruments (
            instrument_token VARCHAR(255) PRIMARY KEY, 
            exchange VARCHAR(50),
            segment VARCHAR(50), 
            symbol VARCHAR(50),
            expiry DATE NULL,
            strike DOUBLE PRECISION NULL,
            option_type VARCHAR(10) NULL,
            underlying_symbol VARCHAR(50) NULL,
            lot_size INT NULL
        );""")
        for token, name in stocks:
            # Skip generating dummy equity metadata for Options 
            # (they are populated by instrument_sync job accurately with expiry/strike)
            if token.startswith("NSE_FO|") or token.startswith("BSE_FO|"):
                continue
                
            cur.execute("""INSERT INTO instruments 
                (instrument_token, exchange, segment, symbol, lot_size)
                VALUES (%s, %s, %s, %s, %s) 
                ON CONFLICT (instrument_token) DO UPDATE 
                SET symbol = EXCLUDED.symbol, lot_size = EXCLUDED.lot_size;
            """, (token, "NSE_EQ", "EQUITY", name, 1))
        conn.commit()
        cur.close()
        release_pg_conn(conn)
    except Exception as e:
        add_log(f"⚠️ Instruments error: {e}")

def ensure_schema(conn):
    try:
        cur = conn.cursor()
        # Create tables for standard timeframes
        timeframes = ['1m', '5m', '15m', '30m', '1h', '1d']
        for tf in timeframes:
            table_name = f"ohlc_{tf}"
            cur.execute(f"""CREATE TABLE IF NOT EXISTS {table_name} (
                timestamp TIMESTAMP, symbol SYMBOL, timeframe SYMBOL,
                open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume LONG
            ) TIMESTAMP(timestamp) PARTITION BY DAY;""")
        
        # Keep legacy 'ohlc' table for backwards compatibility
        cur.execute("""CREATE TABLE IF NOT EXISTS ohlc (
            timestamp TIMESTAMP, symbol SYMBOL, timeframe SYMBOL,
            open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume LONG
        ) TIMESTAMP(timestamp) PARTITION BY DAY;""")
        
        conn.commit()
        cur.close()
    except Exception as e:
        conn.rollback()
        add_log(f"⚠️ Schema Error: {e}")


# --- API Fetch ---
async def fetch_candle_chunk(session, symbol, unit, interval, to_date, from_date, access_token):
    encoded = urllib.parse.quote(symbol)
    # Upstox API V2 interval format: 'day', '1minute', '30minute'
    api_interval = "day" if str(unit).lower() == "day" else f"{interval}minute"
    url = f"{API_BASE_URL}/{encoded}/{api_interval}/{to_date}/{from_date}"
    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {access_token}'}
    try:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                return data.get('data', {}).get('candles', [])
            elif response.status in (401, 403):
                add_log(f"❌ Auth failed ({response.status}). Token expired?")
                return None
            elif response.status == 429:
                add_log("⚠️ Rate limited (429)! Waiting 60 seconds before retry...")
                await asyncio.sleep(60)
                return []
            else:
                try:
                    error_data = await response.json()
                    # Upstox API V2 error structure check
                    msg = error_data.get('errors', [{}])[0].get('message', 'Unknown API Error')
                    add_log(f"   ⚠️ API Error ({response.status}) for {symbol}: {msg}")
                except:
                    add_log(f"   ⚠️ API Error: {response.status} for {symbol}")
                
                # If resource not found (404) or bad request (400), return empty list so loop continues
                if response.status in (400, 404):
                    return []
                return None
    except Exception as e:
        add_log(f"   Network error fetching {symbol}: {e}")
        return []


# --- Core Backfill Logic ---
async def run_backfill(stocks, start_str, end_str, unit, interval, access_token, run_noise_filter=False):
    backfill_state["running"] = True
    backfill_state["total_stocks"] = len(stocks)
    backfill_state["finished"] = False

    start_dt = datetime.strptime(start_str, '%Y-%m-%d')
    end_dt = datetime.strptime(end_str, '%Y-%m-%d')

    conn = get_qdb_conn()
    ensure_schema(conn)
    ensure_instruments(stocks)
    cur = conn.cursor()

    add_log(f"🚀 Starting backfill: {len(stocks)} stocks, {start_str} → {end_str}")

    async with aiohttp.ClientSession() as session:
        for i, (symbol, name) in enumerate(stocks):
            backfill_state["current_stock"] = name
            backfill_state["current_stock_progress"] = 0
            add_log(f"[{i+1}/{len(stocks)}] 📈 Downloading {name}...")

            # Calculate total chunks for progress
            total_days = (end_dt - start_dt).days
            total_chunks = max(1, total_days // 25 + 1)
            chunk_idx = 0

            current_to = end_dt
            stock_candles = 0

            while current_to > start_dt:
                current_from = max(start_dt, current_to - timedelta(days=25))
                to_s = current_to.strftime('%Y-%m-%d')
                from_s = current_from.strftime('%Y-%m-%d')

                # Check if we already have data for this chunk in QuestDB
                check_from = f"{from_s}T00:00:00.000000Z"
                # For `to_s`, we add one day to make the upper bound inclusive for the entire `to_s` date
                check_to = f"{(current_to + timedelta(days=1)).strftime('%Y-%m-%d')}T00:00:00.000000Z"
                
                try:
                    timeframe_str = f"{interval}{unit[0]}"
                    target_table = f"ohlc_{timeframe_str}"
                    query = f"""
                        SELECT count(*) FROM {target_table} 
                        WHERE symbol = '{symbol}' 
                          AND timeframe = '{timeframe_str}'
                          AND timestamp >= to_timestamp('{check_from}', 'yyyy-MM-ddTHH:mm:ss.SSSUUUZ')
                          AND timestamp < to_timestamp('{check_to}', 'yyyy-MM-ddTHH:mm:ss.SSSUUUZ')
                    """
                    cur.execute(query)
                    existing_count = cur.fetchone()[0]
                except Exception as e:
                    # Fallback to legacy ohlc if target doesn't exist yet
                    try:
                        query = f"SELECT count(*) FROM ohlc WHERE symbol = '{symbol}' AND timeframe = '{timeframe_str}' AND timestamp >= to_timestamp('{check_from}', 'yyyy-MM-ddTHH:mm:ss.SSSUUUZ') AND timestamp < to_timestamp('{check_to}', 'yyyy-MM-ddTHH:mm:ss.SSSUUUZ')"
                        cur.execute(query)
                        existing_count = cur.fetchone()[0]
                    except:
                        add_log(f"   ⚠️ DB count check failed: {e}")
                        existing_count = 0

                if existing_count > 0:
                    add_log(f"   ⏭️ Skipping {from_s} → {to_s} (Found {existing_count} candles in DB)")
                    chunk_idx += 1
                    backfill_state["current_stock_progress"] = min(100, int(chunk_idx / total_chunks * 100))
                    current_to = current_from - timedelta(days=1)
                    continue

                candles = await fetch_candle_chunk(session, symbol, unit, interval, to_s, from_s, access_token)

                if candles is None:
                    backfill_state["error"] = f"API request failed for {name} (Auth or Server Error)"
                    backfill_state["running"] = False
                    cur.close()
                    release_qdb_conn(conn)
                    return

                if candles:
                    timeframe_str = f"{interval}{unit[0]}"
                    target_table = f"ohlc_{timeframe_str}"
                    for c in candles:
                        cur.execute(f"""INSERT INTO {target_table} (timestamp, symbol, timeframe, open, high, low, close, volume)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                            (c[0], symbol, timeframe_str, c[1], c[2], c[3], c[4], c[5]))
                    conn.commit()
                    stock_candles += len(candles)

                chunk_idx += 1
                backfill_state["current_stock_progress"] = min(100, int(chunk_idx / total_chunks * 100))
                current_to = current_from - timedelta(days=1)
                await asyncio.sleep(DELAY_BETWEEN_CHUNKS)

            backfill_state["completed_stocks"] = i + 1
            backfill_state["total_candles"] += stock_candles
            add_log(f"   ✅ {name}: {stock_candles} candles saved")

            if i < len(stocks) - 1:
                await asyncio.sleep(DELAY_BETWEEN_STOCKS)

    cur.close()
    release_qdb_conn(conn)
    backfill_state["running"] = False
    backfill_state["finished"] = True
    add_log(f"🏁 Backfill complete! Total: {backfill_state['total_candles']} candles. Noise Filter Toggle: {run_noise_filter}")

    # Trigger Noise Filter for the backfilled range if requested
    if run_noise_filter:
        add_log(f"📡 Triggering KIRA Noise Filter for {len(stocks)} symbols...")
        try:
            noise_filter_url = "http://noise_filter:8000/generate"
            import requests # Explicit import
            for symbol, _ in stocks:
                add_log(f"   Forwarding {symbol} to noise filter...")
                resp = requests.post(
                    noise_filter_url, 
                    params={
                        "symbol": symbol, 
                        "start_date": start_str, 
                        "end_date": end_str
                    },
                    timeout=10
                )
                if resp.status_code != 200:
                    add_log(f"   ⚠️ Noise filter returned error for {symbol}: {resp.status_code} - {resp.text}")
            add_log("✅ Finished triggering KIRA Noise Filter.")
        except Exception as e:
            add_log(f"❌ Failed to trigger Noise Filter: {e}")
    else:
        add_log("⏭️ Noise Filter trigger skipped (toggle off).")


# --- API Endpoints ---

class BackfillRequest(BaseModel):
    start_date: str
    end_date: str
    stocks: Optional[List[str]] = None  # None = all
    interval: str = "1"
    unit: str = "minutes"
    run_noise_filter: bool = False

@app.post("/backfill/start")
def start_backfill(request: BackfillRequest, background_tasks: BackgroundTasks):
    if backfill_state["running"]:
        raise HTTPException(status_code=409, detail="Backfill already running")

    access_token = os.getenv('UPSTOX_ACCESS_TOKEN')
    if not access_token or len(access_token) < 10:
        raise HTTPException(status_code=400, detail="UPSTOX_ACCESS_TOKEN not configured")

    reset_state()
    # Filter stocks dynamically handling both known Equities and raw F&O Tokens
    if request.stocks:
        requested_upper = [s.upper() for s in request.stocks]
        stocks = [(token, name) for token, name in STOCK_LIST if name in requested_upper or token.upper() in requested_upper]
        
        added_tokens = {t for t, _ in stocks}
        for req_symbol in request.stocks:
            req_upper = req_symbol.upper()
            if "NSE_FO|" in req_upper or "BSE_FO|" in req_upper:
                if req_symbol not in added_tokens:
                    stocks.append((req_symbol, req_symbol.split('|')[-1]))
                    added_tokens.add(req_symbol)
    else:
        stocks = STOCK_LIST

    if not stocks:
        raise HTTPException(status_code=400, detail=f"No valid stocks found. input={request.stocks}")

    background_tasks.add_task(
        run_backfill,
        stocks, 
        request.start_date, 
        request.end_date, 
        request.unit, 
        request.interval, 
        access_token,
        request.run_noise_filter
    )

    return {"status": "started", "total_stocks": len(stocks)}

@app.get("/backfill/status")
def get_status():
    return {
        "running": backfill_state["running"],
        "finished": backfill_state["finished"],
        "total_stocks": backfill_state["total_stocks"],
        "completed_stocks": backfill_state["completed_stocks"],
        "current_stock": backfill_state["current_stock"],
        "current_stock_progress": backfill_state["current_stock_progress"],
        "total_candles": backfill_state["total_candles"],
        "overall_progress": int(backfill_state["completed_stocks"] / max(1, backfill_state["total_stocks"]) * 100),
        "logs": backfill_state["logs"][-20:],
        "error": backfill_state["error"],
    }

@app.get("/backfill/stocks")
def list_stocks():
    return [{"token": token, "name": name} for token, name in STOCK_LIST]

@app.get("/health")
def health():
    return {"status": "ok", "service": "backfiller"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
