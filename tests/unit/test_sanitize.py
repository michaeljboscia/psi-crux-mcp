"""Redaction tests — shared by fixtures + artifact store. REQ-CONSTRAINT-002, REQ-ART-004."""
from psi_crux_core.sanitize import sanitize


def test_strips_query_params_from_urls():
    data = {"url": "https://cdn.example.com/app.js?token=SECRET123&v=2"}
    out = sanitize(data)
    assert "SECRET123" not in str(out)
    assert out["url"] == "https://cdn.example.com/app.js"


def test_redacts_seeded_key_anywhere():
    key = "AIzaSyFAKEKEY_do_not_use_1234567890"
    data = {"note": f"called with key {key}"}
    out = sanitize(data, secrets=(key,))
    assert key not in str(out)
    assert "[REDACTED]" in out["note"]


def test_strips_base64_image_blobs():
    data = {"final-screenshot": {"data": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAA"}}
    out = sanitize(data)
    assert "9j/4AAQ" not in str(out)


def test_redacts_credential_keys():
    out = sanitize({"api_key": "live-key", "session_id": "abc"})
    assert out["api_key"] == "[REDACTED]"
    assert out["session_id"] == "[REDACTED]"
