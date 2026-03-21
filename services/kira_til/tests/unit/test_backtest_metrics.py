import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
import json

# We need to mock the dependencies before importing app or functions that use them
with patch('psycopg2.connect'):
    from src.main import app

@pytest.fixture
def mock_pg_rows():
    # snapshot_time, heat_pct, full_json
    # Real DB returns DESC, so we mock DESC
    return [
        (datetime(2024, 1, 1, 15, 30), 1.2, {"total_equity": 102000.0, "cash": 102000.0}),
        (datetime(2024, 1, 1, 9, 15), 0.5, {"total_equity": 100000.0, "cash": 100000.0}),
    ]

@pytest.fixture
def mock_trade_rows():
    # pnl, price, quantity
    return [
        (500.0, 2500.0, 10),  # Win
        (-200.0, 2600.0, 5),  # Loss
        (300.0, 2450.0, 15),  # Win
    ]

@patch('psycopg2.connect')
@pytest.mark.asyncio
async def test_performance_metrics_calculation(mock_connect, mock_pg_rows, mock_trade_rows):
    # Setup mocks
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cur
    
    # Mock sequence of calls: 
    # 1. Check table exists
    # 2. Fetch snapshots
    # 3. Fetch trades
    mock_cur.fetchone.return_value = [True]
    mock_cur.fetchall.side_effect = [
        mock_pg_rows,   # First call for snapshots
        mock_trade_rows # Second call for trades
    ]

    # Call the actual function logic (we can't easily call the FastAPI endpoint async here without TestClient, 
    # but we can call the function directly if we import it)
    from src.main import get_historical_performance
    
    result = await get_historical_performance(run_id="test_run")
    
    summary = result["summary"]
    
    # Verify Metrics
    # Total Trades = 3
    assert summary["total_trades"] == 3
    
    # Winning Steps = 2 (500, 300)
    # Win Rate = 2/3 * 100 = 66.7
    assert summary["win_rate"] == 66.7
    
    # Total Gains = 800, Total Losses = 200
    # Profit Factor = 800/200 = 4.0
    assert summary["profit_factor"] == 4.0
    
    # Expectancy = (800 - 200) / 3 = 200.0
    assert summary["expectancy"] == 200.0
    
    # Net Profit = 102000 - 100000 = 2000
    assert summary["net_profit"] == 2000.0
    
    # Total PnL Pct = (102000/100000 - 1) * 100 = 2.0%
    assert summary["total_pnl_pct"] == 2.0
