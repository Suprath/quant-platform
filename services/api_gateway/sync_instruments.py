import os
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values # Performance boost
import io
import requests
from dotenv import load_dotenv

load_dotenv()

def sync_from_upstox():
    URL = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
    
    print("Downloading Instrument Master...")
    try:
        response = requests.get(URL, headers=headers, timeout=30)
        df = pd.read_csv(io.BytesIO(response.content), compression='gzip')
        
        # Filter for NSE/BSE
        df = df[df['exchange'].isin(['NSE_EQ', 'NSE_INDEX', 'BSE_EQ', 'BSE_INDEX'])]

        # Clean data: Replace NaN with safe defaults
        df['lot_size'] = pd.to_numeric(df['lot_size'], errors='coerce').fillna(1).astype(int)
        df['tick_size'] = pd.to_numeric(df['tick_size'], errors='coerce').fillna(0.05)
        df['name'] = df['name'].fillna(df['tradingsymbol'])

        conn = psycopg2.connect(
            host="postgres_metadata", port=5432, user="admin", password="password123", database="quant_platform"
        )
        cur = conn.cursor()
        
        print("Clearing old data...")
        cur.execute("TRUNCATE TABLE instruments;")

        # Prepare data for bulk insert
        # We match: instrument_token, exchange_token, tradingsymbol, name, exchange, segment, lot_size, tick_size
        values = []
        for _, r in df.iterrows():
            values.append((
                r['instrument_key'],
                str(r['exchange_token']),
                r['tradingsymbol'],
                r['name'],
                r['exchange'],
                r['instrument_type'],
                int(r['lot_size']),
                float(r['tick_size'])
            ))

        print(f"Bulk syncing {len(values)} instruments...")
        insert_query = """
            INSERT INTO instruments 
            (instrument_token, exchange_token, tradingsymbol, name, exchange, segment, lot_size, tick_size)
            VALUES %s
        """
        execute_values(cur, insert_query, values)
        
        conn.commit()
        print(f"✅ SUCCESS: {len(values)} instruments synchronized.")
        
    except Exception as e:
        print(f"❌ Sync Error: {e}")
    finally:
        if 'conn' in locals(): conn.close()

if __name__ == "__main__":
    sync_from_upstox()