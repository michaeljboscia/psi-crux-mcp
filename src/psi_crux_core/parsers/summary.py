"""
Assemble a full PSI scan into projected, capped structures + the persist payload. FEAT-001.
Ties the individual parsers together and enforces the projection budget (REQ-PROJ-002/003/008):
every list is top-N + total_count; the default result stays LLM-sized.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..compat.registry import CompatRegistry
from ..projection import MAX_RESULT_BYTES
from .best_practices import parse_best_practices
from .branches import (
    parse_cwv_elements, parse_diagnostics, parse_main_thread, parse_opportunities,
    parse_scripts, parse_third_party,
)
from .field import parse_crux_field
from .insights import InsightParseResult, parse_insights
from .metrics import parse_core_metrics
from .network import parse_network_requests, parse_resource_summary

# top-N caps per section (REQ-PROJ-008)
CAPS = {"network": 15, "insights": 8, "best_practices": 15, "resource_summary": 12}


def _capped(rows: list, key: str, shrink: int = 0) -> dict:
    """Top-N + total_count. `total_count` is ALWAYS the true length, so a capped list can
    never read as a complete one (REQ-PROJ-002)."""
    n = max(1, CAPS.get(key, 10) >> shrink)
    return {"items": rows[:n], "total_count": len(rows)}


def _byte_size(data: dict) -> int:
    return len(json.dumps(data, default=str).encode("utf-8"))


def _fit_budget(build, run_id_hint: str) -> dict:
    """
    Enforce the ≤25KB projection budget (REQ-PROJ-003 / G7). MAX_RESULT_BYTES was declared but
    never actually checked, and top-N caps alone don't bound a single pathological `details`
    blob — the old report payload regressed to O(n) exactly this way.

    Halve the caps until it fits, then record what was dropped. Truncation is ALWAYS announced
    in-band: silent shrinkage would make a partial result look complete, which is the failure
    class this whole pass exists to remove. The raw payload stays reachable via the artifact.
    """
    for shrink in range(0, 6):
        data = build(shrink)
        size = _byte_size(data)
        if size <= MAX_RESULT_BYTES:
            if shrink:
                data["projection"] = {
                    "truncated": True, "bytes": size, "budget": MAX_RESULT_BYTES,
                    "note": f"lists reduced {2 ** shrink}x to fit the budget; "
                            f"full payload in artifact for run {run_id_hint}",
                }
            return data
    data["projection"] = {"truncated": True, "bytes": _byte_size(data),
                          "budget": MAX_RESULT_BYTES,
                          "note": f"still over budget at minimum caps; "
                                  f"full payload in artifact for run {run_id_hint}"}
    return data


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
    crux_field_rows: list[dict] = field(default_factory=list)
    diagnostic_rows: list[dict] = field(default_factory=list)
    compat_warnings: list[str] = field(default_factory=list)


def assemble(payload: dict, registry: CompatRegistry, strategy: str = "mobile") -> PsiScan:
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
        crux_field_rows=parse_crux_field(payload, strategy),      # G3/G5/G9
        diagnostic_rows=parse_diagnostics(payload, registry),     # G3
        compat_warnings=ins.compat_warnings,
    )


def _field_section(scan: PsiScan) -> dict:
    """
    CrUX field data split by granularity (G5). URL-level and origin-level are kept in SEPARATE
    keys and never merged: an origin average is a different measurement from the page, and
    letting one stand in for the other is how a 0.04 origin CLS shipped for a 1.52 homepage.
    """
    out: dict[str, Any] = {"url": {}, "origin": {}}
    for row in scan.crux_field_rows:
        out.setdefault(row["granularity"], {})[row["metric"]] = {
            "p75": row["p75"], "category": row["category"],
            "good": row["good"], "ni": row["ni"], "poor": row["poor"],
        }
    # Absent field data is "insufficient CrUX traffic" (REQ-CWV-001), not an error.
    out["has_url_data"] = bool(out.get("url"))
    out["has_origin_data"] = bool(out.get("origin"))
    return out


def project(scan: PsiScan, canonical_url: str, run_id: str = "") -> tuple[str, dict]:
    """Dual-content: compact markdown + structured (capped, budget-enforced) JSON.
    REQ-MCP-019, REQ-PROJ-002/003."""
    c = scan.core
    top_insights = sorted(scan.insights.rows, key=lambda r: -(r.savings_ms or 0))
    fld = _field_section(scan)
    md = [
        f"**PageSpeed — {canonical_url}** (LH {c.get('lighthouse_version')})",
        f"- performance **{c.get('performance_score')}** · a11y {c.get('accessibility_score')} "
        f"· seo {c.get('seo_score')} · best-practices {c.get('best_practices_score')}",
        f"- lab: LCP {c.get('lcp')}ms · CLS {c.get('cls')} · TBT {c.get('tbt')}ms",
    ]
    if fld["has_url_data"]:
        u = fld["url"]
        def _p(m):  # noqa: E306
            v = u.get(m) or {}
            return f"{v.get('p75')}" if v.get("p75") is not None else "n/a"
        md.append(f"- field (this URL): LCP {_p('largest_contentful_paint')}ms "
                  f"· CLS {_p('cumulative_layout_shift')} "
                  f"· INP {_p('interaction_to_next_paint')}ms")
    else:
        md.append("- field (this URL): insufficient CrUX traffic")
    md += ["", f"Top insights (of {len(scan.insights.rows)}):"]
    for r in top_insights[:CAPS['insights']]:
        save = f" ~{r.savings_ms:.0f}ms" if r.savings_ms else ""
        md.append(f"- `{r.canonical_key}`{save}")
    if scan.compat_warnings:
        md.append(f"\n_compat: {len(scan.compat_warnings)} warning(s) — see structuredContent_")

    def build(shrink: int) -> dict:
        return {
            "canonical_url": canonical_url,
            "scores": {k: c.get(k) for k in ("performance_score", "accessibility_score",
                                             "seo_score", "best_practices_score")},
            "metrics": {k: c.get(k) for k in ("fcp", "lcp", "cls", "speed_index", "tti", "tbt")},
            "field": fld,
            "lighthouse_version": c.get("lighthouse_version"),
            "insights": _capped(
                [{"canonical_key": r.canonical_key, "source_audit_id": r.source_audit_id,
                  "savings_ms": r.savings_ms, "details_type": r.details_type,
                  "parse_status": r.parse_status} for r in top_insights], "insights", shrink),
            "network": _capped(
                sorted(scan.network_rows, key=lambda r: -(r.get("transfer_size") or 0)),
                "network", shrink),
            "best_practices": _capped(scan.bp_rows, "best_practices", shrink),
            "compat_warnings": scan.compat_warnings,
        }

    return "\n".join(md), _fit_budget(build, run_id)
