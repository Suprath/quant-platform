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

double score_accumulation_pattern(double obv_slope, double adx, double vwap_dist, double relative_vol) {
    double score = 0.0;
    
    // OBV Slope: Direct institutional interest (40 points)
    if (obv_slope > 0) score += 40.0 * (std::min(obv_slope, 5.0) / 5.0);
    
    // ADX: Trend strength (20 points)
    if (adx > 20.0) score += 20.0 * (std::min(adx - 20.0, 30.0) / 30.0);
    
    // VWAP Distance: Valuation anchor (20 points)
    // Closer to VWAP is better for accumulation (within 2%)
    double abs_vwap_dist = std::abs(vwap_dist);
    if (abs_vwap_dist < 2.0) score += 20.0 * (1.0 - abs_vwap_dist / 2.0);
    
    // Relative Volume: Conviction (20 points)
    if (relative_vol > 1.2) score += 20.0 * (std::min(relative_vol - 1.2, 3.8) / 3.8);
    
    return std::min(score, 100.0);
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

    m.def("calculate_excursion_metrics", &calculate_excursion_metrics, "Calculates MAE and MFE percentages");
    m.def("score_accumulation_pattern", &score_accumulation_pattern, "Vectorized institutional accumulation pattern scoring");
    m.def("validate_risk_batch", &validate_risk_batch, "Fast portfolio risk and sector batch validation");
}
