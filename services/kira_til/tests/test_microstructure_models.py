# services/kira_til/tests/test_microstructure_models.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def test_kalman_state_converges():
    """Kalman alpha should converge toward persistent drift, not noise."""
    import til_core
    engine = til_core.MicrostructureEngine(5)
    # Feed 20 ticks: constant return of 0.001 (0.1% per tick), no noise
    for i in range(20):
        engine.update_tick(0, 0.001, 0.0, 100.0, i * 1.0)
    state = engine.get_state(0)
    # After 20 identical ticks, alpha_hat should be close to 0.001
    assert abs(state['alpha_kalman'] - 0.001) < 0.0005, f"Got {state['alpha_kalman']}"

def test_hawkes_lambda_decays():
    """Hawkes lambda decays to near-zero when no new volume arrives."""
    import til_core
    engine = til_core.MicrostructureEngine(5)
    # Single large volume shock
    engine.update_tick(0, 0.0, 0.0, 1000.0, 0.0)
    state_after = engine.get_state(0)
    initial_lambda = state_after['lambda_hawkes']
    # 10 ticks with no volume, 1s apart each
    for t in range(1, 11):
        engine.update_tick(0, 0.0, 0.0, 0.0, float(t))
    decayed = engine.get_state(0)
    assert decayed['lambda_hawkes'] < initial_lambda * 0.5, "Hawkes lambda should decay"

def test_cusum_fires_on_sustained_signal():
    """CUSUM should fire (return True) when alpha consistently exceeds allowance."""
    import til_core
    engine = til_core.MicrostructureEngine(5)
    fired = False
    for i in range(50):
        # Strong persistent signal: return=0.01, variance=0.0001, so z=(0.01/0.01)=1.0 >> k
        triggered = engine.update_tick(0, 0.01, 0.0001, 100.0, float(i))
        if triggered:
            fired = True
            break
    assert fired, "CUSUM should have fired on strong persistent signal"
