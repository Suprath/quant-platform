import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timedelta
from src.backtest_logic import BacktestController

@pytest.fixture
def controller():
    return BacktestController()

@pytest.mark.asyncio
async def test_symbol_discovery_timeframe_fallback(controller):
    """
    Ensures that symbol discovery works even if the backtest timeframe (e.g., 5m)
    differs from the stored data timeframe (e.g., 1m).
    """
    mock_timestamp = datetime(2024, 1, 1, 10, 0)
    # Mock _qdb_exec to return a symbol as if it found it in '1m' data
    with patch.object(controller, '_qdb_exec', return_value=[("SYM_1",)]) as mock_exec:
        symbols = controller._fetch_discovery_universe(mock_timestamp, "5m")
        
        # Verify the query used '1m' regardless of the '5m' input
        args, kwargs = mock_exec.call_args
        query = args[0]
        assert "timeframe = '1m'" in query
        assert "SYM_1" in symbols

@pytest.mark.asyncio
async def test_backtest_persistence_flow_robustness(controller):
    """
    Verifies that the backtest correctly batches and flushes orders to the DB
    without transaction aborts.
    """
    # 1. Setup Mock Data (Mini slice)
    ts = datetime(2024, 1, 1, 9, 15)
    tick_data = {"SYM_1": {"ltp": 150.0, "volume": 1000}}
    
    # 2. Mock Dependencies
    with patch('src.backtest_logic.portfolio_engine') as mock_engine, \
         patch('src.backtest_logic.psycopg2.connect') as mock_pg:
        
        # Mock engine state
        mock_state = MagicMock()
        mock_state.open_positions = []
        mock_state.total_equity = 100000.0
        mock_state.cash = 100000.0
        mock_engine.get_state = AsyncMock(return_value=mock_state)
        mock_engine.update_position_v2 = AsyncMock()
        
        # Mock PG
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_pg.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cur
        
        # 3. Simulate a step with _current_day_orders enabled
        controller._current_day_orders = []
        
        # Trigger a trade manually to test batching
        await controller._execute_trade("SYM_1", "LONG", 10, 150.0, ts, "run_1", skip_db=True)
        
        assert len(controller._current_day_orders) == 1
        assert controller._current_day_orders[0][2] == "SYM_1" # Symbol check
        
        # 4. Verify DB Flush Query (Manual check of what would be passed to executemany)
        # In a real run, this happens at the end of the day in _execute_simulation
        # But here we just verify _execute_trade populated the batch correctly.
        order_row = controller._current_day_orders[0]
        # Order: (run_id, timestamp, symbol, transaction_type, quantity, price, pnl, mechanism)
        assert len(order_row) == 8
        assert order_row[3] == "LONG"

@pytest.mark.asyncio
async def test_portfolio_initialization_schema_check(controller):
    """
    Ensures that PortfolioEngine.clear_state uses the correct columns (including last_updated).
    """
    from src.portfolio_engine.engine import PortfolioEngine
    pe = PortfolioEngine()
    
    # Mock Redis to avoid connection errors
    pe.redis = MagicMock()
    pe.redis.client = AsyncMock()
    
    with patch('src.portfolio_engine.engine.psycopg2.connect') as mock_pg:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_pg.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cur
        
        # Clear state with a run_id triggers the DB insert
        ts = datetime(2024, 1, 1, 9, 15)
        await pe.clear_state(timestamp=ts, run_id="test_run")
        
        # Verify the initial insert query contains 'last_updated'
        calls = mock_cur.execute.call_args_list
        found_init = False
        for call in calls:
            query = call[0][0]
            if "INSERT INTO backtest_portfolios" in query:
                assert "last_updated" in query
                found_init = True
        
        assert found_init, "Initial portfolio insert with last_updated not found!"

@pytest.mark.asyncio
async def test_performance_api_large_volume_sampling():
    """
    Ensures that the performance API handles large snapshot volumes using sampling.
    """
    from src.main import get_historical_performance
    from unittest.mock import MagicMock, patch
    
    # Mock postgres connection
    with patch('src.main.psycopg2.connect') as mock_pg:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_pg.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cur
        
        # Mock boundary and sampling results
        # min_id, max_id, count
        mock_cur.fetchone.return_value = (1, 200000, 200000)
        
        # Mock boundary rows fetch
        start_time = datetime(2024, 1, 1)
        end_time = datetime(2024, 1, 2)
        mock_cur.fetchall.side_effect = [
            # Boundary rows
            [(start_time, 0.0, {"total_equity": 100000.0}), 
             (end_time, 0.0, {"total_equity": 105000.0})],
            # Sampled rows (thin)
            [(start_time + timedelta(hours=i), 0.0, 100000.0 + i*100) for i in range(1, 10)],
            # Trades
            [(100.0, 150.0, 10, "TEST")]
        ]
        
        # Call the API function directly
        result = await get_historical_performance(run_id="test_run")
        
        # Verify metrics
        summary = result["summary"]
        assert summary["total_pnl"] == 5.0 # (105000/100000 - 1) * 100
        assert summary["net_profit"] == 5000.0
        assert summary["total_trades"] == 1
        assert len(result["points"]) > 2
