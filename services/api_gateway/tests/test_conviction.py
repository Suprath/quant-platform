import pytest
from unittest.mock import patch, MagicMock
from datetime import date


def _mock_pg_rows(symbol="RELIANCE", score=0.74):
    return [(
        date(2026, 3, 29), symbol, score, 1_000_000, 740_000
    )]


def test_conviction_trend_returns_list():
    """GET /api/conviction/trend/{symbol} returns a list of up to 20 rows."""
    from starlette.testclient import TestClient
    import main as app_module

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = _mock_pg_rows()
    mock_conn.cursor.return_value = mock_cur

    mock_redis = MagicMock()
    mock_redis.get.return_value = None  # cache miss

    def _override_pg():
        yield mock_conn

    app_module.app.dependency_overrides[app_module.get_pg_conn] = _override_pg

    try:
        with patch.object(app_module, 'redis_client', mock_redis):
            client = TestClient(app_module.app)
            resp = client.get("/api/conviction/trend/RELIANCE")
    finally:
        app_module.app.dependency_overrides.pop(app_module.get_pg_conn, None)

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert data[0]["symbol"] == "RELIANCE"
    assert "conviction_score" in data[0]
    assert "trade_date" in data[0]


def test_conviction_trend_uses_redis_cache():
    """Second call for same symbol returns cached result without hitting DB."""
    from starlette.testclient import TestClient
    import json
    import main as app_module

    cached = json.dumps([{"trade_date": "2026-03-29", "symbol": "TCS",
                          "conviction_score": 0.82, "total_volume": 500000,
                          "delivery_qty": 410000}])
    mock_redis = MagicMock()
    mock_redis.get.return_value = cached

    mock_conn = MagicMock()

    def _override_pg():
        yield mock_conn

    app_module.app.dependency_overrides[app_module.get_pg_conn] = _override_pg

    try:
        with patch.object(app_module, 'redis_client', mock_redis):
            client = TestClient(app_module.app)
            resp = client.get("/api/conviction/trend/TCS")
    finally:
        app_module.app.dependency_overrides.pop(app_module.get_pg_conn, None)

    assert resp.status_code == 200
    mock_conn.cursor.assert_not_called()  # DB not hit on cache hit
