"""
TimeSync Module — Centralized Time Authority
=============================================
Single source of truth for timezone handling, market-hours logic,
and the NSE trading calendar across the entire quant-platform ecosystem.

All services should import from here instead of rolling their own
IST / market-hour checks.
"""

from datetime import datetime, timezone, timedelta, date, time as dt_time
from typing import Optional, List
import logging

logger = logging.getLogger("TimeSync")

# ────────────────────────────────────────────────────────────
# 1.  TIMEZONE CONSTANTS
# ────────────────────────────────────────────────────────────

IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc

# ────────────────────────────────────────────────────────────
# 2.  CORE CONVERSION HELPERS
# ────────────────────────────────────────────────────────────

def to_ist(dt_obj: datetime, backtest_mode: bool = False) -> datetime:
    """
    Normalise any datetime to IST.

    Rules:
      • Naive + backtest  → treat as already IST (QuestDB stores IST)
      • Naive + live      → treat as UTC, convert to IST
      • Aware             → convert to IST regardless
    """
    if dt_obj.tzinfo is None:
        if backtest_mode:
            return dt_obj.replace(tzinfo=IST)
        else:
            return dt_obj.replace(tzinfo=UTC).astimezone(IST)
    return dt_obj.astimezone(IST)


def now_ist() -> datetime:
    """Current wall-clock time in IST."""
    return datetime.now(IST)


def to_utc(dt_obj: datetime) -> datetime:
    """Convert any datetime to UTC."""
    if dt_obj.tzinfo is None:
        return dt_obj.replace(tzinfo=UTC)
    return dt_obj.astimezone(UTC)


def make_ist(year: int, month: int, day: int,
             hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    """Convenience builder for an IST-aware datetime."""
    return datetime(year, month, day, hour, minute, second, tzinfo=IST)


# ────────────────────────────────────────────────────────────
# 3.  NSE MARKET HOURS
# ────────────────────────────────────────────────────────────

# Regular trading session
MARKET_OPEN   = dt_time(9, 15)    # 09:15 IST
MARKET_CLOSE  = dt_time(15, 30)   # 15:30 IST

# Pre-open auction
PRE_OPEN_START = dt_time(9, 0)    # 09:00 IST
PRE_OPEN_END   = dt_time(9, 15)   # 09:15 IST

# MIS square-off window
SQUARE_OFF_START = dt_time(15, 20)  # 15:20 IST
SQUARE_OFF_END   = dt_time(15, 30)  # 15:30 IST


def is_market_open(dt_obj: datetime, backtest_mode: bool = False) -> bool:
    """
    Check if the given time falls within NSE regular trading hours
    (09:15 – 15:30 IST) on a valid trading day.
    """
    ist = to_ist(dt_obj, backtest_mode)
    t = ist.time()

    if not is_trading_day(ist.date()):
        return False

    return MARKET_OPEN <= t <= MARKET_CLOSE


def is_pre_market(dt_obj: datetime, backtest_mode: bool = False) -> bool:
    """Check if time is in the NSE pre-open auction window (09:00–09:15)."""
    ist = to_ist(dt_obj, backtest_mode)
    t = ist.time()
    return PRE_OPEN_START <= t < PRE_OPEN_END


def is_square_off_window(dt_obj: datetime, backtest_mode: bool = False) -> bool:
    """
    Check if time is in the MIS auto-square-off window (15:20–15:30).
    Brokers typically begin liquidating intraday positions here.
    """
    ist = to_ist(dt_obj, backtest_mode)
    t = ist.time()
    return SQUARE_OFF_START <= t <= SQUARE_OFF_END


def market_open_today(ref: Optional[datetime] = None) -> datetime:
    """Return today's (or ref date's) market open as an IST datetime."""
    d = (ref or now_ist()).date() if ref is None or isinstance(ref, datetime) else ref
    if isinstance(d, datetime):
        d = d.date()
    return datetime.combine(d, MARKET_OPEN, tzinfo=IST)


def market_close_today(ref: Optional[datetime] = None) -> datetime:
    """Return today's (or ref date's) market close as an IST datetime."""
    d = (ref or now_ist()).date() if ref is None or isinstance(ref, datetime) else ref
    if isinstance(d, datetime):
        d = d.date()
    return datetime.combine(d, MARKET_CLOSE, tzinfo=IST)


def next_market_open(dt_obj: Optional[datetime] = None) -> datetime:
    """
    Return the next market open time (skipping weekends and holidays).
    If already before today's open on a trading day, returns today's open.
    """
    ist = to_ist(dt_obj, False) if dt_obj else now_ist()
    d = ist.date()

    # If before today's open and today is a trading day, return today
    if is_trading_day(d) and ist.time() < MARKET_OPEN:
        return datetime.combine(d, MARKET_OPEN, tzinfo=IST)

    # Otherwise, advance day-by-day
    d += timedelta(days=1)
    for _ in range(14):  # Max lookahead 2 weeks
        if is_trading_day(d):
            return datetime.combine(d, MARKET_OPEN, tzinfo=IST)
        d += timedelta(days=1)

    # Fallback  (should never reach)
    return datetime.combine(d, MARKET_OPEN, tzinfo=IST)


# ────────────────────────────────────────────────────────────
# 4.  NSE TRADING CALENDAR & HOLIDAYS
# ────────────────────────────────────────────────────────────

# Official NSE holidays (non-trading days) for FY 2024-2026
# Source: NSE circulars.  Partial list — extend as NSE publishes new years.
NSE_HOLIDAYS = {
    # 2024
    date(2024, 1, 26),   # Republic Day
    date(2024, 3, 8),    # Maha Shivaratri
    date(2024, 3, 25),   # Holi
    date(2024, 3, 29),   # Good Friday
    date(2024, 4, 11),   # Id-Ul-Fitr (Eid)
    date(2024, 4, 14),   # Dr. Ambedkar Jayanti
    date(2024, 4, 17),   # Ram Navami
    date(2024, 4, 21),   # Mahavir Jayanti
    date(2024, 5, 1),    # Maharashtra Day
    date(2024, 5, 23),   # Buddha Purnima
    date(2024, 6, 17),   # Eid-Ul-Adha (Bakri Id)
    date(2024, 7, 17),   # Muharram
    date(2024, 8, 15),   # Independence Day
    date(2024, 9, 16),   # Milad-Un-Nabi
    date(2024, 10, 2),   # Mahatma Gandhi Jayanti
    date(2024, 10, 12),  # Dussehra
    date(2024, 11, 1),   # Diwali-Laxmi Pujan
    date(2024, 11, 15),  # Guru Nanak Jayanti
    date(2024, 12, 25),  # Christmas

    # 2025
    date(2025, 1, 26),   # Republic Day
    date(2025, 2, 26),   # Maha Shivaratri
    date(2025, 3, 14),   # Holi
    date(2025, 3, 31),   # Id-Ul-Fitr (Eid)
    date(2025, 4, 10),   # Shri Mahavir Jayanti
    date(2025, 4, 14),   # Dr. Ambedkar Jayanti
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 1),    # Maharashtra Day
    date(2025, 5, 12),   # Buddha Purnima
    date(2025, 6, 7),    # Eid-Ul-Adha (Bakri Id)
    date(2025, 7, 6),    # Muharram
    date(2025, 8, 15),   # Independence Day
    date(2025, 8, 16),   # Janmashtami
    date(2025, 8, 27),   # Ganesh Chaturthi
    date(2025, 9, 5),    # Milad-Un-Nabi
    date(2025, 10, 2),   # Mahatma Gandhi Jayanti / Dussehra
    date(2025, 10, 21),  # Diwali-Laxmi Pujan
    date(2025, 10, 22),  # Diwali-Balipratipada
    date(2025, 11, 5),   # Guru Nanak Jayanti
    date(2025, 12, 25),  # Christmas

    # 2026
    date(2026, 1, 26),   # Republic Day
    date(2026, 2, 17),   # Maha Shivaratri
    date(2026, 3, 3),    # Holi
    date(2026, 3, 20),   # Id-Ul-Fitr (Eid)
    date(2026, 3, 30),   # Shri Mahavir Jayanti
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr. Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day / Buddha Purnima
    date(2026, 5, 28),   # Eid-Ul-Adha (Bakri Id)
    date(2026, 6, 25),   # Muharram
    date(2026, 8, 15),   # Independence Day
    date(2026, 8, 25),   # Milad-Un-Nabi
    date(2026, 10, 2),   # Mahatma Gandhi Jayanti
    date(2026, 10, 19),  # Dussehra
    date(2026, 11, 9),   # Diwali-Laxmi Pujan
    date(2026, 11, 24),  # Guru Nanak Jayanti
    date(2026, 12, 25),  # Christmas
}


def is_trading_day(d: date) -> bool:
    """
    Check if `d` is a valid NSE trading day.
    Excludes weekends (Sat/Sun) and gazetted NSE holidays.
    """
    if isinstance(d, datetime):
        d = d.date()
    # Weekend check
    if d.weekday() >= 5:
        return False
    # Holiday check
    if d in NSE_HOLIDAYS:
        return False
    return True


def trading_days_between(start: date, end: date) -> int:
    """
    Count the number of valid trading days between `start` and `end` (inclusive).
    """
    if isinstance(start, datetime):
        start = start.date()
    if isinstance(end, datetime):
        end = end.date()

    if start > end:
        start, end = end, start

    count = 0
    current = start
    while current <= end:
        if is_trading_day(current):
            count += 1
        current += timedelta(days=1)
    return count


def get_trading_days(start: date, end: date) -> List[date]:
    """
    Return a sorted list of valid NSE trading days between `start` and `end` (inclusive).
    """
    if isinstance(start, datetime):
        start = start.date()
    if isinstance(end, datetime):
        end = end.date()

    if start > end:
        start, end = end, start

    days = []
    current = start
    while current <= end:
        if is_trading_day(current):
            days.append(current)
        current += timedelta(days=1)
    return days


def seconds_to_market_open(dt_obj: Optional[datetime] = None) -> float:
    """Seconds remaining until the next market open. Negative if market is already open."""
    nmo = next_market_open(dt_obj)
    now = to_ist(dt_obj, False) if dt_obj else now_ist()
    return (nmo - now).total_seconds()
