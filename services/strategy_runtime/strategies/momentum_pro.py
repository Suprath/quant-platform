"""
MomentumPro: High-Frequency Intraday Strategy

Core Philosophy: Ride short-term momentum waves with tight risk management.
- Entry: VWAP Crossover + Volume Spike
- Exit: Trailing Stop (0.3%) OR Fixed Target (0.5%)
- Risk: Fixed ₹50 max loss per trade (~1% of ₹5,000)
"""

import logging
from datetime import datetime, time as dt_time
from typing import Dict, Optional
import pandas as pd

logger = logging.getLogger("MomentumPro")


class MomentumPro:
    """High-Frequency Momentum Strategy for Intraday Trading."""

    def __init__(
        self,
        strategy_id: str = "MOMENTUM_PRO_V1",
        backtest_mode: bool = False,
        risk_per_trade: float = 50.0,  # ₹50 max loss per trade
        trailing_stop_pct: float = 0.002,  # 0.2% trailing stop (wider)
        profit_target_pct: float = 0.003,  # 0.3% profit target (1.5:1 R:R)
        volume_spike_ratio: float = 1.5,  # 1.5x avg volume for entry
        use_volume_filter: bool = False,  # Disable by default for OHLC replay
        cooldown_seconds: int = 30,  # 30 seconds cooldown (fast re-entry)
        max_trades_per_symbol: int = 50,  # More trades allowed
        max_trades_total: int = 100,  # More trades allowed
        **kwargs
    ):
        self.strategy_id = strategy_id
        self.backtest_mode = backtest_mode
        self.risk_per_trade = risk_per_trade
        self.trailing_stop_pct = trailing_stop_pct
        self.profit_target_pct = profit_target_pct
        self.volume_spike_ratio = volume_spike_ratio
        self.cooldown_seconds = cooldown_seconds
        self.max_trades_per_symbol = max_trades_per_symbol
        self.max_trades_total = max_trades_total
        self.use_volume_filter = use_volume_filter

        # State tracking
        self.symbol_state: Dict[str, dict] = {}
        self.total_trades_today = 0
        self.last_trade_date = None

        logger.info(
            f"🚀 {self.strategy_id} Initialized | "
            f"Risk/Trade: ₹{risk_per_trade} | "
            f"Trailing: {trailing_stop_pct*100:.1f}% | "
            f"Target: {profit_target_pct*100:.1f}%"
        )

    def _get_or_create_state(self, symbol: str) -> dict:
        if symbol not in self.symbol_state:
            self.symbol_state[symbol] = {
                "buffer": [],
                "max_buffer": 60,  # 1 hour of minute bars
                "last_processed_minute": -1,
                "last_processed_date": None,
                "active_trade": None,
                "trades_today": 0,
                "last_exit_time": None,
                "vwap_crossed_above": False,
                "vwap_crossed_below": False,
                "peak_price": None,
                "trough_price": None,
                # Per-symbol optimized params (loaded from DB if available)
                "optimized_params": None,
            }
        return self.symbol_state[symbol]

    def set_symbol_params(self, symbol: str, params: dict):
        """Set optimized parameters for a specific symbol."""
        state = self._get_or_create_state(symbol)
        state["optimized_params"] = params
        logger.info(
            f"⚙️ {symbol} optimized params: TS={params.get('trailing_stop_pct', self.trailing_stop_pct)*100:.2f}%, "
            f"PT={params.get('profit_target_pct', self.profit_target_pct)*100:.2f}%, "
            f"CD={params.get('cooldown_seconds', self.cooldown_seconds)}s"
        )

    def _get_params_for_symbol(self, state: dict) -> tuple:
        """Get trailing_stop, profit_target, cooldown for a symbol (optimized or default)."""
        if state.get("optimized_params"):
            p = state["optimized_params"]
            return (
                p.get("trailing_stop_pct", self.trailing_stop_pct),
                p.get("profit_target_pct", self.profit_target_pct),
                p.get("cooldown_seconds", self.cooldown_seconds),
            )
        return (self.trailing_stop_pct, self.profit_target_pct, self.cooldown_seconds)

    def _calculate_vwap(self, df: pd.DataFrame) -> float:
        """Calculate Volume-Weighted Average Price."""
        if len(df) < 2 or df["volume"].sum() == 0:
            return 0.0
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        return (typical_price * df["volume"]).sum() / df["volume"].sum()

    def _calculate_avg_volume(self, df: pd.DataFrame, periods: int = 20) -> float:
        """Calculate average volume over N periods."""
        if len(df) < periods:
            return df["volume"].mean() if len(df) > 0 else 0.0
        return df["volume"].tail(periods).mean()

    def _calculate_position_size(self, entry_price: float, stop_loss_price: float, balance: float) -> int:
        """Calculate position size based on risk per trade."""
        risk_per_share = abs(entry_price - stop_loss_price)
        if risk_per_share <= 0:
            risk_per_share = entry_price * self.trailing_stop_pct

        # Max shares based on risk
        max_shares_by_risk = int(self.risk_per_trade / risk_per_share)

        # Max shares based on available capital (5x leverage)
        max_shares_by_capital = int((balance * 5) / entry_price)

        return max(1, min(max_shares_by_risk, max_shares_by_capital))

    def on_tick(self, tick: dict, current_qty: int, balance: float = 5000.0, avg_price: float = None) -> Optional[dict]:
        """Process incoming tick and generate trading signals."""
        symbol = tick.get("symbol")
        ts_ms = tick.get("timestamp", 0)
        ltp = float(tick.get("ltp", 0))
        volume = float(tick.get('volume', 0))
        vwap_tick = float(tick.get("vwap", 0))  # VWAP from tick if available

        if ltp <= 0:
            return None

        dt = datetime.fromtimestamp(ts_ms / 1000)
        current_time = dt.time()
        tick_date = dt.date()
        minute_key = dt.minute

        # Skip non-tradeable symbols (indices)
        if "INDEX" in symbol.upper() or "Nifty" in symbol:
            return None

        state = self._get_or_create_state(symbol)

        # === Day Reset ===
        if state["last_processed_date"] and tick_date > state["last_processed_date"]:
            logger.info(f"📆 New Day for {symbol}: Resetting state")
            state["buffer"] = []
            state["trades_today"] = 0
            state["last_exit_time"] = None
            state["active_trade"] = None
            state["vwap_crossed_above"] = False
            state["vwap_crossed_below"] = False
            state["peak_price"] = None
            state["trough_price"] = None
            self.total_trades_today = 0

        state["last_processed_date"] = tick_date

        # === Market Hours Check (9:20 AM - 3:15 PM IST) ===
        market_start = dt_time(3, 50)  # 9:20 AM IST in UTC
        market_end = dt_time(9, 45)    # 3:15 PM IST in UTC

        if current_time < market_start or current_time > market_end:
            return None

        # === Buffer Management ===
        if minute_key != state["last_processed_minute"]:
            state["buffer"].append({
                "time": dt,
                "open": ltp,
                "high": ltp,
                "low": ltp,
                "close": ltp,
                "volume": volume,
            })
            state["last_processed_minute"] = minute_key
            if len(state["buffer"]) > state["max_buffer"]:
                state["buffer"].pop(0)
        else:
            if state["buffer"]:
                state["buffer"][-1]["high"] = max(state["buffer"][-1]["high"], ltp)
                state["buffer"][-1]["low"] = min(state["buffer"][-1]["low"], ltp)
                state["buffer"][-1]["close"] = ltp
                state["buffer"][-1]["volume"] += volume

        if len(state["buffer"]) < 5:
            return None

        df = pd.DataFrame(state["buffer"])

        # === Calculate Indicators ===
        vwap = vwap_tick if vwap_tick > 0 else self._calculate_vwap(df)
        avg_volume = self._calculate_avg_volume(df)

        # === ACTIVE TRADE MANAGEMENT ===
        if current_qty != 0 and state["active_trade"]:
            trade = state["active_trade"]
            trailing_stop_pct, profit_target_pct, _ = self._get_params_for_symbol(state)

            if trade["type"] == "LONG":
                # Update peak price for trailing stop
                if state["peak_price"] is None or ltp > state["peak_price"]:
                    state["peak_price"] = ltp

                # Grace period: trailing stop only activates after 0.1% move in favor
                min_activation_price = trade["entry"] * 1.001  # 0.1% above entry
                trailing_active = state["peak_price"] >= min_activation_price

                trailing_stop = state["peak_price"] * (1 - trailing_stop_pct)
                profit_target = trade["entry"] * (1 + profit_target_pct)

                # Profit target always active
                if ltp >= profit_target:
                    pnl = (ltp - trade["entry"]) * abs(current_qty)
                    logger.info(f"🎯 TARGET HIT: {symbol} @ {ltp} | P&L: ₹{pnl:.2f}")
                    state["active_trade"] = None
                    state["last_exit_time"] = dt
                    state["peak_price"] = None
                    return {
                        "strategy_id": self.strategy_id,
                        "symbol": symbol,
                        "action": "SELL",
                        "price": ltp,
                        "quantity": abs(current_qty),
                        "reason": "TARGET_HIT",
                        "timestamp": dt,
                    }

                # Trailing stop only if activated
                if trailing_active and ltp <= trailing_stop:
                    pnl = (ltp - trade["entry"]) * abs(current_qty)
                    logger.info(f"🛑 TRAILING STOP: {symbol} @ {ltp} | P&L: ₹{pnl:.2f}")
                    state["active_trade"] = None
                    state["last_exit_time"] = dt
                    state["peak_price"] = None
                    return {
                        "strategy_id": self.strategy_id,
                        "symbol": symbol,
                        "action": "SELL",
                        "price": ltp,
                        "quantity": abs(current_qty),
                        "reason": "TRAILING_STOP",
                        "timestamp": dt,
                    }

                # Hard stop: if drops more than 1% from entry without activation, exit
                hard_stop = trade["entry"] * 0.99  # 1% hard stop loss
                if not trailing_active and ltp <= hard_stop:
                    pnl = (ltp - trade["entry"]) * abs(current_qty)
                    logger.info(f"❌ HARD STOP: {symbol} @ {ltp} | P&L: ₹{pnl:.2f}")
                    state["active_trade"] = None
                    state["last_exit_time"] = dt
                    state["peak_price"] = None
                    return {
                        "strategy_id": self.strategy_id,
                        "symbol": symbol,
                        "action": "SELL",
                        "price": ltp,
                        "quantity": abs(current_qty),
                        "reason": "HARD_STOP",
                        "timestamp": dt,
                    }

            elif trade["type"] == "SHORT":
                # Update trough price for trailing stop
                if state["trough_price"] is None or ltp < state["trough_price"]:
                    state["trough_price"] = ltp

                # Grace period: trailing stop only activates after 0.1% move in favor
                min_activation_price = trade["entry"] * 0.999  # 0.1% below entry
                trailing_active = state["trough_price"] <= min_activation_price

                trailing_stop = state["trough_price"] * (1 + trailing_stop_pct)
                profit_target = trade["entry"] * (1 - profit_target_pct)

                # Profit target always active
                if ltp <= profit_target:
                    pnl = (trade["entry"] - ltp) * abs(current_qty)
                    logger.info(f"🎯 TARGET HIT: {symbol} @ {ltp} | P&L: ₹{pnl:.2f}")
                    state["active_trade"] = None
                    state["last_exit_time"] = dt
                    state["trough_price"] = None
                    return {
                        "strategy_id": self.strategy_id,
                        "symbol": symbol,
                        "action": "BUY",
                        "price": ltp,
                        "quantity": abs(current_qty),
                        "reason": "TARGET_HIT",
                        "timestamp": dt,
                    }

                # Trailing stop only if activated
                if trailing_active and ltp >= trailing_stop:
                    pnl = (trade["entry"] - ltp) * abs(current_qty)
                    logger.info(f"🛑 TRAILING STOP: {symbol} @ {ltp} | P&L: ₹{pnl:.2f}")
                    state["active_trade"] = None
                    state["last_exit_time"] = dt
                    state["trough_price"] = None
                    return {
                        "strategy_id": self.strategy_id,
                        "symbol": symbol,
                        "action": "BUY",
                        "price": ltp,
                        "quantity": abs(current_qty),
                        "reason": "TRAILING_STOP",
                        "timestamp": dt,
                    }

                # Hard stop: if rises more than 1% from entry without activation, exit
                hard_stop = trade["entry"] * 1.01  # 1% hard stop loss
                if not trailing_active and ltp >= hard_stop:
                    pnl = (trade["entry"] - ltp) * abs(current_qty)
                    logger.info(f"❌ HARD STOP: {symbol} @ {ltp} | P&L: ₹{pnl:.2f}")
                    state["active_trade"] = None
                    state["last_exit_time"] = dt
                    state["trough_price"] = None
                    return {
                        "strategy_id": self.strategy_id,
                        "symbol": symbol,
                        "action": "BUY",
                        "price": ltp,
                        "quantity": abs(current_qty),
                        "reason": "HARD_STOP",
                        "timestamp": dt,
                    }

            return None  # Holding position, no new signal


        # === ENTRY LOGIC (Only if no position) ===
        if current_qty != 0:
            logger.debug(f"📛 {symbol}: Entry blocked - existing position qty={current_qty}")
            return None

        # Check guardrails
        if state["trades_today"] >= self.max_trades_per_symbol:
            logger.debug(f"📛 {symbol}: Max trades/symbol reached ({state['trades_today']})")
            return None
        if self.total_trades_today >= self.max_trades_total:
            logger.debug(f"📛 {symbol}: Max total trades reached ({self.total_trades_today})")
            return None

        # Cooldown check (use per-symbol optimized cooldown)
        _, _, cooldown_sec = self._get_params_for_symbol(state)
        if state["last_exit_time"]:
            elapsed = (dt - state["last_exit_time"]).total_seconds()
            if elapsed < cooldown_sec:
                logger.debug(f"📛 {symbol}: Cooldown active ({elapsed:.0f}s / {cooldown_sec}s)")
                return None

        # Volume spike check (optional, disabled by default for OHLC backtests)
        if self.use_volume_filter:
            if avg_volume <= 0 or volume < avg_volume * self.volume_spike_ratio:
                return None

        # VWAP Crossover detection with momentum confirmation
        # Instead of requiring exact crossover, detect sustained momentum above/below VWAP
        prev_close = df["close"].iloc[-2] if len(df) >= 2 else ltp
        prev_prev_close = df["close"].iloc[-3] if len(df) >= 3 else prev_close

        # Calculate price momentum (last 3 bars trend)
        is_uptrend = ltp > prev_close > prev_prev_close
        is_downtrend = ltp < prev_close < prev_prev_close

        # Long Entry: Price above VWAP with upward momentum
        # Relaxed: don't require exact crossover, just price above VWAP with confirmation
        if ltp > vwap * 1.001:
            recently_crossed_up = prev_close <= vwap or prev_prev_close <= vwap
            if recently_crossed_up or is_uptrend:
                _, _, cooldown_sec = self._get_params_for_symbol(state)
                trailing_stop_pct, profit_target_pct, _ = self._get_params_for_symbol(state)
                
                stop_loss = ltp * (1 - trailing_stop_pct)
                quantity = self._calculate_position_size(ltp, stop_loss, balance)

                state["active_trade"] = {
                    "type": "LONG",
                    "entry": ltp,
                    "sl": stop_loss,
                }
                state["trades_today"] += 1
                self.total_trades_today += 1
                state["peak_price"] = ltp

                logger.info(f"🟢 LONG ENTRY: {symbol} @ {ltp} | Qty: {quantity} | VWAP: {vwap:.2f} | Trend: {'↑' if is_uptrend else '→'}")
                return {
                    "strategy_id": self.strategy_id,
                    "symbol": symbol,
                    "action": "BUY",
                    "price": ltp,
                    "quantity": quantity,
                    "reason": "VWAP_MOMENTUM_UP",
                    "timestamp": dt,
                }
            # else:
            #     logger.debug(f"🔵 {symbol}: Price > VWAP but NO ENTRY. Trend={is_uptrend}, Cross={recently_crossed_up}")

        # Short Entry: Price below VWAP with downward momentum
        if ltp < vwap * 0.999:
            recently_crossed_down = prev_close >= vwap or prev_prev_close >= vwap
            if recently_crossed_down or is_downtrend:
                trailing_stop_pct, profit_target_pct, _ = self._get_params_for_symbol(state)
                
                stop_loss = ltp * (1 + trailing_stop_pct)
                quantity = self._calculate_position_size(ltp, stop_loss, balance)

                state["active_trade"] = {
                    "type": "SHORT",
                    "entry": ltp,
                    "sl": stop_loss,
                }
                state["trades_today"] += 1
                self.total_trades_today += 1
                state["trough_price"] = ltp

                logger.info(f"🔴 SHORT ENTRY: {symbol} @ {ltp} | Qty: {quantity} | VWAP: {vwap:.2f} | Trend: {'↓' if is_downtrend else '→'}")
                return {
                    "strategy_id": self.strategy_id,
                    "symbol": symbol,
                    "action": "SELL",
                    "price": ltp,
                    "quantity": quantity,
                    "reason": "VWAP_MOMENTUM_DOWN",
                    "timestamp": dt,
                }
            # else:
            #     logger.debug(f"🟠 {symbol}: Price < VWAP but NO ENTRY. Trend={is_downtrend}, Cross={recently_crossed_down}")

        return None
