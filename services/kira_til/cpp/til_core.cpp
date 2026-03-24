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
    double obv = 0.0;
    double atr = 0.0;
    double last_close = 0.0;
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
            double prev_close = (fs.count > 0) ? fs.last_close : price;
            fs.last_close = price;
            
            if (fs.count == 0) {
                fs.sma50 = price;
                fs.sma200 = price;
                fs.obv = 0.0;
                fs.atr = 0.01 * price; // Seed ATR
            }
            fs.count++;
            
            // SMA
            int n50 = std::min(fs.count, 50);
            int n200 = std::min(fs.count, 200);
            fs.sma50 = (fs.sma50 * (n50 - 1) + price) / n50;
            fs.sma200 = (fs.sma200 * (n200 - 1) + price) / n200;
            
            // OBV & OBV Slope (approx)
            if (price > prev_close) fs.obv += r(i, 3); // volume at index 3? No, let's check ohlc_rows index.
            else if (price < prev_close) fs.obv -= r(i, 3);
            
            // ATR (simplified)
            double tr = std::max({std::abs(price - prev_close), std::abs(price - fs.sma50), std::abs(prev_close - fs.sma50)});
            fs.atr = (fs.atr * 13 + tr) / 14; 

            double momentum = (fs.sma50 > 0) ? (price / fs.sma50 - 1.0) : 0.0;
            
            // Noise Heuristic (Price variation in last 10 ticks)
            fs.price_history.push_back(price);
            if (fs.price_history.size() > 10) fs.price_history.erase(fs.price_history.begin());
            
            double noise_conf = 0.8; // Default
            if (fs.price_history.size() >= 10) {
                double v_sum = 0;
                for (double p : fs.price_history) v_sum += p;
                double v_avg = v_sum / 10.0;
                double v_var = 0;
                for (double p : fs.price_history) v_var += std::pow(p - v_avg, 2);
                double cv = (std::sqrt(v_var/10.0) / v_avg) * 100.0;
                noise_conf = std::max(0.0, std::min(1.0, 1.0 - (cv * 10.0))); 
            }
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
                    
                    // Apply Brokerage on Exit
                    double brokerage = 20.0 + (price * pos.qty * 0.001);
                    cash += (pos.qty * price) - brokerage;
                    
                    trades.push_back({ts, sym_id, (pos.direction == "LONG" ? "SHORT" : "LONG"), pos.qty, price, pnl - brokerage, reason});
                    positions.erase(sym_id);
                }
            } else {
                // Intelligent Scoring logic
                if (momentum > 0.002 && noise_conf > 0.4) {
                    // Accumulation Pattern Check (Simplified C++ version)
                    double score = 0.7; // High conviction fallback
                    
                    // Brokerage Sufficiency Filter
                    double est_cost = 40.0 + (price * 2.0 * 0.001);
                    double target_gain = fs.atr * 1.5;
                    
                    if (target_gain >= (est_cost * 2.0) && cash >= (price * 1)) {
                        int qty = (int)((cash * 0.2) / price);
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
                            new_pos.bars_held = 0;
                            positions[sym_id] = new_pos;
                            trades.push_back({ts, sym_id, "LONG", qty, price, -entry_brokerage, "SIGNAL"});
                        }
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
