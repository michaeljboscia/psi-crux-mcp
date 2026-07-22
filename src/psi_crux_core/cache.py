"""In-memory TTL cache. FEAT-022, REQ-ENG-004. Never caches errors."""
from __future__ import annotations

from typing import Any

from cachetools import TTLCache


class ResponseCache:
    def __init__(self, ttl_s: int = 300, maxsize: int = 512) -> None:
        self._c: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl_s)

    def get(self, key: str) -> Any | None:
        return self._c.get(key)

    def set(self, key: str, value: Any) -> None:
        self._c[key] = value

    def clear(self) -> None:
        self._c.clear()
