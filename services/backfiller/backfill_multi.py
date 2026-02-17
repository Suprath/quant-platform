"""
Multi-Stock Historical Data Backfiller for Quant Platform
=========================================================
Downloads OHLC candle data for multiple stocks from Upstox V3 API
and stores it in QuestDB. Respects Upstox rate limits (50 req/s, 250 req/min).

Usage:
  docker exec -it data_backfiller python backfill_multi.py \
    --start 2025-01-01 --end 2026-02-14 --interval 1 --unit minutes

Or run locally:
  python backfill_multi.py --start 2025-01-01 --end 2026-02-14
"""

import os
import asyncio
import aiohttp
import psycopg2
import urllib.parse
import time
import argparse
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
API_BASE_URL = "https://api.upstox.com/v3/historical-candle"
ACCESS_TOKEN = os.getenv('UPSTOX_ACCESS_TOKEN')

# --- TOP NIFTY 50 STOCKS (Instrument Token -> Trading Symbol) ---
# These are the Upstox V3 instrument keys (ISIN-based)
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

# Rate limit config: Upstox allows 50 req/s, 250 req/min
# We stay well below at ~1 req per 1.5 seconds = 40 req/min
DELAY_BETWEEN_CHUNKS = 1.5    # seconds between API calls
DELAY_BETWEEN_STOCKS = 5.0    # seconds between each stock (extra safety margin)


def get_qdb_conn():
    """Connect to QuestDB with retry logic"""
    host = os.getenv("QUESTDB_HOST", "questdb_tsdb")
    print(f"Connecting to QuestDB at {host}:8812...")
    while True:
        try:
            conn = psycopg2.connect(
                host=host,
                port=8812,
                user="admin",
                password="quest",
                database="qdb"
            )
            conn.autocommit = True
            print("✅ Connected to QuestDB (autocommit=True)")
            return conn
        except Exception as e:
            print(f"QuestDB not ready. Retrying in 2s... ({e})")
            time.sleep(2)


def get_pg_conn():
    """Connect to PostgreSQL (for instruments table)"""
    host = os.getenv("POSTGRES_HOST", "postgres_metadata")
    return psycopg2.connect(
        host=host,
        port=5432,
        user="admin",
        password="password123",
        database="quant_platform"
    )


def ensure_instruments(stocks):
    """Make sure all stocks exist in the PostgreSQL instruments table"""
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS instruments (
                instrument_token VARCHAR(255) PRIMARY KEY,
                exchange VARCHAR(50),
                segment VARCHAR(50),
                symbol VARCHAR(50)
            );
        """)
        
        for token, name in stocks:
            cur.execute("""
                INSERT INTO instruments (instrument_token, exchange, segment, symbol)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (instrument_token) DO UPDATE SET symbol = EXCLUDED.symbol;
            """, (token, "NSE_EQ", "EQUITY", name))
        
        conn.commit()
        cur.close()
        conn.close()
        print(f"✅ {len(stocks)} instruments registered in PostgreSQL")
    except Exception as e:
        print(f"⚠️ Instruments registration error: {e}")


def ensure_schema(conn):
    """Auto-creates OHLC table if it doesn't exist"""
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ohlc (
                timestamp TIMESTAMP,
                symbol SYMBOL,
                timeframe SYMBOL,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume LONG
            ) TIMESTAMP(timestamp) PARTITION BY DAY;
        """)
        conn.commit()
        cur.close()
        print("✅ OHLC schema verified")
    except Exception as e:
        print(f"Schema error: {e}")
        conn.rollback()


async def fetch_candle_chunk(session, symbol, unit, interval, to_date, from_date):
    """Fetches a single 30-day chunk from Upstox V3 API"""
    encoded_symbol = urllib.parse.quote(symbol)
    url = f"{API_BASE_URL}/{encoded_symbol}/{unit}/{interval}/{to_date}/{from_date}"
    
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {ACCESS_TOKEN}'
    }

    try:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                res_json = await response.json()
                return res_json.get('data', {}).get('candles', [])
            elif response.status == 401:
                print("❌ Error 401: Unauthorized. Token expired.")
                return None
            elif response.status == 429:
                print("⚠️ Rate limited! Waiting 60 seconds...")
                await asyncio.sleep(60)
                return []  # Will retry in next chunk cycle
            else:
                text = await response.text()
                print(f"   Error {response.status}: {text[:200]}")
                return []
    except Exception as e:
        print(f"   Network error: {e}")
        return []


async def backfill_single_stock(session, conn, symbol, name, unit, interval, start_dt, end_dt):
    """Backfill one stock in 30-day chunks"""
    cur = conn.cursor()
    current_to = end_dt
    total_saved = 0
    
    print(f"\n{'='*60}")
    print(f"📈 Downloading: {name} ({symbol})")
    print(f"   Range: {start_dt.strftime('%Y-%m-%d')} → {end_dt.strftime('%Y-%m-%d')}")
    print(f"{'='*60}")

    while current_to > start_dt:
        current_from = max(start_dt, current_to - timedelta(days=30))
        
        to_str = current_to.strftime('%Y-%m-%d')
        from_str = current_from.strftime('%Y-%m-%d')
        
        print(f"   🔄 Chunk: {from_str} → {to_str}...", end=" ", flush=True)
        
        candles = await fetch_candle_chunk(session, symbol, unit, interval, to_str, from_str)
        
        if candles is None:  # Auth error — stop everything
            return -1
        
        if candles:
            for c in candles:
                cur.execute("""
                    INSERT INTO ohlc (timestamp, symbol, timeframe, open, high, low, close, volume)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (c[0], symbol, f"{interval}{unit[0]}", c[1], c[2], c[3], c[4], c[5]))
            
            conn.commit()
            total_saved += len(candles)
            print(f"✅ {len(candles)} candles saved")
        else:
            print(f"⏭️  No data")
        
        current_to = current_from - timedelta(days=1)
        
        # Rate limit: wait between API calls
        await asyncio.sleep(DELAY_BETWEEN_CHUNKS)
    
    cur.close()
    print(f"   📊 Total for {name}: {total_saved} candles")
    return total_saved


async def backfill_all(stocks, unit, interval, start_date_str, end_date_str):
    """Backfill all stocks sequentially to stay within rate limits"""
    start_dt = datetime.strptime(start_date_str, '%Y-%m-%d')
    end_dt = datetime.strptime(end_date_str, '%Y-%m-%d')
    
    # Setup
    conn = get_qdb_conn()
    ensure_schema(conn)
    ensure_instruments(stocks)
    
    print(f"\n🚀 Starting multi-stock backfill")
    print(f"   Stocks: {len(stocks)}")
    print(f"   Range: {start_date_str} → {end_date_str}")
    print(f"   Interval: {interval} {unit}")
    print(f"   Rate limit: {DELAY_BETWEEN_CHUNKS}s/chunk, {DELAY_BETWEEN_STOCKS}s between stocks\n")
    
    results = {}
    
    async with aiohttp.ClientSession() as session:
        for i, (symbol, name) in enumerate(stocks):
            print(f"\n[{i+1}/{len(stocks)}] Processing {name}...")
            
            count = await backfill_single_stock(
                session, conn, symbol, name, unit, interval, start_dt, end_dt
            )
            
            if count == -1:
                print("\n❌ Authentication failed. Stopping.")
                break
            
            results[name] = count
            
            # Extra delay between stocks to stay safe
            if i < len(stocks) - 1:
                print(f"\n   ⏳ Cooling down {DELAY_BETWEEN_STOCKS}s before next stock...")
                await asyncio.sleep(DELAY_BETWEEN_STOCKS)
    
    conn.close()
    
    # Summary
    print(f"\n{'='*60}")
    print(f"📊 BACKFILL SUMMARY")
    print(f"{'='*60}")
    total = 0
    for name, count in results.items():
        status = f"✅ {count:,} candles" if count > 0 else "⏭️  No data"
        print(f"   {name:15s} → {status}")
        total += count
    print(f"{'='*60}")
    print(f"   TOTAL: {total:,} candles stored in QuestDB")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Multi-Stock Historical Data Backfiller')
    parser.add_argument('--start', type=str, required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--interval', type=str, default='1', help='Candle interval (default: 1)')
    parser.add_argument('--unit', type=str, default='minutes', 
                        choices=['minutes', 'hours', 'days'], help='Time unit (default: minutes)')
    parser.add_argument('--stocks', type=str, default='all',
                        help='Comma-separated stock names to backfill (e.g., RELIANCE,TCS,INFY) or "all"')
    
    args = parser.parse_args()
    
    if not ACCESS_TOKEN or len(ACCESS_TOKEN) < 10:
        print("❌ Error: UPSTOX_ACCESS_TOKEN is missing or invalid in .env")
        print("   Set it via: export UPSTOX_ACCESS_TOKEN=your_token")
        exit(1)
    
    # Filter stocks if specific ones requested
    if args.stocks == 'all':
        stocks = STOCK_LIST
    else:
        requested = [s.strip().upper() for s in args.stocks.split(',')]
        stocks = [(token, name) for token, name in STOCK_LIST if name in requested]
        if not stocks:
            print(f"❌ No matching stocks found. Available: {[n for _, n in STOCK_LIST]}")
            exit(1)
    
    print(f"📥 Multi-Stock Backfiller")
    print(f"   Upstox Rate Limit: 50 req/s, 250 req/min")
    print(f"   Our rate: ~{60/DELAY_BETWEEN_CHUNKS:.0f} req/min (safe margin)")
    
    asyncio.run(backfill_all(stocks, args.unit, args.interval, args.start, args.end))
