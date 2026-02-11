import os
import time
import logging
import psycopg2
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("DB")

DB_CONF = {
    "host": os.getenv("POSTGRES_HOST", "postgres_metadata"),
    "port": 5432,
    "user": "admin",
    "password": "password123",
    "database": "quant_platform"
}

def get_db_connection():
    while True:
        try:
            conn = psycopg2.connect(**DB_CONF)
            return conn
        except Exception:
            logger.warning("Postgres not ready, retrying...")
            time.sleep(2)
