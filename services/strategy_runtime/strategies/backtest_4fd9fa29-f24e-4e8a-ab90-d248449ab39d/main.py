from quant_sdk import QCAlgorithm, Resolution
import datetime

class RobustInstitutionalStrategy(QCAlgorithm):
    """
    Robust Multi-Factor Strategy - Fixed & Simplified
    """
    
    def Initialize(self):
        self.SetCash(100000)
        self.SetStartDate(2023, 1, 1)
        self.SetEndDate(2024, 12, 31)
        
        self.leverage = 3.0
        self.SetLeverage(self.leverage)
        
        # Risk limits
        self.max_daily_loss = 0.03
        self.max_position = 0.40
        
        # Universe
        self.symbols = [
            "NSE_EQ|INE002A01018",  # Reliance
            "NSE_EQ|INE040A01034",  # HDFC Bank
            "NSE_EQ|INE009A01021",  # Infosys
            "NSE_EQ|INE238A01034",  # ICICI Bank
        ]
        
        self.allocations = {
            "NSE_EQ|INE002A01018": 0.30,
            "NSE_EQ|INE040A01034": 0.30,
            "NSE_EQ|INE009A01021": 0.20,
            "NSE_EQ|INE238A01034": 0.20,
        }
        
        # State
        self.state = {}
        for symbol in self.symbols:
            self.AddEquity(symbol, Resolution.Tick)
            self.state[symbol] = {
                'in_position': False,
                'direction': 0,
                'entry': 0,
                'stop': 0,
                'target': 0,
                'quantity': 0,
                'trades_today': 0,
                'vwap': 0,
                'vwap_pv': 0,
                'vwap_vol': 0,
                'ema_fast': 0,
                'ema_slow': 0,
                'prices': [],
                'atr': 0,
                'day_high': 0,
                'day_low': float('inf'),
            }
        
        self.bars = {}
        self.last_date = None
        self.daily_pnl = 0
        self.total_trades = 0
        
        self.Log("🚀 ROBUST INSTITUTIONAL STRATEGY")
        self.Log(f"💰 Capital: ₹{self.Portfolio.Cash:,.0f}")
        
    def OnData(self, data):
        current_time = data.Time if hasattr(data, 'Time') else datetime.datetime.now()
        time_only = current_time.time() if isinstance(current_time, datetime.datetime) else current_time
        current_date = current_time.date() if isinstance(current_time, datetime.datetime) else datetime.date.today()
        
        nav = self.Portfolio.TotalPortfolioValue
        
        # Daily reset
        if self.last_date != current_date:
            self.last_date = current_date
            self.daily_pnl = 0
            
            for symbol in self.symbols:
                s = self.state[symbol]
                s['in_position'] = False
                s['trades_today'] = 0
                s['vwap'] = 0
                s['vwap_pv'] = 0
                s['vwap_vol'] = 0
                s['ema_fast'] = 0
                s['ema_slow'] = 0
                s['prices'] = []
                s['atr'] = 0
                s['day_high'] = 0
                s['day_low'] = float('inf')
            
            self.bars = {}
            self.Log(f"📅 NEW DAY: {current_date}")
        
        # Market close
        if time_only >= datetime.time(15, 25):
            for symbol in self.symbols:
                if self.state[symbol]['in_position']:
                    self.Liquidate(symbol)
                    self.state[symbol]['in_position'] = False
            return
        
        # Process each symbol
        for symbol in self.symbols:
            if not data.ContainsKey(symbol):
                continue
            
            tick = data[symbol]
            price = tick.Price
            qty = getattr(tick, 'Quantity', 1)
            
            s = self.state[symbol]
            
            # Update VWAP
            s['vwap_pv'] += price * qty
            s['vwap_vol'] += qty
            if s['vwap_vol'] > 0:
                s['vwap'] = s['vwap_pv'] / s['vwap_vol']
            
            # Update day high/low
            s['day_high'] = max(s['day_high'], price)
            s['day_low'] = min(s['day_low'], price)
            
            # Update price history (keep last 50)
            s['prices'].append(price)
            if len(s['prices']) > 50:
                s['prices'].pop(0)
            
            # Calculate EMAs when we have enough data
            if len(s['prices']) >= 20:
                if s['ema_fast'] == 0:
                    # Initialize
                    s['ema_fast'] = sum(s['prices'][-10:]) / 10
                    s['ema_slow'] = sum(s['prices'][-20:]) / 20
                else:
                    # Update
                    alpha_fast = 2.0 / (10 + 1)
                    alpha_slow = 2.0 / (20 + 1)
                    s['ema_fast'] = (price - s['ema_fast']) * alpha_fast + s['ema_fast']
                    s['ema_slow'] = (price - s['ema_slow']) * alpha_slow + s['ema_slow']
            
            # Calculate ATR using day range (simpler & robust)
            if s['day_high'] > s['day_low']:
                s['atr'] = s['day_high'] - s['day_low']
            
            # Build 5-min bars
            if isinstance(current_time, datetime.datetime):
                bar_minute = (current_time.minute // 5) * 5
                bar_time = current_time.replace(minute=bar_minute, second=0, microsecond=0)
            else:
                bar_time = current_time
            
            if symbol not in self.bars or self.bars[symbol].get('time') != bar_time:
                # Process completed bar
                if symbol in self.bars and not s['in_position']:
                    self._check_entry(symbol, self.bars[symbol], time_only, nav)
                
                # New bar
                self.bars[symbol] = {
                    'open': price, 'high': price, 'low': price,
                    'close': price, 'volume': qty, 'time': bar_time
                }
            else:
                bar = self.bars[symbol]
                bar['high'] = max(bar['high'], price)
                bar['low'] = min(bar['low'], price)
                bar['close'] = price
                bar['volume'] += qty
            
            # Manage position
            if s['in_position']:
                self._manage_position(symbol, price, time_only, nav)

    def _check_entry(self, symbol, bar, time_only, nav):
        """Entry logic - simplified but effective"""
        s = self.state[symbol]
        
        # Skip if max trades (3 per symbol)
        if s['trades_today'] >= 3:
            return
        
        # Skip early or late
        if time_only < datetime.time(9, 25) or time_only > datetime.time(14, 45):
            return
        
        # Need indicators
        if s['ema_fast'] == 0 or s['vwap'] == 0:
            return
        
        close = bar['close']
        
        # Calculate signals
        trend_up = s['ema_fast'] > s['ema_slow']
        trend_down = s['ema_fast'] < s['ema_slow']
        
        above_vwap = close > s['vwap'] * 1.002
        below_vwap = close < s['vwap'] * 0.998
        
        # LONG: Trend up + above VWAP
        if trend_up and above_vwap and not s['in_position']:
            self._enter(symbol, close, 1, "TREND_VWAP", nav)
        
        # SHORT: Trend down + below VWAP
        elif trend_down and below_vwap and not s['in_position']:
            self._enter(symbol, close, -1, "TREND_VWAP", nav)

    def _enter(self, symbol, price, direction, signal, nav):
        """Enter position"""
        s = self.state[symbol]
        
        # Position sizing: allocation-based with risk cap
        alloc = self.allocations[symbol]
        target_notional = nav * alloc * self.leverage * 0.7
        
        # Risk-based cap: 2% risk max
        stop_dist = max(s['atr'] * 0.5, price * 0.005)  # 0.5% or 0.5 ATR
        risk_qty = int((nav * 0.02) / stop_dist)
        
        alloc_qty = int(target_notional / price)
        
        # Take smaller of two (risk control)
        quantity = min(alloc_qty, risk_qty, 400)
        
        if quantity < 10:
            return
        
        s['in_position'] = True
        s['direction'] = direction
        s['entry'] = price
        s['stop'] = price - (stop_dist * direction)
        s['target'] = price + (stop_dist * 2 * direction)  # 1:2 R:R
        s['quantity'] = quantity
        s['trades_today'] += 1
        self.total_trades += 1
        
        notional = quantity * price
        
        side = "🟢 LONG" if direction == 1 else "🔴 SHORT"
        self.Log(f"{side} #{self.total_trades} | {symbol[-12:]} | {signal}")
        self.Log(f"   Qty: {quantity} | ₹{notional:,.0f} | Stop: ₹{s['stop']:.2f}")
        
        weight = notional / nav
        self.SetHoldings(symbol, weight if direction == 1 else -weight)

    def _manage_position(self, symbol, price, time_only, nav):
        """Manage open position"""
        s = self.state[symbol]
        
        unrealized = (price - s['entry']) * s['direction'] * s['quantity']
        unrealized_pct = (price - s['entry']) / s['entry'] * 100 * s['direction']
        
        exit_reason = None
        
        # Stop loss
        if s['direction'] == 1 and price <= s['stop']:
            exit_reason = "STOP"
        elif s['direction'] == -1 and price >= s['stop']:
            exit_reason = "STOP"
        
        # Target
        if s['direction'] == 1 and price >= s['target']:
            exit_reason = "TARGET"
        elif s['direction'] == -1 and price <= s['target']:
            exit_reason = "TARGET"
        
        # Trailing stop (breakeven at 1R profit)
        risk = abs(s['entry'] - s['stop'])
        profit = (price - s['entry']) * s['direction']
        
        if profit > risk:  # In 1R+ profit
            if s['direction'] == 1:
                s['stop'] = max(s['stop'], s['entry'] * 1.001)
            else:
                s['stop'] = min(s['stop'], s['entry'] * 0.999)
        
        # Time exit
        if time_only >= datetime.time(14, 50):
            exit_reason = "EOD"
        
        if exit_reason:
            self.daily_pnl += unrealized
            
            self.Liquidate(symbol)
            s['in_position'] = False
            
            emoji = "✅" if unrealized > 0 else "❌"
            self.Log(f"{emoji} EXIT | {symbol[-12:]} | {exit_reason} | ₹{unrealized:+,.0f}")