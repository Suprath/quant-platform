import os
import json
import psycopg2
import time
import logging
from confluent_kafka import Consumer
from dotenv import load_dotenv

load_dotenv()

# Logging Configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("Persistor-Enriched")

# --- CONFIGURATION ---
KAFKA_CONF = {
    'bootstrap.servers': os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka_bus:9092'),
    'group.id': 'questdb-persistor-microstructure-v1', # New group for new logic
    'auto.offset.reset': 'latest'
}

QDB_CONF = {
    'host': 'questdb_tsdb',
    'port': 8812,
    'user': 'admin',
    'password': 'quest',
    'database': 'qdb'
}

def get_db_connection():
    """Robust connection loop for QuestDB"""
    while True:
        try:
            conn = psycopg2.connect(**QDB_CONF)
            return conn
        except Exception as e:
            logger.warning(f"QuestDB not ready: {e}. Retrying in 3s...")
            time.sleep(3)

def ensure_schema(conn):
    """
    Auto-creates/Updates tables to match the Quant Data structure.
    This ensures your DB never crashes due to missing columns.
    """
    try:
        cur = conn.cursor()
        
        # 1. TICKS Table (Now with Microstructure columns)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticks (
                timestamp TIMESTAMP,
                symbol SYMBOL,
                ltp DOUBLE,
                volume LONG,
                oi LONG,
                day_high DOUBLE,
                day_low DOUBLE,
                spread DOUBLE,
                obi DOUBLE,
                aggressor SYMBOL
            ) TIMESTAMP(timestamp) PARTITION BY DAY;
        """)
        
        # 2. GREEKS Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS option_greeks (
                timestamp TIMESTAMP,
                symbol SYMBOL,
                iv DOUBLE,
                delta DOUBLE,
                gamma DOUBLE,
                theta DOUBLE,
                vega DOUBLE
            ) TIMESTAMP(timestamp) PARTITION BY DAY;
        """)
        
        conn.commit()
        cur.close()
        logger.info("✅ Database Schema Verified.")
    except Exception as e:
        logger.error(f"Schema Error: {e}")
        conn.rollback()

def run_persistor():
    consumer = Consumer(KAFKA_CONF)
    
    # Subscribe to ENRICHED ticks (from Feature Engine) and GREEKS (from Ingestor)
    topics = ['market.enriched.ticks', 'market.option.greeks']
    consumer.subscribe(topics)
    
    conn = get_db_connection()
    ensure_schema(conn) # Auto-fix tables on startup
    cur = conn.cursor()
    
    logger.info(f"Persistor Online. Listening to: {topics}")

    try:
        while True:
            msg = consumer.poll(0.5)
            if msg is None: continue
            if msg.error():
                logger.error(f"Kafka Error: {msg.error()}")
                continue

            topic = msg.topic()
            
            try:
                data = json.loads(msg.value().decode('utf-8'))
                
                # --- CASE 1: ENRICHED MICROSTRUCTURE DATA ---
                if topic == 'market.enriched.ticks':
                    # We map the JSON fields from Feature Engine to QuestDB columns
                    values = (
                        data.get('symbol'),
                        data.get('ltp'),
                        data.get('volume', 0),
                        data.get('oi', 0),
                        data.get('day_high'),
                        data.get('day_low'),
                        data.get('spread'),
                        data.get('obi', 0.0),
                        data.get('aggressor', 'NEUTRAL')
                    )
                    logger.info(f"Inserting {len(values)} args: {values}")
                    cur.execute("""
                        INSERT INTO ticks (
                            timestamp, symbol, ltp, volume, oi, 
                            day_high, day_low, spread, obi, aggressor
                        ) VALUES (now(), %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, values)

                # --- CASE 2: OPTION GREEKS ---
                elif topic == 'market.option.greeks':
                    cur.execute("""
                        INSERT INTO option_greeks (
                            timestamp, symbol, iv, delta, gamma, theta, vega
                        ) VALUES (now(), %s, %s, %s, %s, %s, %s)
                    """, (
                        data.get('symbol'),
                        data.get('iv'),
                        data.get('delta'),
                        data.get('gamma'),
                        data.get('theta'),
                        data.get('vega')
                    ))

                conn.commit()

            except json.JSONDecodeError:
                pass # Skip bad packets
            except psycopg2.InterfaceError:
                # Connection died, reconnect
                logger.error("DB Connection lost. Reconnecting...")
                conn = get_db_connection()
                cur = conn.cursor()
            except Exception as e:
                logger.error(f"Insert Error: {e}")
                conn.rollback()

    except KeyboardInterrupt:
        logger.info("Persistor shutting down.")
    finally:
        cur.close()
        conn.close()
        consumer.close()

if __name__ == "__main__":
    run_persistor()