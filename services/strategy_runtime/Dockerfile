FROM kira-python-base as builder

WORKDIR /app

# Install cmake for compilation
RUN apt-get update && apt-get install -y cmake && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache pybind11[global]

# Build C++ Engine (kira_engine — backtest metrics)
COPY services/strategy_runtime/cpp/ /app/cpp/
RUN cd /app/cpp && mkdir -p build && cd build && \
    cmake -DCMAKE_BUILD_TYPE=Release \
    -Dpybind11_DIR=$(python3 -c "import pybind11; print(pybind11.get_cmake_dir())") \
    .. && \
    make -j$(nproc) && \
    cp kira_engine*.so /app/

# Build til_core (MicrostructureEngine — Kalman/Hawkes/CUSUM, feeds /ws/orderflow)
COPY services/kira_til/cpp/ /build_til/cpp/
COPY services/kira_til/setup.py /build_til/
RUN cd /build_til && python setup.py build_ext --inplace && \
    cp til_core*.so $(python3 -c "import site; print(site.getsitepackages()[0])")/

# Final Stage
FROM kira-python-base
WORKDIR /app

# Install build tools in final stage for dev-mode (volume mounts)
RUN apt-get update && apt-get install -y cmake g++ build-essential && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache pybind11[global]

COPY --from=builder /app/kira_engine*.so /app/
COPY --from=builder /build_til/til_core*.so /usr/local/lib/python3.11/site-packages/

# Add kira-shared
COPY kira-shared /app/kira-shared
RUN pip install -e /app/kira-shared

COPY services/strategy_runtime/ .
RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "main.py"]