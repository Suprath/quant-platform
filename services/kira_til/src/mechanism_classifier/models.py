from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from ..signal_generator.strategies.base_strategy import RawSignal

@dataclass
class MechanismResult:
    is_present: bool
    mechanism_type: str
    confidence: float
    evidence: Dict[str, Any] = field(default_factory=dict)
    thesis_components: Dict[str, Any] = field(default_factory=dict)
    invalidation_triggers: List[str] = field(default_factory=list)
    expected_days: tuple = (0, 0)

@dataclass
class Thesis:
    statement: str
    invalidation_conditions: List[str]
    confidence_level: str

@dataclass
class ClassifiedSignal:
    signal_id: str
    symbol: str
    signal_type: str
    direction: str
    has_mechanism: bool
    primary_mechanism: Optional[str] = None
    mechanism_confidence: float = 0.0
    pattern_score: float = 0.0
    thesis: Optional[str] = None
    invalidation_conditions: List[str] = field(default_factory=list)
    expected_days_min: int = 0
    expected_days_max: int = 0
    supporting_mechanisms: List[str] = field(default_factory=list)
    action: str = "DISCARD"
    computation_ms: float = 0.0
