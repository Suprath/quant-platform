import logging
import json
from aiokafka import AIOKafkaProducer
from kira_shared.kafka.schemas import KafkaEnvelope
from kira_shared.models.sizing import SizingResult

logger = logging.getLogger("SizingProducer")

class SizingProducer:
    def __init__(self, bootstrap_servers: str):
        self.bootstrap_servers = bootstrap_servers
        self.producer = None

    async def start(self):
        self.producer = AIOKafkaProducer(bootstrap_servers=self.bootstrap_servers)
        await self.producer.start()
        logger.info("Sizing producer started.")

    async def stop(self):
        if self.producer:
            await self.producer.stop()
        logger.info("Sizing producer stopped.")

    async def send_result(self, result: SizingResult):
        envelope = KafkaEnvelope(
            event_type="sizing.result",
            source="position_sizer",
            payload=result.model_dump()
        )
        await self.producer.send_and_wait("sizing.results", envelope.to_bytes())
        logger.info(f"Sent sizing result for {result.symbol}")
