from quant_sdk import QCAlgorithm, Resolution
import datetime
import statistics

class InstitutionalGradeStrategy(QCAlgorithm):
    """
    Institutional Capital Deployment System
    Philosophy: Diversified alpha generation with strict risk overlay
    """
    
    def Initialize(self):
        self.SetCash(100000)
        self.SetStartDate(2023, 1, 1)
        self.SetEndDate(2024, 12, 31)
        
        # === FUND PARAMETERS ===
        self.leverage = 3.0
        self.SetLeverage(self.leverage)
        self.target_gross_exposure = 2.5  # 250% of NAV
        self.max_net_exposure = 0.5       # 50% net (can be 75% long / 25% short)
        self.max_single_position = 0.40   # 40% of portfolio max in one name
        
        # === RISK MANAGEMENT ===
        self.var_limit = 0.02             # 2% daily VaR limit
        self.max_drawdown_cutoff = 0.05   # Stop trading at 5% DD
        self.daily_loss_limit = 0.03      # 3% max daily loss
        
        # === UNIVERSE ===
        # Only trade the most liquid names with tight spreads
        self.universe = {
            "NSE_EQ|INE002A01018": {"name": "RELIANCE", "alloc": 0.30, "beta": 1.1},
            "NSE_EQ|INE040A01034": {"name": "HDFCBANK", "alloc": 0.25, "beta": 0.9},
            "NSE_EQ|INE238A01034": {"name": "ICICIBANK", "alloc": 0.25, "beta": 1.0},
            "NSE_EQ|INE009A01021": {"name": "INFY", "alloc": 0.20, "beta": 0.8},
        }
        
        self.symbols = list(self.universe.keys())
        
        # === STATE ===
        self.positions = {}
        self.daily_pnl = 0
        self.daily_trades = 0
        self.equity_curve = []
        self.last_date = None
        self.trading_enabled = True
        
        for symbol in self.symbols:
            self.AddEquity(symbol, Resolution.Tick)
            self.positions[symbol] = {
                # Position state
                'quantity': 0, 'direction': 0, 'entry': 0, 
                'stop': 0, 'target': 0, 'unrealized': 0,
                
                # Signals
                'alpha_score': 0, 'trend_score': 0, 'mean_rev_score': 0,
                
                # Indicators
                'vwap': 0, 'vwap_std': 0, 'vwap_upper': 0, 'vwap_lower': 0,
                'ema_9': 0, 'ema_21': 0, 'ema_50': 0,
                'rsi': 50, 'atr': 0,
                
                # Data
                'prices': [], 'volumes': [], 'returns': [],
                'high_5m': 0, 'low_5m': float('inf'), 'open_5m': 0,
                
                # Tracking
                'trades_today': 0, 'max_trades': 3,
                'last_trade_time': None,
            }
        
        self.bar_count = 0
        self.current_bar = {}
        
        # Log fund setup
        self.Log("═" * 50)
        self.Log("🏛️  INSTITUTIONAL GRADE STRATEGY")
        self.Log("═" * 50)
        self.Log(f"💰 AUM: ₹{self.Portfolio.Cash:,.0f}")
        self.Log(f"⚡ Target Gross Exposure: {self.target_gross_exposure*100:.0f}%")
        self.Log(f"📊 Max Net Exposure: {self.max_net_exposure*100:.0f}%")
        self.Log(f"🛡️  Daily Loss Limit: {self.daily_loss_limit*100:.1f}%")
        self.Log("═" * 50)
        
    def OnData(self, data):
        # === TIME HANDLING ===
        current_time = data.Time if hasattr(data, 'Time') else datetime.datetime.now()
        time_only = current_time.time() if isinstance(current_time, datetime.datetime) else current_time
        current_date = current_time.date() if isinstance(current_time, datetime.datetime) else datetime.date.today()
        
        portfolio = self.Portfolio
        nav = portfolio.TotalPortfolioValue
        cash = portfolio.Cash
        invested = portfolio.TotalHoldingsValue
        
        # === DAILY RESET & RISK CHECKS ===
        if self.last_date != current_date:
            self._daily_reset(current_date, nav)
        
        # Check circuit breakers
        if not self.trading_enabled:
            return
        
        # Calculate current exposures
        gross_exposure, net_exposure, long_exposure, short_exposure = self._calculate_exposures(nav)
        
        # Check risk limits
        if self.daily_pnl < -nav * self.daily_loss_limit:
            self.Log("🛑 DAILY LOSS LIMIT HIT - STOPPING TRADING")
            self.trading_enabled = False
            self._liquidate_all()
            return
        
        # === MARKET CLOSE PROCEDURES ===
        if time_only >= datetime.time(15, 20):
            self._market_close_procedure(nav, time_only)
            return
        
        # === DATA AGGREGATION & SIGNAL GENERATION ===
        for symbol in self.symbols:
            if not data.ContainsKey(symbol):
                continue
            
            tick = data[symbol]
            price = tick.Price
            qty = getattr(tick, 'Quantity', 1)
            
            p = self.positions[symbol]
            
            # Update tick data
            p['prices'].append(price)
            p['volumes'].append(qty)
            if len(p['prices']) > 100:
                p['prices'].pop(0)
                p['volumes'].pop(0)
            
            # Calculate returns for volatility
            if len(p['prices']) > 1:
                ret = (p['prices'][-1] - p['prices'][-2]) / p['prices'][-2]
                p['returns'].append(ret)
                if len(p['returns']) > 50:
                    p['returns'].pop(0)
            
            # Update VWAP and bands
            pv = sum(p['prices'][i] * p['volumes'][i] for i in range(len(p['prices'])))
            vol = sum(p['volumes'])
            if vol > 0:
                p['vwap'] = pv / vol
            
            # VWAP standard deviation (volatility bands)
            if len(p['prices']) >= 20:
                p['vwap_std'] = statistics.stdev(p['prices'][-20:])
                p['vwap_upper'] = p['vwap'] + 2 * p['vwap_std']
                p['vwap_lower'] = p['vwap'] - 2 * p['vwap_std']
            
            # Update EMAs
            if len(p['prices']) >= 50:
                if p['ema_50'] == 0:
                    p['ema_9'] = sum(p['prices'][-9:]) / 9
                    p['ema_21'] = sum(p['prices'][-21:]) / 21
                    p['ema_50'] = sum(p['prices'][-50:]) / 50
                else:
                    p['ema_9'] = (price - p['ema_9']) * (2/10) + p['ema_9']
                    p['ema_21'] = (price - p['ema_21']) * (2/22) + p['ema_21']
                    p['ema_50'] = (price - p['ema_50']) * (2/51) + p['ema_50']
            
            # Calculate ATR
            if len(p['prices']) >= 14:
                tr_list = []
                for i in range(-14, 0):
                    if i > -len(p['prices']):
                        high = max(p['prices'][i-1:i+1]) if i > -len(p['prices'])+1 else p['prices'][i]
                        low = min(p['prices'][i-1:i+1]) if i > -len(p['prices'])+1 else p['prices'][i]
                        prev_close = p['prices'][i-1] if i > -len(p['prices'])+1 else p['prices'][i]
                        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
                        tr_list.append(tr)
                if tr_list:
                    p['atr'] = sum(tr_list) / len(tr_list)
            
            # === 5-MIN BAR CONSTRUCTION ===
            bar_time = datetime.datetime(
                current_time.year, current_time.month, current_time.day,
                current_time.hour, (current_time.minute // 5) * 5, 0
            ) if isinstance(current_time, datetime.datetime) else current_time
            
            if symbol not in self.current_bar or self.current_bar.get(symbol, {}).get('time') != bar_time:
                # Process completed bar
                if symbol in self.current_bar:
                    self._process_bar(symbol, self.current_bar[symbol], time_only, nav, 
                                    gross_exposure, net_exposure, long_exposure, short_exposure)
                
                # New bar
                self.current_bar[symbol] = {
                    'open': price, 'high': price, 'low': price, 'close': price,
                    'volume': qty, 'time': bar_time
                }
                p['open_5m'] = price
                p['high_5m'] = price
                p['low_5m'] = price
            else:
                bar = self.current_bar[symbol]
                bar['high'] = max(bar['high'], price)
                bar['low'] = min(bar['low'], price)
                bar['close'] = price
                bar['volume'] += qty
                p['high_5m'] = max(p['high_5m'], price)
                p['low_5m'] = min(p['low_5m'], price)
            
            # === POSITION MANAGEMENT (Tick-by-tick) ===
            if p['quantity'] != 0:
                self._manage_position(symbol, price, time_only, nav, p['atr'])

    def _process_bar(self, symbol, bar, time_only, nav, gross_exp, net_exp, long_exp, short_exp):
        """Institutional-grade signal generation and position sizing"""
        p = self.positions[symbol]
        info = self.universe[symbol]
        
        # Skip if max trades reached
        if p['trades_today'] >= p['max_trades']:
            return
        
        # Skip if insufficient data
        if p['ema_50'] == 0 or p['vwap'] == 0 or p['atr'] == 0:
            return
        
        close = bar['close']
        
        # === ALPHA SIGNAL GENERATION ===
        
        # 1. Trend Following Score (-1 to +1)
        trend_score = 0
        if p['ema_9'] > p['ema_21'] > p['ema_50']:
            trend_score = 1  # Strong uptrend
        elif p['ema_9'] < p['ema_21'] < p['ema_50']:
            trend_score = -1  # Strong downtrend
        
        # 2. Mean Reversion Score (-1 to +1)
        mean_rev_score = 0
        vwap_dev = (close - p['vwap']) / p['vwap']
        
        if close < p['vwap_lower'] and trend_score > 0:
            mean_rev_score = 0.8  # Oversold in uptrend = strong buy
        elif close > p['vwap_upper'] and trend_score < 0:
            mean_rev_score = -0.8  # Overbought in downtrend = strong sell
        elif close < p['vwap'] * 0.995 and trend_score > 0:
            mean_rev_score = 0.5  # Slight dip in uptrend
        elif close > p['vwap'] * 1.005 and trend_score < 0:
            mean_rev_score = -0.5  # Slight rally in downtrend
        
        # 3. Momentum Score
        momentum_score = 0
        if len(p['returns']) >= 10:
            recent_returns = p['returns'][-5:]
            avg_return = sum(recent_returns) / len(recent_returns)
            if avg_return > 0.001:
                momentum_score = 1
            elif avg_return < -0.001:
                momentum_score = -1
        
        # === COMBINED ALPHA SCORE ===
        # Weight: Trend 40%, Mean Rev 40%, Momentum 20%
        p['alpha_score'] = (trend_score * 0.4 + mean_rev_score * 0.4 + momentum_score * 0.2)
        p['trend_score'] = trend_score
        p['mean_rev_score'] = mean_rev_score
        
        # === POSITION SIZING & ENTRY ===
        
        # Only trade if strong signal (|score| > 0.5)
        if abs(p['alpha_score']) < 0.5:
            return
        
        # Determine direction
        direction = 1 if p['alpha_score'] > 0 else -1
        
        # Check exposure limits
        target_position_size = info['alloc'] * self.target_gross_exposure * nav
        
        # Adjust for net exposure limit
        if direction == 1 and net_exp > self.max_net_exposure:
            target_position_size *= 0.5  # Reduce long additions
        elif direction == -1 and net_exp < -self.max_net_exposure:
            target_position_size *= 0.5  # Reduce short additions
        
        # Check single position limit
        current_position_value = abs(p['quantity'] * close)
        if current_position_value + target_position_size > nav * self.max_single_position:
            target_position_size = nav * self.max_single_position - current_position_size
        
        # Calculate quantity
        quantity = int(target_position_size / close)
        
        # Risk-based sizing: Max 2% risk per position
        stop_dist = p['atr'] * 2  # 2 ATR stop
        risk_per_share = stop_dist
        max_risk_quantity = int((nav * 0.02) / risk_per_share) if risk_per_share > 0 else quantity
        
        quantity = min(quantity, max_risk_quantity, 500)
        
        if quantity < 10:
            return
        
        # === EXECUTION ===
        self._execute_trade(symbol, close, direction, quantity, stop_dist, nav, p['alpha_score'])

    def _execute_trade(self, symbol, price, direction, quantity, stop_dist, nav, alpha):
        """Execute trade with full logging"""
        p = self.positions[symbol]
        
        # If reversing position, liquidate first
        if p['quantity'] != 0 and p['direction'] != direction:
            self.Liquidate(symbol)
            p['quantity'] = 0
        
        # Update position
        p['direction'] = direction
        p['entry'] = price
        p['stop'] = price - (stop_dist * direction)
        p['target'] = price + (stop_dist * 2 * direction)  # 1:2 R:R
        p['quantity'] = quantity
        p['trades_today'] += 1
        self.daily_trades += 1
        
        notional = quantity * price
        weight = notional / nav
        
        side = "🟢 LONG" if direction == 1 else "🔴 SHORT"
        
        self.Log(f"{side} #{self.daily_trades} | {self.universe[symbol]['name']}")
        self.Log(f"   Alpha: {alpha:+.2f} | Qty: {quantity} | ₹{notional:,.0f} ({weight*100:.1f}%)")
        self.Log(f"   Entry: ₹{price:.2f} | Stop: ₹{p['stop']:.2f} | Target: ₹{p['target']:.2f}")
        
        self.SetHoldings(symbol, weight if direction == 1 else -weight)

    def _manage_position(self, symbol, price, time_only, nav, atr):
        """Sophisticated position management"""
        p = self.positions[symbol]
        
        if p['quantity'] == 0:
            return
        
        unrealized = (price - p['entry']) * p['direction'] * p['quantity']
        unrealized_pct = (price - p['entry']) / p['entry'] * 100 * p['direction']
        
        # Calculate R-multiple
        risk_per_share = abs(p['entry'] - p['stop'])
        current_r = ((price - p['entry']) * p['direction']) / risk_per_share if risk_per_share > 0 else 0
        
        exit_reason = None
        
        # 1. Hard stop
        if p['direction'] == 1 and price <= p['stop']:
            exit_reason = "STOP"
        elif p['direction'] == -1 and price >= p['stop']:
            exit_reason = "STOP"
        
        # 2. Target
        if p['direction'] == 1 and price >= p['target']:
            exit_reason = "TARGET"
        elif p['direction'] == -1 and price <= p['target']:
            exit_reason = "TARGET"
        
        # 3. Trailing stop (institutional style)
        if current_r > 1.5:
            # Move stop to breakeven + 1R
            if p['direction'] == 1:
                new_stop = max(p['stop'], p['entry'] + risk_per_share)
                p['stop'] = new_stop
            else:
                new_stop = min(p['stop'], p['entry'] - risk_per_share)
                p['stop'] = new_stop
        
        # 4. Time decay exit (flat after 20 mins)
        # (Would need timestamp tracking)
        
        # 5. Alpha decay exit (signal reversed)
        if p['alpha_score'] * p['direction'] < -0.3 and current_r > 0.5:
            exit_reason = "ALPHA_REVERSAL"
        
        # 6. End of day
        if time_only >= datetime.time(15, 15):
            exit_reason = "EOD"
        
        if exit_reason:
            realized = unrealized
            self.daily_pnl += realized
            
            self.Liquidate(symbol)
            p['quantity'] = 0
            
            emoji = "✅" if realized > 0 else "❌"
            self.Log(f"{emoji} EXIT | {self.universe[symbol]['name']} | {exit_reason}")
            self.Log(f"   P&L: ₹{realized:+,.0f} ({unrealized_pct:+.2f}%) | R:{current_r:.1f}")
            self.Log(f"   Daily P&L: ₹{self.daily_pnl:+,.0f} ({self.daily_pnl/nav*100:+.2f}%)")

    def _calculate_exposures(self, nav):
        """Calculate portfolio exposures"""
        long_value = 0
        short_value = 0
        
        for symbol in self.symbols:
            p = self.positions[symbol]
            if p['quantity'] > 0:
                long_value += p['quantity'] * p['prices'][-1] if p['prices'] else 0
            elif p['quantity'] < 0:
                short_value += abs(p['quantity']) * p['prices'][-1] if p['prices'] else 0
        
        gross = (long_value + short_value) / nav if nav > 0 else 0
        net = (long_value - short_value) / nav if nav > 0 else 0
        
        return gross, net, long_value / nav, short_value / nav

    def _daily_reset(self, date, nav):
        """Reset daily tracking"""
        self.last_date = date
        self.daily_pnl = 0
        self.daily_trades = 0
        self.trading_enabled = True
        
        for symbol in self.symbols:
            p = self.positions[symbol]
            p['trades_today'] = 0
            p['alpha_score'] = 0
            p['prices'] = []
            p['volumes'] = []
            p['returns'] = []
            p['ema_9'] = 0
            p['ema_21'] = 0
            p['ema_50'] = 0
        
        self.Log("═" * 50)
        self.Log(f"📅 NEW DAY: {date} | NAV: ₹{nav:,.0f}")
        self.Log("═" * 50)

    def _liquidate_all(self):
        """Emergency liquidation"""
        for symbol in self.symbols:
            if self.positions[symbol]['quantity'] != 0:
                self.Liquidate(symbol)
                self.positions[symbol]['quantity'] = 0

    def _market_close_procedure(self, nav, time_only):
        """End of day procedures"""
        self.Log(f"🏁 MARKET CLOSE | Trades: {self.daily_trades} | P&L: ₹{self.daily_pnl:+,.0f}")
        
        for symbol in self.symbols:
            p = self.positions[symbol]
            if p['quantity'] != 0:
                self.Liquidate(symbol)
                p['quantity'] = 0
        
        # Log performance
        if len(self.equity_curve) > 0:
            self.equity_curve.append(nav)
            returns = [(self.equity_curve[i] - self.equity_curve[i-1]) / self.equity_curve[i-1] 
                      for i in range(1, len(self.equity_curve))]
            if returns:
                sharpe = (sum(returns) / len(returns)) / (statistics.stdev(returns) + 0.0001) * (252 ** 0.5)
                self.Log(f"📊 Sharpe Ratio: {sharpe:.2f}")