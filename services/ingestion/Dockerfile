# 1. Builder Stage
FROM python:3.11-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y build-essential librdkafka-dev protobuf-compiler && rm -rf /var/lib/apt/lists/*
COPY services/ingestion/requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt

# 2. Production Stage
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y librdkafka1 protobuf-compiler && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/wheels /wheels
COPY --from=builder /app/requirements.txt .
RUN pip install --no-cache /wheels/*

# Add kira-shared
COPY kira-shared /app/kira-shared
RUN pip install -e /app/kira-shared

COPY services/ingestion/ .
# We move the protoc command to the start command so it works with Mac volumes
CMD protoc --python_out=. MarketDataFeedV3.proto && python main.py