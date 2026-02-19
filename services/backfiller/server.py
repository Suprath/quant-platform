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
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional

load_dotenv()

app = FastAPI(title="Backfiller Service")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- CONFIG ---
API_BASE_URL = "https://api.upstox.com/v3/historical-candle"
ACCESS_TOKEN = os.getenv('UPSTOX_ACCESS_TOKEN')
DELAY_BETWEEN_CHUNKS = 1.5
DELAY_BETWEEN_STOCKS = 3.0

# Top Nifty 50 stocks
STOCK_LIST = [
    ("NSE_EQ|INE002A01018", "RELIANCE"),
    ("NSE_EQ|INE040A01034", "HDFCBANK"),
    ("NSE_EQ|INE090A01021", "TCS"),
    ("NSE_EQ|INE009A01021", "INFY"),
    ("NSE_EQ|INE467B01029", "ICICIBANK"),
    ("NSE_EQ|INE062A01020", "SBIN"),
    ("NSE_EQ|INE154A01025", "ITC"),
    ("NSE_EQ|INE669E01016", "BAJFINANCE"),
    ("NSE_EQ|INE030A01027", "HINDUNILVR"),
    ("NSE_EQ|INE585B01010", "MARUTI"),
    ("NSE_EQ|INE176A01028", "AXISBANK"),
    ("NSE_EQ|INE021A01026", "ASIANPAINT"),
    ("NSE_EQ|INE075A01022", "WIPRO"),
    ("NSE_EQ|INE019A01038", "KOTAKBANK"),
    ("NSE_EQ|INE028A01039", "BAJAJFINSV"),
    ("NSE_EQ|INE397D01024", "BHARTIARTL"),
    ("NSE_EQ|INE047A01021", "SUNPHARMA"),
    ("NSE_EQ|INE326A01037", "ULTRACEMCO"),
    ("NSE_EQ|INE101A01026", "HCLTECH"),
    ("NSE_EQ|INE775A01035", "TATAMOTORS"),
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
def get_qdb_conn():
    host = os.getenv("QUESTDB_HOST", "questdb_tsdb")
    while True:
        try:
            return psycopg2.connect(host=host, port=8812, user="admin", password="quest", database="qdb")
        except:
            time.sleep(2)

def get_pg_conn():
    host = os.getenv("POSTGRES_HOST", "postgres_metadata")
    return psycopg2.connect(host=host, port=5432, user="admin", password="password123", database="quant_platform")

def ensure_instruments(stocks):
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS instruments (
            instrument_token VARCHAR(255) PRIMARY KEY, exchange VARCHAR(50),
            segment VARCHAR(50), symbol VARCHAR(50));""")
        for token, name in stocks:
            cur.execute("""INSERT INTO instruments (instrument_token, exchange, segment, symbol)
                VALUES (%s, %s, %s, %s) ON CONFLICT (instrument_token) DO UPDATE SET symbol = EXCLUDED.symbol;
            """, (token, "NSE_EQ", "EQUITY", name))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        add_log(f"⚠️ Instruments error: {e}")

def ensure_schema(conn):
    try:
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS ohlc (
            timestamp TIMESTAMP, symbol SYMBOL, timeframe SYMBOL,
            open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume LONG
        ) TIMESTAMP(timestamp) PARTITION BY DAY;""")
        conn.commit()
        cur.close()
    except Exception as e:
        conn.rollback()


# --- API Fetch ---
async def fetch_candle_chunk(session, symbol, unit, interval, to_date, from_date):
    encoded = urllib.parse.quote(symbol)
    url = f"{API_BASE_URL}/{encoded}/{unit}/{interval}/{to_date}/{from_date}"
    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {ACCESS_TOKEN}'}
    try:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                return data.get('data', {}).get('candles', [])
            elif response.status == 401:
                add_log("❌ Auth failed (401). Token expired?")
                return None
            elif response.status == 429:
                add_log("⚠️ Rate limited! Waiting 60s...")
                await asyncio.sleep(60)
                return []
            else:
                return []
    except Exception as e:
        add_log(f"   Network error: {e}")
        return []


# --- Core Backfill Logic ---
async def run_backfill(stocks, start_str, end_str, unit, interval):
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
            total_chunks = max(1, total_days // 30 + 1)
            chunk_idx = 0

            current_to = end_dt
            stock_candles = 0

            while current_to > start_dt:
                current_from = max(start_dt, current_to - timedelta(days=30))
                to_s = current_to.strftime('%Y-%m-%d')
                from_s = current_from.strftime('%Y-%m-%d')

                # Check if we already have data for this chunk in QuestDB
                check_from = f"{from_s}T00:00:00.000000Z"
                # For `to_s`, we add one day to make the upper bound inclusive for the entire `to_s` date
                check_to = f"{(current_to + timedelta(days=1)).strftime('%Y-%m-%d')}T00:00:00.000000Z"
                
                try:
                    query = f"""
                        SELECT count(*) FROM ohlc 
                        WHERE symbol = '{symbol}' 
                          AND timestamp >= '{check_from}' 
                          AND timestamp < '{check_to}'
                    """
                    cur.execute(query)
                    existing_count = cur.fetchone()[0]
                except Exception as e:
                    add_log(f"   ⚠️ DB count check failed: {e}")
                    existing_count = 0

                if existing_count > 0:
                    add_log(f"   ⏭️ Skipping {from_s} → {to_s} (Found {existing_count} candles in DB)")
                    chunk_idx += 1
                    backfill_state["current_stock_progress"] = min(100, int(chunk_idx / total_chunks * 100))
                    current_to = current_from - timedelta(days=1)
                    continue

                candles = await fetch_candle_chunk(session, symbol, unit, interval, to_s, from_s)

                if candles is None:
                    backfill_state["error"] = "Authentication failed"
                    backfill_state["running"] = False
                    cur.close()
                    conn.close()
                    return

                if candles:
                    for c in candles:
                        cur.execute("""INSERT INTO ohlc (timestamp, symbol, timeframe, open, high, low, close, volume)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                            (c[0], symbol, f"{interval}{unit[0]}", c[1], c[2], c[3], c[4], c[5]))
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
    conn.close()
    backfill_state["running"] = False
    backfill_state["finished"] = True
    add_log(f"🏁 Backfill complete! Total: {backfill_state['total_candles']} candles")


# --- API Endpoints ---

class BackfillRequest(BaseModel):
    start_date: str
    end_date: str
    stocks: Optional[List[str]] = None  # None = all
    interval: str = "1"
    unit: str = "minutes"

@app.post("/backfill/start")
def start_backfill(request: BackfillRequest):
    if backfill_state["running"]:
        raise HTTPException(status_code=409, detail="Backfill already running")

    if not ACCESS_TOKEN or len(ACCESS_TOKEN) < 10:
        raise HTTPException(status_code=400, detail="UPSTOX_ACCESS_TOKEN not configured")

    reset_state()

    # Filter stocks
    if request.stocks:
        requested = [s.upper() for s in request.stocks]
        stocks = [(token, name) for token, name in STOCK_LIST if name in requested]
    else:
        stocks = STOCK_LIST

    if not stocks:
        raise HTTPException(status_code=400, detail="No valid stocks found")

    # Run in background thread with its own event loop
    def run_in_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_backfill(stocks, request.start_date, request.end_date, request.unit, request.interval))
        loop.close()

    thread = threading.Thread(target=run_in_thread, daemon=True)
    thread.start()

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
