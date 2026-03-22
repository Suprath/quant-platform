#!/bin/bash
# Entrypoint for strategy_runtime container.
# Compiles the C++ engine if KIRA_CPP_ENGINE=true.
# Always recompiles if source files are newer than the existing .so.

set -e

if [ "${KIRA_CPP_ENGINE}" = "true" ] && [ -d "/app/cpp" ]; then
    SO_FILE=$(find /app -maxdepth 1 -name "kira_engine*.so" 2>/dev/null | head -1)
    NEEDS_BUILD=false

    if [ -z "$SO_FILE" ]; then
        if command -v cmake >/dev/null 2>&1; then
            NEEDS_BUILD=true
        else
            echo "❌ ERROR: kira_engine.so not found and cmake not available for build!"
            # Don't exit 1 here yet, let it try to run Python if possible (though it will fail later)
            # Actually, exiting 1 is better to stop the restart loop in a 'Backoff' state
            exit 1
        fi
    else
        # Recompile ONLY if source is newer AND cmake is available
        NEWER=$(find /app/cpp -name "*.h" -o -name "*.cpp" -o -name "CMakeLists.txt" | \
                xargs -I{} find {} -newer "$SO_FILE" 2>/dev/null | head -1)
        if [ -n "$NEWER" ] && command -v cmake >/dev/null 2>&1; then
            NEEDS_BUILD=true
            echo "🔄 C++ source changed, recompiling..."
        fi
    fi

    if [ "$NEEDS_BUILD" = true ]; then
        echo "🔧 Building C++ engine (kira_engine)..."
        cd /app/cpp
        rm -rf build
        mkdir -p build && cd build
        cmake -DCMAKE_BUILD_TYPE=Release \
              -Dpybind11_DIR=$(python3 -c "import pybind11; print(pybind11.get_cmake_dir())") \
              .. 2>&1 | tail -3
        make -j$(nproc) 2>&1 | tail -5
        cp kira_engine*.so /app/
        echo "✅ C++ engine built successfully"
    else
        echo "✅ C++ engine up-to-date: $SO_FILE"
    fi
fi

exec "$@"

