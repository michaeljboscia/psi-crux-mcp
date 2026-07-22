"""
Key-ring — LRU key selection with 429 cooldown. FEAT-009, REQ-KEY-001/002/014.
Walking-skeleton scope: in-memory (single key / single host). SQLite backend + per-project
quota pools + permanent-fail disable land in Phase 2.3. Original implementation.

QUOTA_COOLDOWN contract (REQ-KEY-014): acquire() never hangs. If all keys are cooling beyond the
caller's max_wait budget, it raises QuotaCooldown with the seconds until the soonest key frees.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


class QuotaCooldown(Exception):
    """Raised when every key is cooling beyond the caller's wait budget (REQ-KEY-014)."""

    def __init__(self, retry_after_seconds: int, cooling_keys: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        self.cooling_keys = cooling_keys
        super().__init__(f"all keys cooling; retry after {retry_after_seconds}s")


@dataclass
class KeyLease:
    key: str
    project_id: str


@dataclass
class _KeyState:
    key: str
    project_id: str
    last_used_at: float = 0.0
    cooldown_until: float = 0.0
    total_uses: int = 0
    total_429s: int = 0


DEFAULT_429_COOLDOWN_S = 120


@dataclass
class Keyring:
    """In-memory LRU keyring. Keys are 'keystring:project_id' strings."""

    _states: list[_KeyState] = field(default_factory=list)

    @classmethod
    def from_pairs(cls, pairs: list[str]) -> "Keyring":
        states = []
        for p in pairs:
            key, _, proj = p.partition(":")
            key = key.strip()
            if key:
                states.append(_KeyState(key=key, project_id=(proj.strip() or "default")))
        if not states:
            raise ValueError("no API keys provided — set PSI_API_KEYS / CRUX_API_KEYS")
        return cls(_states=states)

    def acquire(self, max_wait_s: float = 0.0) -> KeyLease:
        """
        Return the LRU non-cooling key. If all cooling: within max_wait_s, wait to the soonest;
        beyond budget, raise QuotaCooldown (no unbounded hang). REQ-KEY-004/014.
        """
        now = time.time()
        available = [s for s in self._states if s.cooldown_until <= now]
        if available:
            s = min(available, key=lambda x: (x.last_used_at, x.key))
            s.last_used_at = now
            s.total_uses += 1
            return KeyLease(key=s.key, project_id=s.project_id)

        soonest = min(self._states, key=lambda x: x.cooldown_until)
        wait = max(0.0, soonest.cooldown_until - now)
        if wait <= max_wait_s:
            time.sleep(wait)
            return self.acquire(max_wait_s=0.0)
        raise QuotaCooldown(retry_after_seconds=int(wait) + 1, cooling_keys=len(self._states))

    def mark_rate_limited(self, lease: KeyLease, retry_after_seconds: int | None = None) -> None:
        cooldown = max(1, int(retry_after_seconds or DEFAULT_429_COOLDOWN_S))
        now = time.time()
        for s in self._states:
            if s.key == lease.key:
                s.cooldown_until = max(s.cooldown_until, now + cooldown)
                s.total_429s += 1

    def stats(self) -> list[dict]:
        now = time.time()
        return [
            {
                "project_id": s.project_id,
                "cooling": s.cooldown_until > now,
                "total_uses": s.total_uses,
                "total_429s": s.total_429s,
            }
            for s in self._states
        ]
