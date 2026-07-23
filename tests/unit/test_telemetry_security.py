"""Telemetry no-op + non-blocking, and SSRF target validation. REQ-OBS-005/006, REQ-SEC-008."""
import pytest

from psi_crux_core.security import TargetBlocked, validate_target
from psi_crux_core.telemetry import NoopSink, emit, get_sink


def test_noop_is_default_and_silent():
    assert isinstance(get_sink("none"), NoopSink)
    assert isinstance(get_sink("posthog", posthog_key=None), NoopSink)   # no key → degrade to noop
    get_sink("none").record("tool_call", tool="x")   # zero network, no raise


def test_emit_swallows_sink_errors():
    class Boom:
        def record(self, *a, **k):
            raise RuntimeError("sink down")
        def flush(self):
            pass
    emit(Boom(), "error", tool="x")   # must NOT raise (REQ-OBS-006)


@pytest.mark.parametrize("bad", [
    "http://localhost/", "https://127.0.0.1/", "https://10.0.0.5/", "https://192.168.1.1/",
    "https://169.254.169.254/", "http://metadata.google.internal/",
    "ftp://example.com/", "https://user:pass@example.com/",
])
def test_blocks_ssrf_and_bad_targets(bad):
    with pytest.raises(TargetBlocked):
        validate_target(bad)


def test_allows_public_and_owned_private_with_flag():
    assert validate_target("https://www.example.com/")
    assert validate_target("https://10.0.0.5/", allow_private=True)   # owned staging opt-in
