import logging
from kira_shared.kafka.consumer import BaseKafkaConsumer
from kira_shared.kafka.schemas import KafkaEnvelope
from kira_shared.models.sizing import SizingRequest, SizingResult

logger = logging.getLogger("SizingConsumer")

class SizingConsumer(BaseKafkaConsumer):
    def __init__(self, bootstrap_servers: str, producer):
        super().__init__(bootstrap_servers, "position-sizer-group", ["sizing.requests"])
        self.producer = producer

    async def handle_message(self, envelope: KafkaEnvelope):
        request = SizingRequest(**envelope.payload)
        logger.info(f"Received sizing request for {request.symbol}")
        
        # Sizing logic (placeholder)
        result = SizingResult(
            request_id=request.request_id,
            symbol=request.symbol,
            approved=True,
            shares=100,
            position_value=request.entry_price * 100,
            risk_pct_nav=1.0,
            net_ev=0.5
        )
        
        # Produce result back to Kafka
        await self.producer.send_result(result)
