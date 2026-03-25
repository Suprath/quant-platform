#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>
#include <vector>
#include <string>
#include <cmath>
#include <algorithm>
#include <map>
#include <unordered_map>
#include <chrono>
#include <deque>

namespace py = pybind11;

struct TradeRecord {
    double timestamp;
    int symbol_id;
    std::string direction;
    int qty;
    double price;
    double pnl;
    std::string reason;
};

struct Position {
    int symbol_id;
    double entry_price;
    double current_price;
    int qty;
    std::string direction;
    double sl_price;
    double tp_price;
    double peak_price;   // New: Track peak for trailing SL
    double trough_price; // New: Track trough for trailing SL
    int bars_held;
    std::string sector;
};

struct EquitySnapshot {
    double timestamp;
    double equity;
};

struct SimulationResult {
    double final_equity;
    double final_cash;
    std::vector<TradeRecord> trades;
    std::vector<EquitySnapshot> equity_curve;
    std::vector<Position> final_positions;
    double execution_time_ms;
};

struct SymbolState {
    double sma50 = 0.0;
    double prev_sma50 = 0.0; // New: Track slope
    double sma200 = 0.0;
    double atr = 0.0;
    double last_close = 0.0;
    double last_intensity = 0.0;
    double last_exit_ts = 0.0;
    std::vector<double> price_history;
    int count = 0;
};

class SimulationEngine {
public:
    double initial_capital;
    double cash;
    std::unordered_map<int, Position> positions;
    std::vector<TradeRecord> trades;
    std::unordered_map<int, double> last_prices;
    std::unordered_map<int, SymbolState> symbol_features;

    // ── Alpha Sniper Parameters (Restored High-Perf) ──
    static constexpr int    MAX_POSITIONS      = 2;     // Restore High Concentration
    static constexpr double MAX_HEAT_PCT       = 0.80;  // Restore Aggressive Heat
    static constexpr double RISK_PER_TRADE     = 0.10;  // Restore 10% Risk (Calibrated from 20% in ed0b736)
    static constexpr double MAX_POSITION_PCT   = 0.40;  
    static constexpr int    WARMUP_TICKS       = 200;   
    static constexpr double INTENSITY_THRESHOLD = 0.015; // Restore 1.5% for higher trade count
    static constexpr double SL_ATR_MULT        = 1.5;   // Restore 1.5x ATR Stop
    static constexpr double TP_ATR_MULT        = 4.0;   // Restore 4.0x ATR Target (Proven for booking fast gains)
    static constexpr double TRAIL_ATR_MULT     = 2.0;   
    static constexpr int    COOLDOWN_TICKS     = 480;   
    
    SimulationEngine(double cap) : initial_capital(cap), cash(cap) {}

    double get_total_equity() const {
        double eq = cash;
        for (auto const& [id, pos] : positions) {
            double p = last_prices.count(id) ? last_prices.at(id) : pos.entry_price;
            if (pos.direction == "LONG")
                eq += pos.qty * p;
            else
                eq += pos.qty * (2.0 * pos.entry_price - p); 
        }
        return eq;
    }

    double get_position_exposure() const {
        double exposure = 0.0;
        for (auto const& [id, pos] : positions) {
            double p = last_prices.count(id) ? last_prices.at(id) : pos.entry_price;
            exposure += pos.qty * p;
        }
        return exposure;
    }

    SimulationResult run_vectorized_simulation(py::array_t<double> tick_data,
                                            const std::map<int, std::string>& id_to_sym) {
        auto start_cpu = std::chrono::high_resolution_clock::now();
        
        trades.clear();

        auto r = tick_data.unchecked<2>();
        int n_ticks = r.shape(0);
        
        SimulationResult result;
        std::vector<EquitySnapshot> equity_curve;
        equity_curve.reserve(n_ticks / 50 + 1); 

        for (int i = 0; i < n_ticks; ++i) {
            double ts = r(i, 0);
            int sym_id = (int)r(i, 1);
            double price = r(i, 2);
            double volume = r(i, 3);
            double noise_conf = r(i, 4);
            
            // ── Feature calculation ──
            auto& fs = symbol_features[sym_id];
            double prev_close = (fs.count > 0) ? fs.last_close : price;
            fs.last_close = price;
            last_prices[sym_id] = price; // Moved here to ensure last_prices is updated for all ticks
            
            if (fs.count == 0) {
                fs.sma50 = price;
                fs.sma200 = price;
                fs.atr = 0.01 * price;
            }
            fs.count++;
            
            // SMA
            int n50 = std::min(fs.count, 50);
            int n200 = std::min(fs.count, 200);
            fs.sma50 = (fs.sma50 * (n50 - 1) + price) / n50;
            
            // ATR (Simplified ed06736 Version)
            double tr = std::max({std::abs(price - prev_close), std::abs(price - fs.sma50), std::abs(prev_close - fs.sma50)});
            fs.atr = (fs.atr * 13 + tr) / 14; 

            double momentum = (prev_close > 0) ? (price / prev_close - 1.0) : 0.0;
            
            // (Removed CV-based Noise Heuristic in favor of QuestDB historical noise data)

            if (positions.count(sym_id)) {
                auto& pos = positions[sym_id];
                bool exit = false;
                std::string reason = "";

                if (pos.direction == "LONG") {
                    if (price <= pos.sl_price) { exit = true; reason = "SL"; }
                    else if (price >= pos.tp_price) { exit = true; reason = "TP"; }
                }

                if (exit) {
                    double pnl = pos.qty * (price - pos.entry_price);
                    double brokerage = 20.0 + (price * pos.qty * 0.001);
                    cash += (pos.qty * price) - brokerage;
                    trades.push_back({ts, sym_id, "SELL", pos.qty, price, pnl - brokerage, reason});
                    positions.erase(sym_id);
                }
            } else {
                if (momentum > 0.002 && noise_conf > 0.4) {
                    int qty = (int)((cash * 0.01) / price);
                    if (qty <= 0) qty = 1;
                    
                    double entry_brokerage = 20.0 + (price * qty * 0.001);
                    if (cash >= (qty * price + entry_brokerage)) {
                        cash -= (qty * price + entry_brokerage);
                        Position new_pos;
                        new_pos.symbol_id = sym_id;
                        new_pos.entry_price = price;
                        new_pos.qty = qty;
                        new_pos.direction = "LONG";
                        new_pos.sl_price = price - (fs.atr * 1.5);
                        new_pos.tp_price = price + (fs.atr * 4.0);
                        positions[sym_id] = new_pos;
                        trades.push_back({ts, sym_id, "LONG", qty, price, -entry_brokerage, "ALPHA"});
                    }
                }
            }

            // Equity snapshot every 50 ticks
            if (i % 50 == 0) {
                equity_curve.push_back({ts, get_total_equity()});
            }
        }

        result.final_cash = cash;
        double final_equity = get_total_equity();
        for (auto const& [id, pos] : positions) {
            double current_p = last_prices.count(id) ? last_prices.at(id) : pos.entry_price;
            Position p_copy = pos;
            p_copy.current_price = current_p;
            result.final_positions.push_back(p_copy);
        }
        result.final_equity = final_equity;
        result.trades = trades;
        result.equity_curve = equity_curve;

        auto end_cpu = std::chrono::high_resolution_clock::now();
        std::chrono::duration<double, std::milli> diff = end_cpu - start_cpu;
        result.execution_time_ms = diff.count();
        
        return result;
    }
};

PYBIND11_MODULE(til_core, m) {
    m.doc() = "KIRA Trading Intelligence Layer (TIL) C++ Core Performance Engine";

    py::class_<TradeRecord>(m, "TradeRecord")
        .def(py::init<>())
        .def_readwrite("timestamp", &TradeRecord::timestamp)
        .def_readwrite("symbol_id", &TradeRecord::symbol_id)
        .def_readwrite("direction", &TradeRecord::direction)
        .def_readwrite("qty", &TradeRecord::qty)
        .def_readwrite("price", &TradeRecord::price)
        .def_readwrite("pnl", &TradeRecord::pnl)
        .def_readwrite("reason", &TradeRecord::reason);

    py::class_<EquitySnapshot>(m, "EquitySnapshot")
            .def(py::init<>())
            .def_readwrite("timestamp", &EquitySnapshot::timestamp)
            .def_readwrite("equity", &EquitySnapshot::equity);

    py::class_<SimulationResult>(m, "SimulationResult")
        .def(py::init<>())
        .def_readwrite("final_equity", &SimulationResult::final_equity)
        .def_readwrite("final_cash", &SimulationResult::final_cash)
        .def_readwrite("trades", &SimulationResult::trades)
        .def_readwrite("equity_curve", &SimulationResult::equity_curve)
        .def_readwrite("final_positions", &SimulationResult::final_positions)
        .def_readwrite("execution_time_ms", &SimulationResult::execution_time_ms);

    py::class_<Position>(m, "Position")
        .def(py::init<>())
        .def_readwrite("symbol_id", &Position::symbol_id)
        .def_readwrite("entry_price", &Position::entry_price)
        .def_readwrite("current_price", &Position::current_price)
        .def_readwrite("qty", &Position::qty)
        .def_readwrite("direction", &Position::direction)
        .def_readwrite("sl_price", &Position::sl_price)
        .def_readwrite("tp_price", &Position::tp_price)
        .def_readwrite("peak_price", &Position::peak_price)
        .def_readwrite("trough_price", &Position::trough_price)
        .def_readwrite("bars_held", &Position::bars_held)
        .def_readwrite("sector", &Position::sector);

    py::class_<SimulationEngine>(m, "SimulationEngine")
        .def(py::init<double>())
        .def("run_vectorized_simulation", &SimulationEngine::run_vectorized_simulation, "Runs high-speed tick simulation");
}
