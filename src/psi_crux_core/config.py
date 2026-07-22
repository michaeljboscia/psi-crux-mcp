"""
Config resolution — precedence CLI > env > TOML > defaults. FEAT-023, REQ-CFG-001, D-14.
Env is canonical; an optional TOML (written by `psi-crux init`) fills gaps. Secrets from env only.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import platformdirs

APP = "psi-crux-mcp"


def _cache_root() -> Path:
    return Path(platformdirs.user_cache_dir(APP))


def _config_toml() -> dict:
    p = Path(platformdirs.user_config_dir(APP)) / "config.toml"
    if p.is_file():
        try:
            return tomllib.loads(p.read_text())
        except (OSError, tomllib.TOMLDecodeError):
            return {}
    return {}


@dataclass
class Config:
    psi_api_keys: list[str] = field(default_factory=list)   # "key:project_id" pairs
    crux_api_keys: list[str] = field(default_factory=list)
    concurrency: int = 8                                    # per-process/IP (REQ-ENG-003)
    cache_ttl_s: int = 300
    crux_timeout_s: float = 30.0
    psi_timeout_s: float = 90.0
    artifact_root: Path = field(default_factory=_cache_root)
    telemetry_backend: str = "none"                          # posthog|otlp|none (REQ-OBS-003)

    @classmethod
    def resolve(cls, overrides: dict | None = None) -> "Config":
        """env > TOML > defaults, then explicit CLI overrides on top."""
        toml = _config_toml()
        cfg = cls()

        def pick(env_name: str, toml_key: str, default):
            if env_name in os.environ:
                return os.environ[env_name]
            return toml.get(toml_key, default)

        raw_psi = pick("PSI_API_KEYS", "psi_api_keys", "")
        raw_crux = pick("CRUX_API_KEYS", "crux_api_keys", "")
        cfg.psi_api_keys = [k.strip() for k in str(raw_psi).split(",") if k.strip()]
        cfg.crux_api_keys = [k.strip() for k in str(raw_crux).split(",") if k.strip()]
        cfg.concurrency = int(pick("PSI_CRUX_CONCURRENCY", "concurrency", 8))
        cfg.cache_ttl_s = int(pick("PSI_CRUX_CACHE_TTL", "cache_ttl_s", 300))
        cfg.telemetry_backend = str(pick("PSI_CRUX_TELEMETRY", "telemetry_backend", "none"))
        root = pick("PSI_CRUX_ARTIFACT_ROOT", "artifact_root", None)
        if root:
            cfg.artifact_root = Path(root)

        for k, v in (overrides or {}).items():
            setattr(cfg, k, v)
        return cfg
