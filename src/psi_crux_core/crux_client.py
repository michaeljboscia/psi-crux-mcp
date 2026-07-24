"""
CrUX API client — SYNC httpx (D-01: core is sync, FastMCP threadpools it). FEAT-002, REQ-CRUX-*.
queryRecord (current) + queryHistoryRecord (history).
Parsing shape verified against reference/fixtures/crux-current-wikipedia-phone.json.

Hardened per harvest G6: this client previously had NO retry and NO rate throttle, so a
transient 5xx dropped the call outright and a burst walked straight into 429s. CrUX allows
150 queries/minute; GTM paced at 0.414s between calls (a ~145 QPM buffer) and honored
Retry-After. Both are restored here.
"""
from __future__ import annotations

import threading
import time

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .keyring import Keyring
from .logging import get_logger

CRUX_QUERY_RECORD = "https://chromeuxreport.googleapis.com/v1/records:queryRecord"
CRUX_QUERY_HISTORY = "https://chromeuxreport.googleapis.com/v1/records:queryHistoryRecord"

# 150 QPM is the documented CrUX ceiling; 0.414s ≈ 145 QPM leaves headroom for clock skew
# and in-flight overlap. The limit is per-project, so the throttle is process-wide, not
# per-client-instance — separate clients sharing a key would otherwise each pace themselves
# and collectively blow the budget.
CRUX_MIN_INTERVAL_S = 0.414

_log = get_logger("crux_client")


class _Throttle:
    """Process-wide minimum spacing between CrUX calls."""

    def __init__(self, min_interval_s: float) -> None:
        self._min = min_interval_s
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            delta = time.monotonic() - self._last
            if delta < self._min:
                time.sleep(self._min - delta)
            self._last = time.monotonic()


_THROTTLE = _Throttle(CRUX_MIN_INTERVAL_S)


class CruxMalformedResponse(Exception):
    """A 200 whose body is not usable JSON — retryable, not a parser bug."""


def _is_transient(exc: BaseException) -> bool:
    """Retry 5xx + network errors + malformed 200s; never retry 4xx (REQ-ENG-001)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError, CruxMalformedResponse))


class CruxClient:
    def __init__(self, keyring: Keyring, timeout_s: float = 30.0) -> None:
        self._keyring = keyring
        self._timeout = timeout_s

    def query_record(self, target: str, form_factor: str | None = "PHONE") -> dict | None:
        """
        POST queryRecord. Returns parsed JSON, or None on 404 (no CrUX data — normal, REQ-CRUX-005).
        `target` is an origin (https://example.com) or a specific url. origin XOR url (REQ-CRUX-007).
        """
        body: dict = {"origin": target} if _is_origin(target) else {"url": target}
        if form_factor:
            body["formFactor"] = form_factor
        resp = self._post(CRUX_QUERY_RECORD, body)
        if resp is None:
            _log.info("crux_no_data", target=target, form_factor=form_factor)
        return resp

    def query_history(self, origin: str, form_factor: str | None = "PHONE",
                      period_count: int = 40) -> dict | None:
        """POST queryHistoryRecord — up to 40 weekly-spaced 28-day windows (REQ-CRUX-002)."""
        body: dict = {"origin": origin, "collectionPeriodCount": min(period_count, 40)}
        if form_factor:
            body["formFactor"] = form_factor
        return self._post(CRUX_QUERY_HISTORY, body)

    @retry(retry=retry_if_exception(_is_transient),
           stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, max=10),
           reraise=True)
    def _post(self, endpoint: str, body: dict) -> dict | None:
        """Throttled, retrying POST. 404 → None (absence of data is not a failure)."""
        _THROTTLE.wait()
        lease = self._keyring.acquire(max_wait_s=0.0)
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(endpoint, params={"key": lease.key}, json=body,
                               headers={"Content-Type": "application/json"})
        if resp.status_code == 404:
            return None
        if resp.status_code == 429:
            self._keyring.mark_rate_limited(lease, _retry_after(resp))
        resp.raise_for_status()
        try:
            return resp.json()
        except ValueError as e:
            raise CruxMalformedResponse(f"200 with non-JSON body ({e})") from e


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
