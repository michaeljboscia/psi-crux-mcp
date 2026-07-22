"""
Pydantic models. FEAT-023, REQ-ENG-006. Typed inputs + result envelopes.
The error envelope (REQ-ERR-001) and completion contract (REQ-STATE-001) live here.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class CruxMetric(BaseModel):
    category: str | None = None            # good | needs-improvement | poor
    p75: float | None = None
    good: float | None = None
    ni: float | None = None
    poor: float | None = None


class CruxCurrentResult(BaseModel):
    origin_or_url: str
    form_factor: str | None = None
    metrics: dict[str, CruxMetric] = Field(default_factory=dict)
    has_data: bool = True                  # False → "insufficient CrUX traffic" (REQ-REC-004)


class ErrorEnvelope(BaseModel):
    """REQ-ERR-001 — the single error shape. No stack traces, keys, or raw payloads."""
    ok: Literal[False] = False
    code: str
    message: str
    category: Literal[
        "config", "validation", "upstream", "quota", "timeout", "not_found", "internal"
    ]
    retryable: bool = False
    upstream_status: int | None = None
    retry_after_seconds: int | None = None
    run_id: str | None = None
    resolution: str | None = None


class ToolResult(BaseModel):
    """Dual-content wrapper (REQ-MCP-019). `content` = markdown; `data` = structuredContent."""
    ok: Literal[True] = True
    run_id: str
    content_markdown: str
    data: dict[str, Any]
