"""
PsiAuditService — the capability behind the `psi_audit` and `recommend` tools. FEAT-001/003.
Orchestrates: PSI call → runtimeError check → assemble → project → persist (12 tables) → artifact →
dual-content + completion contract. Keeps a small in-memory cache of recent scans so `recommend(run_id)`
reuses the parse. Pure core (REQ-CORE-001); the MCP/Prefect wrappers just format the result.
"""
from __future__ import annotations

from collections import OrderedDict

from .artifact import ArtifactStore, new_run_id
from .compat.registry import CompatRegistry
from .config import Config
from .db.probe import ProbeRows, select_median_index
from .db.repository import Repository
from .keyring import Keyring
from .logging import get_logger, register_secret
from .parsers.metrics import PsiRuntimeError, check_runtime_error
from .parsers.summary import PsiScan, assemble, project
from .psi_client import PsiClient
from .recommend import recommend as _recommend
from .url_identity import UrlIdentity

_log = get_logger("psi_audit")

# Each probe is 1 quota unit against a 25,000/day free-tier budget, so accuracy is cheap —
# but N probes is also N x latency, and the median stops improving well before this.
MAX_RUNS = 9


def _branch_rows(scan: PsiScan) -> dict[str, list]:
    """
    PsiScan → {table: rows}. A table is included ONLY if its parser actually ran; an omitted
    key means "never ran" (expected=None) in the completion contract, which fails loudly.
    Every one of the 11 branch tables is wired here — that is what closes G3.
    """
    return {
        "psi_insight": scan.insights.rows,
        "psi_network_request": scan.network_rows,
        "psi_best_practice": scan.bp_rows,
        "psi_resource_summary": scan.resource_rows,
        "psi_main_thread": scan.main_thread_rows,
        "psi_script": scan.script_rows,
        "psi_opportunity": scan.opportunity_rows,
        "psi_third_party": scan.third_party_rows,
        "psi_cwv_element": scan.cwv_element_rows,
        "psi_crux_field": scan.crux_field_rows,
        "psi_diagnostic": scan.diagnostic_rows,
    }


class PsiAuditService:
    def __init__(self, config: Config) -> None:
        keys = config.psi_api_keys or config.crux_api_keys
        for pair in keys:
            register_secret(pair.split(":", 1)[0])
        self._secrets = tuple(p.split(":", 1)[0] for p in keys)
        self._client = PsiClient(Keyring.from_pairs(keys), timeout_s=config.psi_timeout_s)
        self._registry = CompatRegistry.load()
        self._artifacts = ArtifactStore(config.artifact_root)
        self._repo = Repository(artifact_root=config.artifact_root)
        self._cache: OrderedDict[str, tuple[UrlIdentity, str, PsiScan]] = OrderedDict()

    def audit(self, url: str, strategy: str = "mobile", runs: int = 1) -> dict:
        """
        Full PSI audit → projected dual-content + persisted 12 tables + completion contract.

        `runs` > 1 fires N probes and reports the MEDIAN (G10). Lighthouse varies 5-15% run to
        run on an unchanged page, so a single probe gives a number you cannot reproduce. All N
        probes persist; only the median feeds the branch tables.
        """
        run_id = new_run_id()
        requested = max(1, min(int(runs), MAX_RUNS))

        scans: list[PsiScan] = []
        payloads: list[dict] = []
        failures: list[str] = []
        for i in range(requested):
            try:
                payload = self._client.run_pagespeed(url, strategy)
                check_runtime_error(payload)              # PDF/404/timeout → PsiRuntimeError
            except PsiRuntimeError:
                # The TARGET is unfetchable; more probes cannot change that. Fail fast.
                raise
            except Exception as e:                        # noqa: BLE001 — one bad probe ≠ dead run
                failures.append(f"probe {i}: {type(e).__name__}: {e}")
                _log.warning("psi_probe_failed", run_id=run_id, probe=i, error=type(e).__name__)
                continue
            payloads.append(payload)
            scans.append(assemble(payload, self._registry, strategy))

        if not scans:
            raise RuntimeError(f"all {requested} PSI probe(s) failed: {'; '.join(failures)}")

        probes = [ProbeRows(core=s.core, branches=_branch_rows(s)) for s in scans]
        median_i = select_median_index(probes)            # same pure fn the repository uses
        median_scan = scans[median_i]

        idn = UrlIdentity.of(url, final_url=median_scan.core.get("final_url"))
        markdown, data = project(median_scan, idn.canonical_url, run_id)

        self._artifacts.write(run_id, payloads[median_i], data, self._secrets)
        cc = self._repo.persist_scan(
            run_id, idn, strategy, probes, self._registry.version,
            parser_warnings=failures, compat_warnings=median_scan.compat_warnings,
            runs_requested=requested,
        )
        self._remember(run_id, idn, strategy, median_scan)
        _log.info("psi_audit_ok", run_id=run_id, status=cc.status, target=idn.canonical_url,
                  runs_requested=requested, runs_succeeded=len(scans))

        note = f"\n\n_persisted: {cc.status}_"
        if requested > 1:
            note += (f" · median of {len(scans)}/{requested} probe(s)"
                     f"{' — SOME PROBES FAILED' if failures else ''}")
        if cc.mismatched:
            note += f"\n\n_⚠ row-count mismatch: {', '.join(cc.mismatched)}_"
        return {
            "run_id": run_id,
            "content_markdown": markdown + note,
            "data": {**data, "completion": cc.as_dict()},
            "complete": cc.status == "complete",
        }

    def recommend(self, run_id: str | None = None, url: str | None = None, limit: int = 10) -> dict:
        """Deduped recommendations for a prior run_id, or a fresh audit of `url`."""
        if run_id and run_id in self._cache:
            scan = self._cache[run_id][2]
        elif url:
            payload = self._client.run_pagespeed(url, "mobile")
            check_runtime_error(payload)
            scan = assemble(payload, self._registry, "mobile")
        else:
            raise ValueError("recommend requires a known run_id or a url")
        return _recommend(scan, limit=limit)

    def _remember(self, run_id, idn, strategy, scan) -> None:
        self._cache[run_id] = (idn, strategy, scan)
        while len(self._cache) > 32:
            self._cache.popitem(last=False)
