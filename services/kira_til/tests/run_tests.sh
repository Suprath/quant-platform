#!/bin/bash
# run_tests.sh - Executes KIRA-TIL unit tests inside the Docker container

echo "🚀 Running Dockerized Tests for KIRA-TIL..."

# Ensure we are in the correct directory
cd "$(dirname "$0")/.."

# Run pytest inside the existing container
docker exec -it kira_til pytest tests/unit/test_backtest_metrics.py tests/unit/test_portfolio_engine.py

if [ $? -eq 0 ]; then
    echo "✅ All tests passed!"
else
    echo "❌ Some tests failed. Check logs above."
    exit 1
fi
