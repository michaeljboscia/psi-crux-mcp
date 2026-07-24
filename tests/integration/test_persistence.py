"""12-table persistence + count-based completion contract.
REQ-PERSIST-005, REQ-STATE-001, REQ-DATA-002; harvest G1/G2/G3/G10."""
import pytest
from sqlalchemy import inspect

from psi_crux_core.db.models import ALL_BRANCH_TABLES
from psi_crux_core.db.probe import ProbeRows, select_median_index
from psi_crux_core.db.repository import Repository
from psi_crux_core.parsers.insights import InsightRow
from psi_crux_core.url_identity import UrlIdentity


def _repo(tmp_path):
    return Repository(db_url=f"sqlite:///{tmp_path/'t.db'}")


def _insight(key="cls_culprits"):
    return InsightRow(key, "cls-culprits-insight", "list", None, 12.0, 3, "ok", True)


def _core(**kw):
    base = {"performance_score": 90, "lcp": 1200.0, "cls": 0.01,
            "fcp": 1000.0, "tti": 1400.0, "lighthouse_version": "13.4.0"}
    base.update(kw)
    return base


def _branches(**overrides):
    """All 11 branch tables present — an omitted table means 'never ran' and must FAIL."""
    b = {t: [] for t in ALL_BRANCH_TABLES}
    b.update(overrides)
    return b


def _probe(**overrides):
    return ProbeRows(core=_core(), branches=_branches(**overrides))


def test_all_12_tables_created(tmp_path):
    r = _repo(tmp_path)
    names = set(inspect(r.engine).get_table_names())
    expected = {"psi_result", "scan_run", *ALL_BRANCH_TABLES}
    assert expected <= names, f"missing tables: {expected - names}"
    assert len([t for t in names if t.startswith("psi_")]) >= 12  # full fidelity


def test_scan_round_trip_and_contract(tmp_path):
    r = _repo(tmp_path)
    cc = r.persist_scan(
        "run1", UrlIdentity.of("https://example.com"), "mobile",
        [_probe(
            psi_insight=[_insight()],
            psi_network_request=[{"url": "https://example.com/a.js", "resource_type": "Script",
                                  "mime_type": "text/javascript", "transfer_size": 100,
                                  "status_code": 200}],
            psi_best_practice=[{"source_audit_id": "uses-http2", "canonical_key": "modern_http",
                                "title": "x", "score": 0.0}],
            psi_resource_summary=[{"resource_type": "script", "request_count": 1,
                                   "transfer_size": 100}],
        )],
        "2026.07.24",
    )
    assert cc.status == "complete"
    assert "psi_insight" in cc.tables_written
    assert cc.reconciliation["psi_insight"] == {"expected": 1, "actual": 1}
    assert r.get_contract("run1")["status"] == "complete"


def test_partial_failure_is_surfaced_not_swallowed(tmp_path):
    """REQ-STATE-001: an injected branch failure → partial_failed, core row survives."""
    r = _repo(tmp_path)
    cc = r.persist_scan("run2", UrlIdentity.of("https://example.com"), "mobile",
                        [_probe(psi_insight=[_insight()])], "2026.07.24",
                        fault_table="psi_insight")
    assert cc.status == "partial_failed"
    assert "psi_insight" in cc.tables_failed
    assert cc.reconciliation["psi_insight"] == {"expected": 1, "actual": 0}
    assert r.get_contract("run2")["status"] == "partial_failed"


def test_generated_columns_computed_not_written(tmp_path):
    """normalized_domain/test_date computed in Python — write never raises (no 428C9)."""
    r = _repo(tmp_path)
    cc = r.persist_scan("run3", UrlIdentity.of("https://www.Example.com/"), "mobile",
                        [_probe()], "2026.07.24")
    assert cc.status == "complete"


# --- G2/G3: a never-run stage must not pass as a clean zero -------------------------------

def test_unwired_table_fails_instead_of_passing_as_zero(tmp_path):
    """
    The exact bug G2/G3 describe: a table nothing ever wrote to used to land in tables_written
    and report 'complete'. An absent branch key now means expected=None → degraded.
    """
    r = _repo(tmp_path)
    branches = _branches()
    del branches["psi_crux_field"]          # simulate the stage never running
    cc = r.persist_scan("run4", UrlIdentity.of("https://example.com"), "mobile",
                        [ProbeRows(core=_core(), branches=branches)], "2026.07.24")
    assert cc.status == "degraded"
    assert cc.reconciliation["psi_crux_field"] == {"expected": None, "actual": 0}
    assert "psi_crux_field" in cc.mismatched
    assert "psi_crux_field" not in cc.tables_written


def test_legitimately_empty_table_is_complete_not_degraded(tmp_path):
    """expected=0 (ran, nothing to write) is a PASS — distinct from expected=None."""
    r = _repo(tmp_path)
    cc = r.persist_scan("run5", UrlIdentity.of("https://example.com"), "mobile",
                        [_probe()], "2026.07.24")
    assert cc.status == "complete"
    assert cc.reconciliation["psi_crux_field"] == {"expected": 0, "actual": 0}


# --- G1: dedup before insert ---------------------------------------------------------------

def test_duplicate_branch_rows_are_deduped_and_reported(tmp_path):
    """A repeated natural key is dropped before insert and announced, never silently doubled."""
    r = _repo(tmp_path)
    cc = r.persist_scan(
        "run6", UrlIdentity.of("https://example.com"), "mobile",
        [_probe(psi_insight=[_insight(), _insight()])],     # same canonical_key twice
        "2026.07.24",
    )
    assert cc.status == "complete"
    assert cc.reconciliation["psi_insight"] == {"expected": 1, "actual": 1}
    assert any("duplicate" in w for w in cc.parser_warnings)


def test_network_rows_deduped_on_url(tmp_path):
    """psi_network_request has no DB constraint (URL too long to index) — Python dedup holds."""
    r = _repo(tmp_path)
    row = {"url": "https://example.com/a.js", "resource_type": "Script",
           "mime_type": "text/javascript", "transfer_size": 100, "status_code": 200}
    cc = r.persist_scan("run7", UrlIdentity.of("https://example.com"), "mobile",
                        [_probe(psi_network_request=[row, dict(row)])], "2026.07.24")
    assert cc.reconciliation["psi_network_request"] == {"expected": 1, "actual": 1}


# --- G10: multi-probe median ---------------------------------------------------------------

def test_median_index_picks_the_middle_not_the_outlier():
    probes = [
        ProbeRows(core=_core(fcp=1000.0, tti=1400.0)),
        ProbeRows(core=_core(fcp=9000.0, tti=9000.0)),   # outlier
        ProbeRows(core=_core(fcp=1050.0, tti=1450.0)),
    ]
    assert select_median_index(probes) != 1


def test_all_probes_persist_but_only_median_carries_branches(tmp_path):
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session
    from psi_crux_core.db.models import PsiInsight, PsiResult

    r = _repo(tmp_path)
    probes = [
        ProbeRows(core=_core(fcp=1000.0, tti=1400.0), branches=_branches(psi_insight=[_insight()])),
        ProbeRows(core=_core(fcp=1050.0, tti=1450.0), branches=_branches(psi_insight=[_insight()])),
        ProbeRows(core=_core(fcp=9000.0, tti=9000.0), branches=_branches(psi_insight=[_insight()])),
    ]
    cc = r.persist_scan("run8", UrlIdentity.of("https://example.com"), "mobile",
                        probes, "2026.07.24", runs_requested=3)
    assert cc.status == "complete"
    with Session(r.engine) as s:
        assert s.scalar(select(func.count()).select_from(PsiResult)) == 3   # all probes kept
        assert s.scalar(select(func.count()).select_from(PsiResult)
                        .where(PsiResult.is_median.is_(True))) == 1
        # branch rows hang off exactly one result, not all three
        assert s.scalar(select(func.count()).select_from(PsiInsight)) == 1


def test_failed_probe_downgrades_to_degraded(tmp_path):
    """Asking for 5 and getting 3 must be visible, never quietly averaged."""
    r = _repo(tmp_path)
    cc = r.persist_scan("run9", UrlIdentity.of("https://example.com"), "mobile",
                        [_probe(), _probe(), _probe()], "2026.07.24", runs_requested=5)
    assert cc.status == "degraded"
    assert (cc.runs_requested, cc.runs_succeeded) == (5, 3)


def test_zero_probes_is_an_error_not_an_empty_success(tmp_path):
    with pytest.raises(ValueError):
        _repo(tmp_path).persist_scan("runX", UrlIdentity.of("https://example.com"), "mobile",
                                     [], "2026.07.24")
