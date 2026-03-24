import logging
import asyncio
from kira_shared.kafka.consumer import BaseKafkaConsumer
from kira_shared.kafka.schemas import KafkaEnvelope
from kira_shared.redis.client import RedisClient

logger = logging.getLogger("MarketConsumer")

class MarketConsumer(BaseKafkaConsumer):
    def __init__(self, bootstrap_servers: str, redis_client: RedisClient):
        super().__init__(bootstrap_servers, "noise-filter-group", ["market.equity.ticks"])
        self.redis = redis_client

    async def handle_message(self, envelope: KafkaEnvelope):
        # Implementation of noise filtering logic
        # Replace dummy with simple volatility/spread heuristic
        symbol = envelope.payload.get("symbol")
        ltp = float(envelope.payload.get("ltp", 0))
        
        if symbol and ltp > 0:
            # We'll use a sliding window from Redis to compute confidence
            history_key = f"nf:stock:history:{symbol}"
            # Push price, keep last 20
            await self.redis.client.lpush(history_key, ltp)
            await self.redis.client.ltrim(history_key, 0, 19)
            
            history = await self.redis.client.lrange(history_key, 0, -1)
            if len(history) >= 10:
                prices = [float(p) for p in history]
                avg = sum(prices) / len(prices)
                # Volatility (StdDev approx)
                variance = sum((p - avg) ** 2 for p in prices) / len(prices)
                stddev = variance ** 0.5
                cv = (stddev / avg) * 100 if avg > 0 else 1
                
                # Confidence: High CV = High Noise = Low Confidence
                # We want CV < 0.05% for high confidence in 1m ticks
                confidence = max(0, min(100, int(100 - (cv * 1000))))
            else:
                confidence = 50 # Not enough data
                
            await self.redis.set_json(f"nf:stock:confidence:{symbol}", confidence, ttl=900)
            if confidence < 40:
                logger.info(f"⚠️ High noise detected for {symbol}: Confidence {confidence}")
