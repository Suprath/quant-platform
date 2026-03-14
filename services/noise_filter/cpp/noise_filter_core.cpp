#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <vector>
#include <numeric>
#include <cmath>
#include <algorithm>

namespace py = pybind11;

/**
 * KIRA Noise Filter Core (C++)
 * Implementation of high-performance signal processing for market data.
 */

class NoiseFilterCore {
public:
    NoiseFilterCore() {}

    /**
     * Calculates a confidence score (0-100) based on volatility and trend.
     * Higher score = lower noise/higher signal quality.
     */
    int calculate_confidence(const std::vector<double>& prices) {
        if (prices.size() < 5) return 0;

        // 1. Calculate Returns
        std::vector<double> returns;
        for (size_t i = 1; i < prices.size(); ++i) {
            returns.push_back((prices[i] - prices[i-1]) / prices[i-1]);
        }

        // 2. Average Return (Trend)
        double sum_returns = std::accumulate(returns.begin(), returns.end(), 0.0);
        double avg_return = sum_returns / returns.size();

        // 3. Volatility (Standard Deviation of returns)
        double sq_sum = std::inner_product(returns.begin(), returns.end(), returns.begin(), 0.0);
        double stdev = std::sqrt(sq_sum / returns.size() - avg_return * avg_return);

        // 4. Signal-to-Noise Ratio (Heuristic)
        // High trend + Low volatility = High confidence
        if (stdev == 0) return 50;
        
        double abs_trend = std::abs(avg_return);
        double snr = abs_trend / stdev;

        // Map SNR to 0-100 score
        // (This is a simplified mapping for demonstration)
        double score = std::min(100.0, std::max(0.0, snr * 200.0));
        
        // Bonus for trend consistency
        int crossings = 0;
        for (size_t i = 1; i < returns.size(); ++i) {
            if ((returns[i] > 0 && returns[i-1] < 0) || (returns[i] < 0 && returns[i-1] > 0)) {
                crossings++;
            }
        }
        
        // Subtract penalty for high noise (frequent crossings)
        score -= (crossings * 5);
        
        return (int)std::min(100.0, std::max(0.0, score));
    }

    /**
     * Batch process prices to generate a sequence of confidence scores.
     * Useful for historical signal generation.
     */
    std::vector<int> process_batch(const std::vector<double>& prices, int window_size) {
        std::vector<int> results;
        if (prices.size() < window_size) return results;

        for (size_t i = 0; i <= prices.size() - window_size; ++i) {
            std::vector<double> window(prices.begin() + i, prices.begin() + i + window_size);
            results.push_back(calculate_confidence(window));
        }
        return results;
    }
};

PYBIND11_MODULE(noise_filter_core, m) {
    py::class_<NoiseFilterCore>(m, "NoiseFilterCore")
        .def(py::init<>())
        .def("calculate_confidence", &NoiseFilterCore::calculate_confidence)
        .def("process_batch", &NoiseFilterCore::process_batch);
}
