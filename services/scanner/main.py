import os
import argparse
import requests
import json
import time
import psycopg2
import logging
from datetime import datetime, timedelta
from confluent_kafka import Producer
from dotenv import load_dotenv

import sys
load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s',
    stream=sys.stderr
)
logger = logging.getLogger("MarketScanner")

# Kafka Configuration
KAFKA_SERVER = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka_bus:9092')
p = Producer({'bootstrap.servers': KAFKA_SERVER})

DB_CONF = {
    "host": "postgres_metadata",
    "port": 5432,
    "user": "admin",
    "password": "password123",
    "database": "quant_platform"
}

def get_db_connection():
    try:
        return psycopg2.connect(**DB_CONF)
    except Exception as e:
        logger.error(f"DB Connection Error: {e}")
        return None

def ensure_table():
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS scanner_results (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    symbol VARCHAR(50),
                    score DOUBLE PRECISION,
                    ltp DOUBLE PRECISION,
                    volume BIGINT
                );
            """)
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.error(f"Table Creation Error: {e}")

def get_watchlist():
    """Get the Top 100 NSE stocks from our synchronized Dictionary"""
    try:
        conn = get_db_connection()
        if not conn: return []
        cur = conn.cursor()
        # We pick 100 stocks from NSE_EQ segment
        cur.execute("SELECT instrument_token FROM instruments WHERE exchange = 'NSE_EQ' AND segment = 'EQUITY' LIMIT 100;")
        symbols = [r[0] for r in cur.fetchall()]
        cur.close()
        conn.close()
        return symbols
    except Exception as e:
        logger.error(f"Postgres Error: {e}")
        return []

def scan():
    ensure_table() # Ensure table exists before writing
    
    token = os.getenv('UPSTOX_ACCESS_TOKEN')
    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {token}'}
    
    watchlist = get_watchlist()
    if not watchlist:
        logger.warning("Watchlist empty. Is Instrument Sync complete?")
        return

    # Upstox API allows 100 symbols per request
    symbol_str = ",".join(watchlist)
    url = f"https://api.upstox.com/v2/market-quote/quotes?symbol={symbol_str}"

    try:
        logger.info("Scanning 100 stocks for opportunities...")
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            data = response.json().get('data', {})
            scored_stocks = []

            for key, val in data.items():
                # QUANT LOGIC: Momentum = % Change * Relative Volume
                # For simplicity here: Abs % Change from close
                ltp = val.get('last_price', 0)
                cp = val.get('close', 1)
                volume = val.get('volume', 0)
                
                change_pct = abs((ltp - cp) / cp) * 100
                score = change_pct * volume
                
                scored_stocks.append({"symbol": key, "score": score, "ltp": ltp, "volume": volume})

            # Sort by highest momentum score
            top_opportunities = sorted(scored_stocks, key=lambda x: x['score'], reverse=True)[:5]
            
            # 1. Save to DB for Grafana
            conn = get_db_connection()
            if conn:
                cur = conn.cursor()
                for stock in top_opportunities:
                    cur.execute("""
                        INSERT INTO scanner_results (symbol, score, ltp, volume)
                        VALUES (%s, %s, %s, %s)
                    """, (stock['symbol'], stock['score'], stock['ltp'], stock['volume']))
                conn.commit()
                cur.close()
                conn.close()
            
            # 2. Send to Kafka
            suggestion = [s['symbol'] for s in top_opportunities]
            p.produce('scanner.suggestions', value=json.dumps(suggestion))
            p.flush()
            
            logger.info(f"🔥 Top Opportunities Saved & Sent: {suggestion}")
        else:
            logger.error(f"API Error: {response.status_code}")
            
    except Exception as e:
        logger.error(f"Scan Loop Error: {e}")

if __name__ == "__main__":
    import math
    import urllib.parse
    
    parser = argparse.ArgumentParser(description="Market Scanner for Stock Selection")
    parser.add_argument("--date", type=str, help="Target date for historical scan (YYYY-MM-DD)")
    parser.add_argument("--top-n", type=int, default=5, help="Number of top stocks to select")
    parser.add_argument("--output", type=str, choices=["json", "symbols"], default="json")
    parser.add_argument("--live", action="store_true", help="Run in live continuous mode")
    args = parser.parse_args()
    
    if args.date:
        # Historical mode for backtesting
        logger.info(f"📊 Historical scan for {args.date}...")
        QUESTDB_URL = os.getenv('QUESTDB_URL', 'http://questdb_tsdb:9000')
        query = f"""
        SELECT symbol, first(open) as open_price, max(high) - min(low) as day_range, sum(volume) as total_volume
        FROM ohlc WHERE timestamp >= '{args.date}T03:45:00.000000Z' AND timestamp <= '{args.date}T10:00:00.000000Z'
        GROUP BY symbol
        """
        try:
            encoded = urllib.parse.urlencode({"query": query})
            resp = requests.get(f"{QUESTDB_URL}/exec?{encoded}")
            if resp.status_code == 200:
                dataset = resp.json().get('dataset', [])
                scored = []
                for row in dataset:
                    sym, op, dr, vol = row
                    if op and op > 0:
                        range_pct = (dr / op) * 100
                        score = range_pct * math.log10(max(vol, 1))
                        scored.append({"symbol": sym, "score": round(score, 2), "range_pct": round(range_pct, 2)})
                top = sorted(scored, key=lambda x: x['score'], reverse=True)[:args.top_n]
                if args.output == "json":
                    print(json.dumps(top, indent=2))
                else:
                    print(",".join([s['symbol'] for s in top]))
            else:
                logger.error(f"QuestDB Error: {resp.status_code}")
        except Exception as e:
            logger.error(f"Historical Scan Error: {e}")
    elif args.live:
        while True:
            scan()
            logger.info("Next scan in 5 minutes...")
            time.sleep(300)
    else:
        scan()