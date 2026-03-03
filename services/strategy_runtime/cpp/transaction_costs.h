#pragma once

#include <string>
#include <algorithm>
#include <cstdlib>

namespace kira {

// ─── Indian Equity Transaction Cost Model (NSE/BSE) ─────────────
// Mirrors calculations.py TransactionCostCalculator exactly.
class TransactionCostCalculator {
public:
    // Regulatory rates (FY 2024-25)
    static constexpr double BROKERAGE_FLAT_DEFAULT = 20.0;
    static constexpr double BROKERAGE_PCT_DEFAULT  = 0.0003;
    static constexpr double STT_SELL_MIS            = 0.00025;
    static constexpr double STT_BOTH_CNC            = 0.001;
    static constexpr double EXCHANGE_TXN             = 0.0000345;
    static constexpr double SEBI_FEE                 = 0.000001;
    static constexpr double STAMP_MIS                = 0.00003;
    static constexpr double STAMP_CNC                = 0.00015;
    static constexpr double GST_RATE                 = 0.18;

    bool is_cnc_ = false;
    double brokerage_flat_ = BROKERAGE_FLAT_DEFAULT;
    double brokerage_pct_  = BROKERAGE_PCT_DEFAULT;

    TransactionCostCalculator() = default;
    explicit TransactionCostCalculator(bool is_cnc) : is_cnc_(is_cnc) {
        // Allow env overrides (same as Python version)
        const char* flat_env = std::getenv("BROKERAGE_FLAT");
        if (flat_env) brokerage_flat_ = std::atof(flat_env);
        const char* pct_env = std::getenv("BROKERAGE_PCT");
        if (pct_env) brokerage_pct_ = std::atof(pct_env);
    }

    double calculate(double turnover, const std::string& side) const {
        if (turnover <= 0.0) return 0.0;

        // 1. Brokerage
        double brokerage = std::min(brokerage_flat_, turnover * brokerage_pct_);

        // 2. STT
        double stt = 0.0;
        if (is_cnc_) {
            stt = turnover * STT_BOTH_CNC;
        } else {
            stt = (side == "SELL") ? turnover * STT_SELL_MIS : 0.0;
        }

        // 3. Exchange transaction charges
        double exchange_txn = turnover * EXCHANGE_TXN;

        // 4. SEBI turnover fee
        double sebi_fee = turnover * SEBI_FEE;

        // 5. Stamp duty (buy-side only)
        double stamp_duty = 0.0;
        if (side == "BUY") {
            stamp_duty = turnover * (is_cnc_ ? STAMP_CNC : STAMP_MIS);
        }

        // 6. GST: 18% on (brokerage + exchange + SEBI)
        double gst = (brokerage + exchange_txn + sebi_fee) * GST_RATE;

        double total = brokerage + stt + exchange_txn + sebi_fee + stamp_duty + gst;

        // Round to 2 decimal places
        return static_cast<double>(static_cast<int64_t>(total * 100.0 + 0.5)) / 100.0;
    }
};

} // namespace kira
