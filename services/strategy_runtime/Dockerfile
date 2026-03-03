# 1. Builder Stage
FROM python:3.11-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y build-essential librdkafka-dev libpq-dev cmake && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt
RUN pip install --no-cache pybind11[global]

# 2. Build C++ Engine
COPY cpp/ /app/cpp/
RUN cd /app/cpp && mkdir -p build && cd build && \
    cmake -DCMAKE_BUILD_TYPE=Release \
    -Dpybind11_DIR=$(python3 -c "import pybind11; print(pybind11.get_cmake_dir())") \
    .. && \
    make -j$(nproc) && \
    cp kira_engine*.so /app/

# 3. Production Stage
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y librdkafka1 libpq5 \
    build-essential cmake librdkafka-dev libpq-dev && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/wheels /wheels
COPY --from=builder /app/requirements.txt .
RUN pip install --no-cache /wheels/*
RUN pip install --no-cache pybind11[global]
COPY --from=builder /app/kira_engine*.so /app/
COPY . .
RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "main.py"]