"""
PSI core-metrics parser. FEAT-001, REQ-PSI-004/005, REQ-ERR-003, REQ-CWV-001.
Validates lighthouseResult.runtimeError on a 200 BEFORE parsing (a PDF/404/timeout returns 200 +
a nested runtimeError). Enforces strict presence of LAB core CWV (Lighthouse always emits them;
missing = a real parse failure, never null-and-succeed).
"""
from __future__ import annotations


class PsiRuntimeError(Exception):
    """PSI returned 200 but lighthouseResult.runtimeError is set (REQ-ERR-003)."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class LabCwvMissing(Exception):
    """A LAB core web vital (LCP/CLS) is absent — a real failure, not a no-data case (REQ-CWV-001)."""


_LAB_CORE = {
    "fcp": "first-contentful-paint",
    "lcp": "largest-contentful-paint",
    "cls": "cumulative-layout-shift",
    "speed_index": "speed-index",
    "tti": "interactive",
    "tbt": "total-blocking-time",
}
# LAB metrics Lighthouse ALWAYS emits — absence means a broken parse (REQ-CWV-001).
_LAB_REQUIRED = ("largest-contentful-paint", "cumulative-layout-shift")


def check_runtime_error(payload: dict) -> None:
    """Raise PsiRuntimeError if the 200 response carries a runtimeError. Call BEFORE any parsing."""
    rte = (payload.get("lighthouseResult") or {}).get("runtimeError")
    if rte:
        raise PsiRuntimeError(rte.get("code", "UNKNOWN"), rte.get("message", ""))


def parse_core_metrics(payload: dict) -> dict:
    """Core lab metrics + category scores. null score ≠ 0 (REQ-PSI-005)."""
    lh = payload["lighthouseResult"]
    audits = lh.get("audits", {})
    cats = lh.get("categories", {})

    for required in _LAB_REQUIRED:
        if required not in audits:
            raise LabCwvMissing(f"lab core metric '{required}' absent from lighthouseResult")

    metrics = {k: audits.get(aid, {}).get("numericValue") for k, aid in _LAB_CORE.items()}

    def score(cat: str) -> int | None:
        s = cats.get(cat, {}).get("score")
        return round(s * 100) if s is not None else None  # None = absent, distinct from 0

    return {
        "final_url": lh.get("finalUrl") or lh.get("requestedUrl"),
        "lighthouse_version": lh.get("lighthouseVersion"),
        **metrics,
        "performance_score": score("performance"),
        "best_practices_score": score("best-practices"),
        "accessibility_score": score("accessibility"),
        "seo_score": score("seo"),
    }
