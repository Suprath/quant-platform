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
        
        logger.info(f"🚀 {self.strategy_id} Initialized (ORB: {self.orb_minutes}m, Mode: {'BACKTEST' if backtest_mode else 'LIVE'})")

    def _get_or_create_state(self, symbol):
        if symbol not in self.symbol_state:
            self.symbol_state[symbol] = {
                'orb_high': None,
                'orb_low': None,
                'orb_set': False,
                'buffer': [], # To hold recent ticks for ATR/SuperTrend
                'max_buffer': 100,
                'last_processed_minute': -1,
                'last_processed_date': None,
                'active_trade': None, # {type, entry, sl, tgt}
                'trades_today': 0,
                'last_exit_time': None
            }
        return self.symbol_state[symbol]

    MAX_TRADES_PER_DAY = 3
    COOLDOWN_MINUTES = 15
    
    # Strategy Optimization Parameters (Phase 3)
    MIN_ATR_PERCENT = 0.01       # Skip trading if ATR < 0.01% of LTP (extremely narrow)
    TRAILING_STOP_TRIGGER = 1.5  # Move SL to breakeven after 1.5x ATR profit

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
            
            # LONG EXIT
            if trade['type'] == 'LONG':
                # Trailing Stop: Move SL to breakeven after 1.5x ATR profit
                profit = ltp - trade['entry']
                atr_estimate = abs(trade['tgt'] - trade['entry']) / 3.0  # Reverse calc ATR
                if profit >= atr_estimate * self.TRAILING_STOP_TRIGGER and trade['sl'] < trade['entry']:
                    trade['sl'] = trade['entry']  # Lock in breakeven
                    logger.info(f"📈 [ORB_V1] TRAILING STOP ACTIVATED: {symbol} - SL moved to breakeven {trade['entry']}")
                    
                if ltp <= trade['sl']:
                    logger.info(f"🛑 [ORB_V1] STOP LOSS HIT: {symbol} @ {ltp} (Entry: {trade['entry']}, SL: {trade['sl']})")
                    exit_signal = {"strategy_id": self.strategy_id, "symbol": symbol, "action": "SELL", "price": ltp, "reason": "SL_HIT"}
                elif ltp >= trade['tgt']:
                    logger.info(f"🎯 [ORB_V1] TARGET HIT: {symbol} @ {ltp} (Entry: {trade['entry']}, TGT: {trade['tgt']})")
                    exit_signal = {"strategy_id": self.strategy_id, "symbol": symbol, "action": "SELL", "price": ltp, "reason": "TARGET_HIT"}
            
            # SHORT EXIT
            elif trade['type'] == 'SHORT':
                # Trailing Stop: Move SL to breakeven after 1.5x ATR profit
                profit = trade['entry'] - ltp
                atr_estimate = abs(trade['entry'] - trade['tgt']) / 3.0
                if profit >= atr_estimate * self.TRAILING_STOP_TRIGGER and trade['sl'] > trade['entry']:
                    trade['sl'] = trade['entry']  # Lock in breakeven
                    logger.info(f"📉 [ORB_V1] TRAILING STOP ACTIVATED: {symbol} - SL moved to breakeven {trade['entry']}")
                    
                if ltp >= trade['sl']:
                    logger.info(f"🛑 [ORB_V1] STOP LOSS HIT: {symbol} @ {ltp} (Entry: {trade['entry']}, SL: {trade['sl']})")
                    exit_signal = {"strategy_id": self.strategy_id, "symbol": symbol, "action": "BUY", "price": ltp, "reason": "SL_HIT"}
                elif ltp <= trade['tgt']:
                    logger.info(f"🎯 [ORB_V1] TARGET HIT: {symbol} @ {ltp} (Entry: {trade['entry']}, TGT: {trade['tgt']})")
                    exit_signal = {"strategy_id": self.strategy_id, "symbol": symbol, "action": "BUY", "price": ltp, "reason": "TARGET_HIT"}

            if exit_signal:
                state['active_trade'] = None
                state['last_exit_time'] = dt
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
        
        # MIN ATR Filter: Skip trading if volatility is too low
        atr_pct = (atr / ltp) * 100 if ltp > 0 else 0
        
        # DEBUG: Log indicators
        logger.debug(f"📊 {symbol} | Time={dt} | LTP={ltp} | ATR={atr:.2f} ({atr_pct:.2f}%) | ST={st_dir} | ORB=[{state['orb_low']}-{state['orb_high']}] ({orb_range_pct:.2f}%)")
        
        if atr_pct < self.MIN_ATR_PERCENT:
            return None

        if current_qty == 0:
            # 4. ENTRY GUARDRAILS
            if state['trades_today'] >= self.MAX_TRADES_PER_DAY:
                return None
            
            if state['last_exit_time']:
                cooldown_remaining = (dt - state['last_exit_time']).total_seconds() / 60
                if cooldown_remaining < self.COOLDOWN_MINUTES:
                    return None

            # DEBUG: Log breakout potential
            if ltp > state['orb_high'] or ltp < state['orb_low']:
                logger.debug(f"🔍 BREAKOUT DETECTED: {symbol} @ {ltp} (ORB: {state['orb_low']}-{state['orb_high']}, ST: {st_dir}, VWAP: {vwap})")

            # DEBUG: Log breakout potential
            is_breakout = ltp > state['orb_high']
            is_breakdown = ltp < state['orb_low']
            
            if is_breakout or is_breakdown:
                dir_match = (is_breakout and st_dir == 1) or (is_breakdown and st_dir == -1)
                # Removed VWAP check for now to simplify
                
                if dir_match:
                    sl_dist = max(atr * 1.5, ltp * 0.002) # Min 0.2% SL
                    if is_breakout:
                        sl = max(state['orb_low'], ltp - sl_dist)
                        target = ltp + (atr * 3.0)
                        state['active_trade'] = {'type': 'LONG', 'entry': ltp, 'sl': sl, 'tgt': target}
                        logger.info(f"⚡ [ORB_V1] LONG ENTRY: {symbol} @ {ltp} | SL: {sl} | TGT: {target}")
                        action = "BUY"
                    else:
                        sl = min(state['orb_high'], ltp + sl_dist)
                        target = ltp - (atr * 3.0)
                        state['active_trade'] = {'type': 'SHORT', 'entry': ltp, 'sl': sl, 'tgt': target}
                        logger.info(f"⚡ [ORB_V1] SHORT ENTRY: {symbol} @ {ltp} | SL: {sl} | TGT: {target}")
                        action = "SELL"
                    
                    state['trades_today'] += 1
                    return {
                        "strategy_id": self.strategy_id,
                        "symbol": symbol,
                        "action": action,
                        "price": ltp,
                        "stop_loss": sl,
                        "target": target
                    }
                else:
                    if is_breakout:
                        logger.debug(f"🙅 [ORB_V1] LONG breakout for {symbol} @ {ltp} rejected: SuperTrend={st_dir}")
                    else:
                        logger.debug(f"🙅 [ORB_V1] SHORT breakdown for {symbol} @ {ltp} rejected: SuperTrend={st_dir}")
        
        # EXIT LOGIC (Wait for SL/Target or End of Day handled in main.py)
        # Note: Position state management is handled by PaperExchange, 
        # but we could return exit signals here if SL/Target hit in tick data.
        
        return None
