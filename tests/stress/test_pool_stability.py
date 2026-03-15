import threading
import time
import logging
import pytest
from concurrent.futures import ThreadPoolExecutor
from db import get_db_connection, release_db_connection, _POOL

# Configure logging to see individual thread progress
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PoolStressTest")

def simulate_db_work(worker_id):
    """Worker function to simulate a database operation using the pool."""
    conn = None
    max_retries = 3
    retry_delay = 0.5
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Worker {worker_id}: Requesting connection (Attempt {attempt+1})...")
            conn = get_db_connection()
            logger.info(f"Worker {worker_id}: Connection acquired.")
            
            # Simulate simple query and processing time
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            time.sleep(0.05) # Simulate some processing overhead
            
            logger.info(f"Worker {worker_id}: Work complete.")
            return # Success
        except Exception as e:
            if "too many clients already" in str(e).lower():
                logger.warning(f"Worker {worker_id}: DB Limit hit. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                continue
            logger.error(f"Worker {worker_id}: Error: {e}")
            raise e
        finally:
            if conn:
                logger.info(f"Worker {worker_id}: Releasing connection...")
                release_db_connection(conn)
                conn = None # Reset for retry if needed
                logger.info(f"Worker {worker_id}: Connection released.")
    
    raise BlockingIOError(f"Worker {worker_id}: Failed to acquire connection after {max_retries} retries due to DB capacity.")

@pytest.mark.stress
def test_connection_pool_stress():
    """
    Stress test the PostgreSQL connection pool by launching 100 concurrent
    workers that each perform a database operation.
    """
    # The current pool size is 64. We will run 100 workers to exceed
    # the pool size and verify that the 'get_db_connection' blocking
    # and retry logic works correctly without exhaustion errors.
    num_workers = 100
    
    logger.info(f"🚀 Starting Pool Stress Test with {num_workers} workers...")
    
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        # Submit 100 workers
        futures = [executor.submit(simulate_db_work, i) for i in range(num_workers)]
        
        # Wait for all to complete and check for errors
        for future in futures:
            # This will re-raise any exception caught during execution
            future.result()

    logger.info("✅ Pool Stress Test Passed: All connections handled and released correctly.")
    
    # Final check of pool status (internal psycopg2 check if possible)
    if _POOL:
        logger.info(f"Pool status: {len(_POOL._used)} used, {len(_POOL._pool)} available.")
        assert len(_POOL._used) == 0, "Connections leaked! Pool has active 'used' connections after test."

if __name__ == "__main__":
    # Allow running directly for quick verification
    test_connection_pool_stress()
