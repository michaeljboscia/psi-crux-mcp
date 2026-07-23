"""
Recommendation engine. FEAT-003, REQ-REC-001..005.
Dedupe by canonical_key (insight-primary, MAX severity by savings). Attach authored advice or
fall back to the live audit's own title with advice_status='pending' (never fabricate fix steps).
Emits a codebase-aware synthesis prompt — the durable moat over any stateless wrapper (REQ-REC-005).
"""
from __future__ import annotations

from .data.advice import ADVICE
from .parsers.summary import PsiScan

_CODEBASE_PROMPT = (
    "For each recommendation, inspect the user's actual codebase to make it concrete "
    "(e.g. an image-delivery finding → check their <Image>/next.config or <img> tags; "
    "a js_unused finding → check their bundler/imports). Turn generic advice into a specific edit."
)


def recommend(scan: PsiScan, limit: int = 10) -> dict:
    """Return deduped, prioritized recommendations + the codebase-synthesis instruction."""
    # dedupe by canonical_key, keep the max savings seen (MAX severity)
    best: dict[str, float] = {}
    for r in scan.insights.rows:
        if r.canonical_key.startswith("unknown:"):
            continue
        best[r.canonical_key] = max(best.get(r.canonical_key, 0.0), r.savings_ms or 0.0)

    ranked = sorted(best.items(), key=lambda kv: -kv[1])[:limit]
    recs = []
    for ckey, savings in ranked:
        entry = ADVICE.get(ckey)
        if entry:
            recs.append({
                "canonical_key": ckey, "advice_status": "authored",
                "title": entry["title"], "why": entry["why"], "fix_steps": entry["fix_steps"],
                "estimated_savings_ms": savings or None,
            })
        else:
            recs.append({
                "canonical_key": ckey, "advice_status": "pending",
                "title": ckey.replace("_", " ").title(),
                "why": "See the Lighthouse audit detail for this finding.",
                "fix_steps": [], "estimated_savings_ms": savings or None,
            })
    return {"recommendations": recs, "synthesis_instruction": _CODEBASE_PROMPT,
            "total_findings": len(best)}
