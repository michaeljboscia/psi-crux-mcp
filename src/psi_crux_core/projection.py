"""
Projection — keep tool results LLM-sized. FEAT-011, REQ-PROJ-001/002/003.
Renders a CruxCurrentResult to a compact markdown digest + a structured dict. For the skeleton
the CrUX payload is already small; the top-N capping machinery (REQ-PROJ-008) arrives with the
PSI parsers in Phase 3. This module is where the ≤25 KB budget is enforced.
"""
from __future__ import annotations

from .models import CruxCurrentResult

MAX_RESULT_BYTES = 25_600  # REQ-PROJ-003


def project_crux_current(result: CruxCurrentResult) -> tuple[str, dict]:
    """Return (markdown, structured_dict). REQ-MCP-019 dual-content."""
    if not result.has_data:
        md = f"**{result.origin_or_url}** ({result.form_factor}): insufficient CrUX traffic — no field data."
        return md, {"origin_or_url": result.origin_or_url, "has_data": False}

    lines = [f"**CrUX field data — {result.origin_or_url}** ({result.form_factor})", ""]
    core = ["largest_contentful_paint", "interaction_to_next_paint", "cumulative_layout_shift"]
    for name in core + [m for m in result.metrics if m not in core]:
        m = result.metrics.get(name)
        if not m:
            continue
        cat = f" [{m.category}]" if m.category else ""
        lines.append(f"- `{name}` p75={m.p75}{cat}")
    md = "\n".join(lines)

    data = {
        "origin_or_url": result.origin_or_url,
        "form_factor": result.form_factor,
        "has_data": True,
        "metrics": {k: v.model_dump(exclude_none=True) for k, v in result.metrics.items()},
    }
    return md, data
