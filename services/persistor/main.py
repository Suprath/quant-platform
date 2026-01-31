import os
import json
import psycopg2
import time
from confluent_kafka import Consumer
from dotenv import load_dotenv

load_dotenv()

def persist_to_questdb():
    # 1. Kafka Consumer Config
    consumer = Consumer({
        'bootstrap.servers': os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka_bus:9092'),
        'group.id': 'questdb-persistor-group',
        'auto.offset.reset': 'earliest'
    })
    consumer.subscribe(['market.equity.ticks'])

    # 2. QuestDB Connection Details
    # Host is the container name, Port 8812 is the Postgres protocol for QuestDB
    qdb_params = {
        "host": "questdb_tsdb",
        "port": 8812,
        "user": "admin",
        "password": "quest",
        "database": "qdb"
    }

    print("Connecting to QuestDB...")
    conn = None
    while conn is None:
        try:
            conn = psycopg2.connect(**qdb_params)
            print("Successfully connected to QuestDB!")
        except Exception as e:
            print(f"QuestDB not ready ({e}), retrying in 2s...")
            time.sleep(2)

    cur = conn.cursor()

    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None: continue
            if msg.error():
                print(f"Consumer error: {msg.error()}")
                continue

            # 3. Parse and Insert
            data = json.loads(msg.value().decode('utf-8'))
            
            # Match schema from PDF Page 7
            query = """
            INSERT INTO ticks (timestamp, symbol, instrument_token, ltp, volume) 
            VALUES (now(), %s, %s, %s, %s)
            """
            
            cur.execute(query, (
                data.get('symbol'), 
                data.get('symbol'), # token
                data.get('ltp'), 
                data.get('v', 0)
            ))
            conn.commit()
            print(f"Saved: {data['symbol']} @ {data['ltp']}")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        cur.close()
        conn.close()
        consumer.close()

if __name__ == "__main__":
    persist_to_questdb()