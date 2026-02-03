# Intraday Trading Configuration - Summary

## Capital & Currency
✅ **Currency**: Indian Rupees (₹)  
✅ **Starting Capital**: ₹20,000  
✅ **Current Capital**: ₹20,000 (Reset complete)

## Position Sizing (Risk Management)
- **Risk Per Trade**: 1% of capital (₹200 max loss)
- **Capital Allocation**: 10% per position (₹2,000)
- **Max Positions**: Up to 10 concurrent trades
- **Position Size Calculation**: Dynamic based on stock price
  - Example: For ₹1,445 stock (Reliance) → 1 share
  - Example: For ₹952 stock (HDFC Bank) → 2 shares

## Intraday Compliance
✅ **EOD Square-Off**: Automatic position exit at **3:20 PM IST**  
- All open positions forcefully closed before market close (3:30 PM)
- Prevents overnight holdings (strict intraday compliance)

## Strategy Parameters (Multi-Factor)
**Entry Conditions** (All must be true):
1. Price > VWAP (Trading above average)
2. RSI > 50 (Positive momentum)
3. OBI > 0 (Buy-side order pressure)

**Exit Conditions** (Any one):
1. Price < VWAP (Trend broken)
2. RSI < 45 (Momentum lost)
3. Time >= 3:20 PM (EOD cutoff)

## Key Files Modified
- [`schema.py`](file:///Users/suprathps/code/quant-platform/services/strategy_runtime/schema.py#L39): Default balance updated to ₹20,000
- [`paper_exchange.py`](file:///Users/suprathps/code/quant-platform/services/strategy_runtime/paper_exchange.py#L14-L28): Dynamic position sizing added
- [`main.py`](file:///Users/suprathps/code/quant-platform/services/strategy_runtime/main.py#L104-L128): EOD square-off logic implemented

## Next Steps for Optimization
1. **Backtest** the strategy on historical data to tune parameters
2. **Adjust RSI Threshold** (currently 50) based on market volatility
3. **Add Stop-Loss**: Implement automatic exit at -2% loss per trade
4. **Add Profit Target**: Take profit at +3% gain
5. **Increase Capital**: Once confident, scale to ₹50,000 or more
