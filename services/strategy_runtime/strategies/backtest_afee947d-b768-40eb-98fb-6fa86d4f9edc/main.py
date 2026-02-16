from quant_sdk import QCAlgorithm, Resolution
import datetime

class HighFrequencyIntraday(QCAlgorithm):
    """
    High-Frequency Multi-Trade Intraday Strategy
    Targets: 5-10 trades/day, 0.5-1% per trade, 3-5% daily return
    """
    
    def Initialize(self):
        self.SetCash(100000)
        self.SetStartDate(2023, 1, 1)
        self.SetEndDate(2024, 12, 31)
        
        # Aggressive Risk Settings
        self.max_risk_per_trade = 0.02  # 2% risk per trade
        self.max_trades_per_day = 10    # Hard limit
        self.leverage = 3.0
        self.SetLeverage(self.leverage)
        
        # Trading Hours
        self.market_open = datetime.time(9, 15)
        self.market_close = datetime.time(15, 25)
        self.last_entry = datetime.time(15, 00)  # No new trades after 3 PM
        
        # Single high-liquid stock for maximum fills
        self.symbol = "NSE_EQ|INE002A01018"  # Reliance only
        self.AddEquity(self.symbol, Resolution.Tick)
        
        # State
        self.daily_trades = 0
        self.last_trade_day = None
        self.in_position = False
        self.position_direction = 0
        self.entry_price = 0
        self.stop_loss = 0
        self.target = 0
        self.quantity = 0
        
        # VWAP & Bands
        self.vwap = 0
        self.vwap_sum_pv = 0
        self.vwap_sum_vol = 0
        self.vwap_std = 0  # Standard deviation for bands
        self.prices_for_std = []
        
        # 5-min bar for signals
        self.current_bar = None
        self.prev_bar_close = None
        
        self.Log("🚀 HIGH-FREQUENCY STRATEGY STARTED")
        
    def OnData(self, data):
        if not data.ContainsKey(self.symbol):
            return
            
        tick = data[self.symbol]
        price = tick.Price
        qty = getattr(tick, 'Quantity', 1)
        
        # Time handling
        current_time = data.Time if hasattr(data, 'Time') else datetime.datetime.now()
        time_only = current_time.time() if isinstance(current_time, datetime.datetime) else current_time
        current_date = current_time.date() if isinstance(current_time, datetime.datetime) else datetime.date.today()
        
        # Daily reset
        if self.last_trade_day != current_date:
            self.daily_trades = 0
            self.last_trade_day = current_date
            self.vwap_sum_pv = 0
            self.vwap_sum_vol = 0
            self.vwap_std = 0
            self.prices_for_std = []
            self.prev_bar_close = None
            self.Log(f"📅 NEW DAY: {current_date} | Trades reset")
        
        # Skip if max trades reached or after cutoff
        if self.daily_trades >= self.max_trades_per_day or time_only > self.last_entry:
            if self.in_position:
                self._exit_position(price, "MAX_TRADES_DAY_END")
            return
        
        # Market close - square off
        if time_only >= self.market_close:
            if self.in_position:
                self._exit_position(price, "MARKET_CLOSE")
            return
        
        # Update VWAP
        self.vwap_sum_pv += price * qty
        self.vwap_sum_vol += qty
        if self.vwap_sum_vol > 0:
            self.vwap = self.vwap_sum_pv / self.vwap_sum_vol
        
        # Update standard deviation calculation (rolling 100 ticks)
        self.prices_for_std.append(price)
        if len(self.prices_for_std) > 100:
            self.prices_for_std.pop(0)
        
        # Calculate VWAP bands
        if len(self.prices_for_std) >= 20:
            mean = sum(self.prices_for_std) / len(self.prices_for_std)
            variance = sum((p - mean) ** 2 for p in self.prices_for_std) / len(self.prices_for_std)
            self.vwap_std = variance ** 0.5
        
        # Build 3-minute bars (faster signals than 5-min)
        if self.current_bar is None:
            self.current_bar = {
                'open': price, 'high': price, 'low': price,
                'close': price, 'volume': qty,
                'start': current_time
            }
        
        bar_elapsed = (current_time - self.current_bar['start']).total_seconds() if isinstance(current_time, datetime.datetime) else 0
        
        if bar_elapsed >= 180:  # 3 minutes
            # Finalize bar
            self.current_bar['close'] = price
            self.current_bar['volume'] += qty
            
            # Process signal on completed bar
            if not self.in_position and self.prev_bar_close is not None:
                self._check_entry(self.current_bar, price, time_only)
            
            # Store for next comparison
            self.prev_bar_close = self.current_bar['close']
            
            # Reset bar
            self.current_bar = {
                'open': price, 'high': price, 'low': price,
                'close': price, 'volume': qty,
                'start': current_time
            }
        else:
            # Update current bar
            self.current_bar['high'] = max(self.current_bar['high'], price)
            self.current_bar['low'] = min(self.current_bar['low'], price)
            self.current_bar['close'] = price
            self.current_bar['volume'] += qty
        
        # Manage existing position on every tick
        if self.in_position:
            self._manage_position(price, time_only)

    def _check_entry(self, bar, current_price, time_only):
        """Check for entry signals - MULTIPLE STRATEGIES"""
        
        # Skip first 15 mins (let market settle)
        if time_only < datetime.time(9, 30):
            return
        
        # Calculate indicators
        vwap_upper = self.vwap + (self.vwap_std * 1.5) if self.vwap_std > 0 else self.vwap * 1.002
        vwap_lower = self.vwap - (self.vwap_std * 1.5) if self.vwap_std > 0 else self.vwap * 0.998
        
        bar_range = bar['high'] - bar['low']
        bar_range_pct = bar_range / bar['low'] if bar['low'] > 0 else 0
        
        close = bar['close']
        prev_close = self.prev_bar_close
        
        # Skip if no previous bar or VWAP not ready
        if prev_close is None or self.vwap == 0:
            return
        
        # === STRATEGY 1: VWAP Mean Reversion ===
        # Price hits upper band, short; hits lower band, long
        mr_long = current_price < vwap_lower and close > bar['low'] + bar_range * 0.3
        mr_short = current_price > vwap_upper and close < bar['high'] - bar_range * 0.3
        
        # === STRATEGY 2: Momentum Breakout ===
        # Strong close in direction of mini-trend
        mom_long = (close > prev_close * 1.003 and 
                   close > self.vwap and 
                   bar_range_pct > 0.001)
        mom_short = (close < prev_close * 0.997 and 
                    close < self.vwap and 
                    bar_range_pct > 0.001)
        
        # === STRATEGY 3: Pullback to VWAP ===
        # Price was away from VWAP, now returning
        pb_long = (abs(current_price - self.vwap) / self.vwap < 0.001 and 
                  prev_close < self.vwap * 0.997)
        pb_short = (abs(current_price - self.vwap) / self.vwap < 0.001 and 
                   prev_close > self.vwap * 1.003)
        
        # Priority: Mean Reversion > Pullback > Momentum
        if mr_long:
            self._enter_position(current_price, 1, "MR_LONG")
        elif mr_short:
            self._enter_position(current_price, -1, "MR_SHORT")
        elif pb_long:
            self._enter_position(current_price, 1, "PB_LONG")
        elif pb_short:
            self._enter_position(current_price, -1, "PB_SHORT")
        elif mom_long:
            self._enter_position(current_price, 1, "MOM_LONG")
        elif mom_short:
            self._enter_position(current_price, -1, "MOM_SHORT")

    def _enter_position(self, price, direction, signal_type):
        """Enter position with proper sizing"""
        
        portfolio_value = self.Portfolio['TotalPortfolioValue']
        risk_amount = portfolio_value * self.max_risk_per_trade
        
        # Tighter stops for more trades (0.4% - 0.6%)
        if "MR" in signal_type:
            stop_pct = 0.004  # Tight for mean reversion
        elif "PB" in signal_type:
            stop_pct = 0.005  # Medium for pullback
        else:
            stop_pct = 0.006  # Wider for momentum
        
        stop_distance = price * stop_pct
        
        # Ensure minimum ₹5 stop for large caps
        if stop_distance < 5:
            stop_distance = 5
        
        quantity = int(risk_amount / stop_distance)
        
        # Minimum position: ₹15,000 notional (sizable!)
        min_notional = 15000
        if quantity * price < min_notional:
            quantity = int(min_notional / price) + 1
        
        # Cap at leverage
        max_qty = int((portfolio_value * self.leverage * 0.8) / price)
        quantity = min(quantity, max_qty)
        
        if quantity < 1:
            return
        
        self.in_position = True
        self.position_direction = direction
        self.entry_price = price
        self.stop_loss = price - (stop_distance * direction)
        self.target = price + (stop_distance * 1.5 * direction)  # 1:1.5 R:R (higher win rate)
        self.quantity = quantity
        
        self.daily_trades += 1
        
        side = "🟢 LONG" if direction == 1 else "🔴 SHORT"
        notional = quantity * price
        
        self.Log(f"{side} #{self.daily_trades} | Signal: {signal_type} | "
                f"{quantity} shares @ ₹{price:.2f} | "
                f"Notional: ₹{notional:,.0f} | "
                f"Stop: ₹{self.stop_loss:.2f} | "
                f"Target: ₹{self.target:.2f}")
        
        weight = notional / portfolio_value
        self.SetHoldings(self.symbol, weight if direction == 1 else -weight)

    def _manage_position(self, price, time_only):
        """Manage open position with dynamic exits"""
        
        unrealized = (price - self.entry_price) * self.position_direction
        unrealized_pct = (unrealized / self.entry_price) * 100
        
        # Calculate R-multiple
        stop_dist = abs(self.entry_price - self.stop_loss)
        current_r = unrealized / stop_dist if stop_dist > 0 else 0
        
        exit_reason = None
        
        # 1. Hard stop
        if self.position_direction == 1 and price <= self.stop_loss:
            exit_reason = "STOP"
        elif self.position_direction == -1 and price >= self.stop_loss:
            exit_reason = "STOP"
        
        # 2. Target
        if self.position_direction == 1 and price >= self.target:
            exit_reason = "TARGET"
        elif self.position_direction == -1 and price <= self.target:
            exit_reason = "TARGET"
        
        # 3. Trailing stop (move to breakeven at 0.8R, trail at 1.5R)
        if current_r >= 0.8 and self.stop_loss != self.entry_price:
            if self.position_direction == 1:
                new_stop = max(self.stop_loss, self.entry_price * 1.001)
                if current_r >= 1.5:
                    new_stop = max(new_stop, self.entry_price + stop_dist * 0.8)
                self.stop_loss = new_stop
            else:
                new_stop = min(self.stop_loss, self.entry_price * 0.999)
                if current_r >= 1.5:
                    new_stop = min(new_stop, self.entry_price - stop_dist * 0.8)
                self.stop_loss = new_stop
        
        # 4. Time stop (exit if flat for 10 mins)
        # (Would need entry time tracking - simplified here)
        
        # 5. VWAP crossover (exit if wrong side)
        if self.position_direction == 1 and price < self.vwap * 0.998 and current_r > 0.3:
            exit_reason = "VWAP_CROSS"
        elif self.position_direction == -1 and price > self.vwap * 1.002 and current_r > 0.3:
            exit_reason = "VWAP_CROSS"
        
        if exit_reason:
            self._exit_position(price, exit_reason)

    def _exit_position(self, price, reason):
        """Exit position and log P&L"""
        
        if not self.in_position:
            return
        
        pnl_ticks = (price - self.entry_price) * self.position_direction
        pnl_rupees = pnl_ticks * self.quantity
        pnl_pct = (pnl_ticks / self.entry_price) * 100
        
        self.Liquidate(self.symbol)
        
        emoji = "✅" if pnl_rupees > 0 else "❌"
        self.Log(f"{emoji} EXIT #{self.daily_trades} | {reason} | "
                f"@ ₹{price:.2f} | P&L: ₹{pnl_rupees:+,.0f} ({pnl_pct:+.2f}%)")
        
        self.in_position = False
        self.position_direction = 0