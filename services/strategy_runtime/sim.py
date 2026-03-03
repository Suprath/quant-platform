import sys
import time
sys.path.append("/Users/suprathps/code/KIRA/services/strategy_runtime/")

# Patch aiohttp and everything web-related to avoid ImportError outside docker
try:
    import aiohttp
except ImportError:
    import sys, unittest.mock as mock
    sys.modules['aiohttp'] = mock.MagicMock()
try:
    import confluent_kafka
except ImportError:
    import sys, unittest.mock as mock
    sys.modules['confluent_kafka'] = mock.MagicMock()
try:
    import psycopg2
except ImportError:
    import sys, unittest.mock as mock
    sys.modules['psycopg2'] = mock.MagicMock()

from backtest_runner import run
print("Mock environment initialized.")
# We pass valid existing data dates to see speed
run("NSE_EQ|INE002A01018", "2024-01-01", " 2024-01-31", 500000.0, "fast")
