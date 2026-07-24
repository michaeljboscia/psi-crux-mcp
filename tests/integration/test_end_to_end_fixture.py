"""
Full pipeline on the LIVE-captured LH13.4.0 fixture: parse → project → persist → contract.
No API key required, so CI runs it. This is the reality test for the harvest gap fixes —
a stub or a silently-empty branch cannot pass it.
"""
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from psi_crux_core.compat.registry import CompatRegistry
from psi_crux_core.db.models import ALL_BRANCH_TABLES, PsiCruxField, PsiResult
from psi_crux_core.db.probe import ProbeRows
from psi_crux_core.db.repository import Repository
from psi_crux_core.parsers.summary import assemble, project
from psi_crux_core.psi_audit_service import _branch_rows
from psi_crux_core.url_identity import UrlIdentity

FIXTURE = Path(__file__).parents[2] / "reference/fixtures/lh13-wikipedia-mobile.raw.json"


@pytest.fixture(scope="module")
def payload():
    if not FIXTURE.exists():
        pytest.skip("live LH13 fixture not present")
    return json.loads(FIXTURE.read_text())


@pytest.fixture()
def persisted(tmp_path, payload):
    scan = assemble(payload, CompatRegistry.load(), "mobile")
    repo = Repository(db_url=f"sqlite:///{tmp_path/'e2e.db'}")
    idn = UrlIdentity.of("https://www.wikipedia.org", final_url=scan.core.get("final_url"))
    cc = repo.persist_scan("e2e", idn, "mobile",
                           [ProbeRows(core=scan.core, branches=_branch_rows(scan))],
                           CompatRegistry.load().version)
    return repo, scan, cc


def test_every_branch_table_is_wired(persisted):
    """G3: no table may be missing from reconciliation — that is the 'never ran' signal."""
    _, _, cc = persisted
    assert set(cc.reconciliation) == set(ALL_BRANCH_TABLES)
    never_ran = [t for t, r in cc.reconciliation.items() if r["expected"] is None]
    assert never_ran == [], f"unwired tables: {never_ran}"


def test_run_is_complete_with_matching_row_counts(persisted):
    """G2: every expected count must equal what actually landed on disk."""
    _, _, cc = persisted
    assert cc.mismatched == [], f"row-count mismatch: {cc.mismatched}"
    assert cc.status == "complete"


def test_real_data_landed_not_just_empty_tables(persisted):
    """A contract full of legitimate zeros would pass reconciliation but prove nothing."""
    _, _, cc = persisted
    populated = [t for t, r in cc.reconciliation.items() if r["actual"] > 0]
    assert len(populated) >= 6, f"only {populated} populated"
    for t in ("psi_insight", "psi_network_request", "psi_crux_field", "psi_diagnostic"):
        assert cc.reconciliation[t]["actual"] > 0, f"{t} wrote nothing"


def test_crux_field_rows_carry_both_granularities(persisted):
    """G5/G9: field data came from the PSI payload and origin/url stayed distinct."""
    repo, _, _ = persisted
    with Session(repo.engine) as s:
        grans = set(s.scalars(select(PsiCruxField.granularity)).all())
        assert grans == {"url", "origin"}
        cls = s.scalars(select(PsiCruxField.p75).where(
            PsiCruxField.metric == "cumulative_layout_shift")).all()
        assert all(v is None or v <= 1.0 for v in cls), "CLS not descaled from the x100 transport"


def test_storage_key_folds_www(persisted):
    """G4: the www input must land under the bare-host storage key."""
    repo, _, _ = persisted
    with Session(repo.engine) as s:
        key = s.scalar(select(PsiResult.storage_key_url))
        assert key == "https://wikipedia.org"


def test_projection_stays_within_budget(persisted):
    _, scan, _ = persisted
    from psi_crux_core.projection import MAX_RESULT_BYTES
    _, data = project(scan, "https://wikipedia.org", "e2e")
    assert len(json.dumps(data, default=str).encode()) <= MAX_RESULT_BYTES


def test_single_probe_is_flagged_median(persisted):
    repo, _, _ = persisted
    with Session(repo.engine) as s:
        assert s.scalar(select(func.count()).select_from(PsiResult)
                        .where(PsiResult.is_median.is_(True))) == 1
