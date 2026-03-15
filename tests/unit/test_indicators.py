import pytest
import numpy as np
from datetime import datetime
from quant_sdk.indicators import SimpleMovingAverage, ExponentialMovingAverage, RelativeStrengthIndex

def test_sma_logic():
    """Verify Simple Moving Average window and calculation."""
    sma = SimpleMovingAverage("test_sma", 3)
    ts = datetime.now()
    
    # Not ready yet
    assert sma.Update(ts, 10) is False
    assert sma.IsReady is False
    assert sma.Update(ts, 20) is False
    
    # Ready on 3rd sample
    assert sma.Update(ts, 30) is True
    assert sma.IsReady is True
    assert sma.Value == 20.0 # (10+20+30)/3
    
    # Sliding window check
    sma.Update(ts, 40)
    assert sma.Value == 30.0 # (20+30+40)/3

def test_ema_logic():
    """Verify Exponential Moving Average smoothing."""
    period = 9
    ema = ExponentialMovingAverage("test_ema", period)
    ts = datetime.now()
    
    # First value should initialize
    ema.Update(ts, 100)
    assert ema.Value == 100.0
    
    # Second value check logic
    # Alpha = 2 / (9 + 1) = 0.2
    # EMA = (110 * 0.2) + (100 * 0.8) = 22 + 80 = 102
    ema.Update(ts, 110)
    assert abs(ema.Value - 102.0) < 1e-7
    
    # Not ready until 'period' samples
    assert ema.IsReady is False
    for i in range(period - 2):
        ema.Update(ts, 100)
    assert ema.IsReady is True

def test_rsi_calculations():
    """Verify RSI Wilder's smoothing and boundary conditions."""
    rsi = RelativeStrengthIndex("test_rsi", 14)
    ts = datetime.now()
    
    # 1. Test all gains (RSI should approach 100)
    for i in range(20):
        rsi.Update(ts, 100 + i)
    assert rsi.IsReady is True
    assert rsi.Value > 90
    
    # 2. Test all losses (RSI should approach 0)
    rsi_loss = RelativeStrengthIndex("test_rsi_loss", 14)
    for i in range(20):
        rsi_loss.Update(ts, 100 - i)
    assert rsi_loss.Value < 10

def test_rsi_wilder_logic():
    """Detailed check of Wilder's average smoothing."""
    rsi = RelativeStrengthIndex("rsi", 2) # Short period for quick test
    ts = datetime.now()
    
    # Initial price
    rsi.Update(ts, 100) # samples=1
    
    # Period 1: Gain 10
    rsi.Update(ts, 110) # samples=2
    # Period 2: Gain 10
    rsi.Update(ts, 120) # samples=3 (Ready - Simple Average)
    # Gains: 10, 10. AvgGain = 10. Losses: 0. RS = 10/0 = 100. RSI = 100
    assert rsi.IsReady is True
    assert rsi.Value == 100.0
    
    # Period 3: Loss 10 (Price 110)
    rsi.Update(ts, 110) # samples=4 (Wilder's)
    # Wilder's Gain = (PrevAvgGain * (N-1) + CurrentGain) / N
    # NewAvgGain = (10 * 1 + 0) / 2 = 5
    # NewAvgLoss = (0 * 1 + 10) / 2 = 5
    # RS = 5/5 = 1. RSI = 100 - (100 / (1+1)) = 50
    assert rsi.Value == 50.0
