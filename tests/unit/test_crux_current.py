"""Fixture-backed CrUX parser tests. REQ-CRUX-001/010, A-01. Uses the REAL captured response."""
from psi_crux_core.parsers.crux_current import parse_crux_current


def test_parses_core_metrics_from_live_fixture(crux_current_fixture):
    r = parse_crux_current(crux_current_fixture, "https://www.wikipedia.org", "PHONE")
    assert r.has_data
    # core web vitals present with p75s
    for m in ("largest_contentful_paint", "interaction_to_next_paint", "cumulative_layout_shift"):
        assert m in r.metrics, f"missing {m}"
        assert r.metrics[m].p75 is not None


def test_no_fid_in_live_crux(crux_current_fixture):
    """A-01 / REQ-CRUX-001: FID was removed from the CrUX API — must be absent, ground-truthed."""
    r = parse_crux_current(crux_current_fixture, "https://www.wikipedia.org", "PHONE")
    assert "first_input_delay" not in r.metrics


def test_density_bins_preserved_not_averaged(crux_current_fixture):
    """REQ-CRUX-010: keep good/ni/poor density bins (never derive an average)."""
    r = parse_crux_current(crux_current_fixture, "https://www.wikipedia.org", "PHONE")
    lcp = r.metrics["largest_contentful_paint"]
    assert lcp.good is not None and lcp.ni is not None and lcp.poor is not None


def test_no_data_path():
    r = parse_crux_current({}, "https://example.invalid", "PHONE")
    assert r.has_data is False
    assert r.metrics == {}
