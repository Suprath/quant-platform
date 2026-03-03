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
    """
    def __init__(self, time, symbol, price, volume):
        self.Time = time
        self.Symbol = symbol
        self.Price = float(price)
        self.Volume = float(volume)
        self.Value = self.Price

    @property
    def Close(self):
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
