"""
CrUX API client — SYNC httpx (D-01: core is sync, FastMCP threadpools it). FEAT-002, REQ-CRUX-*.
queryRecord (current) for the walking skeleton; queryHistoryRecord lands in Phase 1.3+.
Parsing shape verified against reference/fixtures/crux-current-wikipedia-phone.json.
"""
from __future__ import annotations

import httpx

from .keyring import Keyring
from .logging import get_logger

CRUX_QUERY_RECORD = "https://chromeuxreport.googleapis.com/v1/records:queryRecord"
CRUX_QUERY_HISTORY = "https://chromeuxreport.googleapis.com/v1/records:queryHistoryRecord"
_log = get_logger("crux_client")


class CruxClient:
    def __init__(self, keyring: Keyring, timeout_s: float = 30.0) -> None:
        self._keyring = keyring
        self._timeout = timeout_s

    def query_record(self, target: str, form_factor: str | None = "PHONE") -> dict | None:
        """
        POST queryRecord. Returns parsed JSON, or None on 404 (no CrUX data — normal, REQ-CRUX-005).
        `target` is an origin (https://example.com) or a specific url. origin XOR url (REQ-CRUX-007).
        """
        lease = self._keyring.acquire(max_wait_s=0.0)
        body: dict = {"origin": target} if _is_origin(target) else {"url": target}
        if form_factor:
            body["formFactor"] = form_factor
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(
                CRUX_QUERY_RECORD, params={"key": lease.key},
                json=body, headers={"Content-Type": "application/json"},
            )
        if resp.status_code == 404:
            _log.info("crux_no_data", target=target, form_factor=form_factor)
            return None
        if resp.status_code == 429:
            self._keyring.mark_rate_limited(lease, _retry_after(resp))
        resp.raise_for_status()
        return resp.json()


    def query_history(self, origin: str, form_factor: str | None = "PHONE",
                      period_count: int = 40) -> dict | None:
        """POST queryHistoryRecord — up to 40 weekly-spaced 28-day windows (REQ-CRUX-002)."""
        lease = self._keyring.acquire(max_wait_s=0.0)
        body: dict = {"origin": origin, "collectionPeriodCount": min(period_count, 40)}
        if form_factor:
            body["formFactor"] = form_factor
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(CRUX_QUERY_HISTORY, params={"key": lease.key},
                               json=body, headers={"Content-Type": "application/json"})
        if resp.status_code == 404:
            return None
        if resp.status_code == 429:
            self._keyring.mark_rate_limited(lease, _retry_after(resp))
        resp.raise_for_status()
        return resp.json()


def _is_origin(target: str) -> bool:
    """An origin has no path beyond '/'. A specific URL has a path."""
    t = target.rstrip("/")
    after_scheme = t.split("://", 1)[-1]
    return "/" not in after_scheme


def _retry_after(resp: httpx.Response) -> int | None:
    val = resp.headers.get("Retry-After")
    try:
        return int(val) if val else None
    except (TypeError, ValueError):
        return None
