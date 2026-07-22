"""
Shared redaction/sanitization — used by BOTH the artifact store and checked-in fixtures.
FEAT-011, REQ-CONSTRAINT-002, REQ-ART-004, A-24.

Strips: known API keys, URL query params on any `url`-like field, and base64 image blobs.
A live PSI response leaks secrets via network-request URLs (?token=), screenshots (base64),
and requestedUrl — this removes them before anything is written or committed.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

_BASE64_IMG = re.compile(r"data:image/[a-zA-Z.+-]+;base64,[A-Za-z0-9+/=]+")
_KEY_KEYS = {"key", "apikey", "api_key", "token", "access_token", "session_id"}


def _strip_query(url: str) -> str:
    """Drop the query string from a URL (it may carry ?token=/?key=)."""
    try:
        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except ValueError:
        return url


def redact_text(text: str, secrets: tuple[str, ...] = ()) -> str:
    """Remove seeded secrets + base64 image blobs from any string."""
    for s in secrets:
        if s:
            text = text.replace(s, "[REDACTED]")
    return _BASE64_IMG.sub("data:image/REDACTED", text)


def sanitize(obj: Any, secrets: tuple[str, ...] = ()) -> Any:
    """
    Recursively sanitize a parsed JSON structure:
      - any string value under a `url`/`requestedUrl`/`finalUrl` key → query stripped
      - any string containing a base64 image blob → blob removed
      - any seeded secret string → [REDACTED]
      - keys whose name implies a credential → value replaced
    """
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            kl = str(k).lower()
            if kl in _KEY_KEYS and isinstance(v, str):
                out[k] = "[REDACTED]"
            elif kl in ("url", "requestedurl", "finalurl", "initial_url") and isinstance(v, str):
                out[k] = redact_text(_strip_query(v), secrets)
            else:
                out[k] = sanitize(v, secrets)
        return out
    if isinstance(obj, list):
        return [sanitize(v, secrets) for v in obj]
    if isinstance(obj, str):
        return redact_text(obj, secrets)
    return obj
