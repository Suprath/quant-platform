import os
import argparse
import logging
import asyncio
import aiohttp
import pandas as pd
from datetime import datetime, timedelta
import psycopg2
from kira_shared.logging.setup import setup_logging
from kira_shared.redis.client import RedisClient
from psycopg2 import pool

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

# Global Pool
_QDB_POOL = None

def get_qdb_pool():
    global _QDB_POOL
    if _QDB_POOL is None:
        try:
            _QDB_POOL = pool.ThreadedConnectionPool(1, 20, 
                host=QDB_HOST, port=QDB_PORT, user=QDB_USER, password=QDB_PASS, database="qdb"
            )
            logger.info("✅ Noise Filter QuestDB Pool Initialized")
        except Exception as e:
            logger.error(f"Failed to init QuestDB Pool: {e}")
    return _QDB_POOL

def get_date_chunks(start_str, end_str, chunk_days=30):
    """Generates date chunks for processing."""
    try:
        start_dt = datetime.strptime(start_str, "%Y-%m-%d")
        end_dt = datetime.strptime(end_str, "%Y-%m-%d")
    except ValueError:
        # Fallback if dates are slightly different format
        start_dt = datetime.fromisoformat(start_str.replace("Z", ""))
        end_dt = datetime.fromisoformat(end_str.replace("Z", ""))
    
    chunks = []
    curr_start = start_dt
    while curr_start <= end_dt:
        curr_end = min(curr_start + timedelta(days=chunk_days - 1), end_dt)
        chunks.append((
            curr_start.strftime("%Y-%m-%d"),
            curr_end.strftime("%Y-%m-%d")
        ))
        curr_start = curr_end + timedelta(days=1)
    return chunks

async def process_historical_range(symbol: str, start_date: str, end_date: str, version: int):
    """
    Processes historical OHLC data from QuestDB in chunks and calculates confidence scores.
    """
    await asyncio.sleep(0.1) # Ensure the FastAPI request returns immediately
    logger.info(f"Starting async chunked process for {symbol} ({start_date} to {end_date}) | Version: {version}")
    
    chunks = get_date_chunks(start_date, end_date, 30)
    total_inserted = 0
    window = []
    
    async with aiohttp.ClientSession() as session:
        write_url = f"http://{QDB_HOST}:9000/write?precision=us"
        
        for idx, (c_start, c_end) in enumerate(chunks):
            logger.info(f"📦 [{idx+1}/{len(chunks)}] Fetching chunk: {c_start} to {c_end}")
            
            def fetch_chunk_data(s_date, e_date):
                pool = get_qdb_pool()
                ts_start = f"{s_date}T00:00:00.000000Z"
                ts_end = f"{e_date}T23:59:59.999999Z"
                
                query = """
                    SELECT timestamp, close FROM ohlc_1m 
                    WHERE symbol = %s AND timestamp >= %s AND timestamp <= %s 
                    ORDER BY timestamp ASC
                """
                
                if not pool:
                    conn = psycopg2.connect(host=QDB_HOST, port=QDB_PORT, user=QDB_USER, password=QDB_PASS, database="qdb")
                    try:
                        cur = conn.cursor()
                        cur.execute(query, (symbol, ts_start, ts_end))
                        return cur.fetchall()
                    finally:
                        conn.close()
                else:
                    conn = pool.getconn()
                    try:
                        cur = conn.cursor()
                        cur.execute(query, (symbol, ts_start, ts_end))
                        return cur.fetchall()
                    finally:
                        pool.putconn(conn)

            try:
                rows = await asyncio.to_thread(fetch_chunk_data, c_start, c_end)
            except Exception as e:
                logger.error(f"Failed to fetch chunk {c_start}-{c_end}: {e}")
                continue

            if not rows:
                continue

            # Process Chunk
            batch_size = 1000
            lines = []
            count = 0
            
            for i, (ts, price) in enumerate(rows):
                window.append(float(price))
                if len(window) > 20: window.pop(0)

                if cpp_core and len(window) >= 5:
                    confidence = cpp_core.calculate_confidence(window)
                else:
                    confidence = 50
                
                ts_us = int(ts.timestamp() * 1000000)
                safe_symbol = symbol.replace(" ", "\\ ")
                line = f"noise_confidence,symbol={safe_symbol} confidence={confidence}i,version={version}i {ts_us}"
                lines.append(line)
                count += 1
                
                if count % 200 == 0:
                    await asyncio.sleep(0)

                if len(lines) >= batch_size:
                    try:
                        async with session.post(write_url, data="\n".join(lines) + "\n") as resp:
                            if resp.status != 204:
                                text = await resp.text()
                                logger.error(f"Ingestion failed: {text}")
                    except Exception as e:
                        logger.error(f"Network error during ingestion: {e}")
                    lines = []

            if lines:
                try:
                    async with session.post(write_url, data="\n".join(lines) + "\n") as resp:
                        if resp.status != 204:
                            text = await resp.text()
                            logger.error(f"Final ingestion failed: {text}")
                except Exception as e:
                    logger.error(f"Network error during final ingestion: {e}")
            
            total_inserted += count
            logger.info(f"   ✅ Chunk complete. Current total: {total_inserted}")
            
            # Explicitly clear chunk rows from memory
            del rows
            import gc
            gc.collect()

    logger.info(f"🏁 All chunks completed for {symbol}. Total scores: {total_inserted}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KIRA Noise Filter Batch Processor")
    parser.add_argument("--symbol", required=True, help="Stock symbol (e.g. NSE_EQ|RELIANCE)")
    parser.add_argument("--start", required=True, help="Start date (ISO)")
    parser.add_argument("--end", required=True, help="End date (ISO)")
    parser.add_argument("--version", type=int, default=1, help="Protocol version (for overwrites)")
    
    args = parser.parse_args()
    
    asyncio.run(process_historical_range(args.symbol, args.start, args.end, args.version))
