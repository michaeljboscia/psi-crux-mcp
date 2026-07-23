"""Network parser — network-requests audit. FEAT-001, REQ-PSI-006/015 (negative sizes → None)."""
from __future__ import annotations


def parse_network_requests(payload: dict) -> list[dict]:
    audits = (payload.get("lighthouseResult") or {}).get("audits", {})
    items = ((audits.get("network-requests") or {}).get("details") or {}).get("items") or []
    rows = []
    for it in items:
        ts = it.get("transferSize")
        rows.append({
            "url": it.get("url", ""),
            "resource_type": it.get("resourceType"),
            "mime_type": it.get("mimeType"),
            "transfer_size": ts if isinstance(ts, (int, float)) and ts >= 0 else None,
            "status_code": it.get("statusCode"),
        })
    return rows


def parse_resource_summary(payload: dict) -> list[dict]:
    """resource-summary survives in LH13.4 (fixture-verified) — parse directly (REQ-PSI-006)."""
    audits = (payload.get("lighthouseResult") or {}).get("audits", {})
    items = ((audits.get("resource-summary") or {}).get("details") or {}).get("items") or []
    return [
        {"resource_type": it.get("resourceType", ""),
         "request_count": it.get("requestCount"), "transfer_size": it.get("transferSize")}
        for it in items
    ]
