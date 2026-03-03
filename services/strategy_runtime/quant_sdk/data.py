from datetime import datetime
from typing import Dict, Any

class TradeBar:
    """
    Represents a single candle/bar of data.
    """
    def __init__(self, time, symbol, open_, high, low, close, volume):
        self.Time = time
        self.Symbol = symbol
        self.Open = float(open_)
        self.High = float(high)
        self.Low = float(low)
        self.Close = float(close)
        self.Volume = float(volume)
        # For generic access
        self.Value = self.Close 

    def __repr__(self):
        return f"{self.Symbol}: {self.Close} @ {self.Time}"

class Tick:
    """
    Represents a single tick of data.
    Uses __slots__ for ~30% faster attribute access.
    """
    __slots__ = ('Time', 'Symbol', 'Price', 'Volume', 'Value')

    def __init__(self, time, symbol, price, volume):
        self.Time = time
        self.Symbol = symbol
        self.Price = float(price)
        self.Volume = float(volume)
        self.Value = self.Price

    @property
    def Close(self):
        return self.Price

    @property
    def High(self):
        return self.Price

    @property
    def Low(self):
        return self.Price

    def __repr__(self):
        return f"{self.Symbol}: {self.Price} @ {self.Time}"

class Slice:
    """
    Represents a time-slice of data, containing bars/ticks for all subscribed symbols.
    """
    def __init__(self, time, data: Dict[str, Any]):
        self.Time = time
        self._data = data # Dictionary of Symbol -> TradeBar/Tick

    def __getitem__(self, symbol):
        return self._data.get(symbol)

    def __contains__(self, symbol):
        return symbol in self._data

    def ContainsKey(self, symbol):
        return symbol in self._data

    @property
    def Keys(self):
        return self._data.keys()

    @property
    def Values(self):
        return self._data.values()
    
    def get(self, symbol):
        return self._data.get(symbol)


class FastSlice:
    """
    Zero-allocation Slice for single-symbol backtest ticks.
    Instead of creating a new dict per tick, reuses two slot attributes.
    """
    __slots__ = ('Time', '_data_symbol', '_data_tick')

    def __init__(self):
        self.Time = None
        self._data_symbol = None
        self._data_tick = None

    def __getitem__(self, symbol):
        return self._data_tick if symbol == self._data_symbol else None

    def __contains__(self, symbol):
        return symbol == self._data_symbol

    def ContainsKey(self, symbol):
        return symbol == self._data_symbol

    @property
    def Keys(self):
        return (self._data_symbol,) if self._data_symbol else ()

    @property
    def Values(self):
        return (self._data_tick,) if self._data_tick else ()

    def get(self, symbol):
        return self._data_tick if symbol == self._data_symbol else None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HIGH-PERFORMANCE INDICATORS (O(1) per tick)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class BollingerBands:
    """
    O(1) Bollinger Bands using running sum and sum-of-squares.
    Replaces statistics.mean()/stdev() which are O(n) per call.

    For a 300-period window, this saves ~600 iterations per tick.
    Over 1.7M ticks, that's ~1 billion fewer Python loop iterations.
    """
    __slots__ = ('period', 'num_std', '_buf', '_idx', '_count',
                 '_sum', '_sum_sq', '_full')

    def __init__(self, period: int = 20, num_std: float = 2.0):
        self.period = period
        self.num_std = num_std
        self._buf = [0.0] * period  # Circular buffer
        self._idx = 0
        self._count = 0
        self._sum = 0.0
        self._sum_sq = 0.0
        self._full = False

    def update(self, price: float):
        if self._full:
            # Remove oldest value from running sums
            old = self._buf[self._idx]
            self._sum -= old
            self._sum_sq -= old * old

        self._buf[self._idx] = price
        self._sum += price
        self._sum_sq += price * price

        self._idx = (self._idx + 1) % self.period
        if not self._full:
            self._count += 1
            if self._count >= self.period:
                self._full = True

    @property
    def ready(self) -> bool:
        return self._full

    def values(self):
        """Returns (upper, lower, mean) in O(1)."""
        n = self.period
        mean = self._sum / n
        # Variance = E[X²] - (E[X])²
        variance = (self._sum_sq / n) - (mean * mean)
        # Guard against floating-point negative variance
        std = variance ** 0.5 if variance > 0 else 0.0
        upper = mean + (self.num_std * std)
        lower = mean - (self.num_std * std)
        return upper, lower, mean
