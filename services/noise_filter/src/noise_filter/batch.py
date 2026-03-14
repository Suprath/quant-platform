import os
import argparse
import logging
import asyncio
import aiohttp
import pandas as pd
from datetime import datetime
import psycopg2
from kira_shared.logging.setup import setup_logging
from kira_shared.redis.client import RedisClient

setup_logging()
logger = logging.getLogger("NoiseFilterBatch")

# Try to import the C++ extension
try:
    from noise_filter_core import NoiseFilterCore
    cpp_core = NoiseFilterCore()
    logger.info("C++ Noise Filter Core loaded successfully.")
except ImportError:
    logger.warning("C++ Noise Filter Core not found. Falling back to placeholder.")
    cpp_core = None

# Config
QDB_HOST = os.getenv("QUESTDB_HOST", "questdb_tsdb")
QDB_PORT = 8812
QDB_USER = os.getenv("QUESTDB_USER", "admin")
QDB_PASS = os.getenv("QUESTDB_PASSWORD", "quest")

# Config
QDB_HOST = os.getenv("QUESTDB_HOST", "questdb_tsdb")
QDB_PORT = 8812
QDB_USER = os.getenv("QUESTDB_USER", "admin")
QDB_PASS = os.getenv("QUESTDB_PASSWORD", "quest")

async def process_historical_range(symbol: str, start_date: str, end_date: str, version: int):
    """
    Processes historical OHLC data from QuestDB and calculates confidence scores.
    """
    await asyncio.sleep(0.1) # Ensure the FastAPI request returns immediately
    logger.info(f"Starting async batch process for {symbol} ({start_date} to {end_date}) | Version: {version}")
    
    # 1. Fetch real OHLC data from QuestDB using a thread to avoid blocking loop
    def fetch_data():
        conn = None
        try:
            conn = psycopg2.connect(
                host=QDB_HOST, port=QDB_PORT, user=QDB_USER, password=QDB_PASS, database="qdb"
            )
            cur = conn.cursor()
            ts_start = f"{start_date}T00:00:00.000000Z"
            ts_end = f"{end_date}T23:59:59.999999Z"
            cur.execute("""
                SELECT timestamp, close 
                FROM ohlc 
                WHERE symbol = %s AND timestamp >= %s AND timestamp <= %s 
                ORDER BY timestamp ASC
            """, (symbol, ts_start, ts_end))
            r = cur.fetchall()
            cur.close()
            return r
        finally:
            if conn: conn.close()

    try:
        rows = await asyncio.to_thread(fetch_data)
    except Exception as e:
        logger.error(f"Failed to fetch OHLC: {e}")
        return

    if not rows:
        logger.warning(f"No OHLC data found for {symbol} in range {start_date} - {end_date}")
        return

    logger.info(f"Processing {len(rows)} data points...")

    # 2. Process and Ingest via REST API (Influx Line Protocol)
    write_url = f"http://{QDB_HOST}:9000/write?precision=us"
    batch_size = 500 # Larger batch for efficiency
    lines = []
    count = 0
    window = []
    
    async with aiohttp.ClientSession() as session:
        for i, (ts, price) in enumerate(rows):
            window.append(float(price))
            if len(window) > 20: window.pop(0)

            if cpp_core and len(window) >= 5:
                # Assuming C++ core is fast and releases GIL if possible, 
                # but for simplicity we keep it in-loop for now.
                confidence = cpp_core.calculate_confidence(window)
            else:
                confidence = 50 # Default if no core or window too small
            
            # ts is datetime from psycopg2
            ts_us = int(ts.timestamp() * 1000000)
            
            # ILP requires escaping spaces in tag values
            safe_symbol = symbol.replace(" ", "\\ ")
            line = f"noise_confidence,symbol={safe_symbol} confidence={confidence}i,version={version}i {ts_us}"
            lines.append(line)
            count += 1
            
            # Periodically yield back to event loop to keep Kafka heartbeats alive
            if count % 100 == 0:
                await asyncio.sleep(0) # Cooperative yielding

            if len(lines) >= batch_size:
                try:
                    async with session.post(write_url, data="\n".join(lines) + "\n") as resp:
                        if resp.status != 204:
                            text = await resp.text()
                            logger.error(f"Ingestion failed: {text}")
                except Exception as e:
                    logger.error(f"Network error during ingestion: {e}")
                
                lines = []
                if count % 5000 == 0:
                    logger.info(f"Inserted {count} scores...")

        if lines:
            async with session.post(write_url, data="\n".join(lines) + "\n") as resp:
                if resp.status != 204:
                    text = await resp.text()
                    logger.error(f"Final ingestion failed: {text}")
        
    logger.info(f"Batch completed. Total scores inserted: {count}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KIRA Noise Filter Batch Processor")
    parser.add_argument("--symbol", required=True, help="Stock symbol (e.g. NSE_EQ|RELIANCE)")
    parser.add_argument("--start", required=True, help="Start date (ISO)")
    parser.add_argument("--end", required=True, help="End date (ISO)")
    parser.add_argument("--version", type=int, default=1, help="Protocol version (for overwrites)")
    
    args = parser.parse_args()
    
    asyncio.run(process_historical_range(args.symbol, args.start, args.end, args.version))
