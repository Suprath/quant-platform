# services/strategy_runtime/tests/test_calculations_kelly.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from calculations import compute_kyle_lambda, kelly_with_market_impact

def test_kyle_lambda_positive():
    lam = compute_kyle_lambda(atr=15.0, avg_daily_volume=500000.0, tick_size=0.05)
    assert lam > 0.0

def test_kyle_lambda_formula():
    # lambda = ATR / (avg_daily_volume * tick_size)
    lam = compute_kyle_lambda(atr=10.0, avg_daily_volume=1_000_000.0, tick_size=0.05)
    expected = 10.0 / (1_000_000.0 * 0.05)
    assert abs(lam - expected) < 1e-10

def test_kelly_with_market_impact_positive_alpha():
    q = kelly_with_market_impact(
        alpha_kalman=0.002,
        lambda_hawkes=500.0,
        obi=0.6,
        spread=0.10,
        kyle_lambda=0.0002
    )
    assert q > 0, "Positive alpha + positive OBI should yield positive trade size"

def test_kelly_returns_zero_for_negative_alpha():
    q = kelly_with_market_impact(
        alpha_kalman=-0.005,
        lambda_hawkes=100.0,
        obi=0.5,
        spread=0.10,
        kyle_lambda=0.0002
    )
    assert q == 0, "Negative combined alpha should return 0 (no trade)"

def test_kelly_zero_denominator_guard():
    q = kelly_with_market_impact(
        alpha_kalman=0.001,
        lambda_hawkes=100.0,
        obi=0.5,
        spread=0.05,
        kyle_lambda=0.0
    )
    assert q == 0
