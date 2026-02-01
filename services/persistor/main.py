import os
import json
import psycopg2
import time
import logging
from confluent_kafka import Consumer
from dotenv import load_dotenv

load_dotenv()

# Logging configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MarketPersistor")

# 1. KAFKA CONFIGURATION
KAFKA_CONF = {
    'bootstrap.servers': os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka_bus:9092'),
    'group.id': 'questdb-persistor-v4', # Incremented version to ensure fresh start
    'auto.offset.reset': 'latest'       # Focus on live market data
}

# 2. QUESTDB CONFIGURATION (Postgres Wire Protocol)
QDB_CONF = {
    'host': 'questdb_tsdb',
    'port': 8812,
    'user': 'admin',
    'password': 'quest',
    'database': 'qdb'
}

def get_db_connection():
    """Retry logic for connecting to QuestDB"""
    while True:
        try:
            conn = psycopg2.connect(**QDB_CONF)
            return conn
        except Exception as e:
            logger.warning(f"QuestDB not ready ({e}). Retrying in 5s...")
            time.sleep(5)

def run_persistor():
    # Initialize Kafka Consumer
    consumer = Consumer(KAFKA_CONF)
    
    # Subscribe to both Equity Ticks and Option Greeks topics
    topics = ['market.equity.ticks', 'market.option.greeks']
    consumer.subscribe(topics)
    logger.info(f"Subscribed to Kafka topics: {topics}")

    # Initial DB Connection
    conn = get_db_connection()
    cur = conn.cursor()
    logger.info("✅ Connected to QuestDB. Starting persistence loop...")

    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None: continue
            if msg.error():
                logger.error(f"Consumer error: {msg.error()}")
                continue

            # Identify which topic the data came from
            topic = msg.topic()
            
            try:
                # Decode JSON payload
                data = json.loads(msg.value().decode('utf-8'))
                symbol = data.get('symbol')

                # --- ROUTE TO EQUITY TICKS TABLE ---
                if topic == 'market.equity.ticks':
                    # Columns: timestamp, symbol, ltp, volume, oi
                    cur.execute("""
                        INSERT INTO ticks (timestamp, symbol, ltp, volume, oi)
                        VALUES (now(), %s, %s, %s, %s)
                    """, (
                        symbol, 
                        data.get('ltp'), 
                        data.get('v', 0), # Volume
                        data.get('oi', 0)  # Open Interest
                    ))

                # --- ROUTE TO OPTION GREEKS TABLE ---
                elif topic == 'market.option.greeks':
                    # Columns: timestamp, symbol, iv, delta, gamma, theta, vega
                    cur.execute("""
                        INSERT INTO option_greeks (timestamp, symbol, iv, delta, gamma, theta, vega)
                        VALUES (now(), %s, %s, %s, %s, %s, %s)
                    """, (
                        symbol,
                        data.get('iv'),
                        data.get('delta'),
                        data.get('gamma'),
                        data.get('theta'),
                        data.get('vega')
                    ))

                # Commit every message for real-time consistency
                conn.commit()
                
                # Periodic logging for health monitoring
                if int(time.time()) % 60 == 0:
                    logger.info(f"Still persisting... Latest: {symbol} on {topic}")

            except json.JSONDecodeError:
                logger.error("Skipped message: Invalid JSON")
            except psycopg2.OperationalError:
                logger.error("QuestDB connection lost. Reconnecting...")
                conn = get_db_connection()
                cur = conn.cursor()
            except Exception as e:
                logger.error(f"Processing error on {topic}: {e}")
                conn.rollback()

    except KeyboardInterrupt:
        logger.info("Persistor stopped by user.")
    finally:
        cur.close()
        conn.close()
        consumer.close()

if __name__ == "__main__":
    run_persistor()