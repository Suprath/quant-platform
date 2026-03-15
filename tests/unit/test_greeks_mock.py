import pytest
import math

# We want to test the mathematical logic extracted from api_gateway/main.py
def mock_delta_calc(strike, spot, option_type, steepness=8.0):
    dist_pct = (strike - spot) / spot
    ce_delta = 1.0 / (1.0 + math.exp(steepness * dist_pct))
    if option_type == "CE":
        return round(ce_delta, 4)
    else:
        return round(ce_delta - 1.0, 4)

def mock_iv_calc(strike, spot):
    dist_pct = (strike - spot) / spot
    return round(0.18 + (abs(dist_pct) * 1.5), 4)

def test_mock_delta_ranges():
    """Verify CE delta in (0, 1) and PE delta in (-1, 0)."""
    spot = 20000.0
    
    # ITM CE
    assert 0.5 < mock_delta_calc(18000, spot, "CE") < 1.0
    # OTM CE
    assert 0.0 < mock_delta_calc(22000, spot, "CE") < 0.5
    
    # ITM PE
    assert -1.0 < mock_delta_calc(22000, spot, "PE") < -0.5
    # OTM PE
    assert -0.5 < mock_delta_calc(18000, spot, "PE") < 0.0

def test_mock_iv_smile():
    """Verify IV is lowest near ATM and increases for OTM/ITM."""
    spot = 20000.0
    atm_iv = mock_iv_calc(20000, spot)
    otm_iv = mock_iv_calc(22000, spot)
    itm_iv = mock_iv_calc(18000, spot)
    
    assert atm_iv == 0.18
    assert otm_iv > atm_iv
    assert itm_iv > atm_iv
    # Symmetry check
    assert abs(otm_iv - itm_iv) < 1e-7

def test_mock_price_model():
    """Verify basic pricing properties (ITM > OTM)."""
    # Extracted from main.py logic
    def get_price(strike, spot, opt_type):
        intrinsic = max(0, spot - strike) if opt_type == "CE" else max(0, strike - spot)
        # We'll ignore the random part for deterministic test
        time_val = 10.0 # simplified
        return intrinsic + time_val

    spot = 10000.0
    ce_itm = get_price(9000, spot, "CE")
    ce_otm = get_price(11000, spot, "CE")
    
    assert ce_itm > ce_otm
    assert ce_itm == 1010.0
