"""
Fixture-backed PSI parser tests against the REAL LH13.4.0 response. The core Phase-2 reality tests:
registry-driven insight IDs, correct ground-truth names, list|table shapes, runtimeError handling,
LAB-CWV strictness.
"""
import copy

import pytest

from psi_crux_core.compat.registry import CompatRegistry
from psi_crux_core.parsers.insights import parse_insights
from psi_crux_core.parsers.metrics import (
    LabCwvMissing, PsiRuntimeError, check_runtime_error, parse_core_metrics,
)


@pytest.fixture
def registry() -> CompatRegistry:
    return CompatRegistry.load()


def test_registry_has_ground_truth_names(registry):
    """The R4 fixture corrections: lcp-breakdown (not lcp-phases), inp-breakdown, cache-insight."""
    assert registry.resolve("lcp-breakdown-insight").canonical_key == "lcp_phases"
    assert registry.resolve("inp-breakdown-insight").canonical_key == "inp_latency"
    assert registry.resolve("cache-insight").canonical_key == "cache_policy"
    # the wrong names must NOT be known
    assert registry.resolve("lcp-phases-insight").known is False
    assert registry.resolve("use-cache-insight").known is False


def test_insights_parsed_from_live_fixture(lh13_fixture, registry):
    res = parse_insights(lh13_fixture, registry)
    keys = {r.source_audit_id for r in res.rows}
    # ground-truth IDs present in the real response
    for aid in ("lcp-breakdown-insight", "cls-culprits-insight", "network-dependency-tree-insight",
                "forced-reflow-insight", "image-delivery-insight"):
        assert aid in keys, f"missing insight {aid}"
    # detail shapes branch correctly
    by_id = {r.source_audit_id: r for r in res.rows}
    assert by_id["cls-culprits-insight"].details_type == "list"
    assert by_id["image-delivery-insight"].details_type == "table"
    # every insight resolved to a canonical key, none dropped
    assert all(r.canonical_key and not r.canonical_key.startswith("unknown:") for r in res.rows)


def test_unknown_shape_not_dropped(lh13_fixture, registry):
    """REQ-PARSE-001: an unknown details.type is kept with parse_status=unknown_shape."""
    payload = copy.deepcopy(lh13_fixture)
    payload["lighthouseResult"]["audits"]["cls-culprits-insight"]["details"]["type"] = "filmstrip"
    res = parse_insights(payload, registry)
    row = next(r for r in res.rows if r.source_audit_id == "cls-culprits-insight")
    assert row.parse_status == "unknown_shape"
    assert any("unknown details.type" in w for w in res.compat_warnings)


def test_core_metrics_and_scores(lh13_fixture):
    m = parse_core_metrics(lh13_fixture)
    assert m["lcp"] is not None and m["cls"] is not None
    assert m["lighthouse_version"].startswith("13.")
    assert isinstance(m["performance_score"], int)


def test_runtime_error_detected():
    bad = {"lighthouseResult": {"runtimeError": {"code": "NOT_HTML", "message": "not html"}}}
    with pytest.raises(PsiRuntimeError):
        check_runtime_error(bad)


def test_lab_cwv_missing_raises(lh13_fixture):
    payload = copy.deepcopy(lh13_fixture)
    del payload["lighthouseResult"]["audits"]["largest-contentful-paint"]
    with pytest.raises(LabCwvMissing):
        parse_core_metrics(payload)
