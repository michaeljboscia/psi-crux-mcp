"""
Structured logging with API-key redaction. FEAT-022, REQ-ENG-002, REQ-CONSTRAINT-002.
Keys registered here are scrubbed from every rendered log line — a key never reaches a log sink.
"""
from __future__ import annotations

import logging
from typing import Any

import structlog

_SECRETS: set[str] = set()


def register_secret(value: str | None) -> None:
    """Register a secret (API key) to be redacted from all future log output."""
    if value:
        _SECRETS.add(value)


def _redact_processor(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """structlog processor: replace any registered secret substring in event values."""
    for k, v in list(event_dict.items()):
        if isinstance(v, str):
            for s in _SECRETS:
                if s and s in v:
                    event_dict[k] = v.replace(s, "[REDACTED]")
    return event_dict


def configure(level: int = logging.INFO) -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,  # correlation IDs
            _redact_processor,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "psi_crux") -> Any:
    return structlog.get_logger(name)
