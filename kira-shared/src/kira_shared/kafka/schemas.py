from pydantic import BaseModel
from datetime import datetime
from typing import Any
import uuid

class KafkaEnvelope(BaseModel):
    event_id:   str = str(uuid.uuid4())
    event_type: str
    timestamp:  datetime = datetime.utcnow()
    source:     str
    version:    str = "1.0"
    payload:    dict[str, Any]
    
    def to_bytes(self) -> bytes:
        return self.model_dump_json().encode("utf-8")
    
    @classmethod
    def from_bytes(cls, data: bytes) -> "KafkaEnvelope":
        return cls.model_validate_json(data)
