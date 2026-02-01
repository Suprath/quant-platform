import os
import asyncio
import aiohttp
import psycopg2
import urllib.parse
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
# Based on Upstox V3 Docs: Max 1 month per request for 1-minute data
API_BASE_URL = "https://api.upstox.com/v3/historical-candle"
ACCESS_TOKEN = os.getenv('UPSTOX_ACCESS_TOKEN')

def get_qdb_conn():
    """Expert-level connection helper with retry logic for QuestDB"""
    print("Connecting to QuestDB (port 8812)...")
    while True:
        try:
            conn = psycopg2.connect(
                host="questdb_tsdb",
                port=8812,
                user="admin",
                password="quest", # Standard QuestDB default
                database="qdb"
            )
            print("✅ Successfully connected to QuestDB Engine!")
            return conn
        except Exception as e:
            print(f"QuestDB not ready yet (Postgres Wire Protocol). Retrying in 2s...")
            time.sleep(2)

async def fetch_candle_chunk(session, symbol, unit, interval, to_date, from_date):
    """Fetches a single 30-day chunk from Upstox V3 API"""
    # Important: Symbol contains '|' so it must be URL encoded
    encoded_symbol = urllib.parse.quote(symbol)
    url = f"{API_BASE_URL}/{encoded_symbol}/{unit}/{interval}/{to_date}/{from_date}"
    
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {ACCESS_TOKEN}'
    }

    async with session.get(url, headers=headers) as response:
        if response.status == 200:
            res_json = await response.json()
            return res_json.get('data', {}).get('candles', [])
        elif response.status == 401:
            print("❌ Error 401: Unauthorized. Your token is likely expired.")
            return None
        else:
            print(f"Error {response.status}: {await response.text()}")
            return []

async def backfill_data(symbol, unit, interval, start_date_str, end_date_str):
    """
    Chunks the historical request into 30-day blocks.
    Saves to QuestDB 'ohlc' table.
    """
    start_dt = datetime.strptime(start_date_str, '%Y-%m-%d')
    end_dt = datetime.strptime(end_date_str, '%Y-%m-%d')
    
    # Wait for DB connection
    conn = get_qdb_conn()
    cur = conn.cursor()
    
    async with aiohttp.ClientSession() as session:
        current_to = end_dt
        total_saved = 0

        while current_to > start_dt:
            # Calculate a 30-day window stepping backwards
            current_from = max(start_dt, current_to - timedelta(days=30))
            
            to_str = current_to.strftime('%Y-%m-%d')
            from_str = current_from.strftime('%Y-%m-%d')
            
            print(f"🚀 Downloading {symbol} from {from_str} to {to_str}...")
            
            candles = await fetch_candle_chunk(session, symbol, unit, interval, to_str, from_str)
            
            if candles is None: break # Token error

            if candles:
                # QuestDB Schema (Ref: PDF Page 8)
                # Upstox order: [timestamp, open, high, low, close, volume, oi]
                for c in candles:
                    cur.execute("""
                        INSERT INTO ohlc (timestamp, symbol, timeframe, open, high, low, close, volume)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (c[0], symbol, f"{interval}{unit[0]}", c[1], c[2], c[3], c[4], c[5]))
                
                conn.commit()
                total_saved += len(candles)
                print(f"   Stored {len(candles)} rows into QuestDB.")
            
            # Move window further back in time
            current_to = current_from - timedelta(days=1)
            
            # Rate limit protection (Free Tier safety)
            await asyncio.sleep(1.5)

    cur.close()
    conn.close()
    print(f"✅ Backfill Complete! Total rows stored: {total_saved}")

if __name__ == "__main__":
    # --- TASK PARAMETERS ---
    # Change these values depending on what you want to download
    SYMBOL = "NSE_EQ|INE002A01018" # Reliance
    START = "2024-11-01"
    END = "2025-01-31"
    
    # Check if Token exists
    if not ACCESS_TOKEN or len(ACCESS_TOKEN) < 10:
        print("❌ Error: UPSTOX_ACCESS_TOKEN is missing in .env")
    else:
        asyncio.run(backfill_data(SYMBOL, "minutes", "1", START, END))