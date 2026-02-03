import psycopg2
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("InstrumentPopulator")

DB_CONF = {
    "host": "postgres_metadata",
    "port": 5432,
    "user": "admin",
    "password": "password123",
    "database": "quant_platform"
}

def populate():
    try:
        conn = psycopg2.connect(**DB_CONF)
        cur = conn.cursor()

        # 1. Create Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS instruments (
                instrument_token VARCHAR(255) PRIMARY KEY,
                exchange VARCHAR(50),
                segment VARCHAR(50),
                symbol VARCHAR(50)
            );
        """)

        # 2. Insert Dummy Data (Reliance, HDFC)
        # Upstox V3 uses ISIN format for equities: NSE_EQ|INE...
        instruments = [
            ("NSE_EQ|INE002A01018", "NSE_EQ", "EQUITY", "RELIANCE"),
            ("NSE_EQ|INE040A01034", "NSE_EQ", "EQUITY", "HDFCBANK"),
            ("NSE_EQ|INE001A01036", "NSE_EQ", "EQUITY", "HDFC"), # Legacy? Keeping safe
            ("NSE_EQ|INE090A01021", "NSE_EQ", "EQUITY", "TCS"),
            ("NSE_EQ|INE009A01021", "NSE_EQ", "EQUITY", "INFY")
        ]

        for token, exch, seg, sym in instruments:
            cur.execute("""
                INSERT INTO instruments (instrument_token, exchange, segment, symbol)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (instrument_token) DO NOTHING;
            """, (token, exch, seg, sym))

        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"✅ Populated {len(instruments)} instruments into Postgres.")

    except Exception as e:
        logger.error(f"Error: {e}")

if __name__ == "__main__":
    populate()
