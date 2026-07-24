"""CrUX field data lifted from the PSI payload. Harvest G3/G5/G9."""
import json
from pathlib import Path

import pytest

from psi_crux_core.parsers.field import parse_crux_field

FIXTURE = Path(__file__).parents[2] / "reference/fixtures/lh13-wikipedia-mobile.raw.json"


@pytest.fixture(scope="module")
def payload():
    if not FIXTURE.exists():
        pytest.skip("live LH13 fixture not present")
    return json.loads(FIXTURE.read_text())


def test_both_granularities_parsed_and_tagged(payload):
    """G5: URL-level and origin-level are separate rows, never merged."""
    rows = parse_crux_field(payload, "mobile")
    assert rows, "fixture has field data"
    grans = {r["granularity"] for r in rows}
    assert grans == {"url", "origin"}


def test_cls_is_descaled_from_the_integer_transport(payload):
    """
    PSI transports CLS as an int scaled x100 (bin edges are 10/25, i.e. 0.1/0.25).
    Persisting the raw value would make every CLS read 100x worse than reality.
    """
    cls = [r for r in parse_crux_field(payload, "mobile")
           if r["metric"] == "cumulative_layout_shift"]
    assert cls
    for row in cls:
        assert row["p75"] is not None
        assert row["p75"] <= 1.0, "CLS still on the 0-100 transport scale"


def test_ms_metrics_are_not_descaled(payload):
    lcp = next(r for r in parse_crux_field(payload, "mobile")
               if r["metric"] == "largest_contentful_paint" and r["granularity"] == "url")
    assert lcp["p75"] > 100, "LCP is milliseconds and must not be divided"


def test_category_vocabulary_is_normalized_to_crux(payload):
    """PSI says FAST/AVERAGE/SLOW; everything downstream speaks good/needs-improvement/poor."""
    cats = {r["category"] for r in parse_crux_field(payload, "mobile")}
    assert cats <= {"good", "needs-improvement", "poor", None}


def test_strategy_maps_to_form_factor(payload):
    assert all(r["form_factor"] == "PHONE" for r in parse_crux_field(payload, "mobile"))
    assert all(r["form_factor"] == "DESKTOP" for r in parse_crux_field(payload, "desktop"))


def test_distribution_proportions_preserved_never_averaged(payload):
    """REQ-CRUX-010: the three density bins are data, not something to collapse to a mean."""
    row = next(r for r in parse_crux_field(payload, "mobile")
               if r["metric"] == "largest_contentful_paint" and r["granularity"] == "url")
    assert None not in (row["good"], row["ni"], row["poor"])
    assert 0.99 <= row["good"] + row["ni"] + row["poor"] <= 1.01


def test_no_field_data_returns_empty_not_error():
    """Insufficient CrUX traffic is a legitimate empty (REQ-CWV-001), not a failure."""
    assert parse_crux_field({"lighthouseResult": {}}, "mobile") == []
    assert parse_crux_field({"loadingExperience": {}}, "mobile") == []
