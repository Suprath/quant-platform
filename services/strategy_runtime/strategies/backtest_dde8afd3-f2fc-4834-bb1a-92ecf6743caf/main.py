from quant_sdk import QCAlgorithm, Resolution
import datetime

class UltraAggressiveStrategy(QCAlgorithm):
    """
    Ultra-Aggressive Strategy - Guaranteed to Trade
    Removes all filters, trades on every opportunity
    """
    
    def Initialize(self):
        self.SetCash(100000)
        self.SetStartDate(2023, 1, 1)
        self.SetEndDate(2024, 12, 31)
        
        self.leverage = 3.0
        self.SetLeverage(self.leverage)
        
        # 4 stocks
        self.symbols = [
            "NSE_EQ|INE002A01018",
            "NSE_EQ|INE040A01034", 
            "NSE_EQ|INE009A01021",
            "NSE_EQ|INE238A01034",
        ]
        
        # State - minimal
        self.state = {}
        for symbol in self.symbols:
            self.AddEquity(symbol, Resolution.Tick)
            self.state[symbol] = {
                'in_position': False,
                'direction': 0,
                'entry': 0,
                'stop': 0,
                'target': 0,
                'qty': 0,
                'trades': 0,
                'prices': [],
            }
        
        self.last_date = None
        self.total_trades = 0
        
        self.Log("⚡ ULTRA-AGGRESSIVE STRATEGY")
        self.Log(f"💰 Capital: ₹{self.Portfolio.Cash:,.0f}")
        
    def OnData(self, data):
        current_time = data.Time if hasattr(data, 'Time') else datetime.datetime.now()
        time_only = current_time.time() if isinstance(current_time, datetime.datetime) else current_time
        current_date = current_time.date() if isinstance(current_time, datetime.datetime) else datetime.date.today()
        
        nav = self.Portfolio.TotalPortfolioValue
        
        # Daily reset
        if self.last_date != current_date:
            self.last_date = current_date
            for symbol in self.symbols:
                s = self.state[symbol]
                s['in_position'] = False
                s['trades'] = 0
                s['prices'] = []
            self.Log(f"📅 {current_date}")
        
        # Square off at close
        if time_only >= datetime.time(15, 25):
            for symbol in self.symbols:
                if self.state[symbol]['in_position']:
                    self.Liquidate(symbol)
                    self.state[symbol]['in_position'] = False
            return
        
        # Trade every 15 minutes
        trade_window = time_only.minute % 15 == 0 and time_only.second < 5
        
        for symbol in self.symbols:
            if not data.ContainsKey(symbol):
                continue
            
            tick = data[symbol]
            price = tick.Price
            
            s = self.state[symbol]
            
            # Update prices
            s['prices'].append(price)
            if len(s['prices']) > 20:
                s['prices'].pop(0)
            
            # Manage existing position
            if s['in_position']:
                self._manage(symbol, price, time_only, nav)
            # Enter new position every 15 mins if not in position
            elif trade_window and s['trades'] < 4:  # Max 4 trades per stock per day
                if len(s['prices']) >= 10:
                    self._enter(symbol, price, time_only, nav)

    def _enter(self, symbol, price, time_only, nav):
        """Enter with momentum direction"""
        s = self.state[symbol]
        
        # Simple momentum: compare last 5 prices vs previous 5
        recent = sum(s['prices'][-5:]) / 5
        older = sum(s['prices'][-10:-5]) / 5
        
        direction = 1 if recent > older else -1
        
        # Position size: 25% of capital per stock with leverage
        target_notional = nav * 0.25 * self.leverage * 0.8
        qty = int(target_notional / price)
        
        if qty < 5:
            qty = 5  # Minimum
        
        # Cap at 300 shares
        qty = min(qty, 300)
        
        s['in_position'] = True
        s['direction'] = direction
        s['entry'] = price
        s['stop'] = price * (0.985 if direction == 1 else 1.015)  # 1.5% stop
        s['target'] = price * (1.02 if direction == 1 else 0.98)   # 2% target
        s['qty'] = qty
        s['trades'] += 1
        self.total_trades += 1
        
        notional = qty * price
        
        side = "🟢 BUY" if direction == 1 else "🔴 SELL"
        self.Log(f"{side} #{self.total_trades} | {symbol[-6:]} | ₹{price:.2f} | Qty: {qty} | ₹{notional:,.0f}")
        
        weight = notional / nav
        self.SetHoldings(symbol, weight if direction == 1 else -weight)

    def _manage(self, symbol, price, time_only, nav):
        """Simple management"""
        s = self.state[symbol]
        
        pnl = (price - s['entry']) * s['direction'] * s['qty']
        pnl_pct = (price - s['entry']) / s['entry'] * 100 * s['direction']
        
        exit_reason = None
        
        # Stop
        if s['direction'] == 1 and price <= s['stop']:
            exit_reason = "STOP"
        elif s['direction'] == -1 and price >= s['stop']:
            exit_reason = "STOP"
        
        # Target
        if s['direction'] == 1 and price >= s['target']:
            exit_reason = "TARGET"
        elif s['direction'] == -1 and price <= s['target']:
            exit_reason = "TARGET"
        
        # Time limit (10 minutes)
        if time_only.minute % 15 >= 10 and pnl_pct > 0.5:
            exit_reason = "TIME_PROFIT"
        elif time_only.minute % 15 >= 12:
            exit_reason = "TIME_CUT"
        
        if exit_reason:
            self.Liquidate(symbol)
            s['in_position'] = False
            
            emoji = "✅" if pnl > 0 else "❌"
            self.Log(f"{emoji} EXIT | {symbol[-6:]} | {exit_reason} | ₹{pnl:+,.0f} ({pnl_pct:+.2f}%)")