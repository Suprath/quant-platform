# services/strategy_runtime/tests/test_microstructure_integration.py
import sys, os

# Path to til_core compiled extension
KIRA_TIL_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'kira_til')
sys.path.insert(0, KIRA_TIL_PATH)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def test_cusum_fires_and_produces_trade_size():
    import til_core
    from symbol_registry import SymbolRegistry
    from calculations import compute_kyle_lambda, kelly_with_market_impact

    registry = SymbolRegistry(max_symbols=10)
    engine = til_core.MicrostructureEngine(10)

    key = "NSE_EQ|INE002A01018"
    sym_id = registry.register(key)
    assert sym_id == 0

    # Simulate 40 ticks of strong alpha signal
    fired = False
    for i in range(40):
        ret = 0.008
        vol = 100_000.0
        ts = float(i) * 0.1
        triggered = engine.update_tick(sym_id, ret, 0.0001, vol, ts)
        if triggered:
            fired = True
            break

    assert fired, "CUSUM should fire on 40 ticks of strong persistent signal"

    state = engine.get_state(sym_id)
    kyle_lam = compute_kyle_lambda(atr=15.0, avg_daily_volume=500_000.0)
    q = kelly_with_market_impact(
        alpha_kalman=state['alpha_kalman'],
        lambda_hawkes=state['lambda_hawkes'],
        obi=0.6,
        spread=0.10,
        kyle_lambda=kyle_lam,
    )
    assert q >= 0, "Trade size must be non-negative"
