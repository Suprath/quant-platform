from quant_sdk import QCAlgorithm, Resolution
import datetime
import statistics

class ForcedTradeAdaptiveStrategy(QCAlgorithm):
    """
    Adaptive Strategy GUARANTEED to Trade
    Forces trades when no signal triggers automatically
    """
    
    def Initialize(self):
        self.SetCash(100000)
        self.SetStartDate(2023, 1, 1)
        self.SetEndDate(2024, 12, 31)
        
        self.leverage = 3.0
        self.SetLeverage(self.leverage)
        
        self.symbols = [
            "NSE_EQ|INE002A01018",  # Reliance
            "NSE_EQ|INE040A01034",  # HDFC Bank
            "NSE_EQ|INE009A01021",  # Infosys
            "NSE_EQ|INE238A01034",  # ICICI Bank
        ]
        
        # Learning parameters
        self.LEARNING_DAYS = 2
        self.day_number = 0
        self.learning_complete = False
        
        # Per-stock parameters
        self.params = {}
        self.state = {}
        
        for symbol in self.symbols:
            self.AddEquity(symbol, Resolution.Tick)
            
            self.params[symbol] = {
                'learned': False,
                'volatility_regime': 'normal',
                'stop_pct': 0.006,  # Default 0.6%
                'target_r': 2.0,
                'entry_threshold': 0.002,  # 0.2% default
                'avg_range': 0,
            }
            
            self.state[symbol] = {
                'prices': [],
                'volumes': [],
                'vwap': 0,
                'vwap_pv': 0,
                'vwap_vol': 0,
                'ema_fast': 0,
                'ema_slow': 0,
                'in_position': False,
                'direction': 0,
                'entry': 0,
                'stop': 0,
                'target': 0,
                'qty': 0,
                'trades_today': 0,
                'last_trade_time': None,
                'day_high': 0,
                'day_low': float('inf'),
                'bars_5m': [],
            }
        
        self.current_date = None
        self.total_trades = 0
        
        self.Log("⚡ FORCED TRADE ADAPTIVE STRATEGY")
        self.Log("📚 Days 1-2: Learning")
        self.Log("🚀 Day 3+: Trading with MINIMUM 2 trades per stock per day")
        
    def OnData(self, data):
        current_time = data.Time if hasattr(data, 'Time') else datetime.datetime.now()
        time_only = current_time.time() if isinstance(current_time, datetime.datetime) else current_time
        current_date = current_time.date() if isinstance(current_time, datetime.datetime) else datetime.date.today()
        
        nav = self.Portfolio.TotalPortfolioValue
        
        # New day detection
        if self.current_date != current_date:
            self._handle_new_day(current_date, nav, time_only)
        
        # Market close
        if time_only >= datetime.time(15, 25):
            self._market_close(nav, time_only)
            return
        
        # Skip if still learning
        if self.day_number <= self.LEARNING_DAYS:
            return
        
        # === TRADING PHASE ===
        for symbol in self.symbols:
            if not data.ContainsKey(symbol):
                continue
            
            tick = data[symbol]
            price = tick.Price
            qty = getattr(tick, 'Quantity', 1)
            
            s = self.state[symbol]
            p = self.params[symbol]
            
            # Update VWAP
            s['vwap_pv'] += price * qty
            s['vwap_vol'] += qty
            if s['vwap_vol'] > 0:
                s['vwap'] = s['vwap_pv'] / s['vwap_vol']
            
            # Update prices
            s['prices'].append(price)
            s['volumes'].append(qty)
            if len(s['prices']) > 50:
                s['prices'].pop(0)
                s['volumes'].pop(0)
            
            # Update EMAs
            if len(s['prices']) >= 21:
                if s['ema_fast'] == 0:
                    s['ema_fast'] = sum(s['prices'][-10:]) / 10
                    s['ema_slow'] = sum(s['prices'][-20:]) / 20
                else:
                    s['ema_fast'] = (price - s['ema_fast']) * (2/11) + s['ema_fast']
                    s['ema_slow'] = (price - s['ema_slow']) * (2/22) + s['ema_slow']
            
            # Update day range
            s['day_high'] = max(s['day_high'], price)
            s['day_low'] = min(s['day_low'], price)
            
            # Build 5-min bars
            if isinstance(current_time, datetime.datetime):
                bar_minute = (current_time.minute // 5) * 5
                bar_time = current_time.replace(minute=bar_minute, second=0, microsecond=0)
            else:
                bar_time = current_time
            
            # Check if new bar
            if len(s['bars_5m']) == 0 or s['bars_5m'][-1].get('time') != bar_time:
                # New bar started, process previous if exists
                if len(s['bars_5m']) > 0 and not s['in_position']:
                    prev_bar = s['bars_5m'][-1]
                    self._evaluate_signal(symbol, prev_bar, price, time_only, nav, p, s)
                
                # Create new bar
                s['bars_5m'].append({
                    'open': price, 'high': price, 'low': price,
                    'close': price, 'volume': qty, 'time': bar_time
                })
                
                # Keep only last 2 bars
                if len(s['bars_5m']) > 2:
                    s['bars_5m'].pop(0)
            else:
                # Update current bar
                bar = s['bars_5m'][-1]
                bar['high'] = max(bar['high'], price)
                bar['low'] = min(bar['low'], price)
                bar['close'] = price
                bar['volume'] += qty
            
            # Manage open position
            if s['in_position']:
                self._manage_position(symbol, price, time_only, nav, p, s)
            
            # === FORCED ENTRY ===
            # If no position and it's been 30 mins since last trade, force entry
            if not s['in_position'] and s['last_trade_time']:
                last_mins = s['last_trade_time'].hour * 60 + s['last_trade_time'].minute
                curr_mins = time_only.hour * 60 + time_only.minute
                if (curr_mins - last_mins) >= 30 and s['trades_today'] < 2:
                    # Force momentum entry
                    self._forced_entry(symbol, price, time_only, nav, p, s)

    def _handle_new_day(self, new_date, nav, time_only):
        """Handle day transition"""
        old_date = self.current_date
        self.current_date = new_date
        
        if old_date is not None:
            self.day_number += 1
            
            # Learning from previous day
            if self.day_number <= self.LEARNING_DAYS:
                self._learn_from_day(old_date)
            
            # Finalize learning
            if self.day_number == self.LEARNING_DAYS:
                self._finalize_learning()
        
        # Reset daily state
        for symbol in self.symbols:
            s = self.state[symbol]
            p = self.params[symbol]
            
            s['trades_today'] = 0
            s['in_position'] = False
            s['day_high'] = 0
            s['day_low'] = float('inf')
            s['bars_5m'] = []
            
            # Force first trade at 10:00 AM if no trades by then
            s['last_trade_time'] = datetime.time(9, 30)  # Start from 9:30
        
        self.Log(f"📅 Day {self.day_number}: {new_date}")
        if self.day_number <= self.LEARNING_DAYS:
            self.Log(f"   🔍 LEARNING")
        else:
            self.Log(f"   🚀 TRADING (forced 2 trades per stock)")

    def _learn_from_day(self, date):
        """Learn from completed day"""
        self.Log(f"🧠 Learning from {date}...")
        
        for symbol in self.symbols:
            s = self.state[symbol]
            p = self.params[symbol]
            
            if len(s['prices']) < 30:
                continue
            
            # Calculate volatility
            returns = [(s['prices'][i] - s['prices'][i-1]) / s['prices'][i-1] 
                      for i in range(1, len(s['prices']))]
            
            if returns:
                vol = statistics.stdev(returns) * 100
                
                # Set regime and parameters
                if vol < 0.5:
                    p['volatility_regime'] = 'low'
                    p['stop_pct'] = 0.004
                    p['target_r'] = 1.5
                    p['entry_threshold'] = 0.0015  # 0.15% - VERY PERMISSIVE
                elif vol < 1.0:
                    p['volatility_regime'] = 'normal'
                    p['stop_pct'] = 0.006
                    p['target_r'] = 2.0
                    p['entry_threshold'] = 0.0025  # 0.25%
                else:
                    p['volatility_regime'] = 'high'
                    p['stop_pct'] = 0.010
                    p['target_r'] = 2.5
                    p['entry_threshold'] = 0.0040  # 0.40%
                
                p['avg_range'] = (s['day_high'] - s['day_low']) / s['day_low'] * 100
                
                self.Log(f"   {symbol[-6:]}: {p['volatility_regime']} | "
                        f"vol={vol:.2f}% | stop={p['stop_pct']*100:.2f}% | "
                        f"entry>{p['entry_threshold']*100:.2f}%")

    def _finalize_learning(self):
        """Finalize and ensure minimum thresholds"""
        self.learning_complete = True
        
        self.Log("=" * 50)
        self.Log("✅ LEARNING COMPLETE")
        self.Log("=" * 50)
        
        for symbol in self.symbols:
            p = self.params[symbol]
            p['learned'] = True
            
            # CAP MAXIMUM THRESHOLD - never above 0.3%
            p['entry_threshold'] = min(p['entry_threshold'], 0.003)
            
            self.Log(f"{symbol[-6:]}: {p['volatility_regime']} | "
                    f"stop={p['stop_pct']*100:.2f}% | "
                    f"entry>={p['entry_threshold']*100:.2f}%")

    def _evaluate_signal(self, symbol, bar, current_price, time_only, nav, p, s):
        """Evaluate entry signal with relaxed conditions"""
        
        # Skip if already in position or max trades (2 per day)
        if s['in_position'] or s['trades_today'] >= 2:
            return
        
        # Skip early/late
        if time_only < datetime.time(9, 25) or time_only > datetime.time(14, 45):
            return
        
        close = bar['close']
        
        # Need EMAs
        if s['ema_fast'] == 0 or s['vwap'] == 0:
            return
        
        # === RELAXED ENTRY CONDITIONS ===
        
        # 1. VWAP Deviation (primary)
        vwap_dev = (close - s['vwap']) / s['vwap']
        threshold = p['entry_threshold']  # Max 0.3% after capping
        
        # Long: Below VWAP by threshold
        long_vwap = vwap_dev < -threshold and s['ema_fast'] > s['ema_slow'] * 0.999
        
        # Short: Above VWAP by threshold
        short_vwap = vwap_dev > threshold and s['ema_fast'] < s['ema_slow'] * 1.001
        
        # 2. Momentum (secondary)
        momentum = 0
        if len(s['prices']) >= 10:
            momentum = (close - s['prices'][-10]) / s['prices'][-10] * 100
        
        long_mom = momentum > 0.2 and s['ema_fast'] > s['ema_slow']
        short_mom = momentum < -0.2 and s['ema_fast'] < s['ema_slow']
        
        # 3. EMA Cross (tertiary)
        long_ema = s['ema_fast'] > s['ema_slow'] * 1.002 and not s['in_position']
        short_ema = s['ema_fast'] < s['ema_slow'] * 0.998 and not s['in_position']
        
        # EXECUTE if ANY condition met
        if long_vwap or long_mom or long_ema:
            self._enter_trade(symbol, close, 1, "SIGNAL", time_only, nav, p, s)
        elif short_vwap or short_mom or short_ema:
            self._enter_trade(symbol, close, -1, "SIGNAL", time_only, nav, p, s)

    def _forced_entry(self, symbol, price, time_only, nav, p, s):
        """Force entry when no signal triggered for 30 mins"""
        
        # Determine direction based on EMA
        if s['ema_fast'] > s['ema_slow']:
            direction = 1
            signal = "FORCED_LONG"
        else:
            direction = -1
            signal = "FORCED_SHORT"
        
        self._enter_trade(symbol, price, direction, signal, time_only, nav, p, s)

    def _enter_trade(self, symbol, price, direction, signal, time_only, nav, p, s):
        """Enter trade"""
        
        # Size: 30% of capital per trade
        notional = nav * 0.30 * self.leverage
        qty = int(notional / price)
        qty = min(qty, 400)
        
        if qty < 10:
            qty = 10  # FORCE minimum 10 shares
        
        stop_dist = price * p['stop_pct']
        
        s['in_position'] = True
        s['direction'] = direction
        s['entry'] = price
        s['stop'] = price - (stop_dist * direction)
        s['target'] = price + (stop_dist * p['target_r'] * direction)
        s['qty'] = qty
        s['trades_today'] += 1
        s['last_trade_time'] = time_only
        self.total_trades += 1
        
        side = "🟢 LONG" if direction == 1 else "🔴 SHORT"
        
        self.Log(f"{side} #{self.total_trades} | {symbol[-6:]} | {signal}")
        self.Log(f"   Price: ₹{price:.2f} | Qty: {qty} | ₹{qty*price:,.0f}")
        
        weight = (qty * price) / nav
        self.SetHoldings(symbol, weight if direction == 1 else -weight)

    def _manage_position(self, symbol, price, time_only, nav, p, s):
        """Manage position"""
        
        unrealized = (price - s['entry']) * s['direction'] * s['qty']
        unrealized_pct = (price - s['entry']) / s['entry'] * 100 * s['direction']
        
        stop_dist = abs(s['entry'] - s['stop'])
        current_r = ((price - s['entry']) * s['direction']) / stop_dist if stop_dist > 0 else 0
        
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
        
        # Trail at 1R+
        if current_r > 1.0:
            if s['direction'] == 1:
                s['stop'] = max(s['stop'], s['entry'] * 1.001)
            else:
                s['stop'] = min(s['stop'], s['entry'] * 0.999)
        
        # Time cut (15 mins max)
        if time_only.minute % 15 >= 12:
            exit_reason = "TIME"
        
        if exit_reason:
            self.Liquidate(symbol)
            s['in_position'] = False
            
            emoji = "✅" if unrealized > 0 else "❌"
            self.Log(f"{emoji} EXIT | {symbol[-6:]} | {exit_reason} | ₹{unrealized:+,.0f}")

    def _market_close(self, nav, time_only):
        """Close all"""
        for symbol in self.symbols:
            s = self.state[symbol]
            if s['in_position']:
                self.Liquidate(symbol)
                s['in_position'] = False
        
        pnl = nav - 100000
        self.Log(f"🏁 Day {self.day_number} Close | P&L: ₹{pnl:+,.0f} | Trades: {self.total_trades}")