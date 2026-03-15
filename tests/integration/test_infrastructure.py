import pytest
from unittest.mock import MagicMock, patch
from db import get_db_connection
from schema import ensure_schema
from engine import AlgorithmEngine

def test_db_connection_retry(mocker):
    """Test that get_db_connection retries on failure."""
    # Mock psycopg2.connect to fail twice then succeed
    mock_connect = mocker.patch("psycopg2.connect")
    mock_connect.side_effect = [Exception("Conn fail"), Exception("Conn fail"), MagicMock()]
    
    # Mock time.sleep to speed up test
    mocker.patch("time.sleep")
    
    conn = get_db_connection()
    assert mock_connect.call_count == 3
    assert conn is not None

def test_schema_integrity(mocker):
    """Verify that ensure_schema creates the expected tables."""
    conn = MagicMock()
    cur = conn.cursor.return_value
    
    ensure_schema(conn)
    
    # Check if critical tables are mentioned in execute calls
    executed_queries = [call.args[0].lower() for call in cur.execute.call_args_list]
    
    critical_tables = [
        "portfolios", 
        "positions", 
        "executed_orders", 
        "backtest_portfolios", 
        "backtest_positions", 
        "backtest_orders", 
        "backtest_universe"
    ]
    
    for table in critical_tables:
        assert any(f"create table if not exists {table}" in q for q in executed_queries), f"Missing table: {table}"

def test_kafka_topic_logic():
    """Verify Kafka topic construction based on RunID and Mode."""
    # 1. LIVE Mode
    engine_live = AlgorithmEngine(run_id="live_run", backtest_mode=False)
    # We don't call SetupKafka because it tries to connect to real Kafka
    # But we check the internal logic if we can access it or mock it
    
    # Let's mock the Consumer to see what it subscribes to
    with patch("engine.Consumer") as mock_consumer_cls:
        mock_consumer = mock_consumer_cls.return_value
        engine_live.SetupKafka()
        
        args, _ = mock_consumer.subscribe.call_args
        subscribed_topics = args[0]
        assert "market.enriched.ticks" in subscribed_topics
        
    # 2. BACKTEST Mode
    engine_bt = AlgorithmEngine(run_id="bt_123", backtest_mode=True)
    with patch("engine.Consumer") as mock_consumer_cls:
        mock_consumer = mock_consumer_cls.return_value
        engine_bt.SetupKafka()
        
        args, _ = mock_consumer.subscribe.call_args
        subscribed_topics = args[0]
        assert "market.enriched.ticks.bt_123" in subscribed_topics
