// PyBind11 bindings for the KIRA C++ backtesting engine.
// Exposes KiraEngine, indicators, order records, and statistics to Python.

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/functional.h>

#include "kira_engine.h"
#include "statistics.h"

namespace py = pybind11;
using namespace kira;

PYBIND11_MODULE(kira_engine, m) {
    m.doc() = "KIRA C++ Backtesting Engine — High-performance tick loop with PyBind11";

    // ── OrderRecord (read-only from Python) ──
    py::class_<OrderRecord>(m, "OrderRecord")
        .def_readonly("symbol_id",    &OrderRecord::symbol_id)
        .def_readonly("symbol",       &OrderRecord::symbol)
        .def_readonly("side",         &OrderRecord::side)
        .def_readonly("quantity",     &OrderRecord::quantity)
        .def_readonly("price",        &OrderRecord::price)
        .def_readonly("pnl",          &OrderRecord::pnl)
        .def_readonly("has_pnl",      &OrderRecord::has_pnl)
        .def_readonly("timestamp_ms", &OrderRecord::timestamp_ms);

    // ── DrawdownResult ──
    py::class_<stats::DrawdownResult>(m, "DrawdownResult")
        .def_readonly("max_drawdown_pct", &stats::DrawdownResult::max_drawdown_pct)
        .def_readonly("peak_idx",         &stats::DrawdownResult::peak_idx)
        .def_readonly("trough_idx",       &stats::DrawdownResult::trough_idx)
        .def_readonly("duration_days",    &stats::DrawdownResult::duration_days);

    // ── TradeMetrics ──
    py::class_<stats::TradeMetrics>(m, "TradeMetrics")
        .def_readonly("win_rate",      &stats::TradeMetrics::win_rate)
        .def_readonly("profit_factor", &stats::TradeMetrics::profit_factor)
        .def_readonly("expectancy",    &stats::TradeMetrics::expectancy)
        .def_readonly("avg_win",       &stats::TradeMetrics::avg_win)
        .def_readonly("avg_loss",      &stats::TradeMetrics::avg_loss)
        .def_readonly("total_trades",  &stats::TradeMetrics::total_trades);

    // ── KiraEngine ──
    py::class_<KiraEngine>(m, "KiraEngine")
        .def(py::init<>())

        // Configuration
        .def("configure", &KiraEngine::configure,
             py::arg("initial_cash"), py::arg("sq_hour"), py::arg("sq_minute"),
             py::arg("is_cnc"), py::arg("leverage"))

        // Symbol mapping
        .def("get_or_create_symbol_id", &KiraEngine::get_or_create_symbol_id)
        .def("get_symbol_name",         &KiraEngine::get_symbol_name)

        // Data loading
        .def("reserve_ticks", &KiraEngine::reserve_ticks)
        .def("add_tick",      &KiraEngine::add_tick,
             py::arg("symbol_id"), py::arg("price"), py::arg("volume"),
             py::arg("timestamp_ms"), py::arg("date_int"),
             py::arg("hour"), py::arg("minute"))
        .def("tick_count", &KiraEngine::tick_count)

        // Indicators
        .def("register_sma",       &KiraEngine::register_sma)
        .def("register_ema",       &KiraEngine::register_ema)
        .def("get_indicator_value", &KiraEngine::get_indicator_value)
        .def("is_indicator_ready",  &KiraEngine::is_indicator_ready)

        // Portfolio
        .def("get_cash",              &KiraEngine::get_cash)
        .def("get_position_qty",      &KiraEngine::get_position_qty)
        .def("get_position_avg_price", &KiraEngine::get_position_avg_price)
        .def("has_position",          &KiraEngine::has_position)
        .def("get_last_price",        &KiraEngine::get_last_price)
        .def("get_portfolio_value",   &KiraEngine::get_portfolio_value)
        .def("calculate_portfolio_value", &KiraEngine::calculate_portfolio_value)

        // Trading
        .def("set_holdings", &KiraEngine::set_holdings,
             py::arg("symbol_id"), py::arg("percentage"), py::arg("current_price"))
        .def("execute_order", &KiraEngine::execute_order,
             py::arg("symbol_id"), py::arg("action"), py::arg("quantity"),
             py::arg("price"), py::arg("timestamp_ms"))
        .def("liquidate",     &KiraEngine::liquidate)
        .def("liquidate_all", &KiraEngine::liquidate_all)

        // Main loop — accepts a Python callable as the on_tick callback.
        // The GIL is held during the callback (PyBind11 default for py::function).
        .def("run", [](KiraEngine& self, py::function on_window, int window_size) {
            // Release GIL for the C++ loop, re-acquire only for callback
            py::gil_scoped_release release;

            self.run([&on_window](const std::vector<int64_t>& ts_list,
                                  const std::vector<int>& counts,
                                  const std::vector<int>& sym_ids, 
                                  const std::vector<double>& prices, 
                                  const std::vector<int>& volumes) {
                py::gil_scoped_acquire acquire;
                on_window(ts_list, counts, sym_ids, prices, volumes);
            }, window_size);
        }, py::arg("on_window"), py::arg("window_size") = 50,
           "Run the tick loop with windowed aggregation. Calls on_window(...) once per window of slices.")

        // Results
        .def("get_orders",       &KiraEngine::get_orders)
        .def("get_trade_count",  &KiraEngine::get_trade_count)
        .def("get_equity_curve", &KiraEngine::get_equity_curve);

    // ================================================================
    //  Statistics Module — Pure C++ financial metrics
    // ================================================================

    m.def("build_daily_returns", &stats::build_daily_returns,
          py::arg("equity_curve"), py::arg("initial_capital"),
          "Build daily percentage returns from an equity curve.");

    m.def("compute_sharpe", &stats::compute_sharpe,
          py::arg("returns"),
          py::arg("risk_free_rate") = 0.06,
          py::arg("ann_factor") = 252,
          "Annualised Sharpe Ratio (single-pass).");

    m.def("compute_sortino", &stats::compute_sortino,
          py::arg("returns"),
          py::arg("risk_free_rate") = 0.06,
          py::arg("ann_factor") = 252,
          "Sortino Ratio — penalises downside volatility only.");

    m.def("compute_max_drawdown_cpp", &stats::compute_max_drawdown,
          py::arg("equity_curve"),
          "Maximum drawdown (single-pass peak tracking). Returns DrawdownResult.");

    m.def("compute_cagr", &stats::compute_cagr,
          py::arg("initial"), py::arg("final_val"), py::arg("trading_days"),
          "Compound Annual Growth Rate (%).");

    m.def("compute_calmar", &stats::compute_calmar,
          py::arg("cagr_pct"), py::arg("max_dd_pct"),
          "Calmar Ratio = CAGR / |MaxDrawdown|.");

    m.def("compute_trade_metrics", &stats::compute_trade_metrics,
          py::arg("pnl_list"),
          "Compute trade-level metrics from PnL list. Returns TradeMetrics.");

    m.def("downsample_lttb", &stats::downsample_lttb,
          py::arg("data"), py::arg("max_points"),
          "LTTB downsampling of equity curve to max_points.");

    m.def("compute_total_return", &stats::compute_total_return,
          py::arg("initial"), py::arg("final_val"),
          "Total return as a percentage.");

    m.def("compute_net_profit", &stats::compute_net_profit,
          py::arg("initial"), py::arg("final_val"),
          "Absolute net profit/loss.");
}
