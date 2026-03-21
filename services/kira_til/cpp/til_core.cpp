#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <vector>
#include <string>
#include <cmath>
#include <algorithm>
#include <map>

namespace py = pybind11;

struct ExcursionResult {
    double mae;
    double mfe;
};

ExcursionResult calculate_excursion_metrics(double entry_price, double min_excursion, double max_excursion) {
    ExcursionResult res;
    if (entry_price <= 0) {
        res.mae = 0;
        res.mfe = 0;
        return res;
    }
    // MAE: Maximum Adverse Excursion (risk) - how much it went against us
    res.mae = (std::abs(min_excursion - entry_price) / entry_price) * 100.0;
    // MFE: Maximum Favorable Excursion (potential) - how much it went for us
    res.mfe = (std::abs(max_excursion - entry_price) / entry_price) * 100.0;
    return res;
}

struct PositionState {
    std::string symbol;
    double entry_price;
    double current_price;
    int qty;
    std::string direction; // "LONG" or "SHORT"
    double sl_price;
    double tp_price;
    int bars_held;
};

struct StockFeatures {
    double adx;
    double atr_slope_5d;
    double obv_slope_5d;
    double momentum_5d;
    double hurst;
    double close;
};

struct TickSignal {
    std::string symbol;
    std::string reason; // "SL", "TP", "TIME", "SIGNAL"
};

struct BatchResults {
    std::vector<TickSignal> exits;
    std::map<std::string, double> signals; // symbol -> score
};

double score_accumulation_pattern(double adx, double atr_slope, double obv_slope, double momentum, double hurst) {
    double adx_score = std::max(0.0, 1.0 - (adx / 25.0));
    double atr_score = std::min(1.0, std::max(0.0, -atr_slope / 0.002));
    double obv_score = std::min(1.0, obv_slope / 0.005);
    double flat_score = std::max(0.0, 1.0 - std::abs(momentum) / 0.015);
    double hurst_score = std::min(1.0, std::max(0.0, (hurst - 0.45) / 0.15));
    
    return (adx_score * 0.20 + atr_score * 0.25 + obv_score * 0.25 + flat_score * 0.20 + hurst_score * 0.10);
}

BatchResults process_tick_batch(std::vector<PositionState>& positions, 
                               const std::map<std::string, StockFeatures>& universe_features) {
    BatchResults res;
    
    // 1. Exit & MTW Logic
    for (auto& pos : positions) {
        if (universe_features.count(pos.symbol)) {
            const auto& feat = universe_features.at(pos.symbol);
            pos.current_price = feat.close;
            pos.bars_held++;
            
            double pnl_pct = (pos.current_price - pos.entry_price) / pos.entry_price;
            if (pos.direction == "SHORT") pnl_pct = -pnl_pct;
            
            bool exited = false;
            if (pos.direction == "LONG" && pos.current_price >= pos.tp_price) {
                res.exits.push_back({pos.symbol, "TP"});
                exited = true;
            } else if (pos.direction == "SHORT" && pos.current_price <= pos.tp_price) {
                res.exits.push_back({pos.symbol, "TP"});
                exited = true;
            } else if (pos.direction == "LONG" && pos.current_price <= pos.sl_price) {
                res.exits.push_back({pos.symbol, "SL"});
                exited = true;
            } else if (pos.direction == "SHORT" && pos.current_price >= pos.sl_price) {
                res.exits.push_back({pos.symbol, "SL"});
                exited = true;
            } else if (pos.bars_held >= 40) {
                res.exits.push_back({pos.symbol, "TIME"});
                exited = true;
            }
        }
    }
    
    // 2. Scanner Logic (Multi-Stock)
    for (const auto& [sym, feat] : universe_features) {
        // Only scan if not already in position (simplified)
        double score = score_accumulation_pattern(feat.adx, feat.atr_slope_5d, feat.obv_slope_5d, feat.momentum_5d, feat.hurst);
        if (score >= 0.40) {
            res.signals[sym] = score;
        }
    }
    
    return res;
}

struct RiskResult {
    bool approved;
    std::string reason;
};

RiskResult validate_risk_batch(double current_heat, double max_heat, double new_trade_risk, 
                           std::map<std::string, double> sector_exposure, std::string sector, double sector_limit) {
    RiskResult res;
    res.approved = true;
    res.reason = "APPROVED";

    if (current_heat + new_trade_risk > max_heat) {
        res.approved = false;
        res.reason = "TOTAL_HEAT_LIMIT_EXCEEDED";
        return res;
    }

    if (sector != "UNKNOWN" && sector_exposure.count(sector)) {
        if (sector_exposure.at(sector) + new_trade_risk > sector_limit) {
            res.approved = false;
            res.reason = "SECTOR_EXPOSURE_LIMIT_EXCEEDED";
            return res;
        }
    }

    return res;
}

PYBIND11_MODULE(til_core, m) {
    m.doc() = "KIRA Trading Intelligence Layer (TIL) C++ Core Performance Kernels";

    py::class_<ExcursionResult>(m, "ExcursionResult")
        .def(py::init<>())
        .def_readwrite("mae", &ExcursionResult::mae)
        .def_readwrite("mfe", &ExcursionResult::mfe);

    py::class_<RiskResult>(m, "RiskResult")
        .def(py::init<>())
        .def_readwrite("approved", &RiskResult::approved)
        .def_readwrite("reason", &RiskResult::reason);

    py::class_<StockFeatures>(m, "StockFeatures")
        .def(py::init<>())
        .def_readwrite("adx", &StockFeatures::adx)
        .def_readwrite("atr_slope_5d", &StockFeatures::atr_slope_5d)
        .def_readwrite("obv_slope_5d", &StockFeatures::obv_slope_5d)
        .def_readwrite("momentum_5d", &StockFeatures::momentum_5d)
        .def_readwrite("hurst", &StockFeatures::hurst)
        .def_readwrite("close", &StockFeatures::close);

    py::class_<PositionState>(m, "PositionState")
        .def(py::init<>())
        .def_readwrite("symbol", &PositionState::symbol)
        .def_readwrite("entry_price", &PositionState::entry_price)
        .def_readwrite("current_price", &PositionState::current_price)
        .def_readwrite("qty", &PositionState::qty)
        .def_readwrite("direction", &PositionState::direction)
        .def_readwrite("sl_price", &PositionState::sl_price)
        .def_readwrite("tp_price", &PositionState::tp_price)
        .def_readwrite("bars_held", &PositionState::bars_held);

    py::class_<TickSignal>(m, "TickSignal")
        .def(py::init<>())
        .def_readwrite("symbol", &TickSignal::symbol)
        .def_readwrite("reason", &TickSignal::reason);

    py::class_<BatchResults>(m, "BatchResults")
        .def(py::init<>())
        .def_readwrite("exits", &BatchResults::exits)
        .def_readwrite("signals", &BatchResults::signals);

    m.def("calculate_excursion_metrics", &calculate_excursion_metrics, "Calculates MAE and MFE percentages");
    m.def("score_accumulation_pattern", &score_accumulation_pattern, "Vectorized institutional accumulation pattern scoring");
    m.def("validate_risk_batch", &validate_risk_batch, "Fast portfolio risk and sector batch validation");
    m.def("process_tick_batch", &process_tick_batch, "Atomic multi-stock scan, exit, and MTW update");
}
