import os
import asyncio
import aiohttp
import psycopg2
import urllib.parse
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# Configuration
API_BASE_URL = "https://api.upstox.com/v3/historical-candle"
ACCESS_TOKEN = os.getenv('UPSTOX_ACCESS_TOKEN')
KAFKA_SERVER = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka_bus:9092')

# QuestDB Connection
def get_qdb_conn():
    return psycopg2.connect(
        host="questdb_tsdb", port=8812, user="admin", password="quest", database="qdb"
    )

async def fetch_candle_chunk(session, symbol, unit, interval, to_date, from_date):
    """Fetches a single chunk of data from Upstox V3 API"""
    # URL Encoding the | symbol in instrument key
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
        else:
            print(f"Error {response.status}: {await response.text()}")
            return []

async def backfill_data(symbol, unit, interval, start_date_str, end_date_str):
    """Chunks the request into 30-day blocks to respect API limits"""
    start_dt = datetime.strptime(start_date_str, '%Y-%m-%d')
    end_dt = datetime.strptime(end_date_str, '%Y-%m-%d')
    
    conn = get_qdb_conn()
    cur = conn.cursor()
    
    async with aiohttp.ClientSession() as session:
        current_to = end_dt
        while current_to > start_dt:
            # For minutes, we use 30-day chunks (Max retrieval record limit)
            current_from = max(start_dt, current_to - timedelta(days=30))
            
            to_str = current_to.strftime('%Y-%m-%d')
            from_str = current_from.strftime('%Y-%m-%d')
            
            print(f"Downloading {symbol} from {from_str} to {to_str}...")
            
            candles = await fetch_candle_chunk(session, symbol, unit, interval, to_str, from_str)
            
            if candles:
                # Prepare data for QuestDB (Ref: PDF Page 8 Schema)
                # Upstox order: [timestamp, open, high, low, close, volume, oi]
                for c in candles:
                    cur.execute("""
                        INSERT INTO ohlc (timestamp, symbol, timeframe, open, high, low, close, volume)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (c[0], symbol, f"{interval}{unit[0]}", c[1], c[2], c[3], c[4], c[5]))
                
                conn.commit()
                print(f"  Successfully saved {len(candles)} candles.")
            
            # Step back in time
            current_to = current_from - timedelta(days=1)
            
            # Rate limit protection: sleep 1 second between chunks
            await asyncio.sleep(1)

    cur.close()
    conn.close()
    print("Backfill Complete!")

if __name__ == "__main__":
    # Example: Download last 3 months of 1-minute data for Reliance
    # Note: Ensure UPSTOX_ACCESS_TOKEN is fresh!
    SYMBOL = "NSE_EQ|INE002A01018"
    asyncio.run(backfill_data(SYMBOL, "minutes", "1", "2024-11-01", "2025-01-31"))