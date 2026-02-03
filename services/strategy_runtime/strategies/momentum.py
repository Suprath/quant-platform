import logging

logger = logging.getLogger("MomentumStrategy")

class MomentumStrategy:
    def __init__(self, strategy_id="MOMENTUM_V1"):
        self.strategy_id = strategy_id

    def on_tick(self, tick, current_qty):
        """
        Analyzes a tick and returns a Signal (or None).
        tick: {symbol, ltp, vwap, rsi, obi, ...} (Enriched Tick)
        current_qty: int (Current position size for this symbol)
        """
        symbol = tick.get('symbol')
        ltp = float(tick.get('ltp', 0))
        vwap = float(tick.get('vwap', 0))
        rsi = float(tick.get('rsi', 50)) # Default neutral if missing
        obi = float(tick.get('obi', 0))
        
        # Guard clause for invalid data
        if ltp == 0 or vwap == 0:
            return None

        signal = None

        # --- LOGIC: MULTI-FACTOR MOMENTUM ---
        # 1. ENTRY: 
        #    - Price > VWAP (Trading above average)
        #    - RSI > 50 (Positive Momentum)
        #    - OBI > 0 (Buy Side Order Book pressure)
        if (ltp > vwap) and (rsi > 50) and (obi > 0) and (current_qty == 0):
            logger.info(f"⚡ SIGNAL BUY: {symbol} | LTP:{ltp} > VWAP:{vwap} | RSI:{rsi} | OBI:{obi}")
            signal = {
                "strategy_id": self.strategy_id,
                "symbol": symbol,
                "action": "BUY",
                "price": ltp
            }

        # 2. EXIT:
        #    - Price < VWAP (Trend Broken)
        #    OR
        #    - RSI < 50 (Momentum Lost)
        elif ((ltp < vwap) or (rsi < 45)) and (current_qty > 0):
            logger.info(f"⚡ SIGNAL SELL: {symbol} | LTP:{ltp} vs VWAP:{vwap} | RSI:{rsi}")
            signal = {
                "strategy_id": self.strategy_id,
                "symbol": symbol,
                "action": "SELL",
                "price": ltp
            }

        return signal
