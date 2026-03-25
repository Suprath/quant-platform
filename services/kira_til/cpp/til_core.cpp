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
#include <iostream>
#include <deque>

namespace py = pybind11;

enum class Direction { NONE, LONG, SHORT };
enum class ExitReason { NONE, STOP_LOSS, TAKE_PROFIT, TRAILING_STOP, RIP_REVERT, PANIC_REVERT, QUANT_GOLDEN_LONG, QUANT_GOLDEN_SHORT };

struct TradeRecord {
    double timestamp;
    int symbol_id;
    Direction direction;
    int qty;
    double price;
    double pnl;
    double raw_pnl;
    double brokerage;
    ExitReason reason;
};

struct Position {
    int symbol_id;
    double entry_price;
    double current_price;
    double last_mark_price; 
    int qty;
    double entry_brokerage;
    Direction direction;
    double sl_price;
    double tp_price;
    double peak_price;
    double trough_price;
    int bars_held;
    std::string sector = "EQUITY";
};

struct EquitySnapshot {
    double timestamp;
    double equity;
};

// --- HFT OPTIMIZED RING BUFFER ---
struct PriceRingBuffer {
    double data[50] = {0};
    int head = 0;
    int count = 0;
    void push(double val) {
        data[head] = val;
        head = (head + 1) % 50;
        if (count < 50) count++;
    }
    double front() const { return data[head]; } // Oldest element
    int size() const { return count; }
};

struct MonotonicWindow {
    std::deque<std::pair<double, int>> max_q, min_q;
    int count = 0;
    int window_size;

    MonotonicWindow(int size) : window_size(size) {}

    void push(double val) {
        while (!max_q.empty() && max_q.back().first <= val) max_q.pop_back();
        while (!min_q.empty() && min_q.back().first >= val) min_q.pop_back();
        
        max_q.push_back({val, count});
        min_q.push_back({val, count});
        
        if (count - max_q.front().second >= window_size) max_q.pop_front();
        if (count - min_q.front().second >= window_size) min_q.pop_front();
        count++;
    }

    double get_max() const { return max_q.empty() ? 0.0 : max_q.front().first; }
    double get_min() const { return min_q.empty() ? 0.0 : min_q.front().first; }
    size_t size() const { return (size_t)std::min(count, window_size); }
};

struct SimulationResult {
    double total_return;
    double win_rate;
    double net_profit;
    double final_equity;
    double final_cash;
    int total_trades;
    std::vector<TradeRecord> trades;
    std::vector<EquitySnapshot> equity_curve;
    std::vector<Position> final_positions;
    double execution_time_ms;
};

struct SymbolState {
    double sma50 = 0.0;
    double sma50_sum = 0.0;
    double sma200 = 0.0;
    double sma200_sum = 0.0;
    double atr = 0.0;
    double last_close = 0.0;
    double sma5_vol = 0.0; 
    int count = 0;
    double daily_pnl = 0.0;
    long last_day = 0;
    long last_exit_tick = 0;
    bool deactivated = false;
    
    // Rolling Regression Accumulators (O(1))
    double sum_y = 0.0;
    double sum_xy = 0.0;
    
    PriceRingBuffer price_window; 
    std::deque<double> atr_window;  
    MonotonicWindow tick_range_window{30}; 
};

class SimulationEngine {
public:
    double initial_capital;
    double current_cash;
    double current_equity;
    double current_exposure = 0.0; // O(1) tracking
    
    std::vector<Position> positions;
    std::vector<bool> has_position;
    std::vector<double> last_prices;
    std::vector<SymbolState> symbol_features;
    std::vector<TradeRecord> trades;

    static constexpr int    MAX_POSITIONS      = 10;
    static constexpr double MAX_HEAT_PCT       = 4.0; 
    static constexpr double RISK_PER_TRADE_PCT = 0.02; 
    static constexpr double BROKERAGE_RATE     = 0.0005; 
    static constexpr int    COOLDOWN_TICKS     = 300;    
    static constexpr int    MAX_SYMBOLS        = 20000; 
    
    int active_position_count = 0;

    SimulationEngine(double cap) : initial_capital(cap), current_cash(cap), current_equity(cap) {
        positions.resize(MAX_SYMBOLS);
        has_position.assign(MAX_SYMBOLS, false);
        last_prices.assign(MAX_SYMBOLS, 0.0);
        symbol_features.resize(MAX_SYMBOLS);
    }

    void update_equity(int sym_id, double new_price) {
        if (has_position[sym_id]) {
            auto& pos = positions[sym_id];
            double delta = 0;
            if (pos.direction == Direction::LONG)
                delta = pos.qty * (new_price - pos.last_mark_price);
            else
                delta = pos.qty * (pos.last_mark_price - new_price);
            
            current_equity += delta;
            
            // Incremental Exposure Update (O(1))
            current_exposure -= std::abs(pos.qty * pos.last_mark_price);
            current_exposure += std::abs(pos.qty * new_price);
            
            pos.last_mark_price = new_price;
            pos.current_price = new_price;
        }
        last_prices[sym_id] = new_price;
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
            
            auto& fs = symbol_features[sym_id];
            double prev_close = (fs.count > 0) ? fs.last_close : price;
            fs.last_close = price;

            if (fs.count == 0) {
                fs.last_day = (long)(ts / 86400);
                last_prices[sym_id] = price; 
                fs.sma50 = price;
                fs.sma50_sum = price * 50; 
                fs.sma200 = price;
                fs.atr = 0.01 * price;
                // Pre-fill ring buffer to avoid cold-start branching
                for(int j=0; j<50; ++j) fs.price_window.push(price);
                fs.sum_y = price * 50;
                fs.sum_xy = 0;
                for(int j=0; j<50; ++j) fs.sum_xy += j * price;
            }
            fs.count++;

            update_equity(sym_id, price);
            
            // --- O(1) ROLLING SMA50 (CRITICAL BUG FIX #2) ---
            double outgoing_sma = fs.price_window.front();
            fs.sma50_sum -= outgoing_sma;
            fs.sma50_sum += price;
            fs.sma50 = fs.sma50_sum / 50.0;

            // --- O(1) ROLLING REGRESSION (PERF OPT) ---
            // sum_xy_new = sum_xy_old - sum_y_old + N * price_new - price_new
            fs.sum_xy = fs.sum_xy - (fs.sum_y - outgoing_sma) + 49.0 * price;
            fs.sum_y = fs.sum_y - outgoing_sma + price;
            
            fs.price_window.push(price);
            
            // 50 * sum_xy - sum_x * sum_y / denominator
            // sum_x = 1225, denominator = 50 * 40425 - 1225*1225 = 520625
            double velocity = (50.0 * fs.sum_xy - 1225.0 * fs.sum_y) / 520625.0 / price * 100.0;

            // SMA200 (Bias-Corrected EMA for O(1) memory)
            fs.sma200 = fs.sma200 * 0.995 + price * 0.005;

            // 4. DRAWDOWN SHIELD
            long current_day = (long)(ts / 86400); 
            if (current_day != fs.last_day) {
                fs.daily_pnl = 0.0;
                fs.deactivated = false;
                fs.last_day = current_day;
            }
            
            // 5. O(1) ATR (Monotonic Window)
            fs.tick_range_window.push(price);
            double tr = std::max({
                fs.tick_range_window.get_max() - fs.tick_range_window.get_min(),
                std::abs(price - prev_close)
            });
            fs.atr = (fs.atr * 19.0 + tr) / 20.0; 
            
            fs.atr_window.push_back(fs.atr);
            if (fs.atr_window.size() > 50) fs.atr_window.pop_front();
            double vol_z = 0; // Simplified for speed or implement O(1) variance
            if (fs.atr_window.size() >= 50) {
                double a_sum = 0, a_sq_sum = 0;
                for(double a : fs.atr_window) { a_sum += a; a_sq_sum += a*a; }
                double a_mean = a_sum / 50.0;
                double a_stdev = std::sqrt(std::max(0.0, (a_sq_sum / 50.0) - (a_mean * a_mean)));
                vol_z = (a_stdev > 0.0001) ? (fs.atr - a_mean) / a_stdev : 0;
            }

            // --- ALPHA SNIPER GATING ---
            bool strong_long_trend = (price > fs.sma200 * 1.005);
            bool strong_short_trend = (price < fs.sma200 * 0.995);

            bool panic_dip = (velocity < -0.06 && vol_z > 1.2 && price > fs.sma50);
            if (strong_long_trend) panic_dip = (velocity < -0.05 && vol_z > 1.0);

            bool rip_peak = (velocity > 0.06 && price > fs.sma50 * 1.005);
            if (strong_short_trend) rip_peak = (velocity > 0.05 && price > fs.sma200 * 0.995);

            if (has_position[sym_id]) {
                auto& pos = positions[sym_id];
                pos.bars_held++; // Fix bars_held increment
                bool should_exit = false;
                ExitReason exit_reason = ExitReason::NONE;

                if (pos.direction == Direction::LONG) {
                    pos.peak_price = std::max(pos.peak_price, price);
                    
                    if (price > pos.entry_price + (fs.atr * 1.5)) {
                        pos.sl_price = std::max(pos.sl_price, pos.entry_price);
                    }
                    
                    if (pos.peak_price > pos.entry_price + (fs.atr * 3.0)) {
                        if (price < pos.peak_price - (fs.atr * 2.0)) { should_exit = true; exit_reason = ExitReason::TRAILING_STOP; }
                    }

                    if (price <= pos.sl_price) { should_exit = true; exit_reason = ExitReason::STOP_LOSS; }
                    else if (price >= pos.tp_price) { should_exit = true; exit_reason = ExitReason::TAKE_PROFIT; }
                    else if (rip_peak) { should_exit = true; exit_reason = ExitReason::RIP_REVERT; }
                } else {
                    // Trough initialization bug fix
                    if (pos.bars_held == 1) pos.trough_price = price;
                    else pos.trough_price = std::min(pos.trough_price, price);

                    if (price < pos.entry_price - (fs.atr * 1.5)) {
                        pos.sl_price = std::min(pos.sl_price, pos.entry_price);
                    }
                    
                    if (pos.trough_price > 0 && pos.trough_price < pos.entry_price - (fs.atr * 3.0)) {
                        if (price > pos.trough_price + (fs.atr * 2.0)) { should_exit = true; exit_reason = ExitReason::TRAILING_STOP; }
                    }

                    if (price >= pos.sl_price) { should_exit = true; exit_reason = ExitReason::STOP_LOSS; }
                    else if (price <= pos.tp_price) { should_exit = true; exit_reason = ExitReason::TAKE_PROFIT; }
                    else if (panic_dip) { should_exit = true; exit_reason = ExitReason::PANIC_REVERT; }
                }

                if (should_exit) {
                    double exit_brokerage = price * pos.qty * BROKERAGE_RATE;
                    double total_brokerage = pos.entry_brokerage + exit_brokerage;
                    double raw_pnl = (pos.direction == Direction::LONG) ? (price - pos.entry_price) * pos.qty : (pos.entry_price - price) * pos.qty;
                    double net_pnl = raw_pnl - total_brokerage;
                    
                    fs.daily_pnl += net_pnl;
                    fs.last_exit_tick = i; 

                    if (fs.daily_pnl < -(initial_capital / MAX_POSITIONS) * 0.010) fs.deactivated = true;

                    // O(1) Cash & Exposure Settlement
                    if (pos.direction == Direction::LONG) {
                        current_cash += (pos.qty * price - exit_brokerage);
                    } else {
                        current_cash += (pos.qty * (2.0 * pos.entry_price - price) - exit_brokerage); 
                    }
                    current_exposure -= std::abs(pos.qty * price); 

                    trades.push_back({ts, sym_id, pos.direction, pos.qty, price, net_pnl, raw_pnl, total_brokerage, exit_reason});
                    has_position[sym_id] = false;
                    active_position_count--;
                }
            } else {
                bool in_cooldown = (i < fs.last_exit_tick + COOLDOWN_TICKS);
                bool leveraged_to_max = (current_cash < -initial_capital * 4.0);
                bool can_trade = (active_position_count < MAX_POSITIONS && !fs.deactivated && !in_cooldown && !leveraged_to_max);
                
                if (can_trade) {
                    Direction dir = Direction::NONE;
                    if (panic_dip) dir = Direction::LONG;
                    else if (rip_peak) dir = Direction::SHORT;

                    if (dir != Direction::NONE) {
                        double risk_mult = std::max(1.5, std::min(6.0, std::abs(velocity) / 0.05)); // Branchless clamp
                        int qty = (int)((initial_capital * RISK_PER_TRADE_PCT * risk_mult) / price);
                        if (qty <= 0) qty = 1;
                        double entry_brokerage = price * qty * BROKERAGE_RATE;
                        
                        // O(1) Exposure Check
                        if (current_exposure + qty * price < initial_capital * MAX_HEAT_PCT) {
                            if (dir == Direction::LONG) current_cash -= (qty * price + entry_brokerage);
                            else current_cash -= entry_brokerage; // Short: received (qty*price) implicitly in settlement

                            Position& new_pos = positions[sym_id];
                            new_pos.symbol_id = sym_id;
                            new_pos.entry_price = price;
                            new_pos.current_price = price;
                            new_pos.last_mark_price = price; // Fix Equity Drift
                            new_pos.qty = qty;
                            new_pos.direction = dir;
                            new_pos.entry_brokerage = entry_brokerage;
                            new_pos.sl_price = (dir == Direction::LONG) ? price - (fs.atr * 1.5) : price + (fs.atr * 1.5);
                            new_pos.tp_price = (dir == Direction::LONG) ? price + (fs.atr * 4.5) : price - (fs.atr * 4.5);
                            new_pos.peak_price = price;
                            new_pos.trough_price = price;
                            new_pos.bars_held = 0;
                            
                            has_position[sym_id] = true;
                            active_position_count++;
                            current_exposure += (qty * price); // O(1) incremental track
                        }
                    }
                }
            }
            if (i % 50 == 0) {
                equity_curve.push_back({ts, current_equity});
            }
        }

        auto end_cpu = std::chrono::high_resolution_clock::now();
        result.total_return = (current_equity / initial_capital - 1.0) * 100.0;
        result.win_rate = trades.empty() ? 0.0 : (double)std::count_if(trades.begin(), trades.end(), [](const TradeRecord& t){ return t.pnl > 0; }) / trades.size() * 100.0;
        result.net_profit = current_equity - initial_capital;
        result.final_equity = current_equity;
        result.final_cash = current_cash;
        result.total_trades = (int)trades.size();
        result.trades = trades;
        result.equity_curve = equity_curve;
        result.execution_time_ms = std::chrono::duration<double, std::milli>(end_cpu - start_cpu).count();

        // Sync final positions for MtM continuity
        for (size_t i = 0; i < has_position.size(); ++i) {
            if (has_position[i]) {
                Position p = positions[i];
                p.current_price = last_prices[i];
                result.final_positions.push_back(p);
            }
        }

        return result;
    }
};

PYBIND11_MODULE(til_core, m) {
    py::class_<TradeRecord>(m, "TradeRecord")
        .def_readonly("timestamp", &TradeRecord::timestamp)
        .def_readonly("symbol_id", &TradeRecord::symbol_id)
        .def_property_readonly("direction", [](const TradeRecord& t) { 
            if (t.direction == Direction::LONG) return "LONG";
            if (t.direction == Direction::SHORT) return "SHORT";
            return "NONE";
        })
        .def_readonly("qty", &TradeRecord::qty)
        .def_readonly("price", &TradeRecord::price)
        .def_readonly("pnl", &TradeRecord::pnl)
        .def_readonly("raw_pnl", &TradeRecord::raw_pnl)
        .def_readonly("brokerage", &TradeRecord::brokerage)
        .def_property_readonly("reason", [](const TradeRecord& t) {
            switch(t.reason) {
                case ExitReason::STOP_LOSS: return "STOP_LOSS";
                case ExitReason::TAKE_PROFIT: return "TAKE_PROFIT";
                case ExitReason::TRAILING_STOP: return "TRAILING_STOP";
                case ExitReason::RIP_REVERT: return "RIP_REVERT";
                case ExitReason::PANIC_REVERT: return "PANIC_REVERT";
                case ExitReason::QUANT_GOLDEN_LONG: return "QUANT_GOLDEN_LONG";
                case ExitReason::QUANT_GOLDEN_SHORT: return "QUANT_GOLDEN_SHORT";
                default: return "NONE";
            }
        });

    py::class_<EquitySnapshot>(m, "EquitySnapshot")
        .def_readonly("timestamp", &EquitySnapshot::timestamp)
        .def_readonly("equity", &EquitySnapshot::equity);

    py::class_<SimulationResult>(m, "SimulationResult")
        .def_readonly("total_return", &SimulationResult::total_return)
        .def_readonly("win_rate", &SimulationResult::win_rate)
        .def_readonly("net_profit", &SimulationResult::net_profit)
        .def_readonly("final_equity", &SimulationResult::final_equity)
        .def_readonly("final_cash", &SimulationResult::final_cash)
        .def_readonly("total_trades", &SimulationResult::total_trades)
        .def_readonly("trades", &SimulationResult::trades)
        .def_readonly("equity_curve", &SimulationResult::equity_curve)
        .def_readonly("final_positions", &SimulationResult::final_positions)
        .def_readonly("execution_time_ms", &SimulationResult::execution_time_ms);

    py::class_<Position>(m, "Position")
        .def_readonly("symbol_id", &Position::symbol_id)
        .def_readonly("entry_price", &Position::entry_price)
        .def_readonly("current_price", &Position::current_price)
        .def_readonly("qty", &Position::qty)
        .def_readonly("entry_brokerage", &Position::entry_brokerage)
        .def_property_readonly("direction", [](const Position& p) { 
            if (p.direction == Direction::LONG) return "LONG";
            if (p.direction == Direction::SHORT) return "SHORT";
            return "NONE";
        })
        .def_readonly("sl_price", &Position::sl_price)
        .def_readonly("tp_price", &Position::tp_price)
        .def_readonly("peak_price", &Position::peak_price)
        .def_readonly("trough_price", &Position::trough_price)
        .def_readonly("bars_held", &Position::bars_held)
        .def_readonly("sector", &Position::sector);

    py::class_<SimulationEngine>(m, "SimulationEngine")
        .def(py::init<double>())
        .def("run_vectorized_simulation", &SimulationEngine::run_vectorized_simulation);
}
