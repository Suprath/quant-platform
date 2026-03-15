import pytest
import os
import sys
from unittest.mock import MagicMock

# --- Dependency Mocking for Local Execution ---
# Many modules depend on libraries available only in Docker containers.
# We mock them here to allow local pytest collection/execution.
try:
    import confluent_kafka
except ImportError:
    sys.modules['confluent_kafka'] = MagicMock()

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    sys.modules['psycopg2'] = MagicMock()
    sys.modules['psycopg2.extras'] = MagicMock()

try:
    import redis
except ImportError:
    sys.modules['redis'] = MagicMock()

# --- Path Injection ---
# We try to identify the project root and inject all service paths.
# This handles both local execution and Docker.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

possible_paths = [
    os.path.join(project_root, "services", "strategy_runtime"),
    os.path.join(project_root, "services", "position_sizer", "src"),
    os.path.join(project_root, "services", "noise_filter", "src"),
    os.path.join(project_root, "kira-shared", "src"),
    # Docker-specific mounts
    "/app",
    "/kira-shared/src",
    "/position_sizer",
    "/noise_filter"
]

for p in possible_paths:
    if os.path.exists(p) and p not in sys.path:
        sys.path.append(p)

@pytest.fixture
def mock_db_conn():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    return mock_conn

@pytest.fixture
def mock_algorithm():
    from quant_sdk.algorithm import QCAlgorithm
    algo = MagicMock(spec=QCAlgorithm)
    algo.Time = MagicMock()
    algo.Portfolio = {"Cash": 1000000.0}
    return algo
