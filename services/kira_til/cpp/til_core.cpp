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
    double sma200 = 0.0;
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
    
    SimulationEngine(double cap) : initial_capital(cap), cash(cap) {}

    SimulationResult run_vectorized_simulation(py::array_t<double> tick_data, 
                                            const std::map<int, std::string>& id_to_sym) {
        auto start_cpu = std::chrono::high_resolution_clock::now();
        
        auto r = tick_data.unchecked<2>();
        int n_ticks = r.shape(0);
        
        SimulationResult result;
        std::vector<EquitySnapshot> equity_curve;
        equity_curve.reserve(n_ticks / 50 + 1); 

        for (int i = 0; i < n_ticks; ++i) {
            double ts = r(i, 0);
            int sym_id = (int)r(i, 1);
            double price = r(i, 2);
            last_prices[sym_id] = price;
            
            // --- NEW: High-Performance C++ Feature Calculation ---
            auto& fs = symbol_features[sym_id];
            if (fs.count == 0) {
                fs.sma50 = price;
                fs.sma200 = price;
            }
            fs.count++;
            
            int n50 = std::min(fs.count, 50);
            int n200 = std::min(fs.count, 200);
            fs.sma50 = (fs.sma50 * (n50 - 1) + price) / n50;
            fs.sma200 = (fs.sma200 * (n200 - 1) + price) / n200;
            
            double momentum = (fs.sma50 > 0) ? (price / fs.sma50 - 1.0) : 0.0;
            // --- End Features ---

            if (positions.count(sym_id)) {
                auto& pos = positions[sym_id];
                bool exit = false;
                std::string reason = "";

                if (pos.direction == "LONG") {
                    if (price <= pos.sl_price) { exit = true; reason = "SL"; }
                    else if (price >= pos.tp_price) { exit = true; reason = "TP"; }
                } else {
                    if (price >= pos.sl_price) { exit = true; reason = "SL"; }
                    else if (price <= pos.tp_price) { exit = true; reason = "TP"; }
                }

                if (exit) {
                    double mult = (pos.direction == "LONG") ? 1.0 : -1.0;
                    double pnl = pos.qty * (price - pos.entry_price) * mult;
                    cash += (pos.qty * price);
                    trades.push_back({ts, sym_id, (pos.direction == "LONG" ? "SHORT" : "LONG"), pos.qty, price, pnl, reason});
                    positions.erase(sym_id);
                }
            } else {
                // Mean Reversion Trigger: Based on calculated momentum
                // adx_score substitute: Use simple volatility or just momentum for now
                double mom_abs = std::abs(momentum);
                double score = 0.0;
                
                // If price is 2% below SMA50 (momentum < -0.02)
                if (momentum < -0.02) {
                    score = std::min(1.0, std::abs(momentum) * 20.0); // 0.05 -> score 1.0
                }

                if (score >= 0.45 && cash >= (price * 1)) {
                    int qty = (int)((cash * 0.1) / price);
                    if (qty <= 0) qty = 1;
                    
                    if (cash >= (qty * price)) {
                        cash -= (qty * price);
                        Position new_pos;
                        new_pos.symbol_id = sym_id;
                        new_pos.entry_price = price;
                        new_pos.qty = qty;
                        new_pos.direction = "LONG";
                        new_pos.sl_price = price * 0.985; // 1.5% SL
                        new_pos.tp_price = price * 1.05;  // 5% TP
                        new_pos.bars_held = 0;
                        positions[sym_id] = new_pos;
                        trades.push_back({ts, sym_id, "LONG", qty, price, 0.0, "SIGNAL"});
                    }
                }
            }

            // Snapshotting: Every 50 ticks to keep equity_curve manageable
            if (i % 50 == 0) {
                double current_equity = cash;
                for (auto const& [id, pos] : positions) {
                    double p = (last_prices.count(id)) ? last_prices.at(id) : pos.entry_price;
                    current_equity += pos.qty * p;
                }
                equity_curve.push_back({ts, current_equity});
            }
        }

        result.final_cash = cash;
        double final_equity = cash;
        for (auto const& [id, pos] : positions) {
            double current_p = (last_prices.count(id)) ? last_prices.at(id) : pos.entry_price;
            final_equity += pos.qty * current_p;
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
        .def_readwrite("bars_held", &Position::bars_held)
        .def_readwrite("sector", &Position::sector);

    py::class_<SimulationEngine>(m, "SimulationEngine")
        .def(py::init<double>())
        .def("run_vectorized_simulation", &SimulationEngine::run_vectorized_simulation, "Runs high-speed tick simulation");
}
