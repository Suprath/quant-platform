import pytest
import time
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timedelta
from src.backtest_logic import BacktestController

@pytest.fixture
def performance_controller():
    return BacktestController()

@pytest.mark.asyncio
async def test_backtest_execution_speed_benchmark(performance_controller):
    """
    Benchmark the execution speed of the backtest loop.
    Target: > 5000 candle-evaluations per second on standard hardware.
    """
    num_symbols = 50
    num_days = 2 # Reduced for faster test execution
    timeframe = "1m"
    ticks_per_day = 375 
    total_expected_ticks = num_symbols * num_days * ticks_per_day
    
    # 1. Mock Data
    mock_ohlc = []
    start_dt = datetime(2024, 1, 1, 9, 15)
    for d in range(num_days):
        current_day = start_dt + timedelta(days=d)
        for t in range(ticks_per_day):
            ts = current_day + timedelta(minutes=t)
            for i in range(num_symbols):
                mock_ohlc.append((f"SYM_{i}", ts, 100.0 + i, 1000))

    # 2. Mock Dependencies
    with patch.object(performance_controller, '_fetch_ohlc_bulk', return_value=mock_ohlc), \
         patch.object(performance_controller, '_fetch_noise_confidence_bulk', return_value={}), \
         patch.object(performance_controller, '_fetch_discovery_universe', return_value=[f"SYM_{i}" for i in range(num_symbols)]), \
         patch.object(performance_controller, '_check_data_completeness', return_value=False), \
         patch('src.backtest_logic.portfolio_engine') as mock_engine, \
         patch('src.backtest_logic.psycopg2.connect') as mock_pg:
        
        # Setup mock engine with AsyncMocks
        mock_state = MagicMock()
        mock_state.total_equity = 100000.0
        mock_state.total_heat_pct = 1.0
        mock_state.factor_exposure = {}
        mock_state.open_positions = []
        mock_state.json.return_value = "{}"
        
        mock_engine.get_state = AsyncMock(return_value=mock_state)
        mock_engine.clear_state = AsyncMock()
        mock_engine.mark_to_market = AsyncMock()
        mock_engine.update_position_v2 = AsyncMock()
        
        # Mock PG connection
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_pg.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cur
        
        # 3. Execution Phase
        print(f"\n🚀 Running benchmark for {total_expected_ticks} candles...")
        start_time = time.time()
        
        await performance_controller._execute_simulation(
            symbols=[f"SYM_{i}" for i in range(num_symbols)],
            start_date="2024-01-01",
            end_date="2024-01-02",
            timeframe=timeframe,
            initial_capital=100000.0,
            is_dynamic=False,
            sim_run_id="bench_run"
        )
        
        end_time = time.time()
        duration = end_time - start_time
        
        # 4. Results calculation
        candles_per_sec = total_expected_ticks / duration if duration > 0 else 0
        
        print(f"\n📊 Benchmark Stats:")
        print(f"Total Candles Processed: {total_expected_ticks}")
        print(f"Execution Duration: {duration:.4f}s")
        print(f"Throughput: {candles_per_sec:.2f} candles/sec")
        
        # Vektor simulations should now be very fast (>20,000 c/s is realistic for mocked I/O)
        assert candles_per_sec > 5000, f"Performance regression! Only achieved {candles_per_sec:.2f} candles/sec"
