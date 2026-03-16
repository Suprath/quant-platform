# 1. Builder Stage
FROM python:3.11-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y build-essential librdkafka-dev && rm -rf /var/lib/apt/lists/*
COPY services/feature_engine/requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt

# 2. Production Stage
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y librdkafka1 && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/wheels /wheels
COPY services/feature_engine/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Add kira-shared
COPY kira-shared /app/kira-shared
RUN pip install -e /app/kira-shared

COPY services/feature_engine/ .
CMD ["python", "main.py"]