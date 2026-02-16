from quant_sdk import QCAlgorithm, Resolution
import datetime

class OptimizedORBStrategy(QCAlgorithm):
    """
    Optimized ORB Strategy - Fixed Entry Conditions
    """
    
    def Initialize(self):
        self.SetCash(100000)
        self.SetStartDate(2023, 1, 1)
        self.SetEndDate(2024, 12, 31)
        
        self.max_risk_per_trade = 0.02
        self.max_positions = 3
        self.leverage = 3.0
        self.SetLeverage(self.leverage)
        
        self.market_open = datetime.time(9, 15)
        self.orb_end = datetime.time(9, 30)
        self.no_new_trades = datetime.time(14, 30)
        self.square_off = datetime.time(15, 20)
        
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
                d['in_position'] = False
            self.current_bars = {}
            return
        
        # Square off
        if time_only >= self.square_off:
            for symbol in self.symbols:
                if self.data[symbol]['in_position']:
                    self.Liquidate(symbol)
                    self.Log(f"SQUARE OFF {symbol}")
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
                    self._process_bar(symbol, self.current_bars[symbol], time_only, current_time)
                
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

    def _process_bar(self, symbol, bar, time_only, current_time):
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
                # RELAXED FILTER: Accept ORB range 0.05% to 3%
                if 0.05 <= orb_range <= 3.0:
                    self.Log(f"{symbol} ORB ACTIVE: {d['orb_high']:.2f}/{d['orb_low']:.2f} ({orb_range:.2f}%)")
                else:
                    self.Log(f"{symbol} ORB REJECTED (range {orb_range:.2f}%)")
                    d['orb_set'] = False  # Disable trading this day
        
        # Entry Logic
        if not d['orb_set'] or d['in_position'] or time_only > self.no_new_trades:
            return
        
        # Check max positions
        active = sum(1 for s in self.symbols if self.data[s]['in_position'])
        if active >= self.max_positions:
            return
        
        # RELAXED ENTRY CONDITIONS
        # 1. Price must break ORB level
        # 2. Price must be on right side of VWAP (trend confirmation)
        # 3. Minimum 0.05% momentum beyond ORB
        
        long_trigger = close > d['orb_high'] * 1.0005 and close > d['vwap'] * 0.999
        short_trigger = close < d['orb_low'] * 0.9995 and close < d['vwap'] * 1.001
        
        if long_trigger:
            self._enter_position(symbol, close, 1, "LONG")
        elif short_trigger:
            self._enter_position(symbol, close, -1, "SHORT")
        else:
            # Debug why no entry
            if close > d['orb_high'] or close < d['orb_low']:
                above_orb_high = close > d['orb_high']
                below_orb_low = close < d['orb_low']
                above_vwap = close > d['vwap']
                self.Log(f"{symbol} NO ENTRY: Close={close:.2f} ORB_H={d['orb_high']:.2f} ORB_L={d['orb_low']:.2f} VWAP={d['vwap']:.2f} AboveORB={above_orb_high} BelowORB={below_orb_low} AboveVWAP={above_vwap}")

    def _enter_position(self, symbol, price, direction, side):
        """Enter with proper risk management"""
        d = self.data[symbol]
        
        # Position sizing: Risk 2% of portfolio
        portfolio_value = self.Portfolio['TotalPortfolioValue']
        risk_amount = portfolio_value * self.max_risk_per_trade
        
        # Stop distance: 0.6% for tight ORB, 0.8% for wide ORB
        orb_range = (d['orb_high'] - d['orb_low']) / d['orb_low']
        stop_pct = 0.008 if orb_range > 0.01 else 0.006
        
        stop_distance = price * stop_pct
        quantity = int(risk_amount / stop_distance)
        
        # Apply leverage
        max_position_value = portfolio_value * self.leverage
        position_value = price * quantity
        
        if position_value > max_position_value:
            quantity = int(max_position_value / price)
        
        if quantity < 1:
            quantity = 1  # Force at least 1 share for testing
        
        d['in_position'] = True
        d['direction'] = direction
        d['entry'] = price
        d['stop'] = price - (stop_distance * direction)
        d['target'] = price + (stop_distance * 2.5 * direction)  # 1:2.5 R:R
        d['quantity'] = quantity
        
        weight = min((price * quantity) / portfolio_value, self.leverage * 0.9)
        
        if direction == 1:
            self.SetHoldings(symbol, weight)
            self.Log(f"🟢 {side} {symbol} @ {price:.2f} | Qty:{quantity} | SL:{d['stop']:.2f} | T:{d['target']:.2f}")
        else:
            self.SetHoldings(symbol, -weight)
            self.Log(f"🔴 {side} {symbol} @ {price:.2f} | Qty:{quantity} | SL:{d['stop']:.2f} | T:{d['target']:.2f}")

    def _manage_position(self, symbol, price, time_only):
        """Manage open position"""
        d = self.data[symbol]
        
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
        
        # Breakeven stop after 0.8% profit
        if unrealized_pct > 0.8 and d['stop'] != d['entry']:
            if d['direction'] == 1:
                d['stop'] = max(d['stop'], d['entry'])
            else:
                d['stop'] = min(d['stop'], d['entry'])
        
        # Hard time exit
        if time_only >= datetime.time(15, 15):
            exit_reason = "TIME"
        
        if exit_reason:
            self.Liquidate(symbol)
            pnl = unrealized * d['quantity']
            self.Log(f"🔚 EXIT {symbol} @ {price:.2f} | {exit_reason} | P&L: ₹{pnl:.0f} ({unrealized_pct:.2f}%)")
            d['in_position'] = False