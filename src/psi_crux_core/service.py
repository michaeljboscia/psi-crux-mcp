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
from .projection import project_crux_current

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
