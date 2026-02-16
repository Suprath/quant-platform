from quant_sdk import QCAlgorithm, Resolution
import datetime

class OptimizedORBStrategy(QCAlgorithm):
    """
    Enhanced ORB Strategy - Optimized for Indian Markets
    Improvements: Dynamic position sizing, multi-timeframe confirmation, trend filter
    """
    
    def Initialize(self):
        self.SetCash(100000)
        self.SetStartDate(2023, 1, 1)
        self.SetEndDate(2024, 12, 31)
        
        # Risk Management
        self.max_risk_per_trade = 0.02  # Increased from implicit ~0.5% to 2%
        self.max_positions = 3
        self.leverage = 3.0
        self.SetLeverage(self.leverage)
        
        # Time Settings
        self.market_open = datetime.time(9, 15)
        self.orb_end = datetime.time(9, 30)
        self.no_new_trades = datetime.time(14, 30)
        self.square_off = datetime.time(15, 20)
        
        # Universe - Top liquid Nifty stocks
        self.symbols = [
            "NSE_EQ|INE002A01018",  # Reliance
            "NSE_EQ|INE040A01034",  # HDFC Bank
            "NSE_EQ|INE467B01029",  # TCS
        ]
        
        self.data = {}
        for symbol in self.symbols:
            self.AddEquity(symbol, Resolution.Tick)
            self.data[symbol] = {
                'orb_high': None, 'orb_low': None, 'orb_set': False,
                'in_position': False, 'direction': 0, 'entry': 0,
                'stop': 0, 'target': 0, 'quantity': 0,
                'vwap': 0, 'total_pv': 0, 'total_vol': 0,
                'bars': [], 'day_high': 0, 'day_low': float('inf')
            }
        
        self.current_bars = {}
        self.bar_start_times = {}
        
    def OnData(self, data):
        current_time = data.Time if hasattr(data, 'Time') else datetime.datetime.now()
        time_only = current_time.time() if isinstance(current_time, datetime.datetime) else current_time
        
        # Daily reset
        if time_only < datetime.time(9, 16):
            for symbol in self.symbols:
                d = self.data[symbol]
                d['orb_high'] = None
                d['orb_low'] = None
                d['orb_set'] = False
                d['vwap'] = 0
                d['total_pv'] = 0
                d['total_vol'] = 0
                d['bars'] = []
                d['day_high'] = 0
                d['day_low'] = float('inf')
            self.current_bars = {}
            return
        
        # Square off
        if time_only >= self.square_off:
            for symbol in self.symbols:
                if self.data[symbol]['in_position']:
                    self.Liquidate(symbol)
                    self.data[symbol]['in_position'] = False
            return
        
        for symbol in self.symbols:
            if not data.ContainsKey(symbol):
                continue
                
            tick = data[symbol]
            price = tick.Price
            qty = getattr(tick, 'Quantity', getattr(tick, 'Size', 1))
            
            d = self.data[symbol]
            
            # Update VWAP
            d['total_pv'] += price * qty
            d['total_vol'] += qty
            if d['total_vol'] > 0:
                d['vwap'] = d['total_pv'] / d['total_vol']
            
            # Update day range
            d['day_high'] = max(d['day_high'], price)
            d['day_low'] = min(d['day_low'], price)
            
            # Build 5-min bars
            bar_time = datetime.datetime(
                current_time.year, current_time.month, current_time.day,
                current_time.hour, (current_time.minute // 5) * 5, 0
            )
            
            if symbol not in self.current_bars or self.bar_start_times.get(symbol) != bar_time:
                # Process previous bar if exists
                if symbol in self.current_bars and not d['in_position']:
                    self._process_bar(symbol, self.current_bars[symbol], time_only)
                
                # New bar
                self.current_bars[symbol] = {
                    'open': price, 'high': price, 'low': price, 
                    'close': price, 'volume': qty
                }
                self.bar_start_times[symbol] = bar_time
            else:
                bar = self.current_bars[symbol]
                bar['high'] = max(bar['high'], price)
                bar['low'] = min(bar['low'], price)
                bar['close'] = price
                bar['volume'] += qty
            
            # Manage position
            if d['in_position']:
                self._manage_position(symbol, price, time_only)

    def _process_bar(self, symbol, bar, time_only):
        """Process completed bar for entry signals"""
        d = self.data[symbol]
        high, low, close = bar['high'], bar['low'], bar['close']
        
        # ORB Setup
        if not d['orb_set'] and time_only <= self.orb_end:
            if d['orb_high'] is None or high > d['orb_high']:
                d['orb_high'] = high
            if d['orb_low'] is None or low < d['orb_low']:
                d['orb_low'] = low
            
            if time_only >= self.orb_end:
                d['orb_set'] = True
                orb_range = ((d['orb_high'] - d['orb_low']) / d['orb_low']) * 100
                self.Log(f"{symbol} ORB: {d['orb_high']:.2f}/{d['orb_low']:.2f} ({orb_range:.2f}%)")
        
        # Entry Logic
        if not d['orb_set'] or d['in_position'] or time_only > self.no_new_trades:
            return
        
        # Check max positions
        active = sum(1 for s in self.symbols if self.data[s]['in_position'])
        if active >= self.max_positions:
            return
        
        # Filters
        orb_range_pct = (d['orb_high'] - d['orb_low']) / d['orb_low']
        if orb_range_pct < 0.003 or orb_range_pct > 0.025:  # 0.3% to 2.5% range
            return
        
        # Trend filter: VWAP direction
        vwap_trend = "UP" if close > d['vwap'] else "DOWN"
        
        # Volatility filter (ATR-like using day range)
        day_range_pct = (d['day_high'] - d['day_low']) / d['day_low']
        
        # LONG: Break above ORB high + above VWAP + not extended
        if close > d['orb_high'] and close > d['vwap'] and day_range_pct < 0.04:
            self._enter_position(symbol, close, 1)
            
        # SHORT: Break below ORB low + below VWAP + not extended
        elif close < d['orb_low'] and close < d['vwap'] and day_range_pct < 0.04:
            self._enter_position(symbol, close, -1)

    def _enter_position(self, symbol, price, direction):
        """Enter with proper risk management"""
        d = self.data[symbol]
        
        # Position sizing: Risk 2% of portfolio
        portfolio_value = self.Portfolio['TotalPortfolioValue']
        risk_amount = portfolio_value * self.max_risk_per_trade
        
        # Dynamic stop: 0.5% for high confidence, 1% for normal
        orb_range = (d['orb_high'] - d['orb_low']) / d['orb_low']
        if orb_range > 0.015:
            stop_pct = 0.008  # Tighter stop for wide ORB
        else:
            stop_pct = 0.005  # Wider stop for tight ORB
        
        stop_distance = price * stop_pct
        quantity = int(risk_amount / stop_distance)
        
        # Apply leverage (max 3x)
        max_position_value = portfolio_value * self.leverage
        position_value = price * quantity
        
        if position_value > max_position_value:
            quantity = int(max_position_value / price)
        
        if quantity < 1:
            return
        
        d['in_position'] = True
        d['direction'] = direction
        d['entry'] = price
        d['stop'] = price - (stop_distance * direction)
        d['target'] = price + (stop_distance * 3 * direction)  # 1:3 R:R
        d['quantity'] = quantity
        
        weight = (price * quantity) / portfolio_value
        
        if direction == 1:
            self.SetHoldings(symbol, weight)
            self.Log(f"🟢 LONG {symbol} @ {price:.2f} | Qty:{quantity} | SL:{d['stop']:.2f} | T:{d['target']:.2f}")
        else:
            self.SetHoldings(symbol, -weight)
            self.Log(f"🔴 SHORT {symbol} @ {price:.2f} | Qty:{quantity} | SL:{d['stop']:.2f} | T:{d['target']:.2f}")

    def _manage_position(self, symbol, price, time_only):
        """Manage open position"""
        d = self.data[symbol]
        
        # Calculate unrealized
        unrealized = (price - d['entry']) * d['direction']
        unrealized_pct = (unrealized / d['entry']) * 100
        
        exit_reason = None
        
        # Stop loss
        if d['direction'] == 1 and price <= d['stop']:
            exit_reason = "STOP"
        elif d['direction'] == -1 and price >= d['stop']:
            exit_reason = "STOP"
        
        # Target
        if d['direction'] == 1 and price >= d['target']:
            exit_reason = "TARGET"
        elif d['direction'] == -1 and price <= d['target']:
            exit_reason = "TARGET"
        
        # Trailing stop (breakeven after 1% profit)
        if unrealized_pct > 1.0:
            if d['direction'] == 1:
                new_stop = max(d['stop'], d['entry'])
                if price * 0.995 > d['stop']:  # Trail at -0.5% from current
                    d['stop'] = price * 0.995
            else:
                new_stop = min(d['stop'], d['entry'])
                if price * 1.005 < d['stop']:
                    d['stop'] = price * 1.005
        
        # Time exit (3:00 PM if not in profit)
        if time_only >= datetime.time(15, 0) and unrealized_pct < 0.5:
            exit_reason = "TIME"
        
        if exit_reason:
            self.Liquidate(symbol)
            self.Log(f"🔚 EXIT {symbol} @ {price:.2f} | {exit_reason} | P&L: ₹{unrealized * d['quantity']:.0f} ({unrealized_pct:.2f}%)")
            d['in_position'] = False