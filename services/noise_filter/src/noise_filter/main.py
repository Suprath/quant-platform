import os
import asyncio
from fastapi import FastAPI
from kira_shared.logging.setup import setup_logging
from kira_shared.kafka.consumer import BaseKafkaConsumer
from kira_shared.models.market import PriceBar, FeatureVector

from kira_shared.redis.client import RedisClient
from .consumer import MarketConsumer

setup_logging()
app = FastAPI(title="KIRA Noise Filter")

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")

redis_client = RedisClient(host=REDIS_HOST, port=6379)
market_consumer = MarketConsumer(KAFKA_BOOTSTRAP, redis_client)

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/confidence/{symbol}")
async def get_confidence(symbol: str):
    confidence = await redis_client.get_json(f"nf:stock:confidence:{symbol}")
    return {"symbol": symbol, "confidence": confidence or 0}

@app.post("/generate")
async def trigger_generation(symbol: str, start_date: str, end_date: str, version: int = 1):
    """Trigger background generation of noise signals for a range."""
    from .batch import process_historical_range
    # Run in background to not block the request
    asyncio.create_task(process_historical_range(symbol, start_date, end_date, version))
    return {"status": "triggered", "symbol": symbol, "range": [start_date, end_date]}

@app.on_event("startup")
async def startup_event():
    await market_consumer.start()

@app.on_event("shutdown")
async def shutdown_event():
    await market_consumer.stop()
    await redis_client.close()
