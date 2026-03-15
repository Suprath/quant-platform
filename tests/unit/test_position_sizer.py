import pytest
from unittest.mock import MagicMock, patch
from kira_shared.models.sizing import SizingRequest
from position_sizer.main import get_position_size

@pytest.mark.asyncio
async def test_sizing_logic_high_confidence():
    """Test sizing with high confidence (80+) -> 1.5% risk."""
    request = SizingRequest(
        request_id="test_1",
        symbol="RELIANCE",
        strategy_id="strat_1",
        signal_type="ENTRY",
        direction="BUY",
        entry_price=2500.0,
        confidence_score=85.0,
        current_equity=1000000.0,
        timestamp="2024-01-01T10:00:00"
    )

    # Mock ATR to return a fixed value
    with patch("position_sizer.main.fetch_daily_ranges") as mock_ranges:
        # 14 days of 50 point ranges -> ATR = 50
        mock_ranges.return_value = [50.0] * 14
        
        # We ensure cpp_core is None for this test to use Python fallback logic
        with patch("position_sizer.main.cpp_core", None):
            result = await get_position_size(request)
            
            # Math:
            # risk_pct = 0.015 (85 > 80)
            # risk_amount = 1,000,000 * 0.015 = 15,000
            # stop_dist = ATR * 2 = 50 * 2 = 100
            # shares = 15,000 / 100 = 150
            assert result.shares == 150
            assert result.risk_pct_nav == 1.5
            assert result.exit_plan["stop_loss"] == 2400.0

@pytest.mark.asyncio
async def test_sizing_logic_low_confidence():
    """Test sizing with low confidence (<60) -> 0.5% risk."""
    request = SizingRequest(
        request_id="test_2",
        symbol="TCS",
        strategy_id="strat_1",
        signal_type="ENTRY",
        direction="BUY",
        entry_price=3500.0,
        confidence_score=40.0,
        current_equity=1000000.0,
        timestamp="2024-01-01T10:00:00"
    )

    with patch("position_sizer.main.fetch_daily_ranges") as mock_ranges:
        mock_ranges.return_value = [70.0] * 14 # ATR = 70
        
        with patch("position_sizer.main.cpp_core", None):
            result = await get_position_size(request)
            
            # Math:
            # risk_pct = 0.005 (40 < 60)
            # risk_amount = 1,000,000 * 0.005 = 5,000
            # stop_dist = 70 * 2 = 140
            # shares = 5,000 / 140 = 35.71 -> 35
            assert result.shares == 35
            assert result.risk_pct_nav == 0.5

@pytest.mark.asyncio
async def test_sizing_safety_cap():
    """Ensure shares never exceed total equity (no unintended leverage)."""
    request = SizingRequest(
        request_id="test_3",
        symbol="SMALLCAP",
        strategy_id="strat_1",
        signal_type="ENTRY",
        direction="BUY",
        entry_price=10.0,
        confidence_score=90.0,
        current_equity=1000.0, # Tiny equity
        timestamp="2024-01-01T10:00:00"
    )

    with patch("position_sizer.main.fetch_daily_ranges") as mock_ranges:
        # Low volatility -> Tiny stop distance
        mock_ranges.return_value = [0.01] * 14 
        
        with patch("position_sizer.main.cpp_core", None):
            result = await get_position_size(request)
            
            # Math without cap:
            # risk = 1000 * 0.015 = 15
            # sl = 0.02
            # shares = 15 / 0.02 = 750
            # Value = 750 * 10 = 7500 (7.5x equity!)
            
            # With cap:
            # max_shares = 1000 / 10 = 100
            assert result.shares == 100
            assert result.position_value <= 1000.0

@pytest.mark.asyncio
async def test_zero_volatility_fallback():
    """Test fallback to 2% SL if no historical data exists."""
    request = SizingRequest(
        request_id="test_4",
        symbol="NEWSTOCK",
        strategy_id="strat_1",
        signal_type="ENTRY",
        direction="BUY",
        entry_price=1000.0,
        confidence_score=70.0,
        current_equity=1000000.0,
        timestamp="2024-01-01T10:00:00"
    )

    with patch("position_sizer.main.fetch_daily_ranges") as mock_ranges:
        mock_ranges.return_value = [] # No data
        
        with patch("position_sizer.main.cpp_core", None):
            result = await get_position_size(request)
            
            # Math:
            # risk_pct = 0.01
            # stop_dist = 1000 * 0.02 = 20
            # shares = 10000 / 20 = 500
            assert result.shares == 500
            assert "fixed_2%" in result.exit_plan["sl_source"]
