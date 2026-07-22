"""
LH13 insight-audit parser — the differentiator. FEAT-001, REQ-PSI-013/021, REQ-COMPAT-010, REQ-PARSE-001.
Registry-driven: canonical keys come from the registry, never a hardcoded list. Branches on
details.type (`list` {items,type} vs `table` {items,headings,type}). An UNKNOWN details shape is
kept with parse_status='unknown_shape' (never dropped — REQ-PARSE-001). Unknown audit IDs get a
canonical_key of 'unknown:<id>' and raise a compat warning.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..compat.registry import CompatRegistry


@dataclass
class InsightRow:
    canonical_key: str
    source_audit_id: str
    details_type: str | None
    score: float | None
    savings_ms: float | None
    item_count: int
    parse_status: str            # ok | unknown_shape
    known: bool


@dataclass
class InsightParseResult:
    rows: list[InsightRow] = field(default_factory=list)
    compat_warnings: list[str] = field(default_factory=list)


_KNOWN_SHAPES = {"list", "table"}


def parse_insights(payload: dict, registry: CompatRegistry) -> InsightParseResult:
    audits = (payload.get("lighthouseResult") or {}).get("audits", {})
    out = InsightParseResult()
    for aid, audit in audits.items():
        if not aid.endswith("-insight"):
            continue
        mapping = registry.resolve(aid)
        if not mapping.known:
            out.compat_warnings.append(f"unknown insight audit '{aid}' → {mapping.canonical_key}")
        details = audit.get("details") or {}
        dtype = details.get("type")
        items = details.get("items") or []
        parse_status = "ok" if (dtype in _KNOWN_SHAPES or not details) else "unknown_shape"
        if parse_status == "unknown_shape":
            out.compat_warnings.append(f"insight '{aid}' has unknown details.type='{dtype}'")
        savings = None
        overall = (details.get("overallSavingsMs") if isinstance(details, dict) else None)
        if isinstance(overall, (int, float)):
            savings = float(overall)
        out.rows.append(InsightRow(
            canonical_key=mapping.canonical_key, source_audit_id=aid, details_type=dtype,
            score=audit.get("score"), savings_ms=savings, item_count=len(items),
            parse_status=parse_status, known=mapping.known,
        ))
    return out
