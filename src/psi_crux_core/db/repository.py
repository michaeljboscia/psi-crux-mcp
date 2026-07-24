"""
Persistence repository. FEAT-008, REQ-PERSIST-005, REQ-STATE-001, REQ-DATA-001/002.

Writes a scan across the 12-table schema. Each branch writes inside a SAVEPOINT: a branch
failure is recorded in tables_failed WITHOUT losing the core row or the other branches.

The completion contract is COUNT-based (harvest G2). Recording table NAMES was not enough:
a table that received zero rows still landed in `tables_written`, so "complete" only ever
meant "nothing threw." Every branch now records expected-vs-actual row counts, verified by
a SELECT COUNT after the write — "insert N, verify N exist," the single most-repeated lesson
in the whole corpus. A mismatch downgrades the run to `degraded` rather than passing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import Session

from ..logging import get_logger
from ..url_identity import UrlIdentity
from .models import (
    ALL_BRANCH_TABLES, Base, PsiBestPractice, PsiCruxField, PsiCwvElement, PsiDiagnostic,
    PsiInsight, PsiMainThread, PsiNetworkRequest, PsiOpportunity, PsiResourceSummary,
    PsiResult, PsiScript, PsiThirdParty, ScanRun,
)
from .probe import ProbeRows, select_median_index

# table name → (model, natural key fields used for dedup-before-insert)
#
# Tables whose natural key is a long URL/selector carry NO DB unique constraint (Postgres
# btree caps ~2704 bytes; GTM needed an md5(url) EXPRESSION index, which cannot be an
# ON CONFLICT target). Python dedup is the enforcement point for those, and it is applied
# uniformly so a duplicate key can never turn into an IntegrityError that fails a branch.
_TABLES: dict[str, tuple[Any, tuple[str, ...]]] = {
    "psi_insight": (PsiInsight, ("canonical_key",)),
    "psi_network_request": (PsiNetworkRequest, ("url",)),
    "psi_best_practice": (PsiBestPractice, ("canonical_key",)),
    "psi_resource_summary": (PsiResourceSummary, ("resource_type",)),
    "psi_main_thread": (PsiMainThread, ("group",)),
    "psi_script": (PsiScript, ("url",)),
    "psi_opportunity": (PsiOpportunity, ("canonical_key",)),
    "psi_third_party": (PsiThirdParty, ("canonical_key", "entity")),
    "psi_cwv_element": (PsiCwvElement, ("canonical_key", "selector")),
    "psi_crux_field": (PsiCruxField, ("granularity", "form_factor", "metric")),
    "psi_diagnostic": (PsiDiagnostic, ("canonical_key",)),
}

_INSIGHT_FIELDS = ("canonical_key", "source_audit_id", "details_type", "score",
                   "savings_ms", "item_count", "parse_status")

_log = get_logger("repository")


def _script_directory():
    """Alembic's view of the migrations shipped inside this package."""
    from alembic.config import Config as AlembicConfig
    from alembic.script import ScriptDirectory

    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    return ScriptDirectory.from_config(cfg)


def _stamp_head(engine) -> str | None:
    """
    Record the current migration head against a DB we just created (LESSONS L-008).

    `create_all` builds the schema directly from the models and writes NO `alembic_version`
    row. Such a database looks un-migrated, so the next `alembic upgrade` would try to replay
    migration #1 against tables that already exist and fail. Stamping at creation time keeps
    the zero-config drop-in path and the managed-upgrade path on the same timeline.
    """
    from alembic.runtime.migration import MigrationContext

    script = _script_directory()
    with engine.begin() as conn:
        MigrationContext.configure(conn).stamp(script, "head")
    return script.get_current_head()


@dataclass
class CompletionContract:
    """
    STATE-001. `reconciliation` is {table: {"expected": int|None, "actual": int}}.
    expected=None means the stage never ran — a hard fail, never a silent 0==0 pass.
    """
    run_id: str
    status: str = "complete"        # complete | degraded | partial_failed | failed
    reconciliation: dict = field(default_factory=dict)
    tables_failed: list[str] = field(default_factory=list)
    parser_warnings: list[str] = field(default_factory=list)
    compat_warnings: list[str] = field(default_factory=list)
    runs_requested: int = 1
    runs_succeeded: int = 1

    @property
    def tables_written(self) -> list[str]:
        """Derived, for back-compat. A table only counts as written if rows actually landed."""
        return [t for t, r in self.reconciliation.items() if r["actual"] > 0]

    @property
    def mismatched(self) -> list[str]:
        return [t for t, r in self.reconciliation.items() if r["expected"] != r["actual"]]

    def as_dict(self) -> dict:
        return {
            "run_id": self.run_id, "status": self.status,
            "reconciliation": self.reconciliation,
            "tables_written": self.tables_written,
            "tables_failed": self.tables_failed,
            "mismatched": self.mismatched,
            "runs_requested": self.runs_requested,
            "runs_succeeded": self.runs_succeeded,
        }


def _normalized_domain(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url).split("/")[0].lower()


def _get(row, name: str):
    """Rows arrive as dicts (most parsers) or dataclasses (insights). Read either."""
    return row.get(name) if isinstance(row, dict) else getattr(row, name, None)


def _dedupe(rows: list, key_fields: tuple[str, ...]) -> tuple[list, int]:
    """Drop repeat natural keys, keeping the FIRST occurrence. Returns (kept, dropped_count)."""
    seen, kept = set(), []
    for r in rows:
        k = tuple(_get(r, f) for f in key_fields)
        if k in seen:
            continue
        seen.add(k)
        kept.append(r)
    return kept, len(rows) - len(kept)


def _build(table: str, model: Any, psi_result_id: int, rows: list) -> list:
    if table == "psi_insight":
        return [model(psi_result_id=psi_result_id,
                      **{f: _get(r, f) for f in _INSIGHT_FIELDS}) for r in rows]
    return [model(psi_result_id=psi_result_id, **r) for r in rows]


class Repository:
    def __init__(self, db_url: str | None = None, artifact_root: Path | None = None) -> None:
        if db_url is None:
            root = artifact_root or Path.cwd()
            root.mkdir(parents=True, exist_ok=True)
            db_url = f"sqlite:///{root / 'psi_crux.db'}"
        self.engine = create_engine(db_url)

        # A DB is "fresh" only if it holds none of OUR tables. An alembic_version row on its
        # own doesn't count as content — that is a stamped-but-empty DB, still fresh.
        existing = set(inspect(self.engine).get_table_names())
        fresh = not (existing - {"alembic_version"})

        Base.metadata.create_all(self.engine)

        if fresh:
            try:
                head = _stamp_head(self.engine)
                _log.info("db_created_and_stamped", head=head)
            except Exception as e:                  # noqa: BLE001 — never block the drop-in path
                # Non-fatal by design (REQ-CFG/L-005: hardening must not break the happy path),
                # but it must be SAID. An unstamped DB fails later, during someone's upgrade.
                _log.warning("db_stamp_failed", error=str(e),
                             resolution="run `alembic stamp head` before the next upgrade")
        elif "alembic_version" not in existing:
            # Pre-existing tables with no version row: created by an older build of this code.
            # Its true revision is unknowable from here — guessing a stamp could skip a real
            # migration and silently corrupt the schema. Say so; let a human stamp it.
            _log.warning(
                "db_unstamped_legacy",
                resolution="this database predates auto-stamping; verify its schema, then run "
                           "`alembic stamp <revision>` to put it under migration control",
            )

    def persist_scan(
        self, run_id: str, identity: UrlIdentity, strategy: str,
        probes: list[ProbeRows], registry_version: str,
        parser_warnings: list[str] | None = None, compat_warnings: list[str] | None = None,
        runs_requested: int | None = None,
        fault_table: str | None = None,     # test hook: force a named branch to fail
    ) -> CompletionContract:
        """
        Persist a probe group. ALL probes land as psi_result rows sharing `probe_group_id`;
        exactly one is flagged `is_median` and is the sole FK parent for branch rows (G10).
        """
        if not probes:
            raise ValueError("persist_scan requires at least one probe")

        cc = CompletionContract(
            run_id=run_id,
            parser_warnings=list(parser_warnings or []),
            compat_warnings=list(compat_warnings or []),
            runs_requested=runs_requested if runs_requested is not None else len(probes),
            runs_succeeded=len(probes),
        )
        median_i = select_median_index(probes)

        with Session(self.engine) as s:
            median_id = 0
            for i, probe in enumerate(probes):
                row = self._core_row(run_id, i, i == median_i, identity, strategy,
                                     probe.core, registry_version)
                s.add(row)
                s.flush()                                   # assign row.id
                if i == median_i:
                    median_id = row.id

            median_branches = probes[median_i].branches
            for table in ALL_BRANCH_TABLES:
                model, key_fields = _TABLES[table]
                if table not in median_branches:
                    # Stage never ran. expected=None so this can NEVER read as a clean 0==0.
                    cc.reconciliation[table] = {"expected": None, "actual": 0}
                    continue
                rows, dropped = _dedupe(median_branches[table] or [], key_fields)
                if dropped:
                    cc.parser_warnings.append(
                        f"{table}: dropped {dropped} duplicate row(s) on {'+'.join(key_fields)}")
                try:
                    with s.begin_nested():                  # SAVEPOINT per branch (REQ-DATA-002)
                        if fault_table == table:
                            raise RuntimeError(f"injected fault in {table}")
                        s.add_all(_build(table, model, median_id, rows))
                        s.flush()
                    actual = s.scalar(
                        select(func.count()).select_from(model)
                        .where(model.psi_result_id == median_id)
                    )
                    cc.reconciliation[table] = {"expected": len(rows), "actual": int(actual or 0)}
                except Exception as e:                      # noqa: BLE001 — record, don't abort
                    cc.tables_failed.append(table)
                    cc.reconciliation[table] = {"expected": len(rows), "actual": 0}
                    cc.parser_warnings.append(f"{table} write failed: {e}")

            cc.status = self._verdict(cc)
            s.add(ScanRun(
                run_id=run_id, status=cc.status, reconciliation=cc.reconciliation,
                tables_written=cc.tables_written, tables_failed=cc.tables_failed,
                parser_warnings=cc.parser_warnings, compat_warnings=cc.compat_warnings,
                compat_registry_version=registry_version,
                runs_requested=cc.runs_requested, runs_succeeded=cc.runs_succeeded,
            ))
            s.commit()
        return cc

    @staticmethod
    def _verdict(cc: CompletionContract) -> str:
        """
        A branch that THREW is `partial_failed`. A branch that wrote a different number of rows
        than it was handed — or never ran at all — is `degraded`: nothing raised, but the data
        on disk does not match what the parse produced, and that must not report as complete.
        """
        if cc.tables_failed:
            return "partial_failed"
        if cc.mismatched or cc.runs_succeeded < cc.runs_requested:
            return "degraded"
        return "complete"

    @staticmethod
    def _core_row(run_id: str, index: int, is_median: bool, identity: UrlIdentity,
                  strategy: str, core: dict, registry_version: str) -> PsiResult:
        return PsiResult(
            run_id=run_id, probe_group_id=run_id, probe_index=index, is_median=is_median,
            input_url=identity.input_url, canonical_url=identity.canonical_url,
            final_url=identity.final_url, storage_key_url=identity.storage_key_url,
            normalized_domain=_normalized_domain(identity.canonical_url), strategy=strategy,
            performance_score=core.get("performance_score"),
            best_practices_score=core.get("best_practices_score"),
            accessibility_score=core.get("accessibility_score"), seo_score=core.get("seo_score"),
            fcp=core.get("fcp"), lcp=core.get("lcp"), cls=core.get("cls"),
            speed_index=core.get("speed_index"), tti=core.get("tti"), tbt=core.get("tbt"),
            runtime_error_code=core.get("runtime_error_code"),
            lighthouse_version=core.get("lighthouse_version"),
            tested_at=datetime.now(timezone.utc), test_date=date.today(),
            compat_registry_version=registry_version,
        )

    def get_contract(self, run_id: str) -> dict | None:
        with Session(self.engine) as s:
            row = s.get(ScanRun, run_id)
            if row is None:
                return None
            return {"run_id": row.run_id, "status": row.status,
                    "reconciliation": row.reconciliation,
                    "tables_written": row.tables_written, "tables_failed": row.tables_failed,
                    "runs_requested": row.runs_requested, "runs_succeeded": row.runs_succeeded}
