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
    from strategies.momentum import MomentumStrategy
except ImportError:
    # Fallback for Docker path issues if modules aren't top-level
    from services.strategy_runtime.schema import ensure_schema
    from services.strategy_runtime.paper_exchange import PaperExchange
    from services.strategy_runtime.strategies.momentum import MomentumStrategy

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

    # 1. Initialize DB Schema
    logger.info("Initializing Database...")
    conn = get_db_connection()
    ensure_schema(conn)
    conn.close()

    # 2. Components
    exchange = PaperExchange(DB_CONF, backtest_mode=BACKTEST_MODE, run_id=RUN_ID)
    strategy = MomentumStrategy(strategy_id="MOMENTUM_V1", backtest_mode=BACKTEST_MODE) # Dual-mode: OBI-aware

    # Topics depend on mode
    input_topic = f'market.enriched.ticks.{RUN_ID}' if BACKTEST_MODE else 'market.enriched.ticks'
    group_id = f'strategy-engine-{RUN_ID}' if BACKTEST_MODE else 'strategy-engine-v1'
    offset_reset = 'earliest' if BACKTEST_MODE else 'latest'

    consumer = Consumer({
        'bootstrap.servers': KAFKA_SERVER,
        'group.id': group_id,
        'auto.offset.reset': offset_reset
    })
    consumer.subscribe([input_topic])
    
    if BACKTEST_MODE:
        logger.info(f"🧪 BACKTEST MODE ACTIVE (Run ID: {RUN_ID})")
        logger.info(f"📊 Results will be saved to: backtest_orders, backtest_portfolios")
    
    logger.info(f"🚀 Strategy Engine Started. Listening for Ticks...")

    try:
        while True:
            msg = consumer.poll(0.1)
            if msg is None: continue
            if msg.error():
                logger.error(f"Kafka Error: {msg.error()}")
                continue
            
            try:
                # Parse Tick
                tick = json.loads(msg.value().decode('utf-8'))
                symbol = tick.get('symbol')
                
                if BACKTEST_MODE:
                    print(f"DEBUG: Processing tick for {symbol}")
                
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
                    conn = exchange._get_conn()
                    cur = conn.cursor()
                    cur.execute("SELECT symbol, quantity FROM positions WHERE quantity > 0")
                    open_positions = cur.fetchall()
                    cur.close()
                    conn.close()
                    
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
                
                # Helper: Get current position state (from DB for robustness)
                # In high-frequency, we would cache this in memory.
                current_qty = 0
                conn = exchange._get_conn()
                cur = conn.cursor()
                cur.execute("SELECT quantity FROM positions WHERE symbol = %s", (symbol,))
                res = cur.fetchone()
                if res:
                    current_qty = res[0]
                cur.close()
                conn.close()

                # Run Strategy
                signal = strategy.on_tick(tick, current_qty)
                
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

    except KeyboardInterrupt:
        logger.info("Strategy Engine stopping...")
    finally:
        consumer.close()

if __name__ == "__main__":
    run_engine()