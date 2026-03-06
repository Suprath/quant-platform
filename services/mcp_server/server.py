from mcp.server.fastmcp import FastMCP
import httpx
import json
from typing import Optional, Dict
from starlette.middleware.cors import CORSMiddleware

# Initialize FastMCP Server
mcp = FastMCP("Kira")

# Point to the api_gateway container inside the docker network
API_BASE_URL = "http://api_gateway:8000/api/v1"

@mcp.tool()
async def get_kira_documentation() -> str:
    """Get the KIRA Python framework rules and API reference for writing strategies.
    
    CALL THIS BEFORE WRITING ANY STRATEGY CODE to understand the exact syntax,
    available indicators, loop conventions, and portfolio state objects.
    """
    return """
# KIRA Strategy Framework API (Token Optimized)

1. CLASS STRUCTURE: All strategies MUST inherit `from quant_sdk.algorithm import QCAlgorithm`.
2. REQUIRED METHODS:
   - `def Initialize(self):` -> Set cash, subscriptions, and indicators.
   - `def OnData(self, data):` -> The tick loop. `data` is a `Slice` object.

3. QCAlgorithm METHODS (use with `self.`):
   - `SetCash(amount: float)`
   - `SetStartDate(year, month, day)` / `SetEndDate(...)`
   - `AddEquity(symbol: str)` -> EX: `self.AddEquity("NSE_EQ|INE002A01018")` (RELIANCE)
   - `SetHoldings(symbol: str, percentage: float)`
   - `Liquidate(symbol: str = None)`
   - `SMA(symbol, period)` / `EMA(symbol, period)` -> EX: `self.SMA("NSE_EQ|INE002A01018", 20)`
   - `Schedule.On(self.DateRules.EveryDay(), self.TimeRules.At(hour, minute), self.FuncName)`
   - `Debug(msg)` / `Log(msg)`

4. SYMBOL KEYS: 
   - You MUST use the Upstox Instrument Key (Token) for all symbol arguments.
   - Use the `search_symbols` tool to find the correct token (e.g., `NSE_EQ|INE002A01018` for RELIANCE).
   - DO NOT use human-readable names like "RELIANCE" or placeholders like "AAPL".

5. ONDATA / SLICE (`data`):
   - Check if symbol exists: `if data.ContainsKey("NSE_EQ|INE002A01018"):`
   - Get price: `price = data["NSE_EQ|INE002A01018"].Price`

6. INDICATORS:
   - Must be initialized in `Initialize()`, e.g., `self.sma = self.SMA("NSE_EQ|INE002A01018", 14)`
   - Usage in `OnData`: `if self.sma.IsReady: value = self.sma.Current.Value`

7. UNIVERSE SELECTION (DYNAMIC):
   - Definition: `self.AddUniverse(self.CoarseSelectionFunction)` in `Initialize()`.
   - The function receives a list of `candidates` (dicts with `symbol` and `score`).
   - `score` is a combination of Relative Strength (RS) vs Nifty 50 and Volume.
   - Example (Top 3 by RS):
     ```python
     def CoarseSelectionFunction(self, candidates):
         # Sort by score (Momentum/RS) descending
         sorted_candidates = sorted(candidates, key=lambda x: x['score'], reverse=True)
         # Return the top 3 symbol strings
         return [x['symbol'] for x in sorted_candidates[:3]]
     ```

8. PORTFOLIO STATE (`self.Portfolio`):
   - Check holdings: `if self.Portfolio["NSE_EQ|INE002A01018"].Invested:`
   - Get total equity: `self.Portfolio.TotalPortfolioValue`

9. BACKTEST WORKFLOW (LLM INSTRUCTIONS):
   - Step 1: Use `search_symbols` to get the correct instrument keys for your strategy.
   - Step 2: Write strategy using ISIN-based keys or AddUniverse for dynamic selection.
   - Step 3: Call `run_backtest`. It returns a `run_id`.
   - Step 4: POLL `get_backtest_status` every 5-10 seconds.
   - Step 5: if status is 'running', WAIT. Do not call stats yet.
   - Step 6: if status is 'completed', call `get_backtest_stats`.
   - Step 7: if status is 'failed', call `get_backtest_logs` to debug.
   - NOTE: Backfills can take 30-60s due to Upstox Free Tier (1 req/s) rate limits. BE PATIENT.
"""

@mcp.tool()
async def list_strategies() -> str:
    """Get a list of all existing trading strategies in the KIRA platform."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{API_BASE_URL}/strategies")
            response.raise_for_status()
            return json.dumps(response.json(), indent=2)
        except Exception as e:
            return f"Error listing strategies: {str(e)}"

@mcp.tool()
async def get_strategy(project_name: str) -> str:
    """Read the python code and files for a specific trading strategy project.
    
    Args:
        project_name: The name of the strategy project (e.g. 'nifty_intraday_momentum')
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{API_BASE_URL}/strategies/project/{project_name}")
            response.raise_for_status()
            return json.dumps(response.json(), indent=2)
        except Exception as e:
            return f"Error reading strategy: {str(e)}"

@mcp.tool()
async def save_strategy(project_name: str, code: str) -> str:
    """Write or update Python code for a strategy project.
    
    Args:
        project_name: Name of the strategy to create/update
        code: The raw Python code implementing QCAlgorithm
    """
    async with httpx.AsyncClient() as client:
        payload = {
            "project_name": project_name,
            "files": {"main.py": code}
        }
        try:
            response = await client.post(f"{API_BASE_URL}/strategies/save-project", json=payload)
            response.raise_for_status()
            return f"Successfully saved strategy '{project_name}'."
        except Exception as e:
            return f"Error saving strategy: {str(e)}"

@mcp.tool()
async def run_backtest(
    strategy_code: str, 
    symbol: str, 
    start_date: str, 
    end_date: str, 
    initial_cash: float, 
    strategy_name: str = "CustomStrategy",
    trading_mode: str = "MIS"
) -> str:
    """Trigger a historical backtest for a strategy on the KIRA engine.
    
    Args:
        strategy_code: The raw Python code of the strategy (must inherit QCAlgorithm)
        symbol: The instrument identifier, e.g. 'NSE_EQ|RELIANCE'
        start_date: YYYY-MM-DD
        end_date: YYYY-MM-DD
        initial_cash: Starting capital
        strategy_name: Optional name for the strategy run
        trading_mode: 'MIS' for Intraday, 'CNC' for Delivery (default: MIS)
        
    LLM INSTRUCTION: This starts an ASYNCHRONOUS process. You must capture the `run_id` 
    and poll `get_backtest_status` until it reaches 'completed' or 'failed'.
    """
    async with httpx.AsyncClient() as client:
        # Automated symbol translation for better LLM UX
        try:
            mapping_resp = await client.get(f"{API_BASE_URL}/backfill/stocks", timeout=10.0)
            if mapping_resp.status_code == 200:
                stock_map = mapping_resp.json()
                name_to_token = {s["name"].upper(): s["token"] for s in stock_map}
                clean_symbol = symbol.split('|')[-1].upper() if '|' in symbol else symbol.upper()
                if clean_symbol in name_to_token:
                    symbol = name_to_token[clean_symbol]
        except Exception:
            pass

        payload = {
            "strategy_code": strategy_code,
            "symbol": symbol,
            "start_date": start_date,
            "end_date": end_date,
            "initial_cash": initial_cash,
            "strategy_name": strategy_name,
            "trading_mode": trading_mode,
            "speed": "fast"
        }
        try:
            response = await client.post(f"{API_BASE_URL}/backtest/run", json=payload, timeout=15.0)
            response.raise_for_status()
            return json.dumps(response.json(), indent=2)  # Returns the run_id
        except Exception as e:
            return f"Error starting backtest: {str(e)}"

@mcp.tool()
async def get_backtest_status(run_id: str) -> str:
    """Check if a backtest is running, completed, or failed.
    
    Args:
        run_id: The UUID of the backtest
        
    LLM INSTRUCTION: Poll this every 5 seconds. If the status is 'running', 
    yield control and wait. If 'failed', use `get_backtest_logs` for a traceback.
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{API_BASE_URL}/backtest/status/{run_id}")
            response.raise_for_status()
            data = response.json()
            return f"Status: {data.get('status', 'Unknown')}"
        except Exception as e:
            return f"Error getting status: {str(e)}"

@mcp.tool()
async def get_backtest_stats(run_id: str) -> str:
    """Get the final statistics (Sharpe, ROI, Drawdown) for a completed backtest.
    
    Args:
        run_id: The UUID of the backtest
        
    LLM INSTRUCTION: Do NOT call this until `get_backtest_status` returns 'completed'.
    Calling this on a running or failed backtest will return an error or empty stats.
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{API_BASE_URL}/backtest/stats/{run_id}")
            response.raise_for_status()
            return json.dumps(response.json(), indent=2)
        except Exception as e:
            return f"Error getting stats: {str(e)}"

@mcp.tool()
async def run_edge_scan(
    symbols: list[str],
    timeframe: str = "1d",
    start_date: str = "2020-01-01",
    end_date: str = "2030-01-01",
    patterns: Optional[list[str]] = None,
    forward_returns_bars: Optional[list[int]] = None
) -> str:
    """Trigger the KIRA Statistical Edge Scanner to find quantitative edges.
    
    This runs a vectorized scan on the time-series database to find occurrences
    of technical patterns and calculates the expected forward returns (e.g., probability
    of price going up 1 day, 3 days, or 5 days after the pattern occurs).
    
    Args:
        symbols: List of instrument identifiers, e.g. ['NSE_EQ|TATAMOTORS', 'NSE_INDEX|Nifty 50']
        timeframe: Resolution of the data (default: '1d')
        start_date: Start scanning from YYYY-MM-DD
        end_date: Stop scanning at YYYY-MM-DD
        patterns: List of patterns to scan (e.g. ['gap_up_fade', 'inside_bar_breakout', 'oversold_bounce'])
        forward_returns_bars: Bars to calculate forward returns for (e.g. [1, 3, 5])
    """
    if patterns is None:
        patterns = ["gap_up_fade", "consecutive_up_days", "inside_bar_breakout", "oversold_bounce", "volatility_contraction"]
        
    if forward_returns_bars is None:
        forward_returns_bars = [1, 3, 5]
        
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Translate human-readable symbols into ISIN format for QuestDB
        try:
            mapping_resp = await client.get(f"{API_BASE_URL}/backfill/stocks", timeout=10.0)
            if mapping_resp.status_code == 200:
                stock_map = mapping_resp.json()
                name_to_token = {s["name"]: s["token"] for s in stock_map}
                
                translated_symbols = []
                for sym in symbols:
                    clean_sym = sym.split('|')[-1] if '|' in sym else sym
                    if clean_sym in name_to_token:
                        translated_symbols.append(name_to_token[clean_sym])
                    else:
                        translated_symbols.append(sym)
                symbols = translated_symbols
        except Exception:
            pass # Fall back to using the LLM's original symbols if mapping fails
            
        payload = {
            "symbols": symbols,
            "timeframe": timeframe,
            "start_date": start_date,
            "end_date": end_date,
            "patterns": patterns,
            "forward_returns_bars": forward_returns_bars
        }
        try:
            response = await client.post(f"{API_BASE_URL}/edge/scan", json=payload)
            response.raise_for_status()
            return json.dumps(response.json(), indent=2)
        except Exception as e:
            return f"Error running edge scan: {str(e)}"

@mcp.tool()
async def get_backtest_logs(run_id: str) -> str:
    """Get the runtime logs and python tracebacks for a backtest to debug crashes.
    
    Args:
        run_id: The UUID of the backtest
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{API_BASE_URL}/backtest/logs/{run_id}")
            response.raise_for_status()
            logs = response.json().get('logs', [])
            return "\\n".join(logs)
        except Exception as e:
            return f"Error getting logs: {str(e)}"

@mcp.tool()
async def search_symbols(query: str = "") -> str:
    """Search for the correct Upstox Instrument Keys (Tokens) for stocks.
    
    USE THIS TOOL to find the correct symbol strings for AddEquity, SMA, etc.
    Examples: 'RELIANCE' -> 'NSE_EQ|INE002A01018', 'SBIN' -> 'NSE_EQ|INE062A01020'
    
    Args:
        query: Optional stock name or partial string to filter by (e.g. 'TATA')
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{API_BASE_URL}/backfill/stocks")
            response.raise_for_status()
            stocks = response.json()
            if query:
                q = query.upper()
                stocks = [s for s in stocks if q in s["name"].upper() or q in s["token"].upper()]
            return json.dumps(stocks, indent=2)
        except Exception as e:
            return f"Error searching symbols: {str(e)}"
# Expose the ASGI app for Uvicorn
if hasattr(mcp, "sse_app"):
    app = mcp.sse_app()
elif hasattr(mcp, "get_starlette_app"):
    app = mcp.get_starlette_app()
else:
    app = None

# Wrap the ASGI app with CORS Middleware to allow web-based MCP clients to connect
if app is not None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
