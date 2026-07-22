"""
FastMCP server. FEAT-002, REQ-DIST-004/006, REQ-MCP-011/019.
Tools are plain `def` (FastMCP threadpools them; D-01 — never blocking code in async def).
The server is a thin wrapper: it calls psi_crux_core and formats dual-content (REQ-CORE-002).
"""
from __future__ import annotations

import logging as _stdlib_logging

from fastmcp import FastMCP

from psi_crux_core.config import Config
from psi_crux_core.logging import configure
from psi_crux_core.models import ErrorEnvelope
from psi_crux_core.service import CruxService
from psi_crux_core.keyring import QuotaCooldown

mcp: FastMCP = FastMCP("psi-crux-mcp")
_service: CruxService | None = None


def _svc() -> CruxService:
    global _service
    if _service is None:
        _service = CruxService(Config.resolve())
    return _service


@mcp.tool()
def crux_query(target: str, form_factor: str = "PHONE") -> dict:
    """
    Chrome UX Report field data (real-user Core Web Vitals) for an origin or URL.

    Args:
        target: an origin like "https://example.com" or a specific URL.
        form_factor: PHONE (default), DESKTOP, or TABLET.

    Returns a dual-content result: `content` (markdown digest) + `structuredContent` (metrics JSON).
    Stateless — data comes straight from Google (no database required).
    """
    try:
        result = _svc().query_current(target, form_factor)
        return {
            "content": [{"type": "text", "text": result.content_markdown}],
            "structuredContent": {"run_id": result.run_id, **result.data},
        }
    except QuotaCooldown as e:
        env = ErrorEnvelope(
            code="QUOTA_COOLDOWN", category="quota", retryable=True,
            message=f"All API keys are cooling; retry in {e.retry_after_seconds}s.",
            retry_after_seconds=e.retry_after_seconds,
            resolution="Wait for the cooldown, or add more keys from separate GCP projects.",
        )
        return {"content": [{"type": "text", "text": env.message}],
                "structuredContent": env.model_dump(exclude_none=True)}
    except Exception as e:  # noqa: BLE001 — map ANY error to the envelope, never leak a trace
        env = ErrorEnvelope(
            code="INTERNAL", category="internal", retryable=False,
            message="crux_query failed.", resolution=str(e)[:200],
        )
        return {"content": [{"type": "text", "text": env.message}],
                "structuredContent": env.model_dump(exclude_none=True)}


def main() -> None:
    """Console entry point: `psi-crux-mcp`. stdio by default (REQ-DIST-005)."""
    configure(level=_stdlib_logging.INFO)
    mcp.run()


if __name__ == "__main__":
    main()
