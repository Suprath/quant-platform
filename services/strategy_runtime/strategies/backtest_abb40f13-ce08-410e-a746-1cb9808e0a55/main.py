from quant_sdk import QCAlgorithm, Resolution
import datetime

class CapitalMaximizerStrategy(QCAlgorithm):
    """
    Capital Maximization Strategy for ₹100,000
    Deploys 85%+ capital daily across 4 stocks with 3x leverage
    Target: 2-5% daily returns
    """
    
    def Initialize(self):
        self.SetCash(100000)
        self.SetStartDate(2023, 1, 1)
        self.SetEndDate(2024, 12, 31)
        
        # Capital Deployment Settings
        self.target_utilization = 0.85  # Deploy 85% of capital
        self.leverage = 3.0
        self.SetLeverage(self.leverage)
        
        # Risk Management
        self.max_risk_per_trade = 0.025  # 2.5% risk per trade
        self.max_daily_risk = 0.075      # 7.5% total daily risk (3 trades)
        self.daily_risk_used = 0
        
        # Trading Hours
        self.orb_end = datetime.time(9, 30)
        self.last_entry = datetime.time(14, 30)
        self.market_close = datetime.time(15, 25)
        
        # Universe - 4 liquid large caps
        self.symbols = [
            "NSE_EQ|INE002A01018",  # Reliance (30%)
            "NSE_EQ|INE040A01034",  # HDFC Bank (30%)
            "NSE_EQ|INE009A01021",  # Infosys (20%)
            "NSE_EQ|INE238A01034",  # ICICI Bank (20%)
        ]
        
        self.allocations = {
            "NSE_EQ|INE002A01018": 0.30,
            "NSE_EQ|INE040A01034": 0.30,
            "NSE_EQ|INE009A01021": 0.20,
            "NSE_EQ|INE238A01034": 0.20,
        }
        
        # Per-symbol state
        self.state = {}
        for symbol in self.symbols:
            self.AddEquity(symbol, Resolution.Tick)
            self.state[symbol] = {
                'orb_high': None, 'orb_low': None, 'orb_set': False,
                'in_position': False, 'direction': 0, 'entry': 0,
                'stop': 0, 'target': 0, 'quantity': 0,
                'vwap': 0, 'vwap_pv': 0, 'vwap_vol': 0,
                'trades_today': 0, 'max_trades': 2,
                'ema_fast': 0, 'ema_slow': 0, 'price_hist': []
            }
        
        self.bars = {}
        self.last_date = None
        
        # Log initial capital
        self.Log("💰 CAPITAL MAXIMIZER STRATEGY")
        self.Log(f"💵 Initial Capital: ₹{self.Portfolio.Cash:,.0f}")
        self.Log(f"🎯 Target Utilization: {self.target_utilization*100:.0f}%")
        self.Log(f"⚡ Leverage: {self.leverage}x")
        
    def OnData(self, data):
        current_time = data.Time if hasattr(data, 'Time') else datetime.datetime.now()
        time_only = current_time.time() if isinstance(current_time, datetime.datetime) else current_time
        current_date = current_time.date() if isinstance(current_time, datetime.datetime) else datetime.date.today()
        
        # Get live portfolio status
        portfolio_value = self.Portfolio.TotalPortfolioValue
        cash = self.Portfolio.Cash
        invested = self.Portfolio.Invested
        holdings_value = self.Portfolio.TotalHoldingsValue
        
        # Daily Reset
        if self.last_date != current_date:
            self.daily_risk_used = 0
            self.last_date = current_date
            
            for symbol in self.symbols:
                s = self.state[symbol]
                s['orb_high'] = None
                s['orb_low'] = None
                s['orb_set'] = False
                s['vwap'] = 0
                s['vwap_pv'] = 0
                s['vwap_vol'] = 0
                s['trades_today'] = 0
                s['price_hist'] = []
                s['ema_fast'] = 0
                s['ema_slow'] = 0
                s['in_position'] = False
            
            self.bars = {}
            
            utilization = (holdings_value / portfolio_value * 100) if portfolio_value > 0 else 0
            self.Log(f"📅 NEW DAY: {current_date}")
            self.Log(f"   Portfolio: ₹{portfolio_value:,.0f} | Cash: ₹{cash:,.0f} | Invested: {utilization:.1f}%")
        
        # Market Close - Square Everything
        if time_only >= self.market_close:
            for symbol in self.symbols:
                if self.state[symbol]['in_position']:
                    self.Liquidate(symbol)
                    self.state[symbol]['in_position'] = False
                    
                    # Log P&L for the day
                    day_pnl = portfolio_value - 100000
                    self.Log(f"🏁 DAY CLOSE | P&L: ₹{day_pnl:+,.0f} ({day_pnl/1000:.2f}%)")
            return
        
        # Skip if daily risk limit hit
        if self.daily_risk_used >= self.max_daily_risk:
            return
        
        # Process each symbol
        for symbol in self.symbols:
            if not data.ContainsKey(symbol):
                continue
            
            tick = data[symbol]
            price = tick.Price
            qty = getattr(tick, 'Quantity', getattr(tick, 'Size', 1))
            
            s = self.state[symbol]
            
            # Update VWAP
            s['vwap_pv'] += price * qty
            s['vwap_vol'] += qty
            if s['vwap_vol'] > 0:
                s['vwap'] = s['vwap_pv'] / s['vwap_vol']
            
            # Update EMAs
            s['price_hist'].append(price)
            if len(s['price_hist']) > 30:
                s['price_hist'].pop(0)
            
            if len(s['price_hist']) >= 20:
                if s['ema_fast'] == 0:
                    s['ema_fast'] = sum(s['price_hist'][-10:]) / 10
                    s['ema_slow'] = sum(s['price_hist'][-20:]) / 20
                else:
                    s['ema_fast'] = (price - s['ema_fast']) * (2/11) + s['ema_fast']
                    s['ema_slow'] = (price - s['ema_slow']) * (2/21) + s['ema_slow']
            
            # Build 5-min bars
            if isinstance(current_time, datetime.datetime):
                bar_time = datetime.datetime(
                    current_time.year, current_time.month, current_time.day,
                    current_time.hour, (current_time.minute // 5) * 5, 0
                )
            else:
                bar_time = current_time
            
            if symbol not in self.bars or self.bars[symbol].get('time') != bar_time:
                # Process completed bar
                if symbol in self.bars and not s['in_position']:
                    self._check_entry(symbol, self.bars[symbol], time_only, portfolio_value)
                
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
            
            # Manage open position
            if s['in_position']:
                self._manage_position(symbol, price, time_only, portfolio_value)

    def _check_entry(self, symbol, bar, time_only, portfolio_value):
        """Check for entry signals"""
        s = self.state[symbol]
        
        # Skip if max trades reached
        if s['trades_today'] >= s['max_trades']:
            return
        
        # ORB Setup
        if not s['orb_set'] and time_only <= self.orb_end:
            if s['orb_high'] is None or bar['high'] > s['orb_high']:
                s['orb_high'] = bar['high']
            if s['orb_low'] is None or bar['low'] < s['orb_low']:
                s['orb_low'] = bar['low']
            
            if time_only >= self.orb_end:
                s['orb_set'] = True
                orb_range = (s['orb_high'] - s['orb_low']) / s['orb_low']
                if 0.08 <= orb_range * 100 <= 1.5:
                    self.Log(f"{symbol} ORB: {s['orb_high']:.2f}/{s['orb_low']:.2f} ({orb_range*100:.2f}%)")
        
        # Entry Logic (after 9:30, before 14:30)
        if not s['orb_set'] or time_only <= self.orb_end or time_only > self.last_entry:
            return
        
        close = bar['close']
        if s['ema_fast'] == 0:
            return
        
        orb_range = s['orb_high'] - s['orb_low']
        
        # Breakout entries
        long_break = (close > s['orb_high'] + orb_range * 0.05 and
                     close > s['vwap'] and
                     s['ema_fast'] > s['ema_slow'])
        
        short_break = (close < s['orb_low'] - orb_range * 0.05 and
                      close < s['vwap'] and
                      s['ema_fast'] < s['ema_slow'])
        
        # Reversal entries (only first trade)
        long_rev = (close < s['vwap'] * 0.996 and
                   s['ema_fast'] > s['ema_slow'] and
                   s['trades_today'] == 0)
        
        short_rev = (close > s['vwap'] * 1.004 and
                    s['ema_fast'] < s['ema_slow'] and
                    s['trades_today'] == 0)
        
        if long_break:
            self._enter(symbol, close, 1, "ORB_BREAK", portfolio_value)
        elif short_break:
            self._enter(symbol, close, -1, "ORB_BREAK", portfolio_value)
        elif long_rev:
            self._enter(symbol, close, 1, "VWAP_REV", portfolio_value)
        elif short_rev:
            self._enter(symbol, close, -1, "VWAP_REV", portfolio_value)

    def _enter(self, symbol, price, direction, signal, portfolio_value):
        """Enter position with full capital deployment"""
        s = self.state[symbol]
        
        # Risk amount
        risk_amount = portfolio_value * self.max_risk_per_trade
        
        # Stop distance
        if "ORB" in signal:
            stop_pct = 0.007
            target_r = 2.5
        else:
            stop_pct = 0.005
            target_r = 2.0
        
        stop_dist = price * stop_pct
        
        # Quantity from risk
        risk_qty = int(risk_amount / stop_dist)
        
        # Quantity from capital allocation
        alloc = self.allocations[symbol] * self.target_utilization * self.leverage
        alloc_qty = int((portfolio_value * alloc) / price)
        
        # Take max of risk-based or allocation-based
        quantity = max(risk_qty, alloc_qty)
        
        # Cap individual position
        quantity = min(quantity, 400)
        
        if quantity < 10:
            return
        
        # Check if we have enough buying power
        needed_cash = quantity * price / self.leverage  # Margin required
        if self.Portfolio.Cash < needed_cash * 0.5:  # 50% buffer
            return
        
        # Update tracking
        trade_risk_pct = (stop_dist * quantity) / portfolio_value
        self.daily_risk_used += trade_risk_pct
        
        s['in_position'] = True
        s['direction'] = direction
        s['entry'] = price
        s['stop'] = price - (stop_dist * direction)
        s['target'] = price + (stop_dist * target_r * direction)
        s['quantity'] = quantity
        s['trades_today'] += 1
        s['max_r'] = 0
        
        notional = quantity * price
        weight = notional / portfolio_value
        
        side = "🟢 LONG" if direction == 1 else "🔴 SHORT"
        
        self.Log(f"{side} {symbol} | {signal}")
        self.Log(f"   Qty: {quantity} | Price: ₹{price:.2f} | Notional: ₹{notional:,.0f}")
        self.Log(f"   Risk: {trade_risk_pct*100:.2f}% | Stop: ₹{s['stop']:.2f} | Target: ₹{s['target']:.2f}")
        self.Log(f"   Portfolio: ₹{portfolio_value:,.0f} | Cash: ₹{self.Portfolio.Cash:,.0f}")
        
        self.SetHoldings(symbol, weight if direction == 1 else -weight)

    def _manage_position(self, symbol, price, time_only, portfolio_value):
        """Manage open position"""
        s = self.state[symbol]
        
        # Calculate P&L
        unrealized = (price - s['entry']) * s['direction'] * s['quantity']
        unrealized_pct = (price - s['entry']) / s['entry'] * 100 * s['direction']
        
        stop_dist = abs(s['entry'] - s['stop'])
        current_r = ((price - s['entry']) * s['direction']) / stop_dist if stop_dist > 0 else 0
        
        # Track max R
        if current_r > s['max_r']:
            s['max_r'] = current_r
        
        exit_reason = None
        
        # Hard stops
        if s['direction'] == 1 and price <= s['stop']:
            exit_reason = "STOP"
        elif s['direction'] == -1 and price >= s['stop']:
            exit_reason = "STOP"
        
        # Target
        if s['direction'] == 1 and price >= s['target']:
            exit_reason = "TARGET"
        elif s['direction'] == -1 and price <= s['target']:
            exit_reason = "TARGET"
        
        # Trailing stop (breakeven at 1R, trail at 1.5R+)
        if s['max_r'] >= 1.0:
            if s['direction'] == 1:
                new_stop = max(s['stop'], s['entry'] * 1.002)
                if s['max_r'] >= 1.5:
                    trail = s['entry'] + stop_dist * 1.2
                    new_stop = max(new_stop, trail)
                s['stop'] = new_stop
            else:
                new_stop = min(s['stop'], s['entry'] * 0.998)
                if s['max_r'] >= 1.5:
                    trail = s['entry'] - stop_dist * 1.2
                    new_stop = min(new_stop, trail)
                s['stop'] = new_stop
        
        # Time exit
        if time_only >= datetime.time(14, 45) and current_r < 0.5:
            exit_reason = "TIME"
        
        if exit_reason:
            self.Liquidate(symbol)
            s['in_position'] = False
            
            # Realized P&L
            realized = unrealized
            
            emoji = "✅ PROFIT" if realized > 0 else "❌ LOSS"
            self.Log(f"{emoji} {symbol} | {exit_reason}")
            self.Log(f"   Exit: ₹{price:.2f} | P&L: ₹{realized:+,.0f} ({unrealized_pct:+.2f}%)")
            self.Log(f"   MaxR: {s['max_r']:.1f} | Portfolio: ₹{self.Portfolio.TotalPortfolioValue:,.0f}")