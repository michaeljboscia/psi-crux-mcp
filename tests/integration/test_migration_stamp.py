"""
create_all vs Alembic reconciliation (LESSONS L-008).

A create_all'd DB used to carry no `alembic_version` row, so it looked un-migrated and the next
`alembic upgrade` would replay migration #1 against tables that already existed — and fail.
"""
import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from psi_crux_core.db.repository import Repository, _script_directory


def _version(engine) -> str | None:
    with engine.connect() as c:
        return c.execute(text("SELECT version_num FROM alembic_version")).scalar()


def test_fresh_db_is_stamped_at_head(tmp_path):
    r = Repository(db_url=f"sqlite:///{tmp_path/'fresh.db'}")
    assert "alembic_version" in inspect(r.engine).get_table_names()
    assert _version(r.engine) == _script_directory().get_current_head()


def test_alembic_upgrade_succeeds_on_a_create_all_db(tmp_path):
    """
    The exact failure L-008 predicted, exercised for real: run `alembic upgrade head` against a
    database built by create_all. Unstamped, alembic would replay migration #1 and die on
    'table psi_result already exists'. Stamped, it is a clean no-op.
    """
    import subprocess
    import sys

    db = tmp_path / "up.db"
    Repository(db_url=f"sqlite:///{db}")            # create_all + auto-stamp
    before = set(inspect(create_engine(f"sqlite:///{db}")).get_table_names())

    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).parents[2],
        env={**os.environ, "PSI_CRUX_DB_URL": f"sqlite:///{db}"},
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"upgrade failed:\n{proc.stderr}"
    assert "already exists" not in (proc.stderr + proc.stdout)
    after = set(inspect(create_engine(f"sqlite:///{db}")).get_table_names())
    assert after == before                          # no-op, nothing rebuilt or dropped


def test_reopening_an_existing_db_does_not_restamp(tmp_path):
    db = f"sqlite:///{tmp_path/'reopen.db'}"
    first = _version(Repository(db_url=db).engine)
    assert _version(Repository(db_url=db).engine) == first


def test_persist_still_works_on_a_stamped_db(tmp_path):
    """Stamping must not disturb the drop-in write path."""
    from psi_crux_core.db.models import ALL_BRANCH_TABLES
    from psi_crux_core.db.probe import ProbeRows
    from psi_crux_core.url_identity import UrlIdentity

    r = Repository(db_url=f"sqlite:///{tmp_path/'w.db'}")
    cc = r.persist_scan(
        "s1", UrlIdentity.of("https://example.com"), "mobile",
        [ProbeRows(core={"fcp": 1.0, "tti": 2.0}, branches={t: [] for t in ALL_BRANCH_TABLES})],
        "2026.07.24",
    )
    assert cc.status == "complete"
