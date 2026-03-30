"""
Queries PostgreSQL eod_bhavcopy for the top N symbols by institutional conviction score.
Called at market open to seed the ingestor's subscription list.
"""
import os
import logging
from sqlalchemy import create_engine, text

logger = logging.getLogger("conviction_ranker")
DB_URL = os.getenv("DATABASE_URL", "postgresql://quant:quant@localhost:5432/kira_state")


def _query_top_symbols(engine, top_n: int, lookback_days: int) -> list:
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT symbol, AVG(conviction_score) AS conviction_score "
            "FROM eod_bhavcopy "
            "WHERE trade_date >= CURRENT_DATE - INTERVAL ':days days' "
            "  AND series = 'EQ' "
            "GROUP BY symbol "
            "ORDER BY conviction_score DESC "
            "LIMIT :top_n"
        ), {"days": lookback_days, "top_n": top_n})
        return [dict(row._mapping) for row in result]


def get_top_symbols_by_conviction(top_n: int = 500, lookback_days: int = 5) -> list:
    """
    Returns top N NSE symbols ranked by average conviction_score over the last lookback_days.
    Returns [] if table is empty or DB unavailable.
    """
    try:
        engine = create_engine(DB_URL)
        rows = _query_top_symbols(engine, top_n, lookback_days)
        return [r["symbol"] for r in rows][:top_n]
    except Exception as e:
        logger.warning(f"Conviction ranker query failed: {e}")
        return []
