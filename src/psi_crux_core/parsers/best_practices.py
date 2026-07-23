"""Best-practices parser — one row per FAILING BP audit. FEAT-001, REQ-PSI-014."""
from __future__ import annotations

from ..compat.registry import CompatRegistry


def parse_best_practices(payload: dict, registry: CompatRegistry) -> list[dict]:
    lh = payload.get("lighthouseResult") or {}
    audits = lh.get("audits", {})
    cat = (lh.get("categories") or {}).get("best-practices") or {}
    rows = []
    for ref in cat.get("auditRefs", []):
        aid = ref.get("id")
        audit = audits.get(aid) or {}
        score = audit.get("score")
        if score is not None and score < 1:      # failing only
            rows.append({
                "source_audit_id": aid,
                "canonical_key": registry.resolve(aid).canonical_key,
                "title": audit.get("title"),
                "score": score,
            })
    return rows
