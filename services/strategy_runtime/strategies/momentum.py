import logging
import os

logger = logging.getLogger("MomentumStrategy")

class MomentumStrategy:
    def __init__(self, strategy_id="MOMENTUM_V1", backtest_mode=False):
        self.strategy_id = strategy_id
        self.backtest_mode = backtest_mode
        
        if self.backtest_mode:
            logger.info("🧪 Strategy running in BACKTEST MODE (OBI requirement disabled)")
        else:
            logger.info("📈 Strategy running in LIVE MODE (Full multi-factor logic)")

    def on_tick(self, tick, current_qty, balance=5000, avg_price=None):
        symbol = tick.get('symbol')
        ltp = float(tick.get('ltp', 0))
        vwap = float(tick.get('vwap', 0))
        rsi = float(tick.get('rsi', 50)) 
        obi = float(tick.get('obi', 0))

        if self.backtest_mode:
             logger.info(f"DEBUG [{symbol}]: ltp={ltp}, vwap={vwap}, rsi={rsi}, qty={current_qty}")

        # Guard clause for invalid data
        if ltp == 0 or vwap == 0:
            return None

        signal = None

        # --- DUAL-MODE LOGIC: MULTI-FACTOR MOMENTUM ---
        # 1. ENTRY LOGIC
        if self.backtest_mode:
            entry_condition = (ltp > vwap) and (rsi > 50) and (current_qty == 0)
        else:
            entry_condition = (ltp > vwap) and (rsi > 50) and (obi > 0) and (current_qty == 0)
        
        if entry_condition:
            mode_label = "BACKTEST" if self.backtest_mode else "LIVE"
            logger.info(f"⚡ [{mode_label}] SIGNAL BUY: {symbol} | LTP:{ltp} > VWAP:{vwap} | RSI:{rsi} | OBI:{obi}")
            signal = {
                "strategy_id": self.strategy_id,
                "symbol": symbol,
                "action": "BUY",
                "price": ltp
            }

        # 2. EXIT LOGIC
        elif ((ltp < vwap) or (rsi < 45)) and (current_qty > 0):
            mode_label = "BACKTEST" if self.backtest_mode else "LIVE"
            logger.info(f"⚡ [{mode_label}] SIGNAL SELL: {symbol} | LTP:{ltp} vs VWAP:{vwap} | RSI:{rsi}")
            signal = {
                "strategy_id": self.strategy_id,
                "symbol": symbol,
                "action": "SELL",
                "price": ltp
            }

        return signal
