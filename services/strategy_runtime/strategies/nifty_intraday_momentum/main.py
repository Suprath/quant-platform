from quant_sdk import QCAlgorithm, Resolution
from datetime import time
import numpy as np

class NiftyIntradayMomentum(QCAlgorithm):
    """
    Multi-Factor Intraday Momentum Strategy for Indian Markets
    Compatible with KIRA's event-driven backtesting engine.

    Logic:
    1. Opening Range Breakout (ORB): First 15-minute range establishes bias
    2. Volume Confirmation: Breakout must be accompanied by 1.5x average volume
    3. EMA Trend Filter: Only trade in direction of 9/21 EMA alignment
    4. Dynamic Position Sizing: Based on manual ATR volatility calculation
    5. Hard Stop-Loss: 1.5x ATR or automatic 3:20 PM engine square-off

    KIRA Compatibility Fixes Applied:
    - Removed self.Schedule.On() — not supported; time checks are in OnData instead.
    - Removed self.MAX() / self.MIN() — not in SDK; ORB tracking is done manually.
    - Replaced self.ATR() — not wired in SDK; replaced with manual ATR window.
    - Fixed data.Time -> self.Time (injected by engine on every tick).
    """

    def Initialize(self):
        # Capital (used as metadata; actual capital is set in the backtest UI)
        self.SetCash(500000)  # Rs.5L - realistic for Indian retail
        self.SetStartDate(2023, 1, 1)
        self.SetEndDate(2024, 12, 31)

        # Leverage for Intraday MIS
        self.SetLeverage(5.0)  # 5x intraday leverage

        # Universe: Top 10 Nifty 50 liquid stocks
        self.symbols = [
            "NSE_EQ|INE002A01018",  # Reliance
            "NSE_EQ|INE467B01029",  # TCS
            "NSE_EQ|INE040A01034",  # HDFC Bank
            "NSE_EQ|INE090A01021",  # ICICI Bank
            "NSE_EQ|INE009A01021",  # Infosys
            "NSE_EQ|INE154A01025",  # ITC
            "NSE_EQ|INE238A01034",  # Kotak Mahindra
            "NSE_EQ|INE062A01020",  # L&T
            "NSE_EQ|INE917I01010",  # Axis Bank
            "NSE_EQ|INE669E01016",  # Bajaj Finance
        ]

        for sym in self.symbols:
            self.AddEquity(sym, Resolution.Minute)

        # Strategy Parameters
        self.orb_minutes = 15           # Opening range period
        self.volume_lookback = 20       # Volume SMA period
        self.atr_period = 14            # ATR window size
        self.ema_fast_period = 9
        self.ema_slow_period = 21
        self.volume_threshold = 1.5     # Volume breakout multiplier
        self.risk_per_trade = 0.01      # 1% risk per trade
        self.max_positions = 3          # Max concurrent positions

        # ORB tracking (reset each day)
        self.orb_high = {}
        self.orb_low = {}
        self.orb_volume_avg = {}
        self._orb_reset_done = {}       # Track if today's reset has fired
        self._last_reset_date = {}

        # Trade state tracking
        self.entry_price = {}
        self.stop_loss = {}
        self.target_price = {}
        self.position_direction = {}    # 1=long, -1=short, 0=flat

        # Manual ATR windows (list of recent true ranges per symbol)
        self._atr_windows = {sym: [] for sym in self.symbols}

        # SDK Indicators (SMA for volume, EMA for trend)
        self.indicators = {}
        for sym in self.symbols:
            self.indicators[sym] = {
                'sma_volume': self.SMA(sym, self.volume_lookback, Resolution.Minute),
                'ema_fast':   self.EMA(sym, self.ema_fast_period, Resolution.Minute),
                'ema_slow':   self.EMA(sym, self.ema_slow_period, Resolution.Minute),
            }

        self.Log("Strategy Initialized - Nifty Intraday Momentum v1.0 (KIRA Compatible)")

    # ─────────────────────────────────────────────
    # Manual ATR helper (replaces self.ATR() SDK call)
    # ─────────────────────────────────────────────
    def _get_atr(self, sym, bar):
        """Calculate Average True Range from a rolling window of candle ranges."""
        self._atr_windows[sym].append(bar.High - bar.Low)
        if len(self._atr_windows[sym]) > self.atr_period:
            self._atr_windows[sym].pop(0)
        if len(self._atr_windows[sym]) < self.atr_period:
            return 0.0
        return float(np.mean(self._atr_windows[sym]))

    # ─────────────────────────────────────────────
    # ORB Reset (replaces self.Schedule.On at 9:15)
    # ─────────────────────────────────────────────
    def _reset_orb_if_new_day(self, sym, today):
        """Reset Opening Range levels once per calendar day, at market open."""
        if self._last_reset_date.get(sym) != today:
            self.orb_high[sym] = None
            self.orb_low[sym] = None
            self.orb_volume_avg[sym] = None
            self._last_reset_date[sym] = today
            self.Log(f"ORB reset for {sym} on {today}")

    # ─────────────────────────────────────────────
    # Main event loop
    # ─────────────────────────────────────────────
    def OnData(self, data):
        # FIX: Use self.Time (injected by engine) instead of data.Time
        current_time = self.Time.time()
        today = self.Time.date()

        # No new trade entries before 9:30 AM or after 2:45 PM
        if current_time < time(9, 15) or current_time > time(14, 45):
            return

        for sym in self.symbols:
            if sym not in data:
                continue

            bar = data[sym]
            ind = self.indicators[sym]

            # FIX: Inline ORB reset at start of each day (replaces Schedule.On)
            self._reset_orb_if_new_day(sym, today)

            # Collect ATR data on every bar regardless of state
            atr_value = self._get_atr(sym, bar)

            # Wait for EMA and volume SMA indicators to warm up
            if not (ind['sma_volume'].IsReady and
                    ind['ema_fast'].IsReady and
                    ind['ema_slow'].IsReady):
                continue

            # Build ORB levels during first 15 minutes (9:15 → 9:30)
            if current_time <= time(9, 30):
                self._update_orb_levels(sym, bar, ind)
                continue

            # Trade logic: entry check or position management
            if self.position_direction.get(sym, 0) == 0:
                self._check_entry(sym, bar, ind, atr_value)
            else:
                self._manage_position(sym, bar, atr_value)

    # ─────────────────────────────────────────────
    # ORB level tracking
    # ─────────────────────────────────────────────
    def _update_orb_levels(self, sym, bar, ind):
        """Track highest high and lowest low during the opening 15-minute range."""
        if self.orb_high.get(sym) is None or bar.High > self.orb_high[sym]:
            self.orb_high[sym] = bar.High

        if self.orb_low.get(sym) is None or bar.Low < self.orb_low[sym]:
            self.orb_low[sym] = bar.Low

        if self.orb_volume_avg.get(sym) is None and ind['sma_volume'].IsReady:
            self.orb_volume_avg[sym] = ind['sma_volume'].Value

    # ─────────────────────────────────────────────
    # Entry logic
    # ─────────────────────────────────────────────
    def _check_entry(self, sym, bar, ind, atr_value):
        """Check for ORB breakout with volume and EMA trend confirmation."""
        if self.orb_high.get(sym) is None or self.orb_low.get(sym) is None:
            return
        if atr_value == 0:
            return

        trend_bullish = ind['ema_fast'].Value > ind['ema_slow'].Value
        trend_bearish = ind['ema_fast'].Value < ind['ema_slow'].Value

        base_vol = self.orb_volume_avg.get(sym, bar.Volume) or bar.Volume
        volume_confirmed = bar.Volume > (base_vol * self.volume_threshold)

        # Cap concurrent positions
        current_positions = sum(1 for v in self.position_direction.values() if v != 0)
        if current_positions >= self.max_positions:
            return

        portfolio_value = self.Portfolio.TotalPortfolioValue

        # ── LONG: break above ORB high ──
        if bar.Close > self.orb_high[sym] and trend_bullish and volume_confirmed:
            risk_amount = portfolio_value * self.risk_per_trade
            position_size = risk_amount / (1.5 * atr_value)

            max_shares = (portfolio_value * 0.30) / bar.Close
            shares = min(position_size, max_shares)
            target_pct = (shares * bar.Close) / portfolio_value

            if target_pct > 0.05:
                self.SetHoldings(sym, target_pct)
                self.entry_price[sym] = bar.Close
                self.stop_loss[sym]   = bar.Close - (1.5 * atr_value)
                self.target_price[sym] = bar.Close + (3.0 * atr_value)
                self.position_direction[sym] = 1

                self.Log(
                    f"LONG {sym} @ {bar.Close:.2f} | "
                    f"Size: {target_pct:.2%} | "
                    f"SL: {self.stop_loss[sym]:.2f} | "
                    f"TG: {self.target_price[sym]:.2f} | "
                    f"Vol: {bar.Volume / base_vol:.1f}x"
                )

        # ── SHORT: break below ORB low ──
        elif bar.Close < self.orb_low[sym] and trend_bearish and volume_confirmed:
            risk_amount = portfolio_value * self.risk_per_trade
            position_size = risk_amount / (1.5 * atr_value)

            max_shares = (portfolio_value * 0.30) / bar.Close
            shares = min(position_size, max_shares)
            target_pct = -((shares * bar.Close) / portfolio_value)

            if abs(target_pct) > 0.05:
                self.SetHoldings(sym, target_pct)
                self.entry_price[sym]  = bar.Close
                self.stop_loss[sym]    = bar.Close + (1.5 * atr_value)
                self.target_price[sym] = bar.Close - (3.0 * atr_value)
                self.position_direction[sym] = -1

                self.Log(
                    f"SHORT {sym} @ {bar.Close:.2f} | "
                    f"Size: {target_pct:.2%} | "
                    f"SL: {self.stop_loss[sym]:.2f} | "
                    f"TG: {self.target_price[sym]:.2f}"
                )

    # ─────────────────────────────────────────────
    # Position management
    # ─────────────────────────────────────────────
    def _manage_position(self, sym, bar, atr_value):
        """Check stop-loss, target, and trailing stop for open positions."""
        direction = self.position_direction.get(sym, 0)
        if direction == 0:
            return

        current_price = bar.Close
        entry  = self.entry_price.get(sym, current_price)
        stop   = self.stop_loss.get(sym, current_price)
        target = self.target_price.get(sym, current_price)

        if direction == 1:  # ── Long ──
            if current_price >= target:
                self.Liquidate(sym)
                self.Log(f"LONG Target Hit {sym} @ {current_price:.2f} | PnL: {(current_price/entry - 1)*100:.2f}%")
                self.position_direction[sym] = 0
                return

            if current_price <= stop:
                self.Liquidate(sym)
                self.Log(f"LONG Stop Hit {sym} @ {current_price:.2f} | Loss: {(current_price/entry - 1)*100:.2f}%")
                self.position_direction[sym] = 0
                return

            # Trailing stop: move to breakeven + 0.5 ATR once up > 1 ATR
            if atr_value > 0 and current_price > entry + atr_value and stop < entry:
                new_stop = entry + (0.5 * atr_value)
                if new_stop > stop:
                    self.stop_loss[sym] = new_stop
                    self.Log(f"Trailing Stop {sym} raised to {new_stop:.2f}")

        else:  # ── Short ──
            if current_price <= target:
                self.Liquidate(sym)
                self.Log(f"SHORT Target Hit {sym} @ {current_price:.2f} | PnL: {(entry/current_price - 1)*100:.2f}%")
                self.position_direction[sym] = 0
                return

            if current_price >= stop:
                self.Liquidate(sym)
                self.Log(f"SHORT Stop Hit {sym} @ {current_price:.2f} | Loss: {(entry/current_price - 1)*100:.2f}%")
                self.position_direction[sym] = 0
                return

            # Trailing stop for shorts
            if atr_value > 0 and current_price < entry - atr_value and stop > entry:
                new_stop = entry - (0.5 * atr_value)
                if new_stop < stop:
                    self.stop_loss[sym] = new_stop
                    self.Log(f"Trailing Stop {sym} lowered to {new_stop:.2f}")
