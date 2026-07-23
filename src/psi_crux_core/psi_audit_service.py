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
from .db.repository import Repository
from .keyring import Keyring
from .logging import get_logger, register_secret
from .parsers.metrics import check_runtime_error
from .parsers.summary import PsiScan, assemble, project
from .psi_client import PsiClient
from .recommend import recommend as _recommend
from .url_identity import UrlIdentity

_log = get_logger("psi_audit")


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

    def audit(self, url: str, strategy: str = "mobile") -> dict:
        """Full PSI audit → projected dual-content + persisted 12 tables + completion contract."""
        run_id = new_run_id()
        payload = self._client.run_pagespeed(url, strategy)
        check_runtime_error(payload)                      # PDF/404/timeout → PsiRuntimeError
        scan = assemble(payload, self._registry)
        idn = UrlIdentity.of(url, final_url=scan.core.get("final_url"))
        markdown, data = project(scan, idn.canonical_url)

        self._artifacts.write(run_id, payload, data, self._secrets)
        cc = self._repo.persist_scan(
            run_id, idn, strategy, scan.core, scan.insights.rows, scan.network_rows,
            scan.bp_rows, scan.resource_rows, self._registry.version, [], scan.compat_warnings,
        )
        self._remember(run_id, idn, strategy, scan)
        _log.info("psi_audit_ok", run_id=run_id, status=cc.status, target=idn.canonical_url)
        return {
            "run_id": run_id,
            "content_markdown": markdown + f"\n\n_persisted: {cc.status}_",
            "data": {**data, "completion": {"status": cc.status,
                     "tables_written": cc.tables_written, "tables_failed": cc.tables_failed}},
            "complete": cc.status == "complete",
        }

    def recommend(self, run_id: str | None = None, url: str | None = None, limit: int = 10) -> dict:
        """Deduped recommendations for a prior run_id, or a fresh audit of `url`."""
        if run_id and run_id in self._cache:
            scan = self._cache[run_id][2]
        elif url:
            payload = self._client.run_pagespeed(url, "mobile")
            check_runtime_error(payload)
            scan = assemble(payload, self._registry)
        else:
            raise ValueError("recommend requires a known run_id or a url")
        return _recommend(scan, limit=limit)

    def _remember(self, run_id, idn, strategy, scan) -> None:
        self._cache[run_id] = (idn, strategy, scan)
        while len(self._cache) > 32:
            self._cache.popitem(last=False)
