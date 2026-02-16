from quant_sdk import QCAlgorithm, Resolution
import datetime
import statistics

class AdaptiveLearningStrategy(QCAlgorithm):
    """
    Walk-Forward Adaptive Strategy
    Days 1-2: LEARNING PHASE - Collect data, calculate optimal parameters
    Day 3+: TRADING PHASE - Use learned parameters to trade
    """
    
    def Initialize(self):
        self.SetCash(100000)
        self.SetStartDate(2023, 1, 1)
        self.SetEndDate(2024, 12, 31)
        
        self.leverage = 3.0
        self.SetLeverage(self.leverage)
        
        # 4 stocks for diversification
        self.symbols = [
            "NSE_EQ|INE002A01018",  # Reliance
            "NSE_EQ|INE040A01034",  # HDFC Bank
            "NSE_EQ|INE009A01021",  # Infosys
            "NSE_EQ|INE238A01034",  # ICICI Bank
        ]
        
        # Learning & Trading Phases
        self.LEARNING_DAYS = 2
        self.TRADING_START_DAY = 3
        
        # Per-stock adaptive parameters (learned)
        self.adaptive_params = {}
        
        # State for each stock
        self.state = {}
        for symbol in self.symbols:
            self.AddEquity(symbol, Resolution.Tick)
            
            self.adaptive_params[symbol] = {
                'learned': False,
                'day_count': 0,
                'optimal_stop_pct': 0.008,  # Default 0.8%
                'optimal_target_r': 2.0,     # Default 1:2 R:R
                'optimal_entry_threshold': 0.003,  # 0.3% deviation
                'volatility_regime': 'normal',  # low, normal, high
                'avg_daily_range': 0,
                'win_rate_ema': 50,  # Track win rate
            }
            
            self.state[symbol] = {
                'prices': [],
                'volumes': [],
                'vwap': 0,
                'vwap_pv': 0,
                'vwap_vol': 0,
                'in_position': False,
                'direction': 0,
                'entry': 0,
                'stop': 0,
                'target': 0,
                'qty': 0,
                'trades_today': 0,
                'daily_trades': [],  # Track all trades for learning
                'ema_fast': 0,
                'ema_slow': 0,
                'day_high': 0,
                'day_low': float('inf'),
                'prev_close': 0,
            }
        
        # Global tracking
        self.current_date = None
        self.day_number = 0  # Increment each trading day
        self.total_trades = 0
        self.learning_complete = False
        
        self.Log("🎓 ADAPTIVE LEARNING STRATEGY")
        self.Log("📚 Phase 1 (Days 1-2): Learning - Collect market data")
        self.Log("🚀 Phase 2 (Day 3+): Trading - Use optimized parameters")
        
    def OnData(self, data):
        current_time = data.Time if hasattr(data, 'Time') else datetime.datetime.now()
        time_only = current_time.time() if isinstance(current_time, datetime.datetime) else current_time
        current_date = current_time.date() if isinstance(current_time, datetime.datetime) else datetime.date.today()
        
        nav = self.Portfolio.TotalPortfolioValue
        
        # New day detection
        if self.current_date != current_date:
            self._handle_new_day(current_date, nav)
        
        # Market close - square off
        if time_only >= datetime.time(15, 25):
            self._market_close(nav, time_only)
            return
        
        # Process each stock
        for symbol in self.symbols:
            if not data.ContainsKey(symbol):
                continue
            
            tick = data[symbol]
            price = tick.Price
            qty = getattr(tick, 'Quantity', 1)
            
            s = self.state[symbol]
            params = self.adaptive_params[symbol]
            
            # Update VWAP
            s['vwap_pv'] += price * qty
            s['vwap_vol'] += qty
            if s['vwap_vol'] > 0:
                s['vwap'] = s['vwap_pv'] / s['vwap_vol']
            
            # Update price history for learning
            s['prices'].append(price)
            s['volumes'].append(qty)
            if len(s['prices']) > 100:
                s['prices'].pop(0)
                s['volumes'].pop(0)
            
            # Update day high/low
            s['day_high'] = max(s['day_high'], price)
            s['day_low'] = min(s['day_low'], price)
            
            # Update EMAs
            if len(s['prices']) >= 21:
                if s['ema_fast'] == 0:
                    s['ema_fast'] = sum(s['prices'][-10:]) / 10
                    s['ema_slow'] = sum(s['prices'][-21:]) / 21
                else:
                    s['ema_fast'] = (price - s['ema_fast']) * (2/11) + s['ema_fast']
                    s['ema_slow'] = (price - s['ema_slow']) * (2/22) + s['ema_slow']
            
            # === PHASE 1: LEARNING (Days 1-2) ===
            if self.day_number <= self.LEARNING_DAYS:
                # Just collect data, no trading
                continue
            
            # === PHASE 2: TRADING (Day 3+) ===
            else:
                # Build 5-min bars for signals
                bar_time = datetime.datetime(
                    current_time.year, current_time.month, current_time.day,
                    current_time.hour, (current_time.minute // 5) * 5, 0
                ) if isinstance(current_time, datetime.datetime) else current_time
                
                if not hasattr(self, 'current_bar'):
                    self.current_bar = {}
                
                if symbol not in self.current_bar or self.current_bar[symbol].get('time') != bar_time:
                    # Process completed bar
                    if symbol in self.current_bar and not s['in_position']:
                        self._check_entry(symbol, self.current_bar[symbol], time_only, nav, params)
                    
                    # New bar
                    self.current_bar[symbol] = {
                        'open': price, 'high': price, 'low': price,
                        'close': price, 'volume': qty, 'time': bar_time
                    }
                else:
                    bar = self.current_bar[symbol]
                    bar['high'] = max(bar['high'], price)
                    bar['low'] = min(bar['low'], price)
                    bar['close'] = price
                    bar['volume'] += qty
                
                # Manage open position
                if s['in_position']:
                    self._manage_position(symbol, price, time_only, nav, params)

    def _handle_new_day(self, new_date, nav):
        """Handle day transition and learning"""
        old_date = self.current_date
        self.current_date = new_date
        
        # Increment day counter (only count trading days with data)
        if old_date is not None:
            self.day_number += 1
            
            # === END OF DAY LEARNING ===
            if self.day_number <= self.LEARNING_DAYS:
                self._learn_from_day(old_date)
            
            # Log phase transition
            if self.day_number == self.LEARNING_DAYS:
                self._finalize_learning()
        
        # Reset daily state
        for symbol in self.symbols:
            s = self.state[symbol]
            params = self.adaptive_params[symbol]
            
            # Store previous close for gap analysis
            if s['prices']:
                s['prev_close'] = s['prices'][-1]
            
            # Reset daily tracking
            s['trades_today'] = 0
            s['day_high'] = 0
            s['day_low'] = float('inf')
            s['in_position'] = False
            
            # Increment param day counter
            params['day_count'] += 1
        
        self.Log(f"📅 Day {self.day_number}: {new_date}")
        
        if self.day_number <= self.LEARNING_DAYS:
            self.Log(f"   🔍 LEARNING PHASE - Collecting data (Day {self.day_number}/{self.LEARNING_DAYS})")
        else:
            self.Log(f"   🚀 TRADING PHASE - Using learned parameters")
            self._log_learned_params()

    def _learn_from_day(self, date):
        """Analyze completed day and extract optimal parameters"""
        self.Log(f"🧠 Learning from {date}...")
        
        for symbol in self.symbols:
            s = self.state[symbol]
            params = self.adaptive_params[symbol]
            
            if len(s['prices']) < 50:
                continue
            
            # 1. Calculate Volatility Regime
            returns = []
            for i in range(1, len(s['prices'])):
                ret = (s['prices'][i] - s['prices'][i-1]) / s['prices'][i-1]
                returns.append(ret)
            
            if returns:
                volatility = statistics.stdev(returns) * 100  # Daily volatility %
                params['avg_daily_range'] = (s['day_high'] - s['day_low']) / s['day_low'] * 100
                
                # Classify regime
                if volatility < 0.8:
                    params['volatility_regime'] = 'low'
                    params['optimal_stop_pct'] = 0.005  # Tighter stops in low vol
                    params['optimal_target_r'] = 1.5      # Lower targets
                elif volatility < 1.5:
                    params['volatility_regime'] = 'normal'
                    params['optimal_stop_pct'] = 0.008
                    params['optimal_target_r'] = 2.0
                else:
                    params['volatility_regime'] = 'high'
                    params['optimal_stop_pct'] = 0.012   # Wider stops in high vol
                    params['optimal_target_r'] = 2.5      # Higher targets
                
                # 2. Calculate optimal entry threshold based on mean reversion
                vwap_deviations = []
                for price in s['prices'][-50:]:
                    if s['vwap'] > 0:
                        dev = abs(price - s['vwap']) / s['vwap']
                        vwap_deviations.append(dev)
                
                if vwap_deviations:
                    avg_dev = statistics.mean(vwap_deviations)
                    params['optimal_entry_threshold'] = max(avg_dev * 1.5, 0.002)
                
                self.Log(f"   {symbol[-6:]}: Vol={volatility:.2f}% | "
                        f"Regime={params['volatility_regime']} | "
                        f"Stop={params['optimal_stop_pct']*100:.1f}% | "
                        f"TargetR={params['optimal_target_r']:.1f}")

    def _finalize_learning(self):
        """Finalize learning and prepare for trading"""
        self.learning_complete = True
        
        self.Log("=" * 50)
        self.Log("✅ LEARNING COMPLETE - Ready to trade")
        self.Log("=" * 50)
        
        for symbol in self.symbols:
            params = self.adaptive_params[symbol]
            params['learned'] = True
            self.Log(f"{symbol[-6:]}: {params['volatility_regime'].upper()} vol | "
                    f"Stop={params['optimal_stop_pct']*100:.1f}% | "
                    f"Entry>={params['optimal_entry_threshold']*100:.2f}%")

    def _log_learned_params(self):
        """Log current learned parameters"""
        for symbol in self.symbols:
            params = self.adaptive_params[symbol]
            if params['learned']:
                self.Log(f"   {symbol[-6:]}: {params['volatility_regime']} | "
                        f"WinRateEMA={params['win_rate_ema']:.0f}%")

    def _check_entry(self, symbol, bar, time_only, nav, params):
        """Entry using learned parameters"""
        s = self.state[symbol]
        
        # Skip if max trades (3 per day)
        if s['trades_today'] >= 3:
            return
        
        # Skip early/late
        if time_only < datetime.time(9, 25) or time_only > datetime.time(14, 45):
            return
        
        # Need EMAs
        if s['ema_fast'] == 0:
            return
        
        close = bar['close']
        
        # === ADAPTIVE ENTRY LOGIC ===
        
        # 1. VWAP Mean Reversion (Primary)
        if s['vwap'] > 0:
            vwap_dev = (close - s['vwap']) / s['vwap']
            threshold = params['optimal_entry_threshold']
            
            # Long: Price below VWAP by threshold, but not too far
            long_vwap = vwap_dev < -threshold and vwap_dev > -threshold * 3 and s['ema_fast'] > s['ema_slow']
            
            # Short: Price above VWAP by threshold, but not too far
            short_vwap = vwap_dev > threshold and vwap_dev < threshold * 3 and s['ema_fast'] < s['ema_slow']
            
            if long_vwap:
                self._enter_trade(symbol, close, 1, "ADAPT_VWAP", nav, params)
                return
            elif short_vwap:
                self._enter_trade(symbol, close, -1, "ADAPT_VWAP", nav, params)
                return
        
        # 2. Momentum Breakout (Secondary)
        if len(s['prices']) >= 10:
            momentum = (close - s['prices'][-10]) / s['prices'][-10] * 100
            
            if momentum > 0.4 and s['ema_fast'] > s['ema_slow'] * 1.001:
                self._enter_trade(symbol, close, 1, "ADAPT_MOM", nav, params)
            elif momentum < -0.4 and s['ema_fast'] < s['ema_slow'] * 0.999:
                self._enter_trade(symbol, close, -1, "ADAPT_MOM", nav, params)

    def _enter_trade(self, symbol, price, direction, signal, nav, params):
        """Enter with adaptive position sizing"""
        s = self.state[symbol]
        
        # Position size: 25% of capital per trade
        notional = nav * 0.25 * self.leverage
        qty = int(notional / price)
        qty = min(qty, 400)
        
        if qty < 10:
            return
        
        # Use learned stop distance
        stop_pct = params['optimal_stop_pct']
        stop_dist = price * stop_pct
        
        # Target based on learned R:R
        target_r = params['optimal_target_r']
        
        s['in_position'] = True
        s['direction'] = direction
        s['entry'] = price
        s['stop'] = price - (stop_dist * direction)
        s['target'] = price + (stop_dist * target_r * direction)
        s['qty'] = qty
        s['trades_today'] += 1
        self.total_trades += 1
        
        side = "🟢 LONG" if direction == 1 else "🔴 SHORT"
        
        self.Log(f"{side} #{self.total_trades} | {symbol[-6:]} | {signal}")
        self.Log(f"   Price: ₹{price:.2f} | Qty: {qty} | Notional: ₹{qty*price:,.0f}")
        self.Log(f"   Stop: ₹{s['stop']:.2f} ({stop_pct*100:.2f}%) | "
                f"Target: ₹{s['target']:.2f} (1:{target_r:.1f})")
        
        weight = (qty * price) / nav
        self.SetHoldings(symbol, weight if direction == 1 else -weight)

    def _manage_position(self, symbol, price, time_only, nav, params):
        """Manage with adaptive trailing"""
        s = self.state[symbol]
        
        unrealized = (price - s['entry']) * s['direction'] * s['qty']
        unrealized_pct = (price - s['entry']) / s['entry'] * 100 * s['direction']
        
        stop_dist = abs(s['entry'] - s['stop'])
        current_r = ((price - s['entry']) * s['direction']) / stop_dist if stop_dist > 0 else 0
        
        exit_reason = None
        
        # Hard stop
        if s['direction'] == 1 and price <= s['stop']:
            exit_reason = "STOP"
        elif s['direction'] == -1 and price >= s['stop']:
            exit_reason = "STOP"
        
        # Target
        if s['direction'] == 1 and price >= s['target']:
            exit_reason = "TARGET"
        elif s['direction'] == -1 and price <= s['target']:
            exit_reason = "TARGET"
        
        # Adaptive trailing based on volatility regime
        trail_trigger = 0.8 if params['volatility_regime'] == 'low' else 1.0
        
        if current_r > trail_trigger:
            # Move to breakeven
            if s['direction'] == 1:
                s['stop'] = max(s['stop'], s['entry'] * 1.001)
            else:
                s['stop'] = min(s['stop'], s['entry'] * 0.999)
            
            # Trail further at 1.5R+
            if current_r > 1.5:
                trail_pct = 0.006 if params['volatility_regime'] == 'low' else 0.008
                if s['direction'] == 1:
                    s['stop'] = max(s['stop'], price * (1 - trail_pct))
                else:
                    s['stop'] = min(s['stop'], price * (1 + trail_pct))
        
        # Time cut
        if time_only >= datetime.time(14, 50) and current_r < 0.5:
            exit_reason = "TIME"
        
        if exit_reason:
            # Update win rate EMA
            won = unrealized > 0
            params['win_rate_ema'] = params['win_rate_ema'] * 0.9 + (100 if won else 0) * 0.1
            
            self.Liquidate(symbol)
            s['in_position'] = False
            
            emoji = "✅" if won else "❌"
            self.Log(f"{emoji} EXIT | {symbol[-6:]} | {exit_reason} | "
                    f"₹{unrealized:+,.0f} ({unrealized_pct:+.2f}%) | "
                    f"R:{current_r:.1f}")

    def _market_close(self, nav, time_only):
        """End of day"""
        for symbol in self.symbols:
            s = self.state[symbol]
            if s['in_position']:
                self.Liquidate(symbol)
                s['in_position'] = False
        
        pnl = nav - 100000
        self.Log(f"🏁 CLOSE | P&L: ₹{pnl:+,.0f} ({pnl/1000:.2f}%) | "
                f"Trades: {self.total_trades}")