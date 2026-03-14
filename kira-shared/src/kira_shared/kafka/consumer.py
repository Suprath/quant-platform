import asyncio
import logging
from aiokafka import AIOKafkaConsumer
from ..kafka.schemas import KafkaEnvelope

logger = logging.getLogger("KafkaConsumer")

class BaseKafkaConsumer:
    def __init__(self, bootstrap_servers: str, group_id: str, topics: list[str]):
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.topics = topics
        self.consumer = None
        self._running = False

    async def start(self):
        self.consumer = AIOKafkaConsumer(
            *self.topics,
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.group_id,
            auto_offset_reset='earliest'
        )
        await self.consumer.start()
        self._running = True
        logger.info(f"Kafka consumer started on topics: {self.topics}")
        asyncio.create_task(self.consume_loop())

    async def stop(self):
        self._running = False
        if self.consumer:
            await self.consumer.stop()
        logger.info("Kafka consumer stopped.")

    async def consume_loop(self):
        try:
            async for msg in self.consumer:
                if not self._running:
                    break
                envelope = KafkaEnvelope.from_bytes(msg.value)
                await self.handle_message(envelope)
        except Exception as e:
            logger.error(f"Error in consume loop: {e}")

    async def handle_message(self, envelope: KafkaEnvelope):
        raise NotImplementedError("Subclasses must implement handle_message")
