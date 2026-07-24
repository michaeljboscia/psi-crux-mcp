"""
12-table persistence schema. FEAT-008, REQ-PERSIST-005, D-13 (full fidelity).
Generic OSS names (no org-specific naming). 1 core (`psi_result`) + 11 branch tables + `scan_run`
(the completion contract, STATE-001). Engine-portable (SQLite default / Postgres). Audit-derived
rows key on `canonical_key`, retain `source_audit_id` (REQ-ID-001). normalized_domain + test_date
are computed in Python (portable; avoids DB-generated-column write hazards).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ScanRun(Base):
    """
    STATE-001 completion contract, persisted per run. COUNT-based, not name-based: a table
    that received zero rows must not be able to pass as written (harvest G2/G3). `reconciliation`
    holds {table: {expected, actual}} where expected=None means the stage NEVER RAN — distinct
    from expected=0 ("ran, legitimately empty"). Conflating those lets a never-run stage pass
    as 0==0, which is the exact quiet failure this contract exists to prevent.
    """
    __tablename__ = "scan_run"
    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(16))     # complete|degraded|partial_failed|failed
    reconciliation: Mapped[dict] = mapped_column(JSON, default=dict)
    tables_written: Mapped[dict] = mapped_column(JSON, default=list)   # derived, back-compat
    tables_failed: Mapped[dict] = mapped_column(JSON, default=list)
    parser_warnings: Mapped[dict] = mapped_column(JSON, default=list)
    compat_warnings: Mapped[dict] = mapped_column(JSON, default=list)
    compat_registry_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    runs_requested: Mapped[int] = mapped_column(default=1)   # G10 multi-probe
    runs_succeeded: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))


class PsiResult(Base):
    """
    CORE. FK source for all branch rows.

    Deliberately carries NO uniqueness beyond the surrogate id: repeat audits of the same
    URL/device/day are a TIME SERIES, not duplicates (re-running is how you verify a fix).
    Lighthouse is noisy run-to-run, so accuracy comes from `runs=N` multi-probe (G10) rather
    than from collapsing rows: all N probes persist and share a `probe_group_id`, exactly one
    is flagged `is_median`, and only that one feeds the branch tables. Uniqueness IS enforced
    on the branch tables, where a repeated key is a genuine parser bug.
    """
    __tablename__ = "psi_result"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    probe_group_id: Mapped[str] = mapped_column(String(64), index=True)   # G10: groups the N probes
    probe_index: Mapped[int] = mapped_column(default=0)                   # 0..N-1 within the group
    is_median: Mapped[bool] = mapped_column(default=True)                 # branches hang off this one
    input_url: Mapped[str] = mapped_column(String(2048))
    canonical_url: Mapped[str] = mapped_column(String(2048), index=True)
    final_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    storage_key_url: Mapped[str] = mapped_column(String(2048), index=True)
    normalized_domain: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    strategy: Mapped[str] = mapped_column(String(16))
    performance_score: Mapped[int | None] = mapped_column(nullable=True)
    best_practices_score: Mapped[int | None] = mapped_column(nullable=True)
    accessibility_score: Mapped[int | None] = mapped_column(nullable=True)
    seo_score: Mapped[int | None] = mapped_column(nullable=True)
    fcp: Mapped[float | None] = mapped_column(nullable=True)
    lcp: Mapped[float | None] = mapped_column(nullable=True)
    cls: Mapped[float | None] = mapped_column(nullable=True)
    speed_index: Mapped[float | None] = mapped_column(nullable=True)
    tti: Mapped[float | None] = mapped_column(nullable=True)
    tbt: Mapped[float | None] = mapped_column(nullable=True)
    runtime_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lighthouse_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tested_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    test_date: Mapped[date] = mapped_column(default=date.today)     # computed in Python (portable)
    compat_registry_version: Mapped[str | None] = mapped_column(String(32), nullable=True)

    insights: Mapped[list["PsiInsight"]] = relationship(cascade="all, delete-orphan")
    network_requests: Mapped[list["PsiNetworkRequest"]] = relationship(cascade="all, delete-orphan")
    best_practices: Mapped[list["PsiBestPractice"]] = relationship(cascade="all, delete-orphan")


class _Branch(Base):
    """Shared base for audit-derived branch rows (canonical_key identity, REQ-ID-001)."""
    __abstract__ = True
    id: Mapped[int] = mapped_column(primary_key=True)
    psi_result_id: Mapped[int] = mapped_column(ForeignKey("psi_result.id", ondelete="CASCADE"), index=True)
    canonical_key: Mapped[str] = mapped_column(String(64), index=True)
    source_audit_id: Mapped[str] = mapped_column(String(96))


class PsiInsight(_Branch):
    __tablename__ = "psi_insight"
    __table_args__ = (UniqueConstraint("psi_result_id", "canonical_key",
                                       name="uq_psi_insight_result_key"),)
    details_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    score: Mapped[float | None] = mapped_column(nullable=True)
    savings_ms: Mapped[float | None] = mapped_column(nullable=True)
    item_count: Mapped[int] = mapped_column(default=0)
    parse_status: Mapped[str] = mapped_column(String(16), default="ok")
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class PsiNetworkRequest(Base):
    """
    No DB unique constraint: the natural key is `url`, which is too long to index portably
    (Postgres btree caps ~2704 bytes). GTM hit this and solved it with an md5(url) EXPRESSION
    index — which cannot be an ON CONFLICT target — so it deduped in Python instead. Same here:
    `dedupe_by` in the repository is the enforcement point (harvest §4.1).
    """
    __tablename__ = "psi_network_request"
    id: Mapped[int] = mapped_column(primary_key=True)
    psi_result_id: Mapped[int] = mapped_column(ForeignKey("psi_result.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(2048))
    resource_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    transfer_size: Mapped[int | None] = mapped_column(nullable=True)     # clamped >=0 or null
    status_code: Mapped[int | None] = mapped_column(nullable=True)


class PsiBestPractice(_Branch):
    __tablename__ = "psi_best_practice"
    __table_args__ = (UniqueConstraint("psi_result_id", "canonical_key",
                                       name="uq_psi_best_practice_result_key"),)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    score: Mapped[float | None] = mapped_column(nullable=True)


# --- remaining branch tables (schema present now for full 12-table fidelity; parsers wire in
#     incrementally, same pattern). Keeps the migration/schema complete per D-13. ---
class PsiCruxField(Base):
    """
    CrUX field data lifted from the PSI response itself (G9) — `loadingExperience` is URL-level,
    `originLoadingExperience` is origin-level. `granularity` keeps them apart (G5): an
    origin-aggregated CLS of 0.04 once shipped to a client while the actual homepage was 1.52.
    Origin data must never silently stand in for page data, so the distinction is a KEY column,
    not a comment.
    """
    __tablename__ = "psi_crux_field"
    __table_args__ = (UniqueConstraint("psi_result_id", "granularity", "form_factor", "metric",
                                       name="uq_psi_crux_field_result_metric"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    psi_result_id: Mapped[int] = mapped_column(ForeignKey("psi_result.id", ondelete="CASCADE"), index=True)
    granularity: Mapped[str] = mapped_column(String(8))          # "url" | "origin" — never mixed
    form_factor: Mapped[str] = mapped_column(String(16))
    metric: Mapped[str] = mapped_column(String(64))
    category: Mapped[str | None] = mapped_column(String(24), nullable=True)
    p75: Mapped[float | None] = mapped_column(nullable=True)
    good: Mapped[float | None] = mapped_column(nullable=True)
    ni: Mapped[float | None] = mapped_column(nullable=True)
    poor: Mapped[float | None] = mapped_column(nullable=True)
    fid_p75: Mapped[float | None] = mapped_column(nullable=True)   # legacy, always null from live API


class PsiOpportunity(_Branch):
    """One row per opportunity AUDIT (bytes summed across its items), matching GTM's
    (psi_result_id, opportunity_id) key. Per-item rows would repeat the audit-level
    `overallSavingsMs` on every row and make the key ambiguous."""
    __tablename__ = "psi_opportunity"
    __table_args__ = (UniqueConstraint("psi_result_id", "canonical_key",
                                       name="uq_psi_opportunity_result_key"),)
    wasted_bytes: Mapped[int | None] = mapped_column(nullable=True)
    wasted_ms: Mapped[float | None] = mapped_column(nullable=True)
    item_count: Mapped[int] = mapped_column(default=0)


class PsiThirdParty(_Branch):
    __tablename__ = "psi_third_party"
    __table_args__ = (UniqueConstraint("psi_result_id", "canonical_key", "entity",
                                       name="uq_psi_third_party_result_entity"),)
    entity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transfer_size: Mapped[int | None] = mapped_column(nullable=True)
    blocking_time: Mapped[float | None] = mapped_column(nullable=True)


class PsiDiagnostic(_Branch):
    __tablename__ = "psi_diagnostic"
    __table_args__ = (UniqueConstraint("psi_result_id", "canonical_key",
                                       name="uq_psi_diagnostic_result_key"),)
    numeric_value: Mapped[float | None] = mapped_column(nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class PsiCwvElement(_Branch):
    """No DB constraint — natural key includes `selector` (unbounded length). Python-deduped."""
    __tablename__ = "psi_cwv_element"
    selector: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    score: Mapped[float | None] = mapped_column(nullable=True)


class PsiMainThread(Base):
    __tablename__ = "psi_main_thread"
    __table_args__ = (UniqueConstraint("psi_result_id", "group",
                                       name="uq_psi_main_thread_result_group"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    psi_result_id: Mapped[int] = mapped_column(ForeignKey("psi_result.id", ondelete="CASCADE"), index=True)
    group: Mapped[str] = mapped_column(String(64))
    duration_ms: Mapped[float | None] = mapped_column(nullable=True)


class PsiScript(Base):
    """No DB constraint — natural key is `url` (too long to index portably). Python-deduped."""
    __tablename__ = "psi_script"
    id: Mapped[int] = mapped_column(primary_key=True)
    psi_result_id: Mapped[int] = mapped_column(ForeignKey("psi_result.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(2048))
    total_ms: Mapped[float | None] = mapped_column(nullable=True)
    wasted_bytes: Mapped[int | None] = mapped_column(nullable=True)


class PsiResourceSummary(Base):
    __tablename__ = "psi_resource_summary"
    __table_args__ = (UniqueConstraint("psi_result_id", "resource_type",
                                       name="uq_psi_resource_summary_result_type"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    psi_result_id: Mapped[int] = mapped_column(ForeignKey("psi_result.id", ondelete="CASCADE"), index=True)
    resource_type: Mapped[str] = mapped_column(String(32))
    request_count: Mapped[int | None] = mapped_column(nullable=True)
    transfer_size: Mapped[int | None] = mapped_column(nullable=True)


# The 12 fidelity tables: psi_result + psi_insight, psi_network_request, psi_best_practice,
# psi_crux_field, psi_opportunity, psi_third_party, psi_diagnostic, psi_cwv_element,
# psi_main_thread, psi_script, psi_resource_summary  (+ scan_run for the completion contract).
ALL_BRANCH_TABLES = [
    "psi_insight", "psi_network_request", "psi_best_practice", "psi_crux_field",
    "psi_opportunity", "psi_third_party", "psi_diagnostic", "psi_cwv_element",
    "psi_main_thread", "psi_script", "psi_resource_summary",
]
