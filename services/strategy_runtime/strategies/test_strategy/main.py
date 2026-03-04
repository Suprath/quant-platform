from quant_sdk import QCAlgorithm, Resolution
from datetime import time, timedelta

class NiftyIntradayMeanReversion(QCAlgorithm):
    """
    MEAN REVERSION STRATEGY - Optimized Parameters
    """
    
    def Initialize(self):
        self.SetCash(100000)
        self.SetStartDate(2023, 1, 1)
        self.SetEndDate(2023, 6, 30)
        self.SetLeverage(5.0)
        
        self.symbols = [
            "NSE_EQ|INE002A01018",  # Reliance
            "NSE_EQ|INE467B01029",  # TCS
        ]
        
        for sym in self.symbols:
            self.AddEquity(sym, Resolution.Minute)
        
        # OPTIMIZED PARAMETERS
        self.lookback = 60              # Increased from 20 for smoother mean
        self.entry_zscore = 3.0          # Increased from 1.5 for better quality entries
        self.exit_zscore = -0.5          # Changed from 0.5 - exit past mean (momentum)
        self.atr_period = 40
        self.risk_per_trade = 0.002      # Decreased from 0.005
        self.max_positions = 1
        self.stop_atr_multiple = 1.0    # Tighter stop for better R:R
        
        # Tracking
        self.entry_price = {}
        self.stop_loss = {}
        self.target_price = {}
        self.position_direction = {}
        self.entry_bar_count = {}
        self.daily_trade_count = {}
        self.scaled_out = {}             # Track if we scaled out
        
        # Price history
        self.price_history = {sym: [] for sym in self.symbols}
        self.volume_history = {sym: [] for sym in self.symbols}
        
        # Schedule
        self.Schedule.On(self.DateRules.EveryDay(), 
                        self.TimeRules.At(15, 15), 
                        self.LiquidateAllPositions)
        self.Schedule.On(self.DateRules.EveryDay(), 
                        self.TimeRules.At(9, 15), 
                        self.ResetDaily)
        
        self.Log("Mean Reversion Strategy Initialized - Optimized")

    def ResetDaily(self):
        for sym in self.symbols:
            self.daily_trade_count[sym] = 0
            self.price_history[sym] = []
            self.volume_history[sym] = []
            self.scaled_out[sym] = False
        self.Log("Daily reset")

    def LiquidateAllPositions(self):
        for sym in self.symbols:
            if self.IsInvested(sym):
                self.Liquidate(sym)
                self.position_direction[sym] = 0
        self.Log("EOD Liquidation")

    def IsInvested(self, symbol):
        try:
            return self.Portfolio[symbol].Invested
        except:
            return self.GetQuantity(symbol) != 0

    def GetQuantity(self, symbol):
        try:
            return self.Portfolio[symbol].Quantity
        except:
            return 0

    def GetHoldingsValue(self, symbol):
        try:
            qty = self.GetQuantity(symbol)
            price = self.Portfolio[symbol].Price
            return abs(qty * price)
        except:
            return 0

    def GetTotalExposure(self):
        return sum(self.GetHoldingsValue(s) for s in self.symbols)

    def GetBarFromTick(self, sym, tick_data):
        price = getattr(tick_data, 'Price', getattr(tick_data, 'LastPrice', getattr(tick_data, 'value', None)))
        volume = getattr(tick_data, 'Size', getattr(tick_data, 'Quantity', getattr(tick_data, 'Volume', 0)))
        
        if price is None:
            raise AttributeError("No price in tick")
        
        class SimpleBar:
            def __init__(self, p, v):
                self.Open = p
                self.High = p
                self.Low = p
                self.Close = p
                self.Volume = v
        return SimpleBar(price, volume)

    def GetTime(self, data):
        try:
            t = data.Time
            if isinstance(t, str):
                from datetime import datetime
                dt = datetime.fromisoformat(t.replace('Z', '+00:00'))
                return dt.time()
            return t.time() if hasattr(t, 'time') else t
        except:
            return None

    def CalculateStats(self, prices):
        """Calculate mean, std dev, z-score"""
        if len(prices) < self.lookback:
            return None, None, None
        
        recent = prices[-self.lookback:]
        mean = sum(recent) / len(recent)
        
        variance = sum((p - mean) ** 2 for p in recent) / len(recent)
        std = variance ** 0.5
        
        current = prices[-1]
        zscore = (current - mean) / std if std > 0 else 0
        
        return mean, std, zscore

    def CalculateATR(self, sym):
        history = self.price_history[sym]
        if len(history) < 2:
            return None
        
        tr_values = []
        for i in range(1, min(len(history), self.atr_period + 1)):
            curr = history[-i]
            prev = history[-i-1]
            tr = max(curr['high'] - curr['low'],
                     abs(curr['high'] - prev['close']),
                     abs(curr['low'] - prev['close']))
            tr_values.append(tr)
        
        if len(tr_values) >= self.atr_period:
            return sum(tr_values[:self.atr_period]) / self.atr_period
        return None

    def OnData(self, data):
        current_time = self.GetTime(data)
        if current_time is None:
            return
        
        # Skip first hour
        if current_time < time(9, 30):
            return
        
        # No new entries after 2:30 PM
        if current_time > time(14, 30):
            for sym in self.symbols:
                if self.position_direction.get(sym, 0) != 0:
                    self.ManageExit(sym, data, current_time)
            return
        
        # Force exit at 3:10 PM
        if current_time >= time(15, 10):
            for sym in self.symbols:
                if self.IsInvested(sym):
                    self.Liquidate(sym)
                    self.position_direction[sym] = 0
            return
        
        for sym in self.symbols:
            if not data.ContainsKey(sym):
                continue
            
            try:
                tick_data = data[sym]
                if hasattr(tick_data, 'Open'):
                    bar = tick_data
                else:
                    bar = self.GetBarFromTick(sym, tick_data)
            except Exception as e:
                continue
            
            # Update history
            self.price_history[sym].append({
                'high': bar.High,
                'low': bar.Low,
                'close': bar.Close
            })
            self.volume_history[sym].append(bar.Volume)
            
            max_hist = max(self.lookback, self.atr_period) + 10
            if len(self.price_history[sym]) > max_hist:
                self.price_history[sym].pop(0)
                self.volume_history[sym].pop(0)
            
            if len(self.price_history[sym]) < self.lookback:
                continue
            
            # Calculate stats
            closes = [p['close'] for p in self.price_history[sym]]
            mean, std, zscore = self.CalculateStats(closes)
            atr = self.CalculateATR(sym)
            
            if mean is None or atr is None or atr == 0:
                continue
            
            # Manage existing position
            if self.position_direction.get(sym, 0) != 0:
                self.ManageExit(sym, bar, mean, std, zscore, atr)
                continue
            
            # Check entry
            if self.daily_trade_count.get(sym, 0) >= 2:
                continue
            
            self.CheckEntry(sym, bar, mean, std, zscore, atr)

    def CheckEntry(self, sym, bar, mean, std, zscore, atr):
        """PURE mean reversion entries - no trend filter"""
        portfolio_value = self.Portfolio.TotalPortfolioValue
        total_exposure = self.GetTotalExposure()
        
        if total_exposure / portfolio_value > 0.5:
            return
        
        # LONG: Price stretched below mean (>2 std dev)
        if zscore < -self.entry_zscore:
            self.EnterLong(sym, bar, mean, std, atr)
        
        # SHORT: Price stretched above mean (>2 std dev)
        elif zscore > self.entry_zscore:
            self.EnterShort(sym, bar, mean, std, atr)

    def EnterLong(self, sym, bar, mean, std, atr):
        """Enter long position"""
        portfolio_value = self.Portfolio.TotalPortfolioValue
        risk_amount = portfolio_value * self.risk_per_trade
        
        # Tighter stop: 1.5 ATR or recent low
        recent_lows = [p['low'] for p in self.price_history[sym][-5:]]
        stop_price = min(min(recent_lows), bar.Close - (self.stop_atr_multiple * atr))
        stop_distance = bar.Close - stop_price
        
        if stop_distance <= 0:
            return
        
        position_value = (risk_amount / stop_distance) * bar.Close
        max_position = portfolio_value * 0.25
        position_value = min(position_value, max_position)
        target_pct = position_value / portfolio_value
        
        if target_pct < 0.05:
            return
        
        self.SetHoldings(sym, target_pct)
        self.entry_price[sym] = bar.Close
        self.stop_loss[sym] = stop_price
        # Target is past mean (momentum continuation)
        self.target_price[sym] = mean - (self.exit_zscore * std)
        self.position_direction[sym] = 1
        self.entry_bar_count[sym] = 0
        self.scaled_out[sym] = False
        self.daily_trade_count[sym] = self.daily_trade_count.get(sym, 0) + 1
        
        self.Log(f"LONG {sym} @ {bar.Close:.2f}, Target={self.target_price[sym]:.2f}, SL={stop_price:.2f}")

    def EnterShort(self, sym, bar, mean, std, atr):
        """Enter short position"""
        portfolio_value = self.Portfolio.TotalPortfolioValue
        risk_amount = portfolio_value * self.risk_per_trade
        
        recent_highs = [p['high'] for p in self.price_history[sym][-5:]]
        stop_price = max(max(recent_highs), bar.Close + (self.stop_atr_multiple * atr))
        stop_distance = stop_price - bar.Close
        
        if stop_distance <= 0:
            return
        
        position_value = (risk_amount / stop_distance) * bar.Close
        max_position = portfolio_value * 0.25
        position_value = min(position_value, max_position)
        target_pct = -position_value / portfolio_value
        
        if abs(target_pct) < 0.05:
            return
        
        self.SetHoldings(sym, target_pct)
        self.entry_price[sym] = bar.Close
        self.stop_loss[sym] = stop_price
        # Target is past mean (momentum continuation)
        self.target_price[sym] = mean + (abs(self.exit_zscore) * std)
        self.position_direction[sym] = -1
        self.entry_bar_count[sym] = 0
        self.scaled_out[sym] = False
        self.daily_trade_count[sym] = self.daily_trade_count.get(sym, 0) + 1
        
        self.Log(f"SHORT {sym} @ {bar.Close:.2f}, Target={self.target_price[sym]:.2f}, SL={stop_price:.2f}")

    def ManageExit(self, sym, bar, mean, std, zscore, atr):
        """Exit with momentum continuation and trailing stop"""
        direction = self.position_direction[sym]
        entry = self.entry_price[sym]
        stop = self.stop_loss[sym]
        target = self.target_price[sym]
        price = bar.Close
        
        # Update trailing stop if in profit
        if direction == 1:  # Long
            # Move stop to breakeven + 0.5 ATR when up 1 ATR
            if price > entry + atr and stop < entry:
                new_stop = entry + (0.5 * atr)
                if new_stop > stop:
                    self.stop_loss[sym] = new_stop
                    self.Log(f"TRAIL LONG {sym} stop to {new_stop:.2f}")
            
            # Exit conditions
            hit_target = price <= target      # Below mean (momentum)
            hit_stop = price <= stop
            time_exit = self.entry_bar_count.get(sym, 0) > 50  # Max 50 bars
            
            if hit_target or hit_stop or time_exit:
                self.Liquidate(sym)
                pnl = (price / entry - 1) * 100
                reason = 'Target' if hit_target else 'Stop' if hit_stop else 'Time'
                self.Log(f"EXIT LONG {sym} @ {price:.2f}, PnL={pnl:.2f}%, {reason}")
                self.position_direction[sym] = 0
                self.scaled_out[sym] = False
            else:
                self.entry_bar_count[sym] = self.entry_bar_count.get(sym, 0) + 1
        
        else:  # Short
            # Move stop to breakeven - 0.5 ATR when down 1 ATR
            if price < entry - atr and stop > entry:
                new_stop = entry - (0.5 * atr)
                if new_stop < stop:
                    self.stop_loss[sym] = new_stop
                    self.Log(f"TRAIL SHORT {sym} stop to {new_stop:.2f}")
            
            hit_target = price >= target      # Above mean (momentum)
            hit_stop = price >= stop
            time_exit = self.entry_bar_count.get(sym, 0) > 50
            
            if hit_target or hit_stop or time_exit:
                self.Liquidate(sym)
                pnl = (entry / price - 1) * 100
                reason = 'Target' if hit_target else 'Stop' if hit_stop else 'Time'
                self.Log(f"EXIT SHORT {sym} @ {price:.2f}, PnL={pnl:.2f}%, {reason}")
                self.position_direction[sym] = 0
                self.scaled_out[sym] = False
            else:
                self.entry_bar_count[sym] = self.entry_bar_count.get(sym, 0) + 1