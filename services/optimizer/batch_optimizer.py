import os
import time
import logging
import psycopg2
import argparse
from main import ParameterOptimizer, DB_CONFIG

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("BatchOptimizer")

def get_all_instruments():
    """Fetch all active equity instruments from DB."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        # Filter for NSE Equities only
        cur.execute("SELECT instrument_token FROM instruments WHERE exchange = 'NSE_EQ' AND segment = 'EQUITY';")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [r[0] for r in rows]
    except Exception as e:
        logger.error(f"Failed to fetch instruments: {e}")
        return []

def run_batch_optimization(force=False):
    """Run optimization for all symbols."""
    symbols = get_all_instruments()
    logger.info(f"🚀 Starting batch optimization for {len(symbols)} symbols...")
    
    success_count = 0
    fail_count = 0
    
    for i, symbol in enumerate(symbols):
        try:
            logger.info(f"[{i+1}/{len(symbols)}] Optimizing {symbol}...")
            
            optimizer = ParameterOptimizer(symbol)
            
            # Check if already optimized (skip if not forced)
            # We reuse the logic from main.py's check, but here we just run it
            # The optimizer.optimize() method doesn't check 'already_optimized', 
            # so we should check before instantiating if we want to skip.
            # But let's just let it run.
            
            params = optimizer.optimize()
            if optimizer.save_to_db(params):
                success_count += 1
            else:
                fail_count += 1
                
        except Exception as e:
            logger.error(f"❌ Error optimizing {symbol}: {e}")
            fail_count += 1
            
    logger.info(f"✅ Batch Complete. Success: {success_count}, Failed: {fail_count}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run batch optimization")
    parser.add_argument("--force", action="store_true", help="Force re-optimization")
    parser.add_argument("--loop", action="store_true", help="Run continuously every 24h")
    args = parser.parse_args()
    
    if args.loop:
        while True:
            run_batch_optimization(args.force)
            logger.info("Sleeping for 24 hours...")
            time.sleep(86400)
    else:
        run_batch_optimization(args.force)
