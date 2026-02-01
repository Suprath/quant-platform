FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    librdkafka-dev \
    protobuf-compiler \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# We move the protoc command to the start command so it works with Mac volumes
CMD protoc --python_out=. MarketDataFeedV3.proto && python main.py