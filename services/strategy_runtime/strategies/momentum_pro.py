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
        trailing_stop_pct: float = 0.003,  # 0.3% trailing stop
        profit_target_pct: float = 0.005,  # 0.5% profit target
        volume_spike_ratio: float = 1.5,  # 1.5x avg volume for entry
        use_volume_filter: bool = False,  # Disable by default for OHLC replay
        cooldown_seconds: int = 120,  # 2 minutes cooldown
        max_trades_per_symbol: int = 20,
        max_trades_total: int = 50,
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
            }
        return self.symbol_state[symbol]

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

            if trade["type"] == "LONG":
                # Update peak price for trailing stop
                if state["peak_price"] is None or ltp > state["peak_price"]:
                    state["peak_price"] = ltp

                trailing_stop = state["peak_price"] * (1 - self.trailing_stop_pct)
                profit_target = trade["entry"] * (1 + self.profit_target_pct)

                # Exit conditions
                if ltp <= trailing_stop:
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
                        "reason": "TRAILING_STOP",
                        "timestamp": dt,
                    }

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
                        "reason": "TARGET_HIT",
                        "timestamp": dt,
                    }

            elif trade["type"] == "SHORT":
                # Update trough price for trailing stop
                if state["trough_price"] is None or ltp < state["trough_price"]:
                    state["trough_price"] = ltp

                trailing_stop = state["trough_price"] * (1 + self.trailing_stop_pct)
                profit_target = trade["entry"] * (1 - self.profit_target_pct)

                if ltp >= trailing_stop:
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
                        "reason": "TRAILING_STOP",
                        "timestamp": dt,
                    }

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
                        "reason": "TARGET_HIT",
                        "timestamp": dt,
                    }

            return None  # Holding position, no new signal

        # === ENTRY LOGIC (Only if no position) ===
        if current_qty != 0:
            return None

        # Check guardrails
        if state["trades_today"] >= self.max_trades_per_symbol:
            return None
        if self.total_trades_today >= self.max_trades_total:
            return None

        # Cooldown check
        if state["last_exit_time"]:
            elapsed = (dt - state["last_exit_time"]).total_seconds()
            if elapsed < self.cooldown_seconds:
                return None

        # Volume spike check (optional, disabled by default for OHLC backtests)
        if self.use_volume_filter:
            if avg_volume <= 0 or volume < avg_volume * self.volume_spike_ratio:
                return None

        # VWAP Crossover detection
        prev_close = df["close"].iloc[-2] if len(df) >= 2 else ltp

        # Long Entry: Price crosses above VWAP with volume spike
        if prev_close <= vwap and ltp > vwap:
            stop_loss = ltp * (1 - self.trailing_stop_pct)
            quantity = self._calculate_position_size(ltp, stop_loss, balance)

            state["active_trade"] = {
                "type": "LONG",
                "entry": ltp,
                "sl": stop_loss,
            }
            state["trades_today"] += 1
            self.total_trades_today += 1
            state["peak_price"] = ltp

            logger.info(f"🟢 LONG ENTRY: {symbol} @ {ltp} | Qty: {quantity} | VWAP: {vwap:.2f}")
            return {
                "strategy_id": self.strategy_id,
                "symbol": symbol,
                "action": "BUY",
                "price": ltp,
                "quantity": quantity,
                "reason": "VWAP_CROSS_UP",
                "timestamp": dt,
            }

        # Short Entry: Price crosses below VWAP with volume spike
        if prev_close >= vwap and ltp < vwap:
            stop_loss = ltp * (1 + self.trailing_stop_pct)
            quantity = self._calculate_position_size(ltp, stop_loss, balance)

            state["active_trade"] = {
                "type": "SHORT",
                "entry": ltp,
                "sl": stop_loss,
            }
            state["trades_today"] += 1
            self.total_trades_today += 1
            state["trough_price"] = ltp

            logger.info(f"🔴 SHORT ENTRY: {symbol} @ {ltp} | Qty: {quantity} | VWAP: {vwap:.2f}")
            return {
                "strategy_id": self.strategy_id,
                "symbol": symbol,
                "action": "SELL",
                "price": ltp,
                "quantity": quantity,
                "reason": "VWAP_CROSS_DOWN",
                "timestamp": dt,
            }

        return None
