import asyncio
import logging
from src.backtest_logic import BacktestController

logging.basicConfig(level=logging.INFO)

async def main():
    ctrl = BacktestController()
    # symbols observed in QuestDB
    symbols = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK']
    await ctrl.run_backtest(
        symbols=symbols,
        start_date='2024-03-01',
        end_date='2024-03-02'
    )

if __name__ == "__main__":
    asyncio.run(main())
