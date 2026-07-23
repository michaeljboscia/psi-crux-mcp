"""
Assemble a full PSI scan into projected, capped structures + the persist payload. FEAT-001.
Ties the individual parsers together and enforces the projection budget (REQ-PROJ-002/003/008):
every list is top-N + total_count; the default result stays LLM-sized.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..compat.registry import CompatRegistry
from .best_practices import parse_best_practices
from .branches import (
    parse_cwv_elements, parse_main_thread, parse_opportunities, parse_scripts, parse_third_party,
)
from .insights import InsightParseResult, parse_insights
from .metrics import parse_core_metrics
from .network import parse_network_requests, parse_resource_summary

# top-N caps per section (REQ-PROJ-008)
CAPS = {"network": 15, "insights": 8, "best_practices": 15, "resource_summary": 12}


def _capped(rows: list, key: str) -> dict:
    n = CAPS.get(key, 10)
    return {"items": rows[:n], "total_count": len(rows)}


@dataclass
class PsiScan:
    core: dict
    insights: InsightParseResult
    network_rows: list[dict]
    bp_rows: list[dict]
    resource_rows: list[dict]
    main_thread_rows: list[dict] = field(default_factory=list)
    script_rows: list[dict] = field(default_factory=list)
    opportunity_rows: list[dict] = field(default_factory=list)
    third_party_rows: list[dict] = field(default_factory=list)
    cwv_element_rows: list[dict] = field(default_factory=list)
    compat_warnings: list[str] = field(default_factory=list)


def assemble(payload: dict, registry: CompatRegistry) -> PsiScan:
    """Parse the whole PSI payload (runtimeError must be checked by the caller first)."""
    ins = parse_insights(payload, registry)
    return PsiScan(
        core=parse_core_metrics(payload),
        insights=ins,
        network_rows=parse_network_requests(payload),
        bp_rows=parse_best_practices(payload, registry),
        resource_rows=parse_resource_summary(payload),
        main_thread_rows=parse_main_thread(payload),
        script_rows=parse_scripts(payload),
        opportunity_rows=parse_opportunities(payload, registry),
        third_party_rows=parse_third_party(payload, registry),
        cwv_element_rows=parse_cwv_elements(payload, registry),
        compat_warnings=ins.compat_warnings,
    )


def project(scan: PsiScan, canonical_url: str) -> tuple[str, dict]:
    """Dual-content: compact markdown + structured (capped) JSON. REQ-MCP-019, REQ-PROJ."""
    c = scan.core
    top_insights = sorted(scan.insights.rows, key=lambda r: -(r.savings_ms or 0))
    md = [
        f"**PageSpeed — {canonical_url}** (LH {c.get('lighthouse_version')})",
        f"- performance **{c.get('performance_score')}** · a11y {c.get('accessibility_score')} "
        f"· seo {c.get('seo_score')} · best-practices {c.get('best_practices_score')}",
        f"- LCP {c.get('lcp')}ms · CLS {c.get('cls')} · TBT {c.get('tbt')}ms",
        "",
        f"Top insights (of {len(scan.insights.rows)}):",
    ]
    for r in top_insights[:CAPS['insights']]:
        save = f" ~{r.savings_ms:.0f}ms" if r.savings_ms else ""
        md.append(f"- `{r.canonical_key}`{save}")
    if scan.compat_warnings:
        md.append(f"\n_compat: {len(scan.compat_warnings)} warning(s) — see structuredContent_")

    data = {
        "canonical_url": canonical_url,
        "scores": {k: c.get(k) for k in
                   ("performance_score", "accessibility_score", "seo_score", "best_practices_score")},
        "metrics": {k: c.get(k) for k in ("fcp", "lcp", "cls", "speed_index", "tti", "tbt")},
        "lighthouse_version": c.get("lighthouse_version"),
        "insights": _capped(
            [{"canonical_key": r.canonical_key, "source_audit_id": r.source_audit_id,
              "savings_ms": r.savings_ms, "details_type": r.details_type,
              "parse_status": r.parse_status} for r in top_insights], "insights"),
        "network": _capped(
            sorted(scan.network_rows, key=lambda r: -(r.get("transfer_size") or 0)), "network"),
        "best_practices": _capped(scan.bp_rows, "best_practices"),
        "compat_warnings": scan.compat_warnings,
    }
    return "\n".join(md), data
