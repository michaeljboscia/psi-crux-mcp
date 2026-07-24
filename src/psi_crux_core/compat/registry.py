"""
Compat registry — the SINGLE authority on audit-ID → canonical_key. FEAT-010, REQ-COMPAT-001/002/010.
Parsers NEVER hardcode audit-ID lists; they ask the registry. An unmapped/unknown audit becomes
`unknown:<source_audit_id>` (never dropped silently — REQ-COMPAT-010) and raises a compat warning.
Data ships as package data (data/registry.json), CalVer-versioned, updatable without a code release.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources


@dataclass(frozen=True)
class AuditMapping:
    source_audit_id: str
    canonical_key: str            # "unknown:<id>" if unmapped
    status: str                   # primary | conditional | legacy_fallback | removed | unknown
    details_type: str | None = None
    known: bool = True


class CompatRegistry:
    def __init__(self, data: dict) -> None:
        self.version: str = data.get("registry_version", "unknown")
        self.lighthouse_version: str = data.get("lighthouse_version", "unknown")
        self._audits: dict[str, dict] = data.get("audits", {})

    @classmethod
    def load(cls) -> "CompatRegistry":
        """Load the bundled registry.json (override path support lands with COMPAT-007 config)."""
        raw = resources.files("psi_crux_core.data").joinpath("registry.json").read_text()
        return cls(json.loads(raw))

    def resolve(self, audit_id: str) -> AuditMapping:
        """Map an audit ID to its canonical key. Unknown → 'unknown:<id>' (REQ-COMPAT-010)."""
        entry = self._audits.get(audit_id)
        if entry is None:
            return AuditMapping(
                source_audit_id=audit_id, canonical_key=f"unknown:{audit_id}",
                status="unknown", known=False,
            )
        return AuditMapping(
            source_audit_id=audit_id,
            canonical_key=entry.get("canonical_key") or f"unknown:{audit_id}",
            status=entry.get("status", "unknown"),
            details_type=entry.get("details_type"),
        )

    def primary_insight_ids(self) -> list[str]:
        """Insight audit IDs the registry marks primary/conditional (for the insight parser)."""
        return [
            aid for aid, e in self._audits.items()
            if aid.endswith("-insight") and e.get("status") in ("primary", "conditional")
        ]

    def ids_with_role(self, role: str) -> list[str]:
        """
        Audit IDs tagged with a parser role ("diagnostic", "opportunity"). Parsers ask for a
        role instead of carrying their own ID list, so an LH version bump is a registry-data
        change (CalVer) rather than a code release (REQ-COMPAT-001).
        """
        return [aid for aid, e in self._audits.items() if e.get("role") == role]
