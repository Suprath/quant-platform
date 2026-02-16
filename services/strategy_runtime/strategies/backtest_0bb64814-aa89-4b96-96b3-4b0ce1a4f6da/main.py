from quant_sdk import QCAlgorithm, Resolution
import datetime
import statistics

class InstitutionalStatArbMomentum(QCAlgorithm):
    """
    Institutional-Grade Strategy: Statistical Arbitrage + Momentum
    Based on: Two Sigma, Citadel, and Indian HFT firm approaches
    
    Core Logic:
    1. PAIRS TRADING: Long Reliance / Short HDFC Bank (or vice versa) when spread diverges
    2. MOMENTUM IGNITION: Detect volume spikes + price momentum for directional trades
    3. MARKET MAKING: Capture spread on high-liquid stocks
    """
    
    def Initialize(self):
        self.SetCash(100000)
        self.SetStartDate(2023, 1, 1)
        self.SetEndDate(2024, 12, 31)
        
        # === INSTITUTIONAL PARAMETERS ===
        self.leverage = 3.0
        self.SetLeverage(self.leverage)
        
        # Risk Management (Institutional Grade)
        self.max_gross_exposure = 2.5    # 250% of capital
        self.max_net_exposure = 0.60     # 60% directional bias max
        self.max_single_trade = 0.50     # 50% in one trade
        self.daily_var_limit = 0.025     # 2.5% daily VaR
        
        # PAIRS CONFIGURATION (Cointegrated Indian Large Caps)
        # Reliance-HDFC Bank pair: historically 0.85 correlation
        self.pair_long = "NSE_EQ|INE002A01018"   # Reliance (Alpha generator)
        self.pair_short = "NSE_EQ|INE040A01034"  # HDFC Bank (Hedge)
        self.hedge_ratio = 1.2  # 1.2 HDFC shares per 1 Reliance share
        
        # MOMENTUM UNIVERSE
        self.momentum_symbols = [
            "NSE_EQ|INE002A01018",  # Reliance
            "NSE_EQ|INE238A01034",  # ICICI Bank
        ]
        
        # Subscribe to all
        all_symbols = list(set([self.pair_long, self.pair_short] + self.momentum_symbols))
        self.data = {}
        
        for symbol in all_symbols:
            self.AddEquity(symbol, Resolution.Tick)
            self.data[symbol] = {
                'prices': [], 'volumes': [], 'vwap': 0,
                'vwap_pv': 0, 'vwap_vol': 0,
                'ema_9': 0, 'ema_21': 0,
                'in_position': False, 'direction': 0,
                'entry': 0, 'stop': 0, 'target': 0, 'qty': 0,
                'trades_today': 0
            }
        
        # Pair trading state
        self.pair_spread_history = []
        self.pair_zscore = 0
        self.pair_position = 0  # 0=flat, 1=long spread, -1=short spread
        
        # Tracking
        self.last_date = None
        self.total_trades = 0
        self.daily_pnl = 0
        
        self.Log("🏛️ INSTITUTIONAL STAT-ARB + MOMENTUM STRATEGY")
        self.Log(f"💰 AUM: ₹{self.Portfolio.Cash:,.0f}")
        self.Log(f"⚡ Leverage: {self.leverage}x")
        self.Log(f"📊 Pair: Reliance vs HDFC Bank (Hedge Ratio: {self.hedge_ratio})")
        
    def OnData(self, data):
        current_time = data.Time if hasattr(data, 'Time') else datetime.datetime.now()
        time_only = current_time.time() if isinstance(current_time, datetime.datetime) else current_time
        current_date = current_time.date() if isinstance(current_time, datetime.datetime) else datetime.date.today()
        
        nav = self.Portfolio.TotalPortfolioValue
        
        # Daily reset
        if self.last_date != current_date:
            self._daily_reset(current_date, nav)
        
        # Market close procedures
        if time_only >= datetime.time(15, 20):
            self._market_close(nav, time_only)
            return
        
        # Update all price data
        for symbol in self.data.keys():
            if not data.ContainsKey(symbol):
                continue
            
            tick = data[symbol]
            price = tick.Price
            qty = getattr(tick, 'Quantity', 1)
            
            d = self.data[symbol]
            
            # Update VWAP
            d['vwap_pv'] += price * qty
            d['vwap_vol'] += qty
            if d['vwap_vol'] > 0:
                d['vwap'] = d['vwap_pv'] / d['vwap_vol']
            
            # Update prices
            d['prices'].append(price)
            d['volumes'].append(qty)
            if len(d['prices']) > 50:
                d['prices'].pop(0)
                d['volumes'].pop(0)
            
            # Update EMAs
            if len(d['prices']) >= 21:
                if d['ema_9'] == 0:
                    d['ema_9'] = sum(d['prices'][-9:]) / 9
                    d['ema_21'] = sum(d['prices'][-21:]) / 21
                else:
                    d['ema_9'] = (price - d['ema_9']) * (2/10) + d['ema_9']
                    d['ema_21'] = (price - d['ema_21']) * (2/22) + d['ema_21']
        
        # === STRATEGY 1: PAIRS TRADING (Every 5 minutes) ===
        if time_only.minute % 5 == 0 and time_only.second < 5:
            self._pairs_trading_logic(nav, time_only)
        
        # === STRATEGY 2: MOMENTUM IGNITION (Continuous) ===
        for symbol in self.momentum_symbols:
            if self.data[symbol]['in_position']:
                self._manage_momentum(symbol, nav, time_only)
            elif time_only.minute % 15 == 0 and time_only.second < 5:
                # Check for momentum entry every 15 mins
                self._momentum_entry(symbol, nav, time_only)
        
        # === STRATEGY 3: VWAP MEAN REVERSION (Scalping) ===
        for symbol in self.momentum_symbols:
            if not self.data[symbol]['in_position']:
                self._vwap_scalp_entry(symbol, nav, time_only)

    def _pairs_trading_logic(self, nav, time_only):
        """Statistical Arbitrage: Trade the spread between correlated pairs"""
        long_data = self.data[self.pair_long]
        short_data = self.data[self.pair_short]
        
        # Need data
        if len(long_data['prices']) < 20 or len(short_data['prices']) < 20:
            return
        
        # Calculate spread: Reliance - (HDFC * hedge_ratio)
        current_spread = long_data['prices'][-1] - (short_data['prices'][-1] * self.hedge_ratio)
        
        # Update history
        self.pair_spread_history.append(current_spread)
        if len(self.pair_spread_history) > 50:
            self.pair_spread_history.pop(0)
        
        # Need enough history
        if len(self.pair_spread_history) < 30:
            return
        
        # Calculate Z-score (how many std devs from mean)
        mean_spread = statistics.mean(self.pair_spread_history)
        std_spread = statistics.stdev(self.pair_spread_history) if len(self.pair_spread_history) > 1 else 1
        
        if std_spread == 0:
            return
            
        self.pair_zscore = (current_spread - mean_spread) / std_spread
        
        # ENTRY LOGIC
        # Z-score > 1.5: Spread too wide, short Reliance / long HDFC
        # Z-score < -1.5: Spread too narrow, long Reliance / short HDFC
        
        if self.pair_position == 0:  # Flat
            if self.pair_zscore > 1.5:
                # Enter short spread
                self._enter_pair_trade(-1, nav, time_only)
            elif self.pair_zscore < -1.5:
                # Enter long spread
                self._enter_pair_trade(1, nav, time_only)
        
        # EXIT LOGIC
        elif self.pair_position == 1:  # Long spread
            if self.pair_zscore > -0.5:  # Reverted to mean
                self._exit_pair_trade(nav, time_only, "MEAN_REVERSION")
        elif self.pair_position == -1:  # Short spread
            if self.pair_zscore < 0.5:  # Reverted to mean
                self._exit_pair_trade(nav, time_only, "MEAN_REVERSION")

    def _enter_pair_trade(self, direction, nav, time_only):
        """Enter pairs trade: direction 1 = long Reliance/short HDFC, -1 = opposite"""
        self.pair_position = direction
        
        # Position sizing: 40% of capital per leg
        leg_value = nav * 0.40 * self.leverage
        
        long_qty = int(leg_value / self.data[self.pair_long]['prices'][-1])
        short_qty = int(leg_value / self.data[self.pair_short]['prices'][-1])
        
        if direction == 1:
            # Long Reliance, Short HDFC
            self.SetHoldings(self.pair_long, 0.40 * self.leverage)
            self.SetHoldings(self.pair_short, -0.40 * self.leverage)
            self.Log(f"🔗 PAIR LONG | Reliance: {long_qty} | HDFC: -{short_qty} | Z: {self.pair_zscore:.2f}")
        else:
            # Short Reliance, Long HDFC
            self.SetHoldings(self.pair_long, -0.40 * self.leverage)
            self.SetHoldings(self.pair_short, 0.40 * self.leverage)
            self.Log(f"🔗 PAIR SHORT | Reliance: -{long_qty} | HDFC: {short_qty} | Z: {self.pair_zscore:.2f}")
        
        self.total_trades += 2

    def _exit_pair_trade(self, nav, time_only, reason):
        """Exit pairs trade"""
        self.Liquidate(self.pair_long)
        self.Liquidate(self.pair_short)
        self.pair_position = 0
        
        self.Log(f"🔗 PAIR EXIT | {reason} | Z: {self.pair_zscore:.2f}")
        self.total_trades += 2

    def _momentum_entry(self, symbol, nav, time_only):
        """Momentum Ignition Strategy: Detect volume + price surge"""
        d = self.data[symbol]
        
        if d['in_position'] or d['trades_today'] >= 3:
            return
        
        # Need data
        if len(d['prices']) < 20 or len(d['volumes']) < 20:
            return
        
        # Calculate momentum metrics
        price_change = (d['prices'][-1] - d['prices'][-5]) / d['prices'][-5] * 100
        avg_volume = sum(d['volumes'][-10:]) / 10
        current_volume = d['volumes'][-1]
        volume_spike = current_volume > avg_volume * 2.0  # 2x volume
        
        # Momentum ignition: Price move + Volume spike + EMA alignment
        strong_up = price_change > 0.3 and volume_spike and d['ema_9'] > d['ema_21']
        strong_down = price_change < -0.3 and volume_spike and d['ema_9'] < d['ema_21']
        
        if strong_up:
            self._enter_momentum(symbol, 1, "MOM_IGNITE", nav)
        elif strong_down:
            self._enter_momentum(symbol, -1, "MOM_IGNITE", nav)

    def _enter_momentum(self, symbol, direction, signal, nav):
        """Enter momentum trade"""
        d = self.data[symbol]
        
        price = d['prices'][-1]
        
        # Size: 30% of capital
        notional = nav * 0.30 * self.leverage
        qty = int(notional / price)
        qty = min(qty, 300)
        
        if qty < 10:
            return
        
        d['in_position'] = True
        d['direction'] = direction
        d['entry'] = price
        d['stop'] = price * (0.985 if direction == 1 else 1.015)  # 1.5% stop
        d['target'] = price * (1.025 if direction == 1 else 0.975)  # 2.5% target
        d['qty'] = qty
        d['trades_today'] += 1
        self.total_trades += 1
        
        side = "🚀 LONG" if direction == 1 else "🚀 SHORT"
        self.Log(f"{side} MOMENTUM | {symbol[-6:]} | ₹{price:.2f} | Qty: {qty}")
        
        weight = (qty * price) / nav
        self.SetHoldings(symbol, weight if direction == 1 else -weight)

    def _manage_momentum(self, symbol, nav, time_only):
        """Manage momentum position with trailing"""
        d = self.data[symbol]
        
        price = d['prices'][-1]
        unrealized = (price - d['entry']) * d['direction'] * d['qty']
        unrealized_pct = (price - d['entry']) / d['entry'] * 100 * d['direction']
        
        exit_reason = None
        
        # Stop
        if d['direction'] == 1 and price <= d['stop']:
            exit_reason = "STOP"
        elif d['direction'] == -1 and price >= d['stop']:
            exit_reason = "STOP"
        
        # Target
        if d['direction'] == 1 and price >= d['target']:
            exit_reason = "TARGET"
        elif d['direction'] == -1 and price <= d['target']:
            exit_reason = "TARGET"
        
        # Trailing: Move stop to breakeven at 1% profit
        if unrealized_pct > 1.0:
            if d['direction'] == 1:
                d['stop'] = max(d['stop'], d['entry'] * 1.001)
            else:
                d['stop'] = min(d['stop'], d['entry'] * 0.999)
        
        # Time cut (10 mins)
        if time_only.minute % 15 >= 10 and unrealized_pct < 0.5:
            exit_reason = "TIME_CUT"
        
        if exit_reason:
            self.Liquidate(symbol)
            d['in_position'] = False
            
            emoji = "✅" if unrealized > 0 else "❌"
            self.Log(f"{emoji} MOM EXIT | {symbol[-6:]} | {exit_reason} | ₹{unrealized:+,.0f}")
            
            self.daily_pnl += unrealized

    def _vwap_scalp_entry(self, symbol, nav, time_only):
        """VWAP Scalping: Quick mean reversion to VWAP"""
        d = self.data[symbol]
        
        if d['in_position'] or d['trades_today'] >= 3:
            return
        
        if len(d['prices']) < 10 or d['vwap'] == 0:
            return
        
        price = d['prices'][-1]
        vwap_dev = (price - d['vwap']) / d['vwap'] * 100
        
        # Long: Price 0.4% below VWAP
        if vwap_dev < -0.4 and not d['in_position']:
            self._enter_momentum(symbol, 1, "VWAP_SCALP", nav)
        # Short: Price 0.4% above VWAP
        elif vwap_dev > 0.4 and not d['in_position']:
            self._enter_momentum(symbol, -1, "VWAP_SCALP", nav)

    def _daily_reset(self, date, nav):
        """Reset daily tracking"""
        self.last_date = date
        self.daily_pnl = 0
        
        for symbol in self.data.keys():
            d = self.data[symbol]
            d['trades_today'] = 0
            d['in_position'] = False
        
        self.pair_spread_history = []
        self.pair_position = 0
        
        self.Log(f"📅 NEW DAY: {date} | NAV: ₹{nav:,.0f}")

    def _market_close(self, nav, time_only):
        """Close all positions"""
        for symbol in self.data.keys():
            if self.data[symbol]['in_position']:
                self.Liquidate(symbol)
                self.data[symbol]['in_position'] = False
        
        if self.pair_position != 0:
            self.Liquidate(self.pair_long)
            self.Liquidate(self.pair_short)
            self.pair_position = 0
        
        pnl = nav - 100000
        self.Log(f"🏁 CLOSE | P&L: ₹{pnl:+,.0f} ({pnl/1000:.2f}%) | Trades: {self.total_trades}")