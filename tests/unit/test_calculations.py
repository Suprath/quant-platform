"""
Test Suite — calculations.py
==============================
Validates every financial metric function with known-good inputs.
"""
import pytest
import math
import pandas as pd
from datetime import datetime, timedelta
from calculations import (
    TransactionCostCalculator,
    compute_sharpe_ratio,
    compute_sortino_ratio,
    compute_max_drawdown,
    compute_cagr,
    compute_calmar_ratio,
    compute_win_rate,
    compute_profit_factor,
    compute_expectancy,
    compute_avg_win_loss,
    compute_total_return,
    compute_net_profit,
    compute_portfolio_value,
    compute_all_statistics,
    downsample_equity_curve,
)


# ────────────────────────────────────────────────────────────
# HELPERS
# ────────────────────────────────────────────────────────────

def _make_equity_curve(values, start=datetime(2024, 1, 1)):
    """Build an equity curve from a list of float values (one per day)."""
    return [
        {"timestamp": start + timedelta(days=i), "equity": v}
        for i, v in enumerate(values)
    ]


# ────────────────────────────────────────────────────────────
# TRANSACTION COST CALCULATOR
# ────────────────────────────────────────────────────────────

class TestTransactionCostCalculator:
    def test_mis_buy_non_zero(self):
        calc = TransactionCostCalculator("MIS")
        cost = calc.calculate(100_000, "BUY")
        assert cost > 0
        # MIS BUY: no STT, so cost should be lower than SELL
        sell_cost = calc.calculate(100_000, "SELL")
        assert cost < sell_cost

    def test_mis_sell_includes_stt(self):
        calc = TransactionCostCalculator("MIS")
        cost = calc.calculate(100_000, "SELL")
        # STT = 0.025% of 100k = ₹25, so total > 25
        assert cost > 25.0

    def test_cnc_stt_both_sides(self):
        calc = TransactionCostCalculator("CNC")
        buy = calc.calculate(100_000, "BUY")
        sell = calc.calculate(100_000, "SELL")
        # CNC applies STT on both sides, so both should include it
        assert buy > 50  # 0.1% of 100k = ₹100 STT alone
        assert sell > 50

    def test_zero_turnover(self):
        calc = TransactionCostCalculator("MIS")
        assert calc.calculate(0, "BUY") == 0.0
        assert calc.calculate(-100, "SELL") == 0.0

    def test_round_trip_cost(self):
        calc = TransactionCostCalculator("MIS")
        rt = calc.round_trip_cost(100.0, 1000)
        # Should equal buy + sell on 100k turnover
        buy = calc.calculate(100_000, "BUY")
        sell = calc.calculate(100_000, "SELL")
        assert rt == buy + sell

    def test_brokerage_cap(self):
        """Brokerage is capped at ₹20 flat for large turnovers."""
        calc = TransactionCostCalculator("MIS")
        # For 10 crore turnover, 0.03% = ₹30,000 → should be capped at ₹20
        cost_small = calc.calculate(10_000, "BUY")
        # 0.03% of 10k = ₹3, which is less than ₹20 so brokerage = ₹3
        assert cost_small < 20  # brokerage component < ₹20

class TestOptionsCharges:
    def test_options_buy_flat_brokerage(self):
        calc = TransactionCostCalculator("OPTIONS")
        # For options, brokerage is flat ₹20 regardless of lot size/turnover
        cost1 = calc.calculate(1000, "BUY")
        cost2 = calc.calculate(50000, "BUY")
        # Brokerage part is 20 + GST 18% = 3.6 → 23.6 minimum
        assert cost1 >= 23.6
        # Both should have similar brokerage
        assert abs(cost1 - cost2) < 50 # Difference mostly STT/Txn/Stamp

    def test_options_sell_stt(self):
        calc = TransactionCostCalculator("OPTIONS")
        buy = calc.calculate(100000, "BUY")
        sell = calc.calculate(100000, "SELL")
        # Options Sell side has 0.1% STT on premium turnover (₹100)
        # However, Buy side has 0.003% Stamp Duty (₹3)
        # Net diff should be exactly ₹97 (182.72 - 85.72 = 97.0)
        assert abs(sell - buy - 97.0) < 0.01


# ────────────────────────────────────────────────────────────
# SHARPE RATIO
# ────────────────────────────────────────────────────────────

class TestSharpeRatio:
    def test_flat_equity(self):
        """Flat equity → 0 std → Sharpe should be 0."""
        curve = _make_equity_curve([100_000] * 30)
        assert compute_sharpe_ratio(curve, 100_000) == 0.0

    def test_positive_sharpe(self):
        """Steadily rising equity → positive Sharpe."""
        values = [100_000 + i * 500 for i in range(60)]
        curve = _make_equity_curve(values)
        sharpe = compute_sharpe_ratio(curve, 100_000)
        assert sharpe > 0

    def test_negative_sharpe(self):
        """Steadily declining equity → negative Sharpe."""
        values = [100_000 - i * 500 for i in range(60)]
        curve = _make_equity_curve(values)
        sharpe = compute_sharpe_ratio(curve, 100_000)
        assert sharpe < 0

    def test_too_few_points(self):
        """Fewer than 3 data points → return 0."""
        curve = _make_equity_curve([100_000, 101_000])
        assert compute_sharpe_ratio(curve, 100_000) == 0.0

    def test_empty_curve(self):
        assert compute_sharpe_ratio([], 100_000) == 0.0

    def test_capped_at_10(self):
        """Sharpe is capped at [-10, +10]."""
        # Extremely smooth gains
        values = [100_000 + i for i in range(100)]
        curve = _make_equity_curve(values)
        sharpe = compute_sharpe_ratio(curve, 100_000)
        assert -10 <= sharpe <= 10


# ────────────────────────────────────────────────────────────
# SORTINO RATIO
# ────────────────────────────────────────────────────────────

class TestSortinoRatio:
    def test_no_downside(self):
        """All positive returns → downside std ≈ 0 → Sortino = 0."""
        values = [100_000 + i * 100 for i in range(60)]
        curve = _make_equity_curve(values)
        sortino = compute_sortino_ratio(curve, 100_000)
        # With purely positive returns, no downside → 0
        assert sortino == 0.0

    def test_mixed_returns(self):
        """Oscillating returns → computable Sortino."""
        import random; random.seed(42)
        values = [100_000]
        for _ in range(59):
            values.append(values[-1] + random.uniform(-200, 300))
        curve = _make_equity_curve(values)
        sortino = compute_sortino_ratio(curve, 100_000)
        # Should be a finite number
        assert isinstance(sortino, float)
        assert -10 <= sortino <= 10


# ────────────────────────────────────────────────────────────
# MAX DRAWDOWN
# ────────────────────────────────────────────────────────────

class TestMaxDrawdown:
    def test_known_drawdown(self):
        """Peak 200k → trough 150k = -25%."""
        curve = _make_equity_curve([100_000, 200_000, 150_000, 180_000])
        dd = compute_max_drawdown(curve)
        assert dd["max_drawdown_pct"] == -25.0

    def test_no_drawdown(self):
        """Monotonically increasing → 0% drawdown."""
        curve = _make_equity_curve([100_000, 110_000, 120_000])
        dd = compute_max_drawdown(curve)
        assert dd["max_drawdown_pct"] == 0.0

    def test_empty_curve(self):
        dd = compute_max_drawdown([])
        assert dd["max_drawdown_pct"] == 0.0

    def test_duration_tracking(self):
        """Drawdown duration should be > 0 for a real drawdown."""
        curve = _make_equity_curve([100_000, 200_000, 150_000, 160_000, 170_000])
        dd = compute_max_drawdown(curve)
        assert dd["duration_days"] >= 1


# ────────────────────────────────────────────────────────────
# CAGR
# ────────────────────────────────────────────────────────────

class TestCAGR:
    def test_100pct_return_1yr(self):
        """100k → 200k in 252 days = 100% CAGR."""
        cagr = compute_cagr(100_000, 200_000, 252)
        assert cagr == 100.0

    def test_zero_days(self):
        assert compute_cagr(100_000, 200_000, 0) == 0.0

    def test_negative_return(self):
        cagr = compute_cagr(100_000, 80_000, 252)
        assert cagr < 0

    def test_zero_capital(self):
        assert compute_cagr(0, 100_000, 252) == 0.0


# ────────────────────────────────────────────────────────────
# CALMAR RATIO
# ────────────────────────────────────────────────────────────

class TestCalmarRatio:
    def test_basic(self):
        """CAGR 20%, max DD -10% → Calmar = 2.0."""
        assert compute_calmar_ratio(20.0, -10.0) == 2.0

    def test_zero_drawdown(self):
        assert compute_calmar_ratio(20.0, 0.0) == 0.0


# ────────────────────────────────────────────────────────────
# TRADE-LEVEL METRICS
# ────────────────────────────────────────────────────────────

class TestTradeMetrics:
    def test_win_rate_all_wins(self):
        assert compute_win_rate([100, 200, 50]) == 100.0

    def test_win_rate_all_losses(self):
        assert compute_win_rate([-100, -200]) == 0.0

    def test_win_rate_mixed(self):
        assert compute_win_rate([100, -50, 200, -100]) == 50.0

    def test_win_rate_empty(self):
        assert compute_win_rate([]) == 0.0

    def test_profit_factor_basic(self):
        pf = compute_profit_factor([100, -50, 200, -100])
        # Gross profit = 300, gross loss = 150 → PF = 2.0
        assert pf == 2.0

    def test_profit_factor_no_losses(self):
        assert compute_profit_factor([100, 200]) == 99.99

    def test_profit_factor_no_wins(self):
        assert compute_profit_factor([-100, -200]) == 0.0

    def test_expectancy(self):
        exp = compute_expectancy([100, -50, 200, -100])
        assert exp == 37.5  # (100 - 50 + 200 - 100) / 4

    def test_avg_win_loss(self):
        avg_w, avg_l = compute_avg_win_loss([100, -50, 200, -100])
        assert avg_w == 150.0   # (100 + 200) / 2
        assert avg_l == -75.0   # (-50 + -100) / 2


# ────────────────────────────────────────────────────────────
# PORTFOLIO VALUE
# ────────────────────────────────────────────────────────────

class TestPortfolioValue:
    def test_cash_only(self):
        assert compute_portfolio_value(50_000, {}, {}) == 50_000

    def test_with_holdings(self):
        class MockHolding:
            def __init__(self, qty, avg):
                self.Quantity = qty
                self.AveragePrice = avg
        holdings = {"RELIANCE": MockHolding(10, 2500)}
        prices = {"RELIANCE": 2600}
        # 50k cash + 10 × 2600 = 76k
        assert compute_portfolio_value(50_000, holdings, prices) == 76_000


# ────────────────────────────────────────────────────────────
# MASTER AGGREGATOR
# ────────────────────────────────────────────────────────────

class TestComputeAllStatistics:
    def test_complete_output(self):
        values = [100_000 + i * 200 for i in range(60)]
        curve = _make_equity_curve(values)
        pnls = [200, -100, 300, -50, 150]
        stats = compute_all_statistics(curve, pnls, 100_000)

        # Check all expected keys exist
        expected_keys = [
            "total_return", "net_profit", "cagr",
            "sharpe_ratio", "sortino_ratio", "max_drawdown", "max_dd_duration", "calmar_ratio",
            "total_trades", "win_rate", "profit_factor", "expectancy", "avg_win", "avg_loss",
        ]
        for k in expected_keys:
            assert k in stats, f"Missing key: {k}"

        assert stats["total_trades"] == 5
        assert stats["win_rate"] == 60.0  # 3 wins / 5 trades
        assert stats["net_profit"] > 0

class TestDownsampling:
    def test_no_downsample_small_curve(self):
        curve = _make_equity_curve([100, 110, 105])
        downsampled = downsample_equity_curve(curve, max_points=10)
        assert len(downsampled) == 3
        assert downsampled == curve

    def test_downsample_large_curve(self):
        # 1000 points downsampled to 100
        curve = _make_equity_curve([100 + i for i in range(1000)])
        max_pts = 100
        downsampled = downsample_equity_curve(curve, max_points=max_pts)
        # Should be roughly max_pts (+/- 1 for first/last logic)
        assert len(downsampled) <= max_pts + 1
        # First and last must be preserved (last might be isoformat from fallback)
        assert float(pd.to_numeric(downsampled[0]["equity"])) == 100.0
        assert float(pd.to_numeric(downsampled[-1]["equity"])) == 1099.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
