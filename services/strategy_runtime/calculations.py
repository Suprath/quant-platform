"""
Calculations Module — Centralized Financial Metrics Engine
===========================================================
Pure, stateless functions for every financial metric used across the
quant-platform ecosystem.  All helpers are independently testable.

Covers:
  • Portfolio equity valuation
  • Transaction cost modelling (SEBI-compliant Indian equities)
  • Sharpe / Sortino / Calmar ratios
  • CAGR, Max Drawdown (with duration), Win Rate, Profit Factor, Expectancy
  • A master `compute_all_statistics` aggregator
"""

import os
import math
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger("Calculations")

# ────────────────────────────────────────────────────────────
# 1.  TRANSACTION COST MODEL  (SEBI / NSE Equity)
# ────────────────────────────────────────────────────────────

class TransactionCostCalculator:
    """
    Indian Equity Transaction Cost Model (NSE / BSE)

    Realistic charges as per SEBI regulations (updated FY 2024-25):
      • Brokerage       — min(flat ₹20, 0.03 % of turnover)
      • STT             — 0.025 % sell-side (MIS) / 0.1 % both sides (CNC)
      • Exchange Txn    — 0.00345 %
      • SEBI Fee        — 0.0001 %
      • Stamp Duty      — 0.003 % buy (MIS) / 0.015 % buy (CNC)
      • GST             — 18 % on (brokerage + exchange + SEBI)
    """

    # Default regulatory rates
    # Default regulatory rates
    BROKERAGE_FLAT  = 20.0
    BROKERAGE_PCT   = 0.0003      # 0.03 %
    STT_SELL_MIS    = 0.00025     # 0.025 %  (sell-side only for intraday)
    STT_BOTH_CNC    = 0.001       # 0.1 %    (both sides for delivery)
    STT_SELL_OPT    = 0.001       # 0.1 %    (sell-side only for options)
    EXCHANGE_TXN    = 0.0000345   # 0.00345 %
    EXCHANGE_TXN_OPT= 0.0005      # 0.05 %   (options)
    SEBI_FEE        = 0.000001    # 0.0001 %
    STAMP_MIS       = 0.00003     # 0.003 %  (buy-side only)
    STAMP_CNC       = 0.00015     # 0.015 %  (buy-side only)
    STAMP_OPT       = 0.00003     # 0.003 %  (buy-side only for options)
    GST_RATE        = 0.18        # 18 %

    def __init__(self, trading_mode: str = "MIS"):
        self.trading_mode = trading_mode.upper()

    def calculate(self, turnover: float, side: str) -> float:
        """
        Calculate total transaction charges for a single leg.

        Parameters
        ----------
        turnover : float   — price × quantity (absolute value)
        side     : str     — 'BUY' or 'SELL'

        Returns
        -------
        float — total charges (positive number, rounded to 2 dp)
        """
        if turnover <= 0:
            return 0.0

        side = side.upper()

        brokerage_flat = float(os.getenv('BROKERAGE_FLAT', self.BROKERAGE_FLAT))
        brokerage_pct  = float(os.getenv('BROKERAGE_PCT', self.BROKERAGE_PCT))

        # 1. Brokerage
        if self.trading_mode == "OPTIONS":
            brokerage = brokerage_flat
        else:
            brokerage = min(brokerage_flat, turnover * brokerage_pct)

        # 2. STT
        if self.trading_mode == "CNC":
            stt = turnover * self.STT_BOTH_CNC
        elif self.trading_mode == "OPTIONS":
            stt = turnover * self.STT_SELL_OPT if side == "SELL" else 0.0
        else:
            stt = turnover * self.STT_SELL_MIS if side == "SELL" else 0.0

        # 3. Exchange transaction charges
        if self.trading_mode == "OPTIONS":
            exchange_txn = turnover * self.EXCHANGE_TXN_OPT
        else:
            exchange_txn = turnover * self.EXCHANGE_TXN

        # 4. SEBI turnover fee
        sebi_fee = turnover * self.SEBI_FEE

        # 5. Stamp duty (buy-side only)
        if side == "BUY":
            if self.trading_mode == "CNC":
                stamp_duty = turnover * self.STAMP_CNC
            elif self.trading_mode == "OPTIONS":
                stamp_duty = turnover * self.STAMP_OPT
            else:
                stamp_duty = turnover * self.STAMP_MIS
        else:
            stamp_duty = 0.0

        # 6. GST: 18 % on (brokerage + exchange + SEBI)
        gst = (brokerage + exchange_txn + sebi_fee) * self.GST_RATE

        total = brokerage + stt + exchange_txn + sebi_fee + stamp_duty + gst
        return round(total, 2)

    def round_trip_cost(self, price: float, quantity: int) -> float:
        """Full round-trip cost (BUY + SELL) for a given position."""
        turnover = price * abs(quantity)
        return self.calculate(turnover, "BUY") + self.calculate(turnover, "SELL")


# ────────────────────────────────────────────────────────────
# 2.  EQUITY & PORTFOLIO HELPERS
# ────────────────────────────────────────────────────────────

def compute_portfolio_value(
    cash: float,
    holdings: Dict[str, Any],
    price_map: Dict[str, float],
) -> float:
    """
    Compute total portfolio equity.

    Parameters
    ----------
    cash       : available cash balance
    holdings   : dict  {symbol: SecurityHolding} (needs .Quantity, .AveragePrice)
    price_map  : dict  {symbol: latest_price}

    Returns
    -------
    float — cash + mark-to-market value of all positions
    """
    equity = cash
    for sym, holding in holdings.items():
        if sym in ("Cash", "TotalPortfolioValue"):
            continue
        qty = getattr(holding, "Quantity", 0)
        if qty == 0:
            continue
        price = price_map.get(sym) or getattr(holding, "AveragePrice", 0)
        equity += qty * price
    return equity


# ────────────────────────────────────────────────────────────
# 3.  RETURN SERIES HELPERS
# ────────────────────────────────────────────────────────────

def _build_returns(
    equity_curve: List[Dict],
    initial_capital: float,
) -> Tuple[pd.Series, int]:
    """
    Convert a list of {'timestamp', 'equity'} dicts to a return Series.

    Strategy:
      1. Try daily resampling first (preferred for long backtests).
      2. If daily gives < 3 points, fall back to per-tick returns
         (each equity snapshot becomes a data point).

    Returns
    -------
    (returns Series, annualisation_factor)
      - annualisation_factor = 252 for daily, or estimated from tick frequency
    """
    if not equity_curve:
        return pd.Series(dtype=float), 252

    df = pd.DataFrame(equity_curve)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df.set_index("timestamp", inplace=True)
    df["equity"] = pd.to_numeric(df["equity"])
    df.sort_index(inplace=True)

    # --- Attempt 1: daily resampling ---
    daily = df.resample("D").last().ffill()
    if len(daily) >= 3:
        day_before = daily.index.min() - pd.Timedelta(days=1)
        baseline = pd.DataFrame({"equity": [initial_capital]}, index=[day_before])
        full = pd.concat([baseline, daily])
        returns = full["equity"].pct_change().dropna()
        returns = returns.replace([np.inf, -np.inf], 0.0)
        # Drop zero-return days: forward-filled flat equity days compress
        # volatility and inflate Sharpe/Sortino unrealistically.
        returns = returns[returns.abs() > 1e-10]
        return returns, 252

    # --- Attempt 2: per-tick returns (for short backtests) ---
    # Prepend initial capital so first move is captured
    first_ts = df.index.min() - pd.Timedelta(seconds=1)
    baseline = pd.DataFrame({"equity": [initial_capital]}, index=[first_ts])
    full = pd.concat([baseline, df])
    # Remove duplicate indices keeping last
    full = full[~full.index.duplicated(keep="last")]
    full.sort_index(inplace=True)

    returns = full["equity"].pct_change().dropna()
    returns = returns.replace([np.inf, -np.inf], 0.0)

    # Estimate annualisation factor based on actual time span and trading days
    if len(full) >= 2:
        total_span_seconds = (full.index[-1] - full.index[0]).total_seconds()
        
        # If the span is < 5 minutes, annualisation is statistically dubious.
        # We cap the annualisation factor to avoid astronomical Sharpe ratios.
        if total_span_seconds < 300:
            # Fall back to a more conservative estimate (e.g. daily if very short)
            ann_factor = 252 
        else:
            # Estimate how many such intervals fit into a 6.25h trading day
            avg_interval = total_span_seconds / max(len(full) - 1, 1)
            if avg_interval > 0:
                ticks_per_day = (6.25 * 3600) / avg_interval
                # Cap the number of ticks_per_day to 10,000 (roughly 1 snapshot every 2.25s)
                # to prevent outliers from blowing up the Sharpe.
                ticks_per_day = min(ticks_per_day, 10000)
                ann_factor = int(ticks_per_day * 252)
            else:
                ann_factor = 252
    else:
        ann_factor = 252

    return returns, ann_factor


# Backward-compatible wrapper (used by existing tests)
def _build_daily_returns(
    equity_curve: List[Dict],
    initial_capital: float,
) -> pd.Series:
    """Legacy wrapper — returns only the Series (daily preferred)."""
    returns, _ = _build_returns(equity_curve, initial_capital)
    return returns


# ────────────────────────────────────────────────────────────
# 4.  CORE METRIC FUNCTIONS
# ────────────────────────────────────────────────────────────

def compute_sharpe_ratio(
    equity_curve: List[Dict],
    initial_capital: float,
    risk_free_rate: float = 0.06,
) -> float:
    """
    Annualised Sharpe Ratio.

    Uses daily returns when available (≥ 3 days), otherwise per-tick returns
    with an appropriately scaled annualisation factor.
    """
    returns, ann_factor = _build_returns(equity_curve, initial_capital)
    if len(returns) < 3:
        return 0.0

    rf_per_period = risk_free_rate / ann_factor
    excess = returns - rf_per_period
    std = excess.std()
    if std < 1e-8:
        return 0.0

    sharpe = (excess.mean() / std) * math.sqrt(ann_factor)
    return round(max(-10, min(10, sharpe)), 2)


def compute_sortino_ratio(
    equity_curve: List[Dict],
    initial_capital: float,
    risk_free_rate: float = 0.06,
) -> float:
    """
    Sortino Ratio — like Sharpe but only penalises downside volatility.

    Uses the same per-tick fallback as Sharpe for short backtests.
    """
    returns, ann_factor = _build_returns(equity_curve, initial_capital)
    if len(returns) < 3:
        return 0.0

    rf_per_period = risk_free_rate / ann_factor
    excess = returns - rf_per_period
    downside = excess[excess < 0]

    if len(downside) < 2:
        return 0.0

    downside_std = downside.std()
    if downside_std < 1e-8:
        return 0.0

    sortino = (excess.mean() / downside_std) * math.sqrt(ann_factor)
    return round(max(-10, min(10, sortino)), 2)


def compute_max_drawdown(equity_curve: List[Dict]) -> Dict[str, Any]:
    """
    Maximum peak-to-trough drawdown.

    Returns
    -------
    dict with keys:
        max_drawdown_pct  : float  (negative %, e.g. -12.5)
        peak_date         : datetime or None
        trough_date       : datetime or None
        duration_days     : int
    """
    result = {"max_drawdown_pct": 0.0, "peak_date": None, "trough_date": None, "duration_days": 0}

    if not equity_curve or len(equity_curve) < 2:
        return result

    df = pd.DataFrame(equity_curve)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df.set_index("timestamp", inplace=True)
    df["equity"] = pd.to_numeric(df["equity"])

    rolling_max = df["equity"].cummax()
    drawdown = (df["equity"] - rolling_max) / rolling_max

    if drawdown.empty:
        return result

    min_idx = drawdown.idxmin()
    result["max_drawdown_pct"] = round(float(drawdown.min()) * 100, 2)
    result["trough_date"] = min_idx

    # Find the peak that preceded the trough
    peak_series = rolling_max.loc[:min_idx]
    if not peak_series.empty:
        result["peak_date"] = peak_series.idxmax()
        result["duration_days"] = (min_idx - result["peak_date"]).days

    return result


def compute_cagr(
    initial_capital: float,
    final_capital: float,
    trading_days: int,
) -> float:
    """
    Compound Annual Growth Rate.

    CAGR = (final / initial) ^ (252 / trading_days) - 1
    """
    if initial_capital <= 0 or final_capital <= 0 or trading_days <= 0:
        return 0.0
    years = trading_days / 252
    if years < 0.01:
        return 0.0
    cagr = (final_capital / initial_capital) ** (1 / years) - 1
    return round(cagr * 100, 2)


def compute_calmar_ratio(cagr: float, max_drawdown_pct: float) -> float:
    """
    Calmar Ratio = CAGR / |Max Drawdown|

    Both inputs are percentages (e.g. cagr=15.0, max_dd=-12.5).
    """
    abs_dd = abs(max_drawdown_pct)
    if abs_dd < 0.01:
        return 0.0
    return round(cagr / abs_dd, 2)


# ────────────────────────────────────────────────────────────
# 5.  TRADE-LEVEL METRICS
# ────────────────────────────────────────────────────────────

def compute_win_rate(pnl_list: List[float]) -> float:
    """Percentage of profitable trades (PnL > 0), excluding entries (PnL=0)."""
    # Filter out entries
    actual_trades = [p for p in pnl_list if abs(p) > 1e-8]
    if not actual_trades:
        return 0.0
    wins = sum(1 for p in actual_trades if p > 0)
    return round((wins / len(actual_trades)) * 100, 1)


def compute_profit_factor(pnl_list: List[float]) -> float:
    """
    Gross Profit / Gross Loss.
    Excludes entries (PnL=0).
    """
    actual_trades = [p for p in pnl_list if abs(p) > 1e-8]
    if not actual_trades:
        return 0.0
    gross_profit = sum(p for p in actual_trades if p > 0)
    gross_loss   = abs(sum(p for p in actual_trades if p < 0))
    if gross_loss < 0.01:
        return 99.99 if gross_profit > 0 else 0.0
    return round(gross_profit / gross_loss, 2)


def compute_expectancy(pnl_list: List[float]) -> float:
    """Average expected PnL per trade, excluding entries (PnL=0)."""
    actual_trades = [p for p in pnl_list if abs(p) > 1e-8]
    if not actual_trades:
        return 0.0
    return round(sum(actual_trades) / len(actual_trades), 2)


def compute_avg_win_loss(pnl_list: List[float]) -> Tuple[float, float]:
    """
    Returns (avg_win, avg_loss).
    avg_loss is returned as a negative number.
    """
    wins   = [p for p in pnl_list if p > 0]
    losses = [p for p in pnl_list if p < 0]
    avg_win  = round(sum(wins)   / len(wins),   2) if wins   else 0.0
    avg_loss = round(sum(losses) / len(losses), 2) if losses else 0.0
    return avg_win, avg_loss


def compute_total_return(initial_capital: float, final_equity: float) -> float:
    """Total return as a percentage."""
    if initial_capital <= 0:
        return 0.0
    return round(((final_equity - initial_capital) / initial_capital) * 100, 2)


def compute_net_profit(initial_capital: float, final_equity: float) -> float:
    """Absolute net profit/loss."""
    return round(final_equity - initial_capital, 2)


# ────────────────────────────────────────────────────────────
# 6.  MASTER AGGREGATOR
# ────────────────────────────────────────────────────────────

def _try_cpp_statistics(
    equity_curve: List[Dict],
    pnl_list: List[float],
    initial_capital: float,
    trading_days: int = 0,
    risk_free_rate: float = 0.06,
) -> Optional[Dict[str, Any]]:
    """
    Attempt to compute all statistics using the C++ kira_engine module.
    Returns None if the module is not available — caller should fall back.
    """
    try:
        import kira_engine as ke
    except ImportError:
        return None

    # Build (timestamp_ms, equity) vector for C++
    cpp_curve = []
    for pt in equity_curve:
        ts = pt.get("timestamp")
        eq = float(pt.get("equity", 0))
        if ts is None:
            continue
        if isinstance(ts, (int, float)):
            ts_ms = int(ts)
        elif hasattr(ts, "timestamp"):
            ts_ms = int(ts.timestamp() * 1000)
        else:
            try:
                ts_ms = int(pd.Timestamp(ts).timestamp() * 1000)
            except Exception:
                continue
        cpp_curve.append((ts_ms, eq))

    if not cpp_curve:
        return None

    final_equity = cpp_curve[-1][1] if cpp_curve else initial_capital

    # Build return series
    returns = ke.build_daily_returns(cpp_curve, initial_capital)
    
    if len(cpp_curve) >= 2:
        total_span_seconds = (cpp_curve[-1][0] - cpp_curve[0][0]) / 1000.0
        if total_span_seconds < 300:
            ann_factor = 252
        else:
            avg_interval = total_span_seconds / max(len(cpp_curve) - 1, 1)
            ticks_per_day = min((6.25 * 3600) / avg_interval, 10000)
            ann_factor = int(ticks_per_day * 252)
    else:
        ann_factor = 252

    # Auto-detect trading days
    if trading_days <= 0:
        trading_days = max(len(returns), 1)

    # C++ metrics (all single-pass, zero Pandas)
    sharpe = ke.compute_sharpe(returns, risk_free_rate, ann_factor)
    sortino = ke.compute_sortino(returns, risk_free_rate, ann_factor)
    dd = ke.compute_max_drawdown_cpp(cpp_curve)
    cagr = ke.compute_cagr(initial_capital, final_equity, trading_days)
    calmar = ke.compute_calmar(cagr, dd.max_drawdown_pct)
    tm = ke.compute_trade_metrics(pnl_list)

    # Downsample curve for UI
    downsampled = ke.downsample_lttb(cpp_curve, 500)
    serialised_curve = [
        {"time": datetime.fromtimestamp(ts / 1000.0).isoformat(), "equity": float(eq)}
        for ts, eq in downsampled
    ]
    tm = ke.compute_trade_metrics(pnl_list)

    return {
        "total_return":     round(ke.compute_total_return(initial_capital, final_equity), 2),
        "net_profit":       round(ke.compute_net_profit(initial_capital, final_equity), 2),
        "cagr":             round(cagr, 2),
        "sharpe_ratio":     round(max(-10, min(10, sharpe)), 2),
        "sortino_ratio":    round(max(-10, min(10, sortino)), 2),
        "max_drawdown":     round(dd.max_drawdown_pct, 2),
        "max_dd_duration":  dd.duration_days,
        "calmar_ratio":     round(calmar, 2),
        "total_trades":     tm.total_trades,
        "win_rate":         round(tm.win_rate, 1),
        "profit_factor":    round(tm.profit_factor, 2),
        "expectancy":       round(tm.expectancy, 2),
        "avg_win":          round(tm.avg_win, 2),
        "avg_loss":         round(tm.avg_loss, 2),
        "equity_curve":     serialised_curve,
    }


def compute_all_statistics(
    equity_curve: List[Dict],
    pnl_list: List[float],
    initial_capital: float,
    trading_days: int = 0,
    risk_free_rate: float = 0.06,
) -> Dict[str, Any]:
    """
    Compute every metric in one call.

    Tries the C++ fast path first (single-pass, zero Pandas).
    Falls back to the pure-Python implementation if C++ module is unavailable.

    Parameters
    ----------
    equity_curve    : list of {'timestamp', 'equity'} dicts
    pnl_list        : list of per-trade PnL floats
    initial_capital : starting cash
    trading_days    : number of trading days in the period (0 = auto-detect)
    risk_free_rate  : annual risk-free rate (default 6 % — India 10Y bond)

    Returns
    -------
    dict with all metric keys
    """
    # ── Try C++ fast path ──
    cpp_result = _try_cpp_statistics(
        equity_curve, pnl_list, initial_capital, trading_days, risk_free_rate
    )
    if cpp_result is not None:
        logger.info("⚡ Statistics computed via C++ fast path")
        return cpp_result

    # ── Fallback: Python path ──
    logger.info("📊 Statistics computed via Python fallback path")

    # Filter out entries for trade-level metrics
    filtered_pnl = [p for p in pnl_list if abs(p) > 1e-8]

    # Final equity from curve
    if equity_curve:
        final_equity = float(equity_curve[-1].get("equity", initial_capital))
    else:
        final_equity = initial_capital

    # Auto-detect trading days from equity curve length
    if trading_days <= 0 and equity_curve:
        returns = _build_daily_returns(equity_curve, initial_capital)
        trading_days = max(len(returns), 1)

    dd_info = compute_max_drawdown(equity_curve)
    cagr = compute_cagr(initial_capital, final_equity, trading_days)
    avg_win, avg_loss = compute_avg_win_loss(pnl_list)

    # Downsample equity curve for storage/UI (max 500 points)
    downsampled_curve = downsample_equity_curve(equity_curve, max_points=500)
    # Convert timestamps to ISO strings for JSON serialisation
    serialised_curve = [
        {
            "time": (pt["timestamp"].isoformat() if hasattr(pt.get("timestamp"), "isoformat") else str(pt.get("timestamp", ""))),
            "equity": float(pt.get("equity", 0))
        }
        for pt in downsampled_curve
    ]

    return {
        # Return metrics
        "total_return":     compute_total_return(initial_capital, final_equity),
        "net_profit":       compute_net_profit(initial_capital, final_equity),
        "cagr":             cagr,

        # Risk metrics
        "sharpe_ratio":     compute_sharpe_ratio(equity_curve, initial_capital, risk_free_rate),
        "sortino_ratio":    compute_sortino_ratio(equity_curve, initial_capital, risk_free_rate),
        "max_drawdown":     dd_info["max_drawdown_pct"],
        "max_dd_duration":  dd_info["duration_days"],
        "calmar_ratio":     compute_calmar_ratio(cagr, dd_info["max_drawdown_pct"]),

        # Trade metrics
        "total_trades":     len(pnl_list), 
        "win_rate":         compute_win_rate(filtered_pnl),
        "profit_factor":    compute_profit_factor(filtered_pnl),
        "expectancy":       compute_expectancy(filtered_pnl),
        "avg_win":          avg_win,
        "avg_loss":         avg_loss,

        # High-fidelity curve for UI
        "equity_curve":     serialised_curve,
    }


# ────────────────────────────────────────────────────────────
# 7.  EQUITY CURVE DOWNSAMPLING
# ────────────────────────────────────────────────────────────

def downsample_equity_curve(
    equity_curve: List[Dict],
    max_points: int = 500,
) -> List[Dict]:
    """
    Downsample an equity curve to at most max_points for frontend rendering.
    Uses C++ LTTB (Largest-Triangle-Three-Buckets) if available,
    otherwise uses simple stride-based decimation.
    """
    if len(equity_curve) <= max_points:
        return equity_curve

    try:
        import kira_engine as ke

        # Convert to (timestamp_ms, equity) pairs for C++
        cpp_curve = []
        for pt in equity_curve:
            ts = pt.get("timestamp")
            eq = float(pt.get("equity", 0))
            if ts is None:
                continue
            if isinstance(ts, (int, float)):
                ts_ms = int(ts)
            elif hasattr(ts, "timestamp"):
                ts_ms = int(ts.timestamp() * 1000)
            else:
                try:
                    ts_ms = int(pd.Timestamp(ts).timestamp() * 1000)
                except Exception:
                    continue
            cpp_curve.append((ts_ms, eq))

        if len(cpp_curve) > max_points:
            downsampled = ke.downsample_lttb(cpp_curve, max_points)
            # Convert back to dicts
            return [
                {"time": datetime.fromtimestamp(ts / 1000.0).isoformat(), "equity": eq}
                for ts, eq in downsampled
            ]

    except ImportError:
        pass

    # Fallback: stride-based decimation (keeps first + last + every Nth)
    stride = max(1, len(equity_curve) // max_points)
    result = equity_curve[::stride]
    if result[-1] != equity_curve[-1]:
        result.append(equity_curve[-1])
    return result


# ── Market-Impact-Aware Execution ─────────────────────────────────────────────

def compute_kyle_lambda(atr: float, avg_daily_volume: float, tick_size: float = 0.05) -> float:
    """
    Estimate Kyle's Lambda (market impact coefficient) from ATR and volume.
    Formula: lambda = ATR / (avg_daily_volume * tick_size)
    """
    denominator = avg_daily_volume * tick_size
    if denominator <= 0.0:
        return 0.0
    return atr / denominator


def kelly_with_market_impact(
    alpha_kalman: float,
    lambda_hawkes: float,
    obi: float,
    spread: float,
    kyle_lambda: float,
) -> int:
    """
    Modified Kelly position size accounting for market impact (Kyle's Lambda).
    q* = (alpha_kalman + alpha_hawkes_scaled) * OBI / (2 * kyle_lambda)
    Returns integer share count >= 0.
    """
    if kyle_lambda <= 1e-10:
        return 0

    alpha_hawkes_scaled = lambda_hawkes / 1e5
    combined_alpha = (alpha_kalman + alpha_hawkes_scaled) * obi
    q_star = combined_alpha / (2.0 * kyle_lambda)

    return max(0, int(q_star))

