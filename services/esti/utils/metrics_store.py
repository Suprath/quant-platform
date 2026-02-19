"""
MetricsStore — Thread-Safe History Tracking & Streaming

Accumulates training and backtest metrics across walk-forward cycles.
Supports SSE streaming for real-time dashboard updates.
"""

import asyncio
import json
import time
from collections import deque
from threading import Lock
from typing import Dict, List, Optional, Any
from config import setup_logger

logger = setup_logger("esti.utils.metrics_store")


class MetricsStore:
    """
    Central store for all ESTI metrics (training & backtest).
    Thread-safe and async-friendly for SSE streaming.
    """

    def __init__(self, max_history: int = 2000):
        self._lock = Lock()
        self._max_history = max_history

        # Global history
        self.history: List[Dict[str, Any]] = []

        # Current cycle metrics (reset every cycle)
        self.current_cycle: Dict[str, Any] = {}

        # Async queues for SSE subscribers
        self._subscribers: List[asyncio.Queue] = []

    def log(self, category: str, data: Dict[str, Any]):
        """
        Log a new metric event.
        
        Args:
            category: 'epoch', 'cycle', 'backtest', 'pressure', etc.
            data: metric payload
        """
        event = {
            "timestamp": time.time(),
            "category": category,
            "data": data
        }

        with self._lock:
            self.history.append(event)
            if len(self.history) > self._max_history:
                self.history.pop(0)

            # Update current cycle overview if applicable
            if category == 'cycle':
                self.current_cycle = data

        # push to streaming clients (non-blocking)
        self._notify_subscribers(event)

    def get_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent history."""
        with self._lock:
            return self.history[-limit:]

    def get_cycles(self) -> List[Dict[str, Any]]:
        """Get only cycle-level summaries."""
        with self._lock:
            return [e["data"] for e in self.history if e["category"] == "cycle"]

    async def stream(self):
        """Async generator for SSE streaming."""
        queue = asyncio.Queue()
        with self._lock:
            self._subscribers.append(queue)

        try:
            # Send initial history burst (optional)
            # await queue.put({"type": "history", "data": self.get_history(50)})

            while True:
                event = await queue.get()
                if isinstance(event, dict) and event.get("type") == "shutdown":
                    break
                yield f"data: {json.dumps(event)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            with self._lock:
                if queue in self._subscribers:
                    self._subscribers.remove(queue)

    def _notify_subscribers(self, event: Dict[str, Any]):
        """Push event to all active SSE queues."""
        # Using a copy of the list to perform safe removal during iteration if needed
        # (though removal happens in the streaming task separately)
        subscribers = list(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # Drop events if client is too slow

    def clear(self):
        """Reset all metrics."""
        with self._lock:
            self.history.clear()
            self.current_cycle.clear()
