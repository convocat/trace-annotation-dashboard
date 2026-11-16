"""In-memory session cache for fetched traces.

Traces fetched from Langfuse live here only for the lifetime of the dashboard
process. Never written to disk — so if Python stops, the cache is gone and
message bodies are only reachable via Langfuse again.

This is a deliberate safety choice: PII in traces should not accumulate on local
disk. The cache gives us UI snappiness without the disk footprint.
"""

from __future__ import annotations

from collections import OrderedDict
from threading import RLock

from .loaders.base import Trace


class TraceCache:
    """LRU cache. Bounded by entry count, not bytes (traces vary wildly in size)."""

    def __init__(self, max_entries: int = 500) -> None:
        self._max = max_entries
        self._store: "OrderedDict[str, Trace]" = OrderedDict()
        self._lock = RLock()

    def get(self, trace_id: str) -> Trace | None:
        with self._lock:
            if trace_id not in self._store:
                return None
            self._store.move_to_end(trace_id)
            return self._store[trace_id]

    def put(self, trace: Trace) -> None:
        with self._lock:
            self._store[trace.id] = trace
            self._store.move_to_end(trace.id)
            while len(self._store) > self._max:
                self._store.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)
