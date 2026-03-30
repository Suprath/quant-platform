"""
QuestDB ILP (InfluxDB Line Protocol) writer for high-throughput tick persistence.
Uses port 9009. Designed to be called with a shared Sender instance for batching.
"""
import logging

logger = logging.getLogger("ilp_writer")


def write_ticks_ilp(ticks: list, sender) -> None:
    """
    Write a batch of ticks to QuestDB via ILP.
    Each tick dict must have: instrument_token, last_price, volume, exchange_timestamp (ms).
    Invalid rows are skipped. Flushes the batch at the end.
    """
    for tick in ticks:
        try:
            token = tick["instrument_token"]
            ltp   = float(tick["last_price"])
            volume = int(tick["volume"])
            oi    = int(tick.get("oi", 0))
            ts_ms = int(tick["exchange_timestamp"])
            ts_ns = ts_ms * 1_000_000  # QuestDB expects nanoseconds
        except (KeyError, TypeError, ValueError):
            continue  # Skip malformed ticks

        sender.row(
            "ticks",
            symbols={"instrument_token": token},
            columns={"ltp": ltp, "volume": volume, "oi": oi},
            at=ts_ns,
        )

    sender.flush()
