#pragma once

#include <vector>
#include <string>
#include <unordered_map>
#include <cstdint>
#include <cmath>
#include <functional>
#include <stdexcept>
#include <algorithm>

#include "indicators.h"
#include "transaction_costs.h"

namespace kira {

// ─── Flat tick data (no heap allocs per tick) ─────────────────────
struct TickData {
    int         symbol_id;      // Mapped from string symbol
    double      price;
    int         volume;
    int64_t     timestamp_ms;
    int         date_int;       // YYYYMMDD as integer
    int         hour;
    int         minute;
};

// ─── Buffered order record (flushed to DB at end) ────────────────
struct OrderRecord {
    int         symbol_id;
    std::string symbol;         // Original string for DB write
    std::string side;           // "BUY" or "SELL"
    int         quantity;
    double      price;
    double      pnl;
    bool        has_pnl;        // false for opening trades
    int64_t     timestamp_ms;
};

// ─── Position state ──────────────────────────────────────────────
struct Position {
    int    qty       = 0;
    double avg_price = 0.0;
};

// ─── Engine configuration ────────────────────────────────────────
struct EngineConfig {
    double initial_cash        = 100000.0;
    int    square_off_hour     = 15;
    int    square_off_minute   = 20;
    bool   is_cnc              = false;   // MIS vs CNC
    double leverage            = 1.0;
};

// =================================================================
//  KiraEngine — High-performance C++ backtest core
// =================================================================
class KiraEngine {
public:
    // ── Configuration ──
    EngineConfig config;

    // ── Portfolio state (in-memory, no DB during simulation) ──
    double cash_ = 0.0;
    std::unordered_map<int, Position> positions_;

    // ── Symbol mapping (string ↔ int for zero-alloc tick loop) ──
    std::unordered_map<std::string, int> symbol_to_id_;
    std::unordered_map<int, std::string> id_to_symbol_;
    int next_symbol_id_ = 0;

    // ── Tick data ──
    std::vector<TickData> ticks_;

    // ── Indicator registry: symbol_id → list of indicator ptrs ──
    std::unordered_map<int, std::vector<IndicatorBase*>> indicators_;

    // ── Buffered orders (flushed once post-simulation) ──
    std::vector<OrderRecord> order_buffer_;

    // ── State tracking ──
    int    last_date_int_       = 0;
    bool   squared_off_today_  = false;
    int    trade_count_         = 0;
    double total_portfolio_value_ = 0.0;

    // ── Last known prices (for portfolio valuation) ──
    std::unordered_map<int, double> last_prices_;

    // ── Transaction cost calculator ──
    TransactionCostCalculator cost_calc_;

    // ── Equity curve (sparse: day rollovers + start/end) ──
    std::vector<std::pair<int64_t, double>> equity_curve_;

    // ================================================================
    //  Public API
    // ================================================================

    KiraEngine() = default;

    void configure(double initial_cash, int sq_hour, int sq_minute,
                   bool is_cnc, double leverage) {
        config.initial_cash      = initial_cash;
        config.square_off_hour   = sq_hour;
        config.square_off_minute = sq_minute;
        config.is_cnc            = is_cnc;
        config.leverage          = leverage;
        cash_ = initial_cash;
        cost_calc_ = TransactionCostCalculator(is_cnc);
    }

    // ── Symbol mapping ──

    int get_or_create_symbol_id(const std::string& symbol) {
        auto it = symbol_to_id_.find(symbol);
        if (it != symbol_to_id_.end()) return it->second;
        int id = next_symbol_id_++;
        symbol_to_id_[symbol] = id;
        id_to_symbol_[id] = symbol;
        return id;
    }

    std::string get_symbol_name(int id) const {
        auto it = id_to_symbol_.find(id);
        return (it != id_to_symbol_.end()) ? it->second : "";
    }

    // ── Data loading ──

    void reserve_ticks(size_t count) {
        ticks_.reserve(count);
    }

    void add_tick(int symbol_id, double price, int volume,
                  int64_t timestamp_ms, int date_int, int hour, int minute) {
        ticks_.push_back({symbol_id, price, volume, timestamp_ms,
                          date_int, hour, minute});
    }

    size_t tick_count() const { return ticks_.size(); }

    // ── Indicator registration ──

    void register_sma(int symbol_id, int period, int indicator_id) {
        auto* sma = new SMAIndicator(period);
        sma->id = indicator_id;
        indicators_[symbol_id].push_back(sma);
    }

    void register_ema(int symbol_id, int period, int indicator_id) {
        auto* ema = new EMAIndicator(period);
        ema->id = indicator_id;
        indicators_[symbol_id].push_back(ema);
    }

    double get_indicator_value(int indicator_id) const {
        for (const auto& [sym, inds] : indicators_) {
            for (const auto* ind : inds) {
                if (ind->id == indicator_id) return ind->value;
            }
        }
        return 0.0;
    }

    bool is_indicator_ready(int indicator_id) const {
        for (const auto& [sym, inds] : indicators_) {
            for (const auto* ind : inds) {
                if (ind->id == indicator_id) return ind->is_ready;
            }
        }
        return false;
    }

    // ── Portfolio queries (called from Python strategy) ──

    double get_cash() const { return cash_; }

    int get_position_qty(int symbol_id) const {
        auto it = positions_.find(symbol_id);
        return (it != positions_.end()) ? it->second.qty : 0;
    }

    double get_position_avg_price(int symbol_id) const {
        auto it = positions_.find(symbol_id);
        return (it != positions_.end()) ? it->second.avg_price : 0.0;
    }

    bool has_position(int symbol_id) const {
        auto it = positions_.find(symbol_id);
        return (it != positions_.end()) && (it->second.qty != 0);
    }

    double get_last_price(int symbol_id) const {
        auto it = last_prices_.find(symbol_id);
        return (it != last_prices_.end()) ? it->second : 0.0;
    }

    double get_portfolio_value() const {
        return total_portfolio_value_;
    }

    // ── Compute portfolio value ──

    double calculate_portfolio_value() {
        double equity = cash_;
        for (const auto& [sym_id, pos] : positions_) {
            if (pos.qty == 0) continue;
            auto pit = last_prices_.find(sym_id);
            double price = (pit != last_prices_.end()) ? pit->second : pos.avg_price;
            equity += pos.qty * price;
        }
        total_portfolio_value_ = equity;
        return equity;
    }

    // ================================================================
    //  Order Execution (100% in-memory, mirrors paper_exchange.py)
    // ================================================================

    bool set_holdings(int symbol_id, double percentage, double current_price) {
        if (current_price <= 0.0) return false;

        calculate_portfolio_value();
        double buying_power = total_portfolio_value_ * config.leverage;
        double target_value = buying_power * percentage;
        int target_qty = static_cast<int>(target_value / current_price);

        int current_qty = get_position_qty(symbol_id);
        int order_qty = target_qty - current_qty;
        if (order_qty == 0) return true;

        std::string action = (order_qty > 0) ? "BUY" : "SELL";

        // Cap BUY to available cash
        if (action == "BUY") {
            double usable_cash = cash_ * 0.98;
            double max_value = usable_cash / 1.001;
            int max_qty = static_cast<int>(max_value / current_price);
            if (max_qty <= 0) return false;
            if (order_qty > max_qty) order_qty = max_qty;
        }
        // Cap SELL for new shorts
        else {
            int current_long = std::max(0, current_qty);
            int qty_close_long = std::min(std::abs(order_qty), current_long);
            int qty_new_short = std::abs(order_qty) - qty_close_long;
            if (qty_new_short > 0) {
                double usable_cash = cash_ * 0.98;
                int max_short = static_cast<int>((usable_cash / 1.001) / current_price);
                if (max_short <= 0) {
                    order_qty = -qty_close_long;
                    if (order_qty == 0) return false;
                } else if (qty_new_short > max_short) {
                    order_qty = -(qty_close_long + max_short);
                }
            }
        }

        return execute_order(symbol_id, action, std::abs(order_qty),
                             current_price, 0 /* timestamp filled by caller */);
    }

    bool execute_order(int symbol_id, const std::string& action, int quantity,
                       double price, int64_t timestamp_ms) {
        if (quantity <= 0 || price <= 0.0) return false;

        auto& pos = positions_[symbol_id];
        const std::string& symbol = get_symbol_name(symbol_id);
        double turnover = price * quantity;

        if (action == "BUY") {
            if (pos.qty < 0) {
                // Cover short
                int qty_to_close = std::min(std::abs(pos.qty), quantity);
                double charges = cost_calc_.calculate(price * qty_to_close, "BUY");
                double gross_pnl = (pos.avg_price - price) * qty_to_close;
                double credit = pos.avg_price * qty_to_close + gross_pnl - charges;
                cash_ += credit;
                pos.qty += qty_to_close;
                if (pos.qty == 0) positions_.erase(symbol_id);

                order_buffer_.push_back({symbol_id, symbol, action, quantity,
                                         price, gross_pnl, true, timestamp_ms});
            } else {
                // Open/add to LONG
                double charges = cost_calc_.calculate(turnover, "BUY");
                double total_out = turnover + charges;
                if (cash_ < total_out) return false;
                cash_ -= total_out;

                if (pos.qty > 0) {
                    double new_avg = (pos.avg_price * pos.qty + price * quantity)
                                     / (pos.qty + quantity);
                    pos.qty += quantity;
                    pos.avg_price = new_avg;
                } else {
                    pos.qty = quantity;
                    pos.avg_price = price;
                }

                order_buffer_.push_back({symbol_id, symbol, action, quantity,
                                         price, 0.0, false, timestamp_ms});
            }
        }
        else if (action == "SELL") {
            if (pos.qty > 0) {
                // Close/reduce LONG
                int qty_to_close = std::min(pos.qty, quantity);
                double proceeds = price * qty_to_close;
                double charges = cost_calc_.calculate(proceeds, "SELL");
                double pnl = (price - pos.avg_price) * qty_to_close - charges;
                cash_ += proceeds - charges;
                pos.qty -= qty_to_close;
                if (pos.qty == 0) positions_.erase(symbol_id);

                order_buffer_.push_back({symbol_id, symbol, action, quantity,
                                         price, pnl, true, timestamp_ms});
            } else {
                // Open SHORT
                double charges = cost_calc_.calculate(turnover, "SELL");
                double total_out = turnover + charges;
                if (cash_ < total_out) return false;
                cash_ -= total_out;

                if (pos.qty < 0) {
                    int old_qty = std::abs(pos.qty);
                    double new_avg = (pos.avg_price * old_qty + price * quantity)
                                     / (old_qty + quantity);
                    pos.qty -= quantity;
                    pos.avg_price = new_avg;
                } else {
                    pos.qty = -quantity;
                    pos.avg_price = price;
                }

                order_buffer_.push_back({symbol_id, symbol, action, quantity,
                                         price, 0.0, false, timestamp_ms});
            }
        }

        trade_count_++;
        return true;
    }

    // ── Liquidate ──

    void liquidate(int symbol_id, int64_t timestamp_ms) {
        auto it = positions_.find(symbol_id);
        if (it == positions_.end() || it->second.qty == 0) return;

        double price = get_last_price(symbol_id);
        if (price <= 0.0) price = it->second.avg_price;

        if (it->second.qty > 0) {
            execute_order(symbol_id, "SELL", it->second.qty, price, timestamp_ms);
        } else {
            execute_order(symbol_id, "BUY", std::abs(it->second.qty), price, timestamp_ms);
        }
    }

    void liquidate_all(int64_t timestamp_ms) {
        // Collect keys first (iteration invalidation safety)
        std::vector<int> syms;
        for (const auto& [sid, pos] : positions_) {
            if (pos.qty != 0) syms.push_back(sid);
        }
        for (int sid : syms) {
            liquidate(sid, timestamp_ms);
        }
    }

    // ================================================================
    //  Main Tick Loop (the HOT PATH)
    // ================================================================

    // Callback type: called for each tick, passing (symbol_id, price, volume, timestamp_ms)
    // Returns: void. The Python side will call set_holdings/liquidate back into C++.
    using OnTickCallback = std::function<void(int, double, int, int64_t)>;

    void run(OnTickCallback on_tick) {
        last_date_int_ = 0;
        squared_off_today_ = false;

        // Record starting equity
        equity_curve_.push_back({0, config.initial_cash});

        const size_t n = ticks_.size();
        for (size_t i = 0; i < n; ++i) {
            const TickData& t = ticks_[i];

            // ── Update last price ──
            last_prices_[t.symbol_id] = t.price;

            // ── Update indicators ──
            auto ind_it = indicators_.find(t.symbol_id);
            if (ind_it != indicators_.end()) {
                for (auto* ind : ind_it->second) {
                    ind->update(t.price);
                }
            }

            // ── Date rollover ──
            if (t.date_int != last_date_int_) {
                handle_date_rollover(t);
            }

            // ── Square-off check ──
            if (t.hour == config.square_off_hour &&
                t.minute >= config.square_off_minute &&
                !squared_off_today_) {
                squared_off_today_ = true;
                if (!config.is_cnc) {
                    liquidate_all(t.timestamp_ms);
                }
                continue;  // Skip user callback for square-off tick
            }

            // ── Call user strategy (Python callback via PyBind11) ──
            on_tick(t.symbol_id, t.price, t.volume, t.timestamp_ms);
        }

        // Final equity snapshot
        calculate_portfolio_value();
        equity_curve_.push_back({
            ticks_.empty() ? 0 : ticks_.back().timestamp_ms,
            total_portfolio_value_
        });
    }

    // ── Results access ──

    const std::vector<OrderRecord>& get_orders() const { return order_buffer_; }
    int get_trade_count() const { return trade_count_; }
    const std::vector<std::pair<int64_t, double>>& get_equity_curve() const {
        return equity_curve_;
    }

    // ── Cleanup ──

    ~KiraEngine() {
        for (auto& [sym, inds] : indicators_) {
            for (auto* ind : inds) {
                delete ind;
            }
        }
    }

private:
    void handle_date_rollover(const TickData& t) {
        if (last_date_int_ != 0) {
            calculate_portfolio_value();
            equity_curve_.push_back({t.timestamp_ms, total_portfolio_value_});
        }
        last_date_int_ = t.date_int;
        squared_off_today_ = false;
    }
};

} // namespace kira
