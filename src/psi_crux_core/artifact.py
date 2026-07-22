"""
Artifact/run store. FEAT-011, REQ-ART-001..005. Writes a redacted raw payload + structured rows
to a platformdirs cache dir keyed by run_id; exposes read confined to the artifact root (SEC-002).
Walking-skeleton scope: write + confined read. TTL sweep lands with the full store in Phase 3.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from .sanitize import sanitize


def new_run_id() -> str:
    return uuid.uuid4().hex


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def write(self, run_id: str, raw: dict, rows: dict, secrets: tuple[str, ...] = ()) -> Path:
        """Write redacted raw.json + rows.json under runs/<run_id>/. Returns the run dir."""
        d = (self._root / "runs" / run_id).resolve()
        self._confine(d)
        d.mkdir(parents=True, exist_ok=True)
        (d / "raw.json").write_text(json.dumps(sanitize(raw, secrets), separators=(",", ":")))
        (d / "rows.json").write_text(json.dumps(rows, separators=(",", ":")))
        return d

    def read(self, run_id: str, name: str) -> dict | None:
        """Read a named artifact for a run. Path-traversal safe (REQ-SEC-002)."""
        p = (self._root / "runs" / run_id / name).resolve()
        self._confine(p)
        if not p.is_file():
            return None
        return json.loads(p.read_text())

    def _confine(self, p: Path) -> None:
        """Reject any path that escapes the artifact root (resolve + relative_to, not startswith)."""
        try:
            p.resolve().relative_to(self._root)
        except ValueError as e:
            raise PermissionError(f"path escapes artifact root: {p}") from e
