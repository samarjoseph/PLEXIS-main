"""
Presentation Layer — Explanation Cache

Caches module LLM explanations by (fingerprint, module_id, prompt_version).

Key design (audit fix):
  - prompt_version is part of the key: stale explanations are auto-invalidated
    when a module system prompt is improved (new version = new cache entry)
  - session_id is NOT part of the key: explanations are dataset-level
  - Max 500 entries, LRU eviction
  - TTL: 7 days (explanations don't change unless prompt changes)
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Optional

from .domain.contracts import ExplanationCacheKey

MAX_ENTRIES = 500
TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days


class ExplanationCache:
    """
    Thread-safe LRU + TTL cache for module explanations.
    """

    def __init__(self, max_entries: int = MAX_ENTRIES, ttl: int = TTL_SECONDS) -> None:
        self._max = max_entries
        self._ttl = ttl
        self._store: OrderedDict[ExplanationCacheKey, tuple] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: ExplanationCacheKey) -> Optional[str]:
        """Return cached explanation or None if missing/expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            text, stored_at = entry
            if time.time() - stored_at > self._ttl:
                del self._store[key]
                return None
            self._store.move_to_end(key)
            return text

    def set(self, key: ExplanationCacheKey, text: str) -> None:
        """Store an explanation. Evicts LRU if at capacity."""
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (text, time.time())
            self._store.move_to_end(key)
            while len(self._store) > self._max:
                self._store.popitem(last=False)

    def size(self) -> int:
        return len(self._store)


# Module-level singleton
explanation_cache = ExplanationCache()
