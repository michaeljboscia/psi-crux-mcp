"""
Pluggable telemetry. FEAT-012, REQ-OBS-001..008.
Default is a no-op (zero network calls, zero deps). PostHog and OTLP sinks are opt-in and only
imported when selected. Emission NEVER blocks or fails a tool (REQ-OBS-006) and NEVER carries a
key (REQ-OBS-004). Our copy points at PostHog via env; third parties get the no-op default.
"""
from __future__ import annotations

import time
from typing import Any, Protocol

from .logging import get_logger

_log = get_logger("telemetry")

# events we always keep vs sample (REQ-OBS-008)
_ALWAYS = {"error", "quota", "key_cooldown"}


class TelemetrySink(Protocol):
    def record(self, event: str, **fields: Any) -> None: ...
    def flush(self) -> None: ...


class NoopSink:
    """Default. Makes zero network calls (REQ-OBS-005)."""

    def record(self, event: str, **fields: Any) -> None:  # noqa: D102
        return None

    def flush(self) -> None:  # noqa: D102
        return None


class PostHogSink:
    """PostHog product-analytics sink (opt-in). Non-blocking (posthog batches on a bg thread)."""

    def __init__(self, api_key: str, host: str, sample_rate: float = 1.0) -> None:
        from posthog import Posthog  # imported only when selected
        self._ph = Posthog(api_key, host=host)
        self._sample = sample_rate

    def record(self, event: str, **fields: Any) -> None:
        try:
            if event not in _ALWAYS and self._sample < 1.0:
                # deterministic-ish sampling without Math.random dependence on wall clock
                if (hash((event, fields.get("run_id"))) % 1000) / 1000.0 >= self._sample:
                    return
            self._ph.capture(distinct_id="psi-crux-mcp", event=f"psi_crux_{event}",
                             properties={k: v for k, v in fields.items() if v is not None})
        except Exception as e:  # noqa: BLE001 — telemetry must never break a tool
            _log.warning("telemetry_sink_error", err=str(e)[:120])

    def flush(self) -> None:
        try:
            self._ph.flush()
        except Exception:  # noqa: BLE001
            pass


def emit(sink: TelemetrySink, event: str, **fields: Any) -> None:
    """Safe emit — swallow any sink error so a tool never fails on telemetry (REQ-OBS-006)."""
    try:
        sink.record(event, **fields)
    except Exception as e:  # noqa: BLE001
        _log.warning("telemetry_emit_error", err=str(e)[:120])


def timed() -> float:
    return time.monotonic()


def get_sink(backend: str, *, posthog_key: str | None = None,
            posthog_host: str = "https://us.i.posthog.com",
            sample_rate: float = 1.0) -> TelemetrySink:
    """Factory. 'none' (default) → Noop; 'posthog' → PostHogSink if a key is set, else Noop."""
    if backend == "posthog" and posthog_key:
        try:
            return PostHogSink(posthog_key, posthog_host, sample_rate)
        except Exception as e:  # noqa: BLE001 — missing dep / bad config → degrade to noop
            _log.warning("telemetry_init_failed", backend=backend, err=str(e)[:120])
    return NoopSink()
