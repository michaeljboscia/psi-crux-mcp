"""
FastMCP server — the primary tool surface. FEAT-001/002/003/007, REQ-MCP-010..019, REQ-DIST-004/006.
Tools are plain `def` (FastMCP threadpools them; D-01). Thin wrappers: each calls psi_crux_core and
returns dual-content {content, structuredContent}, mapping ANY error to the envelope (never a trace).
The 5 job-intent tools are primary; ops is a utility (REQ-MCP-021).
"""
from __future__ import annotations

import logging as _stdlib_logging
from typing import Callable

from fastmcp import FastMCP

from psi_crux_core.config import Config
from psi_crux_core.keyring import QuotaCooldown
from psi_crux_core.logging import configure
from psi_crux_core.models import ErrorEnvelope
from psi_crux_core.parsers.metrics import LabCwvMissing, PsiRuntimeError
from psi_crux_core.psi_audit_service import PsiAuditService
from psi_crux_core.security import TargetBlocked, validate_target
from psi_crux_core.service import CruxService
from psi_crux_core.telemetry import TelemetrySink, emit, get_sink, timed

mcp: FastMCP = FastMCP("psi-crux-mcp")
_crux: CruxService | None = None
_psi: PsiAuditService | None = None
_sink_i: TelemetrySink | None = None


def _sink() -> TelemetrySink:
    global _sink_i
    if _sink_i is None:
        import os
        cfg = Config.resolve()
        _sink_i = get_sink(cfg.telemetry_backend, posthog_key=os.getenv("POSTHOG_PROJECT_API_KEY"))
    return _sink_i


def _crux_svc() -> CruxService:
    global _crux
    if _crux is None:
        _crux = CruxService(Config.resolve())
    return _crux


def _psi_svc() -> PsiAuditService:
    global _psi
    if _psi is None:
        _psi = PsiAuditService(Config.resolve())
    return _psi


def _dual(markdown: str, structured: dict) -> dict:
    return {"content": [{"type": "text", "text": markdown}], "structuredContent": structured}


def _guard(tool: str, fn: Callable[[], dict]) -> dict:
    """Run a tool body; emit telemetry; map any failure to the error envelope (REQ-ERR-001).
    No trace, key, or raw payload ever leaks. Telemetry never blocks/fails the tool (REQ-OBS-006)."""
    t0 = timed()
    try:
        out = fn()
        emit(_sink(), "tool_call", tool=tool, status="ok", duration_ms=int((timed() - t0) * 1000))
        return out
    except TargetBlocked as e:
        env = ErrorEnvelope(code="TARGET_BLOCKED", category="validation", retryable=False,
                            message="That target URL is not allowed.", resolution=str(e)[:200])
    except QuotaCooldown as e:
        emit(_sink(), "quota", tool=tool, retry_after_seconds=e.retry_after_seconds)
        env = ErrorEnvelope(code="QUOTA_COOLDOWN", category="quota", retryable=True,
                            message=f"All API keys are cooling; retry in {e.retry_after_seconds}s.",
                            retry_after_seconds=e.retry_after_seconds,
                            resolution="Wait, or add keys from separate GCP projects.")
    except PsiRuntimeError as e:
        env = ErrorEnvelope(code=e.code, category="upstream", retryable=False,
                            message="PageSpeed could not analyze this URL.",
                            resolution=f"Lighthouse runtimeError: {e.code}. Non-HTML/unreachable URLs "
                                       "(PDFs, 404s, WAF-blocked) cannot be analyzed.")
    except LabCwvMissing as e:
        env = ErrorEnvelope(code="LAB_CWV_MISSING", category="internal", retryable=False,
                            message="Lab Core Web Vitals were missing from the response.",
                            resolution=str(e)[:200])
    except ValueError as e:
        env = ErrorEnvelope(code="VALIDATION", category="validation", retryable=False,
                            message=str(e)[:200])
    except Exception as e:  # noqa: BLE001
        env = ErrorEnvelope(code="INTERNAL", category="internal", retryable=False,
                            message="The tool failed.", resolution=str(e)[:200])
    emit(_sink(), "error", tool=tool, code=env.code)
    return _dual(env.message, env.model_dump(exclude_none=True))


@mcp.tool()
def psi_audit(url: str, strategy: str = "mobile") -> dict:
    """
    Run a full PageSpeed Insights (Lighthouse 13) audit for a URL: scores, Core Web Vitals,
    and the top optimization insights. Results are projected (LLM-sized) and persisted.
    strategy: "mobile" (default) or "desktop".
    """
    def body() -> dict:
        validate_target(url)
        r = _psi_svc().audit(url, strategy)
        return _dual(r["content_markdown"], {"run_id": r["run_id"], **r["data"]})
    return _guard("psi_audit", body)


@mcp.tool()
def recommend(url: str = "", run_id: str = "", limit: int = 10) -> dict:
    """
    Deduplicated, prioritized performance recommendations for a URL (or a prior psi_audit run_id).
    Each maps to a canonical issue with authored fix steps; includes an instruction to synthesize
    the advice against the user's actual codebase.
    """
    def body() -> dict:
        rec = _psi_svc().recommend(run_id=run_id or None, url=url or None, limit=limit)
        lines = [f"**{len(rec['recommendations'])} recommendations** (of {rec['total_findings']} findings)"]
        for r in rec["recommendations"]:
            lines.append(f"- **{r['title']}** (`{r['canonical_key']}`, {r['advice_status']})")
        return _dual("\n".join(lines), rec)
    return _guard("recommend", body)


@mcp.tool()
def crux_query(target: str, mode: str = "current", form_factor: str = "PHONE") -> dict:
    """
    Chrome UX Report real-user field data for an origin/URL. Stateless.
    mode: "current" (latest), "history" (up to 40 windows), or "trend" (Mann-Kendall trend).
    form_factor: PHONE (default), DESKTOP, or TABLET.
    """
    def body() -> dict:
        validate_target(target)
        svc = _crux_svc()
        if mode == "history":
            r = svc.query_history(target, form_factor)
        elif mode == "trend":
            r = svc.query_trend(target, form_factor)
        else:
            r = svc.query_current(target, form_factor)
        return _dual(r.content_markdown, {"run_id": r.run_id, **r.data})
    return _guard("crux_query", body)


@mcp.tool()
def ops(action: str = "keyring_stats") -> dict:
    """Operational utility. action: keyring_stats | compat_status."""
    def body() -> dict:
        if action == "compat_status":
            from psi_crux_core.compat.registry import CompatRegistry
            reg = CompatRegistry.load()
            return _dual(f"compat registry {reg.version} (LH {reg.lighthouse_version})",
                         {"registry_version": reg.version, "lighthouse_version": reg.lighthouse_version})
        stats = _crux_svc()._keyring.stats()  # noqa: SLF001 — ops introspection
        return _dual(f"{len(stats)} key(s) in ring", {"keyring": stats})
    return _guard("ops", body)


def main() -> None:
    """Console entry point `psi-crux-mcp`. stdio by default (REQ-DIST-005)."""
    configure(level=_stdlib_logging.INFO)
    mcp.run()


if __name__ == "__main__":
    main()
