import os
import json
import time
import logging
import psycopg2
from datetime import datetime, time as dt_time
from confluent_kafka import Consumer
from dotenv import load_dotenv

# Internal Modules
try:
    from schema import ensure_schema
    from paper_exchange import PaperExchange
    from strategies.orb import EnhancedORB
except ImportError:
    # Fallback for Docker path issues if modules aren't top-level
    from services.strategy_runtime.schema import ensure_schema
    from services.strategy_runtime.paper_exchange import PaperExchange
    from services.strategy_runtime.strategies.orb import EnhancedORB

load_dotenv()

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)
logger = logging.getLogger("StrategyRuntime")

# Config
KAFKA_SERVER = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka_bus:9092')
BACKTEST_MODE = os.getenv('BACKTEST_MODE', 'false').lower() == 'true'
RUN_ID = os.getenv('RUN_ID', f'backtest_{datetime.now().strftime("%Y%m%d_%H%M%S")}')

DB_CONF = {
    "host": "postgres_metadata",
    "port": 5432,
    "user": "admin",
    "password": "password123",
    "database": "quant_platform"
}

def ensure_topics():
    """Auto-create topics if they don't exist"""
    from confluent_kafka.admin import AdminClient, NewTopic
    a = AdminClient({'bootstrap.servers': KAFKA_SERVER})
    
    # Base topics
    base_topics = ["market.enriched.ticks", "strategy.signals"]
    
    # Run-specific topics for backtest
    run_topics = []
    if RUN_ID and BACKTEST_MODE:
        run_topics = [f"market.enriched.ticks.{RUN_ID}"]
    
    topics_to_create = base_topics + run_topics
    
    logger.info(f"Ensuring Kafka topics: {topics_to_create}")
    new_topics = [NewTopic(t, num_partitions=1, replication_factor=1) for t in topics_to_create]
    
    fs = a.create_topics(new_topics)
    for topic, f in fs.items():
        try:
            f.result()
            logger.info(f"Topic {topic} created")
        except Exception as e:
            if "already exists" in str(e).lower():
                continue
            logger.warning(f"Failed to create topic {topic}: {e}")

# --- WAIT FOR KAFKA ---
def wait_for_kafka():
    """Blocks until Kafka is ready."""
    from confluent_kafka.admin import AdminClient
    admin = AdminClient({'bootstrap.servers': KAFKA_SERVER})
    
    logger.info(f"Connecting to Kafka at {KAFKA_SERVER}...")
    while True:
        try:
            # list_topics is a blocking network call that will verify connectivity
            cluster_metadata = admin.list_topics(timeout=3.0)
            if cluster_metadata.topics:
                logger.info("✅ Connected to Kafka.")
                break
        except Exception as e:
            logger.warning(f"Waiting for Kafka... ({e})")
            time.sleep(2)

def get_db_connection():
    while True:
        try:
            conn = psycopg2.connect(**DB_CONF)
            return conn
        except Exception:
            logger.warning("Postgres not ready, retrying...")
            time.sleep(2)

def run_engine():
    # 0. Wait for Kafka
    wait_for_kafka()
    ensure_topics()

    # 1. Initialize DB Schema
    logger.info("Initializing Database...")
    conn = get_db_connection()
    ensure_schema(conn)
    conn.close()

    # 2. Components
    exchange = PaperExchange(DB_CONF, backtest_mode=BACKTEST_MODE, run_id=RUN_ID)
    strategy = EnhancedORB(strategy_id="ORB_V1", orb_minutes=15, backtest_mode=BACKTEST_MODE)

    # Topics depend on mode
    input_topic = f'market.enriched.ticks.{RUN_ID}' if BACKTEST_MODE else 'market.enriched.ticks'
    group_id = f'strategy-engine-{RUN_ID}' if BACKTEST_MODE else 'strategy-engine-v4'
    offset_reset = 'earliest' if BACKTEST_MODE else 'latest'

    def on_assign(consumer, partitions):
        logger.info(f"✅ Kafka Consumer Assigned Partitions: {partitions}")

    logger.info(f"🛠 Initializing Kafka Consumer: Topic={input_topic}, Group={group_id}, Offset={offset_reset}")
    consumer = Consumer({
        'bootstrap.servers': KAFKA_SERVER,
        'group.id': group_id,
        'auto.offset.reset': offset_reset
    })
    consumer.subscribe([input_topic], on_assign=on_assign)
    
    if BACKTEST_MODE:
        logger.info(f"🧪 BACKTEST MODE ACTIVE (Run ID: {RUN_ID})")
        logger.info(f"📊 Results will be saved to: backtest_orders, backtest_portfolios")
    
    logger.info(f"🚀 Strategy Engine Started. Listening for Ticks on {input_topic} (Group: {group_id})...")

    last_heartbeat = 0
    conn = get_db_connection()
    try:
        while True:
            # Heartbeat every 30s
            if time.time() - last_heartbeat > 30:
                logger.info("💓 Strategy Runtime Heartbeat: Polling Kafka...")
                last_heartbeat = time.time()

            msg = consumer.poll(1.0)
            if msg is None: continue
            
            if msg.error():
                logger.error(f"Kafka Error: {msg.error()}")
                continue
            
            try:
                # Parse Tick
                tick = json.loads(msg.value().decode('utf-8'))
                symbol = tick.get('symbol')
                
                # Check for stale connection
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT 1")
                    cur.close()
                except:
                    logger.warning("Reconnecting to database...")
                    conn = get_db_connection()

                # === INTRADAY COMPLIANCE: EOD SQUARE-OFF ===
                if BACKTEST_MODE:
                    # In backtest, use tick's timestamp (ms)
                    tick_ts = tick.get('timestamp', 0) / 1000
                    now_dt = datetime.fromtimestamp(tick_ts)
                else:
                    # In live, use actual system time
                    now_dt = datetime.now()
                
                current_time = now_dt.time()
                eod_cutoff = dt_time(15, 20)  # 3:20 PM IST
                
                # If after 3:20 PM, force close all positions
                if current_time >= eod_cutoff:
                    cur = conn.cursor()
                    cur.execute("SELECT symbol, quantity FROM positions WHERE quantity > 0")
                    open_positions = cur.fetchall()
                    cur.close()
                    
                    if open_positions:
                        logger.warning(f"⏰ EOD Cutoff Reached. Squaring off {len(open_positions)} positions...")
                        for pos_symbol, qty in open_positions:
                            eod_signal = {
                                "strategy_id": "EOD_SQUAREOFF",
                                "symbol": pos_symbol,
                                "action": "SELL",
                                "price": tick.get('ltp', 0)
                            }
                            exchange.execute_order(eod_signal)
                            logger.info(f"🔒 Squared off {pos_symbol}")
                    continue  # Skip normal strategy after EOD
                
                # 2. Get Account State (Balance & Position)
                cur = conn.cursor()
                positions_table = "backtest_positions" if BACKTEST_MODE else "positions"
                portfolios_table = "backtest_portfolios" if BACKTEST_MODE else "portfolios"
                
                if BACKTEST_MODE:
                    cur.execute(f"SELECT id, balance FROM {portfolios_table} WHERE user_id = %s AND run_id = %s", ('default_user', RUN_ID))
                else:
                    cur.execute(f"SELECT id, balance FROM {portfolios_table} WHERE user_id = %s", ('default_user',))
                
                row = cur.fetchone()
                if row:
                    pid, balance = row[0], float(row[1])
                else:
                    pid, balance = None, 20000.0

                current_qty = 0
                avg_price = 0.0
                if pid:
                    cur.execute(f"SELECT quantity, avg_price FROM {positions_table} WHERE portfolio_id = %s AND symbol = %s", (pid, symbol))
                    pos_row = cur.fetchone()
                    if pos_row:
                        current_qty = int(pos_row[0])
                        avg_price = float(pos_row[1])
                cur.close()

                # === STRATEGY EXECUTION ===
                signal = strategy.on_tick(tick, current_qty, balance=balance, avg_price=avg_price)
                
                # Execute Signal (if any)
                if signal:
                    logger.info(f"⚡ SIGNAL RECEIVED: {signal}")
                    success = exchange.execute_order(signal)
                    if success:
                        logger.info(f"✅ ORDER FILLED: {signal['action']} {signal['symbol']}")
                    else:
                        logger.error(f"❌ ORDER FAILED: {signal['symbol']}")

            except json.JSONDecodeError:
                continue
            except Exception as e:
                logger.error(f"Engine Loop Error: {e}")
                # Don't crash the whole engine on a single tick error
    except KeyboardInterrupt:
        logger.info("Strategy Engine stopping...")
    finally:
        if conn: conn.close()
        consumer.close()

if __name__ == "__main__":
    run_engine()