import os
import time
import logging
import psycopg2
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from psycopg2 import pool

import threading

logger = logging.getLogger("DB")

DB_CONF = {
    "host": os.getenv("POSTGRES_HOST", "postgres_metadata"),
    "port": int(os.getenv("POSTGRES_PORT", 5432)),
    "user": os.getenv("POSTGRES_USER", "admin"),
    "password": os.getenv("POSTGRES_PASSWORD", "changeme123"),
    "database": os.getenv("POSTGRES_DB", "quant_platform"),
}

_POOL = None
_DB_LOCK = threading.Lock()

def get_db_connection():
    global _POOL
    if _POOL is None:
        with _DB_LOCK:
            if _POOL is None:
                try:
                    _POOL = pool.ThreadedConnectionPool(1, 64, **DB_CONF)
                    logger.info("✅ Postgres Connection Pool Initialized")
                except Exception as e:
                    logger.error(f"Failed to init PG Pool: {e}")
                    # Fallback to single connection if pool fails
                    return psycopg2.connect(**DB_CONF)
    
    return _POOL.getconn()

def release_db_connection(conn):
    if _POOL:
        try:
            _POOL.putconn(conn)
        except pool.PoolError:
            conn.close()
    else:
        conn.close()
