# services/eod_ingestor/main.py
"""
NSE EOD Bhavcopy Ingestor
Downloads daily delivery data from NSE archives and upserts conviction scores to PostgreSQL.
Scheduled via APScheduler at 18:30 IST (13:00 UTC) Monday-Friday.
Falls back to secondary URL if primary fails.
"""
import os
import io
import logging
import datetime
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("eod_ingestor")

DB_URL = os.getenv("DATABASE_URL", "postgresql://quant:quant@localhost:5432/kira_state")
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}


def _month_abbr(date_str: str) -> str:
    months = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]
    month_idx = int(date_str[2:4]) - 1
    return months[month_idx]


def _bhavcopy_urls(date_str: str) -> list:
    """Return candidate download URLs in priority order. date_str = DDMMYYYY."""
    return [
        f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv",
        f"https://www1.nseindia.com/content/historical/EQUITIES/{date_str[4:]}/{_month_abbr(date_str)}/cm{date_str}bhav.csv.zip",
    ]


def _fetch_bhavcopy_csv(date: datetime.date):
    """Download raw CSV content. Tries primary then secondary URL. Returns None on failure."""
    import requests
    date_str = date.strftime("%d%m%Y")
    for url in _bhavcopy_urls(date_str):
        try:
            logger.info(f"Fetching: {url}")
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200 and len(r.content) > 1000:
                return r.text
            logger.warning(f"HTTP {r.status_code} from {url}")
        except requests.RequestException as e:
            logger.warning(f"Request failed for {url}: {e}")
    return None


def parse_bhavcopy(source) -> pd.DataFrame:
    """
    Parse raw Bhavcopy CSV. Returns DataFrame with EQ-series rows + conviction_score.
    conviction_score = DELIV_QTY / TOTTRDQTY (delivery percentage as ratio 0-1).
    source: file-like object or string path.
    """
    df = pd.read_csv(source)
    df.columns = df.columns.str.strip()

    # Find the series column (handle whitespace variations)
    series_col = None
    for c in df.columns:
        if c.strip().upper() == "SERIES":
            series_col = c
            break

    if series_col:
        df = df[df[series_col].str.strip() == "EQ"].copy()

    # Normalise column names
    df.columns = [c.strip().upper() for c in df.columns]

    # Numeric coercion
    for col in ("TOTTRDQTY", "DELIV_QTY"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Conviction score
    def _score(row):
        qty = row.get("TOTTRDQTY", 0)
        deliv = row.get("DELIV_QTY", 0)
        return float(deliv) / float(qty) if qty and qty > 0 else 0.0

    df["conviction_score"] = df.apply(_score, axis=1)

    return df.reset_index(drop=True)


def _ensure_table(engine) -> None:
    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS eod_bhavcopy (
                id               SERIAL PRIMARY KEY,
                trade_date       DATE NOT NULL,
                symbol           VARCHAR(20) NOT NULL,
                isin             VARCHAR(15),
                series           VARCHAR(5),
                open             DOUBLE PRECISION,
                high             DOUBLE PRECISION,
                low              DOUBLE PRECISION,
                close            DOUBLE PRECISION,
                total_qty        BIGINT,
                deliv_qty        BIGINT,
                conviction_score DOUBLE PRECISION,
                ingested_at      TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (trade_date, symbol)
            )
        """))
        conn.commit()


def ingest_bhavcopy(target_date=None) -> bool:
    """Main ingestion function. Returns True on success."""
    from sqlalchemy import create_engine, text
    date = target_date or datetime.date.today()
    raw_csv = _fetch_bhavcopy_csv(date)
    if not raw_csv:
        logger.error(f"Could not download Bhavcopy for {date}.")
        return False

    df = parse_bhavcopy(io.StringIO(raw_csv))
    if df.empty:
        logger.warning("Parsed Bhavcopy is empty.")
        return False

    engine = create_engine(DB_URL)
    _ensure_table(engine)

    with engine.connect() as conn:
        for _, row in df.iterrows():
            conn.execute(text("""
                INSERT INTO eod_bhavcopy
                    (trade_date, symbol, isin, series, open, high, low, close,
                     total_qty, deliv_qty, conviction_score)
                VALUES
                    (:trade_date, :symbol, :isin, :series, :open, :high, :low, :close,
                     :total_qty, :deliv_qty, :conviction_score)
                ON CONFLICT (trade_date, symbol) DO UPDATE SET
                    conviction_score = EXCLUDED.conviction_score,
                    deliv_qty        = EXCLUDED.deliv_qty,
                    total_qty        = EXCLUDED.total_qty,
                    ingested_at      = NOW()
            """), {
                "trade_date": date,
                "symbol":     str(row.get("SYMBOL", "")).strip(),
                "isin":       str(row.get("ISIN", "")).strip(),
                "series":     "EQ",
                "open":       float(row.get("OPEN", 0) or 0),
                "high":       float(row.get("HIGH", 0) or 0),
                "low":        float(row.get("LOW", 0) or 0),
                "close":      float(row.get("CLOSE") or row.get("LAST", 0) or 0),
                "total_qty":  int(row.get("TOTTRDQTY", 0) or 0),
                "deliv_qty":  int(row.get("DELIV_QTY", 0) or 0),
                "conviction_score": float(row.get("conviction_score", 0)),
            })
        conn.commit()

    logger.info(f"Ingested {len(df)} EQ symbols for {date}")
    return True


if __name__ == "__main__":
    from apscheduler.schedulers.blocking import BlockingScheduler
    scheduler = BlockingScheduler(timezone="Asia/Kolkata")
    scheduler.add_job(ingest_bhavcopy, "cron", day_of_week="mon-fri", hour=18, minute=30)
    logger.info("EOD Bhavcopy Ingestor started. Next run at 18:30 IST on trading days.")
    scheduler.start()
