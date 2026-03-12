from collections import deque
import numpy as np

class IndicatorBase:
    """Base class for all indicators."""
    def __init__(self, name):
        self.Name = name
        self.Value = 0.0
        self.IsReady = False
        self.Samples = 0
        self.Current = self # QC API style: indicator.Current.Value

    def Update(self, timestamp, value):
        """Update the indicator with a new input value."""
        self.Samples += 1
        # Implementation in subclasses
        pass

class SimpleMovingAverage(IndicatorBase):
    """
    Simple Moving Average (SMA) indicator.
    """
    def __init__(self, name, period):
        super().__init__(name)
        self.Period = period
        self.Window = deque(maxlen=period)

    def Update(self, timestamp, value):
        super().Update(timestamp, value)
        self.Window.append(value)
        
        if len(self.Window) == self.Period:
            self.Value = sum(self.Window) / self.Period
            self.IsReady = True
        else:
            self.IsReady = False
            self.Value = 0.0
        return self.IsReady

class ExponentialMovingAverage(IndicatorBase):
    """
    Exponential Moving Average (EMA) indicator.
    """
    def __init__(self, name, period, smoothing=2):
        super().__init__(name)
        self.Period = period
        self.Alpha = smoothing / (period + 1)
        self._last_value = None

    def Update(self, timestamp, value):
        super().Update(timestamp, value)
        
        if self._last_value is None:
            self._last_value = value # Initialize with first value
            self.Value = value
        else:
             # EMA = Price(t) * k + EMA(y) * (1 – k)
            self.Value = (value * self.Alpha) + (self._last_value * (1 - self.Alpha))
            self._last_value = self.Value
            
        if self.Samples >= self.Period:
            self.IsReady = True
        
        return self.IsReady

class RelativeStrengthIndex(IndicatorBase):
    """
    Relative Strength Index (RSI) indicator.
    Calculates RSI using the standard Wilder's Smoothing method.
    """
    def __init__(self, name, period):
        super().__init__(name)
        self.Period = period
        self._prev_price = None
        self._avg_gain = 0.0
        self._avg_loss = 0.0

    def Update(self, timestamp, value):
        super().Update(timestamp, value)
        
        if self._prev_price is None:
            self._prev_price = value
            return False

        change = value - self._prev_price
        gain = max(0, change)
        loss = max(0, -change)

        if self.Samples <= self.Period + 1:
            # First Average calculation (Simple Average)
            self._avg_gain += gain / self.Period
            self._avg_loss += loss / self.Period
            
            if self.Samples == self.Period + 1:
                rs = (self._avg_gain / self._avg_loss) if self._avg_loss != 0 else 100.0
                self.Value = 100.0 - (100.0 / (1.0 + rs))
                self.IsReady = True
        else:
            # Wilder's Smoothing
            self._avg_gain = ((self._avg_gain * (self.Period - 1)) + gain) / self.Period
            self._avg_loss = ((self._avg_loss * (self.Period - 1)) + loss) / self.Period
            
            rs = (self._avg_gain / self._avg_loss) if self._avg_loss != 0 else 100.0
            self.Value = 100.0 - (100.0 / (1.0 + rs))
            self.IsReady = True

        self._prev_price = value
        return self.IsReady
