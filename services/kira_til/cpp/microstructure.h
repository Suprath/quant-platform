// services/kira_til/cpp/microstructure.h
#pragma once
#include <cmath>
#include <vector>
#include <unordered_map>
#include <string>

// ─── Kalman Filter ────────────────────────────────────────────────────────────
// Extracts persistent alpha (true edge) from noisy tick returns.
// R (measurement noise) is provided externally — use short-term return variance.
struct KalmanState {
    double alpha_hat = 0.0;  // Estimated hidden alpha (persistent edge)
    double P         = 1.0;  // Estimate uncertainty (posterior variance)
    double Q         = 1e-5; // Process noise (how fast alpha can change)

    inline double update(double actual_return, double expected_drift, double R) {
        if (R <= 0.0) R = 1e-4;
        P += Q;
        double K = P / (P + R);
        double surprise = actual_return - expected_drift - alpha_hat;
        alpha_hat += K * surprise;
        P *= (1.0 - K);
        return alpha_hat;
    }
};

// ─── Hawkes Process ───────────────────────────────────────────────────────────
// Models "unreacted" institutional order flow: a self-exciting jump intensity.
struct HawkesState {
    double lambda = 0.0;
    double kappa  = 2.0;     // Decay rate per second
    double last_ts = 0.0;

    inline double update(double timestamp, double volume) {
        double dt = timestamp - last_ts;
        if (dt > 0.0) {
            lambda *= std::exp(-kappa * dt);
        }
        lambda += volume;
        last_ts = timestamp;
        return lambda;
    }
};

// ─── CUSUM Regime-Change Detector ─────────────────────────────────────────────
// Numerically stable: normalises signal to z-score before CUSUM update.
struct CusumState {
    double C         = 0.0;
    double k         = 0.5;   // Allowance parameter
    double threshold = 5.0;   // Detection threshold

    inline bool update(double signal, double variance) {
        double sigma = (variance > 1e-10) ? std::sqrt(variance) : 1e-5;
        double z = signal / sigma;
        double log_lr = z - k;
        C = std::max(0.0, C + log_lr);
        if (C >= threshold) {
            C = 0.0;
            return true;
        }
        return false;
    }
};

// ─── Combined Instrument State ────────────────────────────────────────────────
struct InstrumentState {
    KalmanState  kalman;
    HawkesState  hawkes;
    CusumState   cusum;
    double       spread        = 0.0;
    double       variance      = 1e-4;
    double       last_price    = 0.0;
    double       alpha_kalman  = 0.0;
    double       lambda_hawkes = 0.0;
    bool         cusum_fired   = false;
};

// ─── MicrostructureEngine ─────────────────────────────────────────────────────
// Flat buffer of InstrumentState indexed by integer symbol_id.
class MicrostructureEngine {
public:
    std::vector<InstrumentState> states;
    static constexpr double EMA_ALPHA = 0.05;

    explicit MicrostructureEngine(int n_symbols) : states(n_symbols) {}

    bool update_tick(int symbol_id, double actual_return, double variance_hint,
                     double volume, double timestamp) {
        if (symbol_id < 0 || symbol_id >= (int)states.size()) return false;
        auto& s = states[symbol_id];

        double var = (variance_hint > 0.0) ? variance_hint : s.variance;
        s.variance = (1.0 - EMA_ALPHA) * s.variance + EMA_ALPHA * (actual_return * actual_return);

        s.alpha_kalman = s.kalman.update(actual_return, 0.0, var);
        s.lambda_hawkes = s.hawkes.update(timestamp, volume);
        s.cusum_fired = s.cusum.update(s.alpha_kalman, s.variance);

        return s.cusum_fired;
    }

    InstrumentState& get_state_ref(int symbol_id) {
        return states[symbol_id];
    }
};
