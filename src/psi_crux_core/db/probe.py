"""
Multi-probe median selection. FEAT-008, harvest G10 (learning #21, code#12).

Lighthouse is genuinely noisy run-to-run: the same URL, unchanged, routinely moves 5-15% on
LCP/TBT. A single probe therefore reports a number you cannot reproduce, and a naive average
across probes is worse — one pathological run drags the mean and there is no way to tell it
happened.

The fix the old collector landed on, and the one Lighthouse CI uses (`computeMedianRun`):
run N probes, keep them ALL, and pick the run that is jointly closest to the median on FCP
and TTI. Only that run's payload feeds the branch tables, so you get one coherent set of
insights rather than N overlapping sets. Every probe is still persisted, so the spread stays
inspectable — that is the whole point of measuring N times.

FCP+TTI (not the performance score) is the LHCI convention: the score is a weighted composite
that can land mid-pack while the underlying timings are outliers.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProbeRows:
    """
    One probe's parsed output. `branches` maps table name → rows.

    A table ABSENT from the mapping means "this stage never ran" (expected=None in the
    completion contract) — deliberately distinct from a table mapped to [] , which means
    "ran, legitimately produced nothing." Conflating those two lets a never-wired table pass
    reconciliation as 0==0, which is precisely how psi_crux_field and psi_diagnostic sat
    empty and unnoticed.
    """
    core: dict
    branches: dict[str, list] = field(default_factory=dict)


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def select_median_index(probes: list[ProbeRows]) -> int:
    """
    Index of the probe closest to the median on FCP and TTI jointly (LHCI computeMedianRun).

    Probes missing either timing are ranked last rather than dropped — a probe that returned
    without timings is a real observation about the target, not a row to discard silently.
    """
    if not probes:
        raise ValueError("cannot select a median from zero probes")
    if len(probes) == 1:
        return 0

    usable = [i for i, p in enumerate(probes)
              if p.core.get("fcp") is not None and p.core.get("tti") is not None]
    if not usable:
        return 0

    med_fcp = _median([float(probes[i].core["fcp"]) for i in usable])
    med_tti = _median([float(probes[i].core["tti"]) for i in usable])

    def distance(i: int) -> float:
        # Normalized so neither metric's larger absolute scale dominates the ranking.
        c = probes[i].core
        d_fcp = abs(float(c["fcp"]) - med_fcp) / med_fcp if med_fcp else 0.0
        d_tti = abs(float(c["tti"]) - med_tti) / med_tti if med_tti else 0.0
        return d_fcp + d_tti

    return min(usable, key=distance)
