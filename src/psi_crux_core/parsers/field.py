"""
CrUX FIELD data lifted from the PSI response itself. FEAT-002, REQ-CRUX-*, REQ-CWV-001.

G9: a single runPagespeed call ALREADY returns field data twice over — `loadingExperience`
(URL-level) and `originLoadingExperience` (origin-level). The old collector fired a separate
CrUX sweep over the same URLs and burned ~95% of it on 404s. Read what we already paid for.

G5: the two are NOT interchangeable. Origin data is aggregated across every page on the host,
so a healthy origin average can completely mask a broken page (an origin CLS of 0.04 once
shipped to a client whose actual homepage was 1.52). Every row is tagged `granularity`.

Shapes verified against reference/fixtures/lh13-wikipedia-mobile.raw.json.
"""
from __future__ import annotations

# PSI reports field metrics in UPPER_SNAKE; the CrUX API uses lower_snake. Normalize to the
# CrUX vocabulary so psi_crux_field rows and crux_query results are directly comparable.
_METRIC_NAMES = {
    "LARGEST_CONTENTFUL_PAINT_MS": "largest_contentful_paint",
    "CUMULATIVE_LAYOUT_SHIFT_SCORE": "cumulative_layout_shift",
    "INTERACTION_TO_NEXT_PAINT": "interaction_to_next_paint",
    "FIRST_CONTENTFUL_PAINT_MS": "first_contentful_paint",
    "EXPERIMENTAL_TIME_TO_FIRST_BYTE": "experimental_time_to_first_byte",
    "FIRST_INPUT_DELAY_MS": "first_input_delay",       # legacy; absent from live LH13 (A-01)
}

# PSI says FAST/AVERAGE/SLOW; CrUX says good/needs-improvement/poor. Two vocabularies for one
# concept is how a threshold check silently reads the wrong field — bind them here, once.
_CATEGORIES = {"FAST": "good", "AVERAGE": "needs-improvement", "SLOW": "poor"}

# CLS is transported as an INTEGER SCALED BY 100 (fixture: bin edges are 10/25, i.e. 0.1/0.25).
# Persisting the raw 0-100 value would make every CLS look 100x worse than it is.
_SCALED_BY_100 = {"cumulative_layout_shift"}

_STRATEGY_TO_FORM_FACTOR = {"mobile": "PHONE", "desktop": "DESKTOP"}


def _proportions(metric: dict) -> tuple[float | None, float | None, float | None]:
    """good / needs-improvement / poor densities. CrUX always emits exactly 3 ordered bins."""
    dist = metric.get("distributions") or []
    if len(dist) != 3:
        return None, None, None
    return (dist[0].get("proportion"), dist[1].get("proportion"), dist[2].get("proportion"))


def _rows_for(block: dict, granularity: str, form_factor: str) -> list[dict]:
    rows = []
    for raw_name, metric in (block.get("metrics") or {}).items():
        name = _METRIC_NAMES.get(raw_name, raw_name.lower())
        p75 = metric.get("percentile")
        if p75 is not None and name in _SCALED_BY_100:
            p75 = p75 / 100.0
        good, ni, poor = _proportions(metric)
        rows.append({
            "granularity": granularity,
            "form_factor": form_factor,
            "metric": name,
            "category": _CATEGORIES.get(metric.get("category")),
            "p75": float(p75) if p75 is not None else None,
            "good": good, "ni": ni, "poor": poor,
            "fid_p75": None,        # legacy column; live LH13 never returns FID (A-01)
        })
    return rows


def parse_crux_field(payload: dict, strategy: str = "mobile") -> list[dict]:
    """
    psi_crux_field rows from the PSI payload's own field blocks (G3/G5/G9).

    Returns [] when the target has no CrUX coverage. That is the "insufficient traffic"
    contract (REQ-CWV-001) — a legitimate empty, NOT an error and NOT a parse failure.
    The completion contract distinguishes this (expected=0) from a stage that never ran
    (expected=None), so an empty result can no longer hide as a never-wired table.
    """
    form_factor = _STRATEGY_TO_FORM_FACTOR.get(strategy, "PHONE")
    rows: list[dict] = []
    for key, granularity in (("loadingExperience", "url"),
                             ("originLoadingExperience", "origin")):
        block = payload.get(key) or {}
        if block.get("metrics"):
            rows.extend(_rows_for(block, granularity, form_factor))
    return rows
