#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <vector>
#include <numeric>
#include <cmath>
#include <algorithm>
#include <string>

namespace py = pybind11;

/**
 * KIRA Position Sizer Core (C++)
 * Implementation of high-performance risk management logic.
 */

class PositionSizerCore {
public:
    PositionSizerCore() {}

    /**
     * Calculates ATR (Average True Range) given a series of daily high-low ranges.
     */
    double calculate_atr(const std::vector<double>& daily_ranges) {
        if (daily_ranges.empty()) return 0.0;
        double sum = std::accumulate(daily_ranges.begin(), daily_ranges.end(), 0.0);
        return sum / daily_ranges.size();
    }

    /**
     * Calculates the risk-adjusted quantity.
     * Logic: 
     * - Scaling Risk based on Confidence.
     * - Stop Loss based on Volatility (ATR).
     */
    int compute_shares(
        double entry_price, 
        double confidence_score, 
        double current_equity, 
        double atr
    ) {
        if (entry_price <= 0 || current_equity <= 0) return 0;

        // 1. Determine Risk Percentage based on KIRA Confidence
        double risk_pct;
        if (confidence_score >= 80) {
            risk_pct = 0.015;
        } else if (confidence_score >= 60) {
            risk_pct = 0.010;
        } else {
            risk_pct = 0.005;
        }

        // 2. Determine Stop Loss Distance
        // Default to 2% SL if ATR is invalid, else use 2.0 * ATR
        double stop_dist;
        if (atr > 0) {
            stop_dist = atr * 2.0;
            // Safety cap: 0.5% min, 5% max
            double max_stop = entry_price * 0.05;
            double min_stop = entry_price * 0.005;
            stop_dist = std::max(std::min(stop_dist, max_stop), min_stop);
        } else {
            stop_dist = entry_price * 0.02; // Fixed 2% fallback
        }

        // 3. Compute Quantity
        double risk_amount = current_equity * risk_pct;
        int shares = (int)(risk_amount / stop_dist);

        return std::max(0, shares);
    }
};

PYBIND11_MODULE(position_sizer_core, m) {
    py::class_<PositionSizerCore>(m, "PositionSizerCore")
        .def(py::init<>())
        .def("calculate_atr", &PositionSizerCore::calculate_atr)
        .def("compute_shares", &PositionSizerCore::compute_shares);
}
