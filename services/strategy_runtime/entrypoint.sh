#!/bin/bash
# Entrypoint for strategy_runtime container.
# Compiles the C++ engine if KIRA_CPP_ENGINE=true and .so not found.

set -e

if [ "${KIRA_CPP_ENGINE}" = "true" ]; then
    SO_FILE=$(find /app -maxdepth 1 -name "kira_engine*.so" 2>/dev/null | head -1)
    if [ -z "$SO_FILE" ] && [ -d "/app/cpp" ]; then
        echo "🔧 Building C++ engine (kira_engine)..."
        cd /app/cpp
        mkdir -p build && cd build
        cmake -DCMAKE_BUILD_TYPE=Release \
              -Dpybind11_DIR=$(python3 -c "import pybind11; print(pybind11.get_cmake_dir())") \
              .. 2>&1 | tail -3
        make -j$(nproc) 2>&1 | tail -5
        cp kira_engine*.so /app/
        echo "✅ C++ engine built successfully"
    elif [ -n "$SO_FILE" ]; then
        echo "✅ C++ engine already compiled: $SO_FILE"
    fi
fi

exec "$@"
