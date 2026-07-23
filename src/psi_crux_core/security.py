"""
Target-URL validation. FEAT-013, REQ-SEC-008.
The core never fetches the target itself (only Google's APIs do), but we still refuse to hand
Google — or any future local resolver — an internal/metadata address or a credentialed URL.
Default-deny private/localhost/link-local/metadata; owned staging via allow_private=True.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

_METADATA_HOSTS = {"metadata.google.internal", "metadata"}
_CLOUD_METADATA_IP = ipaddress.ip_address("169.254.169.254")


class TargetBlocked(ValueError):
    """The target URL is not allowed (private/metadata/credentialed/non-http)."""


def validate_target(url: str, allow_private: bool = False) -> str:
    """Return the url if allowed, else raise TargetBlocked. REQ-SEC-008."""
    parts = urlsplit(url if "://" in url else "https://" + url)
    if parts.scheme not in ("http", "https"):
        raise TargetBlocked(f"scheme '{parts.scheme}' not allowed (http/https only)")
    if parts.username or parts.password:
        raise TargetBlocked("credentials in URL are not allowed")
    host = parts.hostname
    if not host:
        raise TargetBlocked("no host in URL")
    if allow_private:
        return url
    if host.lower() in _METADATA_HOSTS or host.lower() == "localhost":
        raise TargetBlocked(f"blocked host '{host}'")
    for ip in _resolve(host):
        if ip == _CLOUD_METADATA_IP:
            raise TargetBlocked("cloud metadata IP blocked")
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise TargetBlocked(f"non-public address blocked ({ip})")
    return url


def _resolve(host: str) -> list[ipaddress._BaseAddress]:
    """Resolve host → IPs. If it's already an IP literal, use it directly; DNS failures don't block."""
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
        return [ipaddress.ip_address(i[4][0]) for i in infos]
    except (socket.gaierror, ValueError):
        return []   # unresolvable → let Google's fetch surface the error; not our SSRF concern
