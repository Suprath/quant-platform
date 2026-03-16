from .models import Thesis, MechanismResult
from ..signal_generator.strategies.base_strategy import RawSignal

class ThesisGenerator:
    """
    Generates human-readable thesis from mechanism evidence.
    """
    
    def generate(
        self,
        signal: RawSignal,
        primary_mechanism: MechanismResult,
        supporting: list[MechanismResult]
    ) -> Thesis:
        
        statement = self._build_statement(signal, primary_mechanism, supporting)
        
        invalidation = primary_mechanism.invalidation_triggers.copy()
        
        return Thesis(
            statement=statement,
            invalidation_conditions=invalidation,
            confidence_level=self._get_confidence_level(primary_mechanism.confidence, len(supporting))
        )
    
    def _build_statement(self, signal: RawSignal, primary: MechanismResult, supporting: list) -> str:
        
        if primary.mechanism_type == "ACCUMULATION":
            strength = primary.thesis_components.get("strength", "MODERATE")
            return (
                f"{signal.symbol} showing {strength} institutional accumulation. "
                f"OBV slope is positive ({primary.evidence.get('obv_slope', 0):.4f}) while price is stable. "
                f"Expecting price release when accumulation phase completes."
            )
        
        return f"{signal.symbol} signal: {primary.mechanism_type} mechanism detected."

    def _get_confidence_level(self, confidence: float, supporting_count: int) -> str:
        score = confidence + (supporting_count * 0.1)
        if score > 0.8: return "HIGH"
        if score > 0.6: return "MEDIUM"
        return "LOW"
