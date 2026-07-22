"""
Parse a CrUX queryRecord response → CruxCurrentResult. FEAT-002, REQ-CRUX-001.
Shape verified against reference/fixtures/crux-current-wikipedia-phone.json.
Confirms: NO first_input_delay (REQ-CRUX-001 / A-01); density bins good/ni/poor preserved
(REQ-CRUX-010 — never averaged). Category derived from p75 vs standard CWV thresholds.
"""
from __future__ import annotations

from ..models import CruxCurrentResult, CruxMetric

# Good/poor p75 thresholds for the categorizable metrics (ms except CLS unitless).
_THRESH: dict[str, tuple[float, float]] = {
    "largest_contentful_paint": (2500, 4000),
    "interaction_to_next_paint": (200, 500),
    "cumulative_layout_shift": (0.1, 0.25),
    "first_contentful_paint": (1800, 3000),
    "experimental_time_to_first_byte": (800, 1800),
}


def _category(metric: str, p75: float | None) -> str | None:
    t = _THRESH.get(metric)
    if t is None or p75 is None:
        return None
    good, poor = t
    return "good" if p75 <= good else ("needs-improvement" if p75 <= poor else "poor")


def parse_crux_current(payload: dict, target: str, form_factor: str | None) -> CruxCurrentResult:
    record = payload.get("record", {})
    raw = record.get("metrics", {})
    metrics: dict[str, CruxMetric] = {}
    for name, m in raw.items():
        p75 = (m.get("percentiles") or {}).get("p75")
        try:
            p75f = float(p75) if p75 is not None else None
        except (TypeError, ValueError):
            p75f = None
        good = ni = poor = None
        hist = m.get("histogram") or []
        if len(hist) == 3:  # CrUX always returns exactly 3 bins in order
            good = hist[0].get("density")
            ni = hist[1].get("density")
            poor = hist[2].get("density")
        metrics[name] = CruxMetric(
            category=_category(name, p75f), p75=p75f, good=good, ni=ni, poor=poor
        )
    return CruxCurrentResult(
        origin_or_url=target, form_factor=form_factor, metrics=metrics, has_data=bool(metrics)
    )
