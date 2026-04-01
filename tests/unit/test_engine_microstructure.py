"""Tests for engine._publish_microstructure — mirrors test_redis_publishing.py logic."""
import pytest
from unittest.mock import patch, MagicMock
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def _make_tick(symbol="NSE_EQ|RELIANCE", ltp=2480.0, volume=1000.0, prev_price=2470.0):
    return {
        "instrument_key": symbol,
        "ltp": ltp,
        "volume": volume,
        "prev_price": prev_price,
        "obi": 0.3,
        "exchange_timestamp": 1700000000000,
        "atr": 15.0,
        "bid_price": 2479.0,
        "ask_price": 2481.0,
    }


def test_engine_redis_hash_written_after_tick():
    """engine._publish_microstructure writes microstructure:{symbol} hash to Redis."""
    import engine as eng

    mock_redis = MagicMock()
    mock_micro = MagicMock()
    mock_micro.update_tick.return_value = False
    mock_micro.get_state.return_value = {
        "alpha_kalman": 0.00423,
        "lambda_hawkes": 14820.0,
        "cusum_c": 3.8,
        "variance": 0.000142,
    }
    mock_registry = MagicMock()
    mock_registry.register.return_value = 0

    with patch.object(eng, '_MICRO_ENGINE', mock_micro), \
         patch.object(eng, '_SYM_REGISTRY', mock_registry), \
         patch.object(eng, '_HAS_MICRO_ENGINE', True), \
         patch.object(eng, '_REDIS', mock_redis):
        eng._publish_microstructure(_make_tick())

    mock_redis.hset.assert_called_once()
    call_args = mock_redis.hset.call_args
    key = call_args[0][0]
    assert key == "microstructure:NSE_EQ|RELIANCE"
    mapping = call_args[1].get("mapping") or call_args[0][1]
    assert "alpha" in mapping
    assert "lambda_hawkes" in mapping
    assert "cusum_c" in mapping
    assert isinstance(mapping["alpha"], str)
    assert isinstance(mapping["lambda_hawkes"], str)


def test_engine_cusum_fire_published():
    """When CUSUM fires, engine._publish_microstructure publishes to cusum-fires channel."""
    import engine as eng

    mock_redis = MagicMock()
    mock_micro = MagicMock()
    mock_micro.update_tick.return_value = True  # fire!
    mock_micro.get_state.return_value = {
        "alpha_kalman": 0.00423,
        "lambda_hawkes": 14820.0,
        "cusum_c": 0.0,
        "variance": 0.000142,
    }
    mock_registry = MagicMock()
    mock_registry.register.return_value = 0

    with patch.object(eng, '_MICRO_ENGINE', mock_micro), \
         patch.object(eng, '_SYM_REGISTRY', mock_registry), \
         patch.object(eng, '_HAS_MICRO_ENGINE', True), \
         patch.object(eng, '_REDIS', mock_redis):
        eng._publish_microstructure(_make_tick())

    mock_redis.publish.assert_called_once()
    channel = mock_redis.publish.call_args[0][0]
    assert channel == "cusum-fires"


def test_engine_redis_none_does_not_crash():
    """If _REDIS is None, _publish_microstructure completes silently."""
    import engine as eng

    mock_micro = MagicMock()
    mock_micro.update_tick.return_value = False
    mock_micro.get_state.return_value = {
        "alpha_kalman": 0.0, "lambda_hawkes": 0.0, "cusum_c": 0.0, "variance": 0.0,
    }
    mock_registry = MagicMock()
    mock_registry.register.return_value = 0

    with patch.object(eng, '_MICRO_ENGINE', mock_micro), \
         patch.object(eng, '_SYM_REGISTRY', mock_registry), \
         patch.object(eng, '_HAS_MICRO_ENGINE', True), \
         patch.object(eng, '_REDIS', None):
        eng._publish_microstructure(_make_tick())  # must not raise


def test_engine_no_publish_on_normal_tick():
    """When CUSUM does NOT fire, Redis publish is NOT called."""
    import engine as eng

    mock_redis = MagicMock()
    mock_micro = MagicMock()
    mock_micro.update_tick.return_value = False
    mock_micro.get_state.return_value = {
        "alpha_kalman": 0.001, "lambda_hawkes": 5000.0, "cusum_c": 1.2, "variance": 0.0001,
    }
    mock_registry = MagicMock()
    mock_registry.register.return_value = 0

    with patch.object(eng, '_MICRO_ENGINE', mock_micro), \
         patch.object(eng, '_SYM_REGISTRY', mock_registry), \
         patch.object(eng, '_HAS_MICRO_ENGINE', True), \
         patch.object(eng, '_REDIS', mock_redis):
        eng._publish_microstructure(_make_tick())

    mock_redis.hset.assert_called_once()
    mock_redis.publish.assert_not_called()


def test_engine_symbol_field_fallback():
    """Falls back to 'symbol' field when instrument_key is absent."""
    import engine as eng

    mock_redis = MagicMock()
    mock_micro = MagicMock()
    mock_micro.update_tick.return_value = False
    mock_micro.get_state.return_value = {
        "alpha_kalman": 0.001, "lambda_hawkes": 100.0, "cusum_c": 0.5, "variance": 0.00005,
    }
    mock_registry = MagicMock()
    mock_registry.register.return_value = 1

    tick = _make_tick()
    del tick["instrument_key"]
    tick["symbol"] = "NSE_EQ|INFY"

    with patch.object(eng, '_MICRO_ENGINE', mock_micro), \
         patch.object(eng, '_SYM_REGISTRY', mock_registry), \
         patch.object(eng, '_HAS_MICRO_ENGINE', True), \
         patch.object(eng, '_REDIS', mock_redis):
        eng._publish_microstructure(tick)

    key = mock_redis.hset.call_args[0][0]
    assert key == "microstructure:NSE_EQ|INFY"
