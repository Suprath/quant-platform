import os
import asyncio
import logging
from fastapi import FastAPI
from kira_shared.logging.setup import setup_logging
from kira_shared.redis.client import RedisClient

setup_logging()
app = FastAPI(title="KIRA Position Sizer")

from .producer import SizingProducer
from .consumer import SizingConsumer

setup_logging()
app = FastAPI(title="KIRA Position Sizer")

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")

redis_client = RedisClient(host=REDIS_HOST, port=6379)
sizing_producer = SizingProducer(KAFKA_BOOTSTRAP)
sizing_consumer = SizingConsumer(KAFKA_BOOTSTRAP, sizing_producer)

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.on_event("startup")
async def startup_event():
    await sizing_producer.start()
    await sizing_consumer.start()

@app.on_event("shutdown")
async def shutdown_event():
    await sizing_consumer.stop()
    await sizing_producer.stop()
    await redis_client.close()
