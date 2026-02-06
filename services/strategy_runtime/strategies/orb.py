import pandas as pd
import numpy as np
import logging
from datetime import datetime, time as dt_time
from typing import Dict, Optional, Tuple

logger = logging.getLogger("EnhancedORB")

class EnhancedORB:
    """
    Enhanced Opening Range Breakout (ORB) Strategy for high-frequency tick processing.
    """
    def __init__(self, strategy_id="ORB_V1", orb_minutes=15, backtest_mode=False):
        self.strategy_id = strategy_id
        self.orb_minutes = orb_minutes
        self.backtest_mode = backtest_mode
        
        # State per symbol
        self.symbol_state = {}
        
        # Global Regime State (Index)
        self.nifty_buffer = [] 
        self.nifty_ltp = 0.0
        self.nifty_sma = 0.0
        
        logger.info(f"🚀 {self.strategy_id} Initialized (ORB: {self.orb_minutes}m, Mode: {'BACKTEST' if backtest_mode else 'LIVE'})")

    def _get_or_create_state(self, symbol):
        if symbol not in self.symbol_state:
            self.symbol_state[symbol] = {
                'orb_high': None,
                'orb_low': None,
                'orb_set': False,
                'buffer': [], 
                'max_buffer': 100,
                'last_processed_minute': -1,
                'last_processed_date': None,
                'active_trade': None, 
                'trades_today': 0,
                'last_exit_time': None,
                'pending_pullback': None # {type, level, expires}
            }
        return self.symbol_state[symbol]

    MAX_TRADES_PER_DAY = 3
    COOLDOWN_MINUTES = 15
    
    # Strategy Optimization Parameters (Phase 4)
    MIN_ATR_PERCENT = 0.05       # Reset to 0.05% for quality
    TARGET_1_ATR = 1.5           # Partial profit target
    TARGET_2_ATR = 3.0           # Final profit target
    TRAILING_STOP_TRIGGER = 1.5  # Move remaining SL to breakeven
    PULLBACK_THRESHOLD = 0.0005  # 0.05% pullback limit for entry

    def calculate_atr(self, df, period=14):
        if len(df) < period + 1:
            return 0.0
        high_low = df['high'] - df['low']
        high_prev_close = abs(df['high'] - df['close'].shift(1))
        low_prev_close = abs(df['low'] - df['close'].shift(1))
        tr = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
        return tr.rolling(window=period).mean().iloc[-1]

    def calculate_supertrend(self, df, period=10, multiplier=3.0):
        if len(df) < period + 1:
            return None, 1
        
        hl2 = (df['high'] + df['low']) / 2
        
        # Simple ATR for SuperTrend
        high_low = df['high'] - df['low']
        atr = high_low.rolling(window=period).mean()
        
        upper_band = hl2 + (multiplier * atr)
        lower_band = hl2 - (multiplier * atr)
        
        # Simplified one-step SuperTrend for performance
        if df['close'].iloc[-1] > upper_band.iloc[-2]:
            return lower_band.iloc[-1], 1
        else:
            return upper_band.iloc[-1], -1

    def on_tick(self, tick, current_qty, balance=20000, avg_price=None):
        symbol = tick.get('symbol')
        ltp = float(tick.get('ltp', 0))
        vwap = float(tick.get('vwap', 0))
        volume = float(tick.get('v', 0))
        ts_ms = tick.get('timestamp', 0)
        tick_day_high = float(tick.get('day_high', 0))
        tick_day_low = float(tick.get('day_low', 0))
        
        # Context extraction
        dt = datetime.fromtimestamp(ts_ms / 1000)
        current_time_utc = dt.time()
        
        state = self._get_or_create_state(symbol)
        
        # Day Reset Logic
        tick_date = dt.date()
        if state['last_processed_date'] and tick_date > state['last_processed_date']:
            logger.info(f"📆 New Day Detected for {symbol}: {tick_date}. Resetting state.")
            state['orb_high'] = None
            state['orb_low'] = None
            state['orb_set'] = False
            state['buffer'] = []
            state['trades_today'] = 0
            state['last_exit_time'] = None
            state['last_processed_minute'] = -1
            # Reset Nifty on day change too
            self.nifty_buffer = []
            self.nifty_ltp = 0.0
            self.nifty_sma = 0.0

        state['last_processed_date'] = tick_date
        if current_qty != 0 and state['active_trade'] is None:
            # We have a position but lost state in memory. Re-calculate SL/Target from avg_price if provided.
            entry = avg_price if avg_price else ltp
            state['active_trade'] = {
                'type': 'LONG' if current_qty > 0 else 'SHORT',
                'entry': entry,
                'sl': entry * 0.99 if current_qty > 0 else entry * 1.01, # 1% safety SL
                'tgt': entry * 1.02 if current_qty > 0 else entry * 0.98  # 2% safety TGT
            }
            logger.warning(f"🔄 Re-synced trade state for {symbol} (Position: {current_qty}, Entry: {entry})")

        # 0. ACTIVE TRADE MANAGEMENT (EXITS)
        if current_qty != 0 and state['active_trade']:
            trade = state['active_trade']
            exit_signal = None
            
            # 50/50 MULTI-TARGET LOGIC
            # If current_qty is half of our usual (assuming we sell half at T1)
            # We don't track original qty here globally, but we can detect state['target_1_hit']
            
            # LONG EXIT
            if trade['type'] == 'LONG':
                # Partial Target 1 (1.5x ATR)
                if not trade.get('t1_hit') and ltp >= trade['t1']:
                    trade['t1_hit'] = True
                    trade['sl'] = trade['entry'] # Move SL to Breakeven
                    logger.info(f"🎯 [ORB_V1] TARGET 1 HIT (Partial): {symbol} @ {ltp} | SL moved to Breakeven")
                    return {
                        "strategy_id": self.strategy_id, "symbol": symbol, 
                        "action": "SELL", "price": ltp, "quantity": abs(current_qty) // 2,
                        "reason": "TARGET_1_PARTIAL"
                    }

                if ltp <= trade['sl']:
                    logger.info(f"🛑 [ORB_V1] STOP LOSS HIT: {symbol} @ {ltp} (Entry: {trade['entry']}, SL: {trade['sl']})")
                    exit_signal = {"strategy_id": self.strategy_id, "symbol": symbol, "action": "SELL", "price": ltp, "reason": "SL_HIT"}
                elif ltp >= trade['t2']:
                    logger.info(f"🎯 [ORB_V1] FINAL TARGET HIT: {symbol} @ {ltp} (Entry: {trade['entry']}, TGT: {trade['t2']})")
                    exit_signal = {"strategy_id": self.strategy_id, "symbol": symbol, "action": "SELL", "price": ltp, "reason": "TARGET_2_HIT"}
            
            # SHORT EXIT
            elif trade['type'] == 'SHORT':
                # Partial Target 1 (1.5x ATR)
                if not trade.get('t1_hit') and ltp <= trade['t1']:
                    trade['t1_hit'] = True
                    trade['sl'] = trade['entry'] # Move SL to Breakeven
                    logger.info(f"🎯 [ORB_V1] TARGET 1 HIT (Partial): {symbol} @ {ltp} | SL moved to Breakeven")
                    return {
                        "strategy_id": self.strategy_id, "symbol": symbol, 
                        "action": "BUY", "price": ltp, "quantity": abs(current_qty) // 2,
                        "reason": "TARGET_1_PARTIAL"
                    }

                if ltp >= trade['sl']:
                    logger.info(f"🛑 [ORB_V1] STOP LOSS HIT: {symbol} @ {ltp} (Entry: {trade['entry']}, SL: {trade['sl']})")
                    exit_signal = {"strategy_id": self.strategy_id, "symbol": symbol, "action": "BUY", "price": ltp, "reason": "SL_HIT"}
                elif ltp <= trade['t2']:
                    logger.info(f"🎯 [ORB_V1] FINAL TARGET HIT: {symbol} @ {ltp} (Entry: {trade['entry']}, TGT: {trade['t2']})")
                    exit_signal = {"strategy_id": self.strategy_id, "symbol": symbol, "action": "BUY", "price": ltp, "reason": "TARGET_2_HIT"}

            if exit_signal:
                state['active_trade'] = None
                state['last_exit_time'] = dt
                state['pending_pullback'] = None
                return exit_signal

        # 1. Capture ORB Levels
        market_open_utc = dt_time(3, 45)
        orb_cutoff_utc = (datetime.combine(dt.date(), market_open_utc) + pd.Timedelta(minutes=self.orb_minutes)).time()
        
        if current_time_utc < market_open_utc:
            return None
            
        if current_time_utc <= orb_cutoff_utc:
            if state['orb_high'] is None or ltp > state['orb_high']:
                state['orb_high'] = ltp
            if state['orb_low'] is None or ltp < state['orb_low']:
                state['orb_low'] = ltp
            return None 
        elif not state['orb_set']:
            if state['orb_high'] is None:
                state['orb_high'] = tick_day_high if tick_day_high > 0 else ltp
            if state['orb_low'] is None:
                state['orb_low'] = tick_day_low if tick_day_low > 0 else ltp
            
            state['orb_set'] = True
            logger.info(f"🎯 ORB for {symbol} set: High={state['orb_high']}, Low={state['orb_low']} (Fallback Used: {tick_day_high > 0})")

        # 2. Maintain Buffer
        minute_key = dt.minute
        if minute_key != state['last_processed_minute']:
            state['buffer'].append({
                'time': dt, 'open': ltp, 'high': ltp, 'low': ltp, 'close': ltp, 'volume': volume
            })
            state['last_processed_minute'] = minute_key
            if len(state['buffer']) > state['max_buffer']:
                state['buffer'].pop(0)
        else:
            state['buffer'][-1]['high'] = max(state['buffer'][-1]['high'], ltp)
            state['buffer'][-1]['low'] = min(state['buffer'][-1]['low'], ltp)
            state['buffer'][-1]['close'] = ltp
            state['buffer'][-1]['volume'] += volume

        if len(state['buffer']) < 5: 
            return None

        # 3. Strategy Logic
        df = pd.DataFrame(state['buffer'])
        atr = self.calculate_atr(df, period=min(14, len(df)-1))
        _, st_dir = self.calculate_supertrend(df, period=min(10, len(df)-1))
        
        orb_range_pct = (state['orb_high'] - state['orb_low']) / ltp * 100
        if not (0.1 <= orb_range_pct <= 2.5):
            return None
        
        if atr_pct < self.MIN_ATR_PERCENT:
            return None

        # 4. Global Regime (Nifty 50) Tracking
        if "Nifty 50" in symbol:
            self.nifty_ltp = ltp
            if minute_key != state['last_processed_minute']:
                # Update Nifty SMA
                if len(df) >= 20:
                    self.nifty_sma = df['close'].rolling(20).mean().iloc[-1]
            return None # Don't trade the index itself directly with this strategy

        if current_qty == 0:
            # 4. ENTRY GUARDRAILS
            if state['trades_today'] >= self.MAX_TRADES_PER_DAY:
                return None
            
            # Index Regime Filter
            if self.nifty_sma > 0:
                is_bullish = self.nifty_ltp > self.nifty_sma
                if is_breakout and not is_bullish: return None
                if is_breakdown and is_bullish: return None

            if state['last_exit_time']:
                cooldown_remaining = (dt - state['last_exit_time']).total_seconds() / 60
                if cooldown_remaining < self.COOLDOWN_MINUTES:
                    return None

            # 5. PULLBACK ENTRY LOGIC
            is_breakout = ltp > state['orb_high'] and ltp > vwap
            is_breakdown = ltp < state['orb_low'] and ltp < vwap
            
            # Check for existing pending pullback
            if state['pending_pullback']:
                pending = state['pending_pullback']
                # Check if expired (3 minutes)
                if (dt - pending['ts']).total_seconds() > 180:
                    state['pending_pullback'] = None
                    logger.debug(f"⏰ Pullback for {symbol} expired.")
                else:
                    # Look for trend resumption (SuperTrend alignment)
                    if (pending['type'] == 'LONG' and ltp > state['orb_high'] and st_dir == 1) or \
                       (pending['type'] == 'SHORT' and ltp < state['orb_low'] and st_dir == -1):
                        
                        sl_dist = max(atr * 1.5, ltp * 0.002)
                        if pending['type'] == 'LONG':
                            sl = max(state['orb_low'], ltp - sl_dist)
                            t1 = ltp + (atr * self.TARGET_1_ATR)
                            t2 = ltp + (atr * self.TARGET_2_ATR)
                            state['active_trade'] = {'type': 'LONG', 'entry': ltp, 'sl': sl, 't1': t1, 't2': t2, 't1_hit': False}
                            logger.info(f"⚡ [ORB_V1] LONG ENTRY (Pullback): {symbol} @ {ltp} | SL: {sl} | T2: {t2}")
                            action = "BUY"
                        else:
                            sl = min(state['orb_high'], ltp + sl_dist)
                            t1 = ltp - (atr * self.TARGET_1_ATR)
                            t2 = ltp - (atr * self.TARGET_2_ATR)
                            state['active_trade'] = {'type': 'SHORT', 'entry': ltp, 'sl': sl, 't1': t1, 't2': t2, 't1_hit': False}
                            logger.info(f"⚡ [ORB_V1] SHORT ENTRY (Pullback): {symbol} @ {ltp} | SL: {sl} | T2: {t2}")
                            action = "SELL"
                        
                        state['trades_today'] += 1
                        state['pending_pullback'] = None
                        return {
                            "strategy_id": self.strategy_id, "symbol": symbol, "action": action,
                            "price": ltp, "stop_loss": sl, "target": t2
                        }

            # If no pending pullback, look for first break to start pullback guard
            elif is_breakout or is_breakdown:
                dir_match = (is_breakout and st_dir == 1) or (is_breakdown and st_dir == -1)
                
                if dir_match:
                    logger.info(f"🔍 Initial Breakout for {symbol} @ {ltp}. Waiting for pullback confirmation...")
                    state['pending_pullback'] = {
                        'type': 'LONG' if is_breakout else 'SHORT',
                        'ts': dt,
                        'level': ltp
                    }
                else:
                    reason = "SuperTrend mismatch"
                    if is_breakout:
                        logger.debug(f"🙅 [ORB_V1] LONG breakout for {symbol} @ {ltp} rejected: {reason}")
                    else:
                        logger.debug(f"🙅 [ORB_V1] SHORT breakdown for {symbol} @ {ltp} rejected: {reason}")
        
        # EXIT LOGIC (Wait for SL/Target or End of Day handled in main.py)
        # Note: Position state management is handled by PaperExchange, 
        # but we could return exit signals here if SL/Target hit in tick data.
        
        return None
