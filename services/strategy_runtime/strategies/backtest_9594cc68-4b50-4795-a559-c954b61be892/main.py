from quant_sdk import QCAlgorithm, Resolution
import datetime

class AggressiveMultiTradeStrategy(QCAlgorithm):
    """
    Aggressive Capital Deployment - Maximum Trades
    Goal: 10-20 trades/day, deploy 90%+ capital
    """
    
    def Initialize(self):
        self.SetCash(100000)
        self.SetStartDate(2023, 1, 1)
        self.SetEndDate(2024, 12, 31)
        
        # Maximum leverage and utilization
        self.leverage = 3.0
        self.SetLeverage(self.leverage)
        self.target_utilization = 0.90  # 90% capital deployed
        
        # Very permissive risk (we want trades!)
        self.max_trades_per_symbol = 5  # 5 trades per stock
        self.max_concurrent_positions = 4  # All 4 stocks at once allowed
        
        # Time settings - trade all day
        self.no_trade_before = datetime.time(9, 20)  # Only skip first 5 mins
        self.last_entry = datetime.time(15, 00)  # Trade until 3 PM
        self.square_off = datetime.time(15, 25)
        
        # 4 liquid stocks
        self.symbols = [
            "NSE_EQ|INE002A01018",  # Reliance
            "NSE_EQ|INE040A01034",  # HDFC Bank
            "NSE_EQ|INE009A01021",  # Infosys
            "NSE_EQ|INE238A01034",  # ICICI Bank
        ]
        
        # Equal allocation
        self.allocations = {sym: 0.25 for sym in self.symbols}
        
        # State
        self.state = {}
        for symbol in self.symbols:
            self.AddEquity(symbol, Resolution.Tick)
            self.state[symbol] = {
                'trades_today': 0,
                'in_position': False,
                'direction': 0,
                'entry': 0,
                'stop': 0,
                'target': 0,
                'quantity': 0,
                'vwap': 0,
                'vwap_sum_pv': 0,
                'vwap_sum_vol': 0,
                'prev_price': 0,
                'price_momentum': 0,
            }
        
        self.last_date = None
        self.total_trades_today = 0
        
        self.Log("🚀 AGGRESSIVE MULTI-TRADE STRATEGY")
        self.Log(f"💵 Capital: ₹{self.Portfolio.Cash:,.0f}")
        self.Log("🎯 Goal: 10-20 trades/day | 90% capital deployed")
        
    def OnData(self, data):
        current_time = data.Time if hasattr(data, 'Time') else datetime.datetime.now()
        time_only = current_time.time() if isinstance(current_time, datetime.datetime) else current_time
        current_date = current_time.date() if isinstance(current_time, datetime.datetime) else datetime.date.today()
        
        portfolio_value = self.Portfolio.TotalPortfolioValue
        cash = self.Portfolio.Cash
        holdings_value = self.Portfolio.TotalHoldingsValue
        
        # Daily reset
        if self.last_date != current_date:
            self.last_date = current_date
            self.total_trades_today = 0
            
            for symbol in self.symbols:
                s = self.state[symbol]
                s['trades_today'] = 0
                s['in_position'] = False
                s['vwap'] = 0
                s['vwap_sum_pv'] = 0
                s['vwap_sum_vol'] = 0
                s['price_momentum'] = 0
            
            self.Log(f"📅 NEW DAY: {current_date}")
            self.Log(f"   Portfolio: ₹{portfolio_value:,.0f} | Cash: ₹{cash:,.0f}")
        
        # Square off at close
        if time_only >= self.square_off:
            for symbol in self.symbols:
                if self.state[symbol]['in_position']:
                    self.Liquidate(symbol)
                    self.state[symbol]['in_position'] = False
                    
                    # Final P&L
                    pnl = portfolio_value - 100000
                    self.Log(f"🏁 DAY END | Total Trades: {self.total_trades_today} | P&L: ₹{pnl:+,.0f}")
            return
        
        # Skip early morning
        if time_only < self.no_trade_before:
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
            s['vwap_sum_pv'] += price * qty
            s['vwap_sum_vol'] += qty
            if s['vwap_sum_vol'] > 0:
                s['vwap'] = s['vwap_sum_pv'] / s['vwap_sum_vol']
            
            # Calculate momentum (simple price change)
            if s['prev_price'] > 0:
                s['price_momentum'] = (price - s['prev_price']) / s['prev_price'] * 100
            s['prev_price'] = price
            
            # Manage existing position
            if s['in_position']:
                self._manage_position(symbol, price, time_only, portfolio_value)
            else:
                # Look for entry - VERY PERMISSIVE
                self._check_entry(symbol, price, time_only, portfolio_value)

    def _check_entry(self, symbol, price, time_only, portfolio_value):
        """Ultra-permissive entry logic"""
        s = self.state[symbol]
        
        # Skip if max trades for this symbol
        if s['trades_today'] >= self.max_trades_per_symbol:
            return
        
        # Skip if after last entry time
        if time_only > self.last_entry:
            return
        
        # Need VWAP ready
        if s['vwap'] == 0:
            return
        
        # Count current positions
        positions_open = sum(1 for sym in self.symbols if self.state[sym]['in_position'])
        
        # === STRATEGY: VWAP Deviation ===
        # Simply trade when price deviates from VWAP and shows momentum
        
        vwap_deviation = (price - s['vwap']) / s['vwap'] * 100  # In percent
        
        # LONG: Price 0.3% below VWAP with positive momentum
        long_signal = vwap_deviation < -0.3 and s['price_momentum'] > -0.1
        
        # SHORT: Price 0.3% above VWAP with negative momentum  
        short_signal = vwap_deviation > 0.3 and s['price_momentum'] < 0.1
        
        # Also trade on strong momentum regardless of VWAP
        strong_up = s['price_momentum'] > 0.15  # 0.15% up move
        strong_down = s['price_momentum'] < -0.15  # 0.15% down move
        
        if long_signal or strong_up:
            self._enter_position(symbol, price, 1, "VWAP_DEV", portfolio_value)
        elif short_signal or strong_down:
            self._enter_position(symbol, price, -1, "VWAP_DEV", portfolio_value)

    def _enter_position(self, symbol, price, direction, signal, portfolio_value):
        """Enter with maximum sizing"""
        s = self.state[symbol]
        
        # Calculate position size to deploy capital aggressively
        # Target: 25% of portfolio per stock with 3x leverage = 75% notional per stock
        
        target_notional = portfolio_value * self.allocations[symbol] * self.leverage * 0.8
        
        # Or minimum ₹15,000 per trade
        min_notional = 15000
        notional = max(target_notional, min_notional)
        
        quantity = int(notional / price)
        
        # Cap at 300 shares per trade
        quantity = min(quantity, 300)
        
        if quantity < 5:
            return
        
        # Check available cash (need margin)
        margin_required = (quantity * price) / self.leverage
        if self.Portfolio.Cash < margin_required * 0.3:  # 30% buffer only
            return
        
        # Set stop and target (tight for quick turns)
        stop_pct = 0.006  # 0.6% stop
        target_pct = 0.012  # 1.2% target (1:2 R:R)
        
        stop_dist = price * stop_pct
        
        s['in_position'] = True
        s['direction'] = direction
        s['entry'] = price
        s['stop'] = price - (stop_dist * direction)
        s['target'] = price + (price * target_pct * direction)
        s['quantity'] = quantity
        s['trades_today'] += 1
        self.total_trades_today += 1
        
        notional_value = quantity * price
        
        side = "🟢 LONG" if direction == 1 else "🔴 SHORT"
        
        self.Log(f"{side} #{self.total_trades_today} | {symbol} | {signal}")
        self.Log(f"   Qty: {quantity} | Price: ₹{price:.2f} | Notional: ₹{notional_value:,.0f}")
        self.Log(f"   VWAP: ₹{s['vwap']:.2f} | Momentum: {s['price_momentum']:.3f}%")
        
        # Set holdings
        weight = notional_value / portfolio_value
        self.SetHoldings(symbol, weight if direction == 1 else -weight)

    def _manage_position(self, symbol, price, time_only, portfolio_value):
        """Quick exit management"""
        s = self.state[symbol]
        
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
        
        # Quick profit take (0.8% profit) - scalping style
        if unrealized_pct > 0.8:
            exit_reason = "SCALP_PROFIT"
        
        # Quick cut loss (-0.4%) - tight risk management
        if unrealized_pct < -0.4:
            exit_reason = "TIGHT_STOP"
        
        # Time limit (8 minutes max hold)
        # Note: Would need entry timestamp for precise tracking
        
        # Square off time
        if time_only >= datetime.time(14, 55):
            exit_reason = "DAY_END"
        
        if exit_reason:
            pnl_rupees = (price - s['entry']) * s['quantity'] * s['direction']
            
            self.Liquidate(symbol)
            s['in_position'] = False
            
            emoji = "✅" if pnl_rupees > 0 else "❌"
            self.Log(f"{emoji} EXIT | {symbol} | {exit_reason} | ₹{pnl_rupees:+,.0f} ({unrealized_pct:+.2f}%)")
            self.Log(f"   Portfolio: ₹{portfolio_value:,.0f} | Cash: ₹{self.Portfolio.Cash:,.0f}")