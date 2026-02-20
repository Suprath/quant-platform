from quant_sdk import QCAlgorithm, Resolution
import datetime

class CapitalMaximizerStrategy(QCAlgorithm):
    """
    Capital Maximization Strategy for ₹100,000
    Target: Deploy 80-90% capital daily, 2-5% daily returns
    """
    
    def Initialize(self):
        self.SetCash(100000)
        self.SetStartDate(2023, 1, 1)
        self.SetEndDate(2024, 12, 31)
        
        # AGGRESSIVE Capital Deployment
        self.target_utilization = 0.85  # 85% capital in play
        self.leverage = 3.0
        self.SetLeverage(self.leverage)
        
        # Risk: Higher risk per trade but strict overall limits
        self.max_risk_per_trade = 0.03  # 3% risk per trade (was 1.5%)
        self.max_daily_risk = 0.09     # 9% total daily risk (3 losing trades max)
        self.daily_risk_taken = 0
        
        # Trading Schedule - Capture all opportunities
        self.market_open = datetime.time(9, 15)
        self.orb_end = datetime.time(9, 30)
        self.active_trading = datetime.time(9, 31)
        self.last_entry = datetime.time(14, 45)
        self.market_close = datetime.time(15, 25)
        
        # Multi-Stock Universe for diversification
        self.symbols = [
            "NSE_EQ|INE002A01018",  # Reliance (30% allocation)
            "NSE_EQ|INE040A01034",  # HDFC Bank (30% allocation)
            "NSE_EQ|INE009A01021",  # Infosys (20% allocation)
            "NSE_EQ|INE238A01034",  # ICICI Bank (20% allocation)
        ]
        
        self.allocations = {
            "NSE_EQ|INE002A01018": 0.30,
            "NSE_EQ|INE040A01034": 0.30,
            "NSE_EQ|INE009A01021": 0.20,
            "NSE_EQ|INE238A01034": 0.20,
        }
        
        # State per symbol
        self.data = {}
        for symbol in self.symbols:
            self.AddEquity(symbol, Resolution.Tick)
            self.data[symbol] = {
                'orb_high': None, 'orb_low': None, 'orb_set': False,
                'in_position': False, 'direction': 0, 'entry': 0,
                'stop': 0, 'target': 0, 'quantity': 0,
                'vwap': 0, 'total_pv': 0, 'total_vol': 0,
                'trades_today': 0, 'max_trades': 2,  # 2 trades per stock
                'ema_fast': 0, 'ema_slow': 0,
                'price_history': []
            }
        
        self.current_bars = {}
        self.daily_pnl = 0
        self.last_date = None
        
        self.Log("💰 CAPITAL MAXIMIZER STRATEGY")
        self.Log(f"💵 Capital: ₹{self.Portfolio['TotalPortfolioValue']:,.0f}")
        self.Log(f"🎯 Target Utilization: {self.target_utilization*100:.0f}%")
        self.Log(f"⚡ Leverage: {self.leverage}x")
        
    def OnData(self, data):
        current_time = data.Time if hasattr(data, 'Time') else datetime.datetime.now()
        time_only = current_time.time() if isinstance(current_time, datetime.datetime) else current_time
        current_date = current_time.date() if isinstance(current_time, datetime.datetime) else datetime.date.today()
        
        # Daily Reset
        if self.last_date != current_date:
            self.daily_risk_taken = 0
            self.daily_pnl = 0
            self.last_date = current_date
            
            for symbol in self.symbols:
                d = self.data[symbol]
                d['orb_high'] = None
                d['orb_low'] = None
                d['orb_set'] = False
                d['vwap'] = 0
                d['total_pv'] = 0
                d['total_vol'] = 0
                d['trades_today'] = 0
                d['price_history'] = []
                d['ema_fast'] = 0
                d['ema_slow'] = 0
                d['in_position'] = False
            
            self.current_bars = {}
            self.Log(f"📅 NEW DAY: {current_date} | Risk Budget: ₹{self.Portfolio['TotalPortfolioValue'] * self.max_daily_risk:,.0f}")
        
        # Market Close - Square Everything
        if time_only >= self.market_close:
            for symbol in self.symbols:
                if self.data[symbol]['in_position']:
                    self.Liquidate(symbol)
                    self.data[symbol]['in_position'] = False
            return
        
        # Process each symbol
        for symbol in self.symbols:
            if not data.ContainsKey(symbol):
                continue
            
            tick = data[symbol]
            price = tick.Price
            qty = getattr(tick, 'Quantity', 1)
            
            d = self.data[symbol]
            
            # Update VWAP
            d['total_pv'] += price * qty
            d['total_vol'] += qty
            if d['total_vol'] > 0:
                d['vwap'] = d['total_pv'] / d['total_vol']
            
            # Update EMAs
            d['price_history'].append(price)
            if len(d['price_history']) > 30:
                d['price_history'].pop(0)
            
            if len(d['price_history']) >= 20:
                if d['ema_fast'] == 0:
                    d['ema_fast'] = sum(d['price_history'][-10:]) / 10
                    d['ema_slow'] = sum(d['price_history'][-20:]) / 20
                else:
                    d['ema_fast'] = (price - d['ema_fast']) * (2/11) + d['ema_fast']
                    d['ema_slow'] = (price - d['ema_slow']) * (2/21) + d['ema_slow']
            
            # Build 5-min bars
            bar_time = datetime.datetime(
                current_time.year, current_time.month, current_time.day,
                current_time.hour, (current_time.minute // 5) * 5, 0
            ) if isinstance(current_time, datetime.datetime) else current_time
            
            if symbol not in self.current_bars or self.current_bars[symbol].get('time') != bar_time:
                # Process completed bar
                if symbol in self.current_bars and not d['in_position']:
                    self._process_bar(symbol, self.current_bars[symbol], time_only, current_time)
                
                # New bar
                self.current_bars[symbol] = {
                    'open': price, 'high': price, 'low': price,
                    'close': price, 'volume': qty, 'time': bar_time
                }
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
        """Generate entry signals with full capital deployment"""
        d = self.data[symbol]
        
        # Skip if max trades for this symbol
        if d['trades_today'] >= d['max_trades']:
            return
        
        # Skip if daily risk exceeded
        portfolio_value = self.Portfolio['TotalPortfolioValue']
        if self.daily_risk_taken >= self.max_daily_risk:
            return
        
        # ORB Setup (9:15 - 9:30)
        if not d['orb_set'] and time_only <= self.orb_end:
            if d['orb_high'] is None or bar['high'] > d['orb_high']:
                d['orb_high'] = bar['high']
            if d['orb_low'] is None or bar['low'] < d['orb_low']:
                d['orb_low'] = bar['low']
            
            if time_only >= self.orb_end:
                d['orb_set'] = True
                orb_range = (d['orb_high'] - d['orb_low']) / d['orb_low']
                if 0.05 <= orb_range * 100 <= 2.0:
                    self.Log(f"{symbol} ORB: {d['orb_high']:.2f}/{d['orb_low']:.2f} ({orb_range*100:.2f}%)")
        
        # Entry Logic (after ORB)
        if not d['orb_set'] or time_only < self.active_trading or time_only > self.last_entry:
            return
        
        close = bar['close']
        high = bar['high']
        low = bar['low']
        
        # Need EMAs
        if d['ema_fast'] == 0:
            return
        
        # === STRATEGY 1: ORB Breakout with Momentum ===
        orb_range = d['orb_high'] - d['orb_low']
        
        # Long: Break above ORB high + momentum + above VWAP
        long_breakout = (close > d['orb_high'] + orb_range * 0.1 and
                        close > d['vwap'] and
                        d['ema_fast'] > d['ema_slow'])
        
        # Short: Break below ORB low + momentum + below VWAP
        short_breakout = (close < d['orb_low'] - orb_range * 0.1 and
                         close < d['vwap'] and
                         d['ema_fast'] < d['ema_slow'])
        
        # === STRATEGY 2: VWAP Reversal (if missed ORB) ===
        vwap_deviation = abs(close - d['vwap']) / d['vwap']
        
        long_reversal = (close < d['vwap'] * 0.997 and
                        low <= d['vwap'] * 0.995 and
                        close > d['vwap'] * 0.990 and
                        d['ema_fast'] > d['ema_slow'] * 0.998)
        
        short_reversal = (close > d['vwap'] * 1.003 and
                         high >= d['vwap'] * 1.005 and
                         close < d['vwap'] * 1.010 and
                         d['ema_fast'] < d['ema_slow'] * 1.002)
        
        if long_breakout:
            self._enter_position(symbol, close, 1, "ORB_BREAKOUT")
        elif short_breakout:
            self._enter_position(symbol, close, -1, "ORB_BREAKOUT")
        elif long_reversal and d['trades_today'] == 0:
            self._enter_position(symbol, close, 1, "VWAP_REVERSAL")
        elif short_reversal and d['trades_today'] == 0:
            self._enter_position(symbol, close, -1, "VWAP_REVERSAL")

    def _enter_position(self, symbol, price, direction, signal_type):
        """Deploy capital aggressively with smart sizing"""
        d = self.data[symbol]
        portfolio_value = self.Portfolio['TotalPortfolioValue']
        
        # Risk per trade: 3% of portfolio
        risk_amount = portfolio_value * self.max_risk_per_trade
        
        # Stop distance: 0.8% for breakout, 0.6% for reversal
        if "ORB" in signal_type:
            stop_pct = 0.008
            target_r = 2.5  # 1:2.5 R:R
        else:
            stop_pct = 0.006
            target_r = 2.0  # 1:2 R:R
        
        stop_distance = price * stop_pct
        
        # Calculate base quantity from risk
        base_quantity = int(risk_amount / stop_distance)
        
        # ALLOCATE CAPITAL AGGRESSIVELY
        # Target: Deploy 85% of capital across all positions
        allocation = self.allocations[symbol] * self.target_utilization * self.leverage
        target_notional = portfolio_value * allocation
        
        # Quantity from capital allocation
        alloc_quantity = int(target_notional / price)
        
        # Take MAX of risk-based and allocation-based (ensure full deployment)
        quantity = max(base_quantity, alloc_quantity)
        
        # Cap at available buying power
        available_cash = self.Portfolio['Cash']
        max_qty_cash = int((available_cash * 0.9) / price)  # Keep 10% buffer
        
        # Cap at 3x leverage total
        current_exposure = sum(
            abs(self.Portfolio[s]['Quantity'] * self.Portfolio[s]['AveragePrice']) 
            for s in self.symbols if self.Portfolio[s]['Invested']
        )
        max_leverage_exposure = portfolio_value * self.leverage
        remaining_leverage = max_leverage_exposure - current_exposure
        max_qty_leverage = int(remaining_leverage / price) if remaining_leverage > 0 else 0
        
        quantity = min(quantity, max_qty_cash, max_qty_leverage, 500)  # Max 500 shares
        
        if quantity < 5:  # Minimum 5 shares
            return
        
        # Update risk tracking
        trade_risk = (stop_distance * quantity) / portfolio_value
        self.daily_risk_taken += trade_risk
        
        d['in_position'] = True
        d['direction'] = direction
        d['entry'] = price
        d['stop'] = price - (stop_distance * direction)
        d['target'] = price + (stop_distance * target_r * direction)
        d['quantity'] = quantity
        d['trades_today'] += 1
        d['max_r'] = 0
        
        notional = quantity * price
        utilization = notional / portfolio_value * 100
        
        side = "🟢 LONG" if direction == 1 else "🔴 SHORT"
        
        self.Log(f"{side} {symbol} | {signal_type}")
        self.Log(f"   Qty: {quantity} | Price: ₹{price:.2f} | Notional: ₹{notional:,.0f} ({utilization:.1f}%)")
        self.Log(f"   Risk: ₹{stop_distance * quantity:,.0f} ({trade_risk*100:.2f}%) | Target: ₹{d['target']:.2f}")
        
        weight = notional / portfolio_value
        self.SetHoldings(symbol, weight if direction == 1 else -weight)

    def _manage_position(self, symbol, price, time_only):
        """Aggressive profit taking and loss cutting"""
        d = self.data[symbol]
        
        unrealized = (price - d['entry']) * d['direction']
        unrealized_pct = (unrealized / d['entry']) * 100
        
        stop_dist = abs(d['entry'] - d['stop'])
        current_r = unrealized / stop_dist if stop_dist > 0 else 0
        
        # Track max R
        if current_r > d['max_r']:
            d['max_r'] = current_r
        
        exit_reason = None
        
        # 1. Stop Loss (hard)
        if d['direction'] == 1 and price <= d['stop']:
            exit_reason = "STOP"
        elif d['direction'] == -1 and price >= d['stop']:
            exit_reason = "STOP"
        
        # 2. Target (scale out at target, don't wait)
        if d['direction'] == 1 and price >= d['target']:
            exit_reason = "TARGET"
        elif d['direction'] == -1 and price <= d['target']:
            exit_reason = "TARGET"
        
        # 3. Trailing Stop (protect profits aggressively)
        if d['max_r'] >= 1.0:
            # Move to breakeven + 0.5%
            if d['direction'] == 1:
                new_stop = max(d['stop'], d['entry'] * 1.005)
                if d['max_r'] >= 1.5:
                    # Trail at 60% of max profit
                    trail = d['entry'] + (stop_dist * d['max_r'] * 0.6)
                    new_stop = max(new_stop, trail)
                d['stop'] = new_stop
            else:
                new_stop = min(d['stop'], d['entry'] * 0.995)
                if d['max_r'] >= 1.5:
                    trail = d['entry'] - (stop_dist * d['max_r'] * 0.6)
                    new_stop = min(new_stop, trail)
                d['stop'] = new_stop
        
        # 4. Time-based exit (20 mins max)
        if time_only > self.last_entry and current_r < 0.5:
            exit_reason = "TIME_CUTOFF"
        
        # 5. Quick profit taking (exit at 1.2R if momentum fading)
        if current_r >= 1.2 and current_r < d['max_r'] * 0.8:
            exit_reason = "MOMENTUM_FADE"
        
        if exit_reason:
            self._exit_position(symbol, price, exit_reason, unrealized)

    def _exit_position(self, symbol, price, reason, unrealized):
        """Exit and update P&L tracking"""
        d = self.data[symbol]
        
        pnl_rupees = unrealized * d['quantity']
        pnl_pct = (pnl_rupees / (d['entry'] * d['quantity'])) * 100
        
        self.Liquidate(symbol)
        d['in_position'] = False
        
        self.daily_pnl += pnl_rupees
        
        emoji = "✅ PROFIT" if pnl_rupees > 0 else "❌ LOSS"
        
        self.Log(f"{emoji} {symbol} | {reason}")
        self.Log(f"   Exit: ₹{price:.2f} | P&L: ₹{pnl_rupees:+,.0f} ({pnl_pct:+.2f}%) | MaxR: {d['max_r']:.1f}")
        self.Log(f"   Daily P&L: ₹{self.daily_pnl:+,.0f}")