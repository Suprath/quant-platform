"""
Circuit Breakers — Safety Mechanisms for the ESTI Population

Provides hard limits to prevent catastrophic losses during training.
"""

from config import (
    setup_logger,
    MAX_DRAWDOWN,
    MAX_POSITION_SIZE,
    MIN_POPULATION,
    MAX_CORRELATION,
    SHARPE_FLOOR,
)

logger = setup_logger("esti.risk.circuit_breakers")


class CircuitBreakers:
    """
    Safety mechanisms that halt or modify ESTI training when risk thresholds
    are breached.
    """

    def __init__(
        self,
        max_drawdown: float = MAX_DRAWDOWN,
        max_position: float = MAX_POSITION_SIZE,
        min_population: int = MIN_POPULATION,
        max_correlation: float = MAX_CORRELATION,
        sharpe_floor: float = SHARPE_FLOOR,
    ):
        self.max_drawdown = max_drawdown
        self.max_position = max_position
        self.min_population = min_population
        self.max_correlation = max_correlation
        self.sharpe_floor = sharpe_floor

        self._tripped = {}
        self._trip_count = 0

        logger.info(
            f"🛑 CircuitBreakers initialised | "
            f"max_dd={max_drawdown:.0%} | max_pos={max_position:.0%} "
            f"| min_pop={min_population} | sharpe_floor={sharpe_floor}"
        )

    def check_drawdown(self, capital: float, peak_capital: float) -> bool:
        """Check if agent drawdown exceeds limit."""
        if peak_capital <= 0:
            return False
        drawdown = (peak_capital - capital) / peak_capital
        if drawdown >= self.max_drawdown:
            self._trip("drawdown", f"drawdown={drawdown:.2%} >= {self.max_drawdown:.0%}")
            return True
        return False

    def check_position_size(self, position_fraction: float) -> float:
        """Clamp position size to maximum allowed."""
        if position_fraction > self.max_position:
            logger.debug(
                f"🛑 Position clamped: {position_fraction:.2%} → {self.max_position:.0%}"
            )
            return self.max_position
        return position_fraction

    def check_population(self, alive_count: int) -> bool:
        """Check if population has fallen below minimum."""
        if alive_count < self.min_population:
            self._trip("population", f"alive={alive_count} < min={self.min_population}")
            return True
        return False

    def check_sharpe(self, avg_sharpe: float) -> bool:
        """Check if average Sharpe ratio is below floor."""
        if avg_sharpe < self.sharpe_floor:
            self._trip("sharpe", f"avg_sharpe={avg_sharpe:.4f} < floor={self.sharpe_floor}")
            return True
        return False

    def _trip(self, breaker_name: str, detail: str):
        """Record a circuit breaker trip."""
        self._trip_count += 1
        self._tripped[breaker_name] = detail
        logger.warning(f"🚨 CIRCUIT BREAKER TRIPPED: [{breaker_name}] {detail}")

    def get_status(self) -> dict:
        return {
            "total_trips": self._trip_count,
            "active_trips": dict(self._tripped),
            "thresholds": {
                "max_drawdown": self.max_drawdown,
                "max_position_size": self.max_position,
                "min_population": self.min_population,
                "sharpe_floor": self.sharpe_floor,
            },
        }

    def reset_trips(self):
        """Reset tripped breakers (after recovery action taken)."""
        self._tripped.clear()
        logger.info("🛑 Circuit breaker trips cleared")
