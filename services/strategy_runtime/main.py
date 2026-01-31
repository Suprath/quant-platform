import os
import json
import psycopg2
import time
from confluent_kafka import Consumer
from dotenv import load_dotenv

load_dotenv()

KAFKA_SERVER = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka_bus:9092')
DB_CONF = {
    "host": "postgres_metadata",
    "port": 5432,
    "user": "admin",
    "password": "password123",
    "database": "quant_platform"
}

def run_executor():
    # 1. Connect to Database with Retry
    conn = None
    while conn is None:
        try:
            conn = psycopg2.connect(**DB_CONF)
            cur = conn.cursor()
            print("Successfully connected to Postgres")
        except Exception:
            print("Postgres not ready, retrying...")
            time.sleep(2)

    # 2. Connect to Kafka
    c = Consumer({
        'bootstrap.servers': KAFKA_SERVER,
        'group.id': 'strategy-runtime-v3', # Fresh group to skip poison pills
        'auto.offset.reset': 'earliest'
    })
    c.subscribe(['strategy.signals'])

    print("Strategy Runtime: Listening for signals...")

    try:
        while True:
            msg = c.poll(1.0)
            if msg is None: continue
            
            try:
                # Safe JSON parsing
                payload = msg.value().decode('utf-8')
                if not payload: continue
                
                signal = json.loads(payload)
                
                # Safe key access using .get()
                symbol = signal.get('symbol', 'N/A')
                action = signal.get('action', 'N/A')
                price = signal.get('price', 0.0)
                strat_id = signal.get('strategy_id', 'MANUAL')

                # Database Insert
                cur.execute("""
                    INSERT INTO executed_orders (timestamp, symbol, transaction_type, price, quantity, status, strategy_id)
                    VALUES (now(), %s, %s, %s, 1, 'filled', %s)
                """, (symbol, action, price, strat_id))
                conn.commit()
                
                print(f"✅ TRADE EXECUTED: {action} {symbol} at {price}")

            except json.JSONDecodeError:
                print("Skipped invalid JSON message")
            except Exception as e:
                print(f"Execution Error: {e}")
                conn.rollback()
    finally:
        c.close()
        conn.close()

if __name__ == "__main__":
    run_executor()