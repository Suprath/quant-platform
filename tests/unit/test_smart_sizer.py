import pytest
from unittest.mock import MagicMock, patch
from kira_shared.models.sizing import SizingRequest, SizingResult

# We will import the sizing function from position_sizer/main.py
# Note: In conftest.py, we should have the path to position_sizer/src injected
from position_sizer.main import get_position_size

@pytest.mark.asyncio
async def test_sizer_atr_logic():
    """Verify sizer uses ATR for stop distance and sizing."""
    req = SizingRequest(
        request_id="test_1",
        symbol="RELIANCE",
        strategy_id="strat_1",
        signal_type="ENTRY",
        direction="BUY",
        entry_price=2500.0,
        confidence_score=90.0, 
        current_equity=100000.0,
        timestamp="2024-01-01T10:00:00Z"
    )
    
    # Mock fetch_daily_ranges to return a consistent range (e.g. 50 points)
    # ATR = 50. StopDist = 2 * ATR = 100.
    # Confidence 90 -> Risk 1.5% = 1500.
    # Shares = 1500 / 100 = 15.
    with patch("position_sizer.main.fetch_daily_ranges", return_value=[50.0]*14):
        with patch("position_sizer.main.cpp_core", None): # Force Python path
            result = await get_position_size(req)
            assert result.shares == 15
            assert result.exit_plan["stop_loss"] == 2400.0
            assert "py_atr" in result.exit_plan["sl_source"]

@pytest.mark.asyncio
async def test_sizer_fallback_logic():
    """Verify sizer falls back to 2% fixed stop if no volatility data."""
    req = SizingRequest(
        request_id="test_2",
        symbol="EMPTY_STOCK",
        strategy_id="strat_1",
        signal_type="ENTRY",
        direction="BUY",
        entry_price=1000.0,
        confidence_score=50.0, # Risk 0.5% = 500
        current_equity=100000.0
    )
    
    # No ranges -> ATR 0 -> Fallback to 2% SL = 20 points
    # Shares = 500 / 20 = 25
    with patch("position_sizer.main.fetch_daily_ranges", return_value=[]):
        with patch("position_sizer.main.cpp_core", None):
            result = await get_position_size(req)
            assert result.shares == 25
            assert result.exit_plan["stop_loss"] == 980.0
            assert "py_fixed_2%" in result.exit_plan["sl_source"]

@pytest.mark.asyncio
async def test_sizer_nav_constraint():
    """Verify sizer never recommends more shares than total equity permits."""
    req = SizingRequest(
        request_id="test_3",
        symbol="CHEAP_STOCK",
        strategy_id="strat_1",
        signal_type="ENTRY",
        direction="BUY",
        entry_price=1.0,
        confidence_score=100.0, # High risk
        current_equity=1000.0 # Small capital
    )
    
    # Even if math suggests more, it should be capped at NAV (1000 shares)
    with patch("position_sizer.main.fetch_daily_ranges", return_value=[0.001]*14):
        with patch("position_sizer.main.cpp_core", None):
            result = await get_position_size(req)
            assert result.shares <= 1000
