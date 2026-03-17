FROM kira-python-base as builder

WORKDIR /app

# Install cmake for compilation
RUN apt-get update && apt-get install -y cmake && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache pybind11[global]

# Build C++ Engine
COPY services/strategy_runtime/cpp/ /app/cpp/
RUN cd /app/cpp && mkdir -p build && cd build && \
    cmake -DCMAKE_BUILD_TYPE=Release \
    -Dpybind11_DIR=$(python3 -c "import pybind11; print(pybind11.get_cmake_dir())") \
    .. && \
    make -j$(nproc) && \
    cp kira_engine*.so /app/

# Final Stage
FROM kira-python-base
WORKDIR /app

COPY --from=builder /app/kira_engine*.so /app/

# Add kira-shared
COPY kira-shared /app/kira-shared
RUN pip install -e /app/kira-shared

COPY services/strategy_runtime/ .
RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "main.py"]