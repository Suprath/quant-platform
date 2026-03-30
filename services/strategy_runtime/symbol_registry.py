# services/strategy_runtime/symbol_registry.py
import threading

class SymbolRegistry:
    """Thread-safe bidirectional mapping between Upstox string keys and C++ integer IDs."""

    def __init__(self, max_symbols: int = 1000):
        self.max_symbols = max_symbols
        self._key_to_id: dict = {}
        self._id_to_key: list = [None] * max_symbols
        self._next_id = 0
        self._lock = threading.Lock()

    def register(self, key: str):
        """Register a symbol key and return its integer ID. Returns None if at capacity."""
        with self._lock:
            if key in self._key_to_id:
                return self._key_to_id[key]
            if self._next_id >= self.max_symbols:
                return None
            idx = self._next_id
            self._key_to_id[key] = idx
            self._id_to_key[idx] = key
            self._next_id += 1
            return idx

    def get_id(self, key: str):
        return self._key_to_id.get(key)

    def get_key(self, idx: int):
        if 0 <= idx < self.max_symbols:
            return self._id_to_key[idx]
        return None

    def size(self) -> int:
        return self._next_id
