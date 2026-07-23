"""
Persistence repository. FEAT-008, REQ-PERSIST-005, REQ-STATE-001, REQ-DATA-001/002.
Writes a scan across the 12-table schema. Each branch writes inside a SAVEPOINT: a branch failure
is recorded in tables_failed (status → partial_failed) WITHOUT losing the core row or the other
branches. Emits the STATE-001 completion contract; a tool must not report success unless status=complete.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ..url_identity import UrlIdentity
from .models import (
    Base, PsiBestPractice, PsiCwvElement, PsiInsight, PsiMainThread, PsiNetworkRequest,
    PsiOpportunity, PsiResourceSummary, PsiResult, PsiScript, PsiThirdParty, ScanRun,
)


@dataclass
class CompletionContract:
    run_id: str
    status: str = "complete"                       # complete | partial_failed | failed
    tables_written: list[str] = field(default_factory=list)
    tables_failed: list[str] = field(default_factory=list)
    parser_warnings: list[str] = field(default_factory=list)
    compat_warnings: list[str] = field(default_factory=list)


def _normalized_domain(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url).split("/")[0].lower()


class Repository:
    def __init__(self, db_url: str | None = None, artifact_root: Path | None = None) -> None:
        if db_url is None:
            root = artifact_root or Path.cwd()
            root.mkdir(parents=True, exist_ok=True)
            db_url = f"sqlite:///{root / 'psi_crux.db'}"
        self.engine = create_engine(db_url)
        Base.metadata.create_all(self.engine)

    def persist_scan(
        self, run_id: str, identity: UrlIdentity, strategy: str, core: dict,
        insight_rows: list, network_rows: list[dict], bp_rows: list[dict],
        resource_rows: list[dict], registry_version: str,
        parser_warnings: list[str], compat_warnings: list[str],
        main_thread_rows: list[dict] | None = None, script_rows: list[dict] | None = None,
        opportunity_rows: list[dict] | None = None, third_party_rows: list[dict] | None = None,
        cwv_element_rows: list[dict] | None = None,
        fault_table: str | None = None,     # test hook: force a named branch to fail
    ) -> CompletionContract:
        cc = CompletionContract(
            run_id=run_id, parser_warnings=parser_warnings, compat_warnings=compat_warnings,
        )
        with Session(self.engine) as s:
            result = PsiResult(
                run_id=run_id, input_url=identity.input_url, canonical_url=identity.canonical_url,
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
            s.add(result)
            s.flush()                       # get result.id
            cc.tables_written.append("psi_result")

            branches = {
                "psi_insight": [PsiInsight(
                    psi_result_id=result.id, canonical_key=r.canonical_key,
                    source_audit_id=r.source_audit_id, details_type=r.details_type,
                    score=r.score, savings_ms=r.savings_ms, item_count=r.item_count,
                    parse_status=r.parse_status) for r in insight_rows],
                "psi_network_request": [PsiNetworkRequest(psi_result_id=result.id, **row)
                                        for row in network_rows],
                "psi_best_practice": [PsiBestPractice(psi_result_id=result.id, **row)
                                      for row in bp_rows],
                "psi_resource_summary": [PsiResourceSummary(psi_result_id=result.id, **row)
                                         for row in resource_rows],
                "psi_main_thread": [PsiMainThread(psi_result_id=result.id, **row)
                                    for row in (main_thread_rows or [])],
                "psi_script": [PsiScript(psi_result_id=result.id, **row)
                               for row in (script_rows or [])],
                "psi_opportunity": [PsiOpportunity(psi_result_id=result.id, **row)
                                    for row in (opportunity_rows or [])],
                "psi_third_party": [PsiThirdParty(psi_result_id=result.id, **row)
                                    for row in (third_party_rows or [])],
                "psi_cwv_element": [PsiCwvElement(psi_result_id=result.id, **row)
                                    for row in (cwv_element_rows or [])],
            }
            for table, objs in branches.items():
                try:
                    with s.begin_nested():          # SAVEPOINT per branch (REQ-DATA-002)
                        if fault_table == table:
                            raise RuntimeError(f"injected fault in {table}")
                        s.add_all(objs)
                    cc.tables_written.append(table)
                except Exception as e:              # noqa: BLE001 — record, don't abort the run
                    cc.tables_failed.append(table)
                    cc.parser_warnings.append(f"{table} write failed: {e}")

            cc.status = "complete" if not cc.tables_failed else "partial_failed"
            s.add(ScanRun(
                run_id=run_id, status=cc.status, tables_written=cc.tables_written,
                tables_failed=cc.tables_failed, parser_warnings=cc.parser_warnings,
                compat_warnings=cc.compat_warnings, compat_registry_version=registry_version,
            ))
            s.commit()
        return cc

    def get_contract(self, run_id: str) -> dict | None:
        with Session(self.engine) as s:
            row = s.get(ScanRun, run_id)
            if row is None:
                return None
            return {"run_id": row.run_id, "status": row.status,
                    "tables_written": row.tables_written, "tables_failed": row.tables_failed}
