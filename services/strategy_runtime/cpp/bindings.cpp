// PyBind11 bindings for the KIRA C++ backtesting engine.
// Exposes KiraEngine, indicators, and order records to Python.

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/functional.h>

#include "kira_engine.h"

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
        .def("run", [](KiraEngine& self, py::function on_tick) {
            // Release GIL for the C++ loop, re-acquire only for callback
            py::gil_scoped_release release;

            self.run([&on_tick](int sym_id, double price, int volume, int64_t ts) {
                py::gil_scoped_acquire acquire;
                on_tick(sym_id, price, volume, ts);
            });
        }, py::arg("on_tick"),
           "Run the tick loop. Calls on_tick(symbol_id, price, volume, timestamp_ms) per tick.")

        // Results
        .def("get_orders",       &KiraEngine::get_orders)
        .def("get_trade_count",  &KiraEngine::get_trade_count)
        .def("get_equity_curve", &KiraEngine::get_equity_curve);
}
