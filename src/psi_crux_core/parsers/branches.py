"""
Remaining branch parsers for full 12-table fidelity (D-13). FEAT-008.
Defensive: each returns [] when its audit is absent/empty (well-optimized pages have empty tables).
Shapes verified against the live LH13.4 fixture (main_thread: group/duration; script: url/total;
opportunity: url/wastedBytes; third-parties-insight: table; cls-culprits-insight: list).
"""
from __future__ import annotations

from ..compat.registry import CompatRegistry


def _items(payload: dict, audit_id: str) -> list[dict]:
    audits = (payload.get("lighthouseResult") or {}).get("audits", {})
    return ((audits.get(audit_id) or {}).get("details") or {}).get("items") or []


def parse_main_thread(payload: dict) -> list[dict]:
    return [{"group": it.get("group", it.get("groupLabel", "")),
             "duration_ms": it.get("duration")} for it in _items(payload, "mainthread-work-breakdown")]


def parse_scripts(payload: dict) -> list[dict]:
    """bootup-time (execution) merged with unused-javascript (wasted bytes) by url."""
    wasted = {it.get("url"): it.get("wastedBytes")
              for it in _items(payload, "unused-javascript") if it.get("url")}
    rows = []
    for it in _items(payload, "bootup-time"):
        url = it.get("url", "")
        rows.append({"url": url, "total_ms": it.get("total"), "wasted_bytes": wasted.get(url)})
    return rows


def parse_opportunities(payload: dict, registry: CompatRegistry) -> list[dict]:
    """
    One row per opportunity AUDIT, bytes summed across its items (GTM keyed
    (psi_result_id, opportunity_id)). Emitting a row per item repeated the audit-level
    `overallSavingsMs` on every row and left no usable unique key.

    Audit IDs come from the registry role, never a literal list (REQ-COMPAT-001).
    """
    audits = (payload.get("lighthouseResult") or {}).get("audits", {})
    rows = []
    for aid in registry.ids_with_role("opportunity"):
        det = (audits.get(aid) or {}).get("details") or {}
        items = det.get("items") or []
        if not items:
            continue
        wasted_bytes = sum(it.get("wastedBytes") or 0 for it in items) or None
        rows.append({"source_audit_id": aid,
                     "canonical_key": registry.resolve(aid).canonical_key,
                     "wasted_bytes": wasted_bytes,
                     "wasted_ms": det.get("overallSavingsMs"),
                     "item_count": len(items)})
    return rows


def parse_diagnostics(payload: dict, registry: CompatRegistry) -> list[dict]:
    """
    psi_diagnostic rows (G3 — schema existed but nothing ever produced rows for it).
    Diagnostics are the informative/timing audits carrying a numericValue; the set is
    registry-driven via role="diagnostic". An audit absent from the response is skipped,
    not defaulted — absence is data, not zero.
    """
    audits = (payload.get("lighthouseResult") or {}).get("audits", {})
    rows = []
    for aid in registry.ids_with_role("diagnostic"):
        audit = audits.get(aid)
        if audit is None:                       # audit not emitted by this LH version
            continue
        nv = audit.get("numericValue")
        if nv is None:                          # present but no value → not a measurement
            continue
        rows.append({"source_audit_id": aid,
                     "canonical_key": registry.resolve(aid).canonical_key,
                     "numeric_value": nv,
                     "details": None})
    return rows


def parse_third_party(payload: dict, registry: CompatRegistry) -> list[dict]:
    ck = registry.resolve("third-parties-insight").canonical_key
    rows = []
    for it in _items(payload, "third-parties-insight"):
        rows.append({"source_audit_id": "third-parties-insight", "canonical_key": ck,
                     "entity": it.get("entity") if isinstance(it.get("entity"), str)
                     else (it.get("entity") or {}).get("text"),
                     "transfer_size": it.get("transferSize"),
                     "blocking_time": it.get("blockingTime") or it.get("mainThreadTime")})
    return rows


def parse_cwv_elements(payload: dict, registry: CompatRegistry) -> list[dict]:
    """CLS culprits from cls-culprits-insight (list) AND surviving classic layout-shifts (table)."""
    rows = []
    for aid in ("cls-culprits-insight", "layout-shifts"):
        ck = registry.resolve(aid).canonical_key
        for it in _items(payload, aid):
            node = it.get("node") or {}
            rows.append({"source_audit_id": aid, "canonical_key": ck,
                         "selector": node.get("selector") if isinstance(node, dict) else None,
                         "score": it.get("score")})
    return rows
