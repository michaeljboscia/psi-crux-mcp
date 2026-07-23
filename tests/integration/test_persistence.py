"""12-table persistence + completion contract. REQ-PERSIST-005, REQ-STATE-001, REQ-DATA-002."""
from sqlalchemy import inspect

from psi_crux_core.db.models import ALL_BRANCH_TABLES
from psi_crux_core.db.repository import Repository
from psi_crux_core.parsers.insights import InsightRow
from psi_crux_core.url_identity import UrlIdentity


def _repo(tmp_path):
    return Repository(db_url=f"sqlite:///{tmp_path/'t.db'}")


def _insight():
    return InsightRow("cls_culprits", "cls-culprits-insight", "list", None, 12.0, 3, "ok", True)


def _core():
    return {"performance_score": 90, "lcp": 1200.0, "cls": 0.01, "lighthouse_version": "13.4.0"}


def test_all_12_tables_created(tmp_path):
    r = _repo(tmp_path)
    names = set(inspect(r.engine).get_table_names())
    expected = {"psi_result", "scan_run", *ALL_BRANCH_TABLES}
    assert expected <= names, f"missing tables: {expected - names}"
    assert len([t for t in names if t.startswith("psi_")]) >= 12  # full fidelity


def test_scan_round_trip_and_contract(tmp_path):
    r = _repo(tmp_path)
    idn = UrlIdentity.of("https://example.com")
    cc = r.persist_scan(
        "run1", idn, "mobile", _core(), [_insight()],
        [{"url": "https://example.com/a.js", "resource_type": "Script",
          "mime_type": "text/javascript", "transfer_size": 100, "status_code": 200}],
        [{"source_audit_id": "uses-http2", "canonical_key": "modern_http", "title": "x", "score": 0.0}],
        [{"resource_type": "script", "request_count": 1, "transfer_size": 100}],
        "2026.07.22", [], [],
    )
    assert cc.status == "complete"
    assert "psi_result" in cc.tables_written and "psi_insight" in cc.tables_written
    assert r.get_contract("run1")["status"] == "complete"


def test_partial_failure_is_surfaced_not_swallowed(tmp_path):
    """REQ-STATE-001: an injected branch failure → partial_failed, core row survives."""
    r = _repo(tmp_path)
    idn = UrlIdentity.of("https://example.com")
    cc = r.persist_scan(
        "run2", idn, "mobile", _core(), [_insight()], [], [], [], "2026.07.22", [], [],
        fault_table="psi_insight",
    )
    assert cc.status == "partial_failed"
    assert "psi_insight" in cc.tables_failed
    assert "psi_result" in cc.tables_written          # core NOT lost
    assert r.get_contract("run2")["status"] == "partial_failed"


def test_generated_columns_computed_not_written(tmp_path):
    """normalized_domain/test_date computed in Python — write never raises (no 428C9)."""
    r = _repo(tmp_path)
    cc = r.persist_scan("run3", UrlIdentity.of("https://www.Example.com/"), "mobile",
                        _core(), [], [], [], [], "2026.07.22", [], [])
    assert cc.status == "complete"
