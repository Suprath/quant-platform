"""
Custom indicators module for the Mean Reversion strategy.
This file demonstrates multi-file project support.
"""
import statistics
from collections import deque


class BollingerBands:
    """Simple Bollinger Bands calculator."""

    def __init__(self, period: int = 20, num_std: float = 2.0):
        self.period = period
        self.num_std = num_std
        self.history: deque = deque(maxlen=period)

    def update(self, price: float):
        self.history.append(price)

    @property
    def ready(self) -> bool:
        return len(self.history) >= self.period

    def values(self):
        """Returns (upper, lower, mean)."""
        mean = statistics.mean(self.history)
        std = statistics.stdev(self.history)
        upper = mean + (self.num_std * std)
        lower = mean - (self.num_std * std)
        return upper, lower, mean
