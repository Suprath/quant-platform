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
#include "microstructure.h"

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

// --- EXTREME HFT: FIXED RING BUFFER ---
template<size_t N>
struct FixedRingBuffer {
    double data[N] = {0};
    int head = 0;
    int count = 0;
    inline void push(double val) {
        data[head] = val;
        head = (head + 1) % N;
        if (count < N) count++;
    }
    inline double front() const { return data[head]; } // Oldest
    inline int size() const { return count; }
};

// --- EXTREME HFT: STATIC MONOTONIC WINDOW (Zero-Deque Circular) ---
template<size_t N>
struct StaticMonotonicWindow {
    struct Node { double val; int idx; };
    Node max_q[N], min_q[N];
    int max_head = 0, max_tail = 0, max_cnt = 0;
    int min_head = 0, min_tail = 0, min_cnt = 0;
    int total_count = 0;

    void push(double val) {
        // Max Queue
        while (max_cnt > 0 && max_q[(max_tail + N - 1) % N].val <= val) {
            max_tail = (max_tail + N - 1) % N;
            max_cnt--;
        }
        max_q[max_tail] = {val, total_count};
        max_tail = (max_tail + 1) % N;
        max_cnt++;

        // Min Queue
        while (min_cnt > 0 && min_q[(min_tail + N - 1) % N].val >= val) {
            min_tail = (min_tail + N - 1) % N;
            min_cnt--;
        }
        min_q[min_tail] = {val, total_count};
        min_tail = (min_tail + 1) % N;
        min_cnt++;
        
        // Eviction
        if (total_count - max_q[max_head].idx >= (int)N) {
            max_head = (max_head + 1) % N;
            max_cnt--;
        }
        if (total_count - min_q[min_head].idx >= (int)N) {
            min_head = (min_head + 1) % N;
            min_cnt--;
        }
        total_count++;
    }
    inline double get_max() const { return max_q[max_head].val; }
    inline double get_min() const { return min_q[min_head].val; }
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
    
    // O(1) Accumulators
    double sum_y = 0.0;
    double sum_xy = 0.0;
    double sum_a = 0.0;  // ATR sum
    double sum_a2 = 0.0; // ATR sq sum
    
    FixedRingBuffer<50> price_window; 
    FixedRingBuffer<50> atr_window;  
    StaticMonotonicWindow<30> tick_range_window; 
};

class SimulationEngine {
public:
    double initial_capital;
    double current_cash;
    double current_equity;
    double current_exposure = 0.0; // O(1) tracking
    
    // Performance Trackers for Kelly Formula
    int64_t win_count = 0;
    int64_t loss_count = 0;
    double  win_sum = 0.0;
    double  loss_sum = 0.0;

    std::vector<Position> positions;
    std::vector<bool> has_position;
    std::vector<double> last_prices;
    std::vector<SymbolState> symbol_features;
    std::vector<TradeRecord> trades;

    static constexpr int    MAX_POSITIONS      = 10;
    static constexpr double MAX_HEAT_PCT       = 4.0; 
    static constexpr double RISK_PER_TRADE_PCT = 0.02; // Initial/Fallback risk
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

    double get_kelly_fraction() const {
        // Require at least 5 trades for statistical significance
        if (win_count + loss_count < 5) return RISK_PER_TRADE_PCT; 
        
        double p = (double)win_count / (win_count + loss_count);
        double avg_win = win_sum / (win_count > 0 ? win_count : 1);
        double avg_loss = std::abs(loss_sum / (loss_count > 0 ? loss_count : 1));
        
        // b = Win/Loss Ratio
        double b = (avg_loss > 0) ? avg_win / avg_loss : 1.0;
        
        // Kelly Formula: f* = (p*b - (1-p)) / b
        double f_star = (p * b - (1.0 - p)) / std::max(0.1, b);
        
        // Institutional Guardrails: 0.5 * Kelly (Half-Kelly)
        return std::max(0.005, std::min(0.08, f_star * 0.5));
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
                // Pre-fill ring buffers (Zero-Deque)
                for(int j=0; j<50; ++j) {
                    fs.price_window.push(price);
                    fs.atr_window.push(fs.atr);
                }
                fs.sum_y = price * 50;
                fs.sum_xy = 0;
                for(int j=0; j<50; ++j) fs.sum_xy += j * price;
                
                fs.sum_a = fs.atr * 50;
                fs.sum_a2 = (fs.atr * fs.atr) * 50;
            }
            fs.count++;

            update_equity(sym_id, price);
            
            // --- O(1) ROLLING SMA50 ---
            double outgoing_p = fs.price_window.front();
            fs.sma50_sum = fs.sma50_sum - outgoing_p + price;
            fs.sma50 = fs.sma50_sum / 50.0;

            // --- O(1) ROLLING REGRESSION ---
            fs.sum_xy = fs.sum_xy - (fs.sum_y - outgoing_p) + 49.0 * price;
            fs.sum_y = fs.sum_y - outgoing_p + price;
            fs.price_window.push(price);
            
            double velocity = (50.0 * fs.sum_xy - 1225.0 * fs.sum_y) / 520625.0 / price * 100.0;
            fs.sma200 = fs.sma200 * 0.995 + price * 0.005;

            // DRAWDOWN SHIELD
            long current_day = (long)(ts / 86400); 
            if (current_day != fs.last_day) {
                fs.daily_pnl = 0.0;
                fs.deactivated = false;
                fs.last_day = current_day;
            }
            
            // --- O(1) ATR + VOL_Z (ZERO-DEQUE) ---
            fs.tick_range_window.push(price);
            double tr = std::max({
                fs.tick_range_window.get_max() - fs.tick_range_window.get_min(),
                std::abs(price - prev_close)
            });
            fs.atr = (fs.atr * 19.0 + tr) / 20.0; 
            
            double outgoing_a = fs.atr_window.front();
            fs.sum_a = fs.sum_a - outgoing_a + fs.atr;
            fs.sum_a2 = fs.sum_a2 - (outgoing_a * outgoing_a) + (fs.atr * fs.atr);
            fs.atr_window.push(fs.atr);

            double a_mean = fs.sum_a / 50.0;
            double a_var = (fs.sum_a2 / 50.0) - (a_mean * a_mean);
            double vol_z = (a_var > 1e-9) ? (fs.atr - a_mean) / std::sqrt(a_var) : 0;

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

                    // Update Kelly Metrics
                    if (net_pnl > 0) {
                        win_count++;
                        win_sum += net_pnl;
                    } else {
                        loss_count++;
                        loss_sum += net_pnl;
                    }

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
                        double kelly_pct = get_kelly_fraction();
                        int qty = (int)((current_equity * kelly_pct * risk_mult) / price);
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

    // ── MicrostructureEngine bindings ──────────────────────────────────────────
    py::class_<MicrostructureEngine>(m, "MicrostructureEngine")
        .def(py::init<int>(), py::arg("n_symbols"))
        .def("update_tick", &MicrostructureEngine::update_tick,
             py::arg("symbol_id"), py::arg("actual_return"), py::arg("variance_hint"),
             py::arg("volume"), py::arg("timestamp"))
        .def("get_state", [](MicrostructureEngine& eng, int sym_id) {
            auto& s = eng.get_state_ref(sym_id);
            py::dict d;
            d["alpha_kalman"]  = s.alpha_kalman;
            d["lambda_hawkes"] = s.lambda_hawkes;
            d["cusum_fired"]   = s.cusum_fired;
            d["variance"]      = s.variance;
            d["spread"]        = s.spread;
            return d;
        }, py::arg("symbol_id"))
        .def("__len__", [](const MicrostructureEngine& eng) {
            return eng.states.size();
        });
}
