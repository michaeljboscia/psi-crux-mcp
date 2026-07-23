"""
Trend statistics for CrUX history. REQ-CRUX-009/010.
Mann-Kendall: non-parametric, robust for the log-normal-ish CWV distributions and does NOT assume
independence the way OLS does — appropriate for the overlapping 28-day windows. We run it on the
API-returned per-window p75 series (never an average of p75s).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Trend:
    direction: str          # improving | regressing | flat | insufficient
    s_statistic: int
    n: int
    delta: float | None     # last - first (raw movement, for context)


def mann_kendall(series: list[float | None]) -> Trend:
    """Sign-of-pairwise-differences trend test. Lower CWV = better, so S<0 => improving."""
    xs = [v for v in series if v is not None]
    n = len(xs)
    if n < 4:
        return Trend("insufficient", 0, n, None)
    s = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            s += (xs[j] > xs[i]) - (xs[j] < xs[i])
    # threshold scales with the number of comparisons; keep it simple + conservative
    thresh = max(1, n)
    delta = xs[-1] - xs[0]
    if s <= -thresh:
        direction = "improving"      # metric went DOWN over time = better
    elif s >= thresh:
        direction = "regressing"
    else:
        direction = "flat"
    # L-007: don't assert a direction the endpoint movement contradicts — call it flat (noisy).
    if (direction == "improving" and delta > 0) or (direction == "regressing" and delta < 0):
        direction = "flat"
    return Trend(direction, s, n, delta)
