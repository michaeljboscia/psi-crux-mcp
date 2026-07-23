"""
Parse a CrUX queryHistoryRecord response → per-metric p75 timeseries. REQ-CRUX-002/003.
Shape: record.metrics.<metric>.percentilesTimeseries.p75s (parallel to record.collectionPeriods).
Keeps the raw per-window p75 series (density series also available) — never averaged (REQ-CRUX-010).
"""
from __future__ import annotations


def parse_crux_history(payload: dict) -> dict:
    record = payload.get("record", {})
    metrics = record.get("metrics", {})
    periods = record.get("collectionPeriods", [])
    out_metrics: dict[str, list[float | None]] = {}
    for name, m in metrics.items():
        p75s = (m.get("percentilesTimeseries") or {}).get("p75s")
        if p75s is None:
            continue
        series: list[float | None] = []
        for v in p75s:
            try:
                series.append(float(v) if v not in (None, "NaN") else None)
            except (TypeError, ValueError):
                series.append(None)
        out_metrics[name] = series
    return {"n_periods": len(periods), "metrics": out_metrics}
