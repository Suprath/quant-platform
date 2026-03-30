import pytest
import json
from unittest.mock import patch, MagicMock


def _make_redis_scan_response(symbols):
    keys = [f"microstructure:{s}" for s in symbols]
    return (0, keys)


def _make_redis_hgetall(alpha="0.00423", lam="14820.0", cusum_c="3.8",
                        variance="0.000142", q_star="45", kyle_lambda="0.0002",
                        symbol="NSE_EQ|RELIANCE", ts_ms="1700000000000"):
    return {
        "alpha": alpha, "lambda_hawkes": lam, "cusum_c": cusum_c,
        "variance": variance, "q_star": q_star, "kyle_lambda": kyle_lambda,
        "symbol": symbol, "ts_ms": ts_ms,
    }


def test_ws_orderflow_sends_snapshot():
    """WebSocket /ws/orderflow sends a JSON array of symbol states."""
    from starlette.testclient import TestClient
    import main as app_module

    mock_redis = MagicMock()
    mock_redis.scan.return_value = _make_redis_scan_response(["NSE_EQ|RELIANCE"])
    mock_redis.hgetall.return_value = _make_redis_hgetall()

    with patch.object(app_module, 'redis_client', mock_redis):
        client = TestClient(app_module.app)
        with client.websocket_connect("/ws/orderflow") as ws:
            data = ws.receive_text()
            payload = json.loads(data)
            assert isinstance(payload, list)
            assert len(payload) == 1
            assert payload[0]["symbol"] == "NSE_EQ|RELIANCE"
            assert "alpha" in payload[0]
            assert "cusum_c" in payload[0]
            assert "q_star" in payload[0]


def test_ws_orderflow_empty_when_redis_none():
    """WebSocket /ws/orderflow sends empty list when redis_client is None."""
    from starlette.testclient import TestClient
    import main as app_module

    with patch.object(app_module, 'redis_client', None):
        client = TestClient(app_module.app)
        with client.websocket_connect("/ws/orderflow") as ws:
            data = ws.receive_text()
            payload = json.loads(data)
            assert payload == []
