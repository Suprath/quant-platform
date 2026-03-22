// statistics.h — Pure C++ financial statistics functions
// All operate on flat vectors for zero-copy, single-pass performance.
// No Pandas, no Python, no heap allocations in hot paths.

#pragma once

#include <vector>
#include <cmath>
#include <algorithm>
#include <numeric>
#include <cstdint>
#include <utility>

namespace kira {
namespace stats {

// ─── Helper: build daily returns from equity curve ────────────────
// equity_curve: vector of (timestamp_ms, equity) pairs, sorted by time.
// Returns: vector of daily percentage returns (zero-return days EXCLUDED
//          to avoid inflating Sharpe with calendar-diluted noise).
inline std::vector<double> build_daily_returns(
    const std::vector<std::pair<int64_t, double>>& equity_curve,
    double initial_capital)
{
    if (equity_curve.size() < 2) return {};

    // Group by day (date_int = ms / 86400000)
    struct DayEquity { int64_t day; double equity; };
    std::vector<DayEquity> daily;

    int64_t last_day = -1;
    for (const auto& [ts, eq] : equity_curve) {
        int64_t day = ts / 86400000LL;
        if (day != last_day) {
            daily.push_back({day, eq});
            last_day = day;
        } else {
            daily.back().equity = eq; // keep last equity per day
        }
    }

    // If we have < 3 days, use raw equity points instead
    const auto& source = (daily.size() >= 3) ? [&]() -> const std::vector<DayEquity>& {
        return daily;
    }() : [&]() -> const std::vector<DayEquity>& {
        static std::vector<DayEquity> raw;
        raw.clear();
        raw.reserve(equity_curve.size());
        for (const auto& [ts, eq] : equity_curve) {
            raw.push_back({ts, eq});
        }
        return raw;
    }();

    std::vector<double> returns;
    returns.reserve(source.size());

    double prev_eq = (initial_capital > 0) ? initial_capital : source[0].equity;
    for (size_t i = 0; i < source.size(); ++i) {
        double eq = source[i].equity;
        if (prev_eq > 1e-8) {
            double r = (eq - prev_eq) / prev_eq;
            // Clamp infinities
            if (std::isinf(r) || std::isnan(r)) r = 0.0;
            // Skip zero-return days: they occur when no trades happen
            // and artificially compress volatility, inflating Sharpe.
            if (std::abs(r) > 1e-10) {
                returns.push_back(r);
            }
        }
        prev_eq = eq;
    }

    return returns;
}

// ─── Sharpe Ratio (single-pass) ──────────────────────────────────
// risk_free_rate: annual (e.g. 0.06 for 6%)
// ann_factor: annualization (252 for daily, higher for tick-level)
inline double compute_sharpe(
    const std::vector<double>& returns,
    double risk_free_rate = 0.06,
    int ann_factor = 252)
{
    if (returns.size() < 3) return 0.0;

    double rf_per_period = risk_free_rate / ann_factor;
    double sum = 0.0, sum_sq = 0.0;
    int n = static_cast<int>(returns.size());

    for (double r : returns) {
        double excess = r - rf_per_period;
        sum += excess;
        sum_sq += excess * excess;
    }

    double mean = sum / n;
    // Use Bessel's correction (N-1) for sample std deviation
    double variance = (sum_sq - (sum * sum) / n) / (n - 1);
    if (variance < 1e-16) return 0.0;

    double std_dev = std::sqrt(variance);
    double sharpe = (mean / std_dev) * std::sqrt(static_cast<double>(ann_factor));

    // Clamp to [-10, 10]
    return std::max(-10.0, std::min(10.0, sharpe));
}

// ─── Sortino Ratio (single-pass) ─────────────────────────────────
inline double compute_sortino(
    const std::vector<double>& returns,
    double risk_free_rate = 0.06,
    int ann_factor = 252)
{
    if (returns.size() < 3) return 0.0;

    double rf_per_period = risk_free_rate / ann_factor;
    double sum_excess = 0.0;
    double sum_downside_sq = 0.0;
    int n = static_cast<int>(returns.size());
    int n_down = 0;

    for (double r : returns) {
        double excess = r - rf_per_period;
        sum_excess += excess;
        if (excess < 0.0) {
            sum_downside_sq += excess * excess;
            n_down++;
        }
    }

    if (n_down < 2) return 0.0;

    double mean_excess = sum_excess / n;
    // Use Bessel's correction (N_down-1) for sample downside std
    double downside_std = std::sqrt(sum_downside_sq / (n_down - 1));
    if (downside_std < 1e-8) return 0.0;

    double sortino = (mean_excess / downside_std) * std::sqrt(static_cast<double>(ann_factor));
    return std::max(-10.0, std::min(10.0, sortino));
}

// ─── Max Drawdown (single-pass peak tracking) ────────────────────
// Returns: (max_dd_pct, peak_idx, trough_idx, duration_days)
struct DrawdownResult {
    double max_drawdown_pct = 0.0;   // negative, e.g. -12.5
    int    peak_idx         = 0;
    int    trough_idx       = 0;
    int    duration_days    = 0;
};

inline DrawdownResult compute_max_drawdown(
    const std::vector<std::pair<int64_t, double>>& equity_curve)
{
    DrawdownResult result;
    if (equity_curve.size() < 2) return result;

    double peak = equity_curve[0].second;
    int peak_idx = 0;
    double max_dd = 0.0;

    for (int i = 1; i < static_cast<int>(equity_curve.size()); ++i) {
        double eq = equity_curve[i].second;

        if (eq > peak) {
            peak = eq;
            peak_idx = i;
        }

        if (peak > 1e-8) {
            double dd = (eq - peak) / peak; // negative
            if (dd < max_dd) {
                max_dd = dd;
                result.max_drawdown_pct = dd * 100.0;
                result.peak_idx = peak_idx;
                result.trough_idx = i;

                // Duration in days (ms difference / ms_per_day)
                int64_t dt = equity_curve[i].first - equity_curve[peak_idx].first;
                result.duration_days = static_cast<int>(dt / 86400000LL);
            }
        }
    }

    return result;
}

// ─── CAGR ────────────────────────────────────────────────────────
inline double compute_cagr(double initial, double final_val, int trading_days) {
    if (initial <= 0 || final_val <= 0 || trading_days <= 0) return 0.0;
    double years = trading_days / 252.0;
    if (years < 0.01) return 0.0;
    double cagr = std::pow(final_val / initial, 1.0 / years) - 1.0;
    return cagr * 100.0; // percentage
}

// ─── Calmar Ratio ────────────────────────────────────────────────
inline double compute_calmar(double cagr_pct, double max_dd_pct) {
    double abs_dd = std::abs(max_dd_pct);
    if (abs_dd < 0.01) return 0.0;
    return cagr_pct / abs_dd;
}

// ─── Trade-level metrics ─────────────────────────────────────────
struct TradeMetrics {
    double win_rate       = 0.0;
    double profit_factor  = 0.0;
    double expectancy     = 0.0;
    double avg_win        = 0.0;
    double avg_loss       = 0.0;
    int    total_trades   = 0;
};

inline TradeMetrics compute_trade_metrics(const std::vector<double>& pnl_list) {
    TradeMetrics m;
    m.total_trades = 0;

    double gross_profit = 0.0, gross_loss = 0.0;
    double sum_pnl = 0.0;
    int wins = 0, losses = 0;

    for (double p : pnl_list) {
        if (std::abs(p) < 1e-8) continue; // Skip entries (no PnL)
        
        m.total_trades++;
        sum_pnl += p;
        if (p > 0.0) {
            gross_profit += p;
            wins++;
        } else if (p < 0.0) {
            gross_loss += std::abs(p);
            losses++;
        }
    }

    if (m.total_trades == 0) return m;

    m.win_rate = (static_cast<double>(wins) / m.total_trades) * 100.0;
    m.expectancy = sum_pnl / m.total_trades;
    m.avg_win  = (wins > 0) ? gross_profit / wins : 0.0;
    m.avg_loss = (losses > 0) ? -(gross_loss / losses) : 0.0;

    if (gross_loss < 0.01) {
        m.profit_factor = (gross_profit > 0) ? 99.99 : 0.0;
    } else {
        m.profit_factor = gross_profit / gross_loss;
    }

    return m;
}

// ─── LTTB Downsampling (Largest-Triangle-Three-Buckets) ──────────
// Reduces equity_curve to at most max_points while preserving shape.
inline std::vector<std::pair<int64_t, double>> downsample_lttb(
    const std::vector<std::pair<int64_t, double>>& data,
    int max_points)
{
    int n = static_cast<int>(data.size());
    if (n <= max_points || max_points < 3) return data;

    std::vector<std::pair<int64_t, double>> result;
    result.reserve(max_points);

    // Always keep first point
    result.push_back(data[0]);

    double bucket_size = static_cast<double>(n - 2) / (max_points - 2);

    int a = 0; // index of previous selected point

    for (int i = 1; i < max_points - 1; ++i) {
        // Calculate bucket boundaries
        int bucket_start = static_cast<int>((i - 1) * bucket_size) + 1;
        int bucket_end   = static_cast<int>(i * bucket_size) + 1;
        if (bucket_end > n - 1) bucket_end = n - 1;

        // Calculate average of next bucket (for triangle area)
        int next_start = static_cast<int>(i * bucket_size) + 1;
        int next_end   = static_cast<int>((i + 1) * bucket_size) + 1;
        if (next_end > n - 1) next_end = n - 1;

        double avg_x = 0.0, avg_y = 0.0;
        int count = 0;
        for (int j = next_start; j <= next_end && j < n; ++j) {
            avg_x += static_cast<double>(data[j].first);
            avg_y += data[j].second;
            count++;
        }
        if (count > 0) { avg_x /= count; avg_y /= count; }

        // Find point in current bucket with largest triangle area
        double max_area = -1.0;
        int best_idx = bucket_start;

        double ax = static_cast<double>(data[a].first);
        double ay = data[a].second;

        for (int j = bucket_start; j <= bucket_end && j < n; ++j) {
            double bx = static_cast<double>(data[j].first);
            double by = data[j].second;

            // Triangle area (simplified, we only need relative comparison)
            double area = std::abs((ax - avg_x) * (by - ay) -
                                   (ax - bx) * (avg_y - ay));
            if (area > max_area) {
                max_area = area;
                best_idx = j;
            }
        }

        result.push_back(data[best_idx]);
        a = best_idx;
    }

    // Always keep last point
    result.push_back(data[n - 1]);

    return result;
}

// ─── Total Return % ──────────────────────────────────────────────
inline double compute_total_return(double initial, double final_val) {
    if (initial <= 0) return 0.0;
    return ((final_val - initial) / initial) * 100.0;
}

// ─── Net Profit ──────────────────────────────────────────────────
inline double compute_net_profit(double initial, double final_val) {
    return final_val - initial;
}

} // namespace stats
} // namespace kira
