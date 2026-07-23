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
    rows = []
    for aid in ("unused-javascript", "unused-css-rules"):
        det = ((payload.get("lighthouseResult") or {}).get("audits", {}).get(aid) or {}).get("details") or {}
        items = det.get("items") or []
        if not items:
            continue
        wasted_ms = det.get("overallSavingsMs")
        for it in items:
            rows.append({"source_audit_id": aid,
                         "canonical_key": registry.resolve(aid).canonical_key,
                         "wasted_bytes": it.get("wastedBytes"), "wasted_ms": wasted_ms})
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
