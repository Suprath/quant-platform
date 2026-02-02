import os
import json
import time
import psycopg2
import logging
from confluent_kafka import Producer
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("HistoricalReplayer")

KAFKA_SERVER = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka_bus:9092')

def get_qdb_conn():
    return psycopg2.connect(
        host="questdb_tsdb",
        port=8812,
        user="admin",
        password="quest",
        database="qdb"
    )

def replay_ohlc_as_ticks(symbol="NSE_EQ|INE002A01018", speed_factor=100):
    """
    Replays OHLC data as simulated ticks.
    Uses Close price as LTP, distributes volume across the minute.
    """
    producer = Producer({'bootstrap.servers': KAFKA_SERVER})
    conn = get_qdb_conn()
    cur = conn.cursor()
    
    logger.info(f"🎬 Replaying OHLC data as ticks for {symbol}...")
    
    # DEBUG: First check if table exists and what's in it
    try:
        cur.execute("SELECT count(*) FROM ohlc;")
        total_rows = cur.fetchone()[0]
        logger.info(f"📊 Total rows in ohlc table: {total_rows}")
        
        # DEBUG: Show available symbols
        cur.execute("SELECT DISTINCT symbol FROM ohlc LIMIT 10;")
        available_symbols = [row[0] for row in cur.fetchall()]
        logger.info(f"📋 Available symbols in DB: {available_symbols}")
    except Exception as e:
        logger.error(f"Debug query failed: {e}")
    
    # Query OHLC table (not ticks table)
    cur.execute("""
        SELECT timestamp, symbol, open, high, low, close, volume 
        FROM ohlc 
        WHERE symbol = %s 
        ORDER BY timestamp ASC 
        LIMIT 1000;
    """, (symbol,))
    
    rows = cur.fetchall()
    
    if not rows:
        logger.error(f"❌ No data found for symbol: {symbol}")
        
        # FALLBACK: Try with LIKE query in case format is different
        logger.info("🔍 Trying fuzzy search...")
        cur.execute("""
            SELECT symbol, count(*) as cnt 
            FROM ohlc 
            WHERE symbol LIKE %s 
            GROUP BY symbol;
        """, (f"%{symbol.split('|')[-1]}%",))
        
        fuzzy_results = cur.fetchall()
        if fuzzy_results:
            logger.info(f"🔍 Found similar symbols: {fuzzy_results}")
            # Use the first similar symbol
            symbol = fuzzy_results[0][0]
            logger.info(f"🔄 Retrying with: {symbol}")
            
            cur.execute("""
                SELECT timestamp, symbol, open, high, low, close, volume 
                FROM ohlc 
                WHERE symbol = %s 
                ORDER BY timestamp ASC 
                LIMIT 1000;
            """, (symbol,))
            rows = cur.fetchall()
        else:
            logger.error("❌ No data available at all")
            return
    
    logger.info(f"✅ Found {len(rows)} OHLC candles to replay")
    
    prev_ts = None
    for row in rows:
        ts, sym, open_p, high_p, low_p, close_p, volume = row
        
        # Simulate 4 ticks per candle (O, H, L, C) at 15-second intervals
        ticks = [
            ("OPEN", open_p),
            ("HIGH", high_p), 
            ("LOW", low_p),
            ("CLOSE", close_p)
        ]
        
        for tick_type, price in ticks:
            tick = {
                "symbol": sym,
                "ltp": float(price),
                "v": int(volume // 4) if volume else 100,  # Handle None volume
                "oi": 0,
                "cp": float(close_p),
                "timestamp": int(ts.timestamp() * 1000),
                "type": tick_type,
                "replay": True
            }
            
            producer.produce('market.equity.ticks', key=sym, value=json.dumps(tick))
            producer.poll(0)
            
            logger.info(f"🎬 REPLAY: {sym} @ {price} ({tick_type}) | Vol: {tick['v']}")
            time.sleep(0.01 / speed_factor)
        
        if prev_ts:
            delay = ((ts - prev_ts).total_seconds() / speed_factor)
            time.sleep(min(delay, 0.1))
        prev_ts = ts
    
    producer.flush()
    logger.info("✅ Replay complete")

if __name__ == "__main__":
    replay_ohlc_as_ticks("NSE_EQ|INE002A01018", speed_factor=100)