"""
CruxService — the core capability behind the `crux_query` tool. FEAT-002.
Pure core: no MCP/Prefect imports (REQ-CORE-001). Both the MCP server and Prefect flows call this.
Returns a ToolResult (dual-content) or raises a typed error the wrapper maps to the envelope.
"""
from __future__ import annotations

from .artifact import ArtifactStore, new_run_id
from .config import Config
from .crux_client import CruxClient
from .keyring import Keyring
from .logging import get_logger, register_secret
from .models import ToolResult
from .parsers.crux_current import parse_crux_current
from .parsers.crux_history import parse_crux_history
from .projection import project_crux_current
from .stats import mann_kendall

_log = get_logger("crux_service")


class CruxService:
    def __init__(self, config: Config) -> None:
        keys = config.crux_api_keys or config.psi_api_keys  # same key serves both APIs
        for pair in keys:
            register_secret(pair.split(":", 1)[0])
        self._keyring = Keyring.from_pairs(keys)
        self._client = CruxClient(self._keyring, timeout_s=config.crux_timeout_s)
        self._artifacts = ArtifactStore(config.artifact_root)
        self._secrets = tuple(p.split(":", 1)[0] for p in keys)

    def query_current(self, target: str, form_factor: str = "PHONE") -> ToolResult:
        """crux_query(mode=current) for one origin/url. Stateless field data (REQ-CRUX-001)."""
        run_id = new_run_id()
        raw = self._client.query_record(target, form_factor)
        if raw is None:
            result = parse_crux_current({}, target, form_factor)
            result.has_data = False
        else:
            result = parse_crux_current(raw, target, form_factor)
        markdown, data = project_crux_current(result)
        self._artifacts.write(run_id, raw or {"note": "no crux data"}, data, self._secrets)
        _log.info("crux_current_ok", run_id=run_id, target=target, has_data=result.has_data)
        return ToolResult(run_id=run_id, content_markdown=markdown, data=data)

    def query_history(self, origin: str, form_factor: str = "PHONE") -> ToolResult:
        """crux_query(mode=history) — up to 40 windows of p75 timeseries. Stateless (REQ-CRUX-002)."""
        run_id = new_run_id()
        raw = self._client.query_history(origin, form_factor)
        if raw is None:
            md = f"**{origin}** ({form_factor}): insufficient CrUX traffic — no history."
            return ToolResult(run_id=run_id, content_markdown=md,
                              data={"origin": origin, "has_data": False})
        hist = parse_crux_history(raw)
        md = [f"**CrUX history — {origin}** ({form_factor}, {hist['n_periods']} windows)"]
        for name, series in hist["metrics"].items():
            pts = [v for v in series if v is not None]
            if pts:
                md.append(f"- `{name}`: {pts[0]:.0f} → {pts[-1]:.0f} (p75, {len(pts)} pts)")
        return ToolResult(run_id=run_id, content_markdown="\n".join(md),
                          data={"origin": origin, "has_data": True, **hist})

    def query_trend(self, origin: str, form_factor: str = "PHONE") -> ToolResult:
        """crux_query(mode=trend) — Mann-Kendall trend per metric (REQ-CRUX-009/010; no averaged p75s)."""
        run_id = new_run_id()
        raw = self._client.query_history(origin, form_factor)
        if raw is None:
            return ToolResult(run_id=run_id,
                              content_markdown=f"**{origin}**: insufficient CrUX traffic — no trend.",
                              data={"origin": origin, "has_data": False})
        hist = parse_crux_history(raw)
        trends, md = {}, [f"**CrUX trend — {origin}** ({form_factor}, Mann-Kendall)"]
        for name, series in hist["metrics"].items():
            t = mann_kendall(series)
            trends[name] = {"direction": t.direction, "s": t.s_statistic, "n": t.n, "delta": t.delta}
            if t.direction != "insufficient":
                md.append(f"- `{name}`: **{t.direction}** (Δ={t.delta:+.0f}, n={t.n})")
        return ToolResult(run_id=run_id, content_markdown="\n".join(md),
                          data={"origin": origin, "has_data": True, "trends": trends})
