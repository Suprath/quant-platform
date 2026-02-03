import os
import json
import time
import logging
import psycopg2
from datetime import datetime
from confluent_kafka import Producer
from dotenv import load_dotenv
import argparse

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("HistoricalReplayer")

KAFKA_SERVER = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka_bus:9092')

def get_qdb_conn():
    """Connect to QuestDB"""
    while True:
        try:
            conn = psycopg2.connect(
                host="questdb_tsdb",
                port=8812,
                user="admin",
                password="quest",
                database="qdb"
            )
            logger.info("✅ Connected to QuestDB")
            return conn
        except Exception:
            logger.warning("Waiting for QuestDB...")
            time.sleep(2)

def fetch_historical_data(symbol, start_date, end_date, timeframe='1m'):
    """
    Fetch OHLC candles from QuestDB for given timeframe
    """
    conn = get_qdb_conn()
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
    
    cur.execute(query, (symbol, timeframe, start_date, end_date))
    candles = cur.fetchall()
    cur.close()
    conn.close()
    
    logger.info(f"📊 Loaded {len(candles)} candles for {symbol}")
    return candles

def ohlc_to_ticks(timestamp, open_price, high, low, close, volume):
    """
    Convert single OHLC candle to tick-level events
    Generates 4 ticks per candle: Open, High, Low, Close
    """
    ticks = []
    
    # Tick 1: Open
    ticks.append({
        "symbol": None,  # Will be set by caller
        "ltp": open_price,
        "v": int(volume * 0.25),  # Distribute volume across ticks
        "timestamp": int(timestamp.timestamp() * 1000),
        "depth": {}
    })
    
    # Tick 2: High
    ticks.append({
        "symbol": None,
        "ltp": high,
        "v": int(volume * 0.25),
        "timestamp": int(timestamp.timestamp() * 1000) + 15000,  # +15 seconds
        "depth": {}
    })
    
    # Tick 3: Low
    ticks.append({
        "symbol": None,
        "ltp": low,
        "v": int(volume * 0.25),
        "timestamp": int(timestamp.timestamp() * 1000) + 30000,  # +30 seconds
        "depth": {}
    })
    
    # Tick 4: Close
    ticks.append({
        "symbol": None,
        "ltp": close,
        "v": int(volume * 0.25),
        "timestamp": int(timestamp.timestamp() * 1000) + 45000,  # +45 seconds
        "depth": {}
    })
    
    return ticks

def replay_data(symbol, start_date, end_date, speed_multiplier=1, timeframe='1m'):
    """
    Replay historical data through Kafka
    speed_multiplier: 1 = real-time, 10 = 10x faster, 100 = 100x faster
    """
    candles = fetch_historical_data(symbol, start_date, end_date, timeframe)
    
    if not candles:
        logger.error("❌ No data found for specified timeframe")
        return
    
    producer = Producer({'bootstrap.servers': KAFKA_SERVER})
    total_ticks = len(candles) * 4  # 4 ticks per candle
    
    # Isolation: Use unique topic for backtests
    run_id = os.getenv('RUN_ID')
    topic_name = f'market.equity.ticks.{run_id}' if run_id else 'market.equity.ticks'
    
    logger.info(f"🎬 Starting replay: {len(candles)} candles → {total_ticks} ticks")
    logger.info(f"📡 Producing to topic: {topic_name}")
    
    start_time = time.time()
    tick_count = 0
    
    for timestamp_obj, open_p, high, low, close, volume in candles:
        ticks = ohlc_to_ticks(timestamp_obj, open_p, high, low, close, volume)
        
        for tick in ticks:
            tick['symbol'] = symbol
            producer.produce(topic_name, key=symbol, value=json.dumps(tick))
            tick_count += 1
            
            if tick_count % 100 == 0:
                producer.poll(0)
                logger.info(f"📡 Replayed {tick_count}/{total_ticks} ticks ({tick_count/total_ticks*100:.1f}%)")
        
        # Speed control: sleep between candles
        # 1 minute candle in real-time = 60 seconds
        # At 100x speed = 0.6 seconds
        sleep_time = (60.0 / speed_multiplier) / 4  # Divide by 4 since we send 4 ticks
        time.sleep(sleep_time)
    
    producer.flush()
    elapsed = time.time() - start_time
    
    logger.info(f"✅ Replay Complete!")
    logger.info(f"   📊 Total Ticks: {tick_count}")
    logger.info(f"   ⏱️  Time Taken: {elapsed:.2f} seconds")
    logger.info(f"   🚀 Effective Speed: {speed_multiplier}x")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Replay historical data for backtesting')
    parser.add_argument('--symbol', type=str, required=True, help='Stock symbol (e.g., NSE_EQ|INE002A01018)')
    parser.add_argument('--start', type=str, required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--speed', type=int, default=100, help='Replay speed multiplier (default: 100x)')
    parser.add_argument('--timeframe', type=str, default='1m', help='Timeframe to replay (default: 1m)')
    
    args = parser.parse_args()
    
    logger.info(f"🔄 Historical Replayer Starting...")
    logger.info(f"   Symbol: {args.symbol}")
    logger.info(f"   Period: {args.start} to {args.end}")
    logger.info(f"   Timeframe: {args.timeframe}")
    logger.info(f"   Speed: {args.speed}x")
    
    replay_data(args.symbol, args.start, args.end, args.speed, args.timeframe)