import pytest
import json
from unittest.mock import patch, MagicMock


def _make_envelope(symbol="NSE_EQ|TCS", ltp=3820.0, depth_buy=None, depth_sell=None):
    import uuid
    if depth_buy is None:
        depth_buy = [
            {"price": 3819.0, "quantity": 500},
            {"price": 3818.5, "quantity": 300},
            {"price": 3818.0, "quantity": 200},
            {"price": 3817.5, "quantity": 150},
            {"price": 3817.0, "quantity": 100},
        ]
    if depth_sell is None:
        depth_sell = [
            {"price": 3820.0, "quantity": 400},
            {"price": 3820.5, "quantity": 350},
            {"price": 3821.0, "quantity": 250},
            {"price": 3821.5, "quantity": 180},
            {"price": 3822.0, "quantity": 120},
        ]
    payload = {
        "symbol": symbol,
        "ltp": ltp,
        "v": 1000,
        "depth": {"buy": depth_buy, "sell": depth_sell},
        "timestamp": 1700000000000,
    }
    envelope = {
        "event_id": str(uuid.uuid4()),
        "event_type": "market.tick",
        "source": "upstox_ingestor",
        "payload": payload,
    }
    return json.dumps(envelope).encode()


def test_depth_frame_structure():
    """_parse_depth_frame extracts bids, asks, depth_levels, ltp correctly."""
    import main as app_module

    raw = _make_envelope()
    frame = app_module._parse_depth_frame(raw, "NSE_EQ|TCS")

    assert frame is not None
    assert frame["symbol"] == "NSE_EQ|TCS"
    assert frame["ltp"] == 3820.0
    assert frame["depth_levels"] == 5
    assert len(frame["bids"]) == 5
    assert len(frame["asks"]) == 5
    assert frame["bids"][0]["price"] == 3819.0
    assert frame["asks"][0]["price"] == 3820.0


def test_depth_frame_wrong_symbol_returns_none():
    """_parse_depth_frame returns None if the message is for a different symbol."""
    import main as app_module

    raw = _make_envelope(symbol="NSE_EQ|INFY")
    frame = app_module._parse_depth_frame(raw, "NSE_EQ|TCS")
    assert frame is None


def test_depth_frame_no_depth_returns_none():
    """_parse_depth_frame returns None if depth is empty."""
    import main as app_module

    raw = _make_envelope(depth_buy=[], depth_sell=[])
    frame = app_module._parse_depth_frame(raw, "NSE_EQ|TCS")
    assert frame is None
