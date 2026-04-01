import redis.asyncio as redis
import json
from typing import Optional, Any

class RedisClient:
    def __init__(self, host: str, port: int, db: int = 0):
        self.client = redis.Redis(host=host, port=port, db=db, decode_responses=True)

    async def set_json(self, key: str, value: Any, ttl: Optional[int] = None):
        await self.client.set(key, json.dumps(value), ex=ttl)

    async def get_json(self, key: str) -> Optional[Any]:
        data = await self.client.get(key)
        return json.loads(data) if data else None

    async def close(self):
        await self.client.close()
