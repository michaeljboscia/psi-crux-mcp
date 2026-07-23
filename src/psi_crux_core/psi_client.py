"""
PSI API client — SYNC httpx (D-01). FEAT-001, REQ-PSI-001/002/003, REQ-PSI-017/018.
Requests all four categories (1 quota unit). www/non-www failover on HTTP 400. Sets utm_source
to identify tool traffic and an optional quotaUser. Returns the raw response dict; runtimeError
validation happens in the parser (REQ-ERR-003), not here.
"""
from __future__ import annotations

import httpx
from tenacity import (
    retry, retry_if_exception, stop_after_attempt, wait_exponential,
)

from .keyring import Keyring
from .logging import get_logger


def _is_transient(exc: BaseException) -> bool:
    """Retry 5xx + network errors; never retry 4xx (REQ-ENG-001)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError))

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
DEFAULT_CATEGORIES = ("performance", "best-practices", "accessibility", "seo")
_log = get_logger("psi_client")


class PsiClient:
    def __init__(self, keyring: Keyring, timeout_s: float = 90.0,
                 utm_source: str = "psi-crux-mcp") -> None:
        self._keyring = keyring
        self._timeout = timeout_s
        self._utm = utm_source

    def run_pagespeed(self, url: str, strategy: str = "mobile",
                      categories: tuple[str, ...] = DEFAULT_CATEGORIES,
                      quota_user: str | None = None) -> dict:
        """Call runPagespeed; retry once with the opposite www variant on HTTP 400 (REQ-PSI-003)."""
        try:
            return self._call(url, strategy, categories, quota_user)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                alt = _www_flip(url)
                if alt != url:
                    _log.info("psi_www_failover", frm=url, to=alt)
                    return self._call(alt, strategy, categories, quota_user)
            raise

    @retry(retry=retry_if_exception(_is_transient),
           stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, max=10),
           reraise=True)
    def _call(self, url: str, strategy: str, categories: tuple[str, ...],
              quota_user: str | None) -> dict:
        lease = self._keyring.acquire(max_wait_s=0.0)
        params: list[tuple[str, str]] = [
            ("url", url), ("strategy", strategy), ("key", lease.key),
            ("utm_source", self._utm),
        ]
        params += [("category", c) for c in categories]
        if quota_user:
            params.append(("quotaUser", quota_user))
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.get(PSI_ENDPOINT, params=params)
        if resp.status_code == 429:
            self._keyring.mark_rate_limited(lease, _retry_after(resp))
        resp.raise_for_status()
        return resp.json()


def _www_flip(url: str) -> str:
    if "://www." in url:
        return url.replace("://www.", "://", 1)
    return url.replace("://", "://www.", 1)


def _retry_after(resp: httpx.Response) -> int | None:
    try:
        return int(resp.headers.get("Retry-After") or 0) or None
    except (TypeError, ValueError):
        return None
