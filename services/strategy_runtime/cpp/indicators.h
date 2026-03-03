#pragma once

#include <vector>
#include <numeric>
#include <cstddef>

namespace kira {

// ─── Base indicator interface ────────────────────────────────────
class IndicatorBase {
public:
    int    id       = 0;
    double value    = 0.0;
    bool   is_ready = false;
    int    samples  = 0;

    virtual ~IndicatorBase() = default;
    virtual void update(double price) = 0;
};

// ─── SMA: O(1) update via circular buffer + running sum ─────────
class SMAIndicator : public IndicatorBase {
public:
    explicit SMAIndicator(int period)
        : period_(period), buffer_(period, 0.0), running_sum_(0.0), pos_(0) {}

    void update(double price) override {
        samples++;

        // Subtract old value, add new
        running_sum_ -= buffer_[pos_];
        buffer_[pos_] = price;
        running_sum_ += price;

        pos_ = (pos_ + 1) % period_;

        if (samples >= period_) {
            value = running_sum_ / static_cast<double>(period_);
            is_ready = true;
        } else {
            value = 0.0;
            is_ready = false;
        }
    }

private:
    int period_;
    std::vector<double> buffer_;
    double running_sum_;
    int pos_;
};

// ─── EMA: single multiply-accumulate ────────────────────────────
class EMAIndicator : public IndicatorBase {
public:
    explicit EMAIndicator(int period, double smoothing = 2.0)
        : period_(period), alpha_(smoothing / (period + 1.0)),
          initialized_(false) {}

    void update(double price) override {
        samples++;

        if (!initialized_) {
            value = price;
            initialized_ = true;
        } else {
            value = price * alpha_ + value * (1.0 - alpha_);
        }

        if (samples >= period_) {
            is_ready = true;
        }
    }

private:
    int    period_;
    double alpha_;
    bool   initialized_;
};

} // namespace kira
