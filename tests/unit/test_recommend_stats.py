"""Recommend dedupe + advice fallback, and Mann-Kendall trend. REQ-REC-001/003, REQ-CRUX-009."""
from psi_crux_core.compat.registry import CompatRegistry
from psi_crux_core.parsers.summary import assemble
from psi_crux_core.recommend import recommend
from psi_crux_core.stats import mann_kendall


def test_recommend_from_fixture_dedupes_and_authors(lh13_fixture):
    scan = assemble(lh13_fixture, CompatRegistry.load())
    rec = recommend(scan, limit=10)
    keys = [r["canonical_key"] for r in rec["recommendations"]]
    assert len(keys) == len(set(keys)), "recommendations must be deduped by canonical_key"
    assert rec["synthesis_instruction"]                      # codebase-aware prompt present (REQ-REC-005)
    # authored entries carry fix steps; pending ones do not fabricate them
    for r in rec["recommendations"]:
        if r["advice_status"] == "authored":
            assert r["fix_steps"]
        else:
            assert r["fix_steps"] == []


def test_mann_kendall_directions():
    assert mann_kendall([500, 480, 460, 440, 420]).direction == "improving"   # LCP going down = better
    assert mann_kendall([420, 440, 460, 480, 500]).direction == "regressing"
    assert mann_kendall([100, 101, 100, 99, 100]).direction == "flat"
    assert mann_kendall([100, 200]).direction == "insufficient"               # n<4


def test_trend_never_averages_p75s():
    """REQ-CRUX-010: mann_kendall consumes the raw per-window series, not a mean."""
    t = mann_kendall([300, 290, 285, 280, 270, 260])
    assert t.n == 6 and t.delta == -40                       # last - first, raw
