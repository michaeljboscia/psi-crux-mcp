"""Keyring tests — LRU rotation, 429 cooldown, no-hang QUOTA_COOLDOWN. REQ-KEY-002/014."""
import pytest

from psi_crux_core.keyring import Keyring, QuotaCooldown


def test_lru_rotation():
    kr = Keyring.from_pairs(["k1:projA", "k2:projB"])
    first = kr.acquire()
    second = kr.acquire()
    assert first.key != second.key  # LRU rotates to the other key


def test_429_cooldown_removes_key_from_pool():
    kr = Keyring.from_pairs(["k1:projA"])
    lease = kr.acquire()
    kr.mark_rate_limited(lease, retry_after_seconds=60)
    # single key now cooling; acquire with zero budget must NOT hang — raises QUOTA_COOLDOWN
    with pytest.raises(QuotaCooldown) as ei:
        kr.acquire(max_wait_s=0.0)
    assert ei.value.retry_after_seconds >= 1
    assert ei.value.cooling_keys == 1


def test_empty_keyring_rejected():
    with pytest.raises(ValueError):
        Keyring.from_pairs([])


def test_stats_shape():
    kr = Keyring.from_pairs(["k1:projA"])
    kr.acquire()
    s = kr.stats()
    assert s[0]["project_id"] == "projA"
    assert s[0]["total_uses"] == 1
